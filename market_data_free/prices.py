from __future__ import annotations

from datetime import datetime, timezone
import json
import urllib.parse
import urllib.request

BIQUOTE_LATEST = "https://biquote.io/api/latest"
XAUS = "https://xaus.com/api/v1/spot?compact=1"

_SHARED_CACHE = {}


class FreeMarketPriceAdapter:
    def __init__(self, timeout=4, live_ttl_seconds=180, cache_ttl_seconds=900):
        self.timeout = timeout
        self.live_ttl_seconds = live_ttl_seconds
        self.cache_ttl_seconds = cache_ttl_seconds
        self._cache = _SHARED_CACHE

    def _json(self, url):
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "VELMONTAIRE/1.0"},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    def _iso(self, value):
        if not value:
            return None
        try:
            return datetime.fromisoformat(
                str(value).replace("Z", "+00:00")
            ).astimezone(timezone.utc)
        except Exception:
            return None

    def _age(self, value):
        t = self._iso(value)
        if not t:
            return None
        return max(
            0.0,
            (datetime.now(timezone.utc) - t).total_seconds(),
        )

    def _store(self, item):
        cached = dict(item)
        cached["_cached_at"] = datetime.now(timezone.utc).isoformat()
        self._cache[item["symbol"]] = cached
        return dict(item)

    def _cached(self, symbol):
        item = self._cache.get(symbol)
        if not item:
            return None

        cached_at = self._iso(item.get("_cached_at"))
        if not cached_at:
            return None

        cache_age = max(
            0.0,
            (datetime.now(timezone.utc) - cached_at).total_seconds(),
        )

        if cache_age > self.cache_ttl_seconds:
            self._cache.pop(symbol, None)
            return None

        out = {
            k: v for k, v in item.items()
            if not k.startswith("_")
        }
        out["state"] = "CACHED"
        out["cache_age_seconds"] = round(cache_age, 1)
        return out

    def _normalise_biquote_tick(self, symbol, payload):
        try:
            bid = float(payload["bid"])
            ask = float(payload["ask"])

            # BiQuote's actual tick payload exposes an ISO timestamp here.
            ts = payload.get("timestamp") or payload.get("time")
            age = self._age(ts)

            if (
                bid <= 0
                or ask <= 0
                or ask < bid
                or age is None
                or age > self.live_ttl_seconds
            ):
                return None

            return self._store({
                "symbol": symbol,
                "price": float(
                    payload.get("mid") or ((bid + ask) / 2)
                ),
                "bid": bid,
                "ask": ask,
                "time": ts,
                "source": "BiQuote",
                "state": "LIVE",
                "source_age_seconds": round(age, 1),
                "direction": payload.get("direction"),
                "day_change_percent": payload.get("dayDiffPercent"),
                "type": payload.get("type"),
            })
        except Exception:
            return None

    def _biquote_batch(self, symbols):
        if not symbols:
            return {}

        try:
            query = urllib.parse.urlencode(
                [("symbols", symbol) for symbol in symbols]
            )
            raw = self._json(f"{BIQUOTE_LATEST}?{query}")

            # Current /api/latest response is keyed by symbol:
            # {"EURUSD": {...}, "GBPUSD": {...}, ...}
            # Keep a list fallback for forward compatibility.
            payloads = {}

            if isinstance(raw, dict):
                for key, value in raw.items():
                    if not isinstance(value, dict):
                        continue
                    symbol = str(
                        value.get("symbol") or key
                    ).upper()
                    payloads[symbol] = value

            elif isinstance(raw, list):
                for value in raw:
                    if not isinstance(value, dict):
                        continue
                    symbol = str(
                        value.get("symbol") or ""
                    ).upper()
                    if symbol:
                        payloads[symbol] = value

            out = {}
            for symbol in symbols:
                payload = payloads.get(symbol.upper())
                if not payload:
                    continue
                tick = self._normalise_biquote_tick(
                    symbol.upper(),
                    payload,
                )
                if tick:
                    out[symbol.upper()] = tick

            return out
        except Exception:
            return {}

    def _xau(self):
        try:
            payload = self._json(XAUS)
            price = float(payload["spot_usd_oz"])
            state = (
                (payload.get("data_state") or {})
                .get("status", "")
                .lower()
            )
            ts = (
                payload.get("updated_at")
                or (payload.get("data_state") or {}).get("as_of")
            )
            age = self._age(ts)

            if (
                price <= 0
                or state != "fresh"
                or age is None
                or age > 120
            ):
                return None

            return self._store({
                "symbol": "XAUUSD",
                "price": price,
                "time": ts,
                "source": "XAUS",
                "state": "LIVE",
                "source_age_seconds": round(age, 1),
                "type": "Metal",
            })
        except Exception:
            return None

    def fetch(
        self,
        symbols=("EURUSD", "GBPUSD", "BTCUSD", "XAUUSD"),
    ):
        wanted = [
            symbol.upper()
            for symbol in symbols
            if symbol.upper() != "XAUUSD"
        ]

        live = self._biquote_batch(wanted)

        out = []
        for symbol in wanted:
            item = live.get(symbol) or self._cached(symbol)
            if item:
                out.append(item)

        gold = self._xau() or self._cached("XAUUSD")
        if gold:
            out.append(gold)

        return out
