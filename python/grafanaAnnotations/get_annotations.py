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
    python get_annotations.py --add -                  # add annotation from stdin
    python get_annotations.py --add file.txt           # add annotations from file
"""

import argparse
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests


#GRAFANA_URL = "http://10.0.0.114:3000"
GRAFANA_URL = "http://192.168.1.131:3000"
GRAFANA_USER = "admin"
GRAFANA_PASSWORD = "password"
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


def parse_timestamp(time_str):
    """Parse a local timezone timestamp string (YYYY-MM-DD HH:MM:SS).
    
    Input is interpreted as LOCAL_TZ (Australia/Perth), then converted to UTC
    milliseconds for Grafana API. This ensures annotations appear at the correct
    local time in Grafana.
    """
    for fmt in ("%Y-%m-%d %H:%M:%S",):
        try:
            # Parse as naive datetime, then localize to LOCAL_TZ
            naive_dt = datetime.strptime(time_str, fmt)
            local_dt = naive_dt.replace(tzinfo=LOCAL_TZ)
            # Convert to UTC milliseconds
            return int(local_dt.timestamp() * 1000)
        except ValueError:
            continue
    raise ValueError(f"Invalid timestamp format: {time_str}")


def parse_tags(tags_str):
    """Parse comma-separated tags into a list."""
    if not tags_str or not tags_str.strip():
        return []
    return [tag.strip() for tag in tags_str.split(",")]


def annotation_exists(dashboard_uid, text, ts_ms, tags=None, panel_id=None):
    """Check if an annotation with the same properties already exists."""
    try:
        # Resolve dashboard UID to internal ID
        dash = requests.get(
            f"{GRAFANA_URL}/api/dashboards/uid/{dashboard_uid}",
            auth=(GRAFANA_USER, GRAFANA_PASSWORD),
            timeout=10,
        )
        dash.raise_for_status()
        dashboard_id = dash.json()["dashboard"]["id"]

        # Query annotations for this dashboard
        params = {
            "type": "annotation",
            "dashboardId": dashboard_id,
            "from": int(ts_ms - 60000),  # Check 1 minute before
            "to": int(ts_ms + 60000),   # Check 1 minute after
            "limit": 100,
        }

        resp = requests.get(
            f"{GRAFANA_URL}/api/annotations",
            params=params,
            auth=(GRAFANA_USER, GRAFANA_PASSWORD),
            timeout=10,
        )
        resp.raise_for_status()
        annotations = resp.json()

        # Check for matching annotation
        for ann in annotations:
            if (ann.get("text") == text and
                abs(ann.get("time", 0) - ts_ms) < 1000 and  # Within 1 second
                (panel_id is None or ann.get("panelId") == panel_id)):
                return True

        return False
    except requests.RequestException:
        return False


def add_annotation(dashboard_uid, time_ms, text, tags=None, panel_id=None, time_end_ms=None):
    """Add an annotation to a dashboard via Grafana API."""
    try:
        # Resolve dashboard UID to internal ID
        dash = requests.get(
            f"{GRAFANA_URL}/api/dashboards/uid/{dashboard_uid}",
            auth=(GRAFANA_USER, GRAFANA_PASSWORD),
            timeout=10,
        )
        dash.raise_for_status()
        dashboard_id = dash.json()["dashboard"]["id"]

        # Prepare annotation payload
        payload = {
            "dashboardId": dashboard_id,
            "time": time_ms,
            "text": text,
            "tags": tags or [],
        }

        if panel_id:
            payload["panelId"] = panel_id

        if time_end_ms:
            payload["timeEnd"] = time_end_ms

        # Create annotation
        resp = requests.post(
            f"{GRAFANA_URL}/api/annotations",
            json=payload,
            auth=(GRAFANA_USER, GRAFANA_PASSWORD),
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    except requests.RequestException as e:
        raise RuntimeError(f"Failed to add annotation: {e}")


def parse_annotation_line(line):
    """Parse a tab-separated annotation line.
    
    Format: Time|End Time|Text|Tags|Dashboard|Panel ID
    """
    parts = line.split("|")
    if len(parts) < 4:
        raise ValueError(f"Invalid annotation format: {line}")

    time_str = parts[0].strip()
    end_time_str = parts[1].strip()
    text = parts[2].strip()
    tags_str = parts[3].strip()
    dashboard_uid = parts[4].strip() if len(parts) > 4 else None
    panel_id_str = parts[5].strip() if len(parts) > 5 else None

    if not time_str or not text or not dashboard_uid:
        raise ValueError(f"Missing required fields in: {line}")

    time_ms = parse_timestamp(time_str)
    time_end_ms = parse_timestamp(end_time_str) if end_time_str else None
    tags = parse_tags(tags_str)
    panel_id = int(panel_id_str) if panel_id_str else None

    return {
        "time_ms": time_ms,
        "text": text,
        "tags": tags,
        "dashboard_uid": dashboard_uid,
        "panel_id": panel_id,
        "time_end_ms": time_end_ms,
    }


def process_add_annotations(input_source):
    """Process and add annotations from input source (file or stdin).
    
    Input format (tab-separated):
    Time|End Time|Text|Tags|Dashboard|Panel ID
    """
    if input_source == "-":
        lines = sys.stdin.readlines()
    else:
        try:
            with open(input_source, "r") as f:
                lines = f.readlines()
        except FileNotFoundError:
            print(f"Error: File not found: {input_source}", file=sys.stderr)
            sys.exit(1)

    added_count = 0
    skipped_count = 0
    error_count = 0

    # Skip header line if present
    if lines and "|" in lines[0] and "Time" in lines[0]:
        lines = lines[1:]

    for line_num, line in enumerate(lines, start=2 if input_source != "-" else 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        try:
            ann_data = parse_annotation_line(line)

            # Check if annotation already exists
            if annotation_exists(
                ann_data["dashboard_uid"],
                ann_data["text"],
                ann_data["time_ms"],
                tags=ann_data["tags"],
                panel_id=ann_data["panel_id"],
            ):
                print(f"⚠️  Line {line_num}: Annotation already exists (skipped)", file=sys.stderr)
                print(f"   Dashboard: {ann_data['dashboard_uid']}, Time: {ann_data['time_ms']}, Text: {ann_data['text']}", file=sys.stderr)
                skipped_count += 1
                continue

            # Add annotation
            result = add_annotation(
                ann_data["dashboard_uid"],
                ann_data["time_ms"],
                ann_data["text"],
                tags=ann_data["tags"],
                panel_id=ann_data["panel_id"],
                time_end_ms=ann_data["time_end_ms"],
            )

            print(f"✓ Line {line_num}: Added annotation (ID: {result.get('id', 'unknown')})")
            added_count += 1

        except (ValueError, RuntimeError) as e:
            print(f"✗ Line {line_num}: {e}", file=sys.stderr)
            error_count += 1

    # Summary
    print(f"\nSummary: {added_count} added, {skipped_count} skipped, {error_count} errors")
    return error_count == 0


def main():
    parser = argparse.ArgumentParser(
        description="Fetch or add Grafana annotations",
        epilog="Examples:\n"
               "  %(prog)s --dashboard Orin                    # Fetch from dashboard\n"
               "  %(prog)s --add - < exported.txt              # Add from stdin\n"
               "  %(prog)s --add annotations.txt               # Add from file",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--dashboard", "-d", help="Dashboard UID to filter by (fetch mode)")
    parser.add_argument("--list-dashboards", action="store_true", help="List available dashboards")
    parser.add_argument("--from", dest="from_dt", type=parse_date, help="Start date (YYYY-MM-DD) (fetch mode)")
    parser.add_argument("--to", dest="to_dt", type=parse_date, help="End date (YYYY-MM-DD) (fetch mode)")
    parser.add_argument("--limit", type=int, default=100, help="Max annotations to return (default 100) (fetch mode)")
    parser.add_argument("--add", metavar="FILE", help="Add annotations from file or stdin (-)")
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

    if args.add:
        # Add mode
        success = process_add_annotations(args.add)
        sys.exit(0 if success else 1)

    # Fetch mode (default)
    annotations = get_annotations(
        dashboard_uid=args.dashboard,
        from_dt=args.from_dt,
        to_dt=args.to_dt,
        limit=args.limit,
    )
    print_annotations(annotations)


if __name__ == "__main__":
    main()
