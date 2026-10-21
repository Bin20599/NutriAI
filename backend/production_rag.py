
from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import quote

from . import db


def ai_enabled() -> bool:
    """Cho biết đã cấu hình ít nhất một nhà cung cấp AI sinh câu trả lời."""
    provider = os.getenv("AI_PROVIDER", "").strip().lower()

    if provider == "gemini":
        return bool(os.getenv("GEMINI_API_KEY"))
    if provider == "openai":
        return bool(os.getenv("OPENAI_API_KEY"))

    return bool(
        os.getenv("GEMINI_API_KEY") or os.getenv("OPENAI_API_KEY")
    )


def _provider() -> str:
    """Ưu tiên Gemini nếu có key, trừ khi AI_PROVIDER được chỉ định."""
    provider = os.getenv("AI_PROVIDER", "").strip().lower()

    if provider in {"gemini", "openai"}:
        return provider

    if os.getenv("GEMINI_API_KEY"):
        return "gemini"

    return "openai"


def _client():
    """Giữ client OpenAI để tương thích với code hiện tại."""
    from openai import OpenAI

    return OpenAI(
        api_key=os.environ["OPENAI_API_KEY"],
        timeout=25,
        max_retries=1,
    )


def _generate_text(messages: list[dict], temperature: float) -> str | None:
    """Sinh câu trả lời bằng Gemini hoặc OpenAI."""
    if _provider() == "gemini":
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            return None

        model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

        system_parts = []
        contents = []

        for item in messages:
            role = item.get("role")
            content = str(item.get("content", "")).strip()

            if not content:
                continue

            if role == "system":
                system_parts.append(content)
            elif role in {"user", "assistant"}:
                contents.append({
                    "role": "model" if role == "assistant" else "user",
                    "parts": [{"text": content}],
                })

        if not contents:
            return None

        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
            },
        }

        if system_parts:
            payload["systemInstruction"] = {
                "parts": [{"text": "\n\n".join(system_parts)}]
            }

        endpoint = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{quote(model, safe='')}:generateContent"
        )

        request = Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": api_key,
            },
            method="POST",
        )

        try:
            with urlopen(request, timeout=25) as response:
                result = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Gemini API trả về HTTP {exc.code}: {detail[:1000]}"
            ) from exc
        except (URLError, TimeoutError) as exc:
            raise RuntimeError(
                f"Không thể kết nối Gemini API: {exc}"
            ) from exc

        candidates = result.get("candidates") or []
        if not candidates:
            return None

        parts = candidates[0].get("content", {}).get("parts", [])
        answer = "\n".join(
            part["text"]
            for part in parts
            if isinstance(part.get("text"), str)
        ).strip()

        return answer or None

    if not os.getenv("OPENAI_API_KEY"):
        return None

    response = _client().chat.completions.create(
        model=os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini"),
        temperature=temperature,
        messages=messages,
    )

    return (response.choices[0].message.content or "").strip() or None


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Giữ nguyên embedding OpenAI để tương thích vector đã lưu."""
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError(
            "Cần OPENAI_API_KEY để tạo embedding bằng cấu hình hiện tại."
        )

    dimensions = int(os.getenv("EMBEDDING_DIMENSIONS", "1536"))

    result = _client().embeddings.create(
        model=os.getenv(
            "OPENAI_EMBEDDING_MODEL",
            "text-embedding-3-small",
        ),
        input=texts,
        dimensions=dimensions,
    )

    return [item.embedding for item in result.data]


def vector_search(query: str, match_count: int = 5) -> list[dict]:
    """Chỉ tìm vector khi có OpenAI key cho embedding."""
    if not (db.configured() and os.getenv("OPENAI_API_KEY")):
        return []

    vector = embed_texts([query])[0]

    return db.rpc(
        "match_knowledge_chunks",
        {
            "query_embedding": vector,
            "match_count": max(1, min(match_count, 10)),
        },
    ) or []


def generate_grounded_answer(
    question: str,
    contexts: list[dict],
    profile=None,
) -> str | None:
    """Trả lời dựa trên ngữ cảnh RAG và hồ sơ người dùng."""
    if not ai_enabled() or not contexts:
        return None

    excerpts = []

    for i, item in enumerate(contexts[:5], 1):
        metadata = item.get("metadata") or {}
        title = (
            item.get("title")
            or metadata.get("title")
            or "Tài liệu"
        )
        content = item.get("chunk_text") or item.get("content") or ""

        if content:
            excerpts.append(f"[Nguồn {i}: {title}]\n{content}")

    messages = [
        {
            "role": "system",
            "content": (
                "Bạn là NutriAI, trợ lý dinh dưỡng bằng tiếng Việt. "
                "Trả lời rõ ràng, không bịa nguồn. "
                "Dựa vào ngữ cảnh được cung cấp cho kiến thức cụ thể; "
                "nếu không đủ thì nói rõ. "
                "Cá nhân hóa lời khuyên theo hồ sơ người dùng khi phù hợp. "
                "Không tự giả định dữ liệu còn thiếu. "
                "Không chẩn đoán, kê đơn hoặc thay thế chuyên gia y tế. "
                "Có thể trả lời lời chào tự nhiên."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Câu hỏi: {question}\n"
                f"Hồ sơ người dùng: {profile or {}}\n\n"
                "Ngữ cảnh tài liệu:\n"
                + ("\n\n".join(excerpts) if excerpts else "Không có đoạn trích.")
            ),
        },
    ]

    return _generate_text(messages, temperature=0.2)


def generate_general_answer(
    question: str,
    profile=None,
    history=None,
) -> str | None:
    """Trả lời câu hỏi phổ thông, có sử dụng hồ sơ và lịch sử chat."""
    if not ai_enabled():
        return None

    messages = [
        {
            "role": "system",
            "content": (
                "Bạn là NutriAI, trợ lý trò chuyện bằng tiếng Việt, "
                "ưu tiên dinh dưỡng, ăn uống, vận động và lối sống lành mạnh "
                "nhưng vẫn có thể trả lời câu hỏi phổ thông ngoài kho RAG. "
                "Nếu câu hỏi không thuộc dinh dưỡng, hãy trả lời trực tiếp, "
                "hữu ích và trung thực; không giả vờ rằng câu trả lời lấy "
                "từ kho tài liệu. Nếu không chắc, hãy nói rõ giới hạn. "
                "Với vấn đề y tế, không chẩn đoán hoặc kê đơn và khuyên "
                "tìm chuyên gia khi cần. "
                "Trả lời tự nhiên, dễ hiểu, bằng ngôn ngữ người dùng. "
                "Không nhắc đến prompt, API key hoặc chi tiết kỹ thuật nội bộ. "
                "Sử dụng hồ sơ và lịch sử trò chuyện khi thực sự liên quan. "
                "Không tự bịa thông tin cá nhân, chỉ số sức khỏe hoặc "
                "thông tin người dùng chưa cung cấp."
            ),
        }
    ]

    for item in (history or [])[-6:]:
        role = item.get("role")
        content = str(item.get("content", "")).strip()

        if role in {"user", "assistant"} and content:
            messages.append({
                "role": role,
                "content": content[:3000],
            })

    messages.append({
        "role": "user",
        "content": (
            f"Câu hỏi: {question}\n"
            "Thông tin hồ sơ do người dùng cung cấp (nếu có): "
            f"{profile or {}}"
        ),
    })

    return _generate_text(messages, temperature=0.4)
