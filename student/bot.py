"""Điểm vào bắt buộc của bài nộp: lớp `StudentBot`.

Nguyên tắc số một: KHÔNG BAO GIỜ thua vì lỗi kỹ thuật. Mọi nhánh của
`choose_move()` đều trả về một nước thuộc `board.legal_moves`, kể cả khi
phần search gặp lỗi bất ngờ.
"""
import time

import chess

from chesslab_sdk import BotConfig, SearchContext

from . import fastboard
from .fastsearch import FastSearcher
from .search import Searcher
from .time_manager import TimeManager

_VALUE = (0, 1, 3, 3, 5, 9, 0)


def _emergency_move(board: chess.Board, legal: list[chess.Move]) -> chess.Move:
    """Chọn nước không cần search: chiếu hết ngay > ăn quân lời nhất > nước đầu tiên."""
    best = legal[0]
    best_score = -100
    for move in legal:
        score = 0
        victim = board.piece_type_at(move.to_square)
        if victim and board.color_at(move.to_square) != board.turn:
            score = 10 * _VALUE[victim] - _VALUE[board.piece_type_at(move.from_square) or 0]
        if move.promotion == chess.QUEEN:
            score += 80
        if score > best_score:
            best, best_score = move, score
    return best


class StudentBot:
    """The only class imported by the local runner and official grader."""

    def __init__(self, config: BotConfig) -> None:
        self.config = config
        self.timer = TimeManager(config.initial_time_ms)
        self.searcher = Searcher()      # lõi A: python-chess, dùng khi lõi B có vấn đề
        self.fast = None                # lõi B: bàn cờ tự viết, nhanh (bộ search chính)
        self.use_fast = False
        try:
            # Nguồn ngẫu nhiên duy nhất của bot (khóa Zobrist) được khởi tạo từ config.seed.
            fastboard.init_zobrist(config.seed)
            self.fast = FastSearcher()
            self.use_fast = True
        except Exception:  # noqa: BLE001 - khởi tạo lõi B lỗi thì vẫn chơi được bằng lõi A
            self.use_fast = False

    def choose_move(self, board: chess.Board, context: SearchContext) -> chess.Move:
        started = time.perf_counter()
        legal = list(board.legal_moves)
        if len(legal) == 1:
            try:                         # vẫn báo cho bộ quản lý giờ để nó đo độ trễ của hệ thống
                self.timer.allocate(context.time_remaining_ms, context.ply)
                self.timer.record(time.perf_counter() - started)
            except Exception:  # noqa: BLE001
                pass
            return legal[0]
        root_fen = board.fen()
        move = None
        soft = hard = 0.05
        try:
            soft, hard = self.timer.allocate(context.time_remaining_ms, context.ply)
        except Exception:  # noqa: BLE001
            pass
        if self.use_fast:
            try:
                move = self.fast.think(board, soft, hard, context.ply)
            except Exception:  # noqa: BLE001 - lõi B lỗi/không khớp: bỏ hẳn, dùng lõi A tới hết ván
                self.use_fast = False
                self.fast = None         # giải phóng bộ nhớ của lõi B
                move = None
        if move is None or move not in legal:
            try:
                if board.fen() != root_fen:
                    board = chess.Board(root_fen, chess960=True)
                used = time.perf_counter() - started
                move = self.searcher.think(board, max(0.02, soft - used), max(0.03, hard - used),
                                           context.ply)
            except Exception:  # noqa: BLE001 - lỗi nào cũng phải trả về được một nước hợp lệ
                move = None
        try:
            self.timer.record(time.perf_counter() - started)
        except Exception:  # noqa: BLE001
            pass
        if move is None or move not in legal:
            if board.fen() != root_fen:      # search để lại bàn cờ sai: dựng lại từ FEN gốc
                board = chess.Board(root_fen, chess960=True)
                legal = list(board.legal_moves)
            move = _emergency_move(board, legal)
        return move
