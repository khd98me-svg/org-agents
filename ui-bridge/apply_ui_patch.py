#!/usr/bin/env python3
"""Safely install the read-only organization adapter and Quest Log approvals feed."""
from datetime import datetime, timezone
from pathlib import Path
import secrets
import shutil

REPO_ROOT = Path(__file__).resolve().parents[1]
UI_ROOT = Path.home() / "openclawfice"
PAGE = UI_ROOT / "app" / "page.tsx"
ROUTE = UI_ROOT / "app" / "api" / "office" / "route.ts"
ACTIONS_ROUTE = UI_ROOT / "app" / "api" / "office" / "actions" / "route.ts"
INSTRUMENTATION = UI_ROOT / "instrumentation.ts"
ROUTE_SOURCE = REPO_ROOT / "ui-bridge" / "office-route.ts"
ACTIONS_SOURCE = REPO_ROOT / "ui-bridge" / "actions-route.ts"
INSTRUMENTATION_SOURCE = REPO_ROOT / "ui-bridge" / "instrumentation-safe.ts"
ENV_FILE = UI_ROOT / ".env.local"

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

READ_ONLY_START = """              {/* Options buttons */}"""
READ_ONLY_WRAPPED_START = """              {action.data?.readOnly ? (
                <div style={{
                  background: 'rgba(245,158,11,0.08)',
                  border: '1px solid rgba(245,158,11,0.35)',
                  borderRadius: 6,
                  padding: 10,
                  color: '#fbbf24',
                  fontSize: 11,
                  lineHeight: 1.6,
                }}>
                  🛡️ عرض فقط — هذا طلب موافقة حقيقي من محرك المؤسسة.
                  <br />
                  أزرار الاعتماد غير مفعّلة حتى يكتمل ربط القرار الآمن بالمحرك.
                </div>
              ) : (
                <>
              {/* Options buttons */}"""

READ_ONLY_END = """              )}
            </div>
          </div>
        );
      })()}"""
READ_ONLY_WRAPPED_END = """              )}
                </>
              )}
            </div>
          </div>
        );
      })()}"""


def configure_env():
    text = ENV_FILE.read_text(encoding="utf-8") if ENV_FILE.exists() else ""
    lines = text.splitlines()
    token = ""
    for line in lines:
        if line.startswith("OFFICE_API_TOKEN="):
            token = line.split("=", 1)[1].strip().strip('"').strip("'")
            if token:
                break
    values = {
        "OFFICE_API_URL": "http://127.0.0.1:8765/api/office",
        "OFFICE_API_TOKEN": token or secrets.token_urlsafe(32),
    }
    seen = set()
    output = []
    for line in lines:
        key = line.split("=", 1)[0] if "=" in line else ""
        if key in values:
            if key not in seen:
                output.append(f"{key}={values[key]}")
                seen.add(key)
        else:
            output.append(line)
    for key, value in values.items():
        if key not in seen:
            output.append(f"{key}={value}")
    temp = ENV_FILE.with_name(".env.local.office-ui-bridge.tmp")
    temp.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")
    temp.replace(ENV_FILE)


def main():
    if not all(path.is_file() for path in (PAGE, ROUTE_SOURCE, ACTIONS_SOURCE, INSTRUMENTATION_SOURCE, INSTRUMENTATION)):
        raise SystemExit("Required file missing. Expected ~/openclawfice and both bridge route sources.")
    page_text = PAGE.read_text(encoding="utf-8")

    if OLD in page_text:
        patched_page = page_text.replace(OLD, NEW, 1)
    elif NEW in page_text:
        patched_page = page_text
    else:
        raise SystemExit("OpenClawfice agent normalization block differs; stopped without changes.")

    # Replace OpenClawfice's stale empty-state source label. The Quest Log
    # endpoint is now backed by organization.db:approvals, not actions.json.
    legacy_source = "(Pulled from ~/.openclaw/.status/actions.json)"
    current_source = "(Source: organization.db — pending approvals)"
    if legacy_source in patched_page:
        patched_page = patched_page.replace(legacy_source, current_source, 1)

    if READ_ONLY_START in patched_page:
        patched_page = patched_page.replace(READ_ONLY_START, READ_ONLY_WRAPPED_START, 1)
        if READ_ONLY_END not in patched_page:
            raise SystemExit("Quest modal closing block differs; stopped without changes.")
        patched_page = patched_page.replace(READ_ONLY_END, READ_ONLY_WRAPPED_END, 1)
    elif READ_ONLY_WRAPPED_START in patched_page and READ_ONLY_WRAPPED_END in patched_page:
        pass
    else:
        raise SystemExit("Quest Log modal differs from reviewed version; stopped without changes.")

    respond_old = """        const respondAction = async (response: string) => {
          await secureFetch('/api/office/actions', {"""
    respond_new = """        const respondAction = async (response: string) => {
          if (action.data?.readOnly) return;
          await secureFetch('/api/office/actions', {"""
    if respond_old in patched_page:
        patched_page = patched_page.replace(respond_old, respond_new, 1)
    elif respond_new not in patched_page:
        raise SystemExit("Quest response handler differs; stopped without changes.")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = Path.home() / ".cache" / "office-ui-bridge-backups" / stamp
    backup_dir.mkdir(parents=True, exist_ok=False)
    for path, name in (
        (PAGE, "page.tsx"),
        (ROUTE, "office-route.ts"),
        (ACTIONS_ROUTE, "actions-route.ts"),
        (INSTRUMENTATION, "instrumentation.ts"),
        (ENV_FILE, ".env.local"),
    ):
        if path.exists():
            shutil.copy2(path, backup_dir / name)

    temp_page = PAGE.with_name("page.tsx.office-ui-bridge.tmp")
    temp_page.write_text(patched_page, encoding="utf-8")
    temp_page.replace(PAGE)

    ROUTE.parent.mkdir(parents=True, exist_ok=True)
    for target, source, label in (
        (ROUTE, ROUTE_SOURCE, "office-route.ts"),
        (ACTIONS_ROUTE, ACTIONS_SOURCE, "actions-route.ts"),
        (INSTRUMENTATION, INSTRUMENTATION_SOURCE, "instrumentation.ts"),
    ):
        temp = target.with_name(target.name + ".office-ui-bridge.tmp")
        shutil.copy2(source, temp)
        temp.replace(target)

    configure_env()
    print("Installed the read-only organization adapter and Quest Log approvals feed.")
    print(f"Backup: {backup_dir}")
    print("Quest Log displays only approvals whose database status is pending.")
    print("Approval decisions remain disabled; no database or engine files were changed.")
    print("Legacy OpenClaw autowork and watercooler background tickers are disabled.")
    print("The local bridge secret remains in .env.local and was not displayed.")


if __name__ == "__main__":
    main()
