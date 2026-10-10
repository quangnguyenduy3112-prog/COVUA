# Khai báo sử dụng AI

> Bản nháp do Claude Code soạn theo đúng những gì đã làm. Nhóm cần đọc lại, chỉnh sửa cho đúng thực tế của nhóm trước khi nộp.

- Công cụ đã dùng: Claude Code (mô hình Claude Opus của Anthropic), chạy trong ứng dụng Claude trên máy của nhóm.
- Mục đích sử dụng:
  - Đọc toàn bộ repo mẫu và README để phân tích yêu cầu, cơ chế đồng hồ và luật hòa của hệ thống chấm.
  - Lập kế hoạch thiết kế bot và viết mã nguồn trong `student/`:
    - `bot.py`: điểm vào `StudentBot`, cơ chế dự phòng để luôn trả về nước hợp lệ.
    - `time_manager.py`: phân bổ thời gian theo quỹ giờ còn lại và độ trễ tối thiểu mỗi nước.
    - `evaluation.py`: hàm lượng giá tự thiết kế tay (giá trị quân, bảng điểm theo ô sinh bằng công thức, cấu trúc tốt, độ linh hoạt, an toàn vua, tàn cuộc).
    - `search.py`: tìm kiếm alpha-beta trên `chess.Board` (lõi dự phòng).
    - `fastboard.py`, `fastsearch.py`: bàn cờ bitboard tự viết và bộ tìm kiếm chính (đào sâu lặp, PVS, bảng chuyển vị, quiescence, null-move, LMR, futility, SEE, killer/history).
    - `tt.py`: bảng chuyển vị.
  - Viết công cụ kiểm thử dùng riêng trên máy (không nằm trong bài nộp): đấu bot với bot theo đúng luật đồng hồ, perft đối chiếu bàn cờ tự viết với thư viện `chess`, kiểm tra import và dung lượng `student/`.
  - Chạy thử nghiệm đối kháng giữa các phiên bản để quyết định giữ hay bỏ từng kỹ thuật.
- Những gì KHÔNG dùng: không dùng mô hình học máy, dữ liệu đã huấn luyện, sách khai cuộc, cơ sở dữ liệu tàn cuộc hay chương trình cờ vua bên ngoài trong bot. Các hệ số lượng giá do đặt tay, không tinh chỉnh tự động từ dữ liệu ván đấu.
- Trách nhiệm của nhóm: các thành viên đọc, hiểu và có thể giải thích toàn bộ mã nguồn trong `student/`.
