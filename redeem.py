from __future__ import annotations

import os
from playwright.sync_api import sync_playwright


REDEEM_URL = "https://ks-giftcode.centurygame.com/"


def main() -> None:
    player_id = os.environ["KINGSHOT_PLAYER_ID"]
    kingdom = os.environ["KINGSHOT_KINGDOM"]
    gift_code = os.environ.get("GIFT_CODE", "TEST_CODE")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})

        page.goto(REDEEM_URL, wait_until="networkidle", timeout=60_000)

        inputs = page.locator("input")

        print(f"Found {inputs.count()} input fields")

        inputs.nth(0).fill(player_id)
        inputs.nth(1).fill(kingdom)
        inputs.nth(2).fill(gift_code)

        page.screenshot(path="filled-form.png", full_page=True)

        print("Form fields filled successfully.")
        print("Confirm was NOT clicked during this test.")

        browser.close()


if __name__ == "__main__":
    main()
