"""
PayPal Orders V2 API integration for Apple Pay donations.
Server-side endpoints to create and capture orders.
The PayPal client secret never leaves the server.
"""
import json
import logging
import os

import requests
from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.http import require_POST

logger = logging.getLogger(__name__)

_SANDBOX = os.environ.get('PAYPAL_SANDBOX', 'False').lower() in ('true', '1', 'yes')
_PAYPAL_API_BASE = "https://api-m.sandbox.paypal.com" if _SANDBOX else "https://api-m.paypal.com"

_MAX_DONATION_USD = 10_000


def _get_paypal_token():
    """Exchange client credentials for a short-lived PayPal access token."""
    resp = requests.post(
        f"{_PAYPAL_API_BASE}/v1/oauth2/token",
        data={"grant_type": "client_credentials"},
        auth=(settings.PAYPAL_CLIENT_ID, settings.PAYPAL_CLIENT_SECRET),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


@require_POST
def paypal_create_order(request):
    """
    POST /api/paypal/orders/
    Body (JSON): { "amount": "5.00" }   (optional, defaults to "5.00")
    Returns the PayPal order object (id, status, …).
    """
    try:
        body = json.loads(request.body) if request.body else {}
        amount_raw = body.get("amount", "5.00")
        amount_float = float(amount_raw)
        if amount_float <= 0 or amount_float > _MAX_DONATION_USD:
            return JsonResponse({"error": "Amount out of range"}, status=400)
        amount = f"{amount_float:.2f}"
    except (ValueError, TypeError, json.JSONDecodeError):
        return JsonResponse({"error": "Invalid request body"}, status=400)

    if not settings.PAYPAL_CLIENT_ID or not settings.PAYPAL_CLIENT_SECRET:
        logger.error("PayPal credentials not configured")
        return JsonResponse({"error": "Payment not configured"}, status=503)

    try:
        token = _get_paypal_token()
        resp = requests.post(
            f"{_PAYPAL_API_BASE}/v2/checkout/orders",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={
                "intent": "CAPTURE",
                "purchase_units": [
                    {
                        "amount": {
                            "currency_code": "USD",
                            "value": amount,
                        },
                        "description": "Real Bible Translation Project Donation",
                    }
                ],
            },
            timeout=15,
        )
        resp.raise_for_status()
        return JsonResponse(resp.json())
    except requests.HTTPError as exc:
        logger.error("PayPal create order HTTP error: %s – %s", exc, exc.response.text if exc.response else "")
        return JsonResponse({"error": "PayPal order creation failed"}, status=502)
    except Exception as exc:
        logger.error("PayPal create order error: %s", exc)
        return JsonResponse({"error": "Payment service unavailable"}, status=502)


@require_POST
def paypal_capture_order(request, order_id):
    """
    POST /api/paypal/orders/<order_id>/capture/
    Captures the approved PayPal order after Apple Pay authorization.
    """
    # Sanitise the order ID: PayPal IDs are alphanumeric, ≤ 20 chars
    if not order_id or not order_id.replace("-", "").isalnum() or len(order_id) > 50:
        return JsonResponse({"error": "Invalid order ID"}, status=400)

    if not settings.PAYPAL_CLIENT_ID or not settings.PAYPAL_CLIENT_SECRET:
        logger.error("PayPal credentials not configured")
        return JsonResponse({"error": "Payment not configured"}, status=503)

    try:
        token = _get_paypal_token()
        resp = requests.post(
            f"{_PAYPAL_API_BASE}/v2/checkout/orders/{order_id}/capture",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            timeout=15,
        )
        resp.raise_for_status()
        return JsonResponse(resp.json())
    except requests.HTTPError as exc:
        logger.error("PayPal capture HTTP error: %s – %s", exc, exc.response.text if exc.response else "")
        return JsonResponse({"error": "PayPal capture failed"}, status=502)
    except Exception as exc:
        logger.error("PayPal capture error: %s", exc)
        return JsonResponse({"error": "Payment service unavailable"}, status=502)
