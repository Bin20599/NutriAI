from __future__ import annotations
import os, uuid
from typing import Any
import httpx
from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, ConfigDict

from backend.db import configured, insert, select, upsert, delete
from backend.engine import RAG, answer, reload_knowledge
from backend.production_rag import ai_enabled, vector_search, generate_grounded_answer

app = FastAPI(title="NutriAI API", version="3.0.0")
origins = [x.strip() for x in os.getenv("ALLOWED_ORIGINS", "").split(",") if x.strip()]
if not origins:
    origins = ["*"] if os.getenv("APP_ENV", "development") != "production" else []
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=False,
                   allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
                   allow_headers=["Authorization", "Content-Type", "apikey"])

MAX_MESSAGE_CHARS = int(os.getenv("MAX_MESSAGE_CHARS", "6000"))
ALLOW_GUEST_MODE = os.getenv("ALLOW_GUEST_MODE", "true").lower() == "true"

class ChatRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)
    conversation_id: str | None = None
    profile: dict[str, Any] = Field(default_factory=dict)

class ConversationCreate(BaseModel):
    title: str = Field(default="Cuộc trò chuyện mới", min_length=1, max_length=180)

class ProfilePayload(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    age: int | None = Field(default=None, ge=1, le=120)
    gender: str | None = None
    height: float | None = Field(default=None, gt=0, le=260)
    weight: float | None = Field(default=None, gt=0, le=500)
    goal: str | None = Field(default=None, max_length=500)
    activity_level: str | None = None

async def current_user(authorization: str | None):
    # Never trust a user_id sent by the browser; verify the access token with Supabase Auth.
    if not authorization or not authorization.lower().startswith("bearer "):
        if ALLOW_GUEST_MODE:
            return None
        raise HTTPException(401, "Vui lòng đăng nhập để tiếp tục.")
    url = os.getenv("SUPABASE_URL", "").rstrip("/")
    anon = os.getenv("SUPABASE_ANON_KEY", "")
    if not url or not anon:
        raise HTTPException(503, "Chưa cấu hình Supabase Auth.")
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(f"{url}/auth/v1/user",
                headers={"apikey": anon, "Authorization": authorization})
        if r.status_code != 200:
            raise HTTPException(401, "Phiên đăng nhập không hợp lệ hoặc đã hết hạn.")
        return r.json()
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, "Không thể xác minh phiên đăng nhập.")

def require_db():
    if not configured():
        raise HTTPException(503, "Supabase chưa được cấu hình.")

@app.get("/")
def root():
    return {"product": "NutriAI", "message": "API is running"}

@app.get("/api/health")
def health():
    return {"status": "ok", "product": "NutriAI", "database": configured(),
            "ai_generation": ai_enabled(),
            "rag_mode": "Supabase pgvector + LLM" if configured() and ai_enabled() else "TXT lexical retrieval",
            "knowledge": RAG.stats()}

@app.get("/api/knowledge")
def knowledge():
    return RAG.stats()

@app.post("/api/chat")
async def chat(payload: ChatRequest, authorization: str | None = Header(default=None)):
    user = await current_user(authorization)
    message = payload.message.strip()
    if not message:
        raise HTTPException(400, "Tin nhắn trống.")
    normalized = " ".join(message.lower().strip(" .,!?:;").split())
    greetings = {"chào", "chào bạn", "xin chào", "hello", "hi", "hey", "alo", "bạn khỏe không"}
    contexts = []
    if normalized in greetings:
        response_text = "Xin chào! 👋 Mình là NutriAI. Mình có thể hỗ trợ bạn về dinh dưỡng, thực phẩm, tập luyện và lối sống lành mạnh. Bạn muốn tìm hiểu điều gì hôm nay?"
    else:
        try:
            contexts = vector_search(message, 5)
        except Exception as exc:
            print("Vector retrieval fallback:", str(exc)[:250])
        if contexts:
            response_text = generate_grounded_answer(message, contexts, payload.profile)
        else:
            response_text = None
        if not response_text:
            response_text, contexts = answer(message, payload.profile)
            if ai_enabled() and contexts:
                try:
                    response_text = generate_grounded_answer(message, contexts, payload.profile) or response_text
                except Exception as exc:
                    print("LLM fallback:", str(exc)[:250])
    if user and configured():
        uid = user.get("id")
        try:
            cid = payload.conversation_id
            if cid:
                owned = select("conversations", {"select":"id", "id":f"eq.{cid}",
                                                  "user_id":f"eq.{uid}", "limit":"1"})
                if not owned:
                    raise HTTPException(404, "Không tìm thấy cuộc trò chuyện.")
            else:
                rows = insert("conversations", {"user_id":uid, "title":message[:80]}) or []
                cid = rows[0].get("id") if rows else None
            if cid:
                insert("messages", {"conversation_id":cid,"user_id":uid,"role":"user","content":message})
                insert("messages", {"conversation_id":cid,"user_id":uid,"role":"assistant","content":response_text})
        except HTTPException:
            raise
        except Exception as exc:
            print("Chat persistence warning:", str(exc)[:250])
    sources = [{"title":x.get("title") or x.get("metadata",{}).get("title") or "Tài liệu kiến thức",
                "source":x.get("source") or x.get("metadata",{}).get("source") or "knowledge.txt",
                "score":x.get("similarity", x.get("score"))} for x in contexts]
    return {"answer":response_text, "sources":sources,
            "model":"LLM + RAG" if ai_enabled() and contexts else "RAG TXT local"}

@app.get("/api/conversations")
async def list_conversations(authorization: str | None = Header(default=None),
                             limit: int = Query(default=30, ge=1, le=100)):
    user = await current_user(authorization)
    if not user:
        return {"items":[], "guest_mode":True}
    require_db()
    rows = select("conversations", {"select":"id,title,created_at", "user_id":f"eq.{user['id']}",
                                    "order":"created_at.desc", "limit":str(limit)})
    return {"items":rows or []}

@app.post("/api/conversations")
async def create_conversation(payload: ConversationCreate, authorization: str | None = Header(default=None)):
    user = await current_user(authorization)
    if not user:
        return {"id":str(uuid.uuid4()), "guest_mode":True}
    require_db()
    rows = insert("conversations", {"user_id":user["id"], "title":payload.title}) or []
    if not rows:
        raise HTTPException(500, "Không tạo được cuộc trò chuyện.")
    return rows[0]

@app.get("/api/conversations/{conversation_id}/messages")
async def get_messages(conversation_id: str, authorization: str | None = Header(default=None)):
    user = await current_user(authorization)
    if not user:
        return {"items":[], "guest_mode":True}
    require_db()
    owned = select("conversations", {"select":"id", "id":f"eq.{conversation_id}",
                                     "user_id":f"eq.{user['id']}", "limit":"1"})
    if not owned:
        raise HTTPException(404, "Không tìm thấy cuộc trò chuyện.")
    rows = select("messages", {"select":"id,role,content,created_at",
        "conversation_id":f"eq.{conversation_id}", "user_id":f"eq.{user['id']}",
        "order":"created_at.asc", "limit":"500"})
    return {"items":rows or []}

@app.delete("/api/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str, authorization: str | None = Header(default=None)):
    user = await current_user(authorization)
    if not user:
        raise HTTPException(401, "Vui lòng đăng nhập.")
    require_db()
    rows = delete("conversations", {"id":f"eq.{conversation_id}", "user_id":f"eq.{user['id']}"})
    return {"ok":True, "deleted":len(rows or [])}

@app.get("/api/profile")
async def get_profile(authorization: str | None = Header(default=None)):
    user = await current_user(authorization)
    if not user:
        return {"profile":None, "guest_mode":True}
    require_db()
    rows = select("profiles", {"select":"*", "user_id":f"eq.{user['id']}", "limit":"1"})
    return {"profile":(rows or [None])[0]}

@app.put("/api/profile")
async def save_profile(payload: ProfilePayload, authorization: str | None = Header(default=None)):
    user = await current_user(authorization)
    if not user:
        raise HTTPException(401, "Đăng nhập để đồng bộ hồ sơ lên cloud.")
    require_db()
    row = payload.model_dump()
    row["user_id"] = user["id"]
    rows = upsert("profiles", row, "user_id")
    return {"ok":True, "profile":(rows or [row])[0]}

@app.post("/api/knowledge/reload")
def reload():
    return reload_knowledge()
