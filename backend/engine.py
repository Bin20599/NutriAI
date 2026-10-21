
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
            "thực đơn và các chỉ số sức khỏe như BMI, BMR, TDEE."
        )

    if text in {
        "bạn có thể làm gì",
        "bạn làm được gì",
        "giúp được gì",
        "help",
    }:
        return (
            "Mình có thể hỗ trợ bạn tìm hiểu về ăn uống, "
            "giảm cân, tăng cơ, thực đơn và nhu cầu năng lượng. "
            "Bạn đang muốn giải quyết vấn đề gì?"
        )

    return None


def _build_rag_answer(
    contexts: list[dict],
    message: str,
) -> str:
    """
    Fallback khi AI không khả dụng.
    Hạn chế ghép các đoạn kiến thức không liên quan.
    """
    if not contexts:
        return ""

    selected = []
    seen_content = set()

    for item in contexts:
        content = re.sub(
            r"\s+",
            " ",
            str(item.get("content", "")).strip(),
        )
        if not content:
            continue

        normalized = content.lower()
        if normalized in seen_content:
            continue

        seen_content.add(normalized)
        selected.append({
            "title": str(item.get("title", "")).strip(),
            "content": content,
            "score": item.get("score", 0),
        })

        if len(selected) >= 3:
            break

    if not selected:
        return ""

    answer_parts = [selected[0]["content"]]
    first_score = selected[0]["score"]

    for item in selected[1:]:
        try:
            relevant = float(item["score"]) >= max(
                1.0, float(first_score) * 0.6
            )
        except (TypeError, ValueError):
            relevant = False

        if not relevant:
            continue

        content = item["content"]
        if content.lower() not in answer_parts[0].lower():
            answer_parts.append(content)

    return "\n\n".join(answer_parts)


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
                RAG.retrieve("BMI", 2),
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
                RAG.retrieve("BMR và TDEE", 2),
            )
        except (ValueError, ZeroDivisionError):
            return (
                "Mình chưa thể tính BMR/TDEE từ số liệu này. "
                "Bạn hãy kiểm tra lại tuổi, chiều cao và cân nặng nhé.",
                [],
            )

    # 3. Truy xuất kiến thức.
    contexts = RAG.retrieve(m, top_k=5)

    # 4. Ưu tiên Gemini nếu đã cấu hình.
    if ai_enabled():
        try:
            relevant_contexts = []

            for item in contexts:
                try:
                    score = float(item.get("score", 0) or 0)
                except (TypeError, ValueError):
                    score = 0

                # Ngưỡng ban đầu, cần điều chỉnh theo thang điểm RAG.
                if score >= 4.0:
                    relevant_contexts.append(item)

            if relevant_contexts:
                grounded_text = generate_grounded_answer(
                    question=m,
                    contexts=relevant_contexts[:3],
                    profile=profile,
                )

                if grounded_text:
                    return grounded_text, relevant_contexts

            # Câu hỏi ngoài kho kiến thức hoặc không đủ ngữ cảnh.
            general_text = generate_general_answer(
                question=m,
                profile=profile,
            )

            if general_text:
                return general_text, []

        except Exception as exc:
            print(
                "NutriAI AI generation error:",
                str(exc)[:500],
            )

    # 5. Fallback TXT khi AI không khả dụng.
    if contexts:
        rag_answer = _build_rag_answer(contexts, m)
        if rag_answer:
            return rag_answer, contexts

    return (
        "Mình chưa tìm thấy thông tin đủ phù hợp để trả lời "
        "chắc chắn. Bạn có thể nói rõ hơn một chút để mình "
        "hỗ trợ bạn tốt hơn nhé.",
        [],
    )


def reload_knowledge() -> dict:
    RAG.reload()
    return RAG.stats()
