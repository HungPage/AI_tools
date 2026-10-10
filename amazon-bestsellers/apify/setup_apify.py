#!/usr/bin/env python3
"""Create or update the Apify task, Dify webhook and Mon/Thu schedule.

Safe to run repeatedly: existing objects are found by name/URL and updated
instead of duplicated. Only the standard library is used.

    export APIFY_TOKEN=...            # Apify → Settings → API & Integrations
    export DIFY_WEBHOOK_URL=...       # optional; skip to set the webhook later
    python3 setup_apify.py            # task + schedule (+ webhook)
    python3 setup_apify.py --run      # also start one run (uses ~US$0.32 credit)
    python3 setup_apify.py --dry-run  # print the requests, send nothing
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

API = "https://api.apify.com/v2"
ACTOR_ID = "junglee~amazon-bestsellers"
TASK_NAME = "amazon-3c-bestsellers"
SCHEDULE_NAME = "amazon-3c-bestsellers-mon-thu"
CRON = "0 9 * * 1,4"
TIMEZONE = "Asia/Taipei"
HERE = Path(__file__).resolve().parent
INPUT = json.loads((HERE / "input.json").read_text(encoding="utf-8"))
PAYLOAD_TEMPLATE = (HERE / "webhook_payload.txt").read_text(encoding="utf-8")


class Apify:
    def __init__(self, token, dry_run=False):
        self.token = token
        self.dry_run = dry_run

    def call(self, method, path, body=None):
        if self.dry_run and method != "GET":
            print(f"[dry-run] {method} {path}\n{json.dumps(body, ensure_ascii=False, indent=2)}")
            return {"id": "DRY_RUN_ID"}
        if self.dry_run:
            print(f"[dry-run] {method} {path}")
            return {"items": []}
        req = urllib.request.Request(
            API + path,
            method=method,
            data=None if body is None else json.dumps(body).encode(),
            headers={"Authorization": "Bearer " + self.token,
                     "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as res:
                return json.loads(res.read() or b"{}").get("data", {})
        except urllib.error.HTTPError as err:
            sys.exit(f"Apify API {method} {path} failed: {err.code} {err.read().decode(errors='replace')}")


def find(items, **match):
    return next((it for it in items if all(it.get(k) == v for k, v in match.items())), None)


def ensure_task(api):
    task = find(api.call("GET", "/actor-tasks?limit=1000").get("items", []), name=TASK_NAME)
    if task:
        api.call("PUT", f"/actor-tasks/{task['id']}", {"input": INPUT})
        print(f"task updated: {TASK_NAME} ({task['id']})")
        return task["id"]
    task = api.call("POST", "/actor-tasks", {"actId": ACTOR_ID, "name": TASK_NAME, "input": INPUT})
    print(f"task created: {TASK_NAME} ({task['id']})")
    return task["id"]


def ensure_webhook(api, task_id, url):
    body = {
        "eventTypes": ["ACTOR.RUN.SUCCEEDED"],
        "condition": {"actorTaskId": task_id},
        "requestUrl": url,
        "payloadTemplate": PAYLOAD_TEMPLATE,
    }
    hooks = api.call("GET", f"/actor-tasks/{task_id}/webhooks?limit=1000").get("items", [])
    hook = find(hooks, requestUrl=url)
    if hook:
        api.call("PUT", f"/webhooks/{hook['id']}", body)
        print(f"webhook updated ({hook['id']})")
    else:
        hook = api.call("POST", "/webhooks", body)
        print(f"webhook created ({hook['id']})")
    others = [h for h in hooks if h.get("requestUrl") != url]
    if others:
        print(f"note: the task has {len(others)} other webhook(s); remove stale ones in the Apify console")


def ensure_schedule(api, task_id):
    body = {
        "name": SCHEDULE_NAME,
        "cronExpression": CRON,
        "timezone": TIMEZONE,
        "isEnabled": True,
        "isExclusive": True,
        "actions": [{"type": "RUN_ACTOR_TASK", "actorTaskId": task_id}],
    }
    sched = find(api.call("GET", "/schedules?limit=1000").get("items", []), name=SCHEDULE_NAME)
    if sched:
        api.call("PUT", f"/schedules/{sched['id']}", body)
        print(f"schedule updated: {CRON} {TIMEZONE} ({sched['id']})")
    else:
        sched = api.call("POST", "/schedules", body)
        print(f"schedule created: {CRON} {TIMEZONE} ({sched['id']})")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", action="store_true", help="start one task run after setup (uses Apify credit)")
    ap.add_argument("--dry-run", action="store_true", help="print write requests instead of sending them")
    args = ap.parse_args(argv)

    token = os.environ.get("APIFY_TOKEN", "")
    if not token and not args.dry_run:
        sys.exit("APIFY_TOKEN is not set (Apify → Settings → API & Integrations)")
    api = Apify(token, dry_run=args.dry_run)

    task_id = ensure_task(api)
    ensure_schedule(api, task_id)
    url = os.environ.get("DIFY_WEBHOOK_URL", "").strip()
    if url:
        ensure_webhook(api, task_id, url)
    else:
        print("DIFY_WEBHOOK_URL not set: webhook skipped (rerun after publishing the Dify workflow)")
    if args.run:
        run = api.call("POST", f"/actor-tasks/{task_id}/runs")  # no body: a body would override the task input
        print(f"run started: https://console.apify.com/actors/runs/{run.get('id')}")


if __name__ == "__main__":
    main()
