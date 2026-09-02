from __future__ import annotations

import os
from pathlib import Path

# Gift-code sources
KINGSHOT_NET_API = "https://kingshot.net/api/gift-codes"
KINGSHOT_WIKI_URL = "https://kingshotwiki.com/giftcodes/"

# Official redeem page
REDEEM_URL = "https://ks-giftcode.centurygame.com/"

# Local state/output
SEEN_CODES_FILE = Path("seen_codes.json")
RESULTS_DIR = Path("redeem-results")
SUMMARY_TEXT_FILE = Path("redeem-summary.txt")
SUMMARY_JSON_FILE = Path("redeem-summary.json")

# HTTP
HTTP_TIMEOUT = 20
USER_AGENT = "Mozilla/5.0 (compatible; KingShot537GiftBot/1.0)"

# Redeem retry behaviour
MAX_SERVER_BUSY_RETRIES = 3
SERVER_BUSY_RETRY_DELAYS = (5, 10, 20)
RESULT_WAIT_SECONDS = 5
PLAYER_INTERVAL_SECONDS = 3
PARALLEL_WORKERS = 2

# Runtime
DRY_RUN = os.environ.get("DRY_RUN", "false").strip().casefold() in {
    "true", "1", "yes", "on"
}
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
