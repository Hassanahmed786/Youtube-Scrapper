"""Command line version: read urls.txt, scrape the videos and save them to the sheet.

Run with:  python main.py
(optional)  python main.py other_file.txt
"""
import sys
from pathlib import Path

import sheets_client
import youtube_client
from utils import BASE_DIR, check_config, load_config, parse_urls, setup_logging


def main():
    load_config()
    setup_logging()
    check_config()

    # which file to read: first argument, or urls.txt next to this script
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else BASE_DIR / "urls.txt"
    if not path.is_file():
        print(f"Could not find the URL file: {path}")
        return 1

    urls = parse_urls(path.read_text(encoding="utf-8-sig"))
    if not urls:
        print(f"{path.name} has no URLs.")
        return 1

    print(f"\nScraping {len(urls)} URLs from {path.name} ...")
    results, errors = youtube_client.get_videos(urls)

    for r in results:
        views = "n/a" if r["views"] is None else f"{r['views']:,}"
        print(f"  OK     {r['title']} | {r['channel']} | {views} views")
    for e in errors:
        print(f"  FAILED {e['url']} -> {e['reason']}")
    print(f"\n{len(results)} scraped, {len(errors)} failed")

    if not results:
        return 1

    # save to Google Sheets
    if not sheets_client.sheets_configured():
        print("Not saving: GOOGLE_SHEET_ID or GOOGLE_SERVICE_ACCOUNT_FILE is missing in .env")
        return 1
    try:
        summary = sheets_client.save_results(results)
    except sheets_client.SheetsError as err:
        print(f"Could not save to Google Sheets: {err}")
        return 1

    print(f"{summary['added']} rows added, {summary['skipped']} skipped (already in sheet)")
    print(f"Sheet: {sheets_client.sheet_url()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
