from __future__ import annotations

import json
import os
import subprocess
import sys

from config import (
    SEEN_CODES_FILE,
    SUMMARY_JSON_FILE,
    SUMMARY_TEXT_FILE,
)
from notifier import (
    send_redeem_notification,
    send_source_error_notification,
)
from sources import collect_sources


def load_state() -> tuple[bool, set[str]]:
    if not SEEN_CODES_FILE.exists():
        return False, set()

    try:
        data = json.loads(
            SEEN_CODES_FILE.read_text(encoding="utf-8")
        )
    except (json.JSONDecodeError, OSError):
        return False, set()

    initialized = bool(data.get("initialized", False))
    seen = {
        str(code).strip()
        for code in data.get("seen_codes", [])
        if str(code).strip()
    }

    return initialized, seen


def save_state(
    codes: set[str],
    initialized: bool = True,
) -> None:
    SEEN_CODES_FILE.write_text(
        json.dumps(
            {
                "initialized": initialized,
                "seen_codes": sorted(
                    codes,
                    key=str.casefold,
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def run_redeemer(code: str) -> tuple[bool, dict]:
    env = os.environ.copy()
    env["GIFT_CODE"] = code
    env.setdefault("DRY_RUN", "false")

    for path in (
        SUMMARY_JSON_FILE,
        SUMMARY_TEXT_FILE,
    ):
        if path.exists():
            path.unlink()

    completed = subprocess.run(
        [sys.executable, "redeem.py"],
        env=env,
        check=False,
    )

    if not SUMMARY_JSON_FILE.exists():
        return False, {}

    summary = json.loads(
        SUMMARY_JSON_FILE.read_text(encoding="utf-8")
    )

    retryable_statuses = {
        "server_busy",
        "unknown",
    }

    terminal_statuses = {
        "success",
        "already_redeemed",
        "failed",
        "requirements_not_met",
    }

    results = summary.get("results", [])

    has_retryable = any(
        item.get("status") in retryable_statuses
        for item in results
    )

    has_unexpected_status = any(
        item.get("status")
        not in (retryable_statuses | terminal_statuses)
        for item in results
    )

    # success / already_redeemed / failed は確定結果として扱う。
    # redeem.py が「全員 failed」で非0終了しても、
    # server_busy / unknown が残っていなければ Seen に保存する。
    #
    # 再試行するのは server_busy / unknown、
    # または想定外ステータス・結果なしの場合だけ。
    fully_processed = (
        bool(results)
        and not has_retryable
        and not has_unexpected_status
    )

    if completed.returncode != 0 and fully_processed:
        print(
            "[INFO] redeem.py は非0終了でしたが、"
            "結果はすべて確定ステータスのため処理済みとして扱います。"
        )

    return fully_processed, summary


def main() -> int:
    sources, errors = collect_sources()

    if errors:
        # 片方だけ失敗した場合も警告を出す。
        try:
            send_source_error_notification(errors)
        except Exception as exc:
            print(f"[WARN] Discord source-error notification failed: {exc}")

    if not sources:
        print("[ERROR] 全取得元が失敗しました。")
        return 1

    all_codes: set[str] = set()

    for codes in sources.values():
        all_codes.update(codes)

    initialized, seen = load_state()

    # 初回は現在掲載中のコードを基準値として保存。
    # 既存コードを突然全員へ交換しないための安全策。
    if not initialized:
        save_state(all_codes, initialized=True)
        print(
            "[BOOTSTRAP] 現在のコードを初期値として保存しました。"
            "交換処理は行いません。"
        )
        return 0

    new_codes = sorted(
        all_codes - seen,
        key=str.casefold,
    )

    if not new_codes:
        print("No new gift codes.")
        return 0

    print(f"NEW code(s): {new_codes}")

    for code in new_codes:
        detected_by = [
            source_name
            for source_name, codes in sources.items()
            if code in codes
        ]

        print(
            f"\nNEW: {code} | "
            f"source: {', '.join(detected_by)}"
        )

        processed, summary = run_redeemer(code)

        summary_counts = summary.get("counts", {})
        success_count = int(summary_counts.get("success", 0))
        already_count = int(
            summary_counts.get("already_redeemed", 0)
        )

        # Success / Already Redeemed が1件もない場合は
        # 一時的にDiscord通知を送らない。
        if success_count > 0 or already_count > 0:
            try:
                send_redeem_notification(
                    code=code,
                    sources=detected_by,
                    summary=summary,
                    summary_file=SUMMARY_TEXT_FILE,
                )
            except Exception as exc:
                print(
                    f"[WARN] Discord notification failed: {exc}"
                )
        else:
            print(
                "Discord通知をスキップしました "
                "(Success=0, AlreadyRedeemed=0)"
            )

        if processed:
            seen.add(code)
            save_state(seen, initialized=True)
            print(f"✅ Seenに保存: {code}")
        else:
            print(
                f"⏳ {code} は一時エラーが残っているため"
                "Seenに保存しません。次回再試行します。"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
