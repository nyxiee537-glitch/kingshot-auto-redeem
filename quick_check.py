from __future__ import annotations

import json
import os

from config import SEEN_CODES_FILE
from sources import collect_sources


def write_output(should_run: bool, reason: str) -> None:
    """GitHub Actions に重い交換処理を続けるか通知する。"""
    value = "true" if should_run else "false"
    output_file = os.environ.get("GITHUB_OUTPUT", "").strip()

    if output_file:
        with open(output_file, "a", encoding="utf-8") as file_handle:
            file_handle.write(f"should_run={value}\n")
            file_handle.write(f"reason={reason}\n")

    print(f"should_run={value}")
    print(f"reason={reason}")


def load_seen_codes() -> tuple[bool, set[str]]:
    if not SEEN_CODES_FILE.exists():
        return False, set()

    try:
        data = json.loads(SEEN_CODES_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False, set()

    initialized = bool(data.get("initialized", False))
    seen_codes = {
        str(code).strip()
        for code in data.get("seen_codes", [])
        if str(code).strip()
    }
    return initialized, seen_codes


def main() -> int:
    """
    Playwright を入れる前に、取得元だけを軽く確認する。

    新コードなし: 重い処理をスキップ
    新コードあり: Playwright を入れて通常処理へ進む
    取得元エラー: fallback とエラー通知を維持するため通常処理へ進む
    """
    initialized, seen_codes = load_seen_codes()

    if not initialized:
        write_output(True, "state_not_initialized")
        return 0

    sources, errors = collect_sources()

    # 片方でも取得元が失敗した場合は、通常処理側で再確認し、
    # 必要ならDiscordへ取得元エラーを通知する。
    if errors or not sources:
        write_output(True, "source_error")
        return 0

    current_codes: set[str] = set()
    for codes in sources.values():
        current_codes.update(codes)

    new_codes = sorted(current_codes - seen_codes, key=str.casefold)

    if new_codes:
        print(f"新しいギフトコード候補: {new_codes}")
        write_output(True, "new_code")
    else:
        print("新しいギフトコードはありません。")
        write_output(False, "no_new_code")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
