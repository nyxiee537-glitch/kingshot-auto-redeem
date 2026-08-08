from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

from config import (
    MAX_SERVER_BUSY_RETRIES,
    PLAYER_INTERVAL_SECONDS,
    REDEEM_URL,
    RESULT_WAIT_SECONDS,
    RESULTS_DIR,
    SERVER_BUSY_RETRY_DELAYS,
    SUMMARY_JSON_FILE,
    SUMMARY_TEXT_FILE,
)
from test_notion import get_active_players, get_data_source_id


@dataclass
class RedeemResult:
    name: str
    player_id_masked: str
    status: str
    message: str


def mask_player_id(player_id: str) -> str:
    if len(player_id) >= 4:
        return f"***{player_id[-4:]}"
    return "***"


def safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", value.strip())
    return cleaned or "player"


def fill_input(
    page: Page,
    placeholder: str,
    fallback_index: int,
    value: str,
) -> None:
    locator = page.get_by_placeholder(
        re.compile(placeholder, re.IGNORECASE)
    )

    if locator.count() > 0:
        locator.first.fill(value)
        return

    inputs = page.locator("input")

    if inputs.count() <= fallback_index:
        raise RuntimeError(f"入力欄が見つかりませんでした: {placeholder}")

    inputs.nth(fallback_index).fill(value)


def get_page_text(page: Page, player_id: str) -> str:
    body_text = page.locator("body").inner_text(timeout=10_000)
    return body_text.replace(player_id, "***PLAYER_ID***")


def classify_result(page_text: str) -> tuple[str, str]:
    normalized = page_text.casefold()

    if (
        "server busy. please try again later." in normalized
        or "server busy" in normalized
    ):
        return "server_busy", "サーバー混雑のため再試行対象です。"

    already_words = (
        "already redeemed",
        "already used",
        "already claimed",
        "gift has already been claimed",
        "redeemed already",
        "the same gift code type can only be redeemed once",
        "can only be redeemed once",
    )

    invalid_words = (
        "invalid",
        "expired",
        "unable to claim",
        "expired, unable to claim",
        "not valid",
        "does not exist",
    )

    success_words = (
        "redeemed successfully",
        "please check your mail for rewards",
    )

    if any(word in normalized for word in already_words):
        return "already_redeemed", "すでに交換済みです。"

    if any(word in normalized for word in invalid_words):
        return "failed", "無効または期限切れの可能性があります。"

    if any(word in normalized for word in success_words):
        return "success", "交換成功。"

    return "unknown", "結果を自動判定できませんでした。"


def close_server_busy_popup(page: Page) -> None:
    busy_text = page.get_by_text(
        re.compile(
            r"Server busy\. Please try again later\.",
            re.IGNORECASE,
        )
    )

    if busy_text.count() == 0:
        return

    try:
        popup = busy_text.first.locator(
            "xpath=ancestor::*[.//button or .//*[normalize-space()='Confirm']][1]"
        )
        confirm = popup.get_by_text("Confirm", exact=True)

        if confirm.count() > 0:
            confirm.first.click(force=True, timeout=5_000)
            return
    except Exception:
        pass

    try:
        page.keyboard.press("Escape")
    except Exception:
        pass


def redeem_for_player(
    page: Page,
    player: dict[str, str],
    gift_code: str,
    dry_run: bool,
    player_number: int,
) -> RedeemResult:
    name = player["name"].strip() or f"Player-{player_number}"
    player_id = player["player_id"].strip()
    kingdom = player["kingdom"].strip()

    masked_id = mask_player_id(player_id)
    filename_name = safe_filename(name)

    if not player_id:
        return RedeemResult(name, masked_id, "failed", "Player IDが空です。")

    if not kingdom:
        return RedeemResult(name, masked_id, "failed", "Kingdomが空です。")

    print(f"\n[{player_number}] Processing: {name}")
    print(f"Player ID: {masked_id}")
    print(f"Kingdom: {kingdom}")

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
            path=str(
                RESULTS_DIR
                / f"{player_number:03d}-{filename_name}-before.png"
            ),
            full_page=True,
        )

        if dry_run:
            return RedeemResult(
                name,
                masked_id,
                "dry_run",
                "入力確認のみ。Confirmは未実行です。",
            )

        status = "unknown"
        message = "結果を自動判定できませんでした。"
        page_text = ""

        for attempt in range(MAX_SERVER_BUSY_RETRIES + 1):
            if attempt > 0:
                fill_input(page, "Player ID", 0, player_id)
                fill_input(page, "Kingdom", 1, kingdom)
                fill_input(page, "Gift Code", 2, gift_code)

            confirm_text = page.get_by_text("Confirm", exact=True)

            if confirm_text.count() == 0:
                raise RuntimeError("Confirmの文字が見つかりませんでした。")

            confirm_text.last.click(
                force=True,
                timeout=15_000,
            )

            time.sleep(RESULT_WAIT_SECONDS)

            page_text = get_page_text(page, player_id)
            status, message = classify_result(page_text)

            print(
                f"Attempt {attempt + 1}/"
                f"{MAX_SERVER_BUSY_RETRIES + 1}: {status}"
            )

            if status != "server_busy":
                break

            if attempt >= MAX_SERVER_BUSY_RETRIES:
                message = (
                    "サーバー混雑が続いたため、"
                    f"{MAX_SERVER_BUSY_RETRIES}回の再試行後も交換できませんでした。"
                )
                break

            delay = SERVER_BUSY_RETRY_DELAYS[
                min(attempt, len(SERVER_BUSY_RETRY_DELAYS) - 1)
            ]

            print(f"Server busy → {delay}秒後に再試行")
            close_server_busy_popup(page)
            time.sleep(delay)

        page.screenshot(
            path=str(
                RESULTS_DIR
                / f"{player_number:03d}-{filename_name}-after.png"
            ),
            full_page=True,
        )

        (
            RESULTS_DIR
            / f"{player_number:03d}-{filename_name}-result.txt"
        ).write_text(
            page_text,
            encoding="utf-8",
        )

        return RedeemResult(
            name,
            masked_id,
            status,
            message,
        )

    except Exception as exc:
        try:
            page.screenshot(
                path=str(
                    RESULTS_DIR
                    / f"{player_number:03d}-{filename_name}-error.png"
                ),
                full_page=True,
            )
        except Exception:
            pass

        print(f"ERROR: {name}: {exc}")

        return RedeemResult(
            name,
            masked_id,
            "failed",
            str(exc),
        )


def save_summary(
    gift_code: str,
    dry_run: bool,
    results: list[RedeemResult],
) -> dict:
    counts: dict[str, int] = {}

    for result in results:
        counts[result.status] = counts.get(result.status, 0) + 1

    summary = {
        "gift_code": gift_code,
        "dry_run": dry_run,
        "total_players": len(results),
        "counts": counts,
        "results": [
            {
                "name": result.name,
                "status": result.status,
                "message": result.message,
            }
            for result in results
        ],
    }

    SUMMARY_JSON_FILE.write_text(
        json.dumps(
            summary,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    lines = [
        f"Gift code: {gift_code}",
        f"Dry run: {dry_run}",
        f"Total players: {len(results)}",
        "",
        "Summary:",
    ]

    for status, count in sorted(counts.items()):
        lines.append(f"- {status}: {count}")

    lines.extend(["", "Players:"])

    # Discord添付用なのでPlayer IDは書かず、ユーザー名だけにする。
    for result in results:
        lines.append(
            f"- {result.name} | {result.status} | {result.message}"
        )

    SUMMARY_TEXT_FILE.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )

    return summary


def main() -> None:
    database_id = os.environ["NOTION_DATABASE_ID"]
    gift_code = os.environ["GIFT_CODE"].strip()
    dry_run = os.environ.get("DRY_RUN", "false").strip().casefold() in {
        "true", "1", "yes", "on"
    }

    if not gift_code:
        raise RuntimeError("GIFT_CODEが空です。")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    data_source_id = get_data_source_id(database_id)
    players = get_active_players(data_source_id)

    if not players:
        raise RuntimeError(
            "NotionにActiveのプレイヤーがいません。"
        )

    print(f"Gift code: {gift_code}")
    print(f"Active players: {len(players)}")
    print(f"Dry run: {dry_run}")

    results: list[RedeemResult] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(
            viewport={"width": 1450, "height": 1000}
        )

        try:
            for index, player in enumerate(players, start=1):
                results.append(
                    redeem_for_player(
                        page,
                        player,
                        gift_code,
                        dry_run,
                        index,
                    )
                )
                time.sleep(PLAYER_INTERVAL_SECONDS)
        finally:
            browser.close()

    summary = save_summary(
        gift_code,
        dry_run,
        results,
    )

    print(json.dumps(summary, ensure_ascii=False, indent=2))

    # すべて failed のときだけプロセス失敗。
    if results and all(r.status == "failed" for r in results):
        raise RuntimeError(
            "すべてのプレイヤーで処理に失敗しました。"
        )


if __name__ == "__main__":
    main()
