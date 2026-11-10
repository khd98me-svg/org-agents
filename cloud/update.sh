#!/usr/bin/env bash
# تحديث كود الشركة على GitHub بدون لمس حالتها (الذاكرة والمهام تبقى كما هي).
# الاستخدام:  GH_TOKEN=التوكن GH_USER=اسمك bash cloud/update.sh
set -euo pipefail
RL="${RL_DIR:-$HOME/rl-agent}"
REPO_NAME="${REPO_NAME:-org-agents}"
: "${GH_TOKEN:?ضع GH_TOKEN}" ; : "${GH_USER:?ضع GH_USER}"
GIT_BASE="${GIT_BASE:-https://x-access-token:${GH_TOKEN}@github.com}"
GHX="${GHX:-gh}"
say() { echo "▶ $*"; }
W=$(mktemp -d); cd "$W"
git init -q && git checkout -q -b main
for f in org_bot.py orgx.py ceo_brain.py ceo_advisor.py exper.py agent_run.py tools.py ext.py tools_x.py; do cp "$RL/$f" . ; done
mkdir -p cloud .github/workflows
cp "$RL"/cloud/restore.sh "$RL"/cloud/save.sh "$RL"/cloud/secret.sh "$RL"/cloud/update.sh cloud/
[ -d "$RL/rl" ] && cp -r "$RL/rl" . || true
cp "$RL"/cloud/.github/workflows/org.yml .github/workflows/org.yml
printf '__pycache__/\n*.db\nworkspace/\n.env*\nowner.json\n' > .gitignore
git add -A
git -c user.name=org-bot -c user.email=org-bot@users.noreply.github.com commit -q -m "update code"
say "رفع الكود المحدّث (الحالة ما تتأثر)"
git push -q -f "$GIT_BASE/$GH_USER/$REPO_NAME.git" main
say "تشغيل دورة الآن"
GH_TOKEN="$GH_TOKEN" $GHX workflow run org.yml --repo "$GH_USER/$REPO_NAME" >/dev/null 2>&1 || echo "(شغّلها يدوياً من تبويب Actions: Run workflow)"
echo "✅ تم. أرسل /runs للبوت بعد دقيقة."
