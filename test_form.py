from __future__ import annotations

import os
import re

from playwright.sync_api import Page, sync_playwright

from test_notion import get_active_players, get_data_source_id


REDEEM_URL = "https://ks-giftcode.centurygame.com/"


def fill_input(
    page: Page,
    placeholder: str,
    fallback_index: int,
    value: str,
) -> None:
    """
    placeholderで入力欄を探す。
    見つからなければ、上から何番目かで指定する。
    """
    locator = page.get_by_placeholder(
        re.compile(placeholder, re.IGNORECASE)
    )

    if locator.count() > 0:
        locator.first.fill(value)
        return

    inputs = page.locator("input")

    if inputs.count() <= fallback_index:
        raise RuntimeError(
            f"入力欄が見つかりませんでした: {placeholder}"
        )

    inputs.nth(fallback_index).fill(value)


def main() -> None:
    database_id = os.environ["NOTION_DATABASE_ID"]
    gift_code = os.environ["GIFT_CODE"].strip()

    data_source_id = get_data_source_id(database_id)
    players = get_active_players(data_source_id)

    if not players:
        raise RuntimeError(
            "Notionに有効なプレイヤーが登録されていません。"
        )

    # 最初の1人だけテスト
    player = players[0]

    name = player["name"].strip()
    player_id = player["player_id"].strip()
    kingdom = player["kingdom"].strip()

    if not player_id:
        raise RuntimeError(f"{name}のPlayerIDが空です。")

    if not kingdom:
        raise RuntimeError(f"{name}のKingdomが空です。")

    masked_id = (
        f"***{player_id[-4:]}"
        if len(player_id) >= 4
        else "***"
    )

    print(f"Testing player: {name}")
    print(f"Player ID: {masked_id}")
    print(f"Kingdom: {kingdom}")
    print(f"Gift code: {gift_code}")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)

        page = browser.new_page(
            viewport={"width": 1450, "height": 1000},
        )

        try:
            page.goto(
                REDEEM_URL,
                wait_until="networkidle",
                timeout=60_000,
            )

            page.screenshot(
                path="01-page-opened.png",
                full_page=True,
            )

            fill_input(
                page,
                "Player ID",
                0,
                player_id,
            )

            fill_input(
                page,
                "Kingdom",
                1,
                kingdom,
            )

            fill_input(
                page,
                "Gift Code",
                2,
                gift_code,
            )

            page.screenshot(
                path="02-form-filled.png",
                full_page=True,
            )

            print("Form filled successfully.")
            print("Confirm was NOT clicked.")

        except Exception:
            page.screenshot(
                path="99-error.png",
                full_page=True,
            )
            raise

        finally:
            browser.close()


if __name__ == "__main__":
    main()
