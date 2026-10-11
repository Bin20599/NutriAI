
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

WORD_RE = re.compile(r"\w+", re.UNICODE)

STOPWORDS = {
    "la", "gi", "cua", "toi", "ban", "mot", "va", "co",
    "the", "nao", "thi", "minh", "muon", "nhung", "cho",
    "tu", "ve", "bao", "nhieu", "neu", "khi", "duoc",
    "khong", "xin", "chao", "g", "kg", "m", "la gi",
    "hay", "voi", "cac", "nhung", "nay", "do", "day",
    "ra", "can", "nen", "bi", "duoc", "lao",
}

# Mở rộng các cách diễn đạt phổ biến trong lĩnh vực dinh dưỡng.
# Các nhóm được chuẩn hóa không dấu để hỗ trợ cả cách viết có dấu
# và không dấu của tiếng Việt.
SYNONYM_GROUPS = [
    {"giam can", "giam mo", "giam beo", "giam trong luong"},
    {"tang can", "tang trong luong"},
    {"tang co", "phat trien co", "xay dung co bap"},
    {"protein", "dam", "chat dam"},
    {"calo", "calories", "kcal", "nang luong"},
    {"bmi", "chi so bmi", "chi so khoi co the"},
    {"bmr", "nang luong nghi ngoi"},
    {"tdee", "tong nang luong tieu hao"},
    {"thuc don", "khau phan", "ke hoach an uong"},
    {"bua sang", "an sang"},
    {"bua trua", "an trua"},
    {"bua toi", "an toi"},
    {"chat beo", "lipid", "fat"},
    {"tinh bot", "carbohydrate", "carb"},
    {"tap the duc", "van dong", "hoat dong the chat"},
    {"nuoc", "nuoc uong", "cap nuoc"},
    {"vitamin", "vi chat"},
    {"chat xo", "chat xơ"},
]

SYNONYM_LOOKUP: dict[str, set[str]] = {}

for group in SYNONYM_GROUPS:
    normalized_group = {
        unicodedata.normalize("NFD", item.lower())
        for item in group
    }
    normalized_group = {
        "".join(
            char for char in item
            if unicodedata.category(char) != "Mn"
        )
        for item in normalized_group
    }

    for item in normalized_group:
        SYNONYM_LOOKUP[item] = normalized_group


@dataclass(frozen=True)
class Chunk:
    title: str
    tags: tuple[str, ...]
    content: str
    source: str
    chunk_id: str

    @property
    def searchable(self) -> str:
        return " ".join(
            (self.title, " ".join(self.tags), self.content)
        )


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFD", value.lower())
    value = "".join(
        char for char in value
        if unicodedata.category(char) != "Mn"
    )
    return value.replace("đ", "d")


def tokens(value: str) -> list[str]:
    return [
        word
        for word in WORD_RE.findall(normalize(value))
        if word not in STOPWORDS
    ]


def _expanded_tokens(value: str) -> set[str]:
    """Mở rộng token theo nhóm từ đồng nghĩa."""
    original = set(tokens(value))
    expanded = set(original)

    for group in SYNONYM_GROUPS:
        group_tokens = {
            token
            for phrase in group
            for token in tokens(phrase)
        }

        if original & group_tokens:
            expanded.update(group_tokens)

    return expanded


def _phrase_present(phrase: str, text: str) -> bool:
    phrase_norm = normalize(phrase).strip()
    text_norm = normalize(text).strip()

    if not phrase_norm or not text_norm:
        return False

    pattern = r"(?<!\w)" + re.escape(phrase_norm) + r"(?!\w)"
    return re.search(pattern, text_norm) is not None


def _chunk_text(
    title: str,
    tags: list[str],
    content: str,
    source: str,
) -> list[Chunk]:
    paragraphs = [
        paragraph.strip()
        for paragraph in re.split(r"\n\s*\n", content)
        if paragraph.strip()
    ]

    chunks: list[Chunk] = []
    buffer = ""
    index = 1
    safe_title = normalize(title).replace(" ", "-")

    for paragraph in paragraphs:
        candidate = f"{buffer} {paragraph}".strip()

        if buffer and len(candidate) > 620:
            chunks.append(
                Chunk(
                    title,
                    tuple(tags),
                    buffer,
                    source,
                    f"{safe_title}-{index}",
                )
            )
            index += 1
            buffer = paragraph
        else:
            buffer = candidate

    if buffer:
        chunks.append(
            Chunk(
                title,
                tuple(tags),
                buffer,
                source,
                f"{safe_title}-{index}",
            )
        )

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
        content_match = re.search(
            r"\[CONTENT\]\s*([\s\S]+?)(?=\n\[TITLE\]|\Z)",
            block,
        )

        if not title_match or not content_match:
            continue

        title = title_match.group(1).strip()

        tags = [
            item.strip()
            for item in (
                tags_match.group(1) if tags_match else ""
            ).split(",")
            if item.strip()
        ]

        content = content_match.group(1).strip()

        chunks.extend(
            _chunk_text(title, tags, content, path.name)
        )

    return chunks


class TextRAG:
    """Tìm kiếm kiến thức TXT bằng từ khóa, cụm từ và từ đồng nghĩa."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.chunks: list[Chunk] = []
        self.reload()

    def reload(self) -> None:
        self.chunks = parse_txt(self.path)

    def retrieve(
        self,
        query: str,
        top_k: int = 4,
    ) -> list[dict]:
        if not query.strip() or top_k <= 0:
            return []

        query_tokens = set(tokens(query))
        expanded_query = _expanded_tokens(query)

        if not query_tokens:
            return []

        scored: list[tuple[float, Chunk]] = []

        for chunk in self.chunks:
            title_tokens = set(tokens(chunk.title))
            tag_tokens = set(tokens(" ".join(chunk.tags)))
            body_tokens = set(tokens(chunk.content))

            # Từ khóa gốc có trọng số cao hơn từ được mở rộng.
            score = 0.0
            score += len(query_tokens & title_tokens) * 5.0
            score += len(query_tokens & tag_tokens) * 3.0
            score += len(query_tokens & body_tokens) * 1.2

            extra_tokens = expanded_query - query_tokens
            score += len(extra_tokens & title_tokens) * 2.5
            score += len(extra_tokens & tag_tokens) * 2.0
            score += len(extra_tokens & body_tokens) * 0.6

            # Ưu tiên các thẻ và tiêu đề khớp cụm từ đầy đủ.
            for tag in chunk.tags:
                if _phrase_present(tag, query):
                    score += 4.0

            if _phrase_present(chunk.title, query):
                score += 7.0

            # Thưởng cho truy vấn có cụm từ khớp với nội dung.
            normalized_query = normalize(query)
            normalized_content = normalize(chunk.content)

            for phrase in (
                "giam can",
                "giam mo",
                "tang can",
                "tang co",
                "thuc don",
                "bua sang",
                "bua trua",
                "bua toi",
                "protein",
                "calories",
                "bmi",
                "bmr",
                "tdee",
            ):
                if (
                    _phrase_present(phrase, normalized_query)
                    and _phrase_present(phrase, normalized_content)
                ):
                    score += 1.5

            # Giảm điểm nhẹ cho nội dung quá dài so với lượng
            # thông tin thực sự khớp, tránh thiên lệch vì độ dài.
            if len(body_tokens) > 250:
                score *= 0.95

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
        titles = list(
            dict.fromkeys(chunk.title for chunk in self.chunks)
        )

        return {
            "source": self.path.name,
            "documents": len(titles),
            "chunks": len(self.chunks),
            "mode": "TXT lexical retrieval with synonyms",
        }
