from __future__ import annotations
import os
from pathlib import Path

KINGSHOT_NET_API="https://kingshot.net/api/gift-codes"
KINGSHOT_WIKI_URL="https://kingshotwiki.com/giftcodes/"
SEEN_CODES_FILE=Path("seen_codes.json")
RESULTS_DIR=Path("redeem-results")
SUMMARY_TEXT_FILE=Path("redeem-summary.txt")
SUMMARY_JSON_FILE=Path("redeem-summary.json")
HTTP_TIMEOUT=20
USER_AGENT="Mozilla/5.0 (compatible; KingShot537GiftBot/2.0)"

GIFT_API_URL="https://kingshot-giftcode.centurygame.com/api/gift_code"
GIFT_API_ENCRYPT_KEY="mN4!pQs6JrYwV9"
API_PLAYER_INTERVAL_SECONDS=1.5
API_MAX_RETRIES=3
API_RETRY_DELAY_SECONDS=2
API_RATE_LIMIT_RETRY_SECONDS=60
API_RATE_LIMIT_MAX_RETRIES=3
API_RETRY_COOLDOWN_SECONDS=60
API_RUN_BUDGET_SECONDS=1020  # 17 minutes inside redeem.py
API_FINISH_MARGIN_SECONDS=90
REDEEM_PROGRESS_FILE=Path("redeem-progress.json")
API_CONSECUTIVE_FAILURE_LIMIT=10
VALIDATION_NORMAL_PLAYER_ID=os.environ.get("VALIDATION_NORMAL_PLAYER_ID","").strip()
VALIDATION_VIP_PLAYER_ID=os.environ.get("VALIDATION_VIP_PLAYER_ID","").strip()

DISCORD_WEBHOOK_URL=os.environ.get("DISCORD_WEBHOOK_URL","").strip()
DISCORD_ERROR_WEBHOOK_URL=os.environ.get("DISCORD_ERROR_WEBHOOK_URL","").strip()
