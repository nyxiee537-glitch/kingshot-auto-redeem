from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

from test_notion import get_active_players, get_data_source_id


REDEEM_URL = "https://ks-giftcode.centurygame.com/"
RESULTS_DIR = Path("redeem-results")


@dataclass
class RedeemResult:
    name: str
    player_id_masked: str
    status: str
    message: str


def mask_player_id(player_id: str) -> str:
    """Player IDをGitHubログ上で伏せる。"""
    if len(player_id) >= 4:
        return f"***{player_id[-4:]}"

    return "***"


def safe_filename(value: str) -> str:
    """HNをスクリーンショットのファイル名に使える形へ変換する。"""
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", value.strip())
    return cleaned or "player"


def fill_input(
    page: Page,
    placeholder: str,
    fallback_index: int,
    value: str,
) -> None:
    """
    placeholderで入力欄を探す。
    見つからなければ、上から何番目のinputかで探す。
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


def get_page_text(page: Page, player_id: str) -> str:
    """画面内テキストを取得し、Player IDを伏せる。"""
    body_text = page.locator("body").inner_text(timeout=10_000)
    return body_text.replace(player_id, "***PLAYER_ID***")


def classify_result(page_text: str) -> tuple[str, str]:
    """
    画面の文言から結果を大まかに分類する。

    サイトの正確な成功・失敗メッセージが判明したら、
    後でこの判定を調整する。
    """
    normalized = page_text.casefold()

    already_words = (
        "already redeemed",
        "already used",
        "already claimed",
        "redeemed already",
    )

    invalid_words = (
        "invalid",
        "expired",
        "not valid",
        "does not exist",
    )

    success_words = (
        "success",
        "successful",
        "redeemed",
        "reward",
    )

    if any(word in normalized for word in already_words):
        return "already_redeemed", "すでに交換済みの可能性があります。"

    if any(word in normalized for word in invalid_words):
        return "failed", "無効または期限切れの可能性があります。"

    if any(word in normalized for word in success_words):
        return "success", "交換成功を示す文言が検出されました。"

    return "unknown", "結果を自動判定できませんでした。"


def redeem_for_player(
    page: Page,
    player: dict[str, str],
    gift_code: str,
    dry_run: bool,
    player_number: int,
) -> RedeemResult:
    """1人分の入力・交換処理を行う。"""
    name = player["name"].strip()
    player_id = player["player_id"].strip()
    kingdom = player["kingdom"].strip()

    if not name:
        name = f"Player-{player_number}"

    masked_id = mask_player_id(player_id)
    filename_name = safe_filename(name)

    if not player_id:
        return RedeemResult(
            name=name,
            player_id_masked=masked_id,
            status="failed",
            message="Player IDが空です。",
        )

    if not kingdom:
        return RedeemResult(
            name=name,
            player_id_masked=masked_id,
            status="failed",
            message="Kingdomが空です。",
        )

    print("")
    print(f"[{player_number}] Processing: {name}")
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

        before_path = RESULTS_DIR / (
            f"{player_number:03d}-{filename_name}-before.png"
        )

        page.screenshot(
            path=str(before_path),
            full_page=True,
        )

        if dry_run:
            print("DRY RUN: Confirmは押していません。")

            return RedeemResult(
                name=name,
                player_id_masked=masked_id,
                status="dry_run",
                message="入力確認のみ。Confirmは未実行です。",
            )

        confirm_text = page.get_by_text(
            "Confirm",
            exact=True,
        )

        if confirm_text.count() == 0:
            raise RuntimeError(
                "Confirmの文字が見つかりませんでした。"
            )

        confirm_text.first.click(
            force=True,
            timeout=15_000,
        )

        # 結果表示を待つ
        time.sleep(5)

        print("========== PAGE TEXT ==========")
        print(page.locator("body").inner_text())
        print("===============================")

        after_path = RESULTS_DIR / (
            f"{player_number:03d}-{filename_name}-after.png"
        )

        page.screenshot(
            path=str(after_path),
            full_page=True,
        )

        page_text = get_page_text(page, player_id)

        text_path = RESULTS_DIR / (
            f"{player_number:03d}-{filename_name}-result.txt"
        )

        text_path.write_text(
            page_text,
            encoding="utf-8",
        )

        status, message = classify_result(page_text)

        print(f"Result: {status}")
        print(f"Message: {message}")

        return RedeemResult(
            name=name,
            player_id_masked=masked_id,
            status=status,
            message=message,
        )

    except Exception as exc:
        error_path = RESULTS_DIR / (
            f"{player_number:03d}-{filename_name}-error.png"
        )

        try:
            page.screenshot(
                path=str(error_path),
                full_page=True,
            )
        except Exception:
            pass

        print(f"ERROR: {name}: {exc}")

        return RedeemResult(
            name=name,
            player_id_masked=masked_id,
            status="failed",
            message=str(exc),
        )


def save_summary(
    gift_code: str,
    dry_run: bool,
    results: list[RedeemResult],
) -> None:
    """全員分の結果をテキストへまとめる。"""
    status_counts: dict[str, int] = {}

    for result in results:
        status_counts[result.status] = (
            status_counts.get(result.status, 0) + 1
        )

    lines = [
        f"Gift code: {gift_code}",
        f"Dry run: {dry_run}",
        f"Total players: {len(results)}",
        "",
        "Summary:",
    ]

    for status, count in sorted(status_counts.items()):
        lines.append(f"- {status}: {count}")

    lines.extend(
        [
            "",
            "Players:",
        ]
    )

    for result in results:
        lines.append(
            f"- {result.name} | "
            f"{result.player_id_masked} | "
            f"{result.status} | "
            f"{result.message}"
        )

    summary_text = "\n".join(lines)

    Path("redeem-summary.txt").write_text(
        summary_text,
        encoding="utf-8",
    )

    print("")
    print(summary_text)


def main() -> None:
    database_id = os.environ["NOTION_DATABASE_ID"]
    gift_code = os.environ["GIFT_CODE"].strip()

    dry_run_value = os.environ.get(
        "DRY_RUN",
        "true",
    ).strip().casefold()

    dry_run = dry_run_value in {
        "true",
        "1",
        "yes",
        "on",
    }

    if not gift_code:
        raise RuntimeError("GIFT_CODEが空です。")

    RESULTS_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    data_source_id = get_data_source_id(database_id)
    players = get_active_players(data_source_id)

    if not players:
        raise RuntimeError(
            "Notionにチェック済みのプレイヤーがいません。"
        )

    print(f"Gift code: {gift_code}")
    print(f"Active players: {len(players)}")
    print(f"Dry run: {dry_run}")

    results: list[RedeemResult] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
        )

        page = browser.new_page(
            viewport={
                "width": 1450,
                "height": 1000,
            },
        )

        try:
            for index, player in enumerate(
                players,
                start=1,
            ):
                result = redeem_for_player(
                    page=page,
                    player=player,
                    gift_code=gift_code,
                    dry_run=dry_run,
                    player_number=index,
                )

                results.append(result)

                # サイトへ連続アクセスしすぎないよう少し間隔を空ける
                time.sleep(3)

        finally:
            browser.close()

    save_summary(
        gift_code=gift_code,
        dry_run=dry_run,
        results=results,
    )

    # 全員失敗した場合のみActionを失敗扱いにする
    if results and all(
        result.status == "failed"
        for result in results
    ):
        raise RuntimeError(
            "すべてのプレイヤーで処理に失敗しました。"
        )


if __name__ == "__main__":
    main()
