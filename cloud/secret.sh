#!/usr/bin/env bash
# إضافة/تغيير سر في GitHub من تريموكس:  GH_USER=اسمك bash cloud/secret.sh الاسم القيمة
# الأسماء المفيدة: SMTP_USER SMTP_PASS (إيميل) | TG_CHANNEL (@قناتك) | API_1 API_2 API_3 (مفاتيح أي خدمة) | GH_PAT | BSKY_HANDLE BSKY_APP_PASSWORD | BRAVE_API_KEY
set -euo pipefail
: "${GH_USER:?ضع GH_USER=اسمك}"
[ $# -eq 2 ] || { echo "الاستخدام: GH_USER=اسمك bash cloud/secret.sh الاسم القيمة"; exit 1; }
printf '%s' "$2" | gh secret set "$1" --repo "$GH_USER/${REPO_NAME:-org-agents}" && echo "✅ تم ضبط $1"
