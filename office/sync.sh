#!/usr/bin/env bash
# Run locally in Termux. Requires OFFICE_SYNC_PASS to be entered locally.
set -euo pipefail
: "${OFFICE_SYNC_PASS:?ادخل OFFICE_SYNC_PASS محليًا أولًا}"
test "${#OFFICE_SYNC_PASS}" -ge 32 || { echo "مفتاح المزامنة يجب أن يكون 32 حرفًا على الأقل." >&2; exit 1; }
for cmd in curl openssl python; do command -v "$cmd" >/dev/null || { echo "الأمر غير موجود: $cmd" >&2; exit 1; }; done
umask 077
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
URL="https://raw.githubusercontent.com/khd98me-svg/org-agents/office-sync/snapshot.enc"
curl --fail --silent --show-error --location "$URL" -o "$TMP/snapshot.enc"
openssl enc -d -aes-256-cbc -pbkdf2 -pass env:OFFICE_SYNC_PASS \
  -in "$TMP/snapshot.enc" -out "$TMP/snapshot.json"
python - "$TMP/snapshot.json" <<'PY'
import json,sys
with open(sys.argv[1], encoding="utf-8") as f:
    d=json.load(f)
assert d.get("read_only") is True, "snapshot is not marked read-only"
assert isinstance(d.get("agents"), list) and isinstance(d.get("tasks"), list)
print("تم فك لقطة المكتب والتحقق منها.")
print("الموظفون:", d.get("counts", {}).get("agents", 0))
print("المهام المفتوحة:", d.get("counts", {}).get("open_tasks", 0))
PY
export OFFICE_SNAPSHOT="$TMP/snapshot.json"
export OFFICE_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
echo "افتح http://127.0.0.1:8765 من هذا الجهاز."
echo "رمز الاتصال المؤقت (أدخله في واجهة المكتب): $OFFICE_TOKEN"
python "$(dirname "$0")/server.py"
