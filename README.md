# Fully automatic reels: Sheet -> GitHub Actions render -> Sheet -> Instagram

Your only job: add rows to the sheet with Status = READY. Everything else runs in the cloud
(GitHub Actions, free) 3x a day. No computer of yours needs to be on.

## One-time setup (about 10 minutes)
1. Create a **public** GitHub repo, upload everything in this folder (or `git push`).
2. Google Sheet -> Share -> "Anyone with the link: Viewer".
3. Make.com scenario (build it first, you need its webhook URL):
   1. **Webhooks > Custom webhook** (copy the URL). Fields: row, no, video_url, caption.
   2. **Google Sheets > Update a Row** ("Reels Data"): Row number = `row`, Status = `RENDERED`, Video URL = `video_url`.
   3. **Tools > Sleep** 30 seconds.
   4. **Instagram for Business > Create a Reel (Video)**: Video URL = `video_url`, Caption = `caption`.
   5. **Google Sheets > Update a Row**: Status = `POSTED`.
   Turn scenario ON ("Immediately" scheduling for the webhook).
   (Instagram must be Business/Creator, linked to a Facebook Page.)
4. GitHub repo -> Settings -> Secrets and variables -> Actions -> New secret:
   `MAKE_WEBHOOK_URL` = the webhook URL.
5. Actions tab -> "Render and publish reel" -> Run workflow (test once).

## Daily use
Add rows (Text / Status=READY / Caption). Posts go out at the scheduled times in
`.github/workflows/reel.yml` (one reel per run; add more cron lines for more posts/day).
Rows already rendered are never re-posted.

Local test: `python run.py --render-only`
