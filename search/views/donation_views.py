"""
Last-30-day donation totals from PayPal + crypto blockchains.
Aggregates PayPal Transaction Search API, mempool.space (BTC), and Etherscan (ETH).
"""
import logging
import time
from datetime import datetime, timedelta, timezone

import requests
from django.conf import settings
from django.core.cache import cache
from django.http import JsonResponse
from django.views.decorators.http import require_GET

logger = logging.getLogger(__name__)

_CACHE_KEY = "donation_totals_v1"
_CACHE_TTL = 3600  # 1 hour

_BTC_ADDRESS = "3QDFmrY14HoQbnDNk5GBey4NQUg9ZLpggc"
_ETH_ADDRESS = "0x8DA15DC1f2b01BD6D270cEA4bf99A78c3DE0C50F"


# ---------------------------------------------------------------------------
# PayPal
# ---------------------------------------------------------------------------

def _paypal_access_token():
    """Get a PayPal OAuth2 access token using client credentials."""
    resp = requests.post(
        "https://api-m.paypal.com/v1/oauth2/token",
        auth=(settings.PAYPAL_CLIENT_ID, settings.PAYPAL_CLIENT_SECRET),
        data={"grant_type": "client_credentials"},
        headers={"Accept": "application/json"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _paypal_donations_last_30_days():
    """Sum of completed PayPal donations in the last 30 days (USD)."""
    if not settings.PAYPAL_CLIENT_ID or not settings.PAYPAL_CLIENT_SECRET:
        return 0.0

    token = _paypal_access_token()
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=30)

    total = 0.0
    page = 1
    while True:
        resp = requests.get(
            "https://api-m.paypal.com/v1/reporting/transactions",
            params={
                "start_date": start.strftime("%Y-%m-%dT%H:%M:%S+0000"),
                "end_date": now.strftime("%Y-%m-%dT%H:%M:%S+0000"),
                "transaction_status": "S",
                "fields": "transaction_info",
                "page_size": 500,
                "page": page,
            },
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        for txn in data.get("transaction_details", []):
            info = txn.get("transaction_info", {})
            amount = info.get("transaction_amount", {})
            try:
                val = float(amount.get("value", 0))
                if val > 0:  # only count incoming (positive) amounts
                    total += val
            except (ValueError, TypeError):
                pass

        if page >= data.get("total_pages", 1):
            break
        page += 1

    return round(total, 2)


# ---------------------------------------------------------------------------
# BTC via mempool.space
# ---------------------------------------------------------------------------

def _btc_donations_last_30_days():
    """Incoming BTC to the donation address in the last 30 days."""
    cutoff = time.time() - (30 * 86400)
    total_sats = 0

    resp = requests.get(
        f"https://mempool.space/api/address/{_BTC_ADDRESS}/txs",
        timeout=10,
    )
    if not resp.ok:
        return 0.0

    txs = resp.json()
    for tx in txs:
        status = tx.get("status", {})
        block_time = status.get("block_time", 0)
        if not block_time or block_time < cutoff:
            continue

        # Skip outgoing transactions (our address in inputs)
        is_outgoing = any(
            vin.get("prevout", {}).get("scriptpubkey_address", "") == _BTC_ADDRESS
            for vin in tx.get("vin", [])
        )
        if is_outgoing:
            continue

        # Sum outputs sent to our address
        for vout in tx.get("vout", []):
            if vout.get("scriptpubkey_address", "") == _BTC_ADDRESS:
                total_sats += vout.get("value", 0)

    return total_sats / 1e8  # satoshis → BTC


# ---------------------------------------------------------------------------
# ETH via Etherscan (public, no key required for light usage)
# ---------------------------------------------------------------------------

def _eth_donations_last_30_days():
    """Incoming ETH to the donation address in the last 30 days."""
    cutoff = int(time.time()) - (30 * 86400)
    total_wei = 0

    resp = requests.get(
        "https://api.etherscan.io/api",
        params={
            "module": "account",
            "action": "txlist",
            "address": _ETH_ADDRESS,
            "sort": "desc",
            "page": 1,
            "offset": 100,
        },
        timeout=10,
    )
    if not resp.ok:
        return 0.0

    data = resp.json()
    for tx in data.get("result", []):
        if not isinstance(tx, dict):
            continue
        ts = int(tx.get("timeStamp", 0))
        if ts < cutoff:
            continue
        if (
            tx.get("to", "").lower() == _ETH_ADDRESS.lower()
            and tx.get("isError", "1") == "0"
        ):
            try:
                total_wei += int(tx.get("value", 0))
            except (ValueError, TypeError):
                pass

    return total_wei / 1e18  # wei → ETH


# ---------------------------------------------------------------------------
# Combined endpoint
# ---------------------------------------------------------------------------

@require_GET
def donation_totals(request):
    """Return last-30-day donation totals from PayPal + crypto (cached 1 hour)."""
    cached = cache.get(_CACHE_KEY)
    if cached is not None:
        return JsonResponse(cached)

    result = {
        "paypal_usd": 0.0,
        "btc": 0.0,
        "eth": 0.0,
        "btc_usd": 0.0,
        "eth_usd": 0.0,
        "total_usd": 0.0,
    }

    # PayPal
    try:
        result["paypal_usd"] = _paypal_donations_last_30_days()
    except Exception:
        logger.exception("Failed to fetch PayPal donations")

    # BTC
    try:
        result["btc"] = _btc_donations_last_30_days()
    except Exception:
        logger.exception("Failed to fetch BTC donations")

    # ETH
    try:
        result["eth"] = _eth_donations_last_30_days()
    except Exception:
        logger.exception("Failed to fetch ETH donations")

    # Convert crypto to USD using Coinbase prices (reuse cached prices if available)
    prices = {}
    prices_cache = cache.get("coinbase_balances_v1")
    if prices_cache:
        prices = prices_cache.get("prices", {})

    if not prices:
        try:
            from .crypto_views import (
                _API_HOST,
                _BEST_BID_ASK_PATH,
                _PRODUCT_IDS,
                _build_jwt,
            )

            product_ids_param = "&".join(
                f"product_ids={p}" for p in _PRODUCT_IDS
            )
            price_token = _build_jwt("GET", _BEST_BID_ASK_PATH)
            price_resp = requests.get(
                f"https://{_API_HOST}{_BEST_BID_ASK_PATH}?{product_ids_param}",
                headers={"Authorization": f"Bearer {price_token}"},
                timeout=8,
            )
            if price_resp.ok:
                for entry in price_resp.json().get("pricebooks", []):
                    pid = entry.get("product_id", "")
                    currency = pid.split("-")[0]
                    try:
                        bid = float(entry["bids"][0]["price"])
                        ask = float(entry["asks"][0]["price"])
                        prices[currency] = (bid + ask) / 2
                    except (KeyError, IndexError, ValueError):
                        pass
        except Exception:
            logger.exception("Failed to fetch crypto prices for donation totals")

    result["btc_usd"] = round(result["btc"] * prices.get("BTC", 0), 2)
    result["eth_usd"] = round(result["eth"] * prices.get("ETH", 0), 2)
    result["total_usd"] = round(
        result["paypal_usd"] + result["btc_usd"] + result["eth_usd"], 2
    )

    cache.set(_CACHE_KEY, result, _CACHE_TTL)
    return JsonResponse(result)
