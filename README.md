# YouTube Scraper

## 1. What this project does

I made a small tool that collects data about YouTube videos.

You paste video links into a web page and click **Scrape**. The page shows a table with the data for each video. Then you can save the table to a Google Sheet or download it as a CSV or Excel file.

For every video it collects:

- title
- channel name
- description
- publish date (ISO format, UTC)
- view count (a whole number)
- the video URL and the time it was scraped (UTC)

How it gets the data:

- **Main way:** the official YouTube Data API v3. Up to 50 videos are fetched in one request.
- **Backup way:** `yt-dlp` (it only reads the info, it never downloads the video). It is used if the API fails or the daily quota runs out.

Files in the project:

```
youtube-scraper/
  app.py              Flask app and routes
  youtube_client.py   gets the video data (API first, then yt-dlp)
  sheets_client.py    reads and writes the Google Sheet
  utils.py            URL parsing, helpers, config check, logging
  main.py             small command line version (reads urls.txt)
  templates/index.html  the web page (HTML + CSS + JS in one file)
  urls.txt            3 sample URLs for testing
  requirements.txt
  .env.example
```

## 2. Setup

You need Python 3.10 or newer.

```bash
cd youtube-scraper

# make a virtual environment
python -m venv venv

# turn it on
source venv/bin/activate        # Mac / Linux
venv\Scripts\activate           # Windows

# install the packages
pip install -r requirements.txt
```

## 3. Get a YouTube Data API key

1. Go to the [Google Cloud Console](https://console.cloud.google.com/) and create a project (or pick an existing one).
2. Open **APIs & Services > Library**, search for **YouTube Data API v3** and click **Enable**.
3. Open **APIs & Services > Credentials**, click **Create credentials > API key**.
4. Copy the key. You will paste it into `.env` as `YOUTUBE_API_KEY`.

Tip: you can click "Edit API key" and restrict it to the YouTube Data API v3 only.

## 4. Create a service account for Google Sheets

The app logs in to Google Sheets with a service account (a robot account).

1. In the same Google Cloud project, open **APIs & Services > Library**, search for **Google Sheets API** and click **Enable**.
2. Open **IAM & Admin > Service Accounts** and click **Create service account**. Give it any name and finish the wizard (no extra roles needed).
3. Click the new service account, open the **Keys** tab, then **Add key > Create new key > JSON**. A JSON file is downloaded.
4. Move that file into the project folder and rename it to `service_account.json`. It is already listed in `.gitignore`, so it will not be committed.
5. Create a new Google Sheet (or use an empty one). Open the JSON file and copy the `client_email` value (it looks like `name@project.iam.gserviceaccount.com`).
6. In the Google Sheet click **Share**, paste that email and give it the **Editor** role.
7. Copy the sheet ID from the sheet URL. It is the long part between `/d/` and `/edit`:
   `https://docs.google.com/spreadsheets/d/` **`THIS_PART`** `/edit`

The app uses the first tab of the sheet. If the sheet is empty it creates the header row by itself.

## 5. Fill in .env

Copy the example file and open it:

```bash
cp .env.example .env            # Windows: copy .env.example .env
```

| Variable | What to put |
| --- | --- |
| `YOUTUBE_API_KEY` | the API key from step 3 |
| `GOOGLE_SHEET_ID` | the sheet ID from step 4 |
| `GOOGLE_SERVICE_ACCOUNT_FILE` | `service_account.json` (the path to the JSON key) |
| `FLASK_SECRET_KEY` | any long random text, make one with `python -c "import secrets; print(secrets.token_hex(32))"` |

When the app starts it checks these variables and prints a warning for every missing one. Scraping and downloading still work without the Google Sheets settings, and scraping works without the API key (it only uses yt-dlp then).

## 6. Run it

**Web page:**

```bash
python app.py
```

Then open <http://localhost:5000>, paste some links (one per line) and click **Scrape**.

You can paste:

- `https://www.youtube.com/watch?v=...` (also with extra parameters like `&t=30s`)
- `https://youtu.be/...`
- `https://www.youtube.com/shorts/...`
- `https://www.youtube.com/embed/...`
- a bare 11-character video ID

**Command line:**

```bash
python main.py
```

This reads `urls.txt`, scrapes every URL, prints the result and saves the new videos to the sheet. The sample `urls.txt` has 3 lines: a normal video, a `youtu.be` short link and an invalid link. So you should see 2 scraped and 1 failed ("Invalid URL").

## 7. What the sheet looks like

The header row is created automatically. Example:

| Title | Channel | Description | Publish Date | Views | URL | Scraped At |
| --- | --- | --- | --- | --- | --- | --- |
| Rick Astley - Never Gonna Give You Up (Official Video) | Rick Astley | The official video for "Never Gonna Give You Up"... | 2009-10-25T06:57:33Z | 1823755442 | https://www.youtube.com/watch?v=dQw4w9WgXcQ | 2025-01-15T10:30:00Z |
| Me at the zoo | jawed | The first video on YouTube... | 2005-04-24T03:31:52Z | 440619572 | https://www.youtube.com/watch?v=jNQXAC9IVRw | 2025-01-15T10:30:00Z |

What the web page looks like: a big text box at the top with a counter ("3 URLs detected") and a blue **Scrape** button. After scraping you see a line like "2 scraped, 1 failed", three buttons (**Save to Google Sheets**, **Download CSV**, **Download Excel**), and a table with a sticky header. Long descriptions are cut with a "show more" link. Failed URLs are listed below the table with a short reason, for example "Invalid URL" or "Video is private or deleted".

If you click **Save to Google Sheets** twice, the second time nothing new is added. The app reads the URLs already in the sheet and skips the videos that are there. You get a message like "2 rows added, 0 skipped" the first time and "0 rows added, 2 skipped (already in sheet)" the second time.

## 8. Known limits

- **API quota:** the YouTube Data API gives 10,000 units per day for free. One request with up to 50 videos costs 1 unit, so this is rarely a problem. If the quota runs out, the app switches to yt-dlp automatically.
- **yt-dlp is slower** (one request per video) and YouTube can block it sometimes (for example a "confirm you are not a bot" check).
- **50 URLs per request** in the web page. Blank lines and duplicate URLs are removed first. The command line version has no limit.
- **Descriptions** are cut to 50,000 characters (the Google Sheets cell limit).
- **Private and deleted videos** cannot be scraped. They show up in the failed list.
- If a video hides its view count, the Views cell is left empty.
- The latest results are kept in the server's memory (per browser session), so they are gone when the server restarts. Just scrape again.
- The app saves into the **first tab** of the sheet only.
- In the CSV file, text that starts with `=`, `+`, `-` or `@` gets a `'` in front so Excel does not run it as a formula.
- `python app.py` runs Flask in debug mode. That is fine for your own computer but do not put it on a public server.

## Troubleshooting

- **"No access to the Google Sheet"**: share the sheet with the service account email as Editor.
- **"Google Sheet not found"**: check `GOOGLE_SHEET_ID` in `.env`.
- **"The Google Sheets API is not enabled"**: enable it in the Google Cloud Console (step 4.1).
- **"API quota exceeded"** next to a failed URL: the API quota is used up and yt-dlp could not get that video either. Try again tomorrow.
- yt-dlp stops working after some months: update it with `pip install -U yt-dlp`.
