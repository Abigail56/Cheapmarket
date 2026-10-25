"""Thin wrappers over the payment gateways' HTTP APIs.
Kept separate so tests can replace them and no real network calls are made."""
import hashlib
import hmac
from decimal import Decimal

import httpx

from app.core.config import settings
from app.core.exceptions import AppError, BadRequest


class PaymentGatewayError(AppError):
    status_code, code = 502, "gateway_error"


def _kobo(amount: Decimal) -> int:
    return int((amount * 100).to_integral_value())


# --------------------------------- Paystack -----------------------------------
def _paystack_headers() -> dict:
    if not settings.PAYSTACK_SECRET_KEY:
        raise BadRequest("Paystack is not configured", code="provider_not_configured")
    return {"Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}"}


async def paystack_initialize(*, email: str, amount: Decimal, reference: str,
                              callback_url: str, order_number: str) -> dict:
    body = {"email": email, "amount": _kobo(amount), "reference": reference,
            "currency": settings.CURRENCY, "callback_url": callback_url,
            "metadata": {"order_number": order_number}}
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(f"{settings.PAYSTACK_BASE_URL}/transaction/initialize",
                         json=body, headers=_paystack_headers())
    data = r.json()
    if r.status_code != 200 or not data.get("status"):
        raise PaymentGatewayError("Could not start the payment. Please try again.")
    return {"authorization_url": data["data"]["authorization_url"], "reference": reference}


async def paystack_verify(reference: str) -> dict:
    """Returns {'success': bool, 'amount_kobo': int, 'raw': dict}"""
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get(f"{settings.PAYSTACK_BASE_URL}/transaction/verify/{reference}",
                        headers=_paystack_headers())
    data = r.json()
    if r.status_code != 200 or not data.get("status"):
        raise PaymentGatewayError("Could not verify the payment right now.")
    tx = data["data"]
    return {"success": tx.get("status") == "success", "amount_kobo": int(tx.get("amount", 0)),
            "raw": tx}


def paystack_signature_ok(raw_body: bytes, signature: str | None) -> bool:
    if not settings.PAYSTACK_SECRET_KEY or not signature:
        return False
    expected = hmac.new(settings.PAYSTACK_SECRET_KEY.encode(), raw_body, hashlib.sha512).hexdigest()
    return hmac.compare_digest(expected, signature)


# -------------------------------- Flutterwave ---------------------------------
def _flw_headers() -> dict:
    if not settings.FLUTTERWAVE_SECRET_KEY:
        raise BadRequest("Flutterwave is not configured", code="provider_not_configured")
    return {"Authorization": f"Bearer {settings.FLUTTERWAVE_SECRET_KEY}"}


async def flutterwave_initialize(*, email: str, name: str, phone: str, amount: Decimal,
                                 reference: str, redirect_url: str) -> dict:
    body = {"tx_ref": reference, "amount": str(amount), "currency": settings.CURRENCY,
            "redirect_url": redirect_url,
            "customer": {"email": email, "name": name, "phonenumber": phone}}
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(f"{settings.FLUTTERWAVE_BASE_URL}/payments", json=body,
                         headers=_flw_headers())
    data = r.json()
    if r.status_code != 200 or data.get("status") != "success":
        raise PaymentGatewayError("Could not start the payment. Please try again.")
    return {"authorization_url": data["data"]["link"], "reference": reference}


async def flutterwave_verify(reference: str) -> dict:
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get(f"{settings.FLUTTERWAVE_BASE_URL}/transactions/verify_by_reference",
                        params={"tx_ref": reference}, headers=_flw_headers())
    data = r.json()
    if r.status_code != 200 or data.get("status") != "success":
        raise PaymentGatewayError("Could not verify the payment right now.")
    tx = data["data"]
    amount = Decimal(str(tx.get("amount", 0)))
    return {"success": tx.get("status") == "successful"
                       and tx.get("currency") == settings.CURRENCY,
            "amount_kobo": _kobo(amount), "raw": tx}


def flutterwave_hash_ok(header_value: str | None) -> bool:
    if not settings.FLUTTERWAVE_SECRET_HASH or not header_value:
        return False
    return hmac.compare_digest(settings.FLUTTERWAVE_SECRET_HASH, header_value)
