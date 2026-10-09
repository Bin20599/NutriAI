from __future__ import annotations
import os
import httpx

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY") or ""

def configured() -> bool:
    return bool(SUPABASE_URL and SUPABASE_KEY)

def request(method: str, resource: str, *, params=None, payload=None, prefer=None, rpc=False):
    if not configured():
        raise RuntimeError("Supabase chưa được cấu hình.")
    url = f"{SUPABASE_URL}/rest/v1/{'rpc/' if rpc else ''}{resource}"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    with httpx.Client(timeout=15) as client:
        response = client.request(method, url, headers=headers, params=params, json=payload)
    if response.status_code >= 400:
        raise RuntimeError(f"Supabase HTTP {response.status_code}: {response.text[:500]}")
    if not response.content:
        return None
    try:
        return response.json()
    except ValueError:
        return response.text

def insert(table, data):
    return request("POST", table, payload=data, prefer="return=representation")

def insert_many(table, data):
    return request("POST", table, payload=data, prefer="return=representation")

def upsert(table, data, on_conflict):
    return request("POST", table, params={"on_conflict": on_conflict}, payload=data,
                   prefer="resolution=merge-duplicates,return=representation")

def select(table, params):
    return request("GET", table, params=params)

def update(table, params, payload):
    return request("PATCH", table, params=params, payload=payload, prefer="return=representation")

def delete(table, params):
    return request("DELETE", table, params=params, prefer="return=representation")

def rpc(name, payload):
    return request("POST", name, payload=payload, rpc=True)
