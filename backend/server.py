from __future__ import annotations

import json
import os
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .db import configured, insert
from .engine import answer, reload_knowledge, RAG

ROOT = Path(__file__).resolve().parents[1]
FRONT = ROOT / "public"


class Handler(BaseHTTPRequestHandler):
    server_version = "NutriAI-Demo/2.0"

    def _send(self, code: int, data, content_type: str = "application/json; charset=utf-8"):
        body = data.encode("utf-8") if isinstance(data, str) else json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self._send(204, "")

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            return self._send(200, {
                "status": "ok",
                "product": "NutriAI",
                "database": configured(),
                "ai": "RAG TXT local",
                "knowledge": RAG.stats(),
            })
        if path == "/api/knowledge":
            return self._send(200, RAG.stats())
        if path == "/":
            return self._file("index.html")
        if path in {"/app.js", "/styles.css"}:
            return self._file(path.lstrip("/"))
        self._send(404, {"detail": "Not found"})

    def _file(self, name: str):
        file_path = FRONT / name
        if not file_path.exists() or not file_path.is_file():
            return self._send(404, {"detail": "File not found"})
        if file_path.suffix == ".html":
            content_type = "text/html; charset=utf-8"
        elif file_path.suffix == ".css":
            content_type = "text/css; charset=utf-8"
        else:
            content_type = "application/javascript; charset=utf-8"
        self._send(200, file_path.read_text(encoding="utf-8"), content_type)

    def _json(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) or b"{}"
        return json.loads(raw.decode("utf-8"))

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            if path == "/api/chat":
                data = self._json()
                message = str(data.get("message", "")).strip()
                if not message:
                    return self._send(400, {"detail": "Tin nhắn trống"})
                result, sources = answer(message, data.get("profile") or {})
                uid = data.get("user_id")
                cid = data.get("conversation_id")
                if uid and cid and configured():
                    try:
                        insert("messages", {"conversation_id": cid, "user_id": uid, "role": "user", "content": message})
                        insert("messages", {"conversation_id": cid, "user_id": uid, "role": "assistant", "content": result})
                    except Exception as exc:
                        print("DB warning:", exc)
                return self._send(200, {"answer": result, "sources": sources, "model": "RAG TXT local"})

            if path == "/api/profile":
                data = self._json()
                if configured():
                    try:
                        insert("profiles", data)
                    except Exception as exc:
                        print("DB warning:", exc)
                return self._send(200, {"ok": True, "database": configured()})

            if path == "/api/conversations":
                data = self._json()
                uid = data.get("user_id") or str(uuid.uuid4())
                title = data.get("title", "Cuộc trò chuyện mới")
                if configured():
                    try:
                        rows = insert("conversations", {"user_id": uid, "title": title}) or []
                        cid = rows[0].get("id") if rows else str(uuid.uuid4())
                    except Exception as exc:
                        print("DB warning:", exc)
                        cid = str(uuid.uuid4())
                else:
                    cid = str(uuid.uuid4())
                return self._send(200, {"id": cid, "user_id": uid})

            if path == "/api/knowledge/reload":
                return self._send(200, reload_knowledge())

            return self._send(404, {"detail": "Not found"})
        except Exception as exc:
            return self._send(500, {"detail": str(exc)})


if __name__ == "__main__":
    os.chdir(ROOT)
    print("NutriAI Demo: http://127.0.0.1:8000")
    print("RAG:", RAG.stats())
    print("Supabase:", "đã cấu hình" if configured() else "chưa cấu hình")
    ThreadingHTTPServer(("127.0.0.1", 8000), Handler).serve_forever()
