#!/usr/bin/env bash
# Run locally in Termux. OFFICE_SYNC_PASS must be entered locally and never shared.
set -euo pipefail
: "${OFFICE_SYNC_PASS:?ادخل OFFICE_SYNC_PASS محليًا أولًا}"
test "${#OFFICE_SYNC_PASS}" -ge 32 || { echo "مفتاح المزامنة يجب أن يكون 32 حرفًا على الأقل." >&2; exit 1; }
for cmd in curl openssl python; do command -v "$cmd" >/dev/null || { echo "الأمر غير موجود: $cmd" >&2; exit 1; }; done
umask 077
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
BASE="https://raw.githubusercontent.com/khd98me-svg/org-agents/office-sync"
curl --fail --silent --show-error --location "$BASE/snapshot.enc" -o "$TMP/snapshot.enc"
curl --fail --silent --show-error --location "$BASE/snapshot.hmac" -o "$TMP/snapshot.hmac"
python - "$OFFICE_SYNC_PASS" "$TMP/snapshot.enc" "$TMP/snapshot.hmac" <<'PY'
import hashlib, hmac, pathlib, sys
password, encrypted, signature = sys.argv[1:]
key = hashlib.pbkdf2_hmac("sha256", password.encode(), b"org-office-sync-integrity-v1", 200000)
expected = pathlib.Path(signature).read_text(encoding="ascii").strip()
actual = hmac.new(key, pathlib.Path(encrypted).read_bytes(), hashlib.sha256).hexdigest()
if not hmac.compare_digest(expected, actual):
    raise SystemExit("رفض اللقطة: فشل التحقق من سلامة التوقيع؛ لم يتم فك التشفير.")
print("تم التحقق من سلامة اللقطة المشفرة.")
PY
openssl enc -d -aes-256-cbc -pbkdf2 -pass env:OFFICE_SYNC_PASS \
  -in "$TMP/snapshot.enc" -out "$TMP/snapshot.json"
python - "$TMP/snapshot.json" <<'PY'
import json,sys
with open(sys.argv[1], encoding="utf-8") as f:
    d=json.load(f)
assert d.get("read_only") is True, "snapshot is not marked read-only"
required=("agents","departments","tasks","approvals","runs","counts")
assert all(k in d for k in required), "snapshot is incomplete"
assert isinstance(d["agents"], list) and isinstance(d["tasks"], list)
print("تم فك لقطة المكتب والتحقق من بنيتها.")
print("الموظفون:", d.get("counts", {}).get("agents", 0))
print("المهام المفتوحة:", d.get("counts", {}).get("open_tasks", 0))
PY
export OFFICE_SNAPSHOT="$TMP/snapshot.json"
export OFFICE_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
echo "افتح http://127.0.0.1:8765 من هذا الجهاز."
echo "رمز الاتصال المؤقت (أدخله في واجهة المكتب): $OFFICE_TOKEN"
python "$(dirname "$0")/server.py"
