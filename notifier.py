from __future__ import annotations

import json
from pathlib import Path

import requests

from config import (
    DISCORD_WEBHOOK_URL,
    DISCORD_ERROR_WEBHOOK_URL,
    HTTP_TIMEOUT,
)


def _post_webhook(
    payload: dict,
    webhook_url: str,
    attachment: Path | None = None,
) -> None:
    if not webhook_url:
        print(
            "[INFO] Webhook URL is empty. "
            "Discord notification skipped."
        )
        return

    if attachment and attachment.exists():
        with attachment.open("rb") as file_handle:
            response = requests.post(
                webhook_url,
                data={
                    "payload_json": json.dumps(
                        payload, ensure_ascii=False
                    )
                },
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
            webhook_url,
            json=payload,
            timeout=HTTP_TIMEOUT,
        )

    response.raise_for_status()


def send_detection_notification(
    code: str,
    sources: list[str],
) -> None:
    """新しいコードを検出し、自動交換を開始することを通知する。（通常チャンネル）"""
    source_text = " / ".join(sources) if sources else "不明"

    lines = [
        "🎁 **新しいギフトコードを検出しました**",
        f"**コード：** `{code}`",
        f"**検出元：** {source_text}",
        "",
        "🔄 自動交換を開始します…",
    ]

    _post_webhook(
        {
            "username": "537 Gift Bot",
            "content": "\n".join(lines),
            "allowed_mentions": {"parse": []},
        },
        webhook_url=DISCORD_WEBHOOK_URL,
    )


def send_redeem_notification(
    code: str,
    sources: list[str],
    summary: dict,
    summary_file: Path,
) -> None:
    """
    Discord本文（通常チャンネル）:
    - Success は人数のみ
    - Already Redeemed はユーザー名
    - Failed / Server Busy / Unknown はユーザー名 + 理由
    - 詳細は txt を添付
    """
    results = summary.get("results", [])

    success = [r for r in results if r.get("status") == "success"]
    already = [
        r for r in results if r.get("status") == "already_redeemed"
    ]
    requirements_not_met = [
        r
        for r in results
        if r.get("status") == "requirements_not_met"
    ]
    dry_run = [r for r in results if r.get("status") == "dry_run"]

    problem_statuses = {
        "failed",
        "server_busy",
        "unknown",
    }
    problems = [
        r for r in results if r.get("status") in problem_statuses
    ]

    source_text = " / ".join(sources) if sources else "不明"
    is_restricted_code = bool(requirements_not_met)

    title = (
        "👑 **VIP・条件付きギフトコードの交換が完了しました**"
        if is_restricted_code
        else "✅ **ギフトコードの自動交換が完了しました**"
    )

    lines = [
        title,
        f"**コード：** `{code}`",
        f"**検出元：** {source_text}",
        "",
        f"👥 対象：**{len(results)}人**",
        f"✅ 交換成功：**{len(success)}人**",
    ]

    if requirements_not_met:
        lines.append(
            f"👑 条件未達：**{len(requirements_not_met)}人**"
        )

    if dry_run:
        lines.append(f"🧪 テスト実行：**{len(dry_run)}人**")

    if already:
        lines.append(f"☑️ 交換済み：**{len(already)}人**")

    if problems:
        lines.extend(
            [
                "",
                f"❌ **要確認（{len(problems)}人）**",
            ]
        )
        for item in problems:
            name = item.get("name", "Unknown")
            message = item.get("message", "")
            lines.append(f"• {name}")
            if message:
                lines.append(f"  └ {message}")

    # VIP／条件付きコードでは対象外ユーザーの一覧を添付しない。
    if not is_restricted_code:
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
        webhook_url=DISCORD_WEBHOOK_URL,
        attachment=None if is_restricted_code else summary_file,
    )


def send_source_error_notification(errors: dict[str, str]) -> None:
    """取得元エラーを通知する。（エラー専用チャンネル）"""
    if not errors:
        return

    lines = [
        "⚠️ **537 Gift Bot・取得元エラー**",
        "ギフトコード取得元でエラーが発生しました。",
        "",
    ]

    for source, error in errors.items():
        lines.append(f"• **{source}**: {error[:500]}")

    # DISCORD_ERROR_WEBHOOK_URL が未設定の場合は
    # 通常チャンネルにフォールバックする（通知が完全に消えるのを防ぐため）。
    error_webhook = DISCORD_ERROR_WEBHOOK_URL or DISCORD_WEBHOOK_URL
    if not DISCORD_ERROR_WEBHOOK_URL:
        print(
            "[WARN] DISCORD_ERROR_WEBHOOK_URL が未設定のため、"
            "通常チャンネルにフォールバックします。"
        )

    _post_webhook(
        {
            "username": "537 Gift Bot",
            "content": "\n".join(lines),
            "allowed_mentions": {"parse": []},
        },
        webhook_url=error_webhook,
    )
