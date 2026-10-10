"""Bộ tìm kiếm chính, chạy trên lõi B (`FastBoard`).

Thuật toán: đào sâu lặp + negamax alpha-beta kiểu PVS (principal variation
search) với cửa sổ kỳ vọng (aspiration window), cùng các kỹ thuật:

- bảng chuyển vị (lưu điểm, độ sâu, loại cận, nước tốt nhất);
- sinh nước theo giai đoạn: nước từ bảng chuyển vị -> ăn quân tốt (MVV-LVA, SEE) ->
  killer/countermove -> nước lặng xếp theo history -> ăn quân lỗ; nút bị cắt sớm
  không phải sinh nước lặng;
- null-move pruning, reverse futility, futility, late-move pruning, LMR;
- mở rộng khi bị chiếu; cắt theo khoảng cách chiếu hết;
- tìm kiếm tĩnh (quiescence) trên nước ăn quân/phong hậu, có delta pruning;
- hòa do lặp thế, luật 50 nước và giới hạn 300 ply của hệ thống.
"""
import math
import time

import chess

from .evaluation import MAX_PHASE, TEMPO, endgame_adjust, positional
from .fastboard import LINE, SEE_VALUE, FastBoard
from .tt import EXACT, LOWER, UPPER, TranspositionTable, pack, unpack

MATE = 30000
MATE_BOUND = 29000
INF = 32000
MAX_PLY = 96
MAX_GAME_PLIES = 300
CONTEMPT = 12
LAZY_MARGIN = 260
QS_MAX_DEPTH = 10
EVAL_CACHE_LIMIT = 250_000

_SQ = chess.BB_SQUARES
_PATT = (chess.BB_PAWN_ATTACKS[chess.WHITE], chess.BB_PAWN_ATTACKS[chess.BLACK])

# Giá trị quân theo mã quân, dùng cho xếp thứ tự và cắt tỉa ở quiescence.
_VALUE = (0, 100, 320, 330, 500, 950, 20000, 100, 320, 330, 500, 950, 20000)
# _MVV_LVA[nạn nhân][kẻ ăn]: ưu tiên ăn quân to bằng quân nhỏ (vua ăn thì xếp sau cùng).
_ATTACKER_COST = (0, 10, 32, 33, 50, 95, 100, 10, 32, 33, 50, 95, 100)
_MVV_LVA = [[2000 + (16 * _VALUE[v]) // 10 - _ATTACKER_COST[a] if v else 2000 - _ATTACKER_COST[a]
             for a in range(13)] for v in range(13)]
_PROMO_BONUS = (0, 0, 160, 0, -500, -500, -400, 9000)   # theo cờ loại nước; EP coi như ăn tốt

_LMR = [[0] * 64 for _ in range(64)]
for _d in range(1, 64):
    for _n in range(1, 64):
        _LMR[_d][_n] = int(0.75 + math.log(_d) * math.log(_n) / 2.25)


class SearchTimeout(Exception):
    """Hết thời gian cho phép."""


class CoreMismatch(Exception):
    """Lõi B không khớp python-chess ở gốc: bot phải chuyển sang lõi A."""


class FastSearcher:
    def __init__(self) -> None:
        self.tt = TranspositionTable()
        self.history = [[0] * 32768, [0] * 32768]
        self.killers = [[0, 0] for _ in range(MAX_PLY + 4)]
        self.counter = [[0] * 4096, [0] * 4096]   # nước đáp trả tốt cho nước vừa đi của đối thủ
        self.eval_cache: dict[int, int] = {}
        self.b: FastBoard | None = None
        self.nodes = 0
        self.hard_deadline = 0.0
        self.root_ply = 0
        self.iter_best = 0
        self.depth_reached = 0
        self.score = 0

    # ------------------------------------------------------------------ gốc
    def build_board(self, board: chess.Board) -> FastBoard:
        """Dựng FastBoard kèm lịch sử khóa (để phát hiện lặp thế) và tự kiểm tra với python-chess."""
        count = min(board.halfmove_clock, len(board.move_stack))
        undone = [board.pop() for _ in range(count)]
        fb = FastBoard(board)
        for move in reversed(undone):
            fb.make(fb.encode(move))
            board.push(move)
        fresh = FastBoard(board)
        if (fb.sq != fresh.sq or fb.key != fresh.key or fb.stm != fresh.stm
                or fb.castle != fresh.castle or fb.ep != fresh.ep or fb.bb != fresh.bb
                or fb.hmc != board.halfmove_clock or fb.occ != fresh.occ
                or fb.mg != fresh.mg or fb.eg != fresh.eg or fb.phase != fresh.phase):
            raise CoreMismatch("replayed position differs")
        return fb

    def think(self, board: chess.Board, soft: float, hard: float, game_ply: int) -> chess.Move:
        start = time.perf_counter()
        self.hard_deadline = start + hard
        self.nodes = 0
        self.root_ply = game_ply
        self.depth_reached = 0

        b = self.build_board(board)
        self.b = b
        root_moves = b.legal_moves()
        legal_ref = set(board.legal_moves)
        decoded = {FastBoard.decode(m): m for m in root_moves}
        if set(decoded) != legal_ref or len(decoded) != len(root_moves):
            raise CoreMismatch("legal move sets differ")

        for table in self.history:
            for i, v in enumerate(table):
                if v:
                    table[i] = v >> 2
        for pair in self.killers:
            pair[0] = pair[1] = 0
        self.counter = [[0] * 4096, [0] * 4096]
        if len(self.eval_cache) > EVAL_CACHE_LIMIT:
            self.eval_cache.clear()

        root_moves = self._order_root(root_moves)
        best_move = root_moves[0]
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
                    self.iter_best = 0
                    value = self._root(root_moves, depth, alpha, beta)
                    if self.iter_best:
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
                if not free_mode and time.perf_counter() - start > soft * 0.55:
                    break
        except SearchTimeout:
            # Bàn cờ `b` đang dở dang nhưng sẽ được dựng lại ở lượt sau nên không cần hoàn tác.
            if self.iter_best:
                best_move = self.iter_best
        move = FastBoard.decode(best_move)
        if move not in legal_ref:
            raise CoreMismatch("best move is not legal")
        return move

    def _order_root(self, moves: list[int]) -> list[int]:
        sq = self.b.sq
        entry = self.tt.get(self.b.key)
        tt_move = unpack(entry)[3] if entry is not None else 0
        scored = []
        for m in moves:
            victim = sq[(m >> 6) & 63]
            flag = m >> 12
            if m == tt_move:
                value = 1 << 30
            elif flag == 3:
                value = 50
            elif victim or flag == 2 or flag >= 4:
                value = 100000 + _MVV_LVA[victim][sq[m & 63]] + _PROMO_BONUS[flag]
            else:
                value = 0
            scored.append((value, m))
        scored.sort(reverse=True)
        return [m for _, m in scored]

    def _root(self, root_moves: list[int], depth: int, alpha: int, beta: int) -> int:
        b = self.b
        key = b.key
        best = -INF
        original_alpha = alpha
        best_move = 0
        for index, m in enumerate(root_moves):
            b.make(m)
            if index == 0:
                value = -self._search(depth - 1, -beta, -alpha, 1, True, m)
            else:
                value = -self._search(depth - 1, -alpha - 1, -alpha, 1, True, m)
                if value > alpha:
                    value = -self._search(depth - 1, -beta, -alpha, 1, True, m)
            b.unmake()
            if value > best:
                best = value
                best_move = m
                if value > alpha:
                    alpha = value
                    self.iter_best = m
                    if value >= beta:
                        break
        if best_move:
            flag = LOWER if best >= beta else (UPPER if best <= original_alpha else EXACT)
            self.tt.put(key, pack(best, depth, flag, best_move))
        return best

    # ------------------------------------------------------------ lượng giá
    def _eval(self) -> int:
        """Điểm thế cờ theo bên đang đi (có bộ nhớ đệm theo khóa Zobrist)."""
        b = self.b
        key = b.key
        cached = self.eval_cache.get(key)
        if cached is not None:
            return cached
        bb = b.bb
        occ = b.occ
        wk = bb[6].bit_length() - 1
        bk = bb[12].bit_length() - 1
        pm, pe = positional(bb[1], bb[2], bb[3], bb[4], bb[5], wk,
                            bb[7], bb[8], bb[9], bb[10], bb[11], bk, occ[0], occ[1])
        ph = b.phase
        if ph > MAX_PHASE:
            ph = MAX_PHASE
        score = (b.mg + pm) * ph + (b.eg + pe) * (MAX_PHASE - ph)
        score = score // MAX_PHASE if score >= 0 else -(-score // MAX_PHASE)
        if ph <= 8:
            score = endgame_adjust(score, ph, wk, bk, bb[1], bb[7],
                                   (bb[2] | bb[3]).bit_count(), (bb[8] | bb[9]).bit_count(),
                                   bb[4] | bb[5] | bb[10] | bb[11], bb[3] | bb[9])
        score = (score if b.stm == 0 else -score) + TEMPO
        self.eval_cache[key] = score
        return score

    # ------------------------------------------------------------- negamax
    def _search(self, depth: int, alpha: int, beta: int, ply: int, can_null: bool,
                prev: int) -> int:
        self.nodes += 1
        if not self.nodes & 127 and time.perf_counter() > self.hard_deadline:
            raise SearchTimeout
        b = self.b
        in_check = b.in_check()
        if in_check:
            depth += 1                     # mở rộng khi bị chiếu
        if depth <= 0:
            return self._quiesce(alpha, beta, ply, 0, in_check)

        key = b.key
        hmc = b.hmc
        draw = -CONTEMPT if not ply & 1 else CONTEMPT
        # Hệ thống xử hòa ngay khi bên tới lượt CÓ THỂ đòi hòa 50 nước (đồng hồ nửa nước >= 99).
        if hmc >= 99 or self.root_ply + ply >= MAX_GAME_PLIES:
            if in_check and not b.legal_moves():
                return -MATE + ply
            return draw
        if hmc >= 4:
            keys = b.keys
            start = len(keys) - hmc
            if key in keys[start if start > 0 else 0:]:
                return draw
        if ply >= MAX_PLY:
            return self._eval()

        if alpha < -MATE + ply:
            alpha = -MATE + ply
        if beta > MATE - ply - 1:
            beta = MATE - ply - 1
        if alpha >= beta:
            return alpha
        is_pv = beta - alpha > 1

        tt_move = 0
        entry = self.tt.get(key)
        if entry is not None:
            tt_score, tt_depth, tt_flag, tt_move = unpack(entry)
            if tt_depth >= depth and not is_pv:
                if tt_score > MATE_BOUND:
                    tt_score -= ply
                elif tt_score < -MATE_BOUND:
                    tt_score += ply
                if (tt_flag == EXACT or (tt_flag == LOWER and tt_score >= beta)
                        or (tt_flag == UPPER and tt_score <= alpha)):
                    return tt_score

        bb = b.bb
        sq = b.sq
        side = b.stm
        base = 6 * side
        static = -INF
        prunable = False
        if not in_check:
            static = self._eval()
            if not is_pv and abs(beta) < MATE_BOUND:
                prunable = True
                if depth <= 4 and static - 95 * depth >= beta:
                    return static          # reverse futility
                if (can_null and depth >= 3 and static >= beta
                        and (bb[base + 2] | bb[base + 3] | bb[base + 4] | bb[base + 5])):
                    b.make_null()
                    value = -self._search(depth - 4 - depth // 5, -beta, -beta + 1, ply + 1, False, 0)
                    b.unmake_null()
                    if value >= beta:
                        return beta if value > MATE_BOUND else value

        if depth >= 4 and not tt_move:
            depth -= 1                 # chưa có nước gợi ý từ bảng chuyển vị: tìm nông hơn một chút

        king_code = base + 6
        king_line = LINE[bb[king_code].bit_length() - 1]
        history = self.history[side]
        counter = self.counter[side][prev & 4095] if prev else 0
        bad_captures: list[int] = []
        killers = self.killers[ply]
        killer1 = killers[0]
        killer2 = killers[1]
        best = -INF
        best_move = 0
        original_alpha = alpha
        legal = 0
        searched = 0
        skipped = False
        quiets_tried: list[int] = []
        futile = prunable and depth <= 3 and static + 90 * depth + 70 <= alpha
        lmp_limit = 5 + 3 * depth * depth if prunable and depth <= 3 else 9999

        for stage in (0, 1, 2, 3, 4):
            if stage == 0:
                if not tt_move or not b.is_pseudo_legal(tt_move):
                    tt_move = 0
                    continue
                moves = (tt_move,)
            elif stage == 1:
                scored = []
                for m in b.gen_noisy():
                    victim = sq[(m >> 6) & 63]
                    attacker = sq[m & 63]
                    # Quân đắt ăn quân rẻ: dùng SEE; nếu lỗ thì để dành thử sau cùng.
                    if (victim and m < 16384 and SEE_VALUE[attacker] > SEE_VALUE[victim] + 50
                            and m != tt_move and b.see(m) < 0):
                        bad_captures.append(m)
                    else:
                        scored.append(((_MVV_LVA[victim][attacker] + _PROMO_BONUS[m >> 12]) << 15)
                                      | m)
                scored.sort(reverse=True)
                moves = [v & 32767 for v in scored]
            elif stage == 2:
                moves = []
                for k in (killer1, killer2, counter):
                    if (k and k != tt_move and k not in moves
                            and (sq[(k >> 6) & 63] == 0 or k >> 12 == 3) and b.is_pseudo_legal(k)):
                        moves.append(k)
            elif stage == 3:
                if searched and best > -MATE_BOUND and (futile or searched >= lmp_limit):
                    continue               # mọi nước lặng còn lại đều sẽ bị cắt tỉa: khỏi sinh
                moves = b.gen_quiet()
                moves.sort(key=history.__getitem__, reverse=True)
            else:
                moves = bad_captures

            for m in moves:
                if stage:
                    if m == tt_move:
                        continue
                    if stage == 3 and (m == killer1 or m == killer2 or m == counter):
                        continue
                frm = m & 63
                flag = m >> 12
                if stage == 2 or stage == 3:
                    quiet = True
                elif stage:
                    quiet = False
                else:
                    quiet = (sq[(m >> 6) & 63] == 0 and flag < 2) or flag == 3
                if quiet and searched and best > -MATE_BOUND and (futile or searched >= lmp_limit):
                    skipped = True         # futility / late-move pruning ở độ sâu nông
                    continue
                piece = sq[frm]
                b.make(m)
                if flag != 3 and (in_check or piece == king_code or flag == 2
                                  or king_line & _SQ[frm]):
                    if b.left_in_check():
                        b.unmake()
                        continue
                legal += 1

                new_depth = depth - 1
                if searched == 0:
                    value = -self._search(new_depth, -beta, -alpha, ply + 1, True, m)
                else:
                    reduction = 0
                    if depth >= 3 and searched >= 3 and quiet and not in_check:
                        reduction = _LMR[depth if depth < 64 else 63][searched if searched < 64 else 63]
                        if is_pv and reduction:
                            reduction -= 1
                        if stage == 2:
                            if reduction:
                                reduction -= 1     # killer/countermove đáng tin hơn nước lặng thường
                        elif history[m] < 0:
                            reduction += 1         # nước lặng hay thất bại: giảm sâu thêm
                        if reduction > new_depth - 1:
                            reduction = new_depth - 1 if new_depth > 1 else 0
                    value = -self._search(new_depth - reduction, -alpha - 1, -alpha, ply + 1,
                                          True, m)
                    if value > alpha and reduction:
                        value = -self._search(new_depth, -alpha - 1, -alpha, ply + 1, True, m)
                    if alpha < value < beta:
                        value = -self._search(new_depth, -beta, -alpha, ply + 1, True, m)
                b.unmake()
                searched += 1

                if value > best:
                    best = value
                    best_move = m
                    if value > alpha:
                        alpha = value
                        if value >= beta:
                            if quiet:
                                if killers[0] != m:
                                    killers[1] = killers[0]
                                    killers[0] = m
                                if prev:
                                    self.counter[side][prev & 4095] = m
                                bonus = depth * depth
                                history[m] += bonus
                                if history[m] > 1_000_000:
                                    for i, v in enumerate(history):
                                        if v:
                                            history[i] = v >> 1
                                for other in quiets_tried:
                                    history[other] -= bonus
                            break
                if quiet:
                    quiets_tried.append(m)
            else:
                continue
            break

        if legal == 0:
            if skipped:
                return alpha
            return -MATE + ply if in_check else draw
        flag = LOWER if best >= beta else (UPPER if best <= original_alpha else EXACT)
        stored = best
        if stored > MATE_BOUND:
            stored += ply
        elif stored < -MATE_BOUND:
            stored -= ply
        self.tt.put(key, pack(stored, depth if depth < 127 else 127, flag, best_move))
        return best

    # -------------------------------------------------------- quiescence
    def _quiesce(self, alpha: int, beta: int, ply: int, qdepth: int, in_check: int = -1) -> int:
        """Chỉ đi tiếp các nước ăn quân/phong hậu (hoặc mọi nước khi bị chiếu) cho tới khi yên tĩnh."""
        self.nodes += 1
        if not self.nodes & 127 and time.perf_counter() > self.hard_deadline:
            raise SearchTimeout
        b = self.b
        sq = b.sq
        bb = b.bb
        side = b.stm
        if in_check < 0:
            in_check = b.in_check()
        if in_check:
            if ply >= MAX_PLY or qdepth >= QS_MAX_DEPTH:
                return self._eval()
            stand = best = -INF
        else:
            ph = b.phase
            if ph > MAX_PHASE:
                ph = MAX_PHASE
            quick = b.mg * ph + b.eg * (MAX_PHASE - ph)
            if side:
                quick = -quick
            quick = (quick // MAX_PHASE if quick >= 0 else -(-quick // MAX_PHASE)) + TEMPO
            if quick - LAZY_MARGIN >= beta:
                return quick
            if quick + LAZY_MARGIN <= alpha:
                stand = quick
            else:
                stand = self._eval()
                if stand >= beta:
                    return stand
            if stand > alpha:
                alpha = stand
            if ply >= MAX_PLY or qdepth >= QS_MAX_DEPTH:
                return stand
            best = stand

        noisy = b.gen_noisy()
        if len(noisy) > 1:
            scored = [((_MVV_LVA[sq[(m >> 6) & 63]][sq[m & 63]] + _PROMO_BONUS[m >> 12]) << 15) | m
                      for m in noisy]
            scored.sort(reverse=True)
            moves = [v & 32767 for v in scored]
        else:
            moves = noisy
        if in_check:
            moves += b.gen_quiet()

        king_code = 6 + 6 * side
        king_line = LINE[bb[king_code].bit_length() - 1]
        enemy_pawns = bb[7 - 6 * side]
        pawn_attacks = _PATT[side]
        legal = 0
        for m in moves:
            frm = m & 63
            flag = m >> 12
            piece = sq[frm]
            if not in_check:
                if 4 <= flag <= 6:
                    continue                      # bỏ phong cấp thấp trong quiescence
                to = (m >> 6) & 63
                gain = _VALUE[sq[to]] if sq[to] else (100 if flag == 2 else 0)
                if flag == 7:
                    gain += 850
                elif stand + gain + 160 <= alpha:
                    continue                      # delta pruning
                elif _VALUE[piece] > gain + 50 and (pawn_attacks[to] & enemy_pawns
                                                    or b.see(m) < 0):
                    continue                      # nước ăn lỗ quân (theo SEE)
            b.make(m)
            if flag != 3 and (in_check or piece == king_code or flag == 2
                              or king_line & _SQ[frm]):
                if b.left_in_check():
                    b.unmake()
                    continue
            legal += 1
            value = -self._quiesce(-beta, -alpha, ply + 1, qdepth + 1)
            b.unmake()
            if value > best:
                best = value
                if value > alpha:
                    alpha = value
                    if value >= beta:
                        break
        if in_check and legal == 0:
            return -MATE + ply
        return best
