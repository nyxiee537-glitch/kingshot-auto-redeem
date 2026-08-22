from __future__ import annotations

import json
from pathlib import Path

import requests

from config import DISCORD_WEBHOOK_URL, HTTP_TIMEOUT


def _post_webhook(
    payload: dict,
    attachment: Path | None = None,
) -> None:
    if not DISCORD_WEBHOOK_URL:
        print("[INFO] DISCORD_WEBHOOK_URL is empty. Discord notification skipped.")
        return

    if attachment and attachment.exists():
        with attachment.open("rb") as file_handle:
            response = requests.post(
                DISCORD_WEBHOOK_URL,
                data={"payload_json": json.dumps(payload, ensure_ascii=False)},
                files={
                    "files[0]": (
                        attachment.name,
                        file_handle,
                        "text/plain",
                    )
                },
                timeout=HTTP_TIMEOUT,
            )
    else:
        response = requests.post(
            DISCORD_WEBHOOK_URL,
            json=payload,
            timeout=HTTP_TIMEOUT,
        )

    response.raise_for_status()


def send_redeem_notification(
    code: str,
    sources: list[str],
    summary: dict,
    summary_file: Path,
) -> None:
    """
    Discord本文:
      - Success は人数のみ
      - Already Redeemed はユーザー名
      - Failed / Server Busy / Unknown はユーザー名 + 理由
      - 詳細は txt を添付
    """
    results = summary.get("results", [])

    success = [r for r in results if r.get("status") == "success"]
    already = [r for r in results if r.get("status") == "already_redeemed"]
    requirements_not_met = [
        r for r in results if r.get("status") == "requirements_not_met"
    ]
    dry_run = [r for r in results if r.get("status") == "dry_run"]

    problem_statuses = {
        "failed",
        "server_busy",
        "unknown",
    }
    problems = [
        r for r in results
        if r.get("status") in problem_statuses
    ]

    source_text = " / ".join(sources) if sources else "不明"

    is_restricted_code = bool(requirements_not_met)
    title = (
        "👑 **VIP / Restricted Gift Code Detected**"
        if is_restricted_code
        else "🎁 **New Gift Code Detected**"
    )

    lines = [
        title,
        f"**Code:** `{code}`",
        f"**Source:** {source_text}",
        "",
        f"👥 対象: **{len(results)}人**",
        f"✅ Success: **{len(success)}人**",
    ]

    if requirements_not_met:
        lines.append(
            f"👑 Requirements Not Met: **{len(requirements_not_met)}人**"
        )

    if dry_run:
        lines.append(f"🧪 Dry Run: **{len(dry_run)}人**")

    if already:
        lines.extend(
            [
                "",
                f"☑️ **Already Redeemed ({len(already)})**",
            ]
        )
        lines.extend(
            f"• {item.get('name', 'Unknown')}"
            for item in already
        )

    if problems:
        lines.extend(
            [
                "",
                f"❌ **Attention ({len(problems)})**",
            ]
        )

        for item in problems:
            name = item.get("name", "Unknown")
            message = item.get("message", "")
            lines.append(f"• {name}")
            if message:
                lines.append(f"  └ {message}")

    lines.extend(
        [
            "",
            "📎 詳細結果",
        ]
    )

    _post_webhook(
        {
            "username": "537 Gift Bot",
            "content": "\n".join(lines),
            "allowed_mentions": {"parse": []},
        },
        attachment=summary_file,
    )


def send_source_error_notification(errors: dict[str, str]) -> None:
    if not errors:
        return

    lines = [
        "⚠️ **537 Gift Bot - Source Error**",
        "ギフトコード取得元でエラーが発生しました。",
        "",
    ]

    for source, error in errors.items():
        lines.append(f"• **{source}**: {error[:500]}")

    _post_webhook(
        {
            "username": "537 Gift Bot",
            "content": "\n".join(lines),
            "allowed_mentions": {"parse": []},
        }
    )
