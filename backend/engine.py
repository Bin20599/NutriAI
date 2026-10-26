from __future__ import annotations

import re
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from .rag import TextRAG
from .tools import bmi, bmr_mifflin, tdee
from .production_rag import (
    ai_enabled,
    generate_general_answer,
    generate_grounded_answer,
)

ROOT = Path(__file__).resolve().parents[1]
RAG = TextRAG(ROOT / "data" / "knowledge.txt")


def _has(text: str, words: list[str]) -> bool:
    low = text.lower()
    return any(word.lower() in low for word in words)


def _clean_text(text: str) -> str:
    """Chuẩn hóa khoảng trắng và dấu câu để nhận diện hội thoại."""
    return re.sub(r"\s+", " ", text.strip().lower()).strip(
        " \t\n\r.,!?;:"
    )


def _remove_unwanted_ai_metadata(text: str) -> str:
    """Bỏ lời chào lặp và nhãn nguồn/phân loại khỏi câu trả lời AI."""
    lines = text.strip().splitlines()
    cleaned = []
    for line in lines:
        if re.match(
            r"^\s*(?:Nguồn(?: kiến thức NutriAI)?|Phân loại)\s*:",
            line,
            flags=re.IGNORECASE,
        ):
            continue
        cleaned.append(line)

    result = "\n".join(cleaned).strip()
    # Bỏ lời chào tự phát ở đầu câu trả lời; lời chào người dùng gửi
    # riêng đã được xử lý bởi _small_talk().
    result = re.sub(
        r"^(?:Xin chào(?: bạn)?|Chào(?: bạn)?(?:\s+[^,!.\n]{1,40})?|"
        r"Hello|Hi|Hey)(?:\s*[,!:.—-]\s*|\s+)",
        "",
        result,
        count=1,
        flags=re.IGNORECASE,
    )
    return result.strip()


def _extract_metrics(
    text: str,
) -> tuple[float | None, float | None, int | None]:
    normalized = text.lower().replace(",", ".")
    height = weight = age = None

    meter = re.search(
        r"(?<!\w)(\d+(?:\.\d+)?)\s*m\s*(\d{1,2})?",
        normalized,
    )

    if meter:
        first = float(meter.group(1))
        extra = meter.group(2)
        height = (
            first * 100 + (float(extra) if extra else 0)
            if first < 3
            else first
        )
    else:
        cm = re.search(
            r"(?:cao|height)[^0-9]{0,12}(\d+(?:\.\d+)?)\s*cm",
            normalized,
        )
        if cm:
            height = float(cm.group(1))

    weight_match = re.search(
        r"(?:nang|weight)[^0-9]{0,12}(\d+(?:\.\d+)?)\s*kg",
        normalized,
    )
    if weight_match:
        weight = float(weight_match.group(1))

    age_match = re.search(
        r"(?:tuoi|age)[^0-9]{0,12}(\d{1,3})",
        normalized,
    )
    if age_match:
        age = int(age_match.group(1))

    return height, weight, age


def _small_talk(message: str) -> str | None:
    """Xử lý lời chào và hội thoại cơ bản."""
    text = _clean_text(message)

    greetings = {
        "xin chào",
        "chào",
        "chào bạn",
        "hello",
        "hi",
        "hey",
        "alo",
        "good morning",
        "good evening",
    }

    thanks = {
        "cảm ơn",
        "cảm ơn bạn",
        "thanks",
        "thank you",
        "cám ơn",
    }

    farewells = {
        "tạm biệt",
        "bye",
        "goodbye",
        "hẹn gặp lại",
    }

    if text in greetings:
        return (
            "Xin chào! Mình là NutriAI. Hôm nay bạn muốn "
            "tìm hiểu về dinh dưỡng, xây dựng thực đơn hay "
            "cải thiện một mục tiêu sức khỏe nào?"
        )

    if text in thanks:
        return (
            "Không có gì nhé! Bạn cứ hỏi thêm nếu muốn "
            "tìm hiểu sâu hơn."
        )

    if text in farewells:
        return "Tạm biệt bạn! Hẹn gặp lại nhé."

    if text in {
        "bạn là ai",
        "bạn là ai vậy",
        "nutriai là gì",
        "who are you",
    }:
        return (
            "Mình là NutriAI, trợ lý hỗ trợ về dinh dưỡng, "
            "thực đơn và các chỉ số sức khỏe như BMI, BMR, TDEE. "
            "Mình cũng có thể hỗ trợ một số câu hỏi phổ thông "
            "thông qua AI Gemini."
        )

    if text in {
        "bạn có thể làm gì",
        "bạn làm được gì",
        "giúp được gì",
        "help",
    }:
        return (
            "Mình có thể hỗ trợ bạn tìm hiểu về ăn uống, "
            "giảm cân, tăng cơ, thực đơn và nhu cầu năng lượng; "
            "tính BMI, BMR, TDEE; đồng thời trả lời câu hỏi "
            "phổ thông bằng AI Gemini. Với câu trả lời từ AI, "
            "bạn nên kiểm chứng thông tin quan trọng."
        )

    return None


def _get_score(item: dict) -> float:
    """Đọc điểm truy xuất an toàn."""
    try:
        return float(item.get("score", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def _get_title(item: dict) -> str:
    """Lấy tiêu đề tài liệu để hiển thị nguồn."""
    title = str(item.get("title", "") or "").strip()
    if not title:
        metadata = item.get("metadata")
        if isinstance(metadata, dict):
            title = str(metadata.get("title", "") or "").strip()
    return title


def _format_source_titles(contexts: list[dict]) -> str:
    """Tạo nhãn nguồn từ các tài liệu RAG đã truy xuất."""
    titles = []
    seen = set()

    for item in contexts:
        title = _get_title(item)
        if title and title.lower() not in seen:
            seen.add(title.lower())
            titles.append(title)

    if titles:
        return "Nguồn kiến thức NutriAI: " + "; ".join(titles[:3])

    return "Nguồn kiến thức NutriAI: các đoạn tài liệu được truy xuất"


def _build_rag_answer(
    contexts: list[dict],
    message: str,
) -> str:
    """
    Fallback TXT khi Gemini không khả dụng.
    Chỉ dùng các đoạn có điểm truy xuất đạt ngưỡng.
    """
    if not contexts:
        return ""

    relevant_contexts = [
        item for item in contexts
        if _get_score(item) >= 4.0
    ]

    if not relevant_contexts:
        return ""

    selected = []
    seen_content = set()

    for item in relevant_contexts:
        content = re.sub(
            r"\s+",
            " ",
            str(item.get("content", "") or "").strip(),
        )
        if not content:
            continue

        normalized = content.lower()
        if normalized in seen_content:
            continue

        seen_content.add(normalized)
        selected.append({
            "title": _get_title(item),
            "content": content,
        })

        if len(selected) >= 3:
            break

    if not selected:
        return ""

    answer_parts = [selected[0]["content"]]

    for item in selected[1:]:
        content = item["content"]
        if content.lower() not in answer_parts[0].lower():
            answer_parts.append(content)

    return "\n\n".join(answer_parts)


def _ai_error_message() -> str:
    return (
        "Hiện tại NutriAI chưa nhận được câu trả lời từ Gemini. "
        "Dịch vụ AI có thể đang quá tải hoặc phản hồi quá chậm. "
        "Bạn hãy thử lại sau ít phút nhé."
    )


def answer(
    message: str,
    profile: dict | None = None,
) -> tuple[str, list[dict]]:
    profile = profile or {}
    m = message.strip()
    low = m.lower()

    if not m:
        return (
            "Bạn hãy nhập câu hỏi để mình hỗ trợ nhé.",
            [],
        )

    # 1. Hội thoại cơ bản.
    small_talk = _small_talk(m)
    if small_talk:
        return small_talk, []

    # 2. Tính toán BMI, BMR và TDEE.
    extracted_height, extracted_weight, extracted_age = (
        _extract_metrics(low)
    )

    nums = [
        float(x.replace(",", "."))
        for x in re.findall(r"(?<!\w)\d+(?:[\.,]\d+)?", low)
    ]

    if _has(low, ["bmi", "chỉ số bmi"]) and (
        (
            extracted_height is not None
            and extracted_weight is not None
        )
        or len(nums) >= 2
    ):
        height = (
            extracted_height
            if extracted_height is not None
            else (nums[0] * 100 if nums[0] < 3 else nums[0])
        )
        weight = (
            extracted_weight
            if extracted_weight is not None
            else nums[1]
        )

        try:
            value, label = bmi(height, weight)
            return (
                f"BMI ước tính của bạn là {value}. "
                f"Chỉ số này đang ở mức {label}. "
                "BMI chỉ là chỉ số sàng lọc, không phải kết luận "
                "toàn diện về sức khỏe.",
                [],
            )
        except (ValueError, ZeroDivisionError):
            return (
                "Mình chưa thể tính BMI với số liệu này. "
                "Bạn hãy kiểm tra lại chiều cao tính bằng cm "
                "và cân nặng tính bằng kg nhé.",
                [],
            )

    if _has(low, ["tdee", "bmr"]) and (
        (
            extracted_height is not None
            and extracted_weight is not None
            and extracted_age is not None
        )
        or len(nums) >= 3
    ):
        height = (
            extracted_height
            if extracted_height is not None
            else (nums[0] * 100 if nums[0] < 3 else nums[0])
        )
        weight = (
            extracted_weight
            if extracted_weight is not None
            else nums[1]
        )
        age = (
            extracted_age
            if extracted_age is not None
            else int(nums[2])
        )

        gender = profile.get("gender") or ""
        activity = profile.get("activity_level") or "moderate"

        try:
            bmr_val = bmr_mifflin(weight, height, age, gender)
            tdee_val = tdee(bmr_val, activity)

            return (
                f"Theo dữ liệu bạn cung cấp, BMR ước tính khoảng "
                f"{bmr_val:,.0f} kcal/ngày và TDEE khoảng "
                f"{tdee_val:,.0f} kcal/ngày.\n\n"
                "Đây là các giá trị ước tính, phụ thuộc vào "
                "thông tin đầu vào và mức vận động.",
                [],
            )
        except (ValueError, ZeroDivisionError):
            return (
                "Mình chưa thể tính BMR/TDEE từ số liệu này. "
                "Bạn hãy kiểm tra lại tuổi, chiều cao và cân nặng nhé.",
                [],
            )

    # 3. Truy xuất tài liệu từ kho RAG.
    contexts = RAG.retrieve(m, top_k=5)

    relevant_contexts = [
        item for item in contexts
        if _get_score(item) >= 4.0
    ]

    # 4. Ưu tiên câu trả lời dựa trên RAG nếu có nguồn phù hợp.
    if ai_enabled():
        if relevant_contexts:
            try:
                grounded_text = generate_grounded_answer(
                    question=m,
                    contexts=relevant_contexts[:3],
                    profile=profile,
                )

                if grounded_text and grounded_text.strip():
                    answer_text = _remove_unwanted_ai_metadata(
                        grounded_text.strip()
                    )
                    if answer_text:
                        return answer_text, []

            except Exception as exc:
                print(
                    "NutriAI grounded generation error:",
                    str(exc)[:500],
                )

        # 5. Không có nguồn RAG phù hợp, hoặc tạo câu trả lời
        # dựa trên RAG thất bại: cho phép Gemini trả lời phổ thông.
        try:
            general_text = generate_general_answer(
                question=m,
                profile=profile,
            )

            if general_text and general_text.strip():
                answer_text = _remove_unwanted_ai_metadata(
                    general_text.strip()
                )
                if answer_text:
                    # Câu trả lời phổ thông không gắn nguồn RAG.
                    return answer_text, []

        except Exception as exc:
            print(
                "NutriAI general generation error:",
                str(exc)[:500],
            )

        # Không trả về các đoạn TXT không liên quan khi Gemini lỗi.
        return _ai_error_message(), []

    # 6. Không có Gemini: chỉ trả lời bằng TXT khi có nguồn đủ phù hợp.
    rag_answer = _build_rag_answer(contexts, m)
    if rag_answer:
        return rag_answer, []

    return (
        "Mình chưa tìm thấy nguồn kiến thức đủ phù hợp trong "
        "kho dữ liệu NutriAI để trả lời chắc chắn. Hiện tại AI "
        "Gemini chưa được cấu hình hoặc chưa khả dụng. Bạn có thể "
        "thử diễn đạt câu hỏi cụ thể hơn hoặc bổ sung tài liệu "
        "liên quan vào kho kiến thức.",
        [],
    )


def reload_knowledge() -> dict:
    RAG.reload()
    return RAG.stats()
