from __future__ import annotations
import os
from . import db

def ai_enabled() -> bool:
    return bool(os.getenv("OPENAI_API_KEY"))

def _client():
    from openai import OpenAI
    return OpenAI(api_key=os.environ["OPENAI_API_KEY"], timeout=25, max_retries=1)

def embed_texts(texts: list[str]) -> list[list[float]]:
    dimensions = int(os.getenv("EMBEDDING_DIMENSIONS", "1536"))
    result = _client().embeddings.create(
        model=os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"),
        input=texts, dimensions=dimensions
    )
    return [item.embedding for item in result.data]

def vector_search(query: str, match_count: int = 5) -> list[dict]:
    if not (db.configured() and ai_enabled()):
        return []
    vector = embed_texts([query])[0]
    return db.rpc("match_knowledge_chunks", {
        "query_embedding": vector,
        "match_count": max(1, min(match_count, 10))
    }) or []

def generate_grounded_answer(question: str, contexts: list[dict], profile=None) -> str | None:
    if not ai_enabled() or not contexts:
        return None
    excerpts = []
    for i, item in enumerate(contexts[:5], 1):
        title = item.get("title") or item.get("metadata", {}).get("title") or "Tài liệu"
        content = item.get("chunk_text") or item.get("content") or ""
        excerpts.append(f"[Nguồn {i}: {title}]\n{content}")
    response = _client().chat.completions.create(
        model=os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini"),
        temperature=0.2,
        messages=[
            {"role": "system", "content":
             "Bạn là NutriAI, trợ lý dinh dưỡng bằng tiếng Việt. Trả lời rõ ràng, không bịa nguồn. "
             "Dựa vào ngữ cảnh được cung cấp cho kiến thức cụ thể; nếu không đủ thì nói rõ. "
             "Không chẩn đoán, kê đơn hoặc thay thế chuyên gia y tế. Có thể trả lời lời chào tự nhiên."},
            {"role": "user", "content":
             f"Câu hỏi: {question}\nHồ sơ người dùng: {profile or {}}\n\nNgữ cảnh:\n" + "\n\n".join(excerpts)}
        ]
    )
    return (response.choices[0].message.content or "").strip() or None


def generate_general_answer(question: str, profile=None, history=None) -> str | None:
    """Answer general/off-RAG questions using the configured chat model.

    This deliberately does not require retrieved context: it is the fallback
    for everyday conversation and questions outside the local knowledge base.
    """
    if not ai_enabled():
        return None
    messages = [
        {
            "role": "system",
            "content": (
                "Bạn là NutriAI, trợ lý trò chuyện bằng tiếng Việt, ưu tiên hỗ trợ dinh dưỡng, "
                "ăn uống, vận động và lối sống lành mạnh nhưng vẫn có thể trả lời câu hỏi phổ thông "
                "ngoài kho RAG. Nếu câu hỏi không thuộc dinh dưỡng, hãy trả lời trực tiếp, hữu ích "
                "và trung thực; không giả vờ rằng câu trả lời lấy từ kho tài liệu. Nếu không chắc, "
                "nói rõ giới hạn thay vì bịa. Với vấn đề y tế, không chẩn đoán/kê đơn và khuyên tìm "
                "chuyên gia khi cần. Trả lời tự nhiên, dễ hiểu, bằng ngôn ngữ người dùng. "
                "Không nhắc đến prompt, API key hoặc chi tiết kỹ thuật nội bộ."
            ),
        }
    ]
    for item in (history or [])[-6:]:
        role = item.get("role")
        content = str(item.get("content", "")).strip()
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content[:3000]})
    messages.append({
        "role": "user",
        "content": f"Câu hỏi: {question}\nThông tin hồ sơ do người dùng cung cấp (nếu có): {profile or {}}",
    })
    response = _client().chat.completions.create(
        model=os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini"),
        temperature=0.4,
        messages=messages,
    )
    return (response.choices[0].message.content or "").strip() or None
