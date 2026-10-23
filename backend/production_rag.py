from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import quote

from . import db


def ai_enabled() -> bool:
    """Kiểm tra cấu hình nhà cung cấp AI."""
    provider = os.getenv("AI_PROVIDER", "").strip().lower()

    if provider == "gemini":
        return bool(os.getenv("GEMINI_API_KEY"))

    if provider == "openai":
        return bool(os.getenv("OPENAI_API_KEY"))

    return bool(
        os.getenv("GEMINI_API_KEY")
        or os.getenv("OPENAI_API_KEY")
    )


def _provider() -> str:
    """Chọn nhà cung cấp AI theo cấu hình."""
    provider = os.getenv("AI_PROVIDER", "").strip().lower()

    if provider in {"gemini", "openai"}:
        return provider

    if os.getenv("GEMINI_API_KEY"):
        return "gemini"

    return "openai"


def _client():
    """Khởi tạo client OpenAI khi cần."""
    from openai import OpenAI

    return OpenAI(
        api_key=os.environ["OPENAI_API_KEY"],
        timeout=25,
        max_retries=1,
    )


def _generate_text(
    messages: list[dict],
    temperature: float = 0.4,
) -> str | None:
    """Sinh câu trả lời bằng Gemini hoặc OpenAI."""
    if _provider() == "gemini":
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            return None

        model = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")

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

        # Gemini yêu cầu các lượt user/model luân phiên.
        # Gộp các lượt liên tiếp cùng vai trò để tránh lỗi API.
        normalized_contents = []

        for item in contents:
            if (
                normalized_contents
                and normalized_contents[-1]["role"] == item["role"]
            ):
                normalized_contents[-1]["parts"].extend(
                    item["parts"]
                )
            else:
                normalized_contents.append(item)

        # Nếu lịch sử kết thúc bằng assistant, không gửi lượt đó
        # như lượt cuối cùng của yêu cầu mới.
        while (
            normalized_contents
            and normalized_contents[-1]["role"] != "user"
        ):
            normalized_contents.pop()

        if not normalized_contents:
            return None

        payload = {
            "contents": normalized_contents,
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
                result = json.loads(
                    response.read().decode("utf-8")
                )
        except HTTPError as exc:
            detail = exc.read().decode(
                "utf-8",
                errors="replace",
            )
            raise RuntimeError(
                f"Gemini API HTTP {exc.code}: {detail[:1000]}"
            ) from exc
        except (URLError, TimeoutError) as exc:
            raise RuntimeError(
                f"Không thể kết nối Gemini API: {exc}"
            ) from exc

        candidates = result.get("candidates") or []
        if not candidates:
            return None

        candidate = candidates[0]
        parts = candidate.get("content", {}).get("parts", [])

        answer = "\n".join(
            part["text"]
            for part in parts
            if isinstance(part.get("text"), str)
        ).strip()

        if not answer:
            print(
                "Gemini returned no text. Finish reason:",
                candidate.get("finishReason", "UNKNOWN"),
            )
            return None

        return answer

    if not os.getenv("OPENAI_API_KEY"):
        return None

    response = _client().chat.completions.create(
        model=os.getenv(
            "OPENAI_CHAT_MODEL",
            "gpt-4o-mini",
        ),
        temperature=temperature,
        messages=messages,
    )

    return (
        response.choices[0].message.content or ""
    ).strip() or None


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Giữ embedding OpenAI để tương thích vector đã lưu."""
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError(
            "Cần OPENAI_API_KEY để tạo embedding hiện tại."
        )

    dimensions = int(
        os.getenv("EMBEDDING_DIMENSIONS", "1536")
    )

    result = _client().embeddings.create(
        model=os.getenv(
            "OPENAI_EMBEDDING_MODEL",
            "text-embedding-3-small",
        ),
        input=texts,
        dimensions=dimensions,
    )

    return [item.embedding for item in result.data]


def vector_search(
    query: str,
    match_count: int = 5,
) -> list[dict]:
    """Tìm kiếm vector khi có cấu hình embedding."""
    if not (
        db.configured()
        and os.getenv("OPENAI_API_KEY")
    ):
        return []

    vector = embed_texts([query])[0]

    return db.rpc(
        "match_knowledge_chunks",
        {
            "query_embedding": vector,
            "match_count": max(1, min(match_count, 10)),
        },
    ) or []


def _format_contexts(contexts: list[dict]) -> str:
    """Chuẩn hóa đoạn kiến thức trước khi gửi Gemini."""
    excerpts = []

    for index, item in enumerate(contexts[:3], 1):
        metadata = item.get("metadata") or {}

        title = (
            item.get("title")
            or metadata.get("title")
            or "Tài liệu"
        )

        content = (
            item.get("chunk_text")
            or item.get("content")
            or ""
        ).strip()

        if content:
            excerpts.append(
                f"[Nguồn {index}: {title}]\n{content[:5000]}"
            )

    return "\n\n".join(excerpts)


def generate_grounded_answer(
    question: str,
    contexts: list[dict],
    profile=None,
    history=None,
) -> str | None:
    """Trả lời dựa trên RAG, hồ sơ và lịch sử hội thoại."""
    if not ai_enabled() or not contexts:
        return None

    excerpts = _format_contexts(contexts)

    if not excerpts:
        return None

    messages = [
        {
            "role": "system",
            "content": (
                "Bạn là NutriAI, trợ lý hội thoại bằng tiếng Việt, "
                "hỗ trợ về dinh dưỡng và sức khỏe.\n\n"
                "NGUYÊN TẮC TRẢ LỜI:\n"
                "- Trả lời trực tiếp câu hỏi hiện tại trước.\n"
                "- Dùng ngôn ngữ tự nhiên, thân thiện, rõ ràng.\n"
                "- Không bắt buộc mọi câu trả lời có cùng bố cục.\n"
                "- Câu hỏi đơn giản: trả lời ngắn gọn.\n"
                "- Câu hỏi phức tạp: giải thích theo từng ý khi cần.\n"
                "- Không chép nối nhiều đoạn tài liệu một cách máy móc.\n"
                "- Chỉ dùng tài liệu làm căn cứ cho thông tin mà tài liệu "
                "thực sự hỗ trợ.\n"
                "- Nếu tài liệu không đủ, hãy nói rõ giới hạn và hỏi "
                "thêm thông tin khi cần; không bịa dữ kiện.\n"
                "- Dùng lịch sử hội thoại để hiểu câu hỏi tiếp nối.\n"
                "- Không tự suy đoán hồ sơ hoặc mục tiêu cá nhân.\n"
                "- Không chẩn đoán, kê đơn hay yêu cầu tự ngừng thuốc.\n"
                "- Với câu hỏi về thuốc, cần làm rõ loại thuốc và lý do "
                "sử dụng; khuyên người dùng hỏi bác sĩ/dược sĩ khi cần.\n"
                "- Không đưa tiêu đề 'Chủ đề kiến thức liên quan' "
                "hoặc liệt kê nguồn nếu người dùng không yêu cầu."
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
            f"Câu hỏi hiện tại:\n{question}\n\n"
            f"Hồ sơ người dùng:\n{profile or {}}\n\n"
            f"Kiến thức truy xuất được:\n{excerpts}\n\n"
            "Hãy trả lời đúng trọng tâm, chỉ sử dụng những thông tin "
            "liên quan đến câu hỏi hiện tại."
        ),
    })

    return _generate_text(messages, temperature=0.4)


def generate_general_answer(
    question: str,
    profile=None,
    history=None,
) -> str | None:
    """Trả lời hội thoại thông thường bằng Gemini/OpenAI."""
    if not ai_enabled():
        return None

    messages = [
        {
            "role": "system",
            "content": (
                "Bạn là NutriAI, trợ lý trò chuyện bằng tiếng Việt.\n"
                "Ưu tiên dinh dưỡng, ăn uống, vận động và lối sống "
                "lành mạnh, nhưng vẫn trả lời các câu hỏi phổ thông "
                "ngoài kho kiến thức.\n"
                "Trả lời trực tiếp, tự nhiên và đúng trọng tâm.\n"
                "Không ép mọi câu trả lời theo một mẫu cố định.\n"
                "Câu hỏi đơn giản nên trả lời ngắn gọn; câu hỏi cần "
                "giải thích mới dùng danh sách hoặc tiêu đề.\n"
                "Dùng lịch sử hội thoại khi câu hỏi phụ thuộc vào "
                "những lượt trao đổi trước.\n"
                "Không bịa thông tin cá nhân hoặc dữ liệu thời gian thực.\n"
                "Với vấn đề y tế, không chẩn đoán hay kê đơn; không "
                "khuyên tự ngừng thuốc đã được kê.\n"
                "Nếu thiếu thông tin quan trọng, hãy hỏi một câu "
                "làm rõ thay vì đoán."
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
            f"Câu hỏi hiện tại:\n{question}\n\n"
            f"Hồ sơ người dùng (nếu có): {profile or {}}"
        ),
    })

    return _generate_text(messages, temperature=0.5)
