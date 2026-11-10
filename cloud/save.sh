#!/usr/bin/env bash
# يحفظ الحالة مشفّرة في فرع state (commit واحد، بدون تاريخ)
set -euo pipefail
if [ ! -f /tmp/restore_ok ]; then echo "restore did not complete: not saving"; exit 0; fi
mkdir -p workspace
[ -f organization.db ] || { echo "no db: nothing to save"; exit 0; }
tar cz organization.db workspace | openssl enc -aes-256-cbc -pbkdf2 -pass env:STATE_PASS -out /tmp/state.tar.enc
rm -rf /tmp/st && mkdir /tmp/st && cp /tmp/state.tar.enc /tmp/st/state.tar.enc
cd /tmp/st
git init -q && git checkout -q -b state && git add state.tar.enc
git -c user.name=org-bot -c user.email=org-bot@users.noreply.github.com commit -q -m "state $(date -u +%FT%TZ)"
REMOTE="${STATE_REMOTE:-https://x-access-token:${GITHUB_TOKEN}@github.com/${GITHUB_REPOSITORY}.git}"
git push -q -f "$REMOTE" state
echo "state saved"
