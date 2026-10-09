from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

WORD_RE = re.compile(r"[\wÀ-ỹ]+", re.UNICODE)
STOPWORDS = {"la", "gi", "cua", "toi", "ban", "mot", "va", "co", "the", "nao", "thi", "minh", "muon", "nhung", "cho", "tu", "ve", "bao", "nhieu", "neu", "khi", "duoc", "khong", "xin", "chao", "g", "kg", "m"}


@dataclass(frozen=True)
class Chunk:
    title: str
    tags: tuple[str, ...]
    content: str
    source: str
    chunk_id: str

    @property
    def searchable(self) -> str:
        return " ".join((self.title, " ".join(self.tags), self.content))


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFD", value.lower())
    return "".join(ch for ch in value if unicodedata.category(ch) != "Mn")


def tokens(value: str) -> list[str]:
    return [word for word in WORD_RE.findall(normalize(value)) if word not in STOPWORDS]


def _chunk_text(title: str, tags: list[str], content: str, source: str) -> list[Chunk]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", content) if p.strip()]
    chunks: list[Chunk] = []
    buf = ""
    idx = 1
    for paragraph in paragraphs:
        candidate = f"{buf} {paragraph}".strip()
        if buf and len(candidate) > 620:
            chunks.append(Chunk(title, tuple(tags), buf, source, f"{normalize(title).replace(' ', '-')}-{idx}"))
            idx += 1
            buf = paragraph
        else:
            buf = candidate
    if buf:
        chunks.append(Chunk(title, tuple(tags), buf, source, f"{normalize(title).replace(' ', '-')}-{idx}"))
    return chunks


def parse_txt(path: Path) -> list[Chunk]:
    text = path.read_text(encoding="utf-8-sig")
    blocks = re.split(r"\n(?=\[TITLE\])", text)
    chunks: list[Chunk] = []
    for block in blocks:
        if "[TITLE]" not in block or "[CONTENT]" not in block:
            continue
        title_match = re.search(r"\[TITLE\]\s*(.+)", block)
        tags_match = re.search(r"\[TAGS\]\s*(.+)", block)
        content_match = re.search(r"\[CONTENT\]\s*([\s\S]+?)(?=\n\[TITLE\]|\Z)", block)
        if not (title_match and content_match):
            continue
        title = title_match.group(1).strip()
        tags = [x.strip() for x in (tags_match.group(1) if tags_match else "").split(",") if x.strip()]
        content = content_match.group(1).strip()
        chunks.extend(_chunk_text(title, tags, content, path.name))
    return chunks


class TextRAG:
    """Lightweight TXT retrieval for the offline demo.

    This is intentionally dependency-free. It ranks local TXT chunks using
    lexical overlap and phrase bonuses. The production version can replace
    only the retrieve() method with embeddings + Supabase pgvector.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.chunks: list[Chunk] = []
        self.reload()

    def reload(self) -> None:
        self.chunks = parse_txt(self.path)

    def retrieve(self, query: str, top_k: int = 4) -> list[dict]:
        q = set(tokens(query))
        q_norm = normalize(query)
        scored: list[tuple[float, Chunk]] = []
        for chunk in self.chunks:
            title_tokens = set(tokens(chunk.title))
            tag_tokens = set(tokens(" ".join(chunk.tags)))
            body_tokens = set(tokens(chunk.content))
            score = 0.0
            score += len(q & title_tokens) * 5.0
            score += len(q & tag_tokens) * 3.0
            score += len(q & body_tokens) * 1.2
            for phrase in chunk.tags:
                if normalize(phrase) in q_norm:
                    score += 3.5
            if normalize(chunk.title) in q_norm:
                score += 7.0
            if score >= 2.8:
                scored.append((score, chunk))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            {
                "title": chunk.title,
                "content": chunk.content,
                "source": chunk.source,
                "chunk_id": chunk.chunk_id,
                "score": round(score, 2),
            }
            for score, chunk in scored[:top_k]
        ]

    def stats(self) -> dict:
        titles = list(dict.fromkeys(chunk.title for chunk in self.chunks))
        return {
            "source": self.path.name,
            "documents": len(titles),
            "chunks": len(self.chunks),
            "mode": "TXT lexical retrieval",
        }
