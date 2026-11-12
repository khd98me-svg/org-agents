#!/usr/bin/env python3
"""Owner-only, pull-based Termux bridge. No arbitrary shell execution."""
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = "khd98me-svg/org-agents"
ISSUE = 1
OWNER = "khd98me-svg"
POLL_SECONDS = 20
HOME = Path.home().resolve()
STATE = HOME / ".termux-office-bridge-state.json"
ROOTS = {
    "openclawfice": HOME / "openclawfice",
    "rl-agent": HOME / "rl-agent",
    "office-ui-bridge-checkout": HOME / "office-ui-bridge-checkout",
}
BLOCKED_PARTS = {".git", "node_modules", "__pycache__", ".next"}
BLOCKED_NAMES = {".env", ".env.local", ".env.production", "organization.db", "state.tar.enc"}
BLOCKED_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".enc", ".pem", ".key", ".p12", ".pfx"}

def gh(args, *, input_text=None, timeout=30):
    p = subprocess.run(["gh"] + args, input=input_text, text=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    if p.returncode:
        raise RuntimeError(p.stderr.strip() or "gh command failed")
    return p.stdout

def post_result(text):
    body = "[Termux bridge]\n" + text[:5000]
    gh(["api", "-X", "POST", f"repos/{REPO}/issues/{ISSUE}/comments", "-f", "body=" + body], timeout=30)

def state_load():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {"last_comment_id": 0}

def state_save(state):
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(STATE)

def safe_path(value):
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError("invalid_path")
    p = Path(value)
    if p.is_absolute():
        target = p.resolve()
    else:
        if "/" not in value:
            raise ValueError("path_must_include_project")
        root_name, rel = value.split("/", 1)
        if root_name not in ROOTS:
            raise ValueError("project_not_allowed")
        target = (ROOTS[root_name] / rel).resolve()
    if not any(target == root or root in target.parents for root in ROOTS.values()):
        raise ValueError("path_outside_projects")
    if any(part in BLOCKED_PARTS for part in target.parts):
        raise ValueError("protected_directory")
    if target.name in BLOCKED_NAMES or target.suffix.lower() in BLOCKED_SUFFIXES:
        raise ValueError("protected_file")
    if target.name.startswith(".env") or target.name.endswith((".bak", ".backup")):
        raise ValueError("protected_file")
    return target

def git_status():
    out = []
    for name, root in ROOTS.items():
        if not root.is_dir():
            out.append(f"{name}: directory missing")
            continue
        branch = gh(["-C", str(root), "status", "--short", "--branch"], timeout=15).strip()
        out.append(f"--- {name} ---\n{branch}")
    return "\n".join(out)

def run_command(cmd, cwd, timeout=120):
    p = subprocess.run(cmd, cwd=str(cwd), text=True, stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, timeout=timeout)
    return f"exit={p.returncode}\n{p.stdout[-4500:]}"

def execute(command):
    if not isinstance(command, dict):
        raise ValueError("command_must_be_object")
    action = command.get("action")
    if action == "status":
        return git_status()
    if action == "read_file":
        path = safe_path(command.get("path"))
        if not path.is_file():
            raise ValueError("file_not_found")
        if path.stat().st_size > 80000:
            raise ValueError("file_too_large")
        return path.read_text(encoding="utf-8")[:8000]
    if action == "write_file":
        if command.get("confirm") is not True:
            raise ValueError("explicit_confirmation_required")
        path = safe_path(command.get("path"))
        data = command.get("content")
        expected = command.get("expected_sha256")
        if not isinstance(data, str) or len(data.encode("utf-8")) > 250000:
            raise ValueError("invalid_or_large_content")
        exists = path.exists()
        if exists:
            if not path.is_file():
                raise ValueError("target_not_regular_file")
            current = hashlib.sha256(path.read_bytes()).hexdigest()
            if not isinstance(expected, str) or current != expected:
                raise ValueError("file_changed_since_read; refusing_to_overwrite")
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            backup = path.with_name(path.name + ".bridge-backup-" + stamp)
            backup.write_bytes(path.read_bytes())
            os.chmod(backup, 0o600)
        elif expected not in (None, ""):
            raise ValueError("expected_file_missing")
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".bridge-tmp")
        tmp.write_text(data, encoding="utf-8")
        os.chmod(tmp, 0o600)
        tmp.replace(path)
        return f"written: {path}\nsha256: {hashlib.sha256(data.encode('utf-8')).hexdigest()}\nbackup: {backup if exists else 'not needed'}"
    if action == "check":
        name = command.get("name")
        if name == "bridge-tests":
            return run_command([sys.executable, "-m", "unittest", "-v", "test_office_api"], ROOTS["office-ui-bridge-checkout"], 120)
        if name == "openclawfice-build":
            return run_command(["npm", "run", "build"], ROOTS["openclawfice"], 240)
        raise ValueError("check_not_allowlisted")
    raise ValueError("action_not_allowlisted")

def extract_command(body):
    match = re.search(r"```json\s*(\{.*?\})\s*```", body or "", re.S)
    if not match:
        return None
    return json.loads(match.group(1))

def poll_once(state):
    raw = gh(["api", "--paginate", f"repos/{REPO}/issues/{ISSUE}/comments"], timeout=45)
    comments = json.loads(raw or "[]")
    comments.sort(key=lambda x: int(x.get("id", 0)))
    last = int(state.get("last_comment_id", 0))
    for item in comments:
        cid = int(item.get("id", 0))
        if cid <= last:
            continue
        state["last_comment_id"] = cid
        state_save(state)
        user = (item.get("user") or {}).get("login", "")
        if user != OWNER:
            continue
        try:
            command = extract_command(item.get("body", ""))
            if command is None:
                continue
            result = execute(command)
            post_result(f"comment #{cid}\n{result}")
        except Exception as exc:
            try:
                post_result(f"comment #{cid}\nERROR: {type(exc).__name__}: {exc}")
            except Exception as post_exc:
                print("Could not post result:", post_exc, flush=True)
        last = cid

def main():
    if not shutil_which("gh"):
        raise SystemExit("GitHub CLI (gh) is required.")
    auth = gh(["auth", "status"], timeout=15)
    print("Termux bridge connected to GitHub. Owner-only inbox:", f"{REPO}#{ISSUE}", flush=True)
    print("Allowed: status, read_file, write_file (with hash + backup), two named checks. No shell command action.", flush=True)
    print("Stop with Ctrl+C.", flush=True)
    state = state_load()
    while True:
        try:
            poll_once(state)
        except Exception as exc:
            print(f"[poll error] {type(exc).__name__}: {exc}", flush=True)
        time.sleep(POLL_SECONDS)

def shutil_which(name):
    from shutil import which
    return which(name) is not None

if __name__ == "__main__":
    main()
