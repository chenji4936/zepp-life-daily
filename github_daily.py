"""Opt-in Zepp GitHub Actions worker. No stored credentials or retries.

The 'reserve' job queries GitHub's artifact API and uploads a marker BEFORE the
'upload' job is allowed to connect to Zepp. A missing/unreadable marker check,
failed artifact upload, re-run attempt, or out-of-window invocation fails closed.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import secrets
import sys
from urllib.parse import urlencode
from urllib.request import Request, urlopen

TZ8 = timezone(timedelta(hours=8))
MIN_STEPS, MAX_STEPS = 8000, 13000


def today_in_window(now=None):
    now = now or datetime.now(TZ8)
    local = now.astimezone(TZ8)
    if not 12 <= local.hour <= 23:
        raise RuntimeError("OUTSIDE_1200_2359_UTC8")
    return local.strftime("%Y-%m-%d")


def marker_name(date):
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        raise RuntimeError("INVALID_DATE")
    return "zepp-daily-reserved-" + date


def check_artifact(name, *, repo=None, token=None, opener=urlopen, expected_run_id=None):
    repo = repo or os.environ.get("GITHUB_REPOSITORY", "")
    token = token or os.environ.get("GH_ARTIFACT_TOKEN", "")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo) or not token:
        raise RuntimeError("GITHUB_ARTIFACT_CHECK_UNAVAILABLE")
    url = "https://api.github.com/repos/" + repo + "/actions/artifacts?" + urlencode({"name": name, "per_page": 100})
    request = Request(url, headers={"Accept": "application/vnd.github+json", "Authorization": "Bearer " + token,
                                    "User-Agent": "StepStudioDaily/1", "X-GitHub-Api-Version": "2022-11-28"})
    try:
        with opener(request, timeout=15) as response:
            data = json.load(response)
        rows = data["artifacts"]
        if not isinstance(rows, list) or not isinstance(data["total_count"], int):
            raise ValueError()
        return any(isinstance(item, dict) and item.get("name") == name and item.get("expired") is False
                   and (expected_run_id is None or (isinstance(item.get("workflow_run"), dict)
                                                      and str(item["workflow_run"].get("id")) == str(expected_run_id)))
                   for item in rows)
    except Exception:
        # Never guess "no marker" after an API failure; it could double-write.
        raise RuntimeError("GITHUB_ARTIFACT_CHECK_UNAVAILABLE") from None


def reserve(*, now=None, repo=None, token=None, opener=urlopen, runner_temp=None, output_path=None, choose=None):
    if os.environ.get("GITHUB_RUN_ATTEMPT", "1") != "1":
        return {"status": "rerun_blocked"}
    date = today_in_window(now)
    if check_artifact(marker_name(date), repo=repo, token=token, opener=opener):
        return {"status": "already_reserved", "date": date}
    steps = choose() if choose is not None else MIN_STEPS + secrets.randbelow(MAX_STEPS - MIN_STEPS + 1)
    if type(steps) is not int or not MIN_STEPS <= steps <= MAX_STEPS:
        raise RuntimeError("INVALID_TARGET")
    folder = Path(runner_temp if runner_temp is not None else os.environ.get("RUNNER_TEMP", ""))
    output = Path(output_path if output_path is not None else os.environ.get("GITHUB_OUTPUT", ""))
    if not folder.is_dir() or not output.is_file():
        raise RuntimeError("GITHUB_RUNTIME_REQUIRED")
    marker = folder / "zepp-daily-reservation.json"
    # Marker has no account, password, token, raw server reply or activity payload.
    marker.write_text(json.dumps({"date": date, "target": steps, "reserved": True}), encoding="utf-8")
    # The upload job depends on the marker upload STEP succeeding in this job.
    with output.open("a", encoding="utf-8") as file:
        file.write("date=" + date + "\ntarget=" + str(steps) + "\nshould_run=true\n")
    return {"status": "reserved_pending_artifact_upload", "date": date, "target": steps}


def upload(*, now=None, client=None, date=None, target=None, account=None, password=None):
    if os.environ.get("GITHUB_RUN_ATTEMPT", "1") != "1":
        raise RuntimeError("RERUN_BLOCKED")
    date = date or os.environ.get("DAILY_DATE", "")
    chosen = target if target is not None else os.environ.get("DAILY_TARGET", "")
    if isinstance(chosen, str) and re.fullmatch(r"[0-9]{4,5}", chosen):
        chosen = int(chosen)
    if type(chosen) is not int or not MIN_STEPS <= chosen <= MAX_STEPS:
        raise RuntimeError("INVALID_TARGET")
    if today_in_window(now) != date:
        raise RuntimeError("DATE_CHANGED_OR_OUTSIDE_WINDOW")
    account = account if account is not None else os.environ.get("ZEPP_ACCOUNT", "")
    password = password if password is not None else os.environ.get("ZEPP_PASSWORD", "")
    if not account or not password:
        raise RuntimeError("GITHUB_SECRETS_MISSING")
    # Check that THIS workflow run uploaded the daily marker in its completed
    # reserve job. A direct invocation or a failed marker upload cannot write.
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    if not run_id.isdecimal() or not check_artifact(marker_name(date), expected_run_id=run_id):
        raise RuntimeError("CURRENT_RUN_RESERVATION_MISSING")
    # Only this job receives Secrets; reserve/check/status never receive them.
    from zepp_client import ZeppClient, normalize_account, summary_record
    account = normalize_account(account)
    service = client if client is not None else ZeppClient()
    auth = service.login(account, password)
    account = password = None
    before = service.read_steps(auth, date)
    values = before.get("steps") if isinstance(before, dict) else None
    if not isinstance(values, list) or not all(type(v) is int and v >= 0 for v in values):
        raise RuntimeError("READBACK_INVALID")
    if values and max(values) >= chosen:
        return {"status": "skipped_existing_not_lower", "date": date, "target": chosen}
    if today_in_window(now) != date:
        raise RuntimeError("DATE_CHANGED_OR_OUTSIDE_WINDOW")
    # Exactly one write; on timeout result is UNKNOWN and not repeated.
    result = service.upload(auth, summary_record(date, chosen, auth.device_id))
    if result.get("accepted") is not True:
        raise RuntimeError("ACCEPTANCE_NOT_CONFIRMED")
    try:
        after = service.read_steps(auth, date)
        matched = chosen in after.get("steps", []) if isinstance(after, dict) else False
    except Exception:
        matched = False
    return {"status": "cloud_matched_wechat_unverified" if matched else "accepted_readback_unverified",
            "date": date, "target": chosen}


def main(argv=None):
    cmd = argv[0] if argv else (sys.argv[1] if len(sys.argv) == 2 else "")
    if cmd not in ("reserve", "upload"):
        print("Usage: python github_daily.py reserve|upload")
        return 2
    try:
        if cmd == "reserve":
            if os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch":
                # Manual workflow test cannot contact Zepp or create a marker.
                current = datetime.now(TZ8)
                print(json.dumps({"status": "manual_dry_run", "date": current.strftime("%Y-%m-%d"),
                                  "windowOpen": 12 <= current.hour <= 23}, ensure_ascii=False))
                return 0
            result = reserve()
        else:
            result = upload()
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        # Reserve job has no third-party dependencies. Do not import Requests
        # merely to print a sanitized failure of the GitHub artifact check.
        upstream_type = ()
        if cmd == "upload":
            try:
                from zepp_client import UpstreamError
                upstream_type = UpstreamError
            except ImportError:
                pass
        if isinstance(exc, upstream_type):
            print(json.dumps({"status": "stopped", "stage": exc.stage, "code": exc.code,
                              "writeUncertain": bool(exc.uncertain)}, ensure_ascii=False))
        else:
            # Do not print exceptions, credential values, URLs or upstream responses.
            allowed = {"OUTSIDE_1200_2359_UTC8", "INVALID_TARGET", "INVALID_DATE", "GITHUB_ARTIFACT_CHECK_UNAVAILABLE",
                       "GITHUB_RUNTIME_REQUIRED", "RERUN_BLOCKED", "GITHUB_SECRETS_MISSING", "READBACK_INVALID",
                       "ACCEPTANCE_NOT_CONFIRMED", "DATE_CHANGED_OR_OUTSIDE_WINDOW", "CURRENT_RUN_RESERVATION_MISSING"}
            code = str(exc)
            print(json.dumps({"status": "stopped", "code": code if code in allowed else "LOCAL_OR_LOGIN_ERROR"}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
