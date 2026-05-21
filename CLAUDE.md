# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A single-file Flask web app (`app.py`) that lets travellers upload receipt photos, runs them through Google Gemini for OCR + structured extraction, converts the total to TWD, and appends the row to a per-user tab in a shared Google Sheet. The UI is server-rendered Jinja2 (`templates/index.html`, `templates/login.html`) with a Chart.js dashboard that calls `/api/stats`. All comments, labels, and prompt text are in Traditional Chinese — keep that convention when editing.

## Commands

```bash
# Install
pip install -r requirements.txt

# One-time bootstrap (run in this order, each writes its ID back into .env)
python setup_sheets.py     # creates the main expense spreadsheet → SPREADSHEET_ID
python setup_registry.py   # creates the user registry spreadsheet → REGISTRY_SPREADSHEET_ID

# Run (dev)
python app.py              # Flask debug server on 0.0.0.0:5001

# Run (prod, per Procfile)
gunicorn app:app --workers 2 --bind 0.0.0.0:$PORT --timeout 120
```

There is no test suite, linter, or formatter configured. `app.py` validates required env vars at startup and prints what's missing instead of crashing.

## Required environment

`.env` (loaded via `python-dotenv`):
- `GEMINI_API_KEY` — Google Generative AI key (model is hardcoded to `gemini-1.5-flash`)
- `SPREADSHEET_ID` — main spreadsheet holding one tab per user
- `REGISTRY_SPREADSHEET_ID` — registry sheet mapping email → name, pin_hash, tab name
- `GOOGLE_CREDENTIALS_FILE` (default `credentials.json`) **or** `GOOGLE_CREDENTIALS_JSON` (raw JSON, used in cloud deploys)
- `SECRET_KEY` — Flask session key; falls back to a random hex if unset (sessions won't survive restarts without it)

The service account email from `credentials.json` must be granted edit access on **both** spreadsheets.

## Architecture

**Two-spreadsheet, one-tab-per-user model.** There is no database. Everything persists in Google Sheets via `gspread`:

1. **Registry sheet** (`REGISTRY_SPREADSHEET_ID`, single tab): rows of `[email, name, sha256(pin), sheet_name, created_at]`. `get_user_by_email` does a linear scan; `verify_login` compares hashed PINs.
2. **Main sheet** (`SPREADSHEET_ID`, many tabs): on registration `create_user_tab` adds a new worksheet named after the user (truncated to 20 chars, suffixed `_2`, `_3`… on collision) with the 13-column `HEADERS` schema and styled header row. Every expense row lives in that user's own tab — there is no shared "all expenses" view.

**Session model.** After login, `session["user"]` holds `{email, name, picture}` and `session["sheet_name"]` holds the worksheet title. `get_user_sheet()` reads from session on every request, so all read/write helpers (`save_to_sheet`, `get_all_records`, `get_stats`, `get_trips`) implicitly scope to the logged-in user. Every protected route uses `@login_required`.

**Receipt pipeline.** `POST /upload` → `parse_receipt` sends the image bytes + a Chinese prompt to Gemini asking for a strict JSON schema (`store_name_original`, `store_name_zh`, `date`, `total_amount`, `currency`, `items`, `category`, `payment_method`, `region`, `notes`). Gemini sometimes wraps the response in ```` ``` ```` fences, so the parser strips them before `json.loads`. On 429/quota/rate errors it sleeps `10*(attempt+1)` seconds and retries up to 3× (non-rate errors raise immediately). `save_to_sheet` then converts to TWD using the hardcoded `EXCHANGE_RATES` table and appends the row. `POST /add` is the manual-entry equivalent that skips Gemini.

**Stats.** `get_stats(trip_name)` reads the whole user tab on every call and aggregates in Python (by category, by day, by payment method, top 10). There is no caching — Dashboard refreshes hit Sheets each time.

**Trip scoping.** The "旅程" (trip) column is a free-text label set per upload; filtering is substring match (`trip_name in r["trip"]`), not exact equality.

## Schema (column order matters)

`HEADERS` in `app.py` and `setup_sheets.py` must stay in sync, and `get_all_records` indexes by position (`row[0]..row[12]`):

```
日期 | 店名 | 原文店名 | 金額 | 幣別 | 台幣換算 | 類別 | 品項 | 支付方式 | 地區 | 旅程 | 備註 | 建立時間
```

Adding/reordering columns requires changes in **three** places: `HEADERS`, `save_to_sheet` (row assembly), and `get_all_records` (parsing).

## Things to know before editing

- **`setup_notion.py` and `啟動說明.md` are stale.** They reference an older Anthropic/Notion design. The live app uses Gemini + Google Sheets; ignore the Notion path unless you're deliberately reviving it. `notion-client` is not in `requirements.txt`.
- **Exchange rates are constants** (`EXCHANGE_RATES` dict). There's no FX API — update the dict manually if rates drift.
- **PIN hashing is plain SHA-256, no salt.** Acceptable only because this is a personal-scale tool; don't claim it's production-grade auth.
- **`MAX_CONTENT_LENGTH` is 20 MB.** Larger uploads return Flask's default 413.
- **Default port is 5001**, not 5000 (macOS AirPlay conflict).
- **All user-facing strings are zh-TW.** New error messages, categories, and prompts should match.
