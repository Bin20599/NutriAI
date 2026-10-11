
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
from .production_rag import ai_enabled, generate_general_answer

ROOT = Path(__file__).resolve().parents[1]
RAG = TextRAG(ROOT / "data" / "knowledge.txt")


def _has(text: str, words: list[str]) -> bool:
    low = text.lower()
    return any(word.lower() in low for word in words)


def _clean_text(text: str) -> str:
    """Chuẩn hóa khoảng trắng và dấu câu để nhận diện hội thoại."""
    return re.sub(r"\s+", " ", text.strip().lower()).strip(" \t\n\r.,!?;:")


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
    """
    Xử lý hội thoại cơ bản không cần API.
    Chỉ xử lý những câu nhận diện rõ ràng, không thay thế RAG.
    """
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
            "Xin chào! Mình là NutriAI, trợ lý hỗ trợ về dinh dưỡng "
            "và sức khỏe. Bạn có thể hỏi mình về giảm cân, tăng cơ, "
            "calories, protein, thực đơn hoặc các chỉ số BMI, BMR, TDEE. "
            "Bạn đang muốn tìm hiểu điều gì hôm nay?"
        )

    if text in thanks:
        return (
            "Rất vui được hỗ trợ bạn! Bạn cứ hỏi thêm nếu muốn tìm hiểu "
            "sâu hơn về dinh dưỡng, thực đơn hoặc mục tiêu sức khỏe nhé."
        )

    if text in farewells:
        return (
            "Tạm biệt bạn! Chúc bạn duy trì được những thói quen "
            "ăn uống và vận động lành mạnh. Hẹn gặp lại!"
        )

    if text in {
        "bạn là ai",
        "bạn là ai vậy",
        "nutriai là gì",
        "who are you",
    }:
        return (
            "Mình là NutriAI, trợ lý dinh dưỡng sử dụng kho kiến thức "
            "để hỗ trợ giải đáp các câu hỏi về ăn uống, vận động và "
            "các chỉ số sức khỏe. Mình cũng có thể tính BMI, BMR và "
            "TDEE khi bạn cung cấp đủ thông tin."
        )

    if text in {
        "bạn có thể làm gì",
        "bạn làm được gì",
        "giúp được gì",
        "help",
    }:
        return (
            "Mình có thể giúp bạn tìm hiểu về giảm cân, tăng cân, "
            "protein, calories, thực đơn và vận động; đồng thời hỗ trợ "
            "tính BMI, BMR và TDEE. Bạn hãy nêu mục tiêu hoặc câu hỏi "
            "cụ thể để mình hỗ trợ nhé."
        )

    return None


def _build_rag_answer(
    contexts: list[dict],
    message: str,
) -> str:
    """
    Kết hợp các đoạn kiến thức liên quan, loại bỏ nội dung trùng lặp
    và tạo câu trả lời có cấu trúc mà không cần LLM.
    """
    if not contexts:
        return ""

    selected = []
    seen_content = set()

    # Giới hạn số đoạn để câu trả lời không quá dài.
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

    lead = selected[0]["content"]
    answer_parts = [lead]

    # Thêm nội dung thứ hai, thứ ba nếu đủ liên quan.
    first_score = selected[0]["score"]

    for item in selected[1:]:
        score = item["score"]

        try:
            relevant = score >= max(1, first_score * 0.35)
        except (TypeError, ValueError):
            relevant = False

        if not relevant:
            continue

        content = item["content"]

        # Tránh lặp nguyên nội dung đã có trong câu trả lời.
        if content.lower() not in lead.lower():
            answer_parts.append(content)

    answer_text = "\n\n".join(answer_parts)

    low = message.lower()

    if _has(low, ["giảm cân", "giảm mỡ", "giảm béo"]):
        answer_text += (
            "\n\n**Gợi ý áp dụng:** Hãy ưu tiên thay đổi từ từ, "
            "duy trì thói quen ăn uống phù hợp và vận động đều đặn. "
            "Tránh các phương pháp giảm cân cực đoan."
        )

    if _has(low, ["protein", "đạm", "tăng cơ"]):
        answer_text += (
            "\n\n**Gợi ý thực phẩm:** Bạn có thể luân phiên trứng, "
            "cá, thịt nạc, sữa, đậu phụ và các loại đậu tùy theo "
            "nhu cầu và sở thích."
        )

    if _has(low, ["thực đơn", "bữa sáng", "bữa trưa", "bữa tối"]):
        answer_text += (
            "\n\n**Gợi ý áp dụng:** Có thể phối hợp nguồn protein, "
            "rau củ, thực phẩm giàu tinh bột và chất béo phù hợp. "
            "Khẩu phần nên điều chỉnh theo nhu cầu cá nhân."
        )

    if _has(low, ["calories", "calo", "kcal"]):
        answer_text += (
            "\n\nNhu cầu năng lượng khác nhau tùy tuổi, chiều cao, "
            "cân nặng, mức vận động và mục tiêu của mỗi người."
        )

    if len(selected) > 1:
        titles = []
        for item in selected[1:]:
            if item["title"] and item["title"] not in titles:
                titles.append(item["title"])

        if titles:
            answer_text += (
                "\n\n**Chủ đề kiến thức liên quan:** "
                + "; ".join(titles)
                + "."
            )

    return answer_text


def answer(
    message: str,
    profile: dict | None = None,
) -> tuple[str, list[dict]]:
    profile = profile or {}
    m = message.strip()
    low = m.lower()

    if not m:
        return (
            "Bạn hãy nhập câu hỏi để mình hỗ trợ nhé. "
            "Bạn có thể hỏi về dinh dưỡng, thực đơn hoặc các chỉ số sức khỏe.",
            [],
        )

    # 1. Hội thoại cơ bản không cần API.
    small_talk = _small_talk(m)
    if small_talk:
        return small_talk, []

    # 2. Các phép tính cần kết quả xác định.
    extracted_height, extracted_weight, extracted_age = _extract_metrics(low)

    nums = [
        float(x.replace(",", "."))
        for x in re.findall(r"(?<!\w)\d+(?:[\.,]\d+)?", low)
    ]

    if _has(low, ["bmi", "chỉ số bmi"]) and (
        (extracted_height is not None and extracted_weight is not None)
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
                "toàn diện về sức khỏe. Nếu muốn, bạn có thể tìm hiểu "
                "thêm về BMR và TDEE để tham khảo nhu cầu năng lượng.",
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
                "BMR là năng lượng cơ thể tiêu hao khi nghỉ ngơi; "
                "TDEE là tổng năng lượng tiêu hao ước tính trong ngày. "
                "Kết quả chỉ mang tính tham khảo và phụ thuộc vào "
                "độ chính xác của thông tin đầu vào.",
                RAG.retrieve("BMR và TDEE", 2),
            )
        except (ValueError, ZeroDivisionError):
            return (
                "Mình chưa thể tính BMR/TDEE từ số liệu này. "
                "Bạn hãy kiểm tra lại tuổi, chiều cao, cân nặng "
                "và thông tin hồ sơ nếu có nhé.",
                [],
            )

    # 3. Tìm kiếm và tổng hợp kiến thức từ TXT RAG.
    contexts = RAG.retrieve(m, top_k=5)

    if contexts:
        rag_answer = _build_rag_answer(contexts, m)
        if rag_answer:
            return rag_answer, contexts

    # 4. Chỉ dùng mô hình mở rộng nếu đã được cấu hình.
    if ai_enabled():
        try:
            general_text = generate_general_answer(m, profile)
            if general_text:
                return general_text, []
        except Exception as exc:
            print("General LLM fallback:", str(exc)[:250])

    # 5. Fallback trung thực khi chưa có kiến thức phù hợp.
    return (
        "Mình chưa tìm thấy thông tin đủ phù hợp trong kho kiến thức "
        "để trả lời chính xác câu hỏi này.\n\n"
        "Bạn có thể diễn đạt câu hỏi cụ thể hơn, chẳng hạn nêu mục tiêu "
        "giảm cân, tăng cơ, loại thực phẩm hoặc chỉ số sức khỏe muốn "
        "tìm hiểu. Mình sẽ thử tìm lại trong kho kiến thức hiện có.",
        [],
    )


def reload_knowledge() -> dict:
    RAG.reload()
    return RAG.stats()
