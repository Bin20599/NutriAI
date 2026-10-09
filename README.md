# NutriAI — bản nâng cấp cloud scaffold

## Có gì trong bản này?
- FastAPI API cho chat, health, hồ sơ và lịch sử hội thoại.
- Kiểm tra Supabase access token qua Auth endpoint; không tin `user_id` do trình duyệt gửi lên.
- Lưu hồ sơ, cuộc trò chuyện và tin nhắn cho người dùng đã xác thực.
- Supabase schema có quan hệ `auth.users`, RLS và pgvector.
- Lớp OpenAI embedding + LLM tùy chọn; khi có OPENAI_API_KEY, chatbot trả lời cả câu hỏi ngoài RAG; khi chưa có key, chatbot giải thích cách cấu hình.
- Script nạp `data/knowledge.txt` vào Supabase pgvector.
- Validation input, giới hạn kích thước tin nhắn và timeout khi gọi API ngoài.

## Chạy local (VS Code / Windows)
```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m backend.server
```
Mở http://127.0.0.1:8000. Để chạy FastAPI riêng: `uvicorn api.index:app --reload` (API này không tự phục vụ thư mục `public`).

### Bật trả lời câu hỏi ngoài RAG khi chạy local
1. Tạo file `.env` trong thư mục `NutriAI-Demo-RAG` (cùng cấp với `requirements.txt`).
2. Thêm `OPENAI_API_KEY=your_api_key_here` và `OPENAI_CHAT_MODEL=gpt-4o-mini`. Có thể sao chép `.env.example` thành `.env` rồi điền key.
3. Cài lại thư viện nếu cần: `pip install -r requirements.txt`.
4. Dừng server bằng `Ctrl+C`, sau đó chạy lại `python -m backend.server`.
5. Thử hỏi `Python là gì?` hoặc `Kể một câu chuyện ngắn`.

Lưu ý: API key của OpenAI cần có quyền sử dụng API và có thể phát sinh phí theo mức sử dụng. Không dán key vào `public/app.js`, không gửi key lên GitHub và không chia sẻ file `.env`. Nếu chưa có key, bản local chỉ có thể trả lời từ RAG TXT và các xử lý tính toán được lập trình sẵn.

## Supabase
1. Tạo project Supabase.
2. Chạy toàn bộ `supabase/schema.sql` trong SQL Editor.
3. Bật Email provider trong Authentication.
4. Cấu hình `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SECRET_KEY` trên môi trường server.
5. Không bao giờ đưa secret/service-role key vào frontend hoặc GitHub.

## Bật LLM + vector RAG
Cấu hình `OPENAI_API_KEY`, `OPENAI_CHAT_MODEL=gpt-4o-mini`, `OPENAI_EMBEDDING_MODEL=text-embedding-3-small`, `EMBEDDING_DIMENSIONS=1536`. Sau đó chạy:
```powershell
python scripts/ingest_knowledge.py
```
Kiểm tra `knowledge_chunks` có embeddings trước khi đánh giá vector search. Script chỉ thêm dữ liệu, không tự xóa chunk cũ.

## Vercel
1. Đẩy nội dung project lên GitHub.
2. Import repo vào Vercel; nếu repo có thư mục cha, đặt Root Directory là `NutriAI-Demo-RAG`.
3. Framework preset: Other.
4. Thêm các biến môi trường Supabase/OpenAI nêu trên, `APP_ENV=production`.
5. Deploy và kiểm tra `/api/health`.

## Giới hạn cần biết trước khi phát hành
Giao diện hiện tại vẫn là guest/local-history. Backend cloud đã có các API yêu cầu access token để đồng bộ dữ liệu cá nhân, nhưng màn hình đăng nhập/đăng ký Supabase Auth chưa được tích hợp vào UI hiện tại. Vì vậy hãy dùng guest mode cho demo; trước khi mở cloud account cho công chúng, cần ghép Supabase Auth UI để gửi `Authorization: Bearer <access_token>`. Không bật `ALLOW_GUEST_MODE=false` trước khi UI đăng nhập hoạt động.
