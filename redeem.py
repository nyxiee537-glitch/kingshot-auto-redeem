from __future__ import annotations

import json
import os
from pathlib import Path

import requests

from config import DISCORD_WEBHOOK_URL, HTTP_TIMEOUT

ERROR_WEBHOOK_URL = os.environ.get("DISCORD_ERROR_WEBHOOK_URL", "").strip()


def _post_webhook(payload: dict, attachment: Path | None = None, *, error: bool = False) -> None:
    webhook_url = ERROR_WEBHOOK_URL if error and ERROR_WEBHOOK_URL else DISCORD_WEBHOOK_URL
    if not webhook_url:
        print("[INFO] Discord webhook is empty. Notification skipped.")
        return

    if attachment and attachment.exists():
        with attachment.open("rb") as file_handle:
            response = requests.post(
                webhook_url,
                data={"payload_json": json.dumps(payload, ensure_ascii=False)},
                files={"files[0]": (attachment.name, file_handle, "text/plain")},
                timeout=HTTP_TIMEOUT,
            )
    else:
        response = requests.post(webhook_url, json=payload, timeout=HTTP_TIMEOUT)
    response.raise_for_status()


def send_detection_notification(code: str, sources: list[str]) -> None:
    source_text = " / ".join(sources) if sources else "不明"
    _post_webhook({
        "username": "537 Gift Bot",
        "content": (
            "🎁 **新しいギフトコードを検出しました**\n"
            f"**Code:** `{code}`\n"
            f"**Source:** {source_text}\n\n"
            "🔄 登録アカウントへの交換を開始します。"
        ),
        "allowed_mentions": {"parse": []},
    })


def send_redeem_notification(code: str, sources: list[str], summary: dict, summary_file: Path) -> None:
    results = summary.get("results", [])
    by_status = lambda status: [r for r in results if r.get("status") == status]
    success = by_status("success")
    already = by_status("already_redeemed")
    requirements = by_status("requirements_not_met")
    moved = by_status("kingdom_changed")
    failed = by_status("failed")
    source_text = " / ".join(sources) if sources else "不明"

    lines = [
        "👑 **537 Gift Bot・ギフトコード交換完了**",
        f"**Code:** `{code}`",
        f"**Source:** {source_text}", "",
        f"👥 対象: **{len(results)}人**",
        f"✅ Success: **{len(success)}人**",
        f"☑️ Already: **{len(already)}人**",
        f"🔒 条件未達: **{len(requirements)}人**",
        f"🚫 537対象外: **{len(moved)}人**",
    ]
    if failed:
        lines.append(f"❌ Failed: **{len(failed)}人**")
    lines.extend(["", "📎 詳細結果"])

    _post_webhook({
        "username": "537 Gift Bot",
        "content": "\n".join(lines),
        "allowed_mentions": {"parse": []},
    }, attachment=summary_file)

    if moved:
        send_kingdom_changed_notification(moved)


def send_kingdom_changed_notification(players: list[dict]) -> None:
    lines = [
        "🚫 **537 Gift Bot・対象外アカウント**",
        "王国情報が一致しないアカウントを検出しました。",
        "537王国から移民した可能性があるため、今後の交換対象を確認してください。",
        "",
    ]
    for item in players:
        lines.append(f"• **{item.get('name', 'Unknown')}**")
        lines.append(f"  └ {item.get('message', 'Character info is incorrect.')}" )
    _post_webhook({
        "username": "537 Gift Bot",
        "content": "\n".join(lines),
        "allowed_mentions": {"parse": []},
    }, error=True)


def send_source_error_notification(errors: dict[str, str]) -> None:
    if not errors:
        return
    lines = ["⚠️ **537 Gift Bot・取得元エラー**", "ギフトコード取得元でエラーが発生しました。", ""]
    for source, error in errors.items():
        lines.append(f"• **{source}**: {error[:500]}")
    _post_webhook({
        "username": "537 Gift Bot",
        "content": "\n".join(lines),
        "allowed_mentions": {"parse": []},
    }, error=True)
