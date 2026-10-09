# NutriAI — hướng phát triển bản thi

## Giai đoạn 1 — Demo hiện tại

- Frontend HTML/CSS/JavaScript, chạy ngay trong VS Code.
- Backend Python không cần cài thư viện cho bản local demo.
- RAG đọc trực tiếp `data/knowledge.txt`.
- Có hồ sơ, tính BMI/BMR/TDEE, lịch sử phiên chat trong bộ nhớ trình duyệt.
- Có lớp kết nối Supabase tùy chọn.

## Giai đoạn 2 — GitHub + Vercel

Bản thư mục đã có sẵn `api/index.py`, `requirements.txt` và `vercel.json` để chuyển backend sang FastAPI trên Vercel. Frontend vẫn giữ tách riêng nên không cần viết lại giao diện.

## Giai đoạn 3 — Supabase + RAG chính thức

- Lưu người dùng, hội thoại, tin nhắn và tài liệu vào PostgreSQL.
- Bật pgvector cho `knowledge_chunks.embedding`.
- Sinh embedding cho các đoạn TXT rồi lưu vào Supabase.
- Tìm kiếm theo vector similarity hoặc hybrid search.
- Sau bước retrieval mới đưa context vào LLM để sinh câu trả lời.
- Thêm RLS/auth và khóa server-side cho các thao tác nhạy cảm.

## Giai đoạn 4 — Bản đem đi thi

Tách thành các lớp: giao diện, API, RAG/retrieval, database và AI generation. Khi thay TXT retrieval bằng pgvector + LLM, contract `/api/chat` và giao diện không cần đổi.
