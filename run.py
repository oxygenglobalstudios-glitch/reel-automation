#!/usr/bin/env python3
"""Sheet -> render ahead & store in GitHub -> post at a fixed rate via Make -> Instagram.

Every run does two independent things:
  1. POST   - if the posting gap has passed, post the next READY row (render it first if needed).
  2. RENDER - keep a stock of finished videos stored in the repo (render_ahead_target), so posting
              never waits on rendering. Videos are stored in videos/ and only *posted* at the set rate.

Usage:
  python run.py                 # normal automatic run (post if due + render ahead)
  python run.py --row 5         # post a specific sheet row now (ignores the rate gap)
  python run.py --render-only   # only render ahead, no push, no posting
"""
import argparse, csv, datetime, io, json, os, subprocess, sys, time, urllib.request
from pathlib import Path

from render_reel import render

ROOT = Path(__file__).parent
CFG = json.loads((ROOT / "config.json").read_text(encoding="utf-8-sig"))
# In GitHub Actions these come from the environment (no secrets in the repo)
if os.environ.get("MAKE_WEBHOOK_URL"):
    CFG["make_webhook_url"] = os.environ["MAKE_WEBHOOK_URL"]
if os.environ.get("GITHUB_REPOSITORY"):
    CFG["github_user"], CFG["github_repo"] = os.environ["GITHUB_REPOSITORY"].split("/")

RENDER_AHEAD_TARGET = CFG.get("render_ahead_target", 24)   # finished videos kept in stock
RENDER_PER_RUN = CFG.get("render_per_run", 12)             # max renders in one run


def fetch_rows():
    url = (f"https://docs.google.com/spreadsheets/d/{CFG['sheet_id']}/export"
           f"?format=csv&gid={CFG['sheet_gid']}")
    with urllib.request.urlopen(url, timeout=60) as r:
        data = r.read().decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(data)))
    for i, row in enumerate(rows):
        row["_row"] = i + 2          # sheet row number (header is row 1)
    return rows


def git(*args, capture=False):
    r = subprocess.run(["git", *args], cwd=ROOT, check=True, text=True,
                       capture_output=capture)
    return r.stdout.strip() if capture else None


def push():
    git("pull", "--rebase", "origin", CFG["branch"])
    git("push", "origin", CFG["branch"])


def cdn_url(rel):
    """Immutable jsDelivr URL pinned to the newest commit that touched the video file."""
    sha = git("log", "-1", "--format=%H", "--", rel, capture=True)
    return (f"https://cdn.jsdelivr.net/gh/{CFG['github_user']}/{CFG['github_repo']}"
            f"@{sha}/{rel}")


def wait_until_live(url, tries=18, pause=10):
    """Wait until the CDN really serves the video (HTTP 200/206 + video type) before Instagram fetches it."""
    for _ in range(tries):
        try:
            req = urllib.request.Request(url, headers={"Range": "bytes=0-1023"})
            with urllib.request.urlopen(req, timeout=30) as r:
                if r.status in (200, 206) and "video" in (r.headers.get("Content-Type") or ""):
                    time.sleep(15)      # small extra margin for CDN edges
                    return True
        except Exception as e:
            print("CDN not ready yet:", e)
        time.sleep(pause)
    return False


def hours_since_last_post():
    """Hours since the last reel was posted (commit messages 'post N' / old 'reel N' / 'repost N')."""
    ts = git("log", "-1", "--format=%ct", "-E", "--grep=^(post|reel|repost) [0-9]+$", capture=True)
    return (time.time() - int(ts)) / 3600 if ts else None


def posts_per_hour_now():
    """Peak (default 18:00-09:00 IST, for US/UK/AU audiences) vs off-peak rate."""
    ist = datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)
    start = CFG.get("peak_start_hour_ist", 18)
    end = CFG.get("peak_end_hour_ist", 9)
    peak = ist.hour >= start or ist.hour < end
    return CFG.get("peak_posts_per_hour", 2) if peak else CFG.get("offpeak_posts_per_hour", 1)


def notify_make(payload):
    req = urllib.request.Request(
        CFG["make_webhook_url"], data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode()


def video_path(r):
    no = r["No."].strip() or str(r["_row"])
    return no, ROOT / "videos" / f"reel_{int(no):03d}.mp4"


def pending(rows):
    """Rows still to post: READY/blank status, text present, no Video URL yet."""
    return [r for r in rows
            if r["Status"].strip().upper() in ("", "READY") and r["Text"].strip()
            and not r["Video URL"].strip()]


def post_row(r):
    no, out = video_path(r)
    rel = out.relative_to(ROOT).as_posix()
    if not out.exists():
        print(f"Rendering row {r['_row']} (No. {no}) ...")
        render(r["Text"], out)
        git("add", rel)
        git("commit", "-m", f"render {no}")
    git("commit", "--allow-empty", "-m", f"post {no}")      # marks the posting time for the rate gap
    push()
    url = cdn_url(rel)
    print("Video ->", url)
    print("CDN live:", wait_until_live(url))
    print("Make:", notify_make({
        "row": r["_row"], "no": no, "video_url": url, "caption": r["Caption"]}))


def render_ahead(rows, skip_row=None):
    """Render + store videos for upcoming rows so a stock of finished videos is always ready."""
    todo = [r for r in pending(rows) if r["_row"] != skip_row]
    stock = sum(1 for r in todo if video_path(r)[1].exists())
    made = []
    for r in todo:
        if stock >= RENDER_AHEAD_TARGET or len(made) >= RENDER_PER_RUN:
            break
        no, out = video_path(r)
        if out.exists():
            continue
        print(f"Render ahead: row {r['_row']} (No. {no})")
        render(r["Text"], out)
        git("add", out.relative_to(ROOT).as_posix())
        made.append(no)
        stock += 1
    if made:
        git("commit", "-m", "render " + ",".join(made))
        return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--row", type=int)
    ap.add_argument("--render-only", action="store_true")
    a = ap.parse_args()

    rows = fetch_rows()
    posted_row = None

    if a.render_only:
        render_ahead(rows)
        return

    if a.row:
        todo = [r for r in rows if r["_row"] == a.row]
    else:
        rate = posts_per_hour_now()
        gap_h = (60 / rate - 5) / 60          # 1/hr -> 55 min apart, 2/hr -> 25 min apart
        h = hours_since_last_post()
        if h is not None and h < gap_h:
            print(f"Rate {rate}/hour: last post {h*60:.0f} min ago (< {gap_h*60:.0f} min); not posting now.")
            todo = []
        else:
            todo = pending(rows)[:1]

    if todo:
        post_row(todo[0])
        posted_row = todo[0]["_row"]
    elif not a.row:
        print("Nothing to post right now.")

    if render_ahead(rows, skip_row=posted_row):
        push()
        print("Stored new rendered videos in the repo.")


if __name__ == "__main__":
    sys.exit(main())
