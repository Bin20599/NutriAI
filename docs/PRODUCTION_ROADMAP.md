# NutriAI — checklist triển khai

## Đã bổ sung trong mã nguồn
- FastAPI API, xác minh Supabase access token và giới hạn dữ liệu theo user đã xác thực.
- Supabase schema với quan hệ `auth.users`, RLS, chỉ mục và hàm pgvector similarity.
- OpenAI embeddings + generation tùy chọn; fallback về TXT RAG.
- Script nạp knowledge TXT vào vector store.
- Environment example, gitignore, README và cấu hình Vercel.

## Việc cần làm trong dashboard
1. Tạo Supabase project và chạy `supabase/schema.sql`.
2. Tạo OpenAI API key nếu muốn dùng LLM/embeddings; chi phí theo mức sử dụng.
3. Đẩy code lên GitHub, import vào Vercel và cấu hình environment variables.
4. Tích hợp màn hình đăng nhập/đăng ký Supabase Auth vào frontend, gửi access token tới API.
5. Chạy ingestion, kiểm tra vector và thử câu hỏi có nguồn trích dẫn.
6. Kiểm thử quyền truy cập bằng hai tài khoản khác nhau, giới hạn request, xác minh email, backup và chính sách riêng tư.

## Trạng thái trung thực
Đây là bộ mã cloud-ready scaffold, chưa phải triển khai production đã được xác nhận. Chưa thể tạo project, cấu hình secret hoặc deploy thay bạn vì cần quyền truy cập tài khoản Supabase/Vercel. UI đăng nhập chưa được ghép vào giao diện hiện tại.
