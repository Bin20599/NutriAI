from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.engine import RAG, answer
from backend.production_rag import ai_enabled

def test_knowledge_is_loaded():
    assert RAG.stats()["chunks"] > 0

def test_local_rag_answer():
    text, sources = answer("Tôi muốn giảm cân thì bắt đầu thế nào?")
    assert text
    assert sources

def test_ai_disabled_without_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert ai_enabled() is False
