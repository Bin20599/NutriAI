from __future__ import annotations

import re
from pathlib import Path

from .rag import TextRAG
from .tools import bmi, bmr_mifflin, tdee

ROOT = Path(__file__).resolve().parents[1]
RAG = TextRAG(ROOT / "data" / "knowledge.txt")


def _has(text: str, words: list[str]) -> bool:
    low = text.lower()
    return any(word.lower() in low for word in words)


def _extract_metrics(text: str) -> tuple[float | None, float | None, int | None]:
    normalized = text.lower().replace(',', '.')
    height = weight = age = None
    meter = re.search(r'(?<!\w)(\d+(?:\.\d+)?)\s*m\s*(\d{1,2})?', normalized)
    if meter:
        first = float(meter.group(1))
        extra = meter.group(2)
        height = first * 100 + (float(extra) if extra else 0) if first < 3 else first
    else:
        cm = re.search(r'(?:cao|height)[^0-9]{0,12}(\d+(?:\.\d+)?)\s*cm', normalized)
        if cm:
            height = float(cm.group(1))
    weight_match = re.search(r'(?:nang|weight)[^0-9]{0,12}(\d+(?:\.\d+)?)\s*kg', normalized)
    if weight_match:
        weight = float(weight_match.group(1))
    age_match = re.search(r'(?:tuoi|age)[^0-9]{0,12}(\d{1,3})', normalized)
    if age_match:
        age = int(age_match.group(1))
    return height, weight, age


def answer(message: str, profile: dict | None = None) -> tuple[str, list[dict]]:
    profile = profile or {}
    m = message.strip()
    low = m.lower()

    # Fast calculations: keep deterministic and explainable for the demo.
    extracted_height, extracted_weight, extracted_age = _extract_metrics(low)
    nums = [float(x.replace(",", ".")) for x in re.findall(r"(?<!\w)\d+(?:[\.,]\d+)?", low)]
    if _has(low, ["bmi", "chỉ số bmi"]) and (extracted_height and extracted_weight or len(nums) >= 2):
        height = extracted_height if extracted_height else (nums[0] * 100 if nums[0] < 3 else nums[0])
        weight = extracted_weight if extracted_weight else nums[1]
        try:
            value, label = bmi(height, weight)
            return (
                f"BMI ước tính của bạn là {value}. Chỉ số này đang ở mức {label}. "
                "BMI chỉ là một chỉ số sàng lọc; để có góc nhìn đầy đủ hơn, bạn có thể xem thêm BMR/TDEE và mục tiêu cá nhân.",
                RAG.retrieve("BMI", 2),
            )
        except ValueError:
            pass

    if _has(low, ["tdee", "bmr"]) and (extracted_height and extracted_weight and extracted_age or len(nums) >= 3):
        # height, weight, age. Gender/activity can come from the saved profile.
        height = extracted_height if extracted_height else (nums[0] * 100 if nums[0] < 3 else nums[0])
        weight = extracted_weight if extracted_weight else nums[1]
        age = extracted_age if extracted_age else int(nums[2])
        gender = profile.get("gender") or ""
        activity = profile.get("activity_level") or "moderate"
        bmr_val = bmr_mifflin(weight, height, age, gender)
        tdee_val = tdee(bmr_val, activity)
        return (
            f"Theo dữ liệu bạn nhập, BMR ước tính khoảng {bmr_val:,.0f} kcal/ngày và TDEE khoảng {tdee_val:,.0f} kcal/ngày. "
            "Đây là ước tính tham khảo và có thể sai khác so với nhu cầu thực tế.",
            RAG.retrieve("BMR và TDEE", 2),
        )

    contexts = RAG.retrieve(m, top_k=4)
    if contexts:
        lead = contexts[0]["content"]
        extra = []
        if _has(low, ["giảm cân", "giảm mỡ"]):
            extra.append("Điểm quan trọng là tạo thâm hụt năng lượng vừa phải và chọn cách ăn có thể duy trì lâu dài.")
        if _has(low, ["protein", "đạm"]):
            extra.append("Bạn có thể luân phiên trứng, cá, thịt nạc, sữa/sữa chua, đậu phụ và các loại đậu.")
        if _has(low, ["bữa sáng", "bữa ăn", "thực đơn", "món"]):
            extra.append("Khi lên khẩu phần, hãy cân bằng protein + rau/trái cây + tinh bột phù hợp + chất béo lành mạnh.")
        answer_text = lead
        if extra:
            answer_text += " " + " ".join(extra)
        if len(contexts) > 1 and contexts[1]["score"] >= max(1, contexts[0]["score"] * 0.35):
            answer_text += f"\n\nLiên quan từ kho kiến thức: {contexts[1]['title']}."
        return answer_text, contexts

    return (
        "Mình chưa tìm thấy đoạn kiến thức phù hợp trong kho TXT hiện tại. "
        "Bạn hãy thử hỏi về giảm cân, protein, tinh bột, chất béo, chất xơ, bữa ăn, BMI hoặc BMR/TDEE.",
        [],
    )


def reload_knowledge() -> dict:
    RAG.reload()
    return RAG.stats()
