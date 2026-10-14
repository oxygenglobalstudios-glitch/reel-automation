#!/usr/bin/env python3
"""Sheet -> local render -> GitHub -> Make webhook (which writes the sheet + posts to Instagram).

Usage:
  python run.py                 # render + publish next READY row
  python run.py --row 5         # a specific sheet row number (2 = first data row)
  python run.py --render-only   # render into videos/, no git push, no webhook
  python run.py --count 3       # process up to 3 READY rows in one go
"""
import argparse, csv, io, json, os, subprocess, sys, urllib.request
from pathlib import Path

from render_reel import render

ROOT = Path(__file__).parent
CFG = json.loads((ROOT / "config.json").read_text(encoding="utf-8-sig"))
# In GitHub Actions these come from the environment (no secrets in the repo)
if os.environ.get("MAKE_WEBHOOK_URL"):
    CFG["make_webhook_url"] = os.environ["MAKE_WEBHOOK_URL"]
if os.environ.get("GITHUB_REPOSITORY"):
    CFG["github_user"], CFG["github_repo"] = os.environ["GITHUB_REPOSITORY"].split("/")


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


def publish(path: Path, no: str):
    rel = path.relative_to(ROOT).as_posix()
    git("add", rel)
    git("commit", "-m", f"reel {no}")
    git("pull", "--rebase", "origin", CFG["branch"])
    git("push", "origin", CFG["branch"])
    sha = git("rev-parse", "HEAD", capture=True)
    # jsDelivr serves proper video/mp4 + range requests; pinning the commit SHA
    # makes the URL immutable and available immediately (no branch cache delay)
    return (f"https://cdn.jsdelivr.net/gh/{CFG['github_user']}/{CFG['github_repo']}"
            f"@{sha}/{rel}")


def notify_make(payload):
    req = urllib.request.Request(
        CFG["make_webhook_url"], data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--row", type=int)
    ap.add_argument("--count", type=int, default=1)
    ap.add_argument("--render-only", action="store_true")
    a = ap.parse_args()

    rows = fetch_rows()
    if a.row:
        todo = [r for r in rows if r["_row"] == a.row]
    else:
        todo = [r for r in rows
                if r["Status"].strip().upper() in ("", "READY") and r["Text"].strip() and not r["Video URL"].strip()]
    todo = todo[: a.count]
    if not todo:
        print("Nothing to do (no READY rows without a Video URL).")
        return

    for r in todo:
        no = r["No."].strip() or str(r["_row"])
        out = ROOT / "videos" / f"reel_{int(no):03d}.mp4"
        if out.exists() and not a.row:
            print(f"Row {r['_row']} already rendered ({out.name}); skipping to avoid a duplicate post.")
            continue
        print(f"Rendering row {r['_row']} (No. {no}) ...")
        render(r["Text"], out)
        if a.render_only:
            print("Saved", out)
            continue
        url = publish(out, no)
        print("Pushed ->", url)
        print("Make:", notify_make({
            "row": r["_row"], "no": no, "video_url": url, "caption": r["Caption"]}))


if __name__ == "__main__":
    sys.exit(main())

