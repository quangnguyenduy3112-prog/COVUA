"""Bảng chuyển vị (transposition table).

Mỗi mục là một số nguyên đóng gói: điểm, độ sâu, loại cận và nước đi tốt nhất.
Dùng `dict[int, int]` (khóa = mã băm thế cờ) vì số nguyên gọn và không làm chậm
bộ thu gom rác của Python như tuple.

Bảng có hai "thế hệ": khi thế hệ hiện tại đầy, nó trở thành thế hệ cũ và bảng
mới được tạo. Nhờ vậy bộ nhớ luôn bị chặn mà vẫn giữ được thông tin gần nhất.
"""

EXACT = 0   # điểm chính xác
LOWER = 1   # điểm thật >= điểm lưu (nút bị cắt beta)
UPPER = 2   # điểm thật <= điểm lưu (không nước nào vượt alpha)

_SCORE_OFFSET = 1 << 15
_SCORE_MASK = (1 << 16) - 1


def pack(score: int, depth: int, flag: int, move: int) -> int:
    """score trong [-32767, 32767], depth 0..127, flag 0..2, move < 2^15."""
    return (score + _SCORE_OFFSET) | (depth << 16) | (flag << 23) | (move << 25)


def unpack(value: int) -> tuple[int, int, int, int]:
    """Trả về (score, depth, flag, move)."""
    return ((value & _SCORE_MASK) - _SCORE_OFFSET, (value >> 16) & 127,
            (value >> 23) & 3, value >> 25)


class TranspositionTable:
    __slots__ = ("limit", "current", "previous")

    def __init__(self, limit: int = 300_000) -> None:
        self.limit = limit
        self.current: dict[int, int] = {}
        self.previous: dict[int, int] = {}

    def get(self, key: int) -> int | None:
        value = self.current.get(key)
        if value is None:
            value = self.previous.get(key)
        return value

    def put(self, key: int, value: int) -> None:
        current = self.current
        current[key] = value
        if len(current) > self.limit:
            self.previous = current
            self.current = {}

    def clear(self) -> None:
        self.current = {}
        self.previous = {}
