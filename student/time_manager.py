"""Phân bổ thời gian cho từng nước đi.

Đặc điểm đồng hồ của hệ thống:
- Không cộng giờ sau mỗi nước; ván dài tối đa 300 ply (150 nước mỗi bên).
- Mỗi nước bị trừ ít nhất khoảng 500-1000 ms dù bot trả lời ngay
  (chi phí = max(thời gian nghĩ, độ trễ tối thiểu)).

Từ đó:
- Nghĩ dưới ~0.42 s gần như "miễn phí" => luôn dùng hết phần này.
- Phải giữ lại quỹ dự trữ = (số nước tối đa còn lại) x (chi phí sàn mỗi nước),
  nếu không sẽ hết giờ ở cuối một ván kéo dài dù đang thắng.
- Phần thời gian vượt quỹ dự trữ được chia dần cho các nước sắp tới.
"""

import math

MAX_PLIES = 300
FREE_MS = 420.0          # nghĩ tới mức này không tốn thêm giờ (sàn 500 ms trừ hao truyền tin)
DEFAULT_FLOOR_MS = 850.0  # ước lượng thận trọng cho chi phí sàn mỗi nước (trung bình ~750 ms)


class TimeManager:
    def __init__(self, initial_time_ms: int) -> None:
        self.initial_ms = max(1, int(initial_time_ms))
        self.floor_ms = DEFAULT_FLOOR_MS
        self._samples = 0
        self._sample_sum = 0.0
        self._prev_remaining: int | None = None
        self._prev_think_ms = 0.0

    def _calibrate(self, remaining_ms: int) -> None:
        """Ước lượng chi phí sàn thật của hệ thống chấm từ các lượt trước của chính mình."""
        if self._prev_remaining is None:
            return
        cost = self._prev_remaining - remaining_ms
        if cost <= 0 or cost > 60_000:
            return
        if self._prev_think_ms <= FREE_MS + 30:
            pass        # lượt trước nghĩ ngắn => chi phí bị trừ chính là độ trễ sàn
        elif self._prev_think_ms > 1000 and cost - self._prev_think_ms >= 250:
            pass        # nghĩ lâu mà vẫn bị trừ dôi ra nhiều => độ trễ sàn lớn hơn giả định
        else:
            return
        self._samples += 1
        self._sample_sum += cost
        n = self._samples
        mean = self._sample_sum / n
        if n >= 3 and mean > DEFAULT_FLOOR_MS + 100.0:
            # Hệ thống chấm trừ nhiều hơn giả định: tăng dự trữ ngay cho an toàn.
            self.floor_ms = min(3000.0, mean * 1.08)
        elif n >= 12:
            # Chỉ hạ dự trữ khi đã có nhiều mẫu, và dùng cận trên của trung bình
            # (độ lệch chuẩn của độ trễ ngẫu nhiên 500-1000 ms khoảng 150 ms).
            upper = mean + 2.5 * 150.0 / math.sqrt(n) + 20.0
            self.floor_ms = max(560.0, min(DEFAULT_FLOOR_MS, upper))

    def allocate(self, remaining_ms: int, ply: int) -> tuple[float, float]:
        """Trả về (soft, hard) tính bằng giây.

        soft: sau mốc này không bắt đầu vòng lặp sâu hơn.
        hard: mốc buộc phải dừng search ngay.
        """
        self._calibrate(remaining_ms)
        self._prev_remaining = remaining_ms

        moves_left = max(1, (MAX_PLIES - ply + 1) // 2)
        margin = 4000.0 + 0.015 * self.initial_ms
        reserve = moves_left * self.floor_ms + margin
        pool = remaining_ms - reserve

        free = FREE_MS
        if pool > 0:
            own_moves_played = ply // 2
            horizon = max(16.0, 40.0 - 0.4 * own_moves_played)
            horizon = min(horizon, float(moves_left))
            extra = pool / horizon
            soft = free + extra
            hard = free + min(3.0 * extra, 0.35 * pool)
        else:
            soft = hard = free

        # Chốt an toàn khi đồng hồ gần cạn: không bao giờ dùng quá một phần nhỏ quỹ còn lại.
        cap = remaining_ms * 0.08 if remaining_ms < 6000 else remaining_ms * 0.25
        hard = max(10.0, min(hard, cap))
        soft = min(soft, hard)
        return soft / 1000.0, hard / 1000.0

    def record(self, think_seconds: float) -> None:
        self._prev_think_ms = think_seconds * 1000.0
