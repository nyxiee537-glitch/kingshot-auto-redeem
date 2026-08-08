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

    has_retryable = any(
        item.get("status") in retryable_statuses
        for item in summary.get("results", [])
    )

    # failed は無効/期限切れ等も含むため、
    # server_busy/unknown のような一時エラーだけ15分後再試行する。
    fully_processed = (
        completed.returncode == 0
        and not has_retryable
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

        try:
            send_redeem_notification(
                code=code,
                sources=detected_by,
                summary=summary,
                summary_file=SUMMARY_TEXT_FILE,
            )
        except Exception as exc:
            print(f"[WARN] Discord notification failed: {exc}")

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
