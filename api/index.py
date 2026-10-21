
from __future__ import annotations

import os
import uuid
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, ConfigDict

from backend.db import configured, insert, select, upsert, delete
from backend.engine import RAG, answer, reload_knowledge
from backend.production_rag import (
    ai_enabled,
    vector_search,
    generate_grounded_answer,
    generate_general_answer,
)


app = FastAPI(title="NutriAI API", version="3.1.0")

origins = [
    item.strip()
    for item in os.getenv("ALLOWED_ORIGINS", "").split(",")
    if item.strip()
]

if not origins:
    origins = (
        ["*"]
        if os.getenv("APP_ENV", "development") != "production"
        else []
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "apikey"],
)

MAX_MESSAGE_CHARS = int(os.getenv("MAX_MESSAGE_CHARS", "6000"))
ALLOW_GUEST_MODE = os.getenv("ALLOW_GUEST_MODE", "true").lower() == "true"


# =========================================================
# REQUEST MODELS
# =========================================================

class ChatRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    message: str = Field(
        min_length=1,
        max_length=MAX_MESSAGE_CHARS,
    )
    conversation_id: str | None = None
    profile: dict[str, Any] = Field(default_factory=dict)
    history: list[dict[str, str]] = Field(default_factory=list)


class ConversationCreate(BaseModel):
    title: str = Field(
        default="Cuộc trò chuyện mới",
        min_length=1,
        max_length=180,
    )


class ProfilePayload(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    age: int | None = Field(default=None, ge=1, le=120)
    gender: str | None = None
    height: float | None = Field(default=None, gt=0, le=260)
    weight: float | None = Field(default=None, gt=0, le=500)
    goal: str | None = Field(default=None, max_length=500)
    activity_level: str | None = None


# =========================================================
# AUTHENTICATION AND HELPERS
# =========================================================

async def current_user(authorization: str | None):
    """
    Xác minh access token với Supabase Auth.
    Không tin user_id do trình duyệt tự gửi lên.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        if ALLOW_GUEST_MODE:
            return None

        raise HTTPException(
            status_code=401,
            detail="Vui lòng đăng nhập để tiếp tục.",
        )

    url = os.getenv("SUPABASE_URL", "").rstrip("/")
    anon_key = os.getenv("SUPABASE_ANON_KEY", "")

    if not url or not anon_key:
        raise HTTPException(
            status_code=503,
            detail="Chưa cấu hình Supabase Auth.",
        )

    try:
        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.get(
                f"{url}/auth/v1/user",
                headers={
                    "apikey": anon_key,
                    "Authorization": authorization,
                },
            )

        if response.status_code != 200:
            raise HTTPException(
                status_code=401,
                detail="Phiên đăng nhập không hợp lệ hoặc đã hết hạn.",
            )

        return response.json()

    except HTTPException:
        raise
    except Exception as exc:
        print("Supabase Auth error:", str(exc)[:250])
        raise HTTPException(
            status_code=503,
            detail="Không thể xác minh phiên đăng nhập.",
        )


def require_db():
    if not configured():
        raise HTTPException(
            status_code=503,
            detail="Supabase chưa được cấu hình.",
        )


def clean_history(items: list[dict[str, str]]) -> list[dict[str, str]]:
    """Chuẩn hóa lịch sử hội thoại, giới hạn số lượng và độ dài."""
    cleaned = []

    for item in items[-12:]:
        role = item.get("role", "")
        content = item.get("content", "")

        if role not in {"user", "assistant"}:
            continue

        if not isinstance(content, str) or not content.strip():
            continue

        cleaned.append({
            "role": role,
            "content": content.strip()[:3000],
        })

    return cleaned


def format_sources(contexts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Chuẩn hóa nguồn kiến thức từ các kiểu kết quả truy xuất."""
    sources = []

    for item in contexts:
        metadata = item.get("metadata") or {}

        if not isinstance(metadata, dict):
            metadata = {}

        sources.append({
            "title": (
                item.get("title")
                or metadata.get("title")
                or "Tài liệu kiến thức"
            ),
            "source": (
                item.get("source")
                or metadata.get("source")
                or "knowledge.txt"
            ),
            "score": item.get(
                "similarity",
                item.get("score"),
            ),
        })

    return sources


# =========================================================
# BASIC ENDPOINTS
# =========================================================

@app.get("/")
def root():
    return {
        "product": "NutriAI",
        "message": "API is running",
    }


@app.get("/api/health")
def health():
    database_ready = configured()
    ai_ready = ai_enabled()

    return {
        "status": "ok",
        "product": "NutriAI",
        "database": database_ready,
        "ai_generation": ai_ready,
        "rag_mode": (
            "Supabase pgvector + LLM"
            if database_ready and ai_ready
            else "TXT lexical retrieval"
        ),
        "knowledge": RAG.stats(),
    }


@app.get("/api/knowledge")
def knowledge():
    return RAG.stats()


# =========================================================
# CHAT ENDPOINT
# =========================================================

@app.post("/api/chat")
async def chat(
    payload: ChatRequest,
    authorization: str | None = Header(default=None),
):
    user = await current_user(authorization)
    message = payload.message.strip()

    if not message:
        raise HTTPException(
            status_code=400,
            detail="Tin nhắn trống.",
        )

    normalized = " ".join(
        message.lower().strip(" .,!?:;").split()
    )

    greetings = {
        "chào",
        "chào bạn",
        "xin chào",
        "hello",
        "hi",
        "hey",
        "alo",
        "bạn khỏe không",
    }

    contexts: list[dict[str, Any]] = []
    response_text: str | None = None
    history: list[dict[str, str]] = []

    # -----------------------------------------------------
    # 1. LOAD CONVERSATION HISTORY
    # -----------------------------------------------------

    if user and configured() and payload.conversation_id:
        try:
            owned = select(
                "conversations",
                {
                    "select": "id",
                    "id": f"eq.{payload.conversation_id}",
                    "user_id": f"eq.{user['id']}",
                    "limit": "1",
                },
            )

            if not owned:
                raise HTTPException(
                    status_code=404,
                    detail="Không tìm thấy cuộc trò chuyện.",
                )

            previous_messages = select(
                "messages",
                {
                    "select": "role,content",
                    "conversation_id": f"eq.{payload.conversation_id}",
                    "user_id": f"eq.{user['id']}",
                    "order": "created_at.desc",
                    "limit": "12",
                },
            ) or []

            history = clean_history([
                {
                    "role": item.get("role", ""),
                    "content": item.get("content", ""),
                }
                for item in reversed(previous_messages)
            ])

        except HTTPException:
            raise
        except Exception as exc:
            print("Chat history warning:", str(exc)[:250])

    else:
        # Chế độ khách: lịch sử cần được frontend gửi kèm.
        history = clean_history(payload.history)

    # -----------------------------------------------------
    # 2. HANDLE GREETINGS
    # -----------------------------------------------------

    if normalized in greetings:
        response_text = (
            "Xin chào! 👋 Mình là NutriAI. "
            "Mình có thể hỗ trợ bạn về dinh dưỡng, thực phẩm, "
            "tập luyện và lối sống lành mạnh. "
            "Bạn muốn tìm hiểu điều gì hôm nay?"
        )

    else:
        # -------------------------------------------------
        # 3. RETRIEVE RELEVANT KNOWLEDGE
        # -------------------------------------------------

        try:
            contexts = vector_search(message, 5) or []
        except Exception as exc:
            print("Vector retrieval fallback:", str(exc)[:250])
            contexts = []

        # -------------------------------------------------
        # 4. GENERATE GROUNDED ANSWER
        # -------------------------------------------------

        if contexts and ai_enabled():
            try:
                response_text = generate_grounded_answer(
                    question=message,
                    contexts=contexts,
                    profile=payload.profile,
                    history=history,
                )
            except Exception as exc:
                print("Grounded answer fallback:", str(exc)[:250])
                response_text = None

        # -------------------------------------------------
        # 5. FALL BACK TO ENGINE
        # -------------------------------------------------

        if not response_text:
            try:
                response_text, engine_contexts = answer(
                    message,
                    payload.profile,
                )

                if not contexts:
                    contexts = engine_contexts or []

            except Exception as exc:
                print("Chat engine error:", str(exc)[:250])
                raise HTTPException(
                    status_code=500,
                    detail="NutriAI chưa thể xử lý câu hỏi lúc này.",
                )

        # -------------------------------------------------
        # 6. GENERAL AI ANSWER WHEN NO CONTEXT IS FOUND
        # -------------------------------------------------

        if not contexts and ai_enabled():
            try:
                general_text = generate_general_answer(
                    question=message,
                    profile=payload.profile,
                    history=history,
                )

                if general_text:
                    response_text = general_text

            except Exception as exc:
                print("General AI fallback:", str(exc)[:250])

    if not response_text:
        response_text = (
            "Mình chưa tìm được thông tin đủ phù hợp để trả lời "
            "chính xác. Bạn có thể diễn đạt câu hỏi cụ thể hơn không?"
        )

    # -----------------------------------------------------
    # 7. SAVE MESSAGES TO SUPABASE
    # -----------------------------------------------------

    if user and configured():
        uid = user.get("id")

        try:
            cid = payload.conversation_id

            if cid:
                owned = select(
                    "conversations",
                    {
                        "select": "id",
                        "id": f"eq.{cid}",
                        "user_id": f"eq.{uid}",
                        "limit": "1",
                    },
                )

                if not owned:
                    raise HTTPException(
                        status_code=404,
                        detail="Không tìm thấy cuộc trò chuyện.",
                    )

            else:
                rows = insert(
                    "conversations",
                    {
                        "user_id": uid,
                        "title": message[:80],
                    },
                ) or []

                cid = rows[0].get("id") if rows else None

            if cid:
                insert(
                    "messages",
                    {
                        "conversation_id": cid,
                        "user_id": uid,
                        "role": "user",
                        "content": message,
                    },
                )

                insert(
                    "messages",
                    {
                        "conversation_id": cid,
                        "user_id": uid,
                        "role": "assistant",
                        "content": response_text,
                    },
                )

        except HTTPException:
            raise
        except Exception as exc:
            print("Chat persistence warning:", str(exc)[:250])

    # -----------------------------------------------------
    # 8. RETURN RESPONSE
    # -----------------------------------------------------

    return {
        "answer": response_text,
        "sources": format_sources(contexts),
        "model": (
            "LLM + RAG"
            if ai_enabled() and contexts
            else "LLM"
            if ai_enabled()
            else "RAG TXT local"
        ),
    }


# =========================================================
# CONVERSATION ENDPOINTS
# =========================================================

@app.get("/api/conversations")
async def list_conversations(
    authorization: str | None = Header(default=None),
    limit: int = Query(default=30, ge=1, le=100),
):
    user = await current_user(authorization)

    if not user:
        return {
            "items": [],
            "guest_mode": True,
        }

    require_db()

    rows = select(
        "conversations",
        {
            "select": "id,title,created_at",
            "user_id": f"eq.{user['id']}",
            "order": "created_at.desc",
            "limit": str(limit),
        },
    )

    return {"items": rows or []}


@app.post("/api/conversations")
async def create_conversation(
    payload: ConversationCreate,
    authorization: str | None = Header(default=None),
):
    user = await current_user(authorization)

    if not user:
        return {
            "id": str(uuid.uuid4()),
            "guest_mode": True,
        }

    require_db()

    rows = insert(
        "conversations",
        {
            "user_id": user["id"],
            "title": payload.title,
        },
    ) or []

    if not rows:
        raise HTTPException(
            status_code=500,
            detail="Không tạo được cuộc trò chuyện.",
        )

    return rows[0]


@app.get("/api/conversations/{conversation_id}/messages")
async def get_messages(
    conversation_id: str,
    authorization: str | None = Header(default=None),
):
    user = await current_user(authorization)

    if not user:
        return {
            "items": [],
            "guest_mode": True,
        }

    require_db()

    owned = select(
        "conversations",
        {
            "select": "id",
            "id": f"eq.{conversation_id}",
            "user_id": f"eq.{user['id']}",
            "limit": "1",
        },
    )

    if not owned:
        raise HTTPException(
            status_code=404,
            detail="Không tìm thấy cuộc trò chuyện.",
        )

    rows = select(
        "messages",
        {
            "select": "id,role,content,created_at",
            "conversation_id": f"eq.{conversation_id}",
            "user_id": f"eq.{user['id']}",
            "order": "created_at.asc",
            "limit": "500",
        },
    )

    return {"items": rows or []}


@app.delete("/api/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    authorization: str | None = Header(default=None),
):
    user = await current_user(authorization)

    if not user:
        raise HTTPException(
            status_code=401,
            detail="Vui lòng đăng nhập.",
        )

    require_db()

    rows = delete(
        "conversations",
        {
            "id": f"eq.{conversation_id}",
            "user_id": f"eq.{user['id']}",
        },
    )

    return {
        "ok": True,
        "deleted": len(rows or []),
    }


# =========================================================
# PROFILE ENDPOINTS
# =========================================================

@app.get("/api/profile")
async def get_profile(
    authorization: str | None = Header(default=None),
):
    user = await current_user(authorization)

    if not user:
        return {
            "profile": None,
            "guest_mode": True,
        }

    require_db()

    rows = select(
        "profiles",
        {
            "select": "*",
            "user_id": f"eq.{user['id']}",
            "limit": "1",
        },
    )

    return {
        "profile": (rows or [None])[0],
    }


@app.put("/api/profile")
async def save_profile(
    payload: ProfilePayload,
    authorization: str | None = Header(default=None),
):
    user = await current_user(authorization)

    if not user:
        raise HTTPException(
            status_code=401,
            detail="Đăng nhập để đồng bộ hồ sơ lên cloud.",
        )

    require_db()

    row = payload.model_dump()
    row["user_id"] = user["id"]

    rows = upsert(
        "profiles",
        row,
        "user_id",
    )

    return {
        "ok": True,
        "profile": (rows or [row])[0],
    }


# =========================================================
# KNOWLEDGE RELOAD
# =========================================================

@app.post("/api/knowledge/reload")
def reload():
    return reload_knowledge()
