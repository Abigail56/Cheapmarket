import uuid

from fastapi import APIRouter, Response

from app.api.deps import CartOwner, CartOwnerDep, CurrentUser, SessionDep
from app.schemas.cart import CartItemAdd, CartItemSet, CartMerge, CartRead
from app.services import cart_service

router = APIRouter(prefix="/cart", tags=["CART"])


def _expose(response: Response, cart) -> None:
    if cart and cart.session_id:
        response.headers["X-Cart-Session"] = cart.session_id


@router.get("", response_model=CartRead)
async def get_cart(owner: CartOwnerDep, session: SessionDep, response: Response):
    cart = await cart_service.find_cart(session, owner)
    _expose(response, cart)
    return cart_service.to_read(cart)


@router.post("/items", response_model=CartRead)
async def add_item(data: CartItemAdd, owner: CartOwnerDep, session: SessionDep, response: Response):
    """Creates the cart on first use. Guests: store the returned session_id and
    send it back as the X-Cart-Session header."""
    cart = await cart_service.get_or_create_cart(session, owner)
    await cart_service.add_item(session, cart, data.product_id, data.quantity)
    await session.refresh(cart)
    _expose(response, cart)
    return cart_service.to_read(cart)


@router.put("/items/{product_id}", response_model=CartRead)
async def set_item(
    product_id: uuid.UUID, data: CartItemSet, owner: CartOwnerDep, session: SessionDep,
    response: Response,
):
    cart = await cart_service.get_or_create_cart(session, owner)
    await cart_service.set_item(session, cart, product_id, data.quantity)
    await session.refresh(cart)
    _expose(response, cart)
    return cart_service.to_read(cart)


@router.delete("/items/{product_id}", response_model=CartRead)
async def remove_item(
    product_id: uuid.UUID, owner: CartOwnerDep, session: SessionDep, response: Response
):
    cart = await cart_service.get_or_create_cart(session, owner)
    await cart_service.set_item(session, cart, product_id, 0)
    await session.refresh(cart)
    _expose(response, cart)
    return cart_service.to_read(cart)


@router.delete("", response_model=CartRead)
async def clear_cart(owner: CartOwnerDep, session: SessionDep, response: Response):
    cart = await cart_service.find_cart(session, owner)
    if cart:
        await cart_service.clear(session, cart)
        await session.refresh(cart)
    _expose(response, cart)
    return cart_service.to_read(cart)


@router.post("/merge", response_model=CartRead)
async def merge_cart(data: CartMerge, user: CurrentUser, session: SessionDep):
    """Call right after login to move the guest cart into the account cart."""
    user_cart = await cart_service.get_or_create_cart(session, CartOwner(user, None))
    notices = await cart_service.merge_guest_cart(session, user_cart, data.session_id)
    await session.refresh(user_cart)
    return cart_service.to_read(user_cart, notices)
