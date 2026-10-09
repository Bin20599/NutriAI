from __future__ import annotations

import json
import os
import urllib.request


def configured() -> bool:
    return bool(os.getenv("SUPABASE_URL") and (os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")))


def insert(table: str, data: dict):
    if not configured():
        return None
    url = os.getenv("SUPABASE_URL", "").rstrip("/") + f"/rest/v1/{table}"
    key = os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY") or ""
    req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"), method="POST")
    req.add_header("apikey", key)
    req.add_header("Authorization", "Bearer " + key)
    req.add_header("Content-Type", "application/json")
    req.add_header("Prefer", "return=representation")
    with urllib.request.urlopen(req, timeout=10) as response:
        raw = response.read().decode("utf-8")
        return json.loads(raw) if raw else None
