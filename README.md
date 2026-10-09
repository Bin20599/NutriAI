# NutriAI Demo — RAG + TXT

Bản demo được làm lại từ `NutriAI-NoInstall`. Giao diện chuyển sang nền trắng kết hợp xanh nhạt, giữ luồng chatbot + hồ sơ sức khỏe nhưng tách rõ phần RAG và kho kiến thức. Mã local và mã deploy dùng chung tầng xử lý để hạn chế phải viết lại khi chuyển lên bản chính thức.

## Điểm nổi bật

- UI responsive, trắng + xanh nhạt, phù hợp trình bày/đem demo.
- RAG đọc từ `data/knowledge.txt`, không hard-code kiến thức vào engine.
- Hiển thị nguồn kiến thức được truy hồi dưới từng câu trả lời.
- Tính BMI và BMR/TDEE theo dữ liệu người dùng nhập.
- Chạy local chỉ với Python 3.x, không cần `pip install` cho bản demo.
- Có sẵn `api/index.py`, `requirements.txt`, `vercel.json` cho bước nâng cấp Vercel/FastAPI.
- Có `supabase/schema.sql` cho PostgreSQL + pgvector và lưu hội thoại.

## Chạy demo trên VS Code

Mở Terminal tại thư mục dự án:

```powershell
python -m backend.server
```

Mở `http://127.0.0.1:8000`.

## Câu hỏi mẫu

- Tôi cao 1m70 nặng 75kg, muốn giảm cân thì nên bắt đầu thế nào?
- Protein có vai trò gì khi giảm cân?
- Gợi ý một bữa sáng cân bằng và dễ chuẩn bị.
- BMI của tôi là bao nhiêu nếu cao 1m70 nặng 75kg?
- BMR và TDEE của tôi khoảng bao nhiêu nếu cao 1m70, nặng 75kg, 22 tuổi?
- Python là gì?

## Quan trọng về chữ “RAG”

Bản demo này là **RAG local dạng lexical retrieval + context grounding**: hệ thống đọc TXT, tìm các đoạn liên quan rồi dùng chúng làm context cho câu trả lời. Nó chưa dùng embedding model/LLM để tránh cài đặt nặng.

Khi làm bản chính thức, có thể giữ nguyên giao diện và API rồi thay lớp retrieval bằng embedding + Supabase pgvector, sau đó nối LLM. Supabase hiện hỗ trợ pgvector cho lưu embedding và similarity search; Vercel có Python runtime và hỗ trợ FastAPI. Xem `docs/PRODUCTION_ROADMAP.md`.
