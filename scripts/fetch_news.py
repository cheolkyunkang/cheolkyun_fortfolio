#!/usr/bin/env python3
"""
보유 종목 관련 뉴스와 배당 관련 뉴스를 구글 뉴스 RSS(무료, 키 불필요)에서 가져와
data/news.json 을 갱신한다. 시세보다 자주 바뀔 필요가 없어서 별도의(더 느린) 주기로 실행한다.
"""
import json
import sys
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

import requests

KST = timezone(timedelta(hours=9))
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}
TIMEOUT = 10
MAX_GENERAL = 3
MAX_DIVIDEND = 2


def _parse_pub_date(pub_date):
    """RFC 822 pubDate 문자열을 정렬 가능한 datetime으로 변환. 실패 시 아주 과거 값 반환."""
    try:
        dt = parsedate_to_datetime(pub_date)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:  # noqa: BLE001
        return datetime.min.replace(tzinfo=timezone.utc)


def fetch_rss(query):
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {"q": query, "hl": "ko", "gl": "KR", "ceid": "KR:ko"}
    )
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    root = ET.fromstring(r.text)
    items = []
    for item in root.findall("./channel/item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub_date = (item.findtext("pubDate") or "").strip()
        source_el = item.find("source")
        source = source_el.text.strip() if source_el is not None and source_el.text else ""
        if title and link:
            items.append({"title": title, "link": link, "source": source, "pubDate": pub_date})
    # 구글 뉴스 RSS 검색 결과는 기본적으로 "관련도" 순이라, 같은 검색어로 매번 같은
    # (오래된) 기사가 계속 1순위로 뽑히는 경우가 많다. 최신 소식이 잘 보이도록
    # 발행일(pubDate) 최신순으로 다시 정렬해서 pick_top이 최신 기사부터 고르게 한다.
    items.sort(key=lambda it: _parse_pub_date(it["pubDate"]), reverse=True)
    return items


def pick_top(items_by_query, limit):
    """여러 종목 쿼리 결과를 골고루 섞어서 상위 N개를 뽑는다."""
    picked = []
    idx = 0
    while len(picked) < limit:
        progressed = False
        for _, items in items_by_query:
            if idx < len(items):
                picked.append(items[idx])
                progressed = True
                if len(picked) >= limit:
                    break
        if not progressed:
            break
        idx += 1
    return picked


def main():
    with open("data/positions.json", encoding="utf-8") as f:
        positions = json.load(f)["positions"]

    general_by_query = []
    dividend_by_query = []

    for p in positions:
        name = p["name"]
        try:
            general_by_query.append((name, fetch_rss(name)))
        except Exception as e:  # noqa: BLE001
            print(f"[warn] news fetch failed for {name}: {e}", file=sys.stderr)
            general_by_query.append((name, []))
        time.sleep(0.5)

        try:
            dividend_by_query.append((name, fetch_rss(f"{name} 배당")))
        except Exception as e:  # noqa: BLE001
            print(f"[warn] dividend news fetch failed for {name}: {e}", file=sys.stderr)
            dividend_by_query.append((name, []))
        time.sleep(0.5)

    general_news = pick_top(general_by_query, MAX_GENERAL)
    dividend_news = pick_top(dividend_by_query, MAX_DIVIDEND)

    out = {
        "updatedAt": datetime.now(KST).isoformat(),
        "generalNews": general_news,
        "dividendNews": dividend_news,
    }

    with open("data/news.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
