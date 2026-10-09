from __future__ import annotations
import os, re, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend import db
from backend.production_rag import embed_texts

def parse_file(path):
    text = path.read_text(encoding="utf-8-sig")
    docs = []
    for block in re.split(r"\n(?=\[TITLE\])", text):
        title = re.search(r"\[TITLE\]\s*(.+)", block)
        tags = re.search(r"\[TAGS\]\s*(.+)", block)
        content = re.search(r"\[CONTENT\]\s*([\s\S]+?)(?=\n\[TITLE\]|\Z)", block)
        if not title or not content:
            continue
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", content.group(1).strip()) if p.strip()]
        buf = ""
        for p in paragraphs:
            if buf and len(buf) + len(p) > 900:
                docs.append({"title":title.group(1).strip(), "tags":tags.group(1).strip() if tags else "",
                             "content":buf})
                buf = p
            else:
                buf = (buf + "\n\n" + p).strip()
        if buf:
            docs.append({"title":title.group(1).strip(), "tags":tags.group(1).strip() if tags else "",
                         "content":buf})
    return docs

def main():
    if not db.configured():
        raise SystemExit("Thiếu SUPABASE_URL hoặc SUPABASE_SECRET_KEY.")
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("Thiếu OPENAI_API_KEY.")
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "knowledge.txt"
    docs = parse_file(path)
    print(f"Đã chia thành {len(docs)} đoạn.")
    for start in range(0, len(docs), 40):
        batch = docs[start:start+40]
        vectors = embed_texts([f"{x['title']}\nTags: {x['tags']}\n{x['content']}" for x in batch])
        rows = [{"title":x["title"], "source":path.name, "chunk_text":x["content"],
                 "embedding":v, "metadata":{"tags":x["tags"],"source":path.name}}
                for x,v in zip(batch,vectors)]
        db.insert_many("knowledge_chunks", rows)
        print(f"Đã nạp {min(start+len(batch),len(docs))}/{len(docs)}.")
    print("Hoàn tất. Script append-only: xóa/sao lưu chunk cũ trước khi import lại.")
if __name__ == "__main__":
    main()
