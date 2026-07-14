#!/usr/bin/env python3
"""
data/positions.json 에 등록된 종목들의 최신 시세와 원/달러 환율을 가져와
data/prices.json 을 갱신한다.

1차 소스: Yahoo Finance chart API (무료, 키 불필요)
2차 소스(Yahoo 실패 시): Stooq CSV (무료, 키 불필요)
환율: Yahoo KRW=X -> 실패 시 open.er-api.com
"""
import json
import sys
import time
from datetime import datetime, timezone, timedelta

import requests

KST = timezone(timedelta(hours=9))
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}
TIMEOUT = 10

# 상단 패널에 보여줄 국내/미국 지수
INDEX_TICKERS = {
    "KOSPI": "^KS11",
    "KOSDAQ": "^KQ11",
    "NASDAQ": "^IXIC",
    "SP500": "^GSPC",
}


def fetch_yahoo(ticker):
    """개별 종목용: 현재가/전일종가/통화 + 스파크라인용 최근 종가 히스토리."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT, params={"range": "5d", "interval": "15m"})
    r.raise_for_status()
    data = r.json()
    result = data["chart"]["result"][0]
    meta = result["meta"]
    price = meta.get("regularMarketPrice")
    prev_close = meta.get("previousClose") or meta.get("chartPreviousClose")
    if price is None:
        raise ValueError("no regularMarketPrice")
    closes = []
    try:
        closes = result["indicators"]["quote"][0]["close"] or []
        closes = [c for c in closes if c is not None]
        closes = closes[-40:]
    except Exception:  # noqa: BLE001
        closes = []
    return {
        "price": float(price),
        "prevClose": float(prev_close) if prev_close is not None else None,
        "currency": meta.get("currency"),
        "history": closes,
        "source": "yahoo",
    }


def fetch_yahoo_index(ticker):
    """지수용: 현재가/전일종가 + 스파크라인용 최근 종가 히스토리."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT, params={"range": "5d", "interval": "15m"})
    r.raise_for_status()
    data = r.json()
    result = data["chart"]["result"][0]
    meta = result["meta"]
    price = meta.get("regularMarketPrice")
    prev_close = meta.get("previousClose") or meta.get("chartPreviousClose")
    if price is None:
        raise ValueError("no regularMarketPrice")
    closes = []
    try:
        closes = result["indicators"]["quote"][0]["close"] or []
        closes = [c for c in closes if c is not None]
        closes = closes[-40:]
    except Exception:  # noqa: BLE001
        closes = []
    return {
        "price": float(price),
        "prevClose": float(prev_close) if prev_close is not None else None,
        "changePct": ((price - prev_close) / prev_close * 100) if prev_close else None,
        "history": closes,
        "source": "yahoo",
    }


def stooq_symbol(ticker):
    # KR: "360750.KS" -> "360750.kr"
    if ticker.upper().endswith(".KS"):
        return ticker.split(".")[0] + ".kr"
    # US ticker: "SCHD" -> "schd.us"
    return ticker.lower() + ".us"


def fetch_stooq(ticker):
    sym = stooq_symbol(ticker)
    url = "https://stooq.com/q/l/"
    r = requests.get(
        url,
        headers=HEADERS,
        timeout=TIMEOUT,
        params={"s": sym, "f": "sd2t2ohlcv", "h": "", "e": "csv"},
    )
    r.raise_for_status()
    lines = r.text.strip().splitlines()
    if len(lines) < 2:
        raise ValueError("stooq empty response")
    header = lines[0].split(",")
    row = lines[1].split(",")
    rec = dict(zip(header, row))
    close = rec.get("Close")
    if close in (None, "", "N/D"):
        raise ValueError("stooq no close price")
    return {
        "price": float(close),
        "prevClose": None,
        "currency": None,
        "history": [],
        "source": "stooq",
    }


def fetch_price(ticker):
    try:
        return fetch_yahoo(ticker)
    except Exception as e:  # noqa: BLE001
        print(f"[warn] yahoo failed for {ticker}: {e}", file=sys.stderr)
    try:
        return fetch_stooq(ticker)
    except Exception as e:  # noqa: BLE001
        print(f"[error] stooq failed for {ticker}: {e}", file=sys.stderr)
    return None


def fetch_fx_rate():
    try:
        data = fetch_yahoo("KRW=X")
        return data["price"], "yahoo"
    except Exception as e:  # noqa: BLE001
        print(f"[warn] yahoo fx failed: {e}", file=sys.stderr)
    try:
        r = requests.get("https://open.er-api.com/v6/latest/USD", headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        rate = data["rates"]["KRW"]
        return float(rate), "open.er-api.com"
    except Exception as e:  # noqa: BLE001
        print(f"[error] fallback fx failed: {e}", file=sys.stderr)
    return None, None


def main():
    with open("data/positions.json", encoding="utf-8") as f:
        positions = json.load(f)["positions"]

    tickers = sorted({p["ticker"] for p in positions})

    prices = {}
    for ticker in tickers:
        result = fetch_price(ticker)
        if result:
            prices[ticker] = result
        else:
            prices[ticker] = {"price": None, "prevClose": None, "currency": None, "history": [], "source": "error"}
        time.sleep(0.5)

    fx_rate, fx_source = fetch_fx_rate()

    indices = {}
    for name, idx_ticker in INDEX_TICKERS.items():
        try:
            indices[name] = fetch_yahoo_index(idx_ticker)
        except Exception as e:  # noqa: BLE001
            print(f"[warn] index fetch failed for {name}: {e}", file=sys.stderr)
            indices[name] = {"price": None, "prevClose": None, "changePct": None, "history": [], "source": "error"}
        time.sleep(0.5)

    out = {
        "updatedAt": datetime.now(KST).isoformat(),
        "fxRate": fx_rate,
        "fxSource": fx_source,
        "prices": prices,
        "indices": indices,
        "status": "ok" if all(v["price"] is not None for v in prices.values()) and fx_rate else "partial",
    }

    with open("data/prices.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
