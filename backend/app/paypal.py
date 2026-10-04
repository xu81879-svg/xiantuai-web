from __future__ import annotations

import os
from typing import Any

import httpx


class PayPalError(RuntimeError):
    pass


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def base_url() -> str:
    return _env("PAYPAL_BASE_URL", "https://api-m.sandbox.paypal.com").rstrip("/")


def configured() -> bool:
    return bool(_env("PAYPAL_CLIENT_ID") and _env("PAYPAL_CLIENT_SECRET"))


def mock_mode() -> bool:
    return _env("PAYPAL_MOCK_MODE", "false").lower() == "true"


def _access_token() -> str:
    if not configured():
        raise PayPalError("PayPal credentials are not configured")
    try:
        response = httpx.post(
            f"{base_url()}/v1/oauth2/token",
            auth=(_env("PAYPAL_CLIENT_ID"), _env("PAYPAL_CLIENT_SECRET")),
            data={"grant_type": "client_credentials"},
            headers={"Accept": "application/json", "Accept-Language": "en_US"},
            timeout=float(_env("PAYPAL_TIMEOUT_SECONDS", "20")),
        )
        response.raise_for_status()
        token = response.json().get("access_token")
        if not token:
            raise PayPalError("PayPal token response did not contain access_token")
        return token
    except (httpx.HTTPError, ValueError) as exc:
        raise PayPalError(f"PayPal authentication failed: {exc}") from exc


def create_order(*, local_order_id: str, plan_name: str, amount: str, currency: str, return_url: str, cancel_url: str) -> dict[str, Any]:
    payload = {
        "intent": "CAPTURE",
        "purchase_units": [{
            "reference_id": local_order_id,
            "custom_id": local_order_id,
            "description": plan_name,
            "amount": {"currency_code": currency, "value": amount},
        }],
        "application_context": {
            "brand_name": _env("PAYPAL_BRAND_NAME", "鲜图 AI"),
            "user_action": "PAY_NOW",
            "return_url": return_url,
            "cancel_url": cancel_url,
            "shipping_preference": "NO_SHIPPING",
        },
    }
    try:
        response = httpx.post(
            f"{base_url()}/v2/checkout/orders",
            headers={"Authorization": f"Bearer {_access_token()}", "Content-Type": "application/json", "Prefer": "return=representation"},
            json=payload,
            timeout=float(_env("PAYPAL_TIMEOUT_SECONDS", "20")),
        )
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise PayPalError(f"PayPal order creation failed: {exc}") from exc


def capture_order(paypal_order_id: str) -> dict[str, Any]:
    try:
        response = httpx.post(
            f"{base_url()}/v2/checkout/orders/{paypal_order_id}/capture",
            headers={"Authorization": f"Bearer {_access_token()}", "Content-Type": "application/json", "Prefer": "return=representation"},
            json={},
            timeout=float(_env("PAYPAL_TIMEOUT_SECONDS", "30")),
        )
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise PayPalError(f"PayPal order capture failed: {exc}") from exc


def approval_url(order: dict[str, Any]) -> str | None:
    for link in order.get("links", []):
        if link.get("rel") in {"approve", "payer-action"}:
            return link.get("href")
    return None
