#!/usr/bin/env python3
"""Safely install the organization-engine /api/office adapter into local OpenClawfice."""
from datetime import datetime, timezone
from pathlib import Path
import shutil
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
UI_ROOT = Path.home() / "openclawfice"
PAGE = UI_ROOT / "app" / "page.tsx"
ROUTE = UI_ROOT / "app" / "api" / "office" / "route.ts"
ROUTE_SOURCE = REPO_ROOT / "ui-bridge" / "office-route.ts"

OLD = """              needs: defaults.needs,
              skills: a.skills || defaults.skills,
              xp: a.xp || defaults.xp,
              level: a.level || defaults.level,"""
NEW = """              // Preserve source values, including legitimate zero/empty values.
              // The organization engine does not currently calculate gamified metrics.
              needs: a.needs || defaults.needs,
              skills: Array.isArray(a.skills) ? a.skills : defaults.skills,
              xp: typeof a.xp === 'number' ? a.xp : defaults.xp,
              level: typeof a.level === 'number' ? a.level : defaults.level,"""


def main():
    if not PAGE.is_file() or not ROUTE_SOURCE.is_file():
        raise SystemExit("Required file missing. Expected ~/openclawfice and this repository checkout.")
    page_text = PAGE.read_text(encoding="utf-8")
    if OLD in page_text:
        patched_page = page_text.replace(OLD, NEW, 1)
    elif NEW in page_text:
        patched_page = page_text
    else:
        raise SystemExit("OpenClawfice page block differs from the reviewed version; stopped without changes.")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = Path.home() / ".cache" / "office-ui-bridge-backups" / stamp
    backup_dir.mkdir(parents=True, exist_ok=False)
    shutil.copy2(PAGE, backup_dir / "page.tsx")
    if ROUTE.exists():
        shutil.copy2(ROUTE, backup_dir / "route.ts")

    temp_page = PAGE.with_suffix(".tsx.office-ui-bridge.tmp")
    temp_page.write_text(patched_page, encoding="utf-8")
    temp_page.replace(PAGE)

    ROUTE.parent.mkdir(parents=True, exist_ok=True)
    temp_route = ROUTE.with_suffix(".ts.office-ui-bridge.tmp")
    shutil.copy2(ROUTE_SOURCE, temp_route)
    temp_route.replace(ROUTE)

    print("Installed the read-only organization adapter.")
    print(f"Backup: {backup_dir}")
    print("No database, agent runtime, or existing engine files were changed.")
    print("Next: set OFFICE_API_URL and OFFICE_API_TOKEN in OpenClawfice's server-side .env.local.")


if __name__ == "__main__":
    main()
