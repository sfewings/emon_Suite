#!/usr/bin/env python3
"""
Export all Grafana dashboards as provisioning-ready JSON files.

This replicates the "Export as Code" operation from the Grafana UI for every
dashboard in the instance. The exported JSON omits the internal 'id' field
and sets 'version' to 1, matching the UI export format.

Usage:
    # Using a provisioning site (reads .env for URL/credentials, auto-sets output dir):
    python grafana_export_dashboards.py --site harvey-farm
    python grafana_export_dashboards.py --site shannstainable

    # Manual options:
    python grafana_export_dashboards.py --url http://localhost:3000 --token <API_KEY>
    python grafana_export_dashboards.py --url http://localhost:3000 --user admin --password admin

Environment variables GRAFANA_URL and GRAFANA_TOKEN can be used instead of
command-line arguments.
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path
import requests


PROVISIONING_DIR = Path(__file__).resolve().parent.parent.parent / "provisioning"


def load_env_file(env_path: Path) -> dict[str, str]:
    """Parse a simple KEY=VALUE .env file, ignoring comments and blank lines."""
    env = {}
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, _, value = line.partition("=")
            if _:
                env[key.strip()] = value.strip()
    return env


def list_sites() -> list[str]:
    """Return names of provisioning subfolders that contain a .env file."""
    if not PROVISIONING_DIR.is_dir():
        return []
    return sorted(
        d.name
        for d in PROVISIONING_DIR.iterdir()
        if d.is_dir() and (d / ".env").is_file()
    )


def apply_site(args, site_name: str):
    """Load .env from a provisioning site and fill in args defaults."""
    site_dir = PROVISIONING_DIR / site_name
    env_path = site_dir / ".env"
    if not env_path.is_file():
        available = list_sites()
        sys.exit(
            f"Error: no .env found for site '{site_name}' "
            f"(looked at {env_path}).\n"
            f"Available sites: {', '.join(available) or 'none'}"
        )

    env = load_env_file(env_path)

    if not args.url:
        args.url = env.get("GRAFANA_URL")
    if not args.user:
        args.user = env.get("GRAFANA_USERNAME")
    if not args.password:
        args.password = env.get("GRAFANA_PASSWORD")
    if not args.output_dir:
        args.output_dir = str(site_dir / "grafana-provisioning" / "dashboards")


def sanitise_filename(name: str) -> str:
    """Replace characters that are unsafe in filenames."""
    return re.sub(r'[<>:"/\\|?*]', "_", name).strip()


def get_session(args) -> requests.Session:
    session = requests.Session()
    if args.token:
        session.headers["Authorization"] = f"Bearer {args.token}"
    elif args.user and args.password:
        session.auth = (args.user, args.password)
    else:
        sys.exit(
            "Error: provide either --token or --user/--password "
            "(or set GRAFANA_URL / GRAFANA_TOKEN environment variables)."
        )
    return session


def search_dashboards(session: requests.Session, base_url: str) -> list[dict]:
    """Return a list of all dashboard search-hit dicts."""
    dashboards = []
    page = 1
    limit = 1000
    while True:
        resp = session.get(
            f"{base_url}/api/search",
            params={"type": "dash-db", "limit": limit, "page": page},
        )
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        dashboards.extend(batch)
        if len(batch) < limit:
            break
        page += 1
    return dashboards


def fetch_dashboard(session: requests.Session, base_url: str, uid: str) -> dict:
    """Fetch the full dashboard model by UID."""
    resp = session.get(f"{base_url}/api/dashboards/uid/{uid}")
    resp.raise_for_status()
    return resp.json()


def export_as_code(dashboard_body: dict) -> dict:
    """
    Transform the API response into the 'Export as Code' format:
    - Extract the 'dashboard' model
    - Remove the internal 'id' field
    - Set 'version' to 1
    """
    model = dashboard_body["dashboard"]
    model.pop("id", None)
    model["version"] = 1
    return model


def main():
    parser = argparse.ArgumentParser(
        description="Export all Grafana dashboards as provisioning-ready JSON."
    )
    parser.add_argument(
        "--site",
        metavar="NAME",
        help=(
            "Provisioning site name (subfolder of provisioning/). "
            "Reads GRAFANA_URL, GRAFANA_USERNAME, GRAFANA_PASSWORD from its "
            ".env file and exports to its grafana-provisioning/dashboards/ dir. "
            f"Available: {', '.join(list_sites()) or 'none found'}"
        ),
    )
    parser.add_argument(
        "--url",
        default=os.environ.get("GRAFANA_URL"),
        help="Grafana base URL (default: $GRAFANA_URL or from --site .env)",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("GRAFANA_TOKEN"),
        help="Grafana API token / service-account token (default: $GRAFANA_TOKEN)",
    )
    parser.add_argument("--user", help="Basic-auth username")
    parser.add_argument("--password", help="Basic-auth password")
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory to write exported JSON files (default: grafana_dashboards, or from --site)",
    )
    parser.add_argument(
        "--folder-structure",
        action="store_true",
        help="Mirror Grafana folder structure in the output directory",
    )
    args = parser.parse_args()

    if args.site:
        apply_site(args, args.site)

    if not args.url:
        args.url = "http://localhost:3000"
    if not args.output_dir:
        args.output_dir = "grafana_dashboards"

    base_url = args.url.rstrip("/")
    session = get_session(args)

    # Verify connectivity
    try:
        health = session.get(f"{base_url}/api/health", timeout=10)
        health.raise_for_status()
    except requests.RequestException as exc:
        sys.exit(f"Cannot reach Grafana at {base_url}: {exc}")

    print(f"Connected to Grafana at {base_url}")

    # Enumerate dashboards
    hits = search_dashboards(session, base_url)
    print(f"Found {len(hits)} dashboard(s)")

    if not hits:
        return

    os.makedirs(args.output_dir, exist_ok=True)

    exported = 0
    errors = 0

    for hit in hits:
        uid = hit["uid"]
        title = hit.get("title", uid)
        folder = hit.get("folderTitle", "General")

        try:
            body = fetch_dashboard(session, base_url, uid)
            model = export_as_code(body)

            if args.folder_structure:
                dest_dir = os.path.join(args.output_dir, sanitise_filename(folder))
            else:
                dest_dir = args.output_dir

            os.makedirs(dest_dir, exist_ok=True)
            filename = f"{sanitise_filename(title)}.json"
            filepath = os.path.join(dest_dir, filename)

            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(model, f, indent=2, ensure_ascii=False)
                f.write("\n")

            exported += 1
            print(f"  [{exported}/{len(hits)}] {folder}/{title} -> {filepath}")

        except Exception as exc:
            errors += 1
            print(f"  ERROR exporting '{title}' (uid={uid}): {exc}", file=sys.stderr)

    print(f"\nDone. Exported {exported} dashboard(s), {errors} error(s).")
    if exported:
        print(f"Files written to: {os.path.abspath(args.output_dir)}")


if __name__ == "__main__":
    main()
