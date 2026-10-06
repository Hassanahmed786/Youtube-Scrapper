"""Save results to a Google Sheet with gspread (service account login)."""
import json
import logging
import os
from pathlib import Path

import gspread
from google.auth.exceptions import GoogleAuthError
from gspread.exceptions import APIError, SpreadsheetNotFound

from utils import BASE_DIR, COLUMNS, extract_video_id, result_to_row

log = logging.getLogger(__name__)

# position of the URL column (1-based), used to read the existing URLs
URL_COLUMN = COLUMNS.index("URL") + 1


class SheetsError(Exception):
    """An error with a message that is safe to show to the user."""


# ---------- settings ----------

def service_account_path():
    """Full path of the service account JSON file (relative paths start at the project folder)."""
    path = Path(os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "").strip())
    return path if path.is_absolute() else BASE_DIR / path


def service_account_email():
    """The email of the service account, read from the JSON file."""
    try:
        with open(service_account_path(), encoding="utf-8") as f:
            return json.load(f)["client_email"]
    except (OSError, ValueError, KeyError):
        return "your service account"


def sheet_url():
    """Link to open the sheet in the browser. None if the ID is not set."""
    sheet_id = os.getenv("GOOGLE_SHEET_ID", "").strip()
    if not sheet_id:
        return None
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit"


def sheets_configured():
    """True if both Google Sheets settings are filled in."""
    return bool(os.getenv("GOOGLE_SHEET_ID", "").strip()
                and os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "").strip())


# ---------- error messages ----------

def explain_api_error(err):
    """Write a clear message for an error coming from the Google Sheets API."""
    code = getattr(err, "code", None)
    text = str(err).lower()

    if code == 404:
        return ("Google Sheet not found. Check that GOOGLE_SHEET_ID in .env is correct "
                "(it is the long ID in the sheet's URL).")
    if code == 403:
        if "has not been used" in text or "is disabled" in text or "service_disabled" in text:
            return ("The Google Sheets API is not enabled in your Google Cloud project. "
                    "Enable it in the Cloud Console and try again.")
        return (f"No access to the Google Sheet. Share the sheet with {service_account_email()} "
                "and give it Editor access.")
    if code == 429:
        return "Google Sheets rate limit reached. Wait a minute and try again."
    return f"Google Sheets error: {err}"


# ---------- reading and writing ----------

def open_worksheet():
    """Log in and return the first tab of the sheet."""
    sheet_id = os.getenv("GOOGLE_SHEET_ID", "").strip()
    if not sheet_id:
        raise SheetsError("GOOGLE_SHEET_ID is not set in .env")
    if not os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "").strip():
        raise SheetsError("GOOGLE_SERVICE_ACCOUNT_FILE is not set in .env")

    path = service_account_path()
    if not path.is_file():
        raise SheetsError(f"Service account file not found: {path}")

    try:
        client = gspread.service_account(filename=str(path))
    except (ValueError, KeyError):
        raise SheetsError("The service account file is not a valid Google key file (JSON).")

    return client.open_by_key(sheet_id).sheet1


def add_new_rows(worksheet, results):
    """Write the header if needed, skip videos that are already there, append the rest."""
    # create the header row if the sheet is empty
    if not worksheet.row_values(1):
        worksheet.append_row(COLUMNS, value_input_option="RAW")

    # video IDs that are already in the URL column
    existing = {extract_video_id(url) for url in worksheet.col_values(URL_COLUMN)}
    existing.discard(None)

    new_rows = []
    for result in results:
        video_id = result.get("video_id") or extract_video_id(result.get("url", ""))
        if video_id in existing:
            continue
        existing.add(video_id)
        new_rows.append(result_to_row(result))

    # one single request for all new rows
    # (RAW keeps text as text, so a title starting with "=" is never a formula)
    if new_rows:
        worksheet.append_rows(new_rows, value_input_option="RAW", table_range="A1")

    return {"added": len(new_rows), "skipped": len(results) - len(new_rows)}


def save_results(results):
    """Save results to the sheet. Returns {"added": n, "skipped": m}."""
    try:
        worksheet = open_worksheet()
        summary = add_new_rows(worksheet, results)
    except SheetsError:
        raise
    except SpreadsheetNotFound:
        raise SheetsError("Google Sheet not found. Check that GOOGLE_SHEET_ID in .env is correct.")
    except APIError as err:
        log.error("Google Sheets API error: %s", err)
        raise SheetsError(explain_api_error(err))
    except GoogleAuthError as err:
        log.error("Google login failed: %s", err)
        raise SheetsError("Could not log in with the service account key. Check the JSON file "
                          "and that your computer's clock and internet are fine.")
    except OSError as err:
        log.error("Network error while saving: %s", err)
        raise SheetsError("Network error while talking to Google Sheets. Check your internet connection.")

    log.info("Saved to sheet: %d added, %d skipped", summary["added"], summary["skipped"])
    return summary
