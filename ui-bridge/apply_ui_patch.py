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
MANAGE_ROUTE = UI_ROOT / "app" / "api" / "office" / "manage" / "route.ts"
INSTRUMENTATION = UI_ROOT / "instrumentation.ts"
LEGACY_CONFIG = UI_ROOT / "app" / "api" / "office" / "config" / "route.ts"
LEGACY_MEETING = UI_ROOT / "app" / "api" / "office" / "meeting" / "route.ts"
LEGACY_AUTOWORK = UI_ROOT / "app" / "api" / "office" / "autowork" / "route.ts"
LEGACY_CHAT = UI_ROOT / "app" / "api" / "office" / "chat" / "route.ts"
ROUTE_SOURCE = REPO_ROOT / "ui-bridge" / "office-route.ts"
ACTIONS_SOURCE = REPO_ROOT / "ui-bridge" / "actions-route.ts"
MANAGE_SOURCE = REPO_ROOT / "ui-bridge" / "manage-route.ts"
INSTRUMENTATION_SOURCE = REPO_ROOT / "ui-bridge" / "instrumentation-safe.ts"
LEGACY_CONFIG_SOURCE = REPO_ROOT / "ui-bridge" / "legacy-config-route.ts"
LEGACY_MEETING_SOURCE = REPO_ROOT / "ui-bridge" / "legacy-meeting-route.ts"
LEGACY_AUTOWORK_SOURCE = REPO_ROOT / "ui-bridge" / "legacy-autowork-route.ts"
LEGACY_CHAT_SOURCE = REPO_ROOT / "ui-bridge" / "legacy-chat-route.ts"
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


ORG_PAGE = UI_ROOT / "app" / "organization" / "page.tsx"
ORG_PAGE_SOURCE = (REPO_ROOT / "ui-bridge" / "organization-page.tsx").read_text(encoding="utf-8")
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
    if not all(path.is_file() for path in (PAGE, ROUTE_SOURCE, ACTIONS_SOURCE, MANAGE_SOURCE, INSTRUMENTATION_SOURCE, INSTRUMENTATION, LEGACY_CONFIG_SOURCE, LEGACY_MEETING_SOURCE, LEGACY_AUTOWORK_SOURCE, LEGACY_CHAT_SOURCE)):
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
        (MANAGE_ROUTE, "manage-route.ts"),
        (ORG_PAGE, "organization-page.tsx"),
        (INSTRUMENTATION, "instrumentation.ts"),
        (LEGACY_CONFIG, "legacy-config-route.ts"),
        (LEGACY_MEETING, "legacy-meeting-route.ts"),
        (LEGACY_AUTOWORK, "legacy-autowork-route.ts"),
        (LEGACY_CHAT, "legacy-chat-route.ts"),
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
        (MANAGE_ROUTE, MANAGE_SOURCE, "manage-route.ts"),
        (INSTRUMENTATION, INSTRUMENTATION_SOURCE, "instrumentation.ts"),
        (LEGACY_CONFIG, LEGACY_CONFIG_SOURCE, "legacy-config-route.ts"),
        (LEGACY_MEETING, LEGACY_MEETING_SOURCE, "legacy-meeting-route.ts"),
        (LEGACY_AUTOWORK, LEGACY_AUTOWORK_SOURCE, "legacy-autowork-route.ts"),
        (LEGACY_CHAT, LEGACY_CHAT_SOURCE, "legacy-chat-route.ts"),
    ):
        temp = target.with_name(target.name + ".office-ui-bridge.tmp")
        shutil.copy2(source, temp)
        temp.replace(target)

    ORG_PAGE.parent.mkdir(parents=True, exist_ok=True)
    org_temp = ORG_PAGE.with_name("page.tsx.office-ui-bridge.tmp")
    org_temp.write_text(ORG_PAGE_SOURCE, encoding="utf-8")
    org_temp.replace(ORG_PAGE)

    configure_env()
    print("Installed the read-only organization adapter, Quest Log feed and organization dashboard.")
    print(f"Backup: {backup_dir}")
    print("Quest Log displays only approvals whose database status is pending.")
    print("Approval decisions and agent execution remain disabled.")
    print("Owner-confirmed profile edits are limited to agent name/specialty and department name/description; each edit is audited.")
    print("Legacy OpenClaw autowork and watercooler background tickers are disabled.")
    print("Legacy config, meeting, autowork, and chat write endpoints return HTTP 405.")
    print("Organization dashboard: http://localhost:3333/organization")
    print("The local bridge secret remains in .env.local and was not displayed.")


if __name__ == "__main__":
    main()
