from __future__ import annotations


def bmi(height_cm: float, weight_kg: float) -> tuple[float, str]:
    if height_cm <= 0 or weight_kg <= 0:
        raise ValueError("Chiều cao và cân nặng phải lớn hơn 0")
    value = weight_kg / ((height_cm / 100) ** 2)
    if value < 18.5:
        label = "dưới khoảng tham khảo"
    elif value < 25:
        label = "trong khoảng tham khảo"
    elif value < 30:
        label = "cao hơn khoảng tham khảo"
    else:
        label = "cao"
    return round(value, 2), label


def bmr_mifflin(weight_kg: float, height_cm: float, age: int, gender: str | None) -> float:
    base = 10 * weight_kg + 6.25 * height_cm - 5 * age
    return round(base + (5 if str(gender).lower() in {"nam", "male", "m"} else -161), 2)


def tdee(bmr_value: float, activity: str | None) -> float:
    factors = {"low": 1.2, "light": 1.375, "moderate": 1.55, "high": 1.725, "very_high": 1.9}
    return round(bmr_value * factors.get(activity or "low", 1.2), 2)
