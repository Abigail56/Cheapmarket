from fastapi import APIRouter, Depends, Header, Request

from app.api.deps import OptionalUser, SessionDep, rate_limit
from app.schemas.order import OrderRead
from app.schemas.payment import PaymentInitRequest, PaymentInitResponse
from app.services import order_service, payment_service

router = APIRouter(prefix="/payments", tags=["PAYMENTS"])


@router.post("/initialize", response_model=PaymentInitResponse,
             dependencies=[Depends(rate_limit("pay-init", 20))])
async def initialize_payment(data: PaymentInitRequest, user: OptionalUser, session: SessionDep):
    order = await order_service.get_for_access(session, data.order_number, user, data.phone)
    return await payment_service.initialize(session, order, data.provider)


@router.get("/verify/{reference}", response_model=OrderRead)
async def verify_payment(reference: str, session: SessionDep):
    """Call this when the customer returns from the gateway (the webhook may be slower)."""
    return await payment_service.verify_reference(session, reference)


@router.post("/webhook/paystack", include_in_schema=False)
async def paystack_webhook(
    request: Request, session: SessionDep,
    x_paystack_signature: str | None = Header(default=None),
):
    await payment_service.handle_paystack_webhook(session, await request.body(), x_paystack_signature)
    return {"status": "ok"}


@router.post("/webhook/flutterwave", include_in_schema=False)
async def flutterwave_webhook(
    request: Request, session: SessionDep, verif_hash: str | None = Header(default=None),
):
    await payment_service.handle_flutterwave_webhook(session, await request.body(), verif_hash)
    return {"status": "ok"}


@router.post("/dev/simulate-success/{reference}", response_model=OrderRead, tags=["DEV"])
async def simulate_success(reference: str, session: SessionDep):
    """Local development only: marks a payment successful when no gateway keys are set."""
    return await payment_service.simulate_success(session, reference)
