#!/usr/bin/env python3
"""Start the local office API using the existing OpenClawfice environment file."""
import os
from pathlib import Path

ENV_FILE = Path.home() / "openclawfice" / ".env.local"
DB_FILE = Path.home() / "rl-agent" / "organization.db"


def read_env_value(key):
    if not ENV_FILE.is_file():
        raise SystemExit("Missing ~/openclawfice/.env.local")
    prefix = key + "="
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        if line.startswith(prefix):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def main():
    token = read_env_value("OFFICE_API_TOKEN")
    if len(token) < 24:
        raise SystemExit("OFFICE_API_TOKEN is missing or too short in .env.local")
    if not DB_FILE.is_file():
        raise SystemExit("Missing ~/rl-agent/organization.db")
    os.environ["OFFICE_API_TOKEN"] = token
    os.environ["ORG_DB"] = str(DB_FILE)
    os.environ["OFFICE_API_HOST"] = "127.0.0.1"
    os.environ["OFFICE_API_PORT"] = "8765"

    import office_api
    office_api.main()


if __name__ == "__main__":
    main()
