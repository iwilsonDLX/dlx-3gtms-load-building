# 3GTMS Load Building Automation - Project Instructions

## Project Overview
This project automates load creation in 3GTMS using Playwright. 
Source data comes from supplier tender emails parsed by Claude API.

## 3GTMS Environment
- **Sandbox URL:** https://shipdlx-sb.3gtms.com/web/login?lk=dlx
- **Login:** Iwilson / Iwilson1 (sandbox only - never use prod credentials in code)
- **Navigation to Create Order:** Click "Orders" in top ribbon → click "+" icon far left

## Form Field Notes
- **Client** is an optional autocomplete field — only fill if provided in the load data
- **Shipper, Receiver** are autocomplete fields — type value, wait for 
  dropdown, click closest match
- **Origin Location, Destination Location** are autocomplete fields — same behavior
- **Delivery date = same as ship date** unless otherwise specified
- **Receiver contact auto-populates** when destination location is selected
- **Order Line** requires clicking "Add Order Line" button — opens a popup modal

## Folder Structure
- `recordings/` — raw Playwright codegen output
- `scripts/` — cleaned, production-ready Python scripts
- `data/` — sample emails and JSON test data

## Coding Standards
- Always use `py` instead of `python` command on this machine
- Save screenshots to `C:/tmp/order_steps/` at each major step
- Use descriptive file names (e.g. `create_order_regal_rexnord.py`)
- Always wait for network idle after navigation steps
- Use try/catch on all form interactions

## Email Parsing
- Origin address is typically in the sender's email signature
- Delivery date defaults to same day as ship date
- Required fields: Shipper, Origin, Receiver, Destination, 
  Ship Date, Commodity, NMFC, Freight Class, Weight, Piece Count, Dimensions
- Optional fields: Client (fill only when present in the source data)

## GitHub
- Repository: https://github.com/iwilsonDLX/dlx-playwright-automations
- Commit and push after every completed working script
- Use descriptive commit messages referencing the client/task
