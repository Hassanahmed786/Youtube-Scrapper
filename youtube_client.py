"""Get video data from YouTube.

Main way: YouTube Data API v3 (up to 50 videos per request).
Fallback: yt-dlp (only reads metadata, never downloads the video).
"""
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import httplib2
import yt_dlp
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from utils import (
    extract_video_id,
    parse_iso_date,
    to_iso_utc,
    truncate_description,
    utc_now_iso,
    watch_url,
)

log = logging.getLogger(__name__)

# the API accepts at most 50 IDs in one request
BATCH_SIZE = 50

# yt-dlp error text -> short reason we show to the user (checked from top to bottom)
YTDLP_REASONS = [
    (("your country", "geo restrict"), "Video is blocked in this region"),
    (("private video", "video unavailable", "is unavailable", "been removed",
      "no longer available", "does not exist", "terminated"), "Video is private or deleted"),
    (("members-only", "members only"), "Video is members-only"),
    (("confirm your age", "age-restricted"), "Video is age-restricted"),
    (("not a bot",), "YouTube asked for a bot check"),
    (("unable to download", "urlopen error", "timed out", "connection",
      "name or service"), "Network error"),
]


# ---------- building one result ----------

def to_int(value):
    """Turn a view count into an int. Returns None if it is missing or not a number."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def make_record(video_id, title, channel, description, publish_date, views):
    """Put all fields of one video into a dict. Missing fields become empty."""
    return {
        "video_id": video_id,
        "title": title or "",
        "channel": channel or "",
        "description": truncate_description(description),
        "publish_date": publish_date or "",
        "views": to_int(views),
        "url": watch_url(video_id),
        "scraped_at": utc_now_iso(),
    }


def record_from_api_item(item):
    """Read one item from the API response."""
    snippet = item.get("snippet") or {}
    stats = item.get("statistics") or {}
    return make_record(
        video_id=item["id"],
        title=snippet.get("title"),
        channel=snippet.get("channelTitle"),
        description=snippet.get("description"),
        publish_date=parse_iso_date(snippet.get("publishedAt")),
        views=stats.get("viewCount"),
    )


# ---------- YouTube Data API ----------

def make_api_client():
    """Create the API client. Returns None if there is no API key."""
    key = os.getenv("YOUTUBE_API_KEY", "").strip()
    if not key:
        log.warning("YOUTUBE_API_KEY is not set, using yt-dlp only")
        return None
    try:
        return build("youtube", "v3", developerKey=key, cache_discovery=False)
    except Exception as err:
        log.error("Could not create the YouTube API client: %s", err)
        return None


def api_error_reason(err):
    """Turn an API exception into a short plain reason."""
    if isinstance(err, HttpError):
        body = ""
        if isinstance(err.content, bytes):
            body = err.content.decode("utf-8", "ignore").lower()
        if "quotaexceeded" in body or "dailylimitexceeded" in body or "ratelimitexceeded" in body:
            return "API quota exceeded"
        if "keyinvalid" in body or "api key not valid" in body or "api_key_invalid" in body:
            return "Invalid API key"
        if "accessnotconfigured" in body or "has not been used" in body or "service_disabled" in body:
            return "YouTube Data API is not enabled for this key"
        return f"YouTube API error (HTTP {err.resp.status})"
    if isinstance(err, (OSError, httplib2.HttpLib2Error)):
        return "Network error"
    return "YouTube API request failed"


def fetch_batch_api(youtube, ids):
    """Ask the API for up to 50 videos. Returns {video_id: record}.

    Private and deleted videos are simply not in the response.
    """
    response = youtube.videos().list(part="snippet,statistics", id=",".join(ids)).execute(num_retries=2)
    found = {}
    for item in response.get("items", []):
        found[item["id"]] = record_from_api_item(item)
    return found


# ---------- yt-dlp fallback ----------

def ytdlp_error_reason(message):
    """Pick a short reason from a yt-dlp error message. Returns None if unknown."""
    text = message.lower()
    for words, reason in YTDLP_REASONS:
        if any(word in text for word in words):
            return reason
    return None


def ytdlp_publish_date(info):
    """Get the publish date from yt-dlp info as an ISO UTC string."""
    timestamp = info.get("timestamp") or info.get("release_timestamp")
    if timestamp:
        return to_iso_utc(datetime.fromtimestamp(timestamp, tz=timezone.utc))
    upload_date = info.get("upload_date")  # looks like 20240501
    if upload_date:
        try:
            return to_iso_utc(datetime.strptime(upload_date, "%Y%m%d"))
        except ValueError:
            pass
    return ""


def fetch_one_ytdlp(video_id):
    """Read one video with yt-dlp. Returns (record, None) or (None, reason)."""
    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,  # metadata only
        "noplaylist": True,
        "socket_timeout": 15,
        "retries": 1,
        "logger": logging.getLogger("yt_dlp"),  # silenced in setup_logging, we log errors ourselves
    }
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(watch_url(video_id), download=False)
    except yt_dlp.utils.DownloadError as err:
        log.error("yt-dlp failed for %s: %s", video_id, err)
        return None, ytdlp_error_reason(str(err))
    except Exception as err:
        log.error("yt-dlp crashed for %s: %s", video_id, err)
        return None, None

    if not info:
        return None, None

    record = make_record(
        video_id=video_id,
        title=info.get("title"),
        channel=info.get("channel") or info.get("uploader"),
        description=info.get("description"),
        publish_date=ytdlp_publish_date(info),
        views=info.get("view_count"),
    )
    return record, None


def fetch_with_ytdlp(ids, api_reason=None):
    """Fallback for a list of IDs. Returns (records, reasons) as dicts keyed by ID."""
    records, reasons = {}, {}
    # a few at a time, yt-dlp is slow when run one by one
    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(pool.map(fetch_one_ytdlp, ids))
    for video_id, (record, reason) in zip(ids, outcomes):
        if record:
            records[video_id] = record
        else:
            reasons[video_id] = reason or api_reason or "Could not fetch video data"
    return records, reasons


# ---------- main function ----------

def fetch_all(ids):
    """Fetch all unique IDs. Returns (records, reasons) as dicts keyed by video ID."""
    records, reasons = {}, {}
    youtube = make_api_client()
    api_reason = None  # why the API failed (used if yt-dlp cannot give a better reason)

    for start in range(0, len(ids), BATCH_SIZE):
        batch = ids[start:start + BATCH_SIZE]

        if youtube is not None:
            try:
                found = fetch_batch_api(youtube, batch)
                records.update(found)
                for video_id in batch:
                    if video_id not in found:
                        reasons[video_id] = "Video is private or deleted"
                continue
            except Exception as err:
                api_reason = api_error_reason(err)
                log.error("YouTube API failed (%s): %s. Trying yt-dlp instead.", api_reason, err)
                youtube = None  # do not call the API again in this request

        found, failed = fetch_with_ytdlp(batch, api_reason)
        records.update(found)
        reasons.update(failed)

    return records, reasons


def get_videos(raw_urls):
    """Scrape a list of URLs or video IDs. Returns (results, errors).

    results: list of video dicts (same order as the input)
    errors:  list of {"url": ..., "reason": ...}
    """
    entries = []  # (text the user gave us, video ID or None)
    ids = []
    seen = set()
    for raw in raw_urls:
        video_id = extract_video_id(raw)
        entries.append((raw, video_id))
        if video_id and video_id not in seen:  # remove duplicate IDs before fetching
            seen.add(video_id)
            ids.append(video_id)

    records, reasons = fetch_all(ids) if ids else ({}, {})

    results, errors = [], []
    done = set()
    for raw, video_id in entries:
        if video_id is None:
            log.error("Invalid URL: %s", raw)
            errors.append({"url": raw, "reason": "Invalid URL"})
        elif video_id in done:
            continue  # same video pasted twice in different forms
        elif video_id in records:
            results.append(records[video_id])
            done.add(video_id)
        else:
            reason = reasons.get(video_id, "Could not fetch video data")
            log.error("Failed %s: %s", raw, reason)
            errors.append({"url": raw, "reason": reason})
            done.add(video_id)

    log.info("Scrape finished: %d ok, %d failed", len(results), len(errors))
    return results, errors
