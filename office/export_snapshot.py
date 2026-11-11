#!/usr/bin/env python3
"""Emit the intentionally limited, read-only office snapshot as JSON."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import server

data = server.snapshot()
# Guard against accidentally expanding the export into private company records.
for forbidden in ("payload", "description", "result", "history", "thought", "observation", "args", "pending"):
    for rowset in ("agents", "departments", "tasks", "approvals", "runs"):
        for row in data.get(rowset, []):
            if forbidden in row:
                raise SystemExit("رفض التصدير: حقل غير مسموح: " + forbidden)
json.dump(data, sys.stdout, ensure_ascii=False, separators=(",", ":"))
sys.stdout.write("\n")
