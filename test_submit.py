from __future__ import annotations

import os
import re
import time
from pathlib import Path

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
    見つからない場合は、上から何番目のinputかで指定する。
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


def select_player(
    players: list[dict[str, str]],
    requested_name: str,
) -> dict[str, str]:
    """
    workflowで指定したHNと完全一致するプレイヤーを選ぶ。
    大文字・小文字は区別しない。
    """
    normalized_requested = requested_name.strip().casefold()

    for player in players:
        if player["name"].strip().casefold() == normalized_requested:
            return player

    available_names = ", ".join(
        player["name"] for player in players
    )

    raise RuntimeError(
        f"指定したプレイヤーが見つかりません: {requested_name}\n"
        f"有効なプレイヤー: {available_names}"
    )


def save_result_text(
    page: Page,
    player_id: str,
) -> None:
    """
    交換後の画面内テキストを保存する。
    Player IDはファイル内で伏せる。
    """
    body_text = page.locator("body").inner_text(timeout=10_000)
    safe_text = body_text.replace(player_id, "***PLAYER_ID***")

    Path("submit-result.txt").write_text(
        safe_text,
        encoding="utf-8",
    )


def main() -> None:
    database_id = os.environ["NOTION_DATABASE_ID"]
    requested_name = os.environ["TEST_PLAYER_NAME"].strip()
    gift_code = os.environ["GIFT_CODE"].strip()

    if not requested_name:
        raise RuntimeError("TEST_PLAYER_NAMEが空です。")

    if not gift_code:
        raise RuntimeError("GIFT_CODEが空です。")

    data_source_id = get_data_source_id(database_id)
    players = get_active_players(data_source_id)

    if not players:
        raise RuntimeError(
            "Notionに有効なプレイヤーが登録されていません。"
        )

    player = select_player(players, requested_name)

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

    print(f"Target player: {name}")
    print(f"Player ID: {masked_id}")
    print(f"Kingdom: {kingdom}")
    print(f"Gift code: {gift_code}")
    print("This test WILL click Confirm.")

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

            fill_input(page, "Player ID", 0, player_id)
            fill_input(page, "Kingdom", 1, kingdom)
            fill_input(page, "Gift Code", 2, gift_code)

            page.screenshot(
                path="01-before-confirm.png",
                full_page=True,
            )

            confirm_button = page.get_by_role(
                "button",
                name=re.compile(r"^Confirm$", re.IGNORECASE),
            )

            if confirm_button.count() == 0:
                raise RuntimeError(
                    "Confirmボタンが見つかりませんでした。"
                )

            confirm_button.first.click(timeout=15_000)

            # サイトの結果表示を待つ
            time.sleep(5)

            page.screenshot(
                path="02-after-confirm.png",
                full_page=True,
            )

            save_result_text(page, player_id)

            print("Confirm clicked.")
            print("Result screenshot and text were saved.")

        except Exception:
            page.screenshot(
                path="99-submit-error.png",
                full_page=True,
            )

            try:
                save_result_text(page, player_id)
            except Exception:
                pass

            raise

        finally:
            browser.close()


if __name__ == "__main__":
    main()
