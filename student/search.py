"""Lõi A: tìm kiếm trên `chess.Board` của python-chess.

Đây là bộ search "an toàn": mọi nước đi đều do python-chess sinh ra nên luôn
hợp lệ với luật Chess960. Nó được dùng làm phương án dự phòng cho lõi nhanh
(`fastsearch.py`) và làm chuẩn đối chiếu khi kiểm thử.

Kỹ thuật: đào sâu lặp (iterative deepening), negamax alpha-beta kiểu PVS,
bảng chuyển vị, tìm kiếm tĩnh (quiescence), null-move, LMR, futility,
killer + history heuristic, phát hiện hòa do lặp thế / 50 nước / giới hạn 300 ply.
"""
import math
import time
from operator import itemgetter

import chess

from .evaluation import MAX_PHASE, TEMPO, full_score, material_pst, move_delta
from .tt import EXACT, LOWER, UPPER, TranspositionTable, pack, unpack

MATE = 30000
MATE_BOUND = 29000      # |điểm| lớn hơn mốc này nghĩa là đã thấy chiếu hết
INF = 32000
MAX_PLY = 96
MAX_GAME_PLIES = 300
CONTEMPT = 12           # coi hòa là hơi xấu để không vội lặp nước với bot yếu hơn
LAZY_MARGIN = 260
QS_MAX_DEPTH = 8

_VAL = (0, 100, 320, 330, 500, 950, 20000)
_M32 = 0xFFFFFFFF
_BB_SQUARES = chess.BB_SQUARES
_first = itemgetter(0)

_LMR = [[0] * 64 for _ in range(64)]
for _d in range(1, 64):
    for _n in range(1, 64):
        _LMR[_d][_n] = int(0.75 + math.log(_d) * math.log(_n) / 2.25)


class SearchTimeout(Exception):
    """Ném ra khi hết thời gian cho phép; search được tháo gỡ về gốc."""


def position_key(board: chess.Board) -> int:
    """Mã băm 64 bit của thế cờ. Bitboard được tách đôi 32 bit để tránh trùng băm của int lớn."""
    w = board.occupied_co[True]
    p, n, b = board.pawns, board.knights, board.bishops
    r, q, k = board.rooks, board.queens, board.kings
    c = board.castling_rights
    return hash((w & _M32, w >> 32, p & _M32, p >> 32, n & _M32, n >> 32, b & _M32, b >> 32,
                 r & _M32, r >> 32, q & _M32, q >> 32, k & _M32, k >> 32,
                 c & _M32, c >> 32, board.turn, board.ep_square))


def move_to_int(move: chess.Move) -> int:
    return move.from_square | (move.to_square << 6) | ((move.promotion or 0) << 12)


def int_to_move(value: int) -> chess.Move:
    return chess.Move(value & 63, (value >> 6) & 63, (value >> 12) or None)


class Searcher:
    def __init__(self) -> None:
        self.tt = TranspositionTable()
        self.history = [[0] * 4096, [0] * 4096]
        self.killers: list[list] = [[None, None] for _ in range(MAX_PLY + 2)]
        self.keys: list[int] = []
        self.nodes = 0
        self.hard_deadline = 0.0
        self.root_ply = 0
        self.board: chess.Board | None = None
        self.iter_best: chess.Move | None = None
        self.depth_reached = 0
        self.score = 0

    # ------------------------------------------------------------------ gốc
    def think(self, board: chess.Board, soft: float, hard: float, game_ply: int) -> chess.Move:
        """Trả về nước tốt nhất tìm được trong giới hạn thời gian (giây)."""
        start = time.perf_counter()
        self.hard_deadline = start + hard
        self.nodes = 0
        self.root_ply = game_ply
        self.board = board
        self.depth_reached = 0
        root_len = len(board.move_stack)

        root_moves = self._ordered_moves(board, None, 0)
        root_moves = [m for _, m in root_moves]
        best_move = root_moves[0]
        if len(root_moves) == 1:
            return best_move

        for table in self.history:
            for i, v in enumerate(table):
                if v:
                    table[i] = v >> 2
        for pair in self.killers:
            pair[0] = pair[1] = None

        # Lịch sử khóa thế cờ từ nước không đảo ngược gần nhất (để phát hiện lặp thế).
        self.keys = self._history_keys(board)
        keys_len = len(self.keys)
        mg, eg, phase = material_pst(board)
        in_check = board.is_check()
        free_mode = hard - soft < 1e-6
        score = 0
        try:
            for depth in range(1, MAX_PLY):
                if depth >= 4:
                    window = 35
                    alpha, beta = max(-INF, score - window), min(INF, score + window)
                else:
                    window = INF
                    alpha, beta = -INF, INF
                while True:
                    self.iter_best = None
                    value = self._root(board, root_moves, depth, alpha, beta, mg, eg, phase,
                                       in_check)
                    if self.iter_best is not None:
                        best_move = self.iter_best
                        root_moves.remove(best_move)
                        root_moves.insert(0, best_move)
                    if value <= alpha and alpha > -INF:
                        window *= 3
                        alpha = max(-INF, value - window)
                    elif value >= beta and beta < INF:
                        window *= 3
                        beta = min(INF, value + window)
                    else:
                        break
                score = value
                self.score = score
                self.depth_reached = depth
                if abs(score) > MATE_BOUND and depth >= MATE - abs(score):
                    break
                elapsed = time.perf_counter() - start
                if not free_mode and elapsed > soft * 0.55:
                    break
        except SearchTimeout:
            if self.iter_best is not None:
                best_move = self.iter_best
        finally:
            while len(board.move_stack) > root_len:
                board.pop()
            del self.keys[keys_len:]
        return best_move

    def _history_keys(self, board: chess.Board) -> list[int]:
        count = min(board.halfmove_clock, len(board.move_stack))
        undone = [board.pop() for _ in range(count)]
        keys = []
        for move in reversed(undone):
            keys.append(position_key(board))
            board.push(move)
        return keys

    def _root(self, board, root_moves, depth, alpha, beta, mg, eg, phase, in_check) -> int:
        key = position_key(board)
        keys = self.keys
        best = -INF
        original_alpha = alpha
        best_move = None
        for index, move in enumerate(root_moves):
            dmg, deg, dph = move_delta(board, move)
            keys.append(key)
            board.push(move)
            gives_check = board.is_check()
            if index == 0:
                value = -self._search(board, depth - 1, -beta, -alpha, 1,
                                      mg + dmg, eg + deg, phase + dph, gives_check, True)
            else:
                value = -self._search(board, depth - 1, -alpha - 1, -alpha, 1,
                                      mg + dmg, eg + deg, phase + dph, gives_check, True)
                if value > alpha:
                    value = -self._search(board, depth - 1, -beta, -alpha, 1,
                                          mg + dmg, eg + deg, phase + dph, gives_check, True)
            board.pop()
            keys.pop()
            if value > best:
                best = value
                best_move = move
                if value > alpha:
                    alpha = value
                    self.iter_best = move
                    if value >= beta:
                        break
        if best_move is not None:
            flag = LOWER if best >= beta else (UPPER if best <= original_alpha else EXACT)
            self.tt.put(key, pack(best, depth, flag, move_to_int(best_move)))
        return best

    # ------------------------------------------------------------- negamax
    def _search(self, board, depth, alpha, beta, ply, mg, eg, phase, in_check, can_null) -> int:
        self.nodes += 1
        if not self.nodes & 63 and time.perf_counter() > self.hard_deadline:
            raise SearchTimeout
        if in_check:
            depth += 1
        if depth <= 0:
            return self._quiesce(board, alpha, beta, ply, mg, eg, phase, in_check, 0)

        key = position_key(board)
        keys = self.keys
        # --- hòa: 50 nước, giới hạn ply của ván, lặp thế ---
        hmc = board.halfmove_clock
        draw = -CONTEMPT if not ply & 1 else CONTEMPT
        # Hệ thống xử hòa ngay khi bên tới lượt CÓ THỂ đòi hòa 50 nước (đồng hồ nửa nước >= 99).
        if hmc >= 99 or self.root_ply + ply >= MAX_GAME_PLIES:
            if in_check and not any(board.generate_legal_moves()):
                return -MATE + ply
            return draw
        if hmc >= 4 and key in keys[max(0, len(keys) - hmc):]:
            return draw
        if ply >= MAX_PLY:
            return full_score(board, mg, eg, phase)

        # --- cắt tỉa theo khoảng cách chiếu hết ---
        if alpha < -MATE + ply:
            alpha = -MATE + ply
        if beta > MATE - ply - 1:
            beta = MATE - ply - 1
        if alpha >= beta:
            return alpha
        is_pv = beta - alpha > 1

        # --- bảng chuyển vị ---
        tt_move = None
        entry = self.tt.get(key)
        if entry is not None:
            tt_score, tt_depth, tt_flag, tt_int = unpack(entry)
            if tt_int:
                tt_move = int_to_move(tt_int)
            if tt_depth >= depth and not is_pv:
                if tt_score > MATE_BOUND:
                    tt_score -= ply
                elif tt_score < -MATE_BOUND:
                    tt_score += ply
                if (tt_flag == EXACT or (tt_flag == LOWER and tt_score >= beta)
                        or (tt_flag == UPPER and tt_score <= alpha)):
                    return tt_score

        turn = board.turn
        static = -INF
        if not in_check:
            static = full_score(board, mg, eg, phase)
            if not is_pv and abs(beta) < MATE_BOUND:
                # reverse futility: đang hơn quá xa beta ở độ sâu nông => cắt
                if depth <= 4 and static - 95 * depth >= beta:
                    return static
                # null-move: nhường lượt mà vẫn >= beta => thế cờ đủ tốt để cắt
                if (can_null and depth >= 3 and static >= beta
                        and board.occupied_co[turn] & ~(board.pawns | board.kings)):
                    reduction = 3 + depth // 5
                    keys.append(key)
                    board.push(chess.Move.null())
                    value = -self._search(board, depth - 1 - reduction, -beta, -beta + 1,
                                          ply + 1, mg, eg, phase, False, False)
                    board.pop()
                    keys.pop()
                    if value >= beta:
                        return beta if value > MATE_BOUND else value

        occ_them = board.occupied_co[not turn]
        history = self.history[turn]
        killers = self.killers[ply]
        best = -INF
        best_move = None
        original_alpha = alpha
        legal = 0
        searched = 0
        quiets_tried = []

        for stage in (0, 1):
            if stage == 0:
                if tt_move is None or not board.is_legal(tt_move):
                    tt_move = None
                    continue
                moves = ((0, tt_move),)
            else:
                moves = self._ordered_moves(board, tt_move, ply)
            for _, move in moves:
                legal += 1
                to_mask = _BB_SQUARES[move.to_square]
                quiet = not (to_mask & occ_them) and not move.promotion
                if quiet and move.to_square == board.ep_square and board.pawns & _BB_SQUARES[move.from_square]:
                    quiet = False
                dmg, deg, dph = move_delta(board, move)
                keys.append(key)
                board.push(move)
                gives_check = board.is_check()

                if (quiet and searched and not in_check and not gives_check and not is_pv
                        and best > -MATE_BOUND):
                    # futility / late-move pruning ở độ sâu nông
                    if (depth <= 3 and static + 90 * depth + 70 <= alpha) \
                            or (depth <= 3 and searched >= 5 + 3 * depth * depth):
                        board.pop()
                        keys.pop()
                        continue

                new_depth = depth - 1
                if searched == 0:
                    value = -self._search(board, new_depth, -beta, -alpha, ply + 1,
                                          mg + dmg, eg + deg, phase + dph, gives_check, True)
                else:
                    reduction = 0
                    if depth >= 3 and searched >= 3 and quiet and not in_check and not gives_check:
                        reduction = _LMR[depth if depth < 64 else 63][searched if searched < 64 else 63]
                        if is_pv and reduction:
                            reduction -= 1
                        if reduction > new_depth - 1:
                            reduction = max(0, new_depth - 1)
                    value = -self._search(board, new_depth - reduction, -alpha - 1, -alpha, ply + 1,
                                          mg + dmg, eg + deg, phase + dph, gives_check, True)
                    if value > alpha and reduction:
                        value = -self._search(board, new_depth, -alpha - 1, -alpha, ply + 1,
                                              mg + dmg, eg + deg, phase + dph, gives_check, True)
                    if alpha < value < beta:
                        value = -self._search(board, new_depth, -beta, -alpha, ply + 1,
                                              mg + dmg, eg + deg, phase + dph, gives_check, True)
                board.pop()
                keys.pop()
                searched += 1

                if value > best:
                    best = value
                    best_move = move
                    if value > alpha:
                        alpha = value
                        if value >= beta:
                            if quiet:
                                if killers[0] != move:
                                    killers[1] = killers[0]
                                    killers[0] = move
                                bonus = depth * depth
                                index = move.from_square | (move.to_square << 6)
                                history[index] += bonus
                                if history[index] > 1_000_000:
                                    for i in range(4096):
                                        history[i] >>= 1
                                for other in quiets_tried:
                                    history[other] -= bonus
                            break
                if quiet:
                    quiets_tried.append(move.from_square | (move.to_square << 6))
            else:
                continue
            break

        if legal == 0:
            return -MATE + ply if in_check else draw
        if best == -INF:
            # mọi nước đều bị cắt tỉa: trả về cận an toàn
            best = alpha
        flag = LOWER if best >= beta else (UPPER if best <= original_alpha else EXACT)
        stored = best
        if stored > MATE_BOUND:
            stored += ply
        elif stored < -MATE_BOUND:
            stored -= ply
        self.tt.put(key, pack(stored, depth if depth < 127 else 127, flag,
                              move_to_int(best_move) if best_move else 0))
        return best

    def _ordered_moves(self, board: chess.Board, skip, ply: int) -> list:
        """Sinh nước hợp lệ kèm điểm ưu tiên: ăn quân (MVV-LVA) > phong hậu > killer > history."""
        turn = board.turn
        occ_them = board.occupied_co[not turn]
        history = self.history[turn]
        killer1, killer2 = self.killers[ply]
        piece_type_at = board.piece_type_at
        ep = board.ep_square
        scored = []
        for move in board.generate_legal_moves():
            if move == skip:
                continue
            to = move.to_square
            if occ_them & _BB_SQUARES[to]:
                value = 2_000_000 + 16 * _VAL[piece_type_at(to)] - _VAL[piece_type_at(move.from_square)]
                if move.promotion:
                    value += _VAL[move.promotion]
            elif move.promotion:
                value = 1_900_000 + _VAL[move.promotion]
            elif to == ep and piece_type_at(move.from_square) == 1:
                value = 2_000_000 + 1500
            elif move == killer1:
                value = 1_500_000
            elif move == killer2:
                value = 1_400_000
            else:
                value = history[move.from_square | (to << 6)]
            scored.append((value, move))
        scored.sort(key=_first, reverse=True)
        return scored

    # -------------------------------------------------------- quiescence
    def _quiesce(self, board, alpha, beta, ply, mg, eg, phase, in_check, qdepth) -> int:
        """Chỉ xét nước ăn quân/phong hậu (hoặc mọi nước thoát chiếu) để lá search "yên tĩnh"."""
        self.nodes += 1
        if not self.nodes & 63 and time.perf_counter() > self.hard_deadline:
            raise SearchTimeout
        turn = board.turn
        if in_check:
            stand = -INF
            best = -INF
            moves = list(board.generate_legal_moves())
            if not moves:
                return -MATE + ply
            if ply >= MAX_PLY or qdepth >= QS_MAX_DEPTH:
                return full_score(board, mg, eg, phase)
        else:
            ph = phase if phase < MAX_PHASE else MAX_PHASE
            quick = mg * ph + eg * (MAX_PHASE - ph)
            if not turn:
                quick = -quick
            quick = (quick // MAX_PHASE if quick >= 0 else -(-quick // MAX_PHASE)) + TEMPO
            if quick - LAZY_MARGIN >= beta:
                return quick
            if quick + LAZY_MARGIN <= alpha:
                stand = quick
            else:
                stand = full_score(board, mg, eg, phase)
                if stand >= beta:
                    return stand
            if stand > alpha:
                alpha = stand
            if ply >= MAX_PLY or qdepth >= QS_MAX_DEPTH:
                return stand
            best = stand
            moves = list(board.generate_legal_captures())
            pawns_7th = board.pawns & board.occupied_co[turn] & \
                (chess.BB_RANK_7 if turn else chess.BB_RANK_2)
            if pawns_7th:
                for move in board.generate_legal_moves(
                        pawns_7th, (chess.BB_RANK_8 if turn else chess.BB_RANK_1) & ~board.occupied):
                    if move.promotion == chess.QUEEN:
                        moves.append(move)

        piece_type_at = board.piece_type_at
        if len(moves) > 1:
            scored = []
            for move in moves:
                victim = piece_type_at(move.to_square)
                value = 16 * _VAL[victim] if victim else 0
                value -= _VAL[piece_type_at(move.from_square)]
                if move.promotion:
                    value += 8000
                scored.append((value, move))
            scored.sort(key=_first, reverse=True)
            moves = [m for _, m in scored]

        occ_them = board.occupied_co[not turn]
        enemy_pawns = board.pawns & occ_them
        pawn_attacks = chess.BB_PAWN_ATTACKS[turn]
        for move in moves:
            if not in_check:
                to = move.to_square
                victim = piece_type_at(to)
                gain = _VAL[victim] if victim else 100
                if move.promotion:
                    gain += 850
                elif stand + gain + 160 <= alpha:
                    continue                      # delta pruning: ăn cũng không cứu nổi alpha
                elif _VAL[piece_type_at(move.from_square)] > gain + 50 and pawn_attacks[to] & enemy_pawns:
                    continue                      # quân đắt ăn quân rẻ có tốt bảo vệ: lỗ rõ ràng
            dmg, deg, dph = move_delta(board, move)
            board.push(move)
            value = -self._quiesce(board, -beta, -alpha, ply + 1, mg + dmg, eg + deg, phase + dph,
                                   board.is_check(), qdepth + 1)
            board.pop()
            if value > best:
                best = value
                if value > alpha:
                    alpha = value
                    if value >= beta:
                        break
        return best
