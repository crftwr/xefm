"""Print where the XeFM Homebrew release stands, and the next step.

Read-only: it only queries GitHub (through `gh`) and PyPI. Run it from
anywhere:

    python3 .claude/skills/xefm-brew-publish/brew_status.py [--json]

The last line, "next:", is one of the actions the skill describes.
"""

import base64
import datetime
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

TAP = "crftwr/homebrew-tap"
APP = "crftwr/xefm"
PROJECT = "xefm"
# autobump.yml waits this long after the sdist upload before bumping.
COOLDOWN = datetime.timedelta(hours=24, minutes=30)
# Its schedule is every six hours; allow for GitHub delaying scheduled runs.
AUTOBUMP_GRACE = datetime.timedelta(hours=8)


def gh(*args):
    out = subprocess.run(["gh", *args], check=True, capture_output=True, text=True)
    return out.stdout


def gh_json(*args):
    return json.loads(gh(*args))


def fetch_json(url):
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return json.load(r)
        except (urllib.error.URLError, TimeoutError):
            if attempt == 3:
                raise
            time.sleep(5 * (attempt + 1))


def tap_file(path):
    data = gh_json("api", f"repos/{TAP}/contents/{path}")
    return base64.b64decode(data["content"]).decode()


def now():
    return datetime.datetime.now(datetime.timezone.utc)


def parse_time(s):
    return datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))


def checks_state(rollup):
    """'none', 'pending', 'failure' or 'success' for a PR's checks."""
    if not rollup:
        return "none"
    states = []
    for c in rollup:
        if c.get("__typename") == "StatusContext":
            states.append(c.get("state", "").upper())
        elif c.get("status") != "COMPLETED":
            states.append("PENDING")
        else:
            states.append((c.get("conclusion") or "").upper())
    if any(s in ("FAILURE", "ERROR", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED",
                 "STARTUP_FAILURE") for s in states):
        return "failure"
    if any(s in ("PENDING", "QUEUED", "IN_PROGRESS", "EXPECTED", "") for s in states):
        return "pending"
    return "success"


def main():
    s = {}

    formula = tap_file("Formula/xefm.rb")
    s["formula"] = re.search(rf"/{PROJECT}-([0-9][^/]*?)\.tar\.gz", formula).group(1)
    m = re.search(r'root_url "[^"]*/xefm-([^"/]+)"', formula)
    s["formula_bottles"] = m.group(1) if m else None

    cask = tap_file("Casks/xefm.rb")
    s["cask"] = re.search(r'version "([^"]+)"', cask).group(1)

    info = fetch_json(f"https://pypi.org/pypi/{PROJECT}/json")
    s["pypi"] = info["info"]["version"]
    sdist = [u for u in info["urls"] if u["packagetype"] == "sdist"]
    if sdist:
        uploaded = parse_time(sdist[0]["upload_time_iso_8601"])
        s["sdist_uploaded"] = uploaded.isoformat()
        s["sdist_age_h"] = round((now() - uploaded).total_seconds() / 3600, 1)
        s["formula_due_at"] = (uploaded + COOLDOWN).isoformat()
    else:
        uploaded = None

    rel = gh_json("release", "view", "-R", APP, "--json", "tagName,assets")
    s["release"] = rel["tagName"].lstrip("v")
    s["release_has_dmg"] = any(a["name"].endswith("-macos.dmg") for a in rel["assets"])

    prs = gh_json("pr", "list", "-R", TAP, "--state", "open", "--limit", "50",
                  "--json", "number,title,headRefName,headRefOid,files,statusCheckRollup,url")
    s["open_prs"] = []
    for pr in prs:
        if not pr["headRefName"].startswith("bump-"):
            continue
        files = [f["path"] for f in pr["files"]]
        kind = ("formula" if any(f.startswith("Formula/") for f in files)
                else "cask" if any(f.startswith("Casks/") for f in files) else "other")
        s["open_prs"].append({
            "number": pr["number"], "title": pr["title"], "kind": kind,
            "head_sha": pr["headRefOid"], "checks": checks_state(pr["statusCheckRollup"]),
            "url": pr["url"]})

    runs = gh_json("run", "list", "-R", TAP, "--workflow", "autobump.yml", "--limit", "5",
                   "--json", "databaseId,status,conclusion,createdAt,event")
    s["autobump_runs"] = runs
    runs_pub = gh_json("run", "list", "-R", TAP, "--workflow", "publish.yml", "--limit", "3",
                       "--json", "databaseId,status,conclusion,createdAt,displayTitle")
    s["publish_runs"] = runs_pub

    s["next"] = decide(s, uploaded)

    if "--json" in sys.argv:
        print(json.dumps(s, indent=2))
        return
    print(f"formula      {s['formula']} (bottles: {s['formula_bottles']})")
    print(f"cask         {s['cask']}")
    print(f"PyPI         {s['pypi']}" + (f" (sdist {s['sdist_age_h']} h old)" if uploaded else " (no sdist)"))
    print(f"release      {s['release']}" + (" with DMG" if s["release_has_dmg"] else " without DMG"))
    for pr in s["open_prs"]:
        print(f"open PR      #{pr['number']} {pr['title']} [{pr['kind']}] checks={pr['checks']} head={pr['head_sha']}")
    for r in runs[:3]:
        print(f"autobump     {r['createdAt']} {r['event']} {r['status']}/{r['conclusion'] or '-'} run {r['databaseId']}")
    for r in runs_pub[:1]:
        print(f"publish      {r['createdAt']} {r['status']}/{r['conclusion'] or '-'} run {r['databaseId']} {r['displayTitle']}")
    print(f"next: {s['next']}")


def decide(s, uploaded):
    formula_prs = [p for p in s["open_prs"] if p["kind"] == "formula"]
    cask_prs = [p for p in s["open_prs"] if p["kind"] == "cask"]

    # A formula PR in flight decides everything else for the formula.
    for p in formula_prs:
        if p["checks"] == "success":
            # auto-publish.yml starts publish.yml as soon as test-bot passes.
            pubs = s["publish_runs"]
            if any(r["status"] != "completed" for r in pubs):
                return f"wait-publish #{p['number']}"
            if pubs and pubs[0]["conclusion"] == "failure" and \
                    now() - parse_time(pubs[0]["createdAt"]) < datetime.timedelta(hours=12):
                return f"publish-failed #{p['number']} run {pubs[0]['databaseId']}"
            return f"publish #{p['number']} {p['head_sha']}"
        if p["checks"] == "failure":
            return f"investigate-ci #{p['number']}"
        return f"wait-ci #{p['number']}"

    # A revision bump (1.10.0_1) names its bottles "xefm-1.10.0_1".
    if (s["formula_bottles"] or "").split("_")[0] != s["formula"]:
        return "bottles-missing"

    for p in cask_prs:
        if p["checks"] == "success":
            return f"merge-cask #{p['number']}"
        if p["checks"] == "failure":
            return f"investigate-ci #{p['number']}"
        return f"wait-ci #{p['number']}"

    if s["formula"] != s["pypi"]:
        if uploaded is None:
            return "wait-sdist"
        if now() < uploaded + COOLDOWN:
            return f"wait-cooldown {s['formula_due_at']}"
        due_at = uploaded + COOLDOWN
        runs_after = [r for r in s["autobump_runs"] if parse_time(r["createdAt"]) >= due_at]
        if any(r["status"] != "completed" for r in runs_after):
            return "wait-autobump"
        if any(r["conclusion"] == "failure" for r in runs_after[:1]):
            return "autobump-failed"
        if runs_after and runs_after[0]["conclusion"] == "success":
            # It ran after the cooldown, succeeded, and still no PR.
            return "autobump-no-pr"
        if now() >= due_at + AUTOBUMP_GRACE:
            return "dispatch-autobump"
        return "wait-autobump"

    if s["release_has_dmg"] and s["cask"] != s["release"]:
        return "cask-behind"
    return "done"


if __name__ == "__main__":
    main()
