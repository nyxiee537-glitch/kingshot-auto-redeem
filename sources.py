from __future__ import annotations

import re

import requests
from bs4 import BeautifulSoup

from config import (
    HTTP_TIMEOUT,
    KINGSHOT_NET_API,
    KINGSHOT_WIKI_URL,
    USER_AGENT,
)


def fetch_kingshot_net() -> set[str]:
    """kingshot.net API から現在のギフトコードを取得する。"""
    response = requests.get(
        KINGSHOT_NET_API,
        headers={"User-Agent": USER_AGENT},
        timeout=HTTP_TIMEOUT,
    )
    response.raise_for_status()

    data = response.json()
    rows = data.get("data", {}).get("giftCodes", [])

    return {
        item["code"].strip()
        for item in rows
        if isinstance(item, dict)
        and isinstance(item.get("code"), str)
        and item["code"].strip()
    }


def fetch_kingshot_wiki() -> set[str]:
    """KingshotWiki の Active Codes セクションからコードを取得する。"""
    response = requests.get(
        KINGSHOT_WIKI_URL,
        headers={"User-Agent": USER_AGENT},
        timeout=HTTP_TIMEOUT,
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    page_text = soup.get_text("\n", strip=True)

    match = re.search(
        r"Active\s+Codes\s*:?\s*(.*?)\s*Concierge\s+member\s+codes\s*:?",
        page_text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    if not match:
        raise RuntimeError(
            "KingshotWiki の Active Codes セクションを見つけられませんでした。"
        )

    section = match.group(1)
    codes: set[str] = set()

    for raw_line in section.splitlines():
        line = raw_line.strip()

        if not line:
            continue

        if line.casefold() in {"copy", "button"}:
            continue

        if re.fullmatch(r"[A-Za-z0-9_-]{4,40}", line):
            codes.add(line)

    if not codes:
        raise RuntimeError(
            "KingshotWiki の Active Codes からコードを抽出できませんでした。"
        )

    return codes


SOURCE_FETCHERS = {
    "kingshot.net": fetch_kingshot_net,
    "KingshotWiki": fetch_kingshot_wiki,
}


def collect_sources() -> tuple[dict[str, set[str]], dict[str, str]]:
    """
    2つの取得元を独立して確認する。
    片方が失敗しても、もう片方が成功すれば処理を継続する。
    """
    sources: dict[str, set[str]] = {}
    errors: dict[str, str] = {}

    for source_name, fetcher in SOURCE_FETCHERS.items():
        try:
            codes = fetcher()
            sources[source_name] = codes
            print(f"[{source_name}] {sorted(codes)}")
        except Exception as exc:
            errors[source_name] = str(exc)
            print(f"[WARN] {source_name}: {exc}")

    return sources, errors
