#!/usr/bin/env python3
"""Fetch user annotations from Grafana dashboards.

Grafana stores user-created annotations (the ones added by clicking on a chart)
in its own internal database, not in InfluxDB. This script queries the Grafana
HTTP API to retrieve them.

Usage:
    python get_annotations.py                     # all annotations
    python get_annotations.py --dashboard <uid>   # from specific dashboard
    python get_annotations.py --from 2026-03-01 --to 2026-03-26
    python get_annotations.py --limit 50
"""

import argparse
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests


GRAFANA_URL = "http://10.0.0.114:3000"
GRAFANA_USER = "admin"
GRAFANA_PASSWORD = "admin"
LOCAL_TZ = ZoneInfo("Australia/Perth")


def get_annotations(dashboard_uid=None, from_dt=None, to_dt=None, limit=100):
    """Query Grafana API for user annotations."""
    params = {"type": "annotation", "limit": limit}

    if dashboard_uid:
        # Resolve dashboard UID to internal ID
        dash = requests.get(
            f"{GRAFANA_URL}/api/dashboards/uid/{dashboard_uid}",
            auth=(GRAFANA_USER, GRAFANA_PASSWORD),
            timeout=10,
        )
        dash.raise_for_status()
        params["dashboardId"] = dash.json()["dashboard"]["id"]

    if from_dt:
        params["from"] = int(from_dt.timestamp() * 1000)
    if to_dt:
        params["to"] = int(to_dt.timestamp() * 1000)

    resp = requests.get(
        f"{GRAFANA_URL}/api/annotations",
        params=params,
        auth=(GRAFANA_USER, GRAFANA_PASSWORD),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def list_dashboards():
    """List all dashboards with their UIDs."""
    resp = requests.get(
        f"{GRAFANA_URL}/api/search",
        params={"type": "dash-db"},
        auth=(GRAFANA_USER, GRAFANA_PASSWORD),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def format_timestamp(epoch_ms):
    """Convert epoch milliseconds to local time string."""
    dt = datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc).astimezone(LOCAL_TZ)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def print_annotations(annotations):
    """Print annotations as a tab-separated table, oldest first."""
    if not annotations:
        print("No annotations found.")
        return

    # Sort chronologically (oldest first)
    annotations.sort(key=lambda a: a["time"])

    # Tab-separated header
    print("|".join(["Time", "End Time", "Text", "Tags", "Dashboard", "Panel ID"]))

    for ann in annotations:
        time_str = format_timestamp(ann["time"])
        end_str = format_timestamp(ann["timeEnd"]) if ann.get("timeEnd") and ann["timeEnd"] != ann["time"] else ""
        text = ann.get("text", "").replace("\t", " ").replace("\n", " ")
        tags = ", ".join(ann.get("tags", []))
        dashboard = ann.get("dashboardUID", "")
        panel_id = str(ann.get("panelId", ""))

        print("|".join([time_str, end_str, text, tags, dashboard, panel_id]))


def parse_date(date_str):
    """Parse a date string (YYYY-MM-DD or YYYY-MM-DD HH:MM:SS)."""
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_str, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise argparse.ArgumentTypeError(f"Invalid date format: {date_str}")


def main():
    parser = argparse.ArgumentParser(description="Fetch Grafana annotations")
    parser.add_argument("--dashboard", "-d", help="Dashboard UID to filter by")
    parser.add_argument("--list-dashboards", action="store_true", help="List available dashboards")
    parser.add_argument("--from", dest="from_dt", type=parse_date, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--to", dest="to_dt", type=parse_date, help="End date (YYYY-MM-DD)")
    parser.add_argument("--limit", type=int, default=100, help="Max annotations to return (default 100)")
    args = parser.parse_args()

    if args.list_dashboards:
        dashboards = list_dashboards()
        if not dashboards:
            print("No dashboards found.")
            return
        print("Available dashboards:\n")
        for d in dashboards:
            print(f"  UID: {d['uid']:<20}  Title: {d['title']}")
        return

    annotations = get_annotations(
        dashboard_uid=args.dashboard,
        from_dt=args.from_dt,
        to_dt=args.to_dt,
        limit=args.limit,
    )
    print_annotations(annotations)


if __name__ == "__main__":
    main()
