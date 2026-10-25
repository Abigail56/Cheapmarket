import re
import secrets
import uuid
from decimal import Decimal

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import CartOwner
from app.core.config import settings
from app.core.exceptions import BadRequest, NotFound
from app.models.cart import Cart, CartItem
from app.models.product import Product
from app.schemas.cart import CartItemRead, CartRead
from app.schemas.catalog import ProductRead
from app.utils.money import q2

SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")


async def find_cart(session: AsyncSession, owner: CartOwner) -> Cart | None:
    if owner.user:
        stmt = select(Cart).where(Cart.user_id == owner.user.id)
    elif owner.session_id:
        stmt = select(Cart).where(Cart.session_id == owner.session_id)
    else:
        return None
    return (await session.exec(stmt)).first()


async def get_or_create_cart(session: AsyncSession, owner: CartOwner) -> Cart:
    cart = await find_cart(session, owner)
    if cart:
        return cart
    if owner.user:
        cart = Cart(user_id=owner.user.id)
    else:
        sid = owner.session_id if owner.session_id and SESSION_RE.match(owner.session_id) else None
        cart = Cart(session_id=sid or secrets.token_urlsafe(24))
    session.add(cart)
    await session.commit()
    await session.refresh(cart)
    return cart


def to_read(cart: Cart | None, notices: list[str] | None = None) -> CartRead:
    items: list[CartItemRead] = []
    subtotal = Decimal(0)
    count = 0
    for it in (cart.items if cart else []):
        line = q2(it.product.price * it.quantity)
        subtotal += line
        count += it.quantity
        items.append(CartItemRead(product=ProductRead.model_validate(it.product),
                                  quantity=it.quantity, line_total=line))
    return CartRead(
        session_id=cart.session_id if cart else None,
        items=items, item_count=count, subtotal=q2(subtotal), notices=notices or [],
    )


async def _product(session: AsyncSession, product_id: uuid.UUID) -> Product:
    product = await session.get(Product, product_id)
    if not product or not product.is_active:
        raise NotFound("Product not found")
    return product


async def add_item(session: AsyncSession, cart: Cart, product_id: uuid.UUID, qty: int) -> None:
    product = await _product(session, product_id)
    item = next((i for i in cart.items if i.product_id == product_id), None)
    new_qty = (item.quantity if item else 0) + qty
    _check_qty(product, new_qty)
    if item:
        item.quantity = new_qty
        session.add(item)
    else:
        session.add(CartItem(cart_id=cart.id, product_id=product_id, quantity=new_qty))
    await session.commit()


async def set_item(session: AsyncSession, cart: Cart, product_id: uuid.UUID, qty: int) -> None:
    item = next((i for i in cart.items if i.product_id == product_id), None)
    if not item:
        raise NotFound("Item is not in the cart")
    if qty == 0:
        await session.delete(item)
    else:
        _check_qty(await _product(session, product_id), qty)
        item.quantity = qty
        session.add(item)
    await session.commit()


async def clear(session: AsyncSession, cart: Cart) -> None:
    for item in list(cart.items):
        await session.delete(item)
    await session.commit()


def _check_qty(product: Product, qty: int) -> None:
    if qty > settings.MAX_CART_ITEM_QTY:
        raise BadRequest(f"You can order at most {settings.MAX_CART_ITEM_QTY} of one item")
    if product.stock_qty < qty:
        raise BadRequest(
            f"Only {product.stock_qty} of '{product.name}' left in stock", code="insufficient_stock"
        )


async def merge_guest_cart(session: AsyncSession, user_cart: Cart, guest_session_id: str) -> list[str]:
    """After login: move guest items into the user's cart, capped at available stock."""
    guest = (await session.exec(select(Cart).where(Cart.session_id == guest_session_id))).first()
    notices: list[str] = []
    if not guest or guest.id == user_cart.id:
        return notices
    for g in list(guest.items):
        product = g.product
        if not product.is_active or product.stock_qty <= 0:
            notices.append(f"'{product.name}' is no longer available")
            continue
        mine = next((i for i in user_cart.items if i.product_id == g.product_id), None)
        wanted = min((mine.quantity if mine else 0) + g.quantity,
                     settings.MAX_CART_ITEM_QTY, product.stock_qty)
        if wanted < (mine.quantity if mine else 0) + g.quantity:
            notices.append(f"Quantity of '{product.name}' reduced to {wanted} (stock limit)")
        if mine:
            mine.quantity = wanted
            session.add(mine)
        else:
            session.add(CartItem(cart_id=user_cart.id, product_id=g.product_id, quantity=wanted))
    await session.delete(guest)
    await session.commit()
    return notices
