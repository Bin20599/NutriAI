from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.engine import answer, RAG


def test_knowledge_loaded():
    stats = RAG.stats()
    assert stats["documents"] >= 8
    assert stats["chunks"] >= stats["documents"]


def test_weight_loss_retrieval():
    text, sources = answer("Tôi muốn giảm cân thì bắt đầu thế nào?")
    assert "thâm hụt" in text.lower()
    assert sources


def test_bmi():
    text, sources = answer("BMI của tôi là bao nhiêu nếu cao 1m70 nặng 75kg?")
    assert "25.95" in text
    assert any(x["title"] == "BMI và cách tính" for x in sources)


def test_offtopic_does_not_leak_random_context():
    text, sources = answer("Python là gì?")
    assert "chưa tìm thấy" in text.lower()
    assert sources == []


if __name__ == "__main__":
    test_knowledge_loaded()
    test_weight_loss_retrieval()
    test_bmi()
    print("All RAG tests passed.")
