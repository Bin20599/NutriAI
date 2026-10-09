from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from backend.db import configured, insert
from backend.engine import RAG, answer

app = FastAPI(title="NutriAI API", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    user_id: str | None = None
    conversation_id: str | None = None
    profile: dict = Field(default_factory=dict)


class ConversationRequest(BaseModel):
    user_id: str | None = None
    title: str = "Cuộc trò chuyện mới"


@app.get("/api/health")
def health():
    return {"status": "ok", "product": "NutriAI", "database": configured(), "ai": "RAG TXT local", "knowledge": RAG.stats()}


@app.get("/api/knowledge")
def knowledge():
    return RAG.stats()


@app.post("/api/chat")
def chat(payload: ChatRequest):
    text, sources = answer(payload.message, payload.profile)
    if payload.user_id and payload.conversation_id and configured():
        try:
            insert("messages", {"conversation_id": payload.conversation_id, "user_id": payload.user_id, "role": "user", "content": payload.message})
            insert("messages", {"conversation_id": payload.conversation_id, "user_id": payload.user_id, "role": "assistant", "content": text})
        except Exception as exc:
            print("DB warning:", exc)
    return {"answer": text, "sources": sources, "model": "RAG TXT local"}


@app.post("/api/conversations")
def conversation(payload: ConversationRequest):
    import uuid
    uid = payload.user_id or str(uuid.uuid4())
    if configured():
        try:
            rows = insert("conversations", {"user_id": uid, "title": payload.title}) or []
            cid = rows[0].get("id") if rows else str(uuid.uuid4())
        except Exception as exc:
            print("DB warning:", exc)
            cid = str(uuid.uuid4())
    else:
        cid = str(uuid.uuid4())
    return {"id": cid, "user_id": uid}


@app.post("/api/profile")
def profile(payload: dict):
    if configured():
        try:
            insert("profiles", payload)
        except Exception as exc:
            print("DB warning:", exc)
    return {"ok": True, "database": configured()}
