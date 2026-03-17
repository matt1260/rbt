"""
Coinbase Advanced Trade API integration for displaying donation wallet balances.
Uses CDP JWT (ES256) authentication — private key stays server-side only.
"""
import secrets
import time

import jwt
import requests
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from django.conf import settings
from django.core.cache import cache
from django.http import JsonResponse
from django.views.decorators.http import require_GET

_CACHE_KEY = "coinbase_balances_v1"
_CACHE_TTL = 300   # 5 minutes
_API_HOST = "api.coinbase.com"
_ACCOUNTS_PATH = "/api/v3/brokerage/accounts"
_BEST_BID_ASK_PATH = "/api/v3/brokerage/best_bid_ask"
_CURRENCIES = {"BTC", "ETH"}
_PRODUCT_IDS = ["BTC-USD", "ETH-USD"]


def _build_jwt(method: str, path: str) -> str:
    raw_key = settings.COINBASE_API_PRIVATE_KEY.replace("\\n", "\n")
    private_key = load_pem_private_key(raw_key.encode(), password=None)
    key_name = settings.COINBASE_API_KEY_NAME
    payload = {
        "sub": key_name,
        "iss": "cdp",
        "nbf": int(time.time()),
        "exp": int(time.time()) + 120,
        "uri": f"{method} {_API_HOST}{path}",
    }
    return jwt.encode(
        payload,
        private_key,
        algorithm="ES256",
        headers={"kid": key_name, "nonce": secrets.token_hex()},
    )


@require_GET
def crypto_balances(request):
    """Return BTC and ETH balances from the Coinbase account (cached 5 min)."""
    cached = cache.get(_CACHE_KEY)
    if cached is not None:
        return JsonResponse(cached)

    try:
        token = _build_jwt("GET", _ACCOUNTS_PATH)
        resp = requests.get(
            f"https://{_API_HOST}{_ACCOUNTS_PATH}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=8,
        )
        resp.raise_for_status()
        accounts = resp.json().get("accounts", [])
        balances = {}
        for acc in accounts:
            currency = acc.get("currency", "")
            if currency in _CURRENCIES:
                val = acc.get("available_balance", {}).get("value", "0")
                balances[currency] = val

        # Fetch mid-market prices for USD conversion
        product_ids_param = "&".join(f"product_ids={p}" for p in _PRODUCT_IDS)
        price_token = _build_jwt("GET", _BEST_BID_ASK_PATH)
        price_resp = requests.get(
            f"https://{_API_HOST}{_BEST_BID_ASK_PATH}?{product_ids_param}",
            headers={"Authorization": f"Bearer {price_token}"},
            timeout=8,
        )
        prices = {}  # e.g. {"BTC": 85000.0, "ETH": 2000.0}
        if price_resp.ok:
            for entry in price_resp.json().get("pricebooks", []):
                pid = entry.get("product_id", "")  # e.g. "BTC-USD"
                currency = pid.split("-")[0]
                try:
                    bid = float(entry["bids"][0]["price"])
                    ask = float(entry["asks"][0]["price"])
                    prices[currency] = (bid + ask) / 2
                except (KeyError, IndexError, ValueError):
                    pass

        total_usd = 0.0
        for currency, amount_str in balances.items():
            try:
                total_usd += float(amount_str) * prices.get(currency, 0.0)
            except (ValueError, TypeError):
                pass

        result = {**balances, "prices": prices, "total_usd": round(total_usd, 2)}
        cache.set(_CACHE_KEY, result, _CACHE_TTL)
        return JsonResponse(result)
    except Exception as exc:
        return JsonResponse({"error": str(exc)}, status=502)
