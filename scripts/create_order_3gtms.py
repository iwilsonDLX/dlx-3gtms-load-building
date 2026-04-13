#!/usr/bin/env python3
"""
create_order_3gtms.py

Automates order creation in 3GTMS from a structured load data dictionary.
Credentials are never hardcoded — loaded from config.json.

Usage:
    py scripts/create_order_3gtms.py
    py scripts/create_order_3gtms.py --data data/load_data.json
    py scripts/create_order_3gtms.py --config config.json
"""

import json
import argparse
from pathlib import Path
from playwright.sync_api import (
    Playwright,
    sync_playwright,
    TimeoutError as PlaywrightTimeoutError,
)

# ─── Screenshot directory ──────────────────────────────────────────────────────
SCREENSHOT_DIR = Path("C:/tmp/order_steps")

# ─── Value maps ────────────────────────────────────────────────────────────────
# Maps human-readable HU type name → 3GTMS dropdown option value
HU_TYPE_MAP = {
    "Pallet": "3",
    # Add others as discovered by inspecting the dropdown in 3GTMS:
    # "Box": "1", "Drum": "4", "Pail": "5", etc.
}

# Maps human-readable reference type name → 3GTMS dropdown option value
REF_TYPE_MAP = {
    "Customer PO Number": "567",
    # Add others as discovered
}

# ─── Default test data ─────────────────────────────────────────────────────────
DEFAULT_LOAD_DATA = {
    "shipper_search":    "Demo Location",   # text to type in shipper autocomplete
    "receiver_search":   "Lowes",           # text to type in receiver autocomplete
    "earliest_ship":     "04/13/2026",      # MM/DD/YYYY
    "latest_ship":       "04/13/2026",
    "earliest_delivery": "04/15/2026",
    "latest_delivery":   "04/15/2026",
    "description":       "Generators",
    "gross_weight":      "20000",
    "net_weight":        "20000",
    "hu_count":          "1",
    "hu_type":           "Pallet",
    "piece_count":       "1",
    "reference_numbers": [
        {"type": "Customer PO Number", "value": "Customer1234567"}
    ],
}


# ─── Helpers ───────────────────────────────────────────────────────────────────

def take_screenshot(page, step: int, label: str) -> None:
    """Save a numbered screenshot to C:/tmp/order_steps/."""
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = SCREENSHOT_DIR / f"{step:02d}_{label}.png"
    try:
        page.screenshot(path=str(path))
        print(f"    [screenshot] {path.name}")
    except Exception as e:
        print(f"    [screenshot failed] {label}: {e}")


def autocomplete_select(frame, field_id: str, search_text: str) -> None:
    """
    Fill an autocomplete field, trigger the search, and click the first result.
    Waits for the dropdown link to appear before clicking.
    """
    field = frame.locator(field_id)
    field.click()
    field.fill(search_text)
    field.press("Enter")
    # Wait for at least one link to appear in the dropdown
    first_result = frame.get_by_role("link").first
    first_result.wait_for(timeout=10_000)
    first_result.click()


def select_date_by_calendar(frame, calendar_index: int, date_str: str) -> None:
    """
    Open the Nth calendar widget (0-indexed) and click the target day.

    Args:
        frame: FrameLocator for the form iframe
        calendar_index: 0=earliest_ship, 1=latest_ship, 2=earliest_delivery, 3=latest_delivery
        date_str: Date in MM/DD/YYYY format

    NOTE: Assumes the calendar is already showing the correct month.
    Cross-month navigation would require additional logic.
    """
    day = str(int(date_str.split("/")[1]))  # strip leading zero (e.g. "04" → "4" → "4")
    frame.locator(".jqx-icon-calendar").nth(calendar_index).click()
    frame.get_by_role("gridcell", name=day).click()


def load_config(config_path: str) -> dict:
    """
    Load 3GTMS URL and credentials from a JSON config file.
    Required keys: url, username, password
    """
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(
            f"Config file not found: {config_path}\n"
            f"Create it from data/config.json.example — never commit real credentials."
        )
    with open(path) as f:
        return json.load(f)


# ─── Core automation ───────────────────────────────────────────────────────────

def create_order(playwright: Playwright, load_data: dict, config: dict) -> None:
    browser = playwright.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()

    # Close any popup that opens automatically (e.g. on prod login redirect)
    page.on("popup", lambda popup: popup.close())

    try:
        # ── Step 1: Login ───────────────────────────────────────────────────
        print("[1/8] Logging in to 3GTMS...")
        page.goto(config["url"], wait_until="networkidle")
        page.get_by_role("textbox", name="* Username:").fill(config["username"])
        page.get_by_role("textbox", name="* Password:").fill(config["password"])
        page.get_by_role("button", name="Login").click()
        page.wait_for_load_state("networkidle")
        take_screenshot(page, 1, "logged_in")

        # ── Step 2: Open Add Order form ─────────────────────────────────────
        print("[2/8] Opening Add Order form...")
        page.get_by_role("button", name="Add Order").click()
        page.wait_for_load_state("networkidle")
        frame = page.locator("iframe[name='Form']").content_frame
        take_screenshot(page, 2, "add_order_form_open")

        # ── Step 3: Shipper and Receiver (autocomplete fields) ──────────────
        print("[3/8] Setting shipper and receiver...")
        autocomplete_select(frame, "#robustSearchText_sourceId",      load_data["shipper_search"])
        autocomplete_select(frame, "#robustSearchText_destinationId",  load_data["receiver_search"])
        take_screenshot(page, 3, "shipper_receiver_set")

        # ── Step 4: Ship and delivery dates ────────────────────────────────
        print("[4/8] Setting dates...")
        select_date_by_calendar(frame, 0, load_data["earliest_ship"])
        select_date_by_calendar(frame, 1, load_data["latest_ship"])
        select_date_by_calendar(frame, 2, load_data["earliest_delivery"])
        select_date_by_calendar(frame, 3, load_data["latest_delivery"])
        take_screenshot(page, 4, "dates_set")

        # ── Step 5: Order line ──────────────────────────────────────────────
        print("[5/8] Adding order line...")
        frame.get_by_role("button", name="Add Order Line").click()
        frame.get_by_role("textbox", name="Description:").wait_for(timeout=10_000)

        frame.get_by_role("textbox", name="Description:").fill(load_data["description"])
        frame.get_by_role("textbox", name="Gross Wt:").fill(load_data["gross_weight"])
        frame.get_by_role("textbox", name="Net Wt:").fill(load_data["net_weight"])
        frame.get_by_role("textbox", name="HU Count:").fill(load_data["hu_count"])

        hu_option = HU_TYPE_MAP.get(load_data["hu_type"])
        if not hu_option:
            raise ValueError(
                f"Unknown HU type '{load_data['hu_type']}'. "
                f"Add it to HU_TYPE_MAP. Known types: {list(HU_TYPE_MAP.keys())}"
            )
        frame.locator("#handlingUnitTypeIdEditor_handlingUnitTypeIdEditor").select_option(hu_option)

        piece_count = load_data.get("piece_count", "")
        if piece_count:
            frame.get_by_role("textbox", name="Piece Count:").fill(piece_count)

        frame.get_by_role("button", name="Save & Close").click()
        take_screenshot(page, 5, "order_line_saved")

        # ── Step 6: Reference numbers ───────────────────────────────────────
        print("[6/8] Adding reference numbers...")
        for i, ref in enumerate(load_data.get("reference_numbers", [])):
            frame.get_by_role("button", name=" Add Another Reference Number").click()

            ref_option = REF_TYPE_MAP.get(ref["type"])
            if not ref_option:
                raise ValueError(
                    f"Unknown reference type '{ref['type']}'. "
                    f"Add it to REF_TYPE_MAP. Known types: {list(REF_TYPE_MAP.keys())}"
                )
            frame.locator(f"#rnSelect{i}").select_option(ref_option)
            frame.get_by_role("textbox", name="Value").nth(i).fill(ref["value"])

        take_screenshot(page, 6, "reference_numbers_added")

        # ── Step 7: Get rates ───────────────────────────────────────────────
        print("[7/8] Getting rates...")
        frame.get_by_role("button", name="Get Rates").click()
        page.wait_for_load_state("networkidle")
        take_screenshot(page, 7, "rates_returned")

        # ── Step 8: Select rate and save ────────────────────────────────────
        print("[8/8] Selecting rate and saving order...")
        frame.locator(".jqx-checkbox-default").first.click()
        frame.get_by_role("button", name="Select & Save Order").click()
        page.wait_for_load_state("networkidle")
        take_screenshot(page, 8, "order_saved")

        print("\n[DONE] Order created successfully.")

    except Exception as e:
        take_screenshot(page, 99, "error_state")
        print(f"\n[ERROR] {type(e).__name__}: {e}")
        raise

    finally:
        context.close()
        browser.close()


# ─── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Create a 3GTMS order from load data.")
    parser.add_argument("--data",   default=None,          help="Path to load data JSON file")
    parser.add_argument("--config", default="config.json", help="Path to credentials config JSON")
    args = parser.parse_args()

    if args.data:
        with open(args.data) as f:
            load_data = json.load(f)
        print(f"[INFO] Using load data from: {args.data}")
    else:
        print("[INFO] No --data file given. Using built-in test data.")
        load_data = DEFAULT_LOAD_DATA

    config = load_config(args.config)

    with sync_playwright() as playwright:
        create_order(playwright, load_data, config)


if __name__ == "__main__":
    main()
