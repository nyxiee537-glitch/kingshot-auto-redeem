from __future__ import annotations

import os
from pathlib import Path

import requests


SUMMARY_FILE = Path("redeem-summary.txt")

GREEN = 0x57F287
YELLOW = 0xFEE75C
RED = 0xED4245


def parse_summary() -> tuple[str, list[dict[str, str]]]:
    if not SUMMARY_FILE.exists():
        raise RuntimeError("redeem-summary.txtが見つかりません。")

    lines = SUMMARY_FILE.read_text(encoding="utf-8").splitlines()

    gift_code = "Unknown"
    players: list[dict[str, str]] = []

    for line in lines:
        if line.startswith("Gift code:"):
            gift_code = line.split(":", 1)[1].strip()

        if not line.startswith("- "):
            continue

        parts = [part.strip() for part in line[2:].split("|")]

        # プレイヤー結果行だけを対象にする
        if len(parts) != 4:
            continue

        name, masked_id, status, message = parts

        players.append(
            {
                "name": name,
                "masked_id": masked_id,
                "status": status,
                "message": message,
            }
        )

    return gift_code, players


def player_names(players: list[dict[str, str]]) -> str:
    if not players:
        return "なし"

    return "\n".join(
        f"• {player['name']}"
        for player in players
    )


def main() -> None:
    webhook_url = os.environ["DISCORD_WEBHOOK_URL"].strip()

    if not webhook_url:
        raise RuntimeError("DISCORD_WEBHOOK_URLが空です。")

    gift_code, players = parse_summary()

    success = [
        player
        for player in players
        if player["status"] == "success"
    ]

    already = [
        player
        for player in players
        if player["status"] == "already_redeemed"
    ]

    failed = [
        player
        for player in players
        if player["status"] not in {
            "success",
            "already_redeemed",
            "dry_run",
        }
    ]

    dry_run = [
        player
        for player in players
        if player["status"] == "dry_run"
    ]

    embeds: list[dict] = []

    if success:
        embeds.append(
            {
                "title": "🟢 交換成功",
                "description": player_names(success),
                "color": GREEN,
            }
        )

    if already:
        embeds.append(
            {
                "title": "🟡 受取済み",
                "description": player_names(already),
                "color": YELLOW,
            }
        )

    if failed:
        failure_lines = []

        for player in failed:
            failure_lines.append(
                f"• **{player['name']}**\n"
                f"  {player['message']}"
            )

        embeds.append(
            {
                "title": "🔴 交換失敗",
                "description": "\n".join(failure_lines),
                "color": RED,
            }
        )

    if dry_run:
        embeds.append(
            {
                "title": "🧪 Dry Run",
                "description": (
                    "Confirmは押していません。\n\n"
                    + player_names(dry_run)
                ),
                "color": YELLOW,
            }
        )

    if not embeds:
        embeds.append(
            {
                "title": "🔴 結果なし",
                "description": "プレイヤーの処理結果を取得できませんでした。",
                "color": RED,
            }
        )

    payload = {
        "username": "KingShot Auto Redeem",
        "content": f"🎁 **ギフトコード：`{gift_code}`**",
        "embeds": embeds,
    }

    response = requests.post(
        webhook_url,
        json=payload,
        timeout=30,
    )

    if response.status_code not in {200, 204}:
        raise RuntimeError(
            f"Discord通知に失敗しました。"
            f"Status: {response.status_code} "
            f"Body: {response.text}"
        )

    print("Discord notification sent successfully.")


if __name__ == "__main__":
    main()
