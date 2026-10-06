"""Helpers used by the web app and the command line script.

This file has the URL parsing, a few small text/date helpers,
the startup config check and the logging setup.
"""
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv

# folder where this file lives (used to find .env and the service account file)
BASE_DIR = Path(__file__).resolve().parent

# Google Sheets allows at most 50,000 characters in one cell
MAX_DESCRIPTION_LENGTH = 50000

# a YouTube video ID is always 11 characters: letters, digits, "-" and "_"
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")

# the hosts we accept (after removing "www.")
YOUTUBE_HOSTS = {
    "youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtube-nocookie.com",
}

# columns used for the Google Sheet, the CSV file and the Excel file
COLUMNS = ["Title", "Channel", "Description", "Publish Date", "Views", "URL", "Scraped At"]

# settings from .env and what happens when they are missing
SETTINGS = {
    "YOUTUBE_API_KEY": "Without it only yt-dlp is used (slower and less reliable).",
    "GOOGLE_SHEET_ID": "Saving to Google Sheets will not work.",
    "GOOGLE_SERVICE_ACCOUNT_FILE": "Saving to Google Sheets will not work.",
    "FLASK_SECRET_KEY": "A random key is used, so sessions reset when the server restarts.",
}


# ---------- config and logging ----------

def load_config():
    """Read the .env file that sits next to this script."""
    load_dotenv(BASE_DIR / ".env")


def check_config():
    """Print a clear message for every missing setting. Returns the missing names."""
    if not (BASE_DIR / ".env").is_file():
        print("NOTE: no .env file found. Copy .env.example to .env and fill it in.")

    missing = [name for name in SETTINGS if not os.getenv(name, "").strip()]
    for name in missing:
        print(f"WARNING: {name} is missing in .env. {SETTINGS[name]}")

    # if a service account file is set, check that it really exists
    key_file = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "").strip()
    if key_file:
        path = Path(key_file)
        if not path.is_absolute():
            path = BASE_DIR / path
        if not path.is_file():
            print(f"WARNING: service account file not found: {path}")

    if not missing:
        print("Config OK: all settings found in .env")
    return missing


def setup_logging():
    """Log to the console with a short format."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # these libraries are very chatty
    logging.getLogger("googleapiclient").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    # yt-dlp prints its own errors, we already log them in youtube_client.py
    logging.getLogger("yt_dlp").setLevel(logging.CRITICAL)


# ---------- URL parsing ----------

def extract_video_id(text):
    """Get the 11-character video ID from a URL or a bare ID. Returns None if invalid."""
    if not text:
        return None
    text = text.strip()

    # a bare video ID
    if VIDEO_ID_RE.match(text):
        return text

    # allow links that were pasted without https://
    if "://" not in text:
        text = "https://" + text

    try:
        parsed = urlparse(text)
        host = (parsed.hostname or "").lower()
    except ValueError:
        return None
    if host.startswith("www."):
        host = host[4:]

    parts = [p for p in parsed.path.split("/") if p]
    candidate = None

    if host == "youtu.be":
        # https://youtu.be/ID
        candidate = parts[0] if parts else None
    elif host in YOUTUBE_HOSTS:
        if parts and parts[0] == "watch":
            # https://www.youtube.com/watch?v=ID&other=params
            candidate = parse_qs(parsed.query).get("v", [None])[0]
        elif len(parts) >= 2 and parts[0] in ("shorts", "embed", "live", "v"):
            # https://www.youtube.com/shorts/ID  and  /embed/ID
            candidate = parts[1]

    if candidate and VIDEO_ID_RE.match(candidate):
        return candidate
    return None


def watch_url(video_id):
    """The clean URL we store for a video."""
    return f"https://www.youtube.com/watch?v={video_id}"


def parse_urls(text):
    """Split pasted text into lines. Blank lines and duplicates are removed, order is kept."""
    seen = set()
    lines = []
    for line in (text or "").splitlines():
        line = line.strip()
        if line and line not in seen:
            seen.add(line)
            lines.append(line)
    return lines


# ---------- small helpers ----------

def truncate_description(text):
    """Cut the description so it fits into one Google Sheets cell."""
    return (text or "")[:MAX_DESCRIPTION_LENGTH]


def to_iso_utc(moment):
    """Format a datetime as ISO 8601 in UTC, like 2024-05-01T12:30:00Z."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_now_iso():
    """Current time in UTC as an ISO string."""
    return to_iso_utc(datetime.now(timezone.utc))


def parse_iso_date(text):
    """Turn a date string from the API into our ISO UTC format. Empty string if bad."""
    if not text:
        return ""
    try:
        return to_iso_utc(datetime.fromisoformat(text.replace("Z", "+00:00")))
    except ValueError:
        return ""


def result_to_row(result):
    """Turn one result dict into a list in the same order as COLUMNS."""
    views = result.get("views")
    return [
        result.get("title", ""),
        result.get("channel", ""),
        result.get("description", ""),
        result.get("publish_date", ""),
        "" if views is None else views,
        result.get("url", ""),
        result.get("scraped_at", ""),
    ]
