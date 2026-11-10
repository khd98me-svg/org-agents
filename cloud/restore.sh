#!/usr/bin/env bash
# يستعيد حالة الشركة (قاعدة البيانات + الملفات) من فرع state المشفّر
set -euo pipefail
rm -f /tmp/restore_ok
rc=0
git ls-remote --exit-code --heads origin state >/dev/null 2>&1 || rc=$?
if [ "$rc" = "0" ]; then
  git fetch --depth=1 origin state
  git show FETCH_HEAD:state.tar.enc > /tmp/state.tar.enc
  openssl enc -d -aes-256-cbc -pbkdf2 -pass env:STATE_PASS -in /tmp/state.tar.enc | tar xz -C "$PWD"
  echo "state restored"
elif [ "$rc" = "2" ]; then
  echo "no state branch yet: fresh start"
else
  echo "cannot reach origin (rc=$rc), refusing to start" >&2
  exit 1
fi
if [ -n "${MODELS_JSON:-}" ]; then echo "$MODELS_JSON" > models.json; fi
touch /tmp/restore_ok
