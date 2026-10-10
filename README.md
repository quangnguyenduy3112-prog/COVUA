# ChessLab

Đây là template repo để các bạn sử dụng cho bài tập lớn (BTL) môn **Biểu diễn tri thức và tìm kiếm nâng cao**.

Nhiệm vụ của các bạn trong BTL này là xây dựng bot chơi Cờ vua bằng các kỹ thuật search đã học.

Các bạn nhớ đọc kỹ đầy đủ yêu cầu về BTL dưới đây để hoàn thành chính xác nhất nhé.

## 1. Mục tiêu

Mục tiêu của BTL này bao gồm:

- Biểu diễn và duyệt không gian trạng thái của một trò chơi đối kháng.
- Xây dựng hàm kinh nghiệm cho các trạng thái trong trò chơi.
- Cân bằng giữa độ sâu tìm kiếm, chất lượng nước đi và thời gian còn lại, từ đó lựa chọn được chiến lược search phù hợp nhất.
- Đánh giá được tác dụng của đào sâu lặp, thứ tự nước đi, bảng chuyển vị, ... trong bài toán này.

> **Chỉ sử dụng các kỹ thuật search. Không sử dụng học máy, mô hình đã huấn luyện, chương trình cờ vua bên ngoài hoặc các dữ liệu nước đi có sẵn**.

## 2. Tổng quan bài tập lớn

Mỗi nhóm sẽ xây dựng phần logic cho con bot chơi Cờ vua. Sau đó, bot của các nhóm sẽ thi đấu đối kháng với nhau, và kết quả của các trận sẽ được tổng hợp lại để tính ra điểm số của nhóm.

### 2.1. Thể thức thi đấu

- Các nhóm thi đấu vòng tròn một lượt, mỗi cặp đấu sẽ đấu với nhau tổng cộng 2 ván (đổi bên).
- Mỗi vòng đấu sử dụng chung một thế cờ và cùng mức thời gian (toàn bộ đều được lựa chọn ngẫu nhiên) cho tất cả các cặp trong vòng. Lịch đấu, màu quân, thế cờ và thời gian được sinh sau khi toàn bộ bài nộp đã được khóa. Lưu ý về thế cờ ngẫu nhiên được đề cập trong mục 2.2.
- **Mỗi ván thắng trong một cặp đấu** được 1 điểm, hòa được 0.5 điểm và thua được 0 điểm.
- Toàn bộ nước đi sẽ được lưu lại để phục vụ xem lại ván đấu và phúc khảo nếu các bạn muốn.

### 2.2. Luật cờ vua và Thể thức Chess960

Đối với các bạn chưa biết chơi cờ vua, các bạn có thể đọc qua luật chơi cờ vua ở [link này](https://www.chess.com/vi/cach-choi-co-vua) nhé. **Lưu ý là trong phạm vi BTL này, các nước đi đặc biệt như nhập thành, phong cấp hay bắt tốt qua đường đều được chấp thuận nhé**.

Trong BTL này, khác với cờ vua tiêu chuẩn, vị trí xuất phát của các quân cờ được sắp xếp theo thể thức cờ vua **Chess960**. Hàng quân phía sau được xáo theo một trong 960 thế hợp lệ, trong đó:

- Hai tượng nằm trên hai màu ô khác nhau.
- Vua nằm giữa hai xe.
- Hàng tốt giữ nguyên như cờ vua tiêu chuẩn.
- Các luật còn lại của cờ vua vẫn được giữ nguyên, bao gồm cả luật nhập thành của Chess960.

Mỗi thế cờ được biểu diễn bằng một `chess960_id` từ 0 đến 959. Thư viện `chess` chịu trách nhiệm tạo bàn cờ, sinh nước đi hợp lệ và xử lý luật nhập thành.

### 2.3. Thời gian thi đấu

- Trong một ván đấu, quỹ thời gian cho 2 bên là như nhau, và không được cộng thêm thời gian sau mỗi nước Thời gian thi đấu chính thức được sinh ngẫu nhiên trong khoảng 180–360 giây cho mỗi bên (phần khoảng thời gian này có thể sẽ có thay đổi nhé).
- Khoảng import mã nguồn, khởi tạo bot, search và các xử lý bên trong bot đều được tính vào thời gian của bot (tất nhiên việc khởi tạo bot, import chỉ diễn ra một lần trong ván đấu).
- Nhằm tránh trường hợp bot trả về câu trả lời ngẫu nhiên ngay lập tức, và để cho mỗi nước đi gần giống với thao tác của con người, hệ thống có áp dụng độ trễ tối thiểu 500 ms cho mỗi nước đi. Hiểu đơn giản thì random không thèm nghĩ gì thì đồng hồ vẫn trừ thời gian một ít.
- Bên nào hết thời gian trước đối thủ sẽ coi như thua. Trắng đi trước và thời gian sẽ bắt đầu trước. Các bạn có thể xem qua một vài ván đấu cờ vua online trên [Chess.com](chess.com) hoặc [lichess](lichess.org) để hiểu rõ hơn nhé.

### 2.4. Kết thúc ván đấu

Ván đấu kết thúc theo luật cờ vua thông thường. Bot cũng bị xử thua nếu phát sinh lỗi, dừng bất thường, hết thời gian hoặc trả về một nước đi không hợp lệ.

Các luật hòa do `chess` xử lý gồm bí nước, thiếu quân để checkmate, lặp lại thế cờ liên tục và luật 50/75 nước. Ván đấu cũng được xử hòa nếu nó không kết thúc sau 300 nước đi. Chi tiết xem thêm trong luật cờ vua thi đấu chính thức phía trên.

## 3. Cài đặt và cấu trúc repo

### 3.1. Chuẩn bị môi trường

Các công cụ cần có:

- Git.
- [uv](https://docs.astral.sh/uv/getting-started/installation/).

Không cần cài riêng Python, Node.js hoặc Docker. `uv` sẽ tự tải đúng phiên bản Python và các thư viện đã được khóa trong repo.

Sau khi tạo repo riêng từ template này và clone về máy, mở terminal tại thư mục gốc của repo rồi chạy:

**macOS hoặc Linux**

```bash
./scripts/setup.sh
```

**Windows PowerShell**

```powershell
.\scripts\setup.ps1
```

### 3.2. Cấu trúc repo

```text
.
├── student/          # Mã nguồn bot của nhóm
├── app/              # Chương trình chạy và giao diện thử nghiệm local
├── chesslab_sdk/     # Các kiểu dữ liệu dùng chung với hệ thống chấm
├── tests/            # Kiểm thử công khai
├── ui/               # Mã nguồn giao diện
├── static/built-ui/  # Giao diện đã được build sẵn
├── scripts/          # Các lệnh cài đặt và chạy chương trình
├── team.json         # Thông tin nhóm
├── AI_USAGE.md       # Khai báo việc sử dụng công cụ AI
├── pyproject.toml    # Khai báo môi trường Python
└── uv.lock           # Khóa phiên bản thư viện
```

Phần cần hiện thực nằm trong thư mục `student/`. Các phần còn lại cung cấp chương trình chạy local, giao diện thử nghiệm và các kiểu dữ liệu dùng chung với hệ thống chấm.

### 3.3. Cấu hình mặc định

- Python 3.12.11.
- `chess==1.11.2`.
- `numpy==1.26.4`.
- Giao diện local chạy tại `http://127.0.0.1:8765`.
- Thời gian mặc định khi thử nghiệm là 240 giây cho mỗi bên; có thể chọn từ 10 đến 3.600 giây trên giao diện.
- Giới hạn mỗi ván là 300 nước đi (ply).
- Bot mẫu trong `student/bot.py` luôn trả về nước đi hợp lệ đầu tiên. Bot này chạy được nhưng chưa có chiến lược search.

## 4. Yêu cầu đối với bot

### 4.1. Phạm vi được phép sửa

Chỉ được sửa các phần sau:

```text
student/**
team.json
AI_USAGE.md
```

Không sửa các phần còn lại của repo. Hệ thống chấm chỉ thu mã nguồn trong `student/`, `team.json` và `AI_USAGE.md`.

Có thể thêm, xóa hoặc tổ chức lại các tệp trong `student/`, nhưng phải đảm bảo:

- Giữ tệp `student/bot.py`.
- Giữ lớp `student.bot.StudentBot`.
- Thư mục `student/` chỉ chứa tệp `.py`.
- Không sử dụng liên kết tệp.
- Tổng dung lượng thư mục `student/` không vượt quá 1 MiB.

### 4.2. Giao diện bắt buộc

Hệ thống chấm khởi tạo bot bằng lớp `StudentBot` trong `student/bot.py`:

```python
import chess

from chesslab_sdk import BotConfig, SearchContext


class StudentBot:
    def __init__(self, config: BotConfig) -> None:
        ...

    def choose_move(
        self,
        board: chess.Board,
        context: SearchContext,
    ) -> chess.Move:
        ...
```

Không thay đổi tên lớp, tên hàm hoặc các tham số trên.

`BotConfig` được cấp một lần khi bot được khởi tạo:

| Thuộc tính        | Nội dung                                      |
| ----------------- | --------------------------------------------- |
| `color`           | Màu của bot: `chess.WHITE` hoặc `chess.BLACK` |
| `chess960_id`     | Mã thế Chess960, từ 0 đến 959                 |
| `initial_time_ms` | Tổng thời gian ban đầu, tính bằng mili-giây   |
| `seed`            | Hạt giống ngẫu nhiên cố định cho ván đấu      |

`SearchContext` được cập nhật trước mỗi lượt:

| Thuộc tính                   | Nội dung                      |
| ---------------------------- | ----------------------------- |
| `time_remaining_ms`          | Thời gian còn lại của bot     |
| `opponent_time_remaining_ms` | Thời gian còn lại của đối thủ |
| `ply`                        | Số nửa nước đã đi từ đầu ván  |

`board` là một `chess.Board` hợp lệ và đã bật Chess960. Có thể sử dụng các thao tác như `board.legal_moves`, `board.push()`, `board.pop()`, `board.is_check()`, `board.is_game_over()` và `board.outcome()` trong quá trình search.

Hàm `choose_move()` phải trả về một đối tượng `chess.Move` thuộc `board.legal_moves`. Nếu dùng `push()` để duyệt trạng thái, cần `pop()` tương ứng để không làm sai bàn cờ của nhánh đang xét.

### 4.3. Giới hạn

Các gói được phép import trực tiếp:

```text
abc, array, bisect, chess, collections, contextlib, copy,
dataclasses, decimal, enum, functools, heapq, itertools, json,
math, numpy, operator, random, statistics, student, time,
typing, chesslab_sdk
```

Có thể import tương đối giữa các tệp trong `student/`, ví dụ:

```python
from .search import alpha_beta
```

Không sử dụng mạng, tiến trình con, đa tiến trình, luồng nền, chương trình cờ vua bên ngoài, sách khai cuộc, cơ sở dữ liệu tàn cuộc, mô hình học máy hoặc dữ liệu đã huấn luyện. Nếu bot sử dụng yếu tố ngẫu nhiên, nguồn ngẫu nhiên phải được khởi tạo từ `config.seed`.

### 4.4. Cấu trúc gợi ý

```text
student/
├── __init__.py
├── bot.py           # Điểm vào bắt buộc
├── search.py        # Thuật toán search
├── evaluation.py    # Hàm kinh nghiệm
└── time_manager.py  # Phân bổ thời gian
```

Đây chỉ là cấu trúc gợi ý. Có thể tổ chức lại mã nguồn nếu vẫn giữ đúng giao diện bắt buộc trong `student/bot.py`.

## 5. Kiểm thử và chạy local

### 5.1. Chạy kiểm thử

Chạy toàn bộ kiểm thử công khai bằng lệnh:

```bash
uv run --frozen pytest -q
```

Kết quả đúng phải không có kiểm thử thất bại. Tuy nhiên, vượt qua kiểm thử công khai không đồng nghĩa bot có chiến thuật tốt, luôn trả nước hợp lệ hoặc chắc chắn không hết thời gian.

### 5.2. Chạy chương trình

Sau khi đã cài đặt môi trường, chạy:

**macOS hoặc Linux**

```bash
./scripts/run.sh
```

**Windows PowerShell**

```powershell
.\scripts\run.ps1
```

Giao diện sẽ mở tại `http://127.0.0.1:8765`. Nếu trình duyệt không tự mở, truy cập trực tiếp địa chỉ trên. Nhấn `Ctrl+C` tại cửa sổ lệnh để dừng chương trình.

Giao diện cho phép:

- Chọn màu của bot.
- Chọn tổng thời gian cho mỗi bên.
- Xáo và xem trước một thế Chess960.
- Chơi trực tiếp với bot bằng cách bấm hoặc kéo quân.
- Xem đồng hồ và lịch sử nước đi.
- Dừng ván hiện tại hoặc bắt đầu ván mới.

Trước khi nộp bài, cần thử bot ở cả hai màu, nhiều thế Chess960 và nhiều mức thời gian khác nhau. Mọi nhánh của `choose_move()` phải luôn trả về một nước đi hợp lệ trong thời gian cho phép.

## 6. Sản phẩm và nộp bài

**(PHẦN NÀY CÓ THỂ SẼ CÓ THAY ĐỔI, NÊN CÁC NHÓM CHƯA CẦN LÀM THEO NGAY NHÉ)**

### 6.1. Sản phẩm cần hoàn thành

Mỗi nhóm cần hoàn thành:

- Mã nguồn bot trong thư mục `student/`.
- Thông tin nhóm trong `team.json`.
- Khai báo việc sử dụng công cụ AI trong `AI_USAGE.md`.
- Thẻ Git `submission-final` trỏ tới phiên bản nộp chính thức.

### 6.2. Thông tin nhóm

Điền `team.json` theo mẫu:

```json
{
    "protocol_version": "1.0",
    "team_id": "nhom-01",
    "display_name": "Tên nhóm",
    "members": ["MSSV - Họ và tên", "MSSV - Họ và tên"]
}
```

`team_id` phải trùng với mã nhóm trong danh sách lớp. Không thay đổi `protocol_version`.

Điền `AI_USAGE.md` trung thực, kể cả khi không sử dụng AI. Việc sử dụng AI được phép, nhưng toàn bộ mã nguồn nộp phải được hiểu, giải thích và bảo vệ được.

### 6.3. Nộp bài

1. Tạo một repo riêng tư của nhóm từ template này.
2. Cấp quyền đọc repo cho tài khoản được thông báo.
3. Hoàn thành mã nguồn, thông tin nhóm và khai báo sử dụng AI.
4. Chạy kiểm thử và thử ít nhất một ván hoàn chỉnh trên giao diện.
5. Commit và push toàn bộ thay đổi lên GitHub.
6. Tạo thẻ có chú thích `submission-final` và push thẻ lên GitHub:

```bash
git tag -a submission-final -m "Bản nộp cuối"
git push origin submission-final
```

Hệ thống chấm lấy đúng commit mà thẻ `submission-final` trỏ tới, không lấy các thay đổi mới hơn trên nhánh chính.

Nếu cần cập nhật bài nộp trước hạn, tạo lại thẻ bằng các lệnh:

```bash
git tag -d submission-final
git push origin :refs/tags/submission-final
git tag -a submission-final -m "Bản nộp cuối"
git push origin submission-final
```

Sau thời điểm khóa bài, bài nộp không thể thay đổi.
