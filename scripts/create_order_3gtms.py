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

import re
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
    "shipper_search":    "Demo Location",                    # text to type in shipper autocomplete
    "origin":            "1000 Industrial Park Holstein IA 51025",  # used to score dropdown results
    "receiver_search":   "Lowes",                           # text to type in receiver autocomplete
    "destination":       "5758 Sunnybrook Dr Sioux City IA 51106",  # used to score dropdown results
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


def autocomplete_select(frame, field_id: str, search_text: str, match_hint: str = None) -> None:
    """
    Fill an autocomplete field, trigger the search, then click the dropdown result
    whose visible text best matches match_hint (falls back to search_text if omitted).

    Scopes the candidate links to the jQWidgets popup that appears directly below
    the input, avoiding page-level nav links and other unrelated anchors.

    Scoring: tokenises match_hint on whitespace and commas, then counts how many
    tokens appear in each result's text. The highest-scoring result wins. Ties and
    zero-score cases fall back to the first result so the function never deadlocks.

    Args:
        frame:       FrameLocator for the containing iframe.
        field_id:    CSS selector for the autocomplete input (e.g. "#robustSearchText_sourceId").
        search_text: Text to type into the field to trigger the search.
        match_hint:  Full address or any additional text used to score results
                     (e.g. "1000 Industrial Park Holstein IA 51025"). Optional —
                     when omitted, search_text is used for scoring instead.
    """
    field = frame.locator(field_id)
    field.click()
    field.fill(search_text)
    field.press("Enter")

    # Wait for the jQWidgets popup that contains the search results to become
    # visible. Scoping to this container prevents matching nav links and other
    # page-level anchors (e.g. "Comments & Special Instructions").
    popup = frame.locator(".jqx-popup").filter(has=frame.locator("a")).first
    try:
        popup.wait_for(state="visible", timeout=10_000)
        result_links = popup.get_by_role("link").all()
    except PlaywrightTimeoutError:
        # Fallback: popup class not found — collect all links as before
        print(f"    [autocomplete] WARNING: popup container not found, falling back to page-wide link search")
        result_links = frame.get_by_role("link").all()

    if not result_links:
        raise RuntimeError(f"No autocomplete results appeared for '{search_text}'")

    # Tokenise the hint (or search text) — lowercase, split on whitespace and commas
    hint = (match_hint or search_text).lower()
    tokens = [t for t in re.split(r"[\s,]+", hint) if t]

    best_link = result_links[0]   # fallback: first result
    best_score = -1

    for link in result_links:
        text = (link.text_content() or "").lower()
        score = sum(1 for token in tokens if token in text)
        if score > best_score:
            best_score = score
            best_link = link

    chosen_text = (best_link.text_content() or "").strip()
    print(f"    [autocomplete] score={best_score}  selected='{chosen_text}'")
    best_link.click()


def fill_date(frame, field_index: int, date_str: str) -> None:
    """
    Type a date directly into the Nth jqx-datetimeinput field (0-indexed).

    Fields in order: 0=earliest_ship, 1=latest_ship, 2=earliest_delivery, 3=latest_delivery

    Args:
        frame:       FrameLocator for the form iframe.
        field_index: 0-based index of the date field.
        date_str:    Date in MM/DD/YYYY format.
    """
    frame.locator(".jqx-datetimeinput").nth(field_index).locator("input").fill(date_str)


def _parse_dollar(text: str) -> float:
    """
    Parse a dollar amount string into a float.
    Handles formats like '$1,234.56', '1234.56', '$1,234'.
    Returns float('inf') if no numeric value can be extracted.
    """
    cleaned = re.sub(r'[^\d.]', '', text)
    try:
        return float(cleaned)
    except ValueError:
        return float("inf")


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
        autocomplete_select(frame, "#robustSearchText_sourceId",     load_data["shipper_search"],  load_data.get("origin"))
        autocomplete_select(frame, "#robustSearchText_destinationId", load_data["receiver_search"], load_data.get("destination"))
        take_screenshot(page, 3, "shipper_receiver_set")

        # ── Step 4: Ship and delivery dates ────────────────────────────────
        print("[4/8] Setting dates...")
        fill_date(frame, 0, load_data["earliest_ship"])
        fill_date(frame, 1, load_data["latest_ship"])
        fill_date(frame, 2, load_data["earliest_delivery"])
        fill_date(frame, 3, load_data["latest_delivery"])
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

        # ── Step 8: Handle orderRatingPopup and save ───────────────────────
        print("[8/8] Selecting rate and saving order...")

        # Wait for the rating popup modal to be fully visible
        popup = frame.locator("#orderRatingPopup")
        popup.wait_for(state="visible", timeout=15_000)
        take_screenshot(page, 8, "rate_popup_visible")

        # Wait for the loading spinner to disappear before reading any rows.
        # Rates can take time to return from carriers — use a 30 s timeout.
        print("    [rates] Waiting for rates to finish loading...")
        popup.locator(".loading, .jqx-loader, [class*='loading'], :text('Loading...')").wait_for(
            state="hidden", timeout=30_000
        )
        # Additional buffer for row DOM to fully render after spinner clears
        page.wait_for_timeout(2_000)
        take_screenshot(page, 8, "rates_loaded")

        # Collect selectable carrier rows — jqxGrid data rows carry a row-id attribute;
        # expansion/detail rows (rendered by rowdetails) do not, so this naturally
        # excludes them without needing a fragile filter(has=...) call.
        rate_rows = popup.locator("[role='row'][row-id]")
        count = rate_rows.count()
        if count == 0:
            raise RuntimeError(
                "No selectable rate rows found in #orderRatingPopup. "
                "Check whether the popup uses a different row structure."
            )
        print(f"    [rates] {count} carrier(s) returned")

        if count == 1:
            # Only one rate available — select it automatically
            rate_rows.first.locator(".jqx-checkbox-default").click()
            print("    [rates] Single rate — selected automatically")
        else:
            # Multiple rates: parse the net charge (red amount) from each row
            # and select the row with the lowest value
            best_idx = 0
            best_amount = float("inf")

            for i in range(count):
                row = rate_rows.nth(i)

                # Red amounts in 3GTMS use inline color styles
                red_el = row.locator(
                    "[style*='color: red'], [style*='color:red'], "
                    "[style*='color:#ff0000'], [style*='color: #ff0000']"
                )

                if red_el.count() > 0:
                    raw = red_el.first.text_content() or ""
                else:
                    # Fallback: scan row for all dollar amounts; net charge is
                    # typically the last (rightmost) figure in the row
                    all_amounts = re.findall(r'\$[\d,]+\.?\d*', row.text_content() or "")
                    raw = all_amounts[-1] if all_amounts else ""

                amount = _parse_dollar(raw)
                print(f"    [rates] row {i}: {raw!r} -> {amount:.2f}")

                if amount < best_amount:
                    best_amount = amount
                    best_idx = i

            rate_rows.nth(best_idx).locator(".jqx-checkbox-default").click()
            print(f"    [rates] Selected row {best_idx} (lowest net charge: ${best_amount:,.2f})")

        take_screenshot(page, 9, "rate_selected")

        # Click the confirm/assign button inside the popup to finalize
        popup.get_by_role("button", name="Select & Save Order").click()
        page.wait_for_load_state("networkidle")
        take_screenshot(page, 10, "order_saved")

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
