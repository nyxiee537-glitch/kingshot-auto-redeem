from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config import (
    SEEN_CODES_FILE,
    SUMMARY_JSON_FILE,
    SUMMARY_TEXT_FILE,
)
from notifier import (
    send_detection_notification,
    send_redeem_notification,
    send_source_error_notification,
)
from sources import collect_sources

PENDING_CODES_FILE = Path("pending_codes.json")

# GitHub Actions の timeout が 20 分なので、
# 途中停止した処理は 30 分後から再取得できるようにする。
PROCESSING_STALE_MINUTES = 30


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_datetime(value: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def load_state() -> tuple[bool, set[str], dict[str, str]]:
    if not SEEN_CODES_FILE.exists():
        return False, set(), {}

    try:
        data = json.loads(
            SEEN_CODES_FILE.read_text(encoding="utf-8")
        )
    except (json.JSONDecodeError, OSError):
        return False, set(), {}

    initialized = bool(data.get("initialized", False))
    seen = {
        str(code).strip()
        for code in data.get("seen_codes", [])
        if str(code).strip()
    }

    raw_processing = data.get("processing_codes", {})
    processing: dict[str, str] = {}
    if isinstance(raw_processing, dict):
        for code, claimed_at in raw_processing.items():
            clean_code = str(code).strip()
            clean_time = str(claimed_at).strip()
            if clean_code and clean_time:
                processing[clean_code] = clean_time

    return initialized, seen, processing


def save_state(
    seen: set[str],
    processing: dict[str, str],
    initialized: bool = True,
) -> None:
    SEEN_CODES_FILE.write_text(
        json.dumps(
            {
                "initialized": initialized,
                "seen_codes": sorted(
                    seen,
                    key=str.casefold,
                ),
                "processing_codes": {
                    code: processing[code]
                    for code in sorted(
                        processing,
                        key=str.casefold,
                    )
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def remove_stale_processing(
    processing: dict[str, str],
) -> list[str]:
    now = utc_now()
    stale_before = now - timedelta(
        minutes=PROCESSING_STALE_MINUTES
    )
    stale_codes: list[str] = []
    for code, claimed_at in list(processing.items()):
        claimed_dt = parse_datetime(claimed_at)
        # 壊れた日時も stale として扱い、永久ロックを防ぐ。
        if claimed_dt is None or claimed_dt <= stale_before:
            stale_codes.append(code)
            processing.pop(code, None)
    return stale_codes


def save_pending_codes(
    pending: list[dict[str, object]],
) -> None:
    PENDING_CODES_FILE.write_text(
        json.dumps(
            pending,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def load_pending_codes() -> list[dict[str, object]]:
    if not PENDING_CODES_FILE.exists():
        return []

    try:
        data = json.loads(
            PENDING_CODES_FILE.read_text(encoding="utf-8")
        )
    except (json.JSONDecodeError, OSError):
        return []

    if not isinstance(data, list):
        return []

    return [
        item
        for item in data
        if isinstance(item, dict)
        and str(item.get("code", "")).strip()
    ]


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

    try:
        summary = json.loads(
            SUMMARY_JSON_FILE.read_text(encoding="utf-8")
        )
    except (json.JSONDecodeError, OSError):
        return False, {}

    retryable_statuses = {
        "server_busy",
        "unknown",
    }
    has_retryable = any(
        item.get("status") in retryable_statuses
        for item in summary.get("results", [])
    )

    # failed は無効/期限切れ等も含むため、
    # server_busy/unknown のような一時エラーだけ次回再試行する。
    fully_processed = (
        completed.returncode == 0
        and not has_retryable
    )

    return fully_processed, summary


def claim_new_codes() -> int:
    # 前回の pending ファイルがローカルに残っていても使わない。
    if PENDING_CODES_FILE.exists():
        PENDING_CODES_FILE.unlink()

    sources, errors = collect_sources()

    if errors:
        try:
            send_source_error_notification(errors)
        except Exception as exc:
            print(
                "[WARN] Discord source-error "
                f"notification failed: {exc}"
            )

    if not sources:
        print("[ERROR] 全取得元が失敗しました。")
        return 1

    all_codes: set[str] = set()
    for codes in sources.values():
        all_codes.update(codes)

    initialized, seen, processing = load_state()

    # 初回は現在掲載中のコードを基準値として保存。
    # 既存コードを突然全員へ交換しないための安全策。
    if not initialized:
        save_state(
            seen=all_codes,
            processing={},
            initialized=True,
        )
        print(
            "[BOOTSTRAP] 現在のコードを初期値として保存しました。"
            "交換処理は行いません。"
        )
        return 0

    stale_codes = remove_stale_processing(processing)
    if stale_codes:
        print(
            "[RECOVER] 期限切れの processing を解除: "
            + ", ".join(
                sorted(stale_codes, key=str.casefold)
            )
        )

    blocked_codes = seen | set(processing)
    new_codes = sorted(
        all_codes - blocked_codes,
        key=str.casefold,
    )

    if not new_codes:
        # stale の掃除だけ発生した場合も state を保存する。
        save_state(
            seen=seen,
            processing=processing,
            initialized=True,
        )
        print("No new gift codes.")
        return 0

    print(f"NEW code(s): {new_codes}")

    pending: list[dict[str, object]] = []
    claimed_at = utc_now().isoformat()

    for code in new_codes:
        detected_by = [
            source_name
            for source_name, codes in sources.items()
            if code in codes
        ]
        processing[code] = claimed_at
        pending.append(
            {
                "code": code,
                "sources": detected_by,
            }
        )
        print(
            f"🔒 CLAIM: {code} | "
            f"source: {', '.join(detected_by)}"
        )
        # 新規コードを検出した時点で通知する。
        try:
            send_detection_notification(
                code=code,
                sources=detected_by,
            )
        except Exception as exc:
            print(
                "[WARN] Discord detection "
                f"notification failed: {exc}"
            )

    # 交換より先に「処理中」を state に書く。
    save_state(
        seen=seen,
        processing=processing,
        initialized=True,
    )
    save_pending_codes(pending)

    print(
        f"✅ {len(pending)} code(s) を processing として確保しました。"
    )
    return 0


def redeem_pending_codes() -> int:
    pending = load_pending_codes()
    if not pending:
        print("No claimed gift codes to redeem.")
        return 0

    initialized, seen, processing = load_state()
    if not initialized:
        print(
            "[ERROR] state が初期化されていません。"
            "交換処理を中止します。"
        )
        return 1

    for item in pending:
        code = str(item.get("code", "")).strip()
        raw_sources = item.get("sources", [])
        detected_by = (
            [str(x) for x in raw_sources]
            if isinstance(raw_sources, list)
            else []
        )

        # claim が state に存在しない場合は安全のため実行しない。
        if code not in processing:
            print(
                f"⏭️ SKIP: {code} は processing に存在しません。"
            )
            continue

        print(
            f"\n▶ REDEEM: {code} | "
            f"source: {', '.join(detected_by)}"
        )
        processed, summary = run_redeemer(code)

        if processed:
            seen.add(code)
            processing.pop(code, None)
            save_state(
                seen=seen,
                processing=processing,
                initialized=True,
            )
            # server_busy / unknown が解消し、結果が確定した時だけ通知する。
            try:
                send_redeem_notification(
                    code=code,
                    sources=detected_by,
                    summary=summary,
                    summary_file=SUMMARY_TEXT_FILE,
                )
            except Exception as exc:
                print(
                    "[WARN] Discord notification failed: "
                    f"{exc}"
                )
            print(
                f"✅ 完了: {code} を Seen に保存し、"
                "processing から削除しました。"
            )
        else:
            # 一時エラーなら processing を解除。
            # 次の Cron で再度 claim して再試行できる。
            # ここでは通知しない（解決するまで何度も通知が飛ぶのを防ぐ）。
            processing.pop(code, None)
            save_state(
                seen=seen,
                processing=processing,
                initialized=True,
            )
            print(
                f"⏳ {code} は一時エラーが残っているため"
                "Seenに保存しません。次回再試行します。"
                "（通知は解消時のみ送信）"
            )

    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--claim",
        action="store_true",
        help="新コードを検出して processing として確保する",
    )
    mode.add_argument(
        "--redeem-pending",
        action="store_true",
        help="このRunで確保したコードを交換する",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.claim:
        return claim_new_codes()
    if args.redeem_pending:
        return redeem_pending_codes()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
