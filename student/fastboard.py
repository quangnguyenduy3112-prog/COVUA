"""Lõi B: bàn cờ tự viết, tối ưu cho search.

Vì sao cần: `chess.Board` rất đúng nhưng tổng quát nên chậm (tạo đối tượng Move,
lưu toàn bộ trạng thái mỗi lần push...). Ở đây thế cờ được lưu bằng:

- `sq[64]`  : mã quân ở từng ô (0 trống, 1..6 Trắng P N B R Q K, 7..12 Đen).
- `bb[13]`  : bitboard (số nguyên 64 bit) của từng mã quân.
- `occ[2]`  : bitboard tất cả quân của Trắng (0) / Đen (1).

Nước đi là một số nguyên: bit 0-5 ô đi, bit 6-11 ô đến, bit 12-14 loại nước.
Nhập thành được mã hóa giống python-chess ở chế độ Chess960: "vua đi tới ô xe".

`make()`/`unmake()` cập nhật gia tăng khóa Zobrist và điểm (mg, eg, phase).
Nước sinh ra là giả hợp lệ (pseudo-legal); tính hợp lệ được kiểm sau khi đi
bằng `attacked()` (vua mình có bị ăn không). Riêng nhập thành được kiểm đầy đủ
ngay khi sinh. Bảng tấn công của quân trượt lấy từ các bảng dựng sẵn của `chess`.

Tính đúng đắn được kiểm bằng perft đối chiếu với python-chess (devtools/perft.py)
và được kiểm lại ở gốc mỗi lượt đi trong lúc thi đấu.
"""
import random

import chess

from .evaluation import EG, MG, PHASE_WEIGHT

# Loại nước đi (bit 12-14)
F_NORMAL = 0
F_DOUBLE = 1      # tốt đi hai ô
F_EP = 2          # bắt tốt qua đường
F_CASTLE = 3      # nhập thành (ô đến = ô xe)
F_PROMO_N = 4     # phong cấp: loại quân = cờ - 2
F_PROMO_Q = 7

_SQ = chess.BB_SQUARES
_KNIGHT = chess.BB_KNIGHT_ATTACKS
_KING = chess.BB_KING_ATTACKS
_DIAG_MASK, _DIAG_ATT = chess.BB_DIAG_MASKS, chess.BB_DIAG_ATTACKS
_FILE_MASK, _FILE_ATT = chess.BB_FILE_MASKS, chess.BB_FILE_ATTACKS
_RANK_MASK, _RANK_ATT = chess.BB_RANK_MASKS, chess.BB_RANK_ATTACKS
# _PATT[bên][ô] = các ô mà một con tốt của `bên` đứng ở `ô` tấn công (0 = Trắng, 1 = Đen)
_PATT = (chess.BB_PAWN_ATTACKS[chess.WHITE], chess.BB_PAWN_ATTACKS[chess.BLACK])
_NOT_A = chess.BB_ALL & ~chess.BB_FILE_A
_NOT_H = chess.BB_ALL & ~chess.BB_FILE_H
_RANK_1, _RANK_2, _RANK_3 = chess.BB_RANK_1, chess.BB_RANK_2, chess.BB_RANK_3
_RANK_6, _RANK_7, _RANK_8 = chess.BB_RANK_6, chess.BB_RANK_7, chess.BB_RANK_8
# Các ô cùng hàng/cột/đường chéo với một ô (bàn trống): quân rời khỏi đây mới có thể làm lộ vua.
SEE_VALUE = (0, 100, 320, 330, 500, 950, 20000, 100, 320, 330, 500, 950, 20000)
LINE = [_DIAG_ATT[s][0] | _FILE_ATT[s][0] | _RANK_ATT[s][0] for s in range(64)]

# Khóa Zobrist; được sinh lại từ config.seed bằng init_zobrist().
Z_PIECE: list[list[int]] = []
Z_CASTLE: list[int] = []
Z_EP: list[int] = []
Z_SIDE = 0


def init_zobrist(seed: int) -> None:
    """Sinh bảng số ngẫu nhiên 64 bit cho băm Zobrist từ hạt giống của ván đấu."""
    global Z_PIECE, Z_CASTLE, Z_EP, Z_SIDE
    rng = random.Random(seed)
    Z_PIECE = [[0] * 64] + [[rng.getrandbits(64) for _ in range(64)] for _ in range(12)]
    Z_CASTLE = [rng.getrandbits(64) for _ in range(16)]
    Z_EP = [rng.getrandbits(64) for _ in range(64)]
    Z_SIDE = rng.getrandbits(64)


init_zobrist(0)


class FastBoard:
    __slots__ = ("sq", "bb", "occ", "stm", "ep", "castle", "hmc", "key", "mg", "eg", "phase",
                 "stack", "keys", "castle_mask", "castle_info")

    def __init__(self, board: chess.Board) -> None:
        """Dựng từ một `chess.Board` (đây là cách duy nhất tạo FastBoard)."""
        sq = [0] * 64
        bb = [0] * 13
        white = board.occupied_co[chess.WHITE]
        for piece_type, bitboard in ((1, board.pawns), (2, board.knights), (3, board.bishops),
                                     (4, board.rooks), (5, board.queens), (6, board.kings)):
            x = bitboard
            while x:
                low = x & -x
                x ^= low
                code = piece_type if low & white else piece_type + 6
                sq[low.bit_length() - 1] = code
                bb[code] |= low
        self.sq = sq
        self.bb = bb
        self.occ = [white, board.occupied_co[chess.BLACK]]
        self.stm = 0 if board.turn else 1
        self.hmc = board.halfmove_clock
        self.stack: list[tuple] = []
        self.keys: list[int] = []

        # Quyền nhập thành: bit 1 = Trắng cánh h, 2 = Trắng cánh a, 4 = Đen cánh h, 8 = Đen cánh a.
        self.castle = 0
        self.castle_mask = [15] * 64
        self.castle_info: list[tuple | None] = [None, None, None, None]
        rights = board.clean_castling_rights()
        for side in (0, 1):
            king_bb = bb[6 + 6 * side]
            if not king_bb:
                continue
            king = king_bb.bit_length() - 1
            base = 56 * side
            x = rights & (_RANK_1 if side == 0 else _RANK_8)
            while x:
                low = x & -x
                x ^= low
                rook = low.bit_length() - 1
                h_side = rook > king
                index = 2 * side + (0 if h_side else 1)
                bit = 1 << index
                king_to = base + (6 if h_side else 2)
                rook_to = base + (5 if h_side else 3)
                self.castle |= bit
                self.castle_mask[king] &= ~bit
                self.castle_mask[rook] &= ~bit
                empty = ((chess.between(king, king_to) | chess.between(rook, rook_to)
                          | _SQ[king_to] | _SQ[rook_to]) & ~(_SQ[king] | _SQ[rook]))
                walk = chess.between(king, king_to) | _SQ[king]
                walk_squares = tuple(s for s in range(64) if walk & _SQ[s])
                # (cờ quyền, ô vua, ô xe, ô vua đến, mặt nạ phải trống, các ô vua đi qua,
                #  phần occ thay đổi khi xét ô đến của vua, nước đi)
                self.castle_info[index] = (
                    bit, king, rook, king_to, empty, walk_squares,
                    _SQ[king] ^ _SQ[rook] ^ _SQ[rook_to],
                    king | (rook << 6) | (F_CASTLE << 12),
                )

        # Chỉ ghi nhận ô bắt tốt qua đường khi thật sự có tốt đối phương đứng cạnh để bắt.
        self.ep = -1
        ep = board.ep_square
        if ep is not None and _PATT[self.stm ^ 1][ep] & bb[1 + 6 * self.stm]:
            self.ep = ep

        mg = eg = phase = 0
        key = Z_SIDE if self.stm else 0
        for s in range(64):
            code = sq[s]
            if code:
                mg += MG[code][s]
                eg += EG[code][s]
                phase += PHASE_WEIGHT[code]
                key ^= Z_PIECE[code][s]
        key ^= Z_CASTLE[self.castle]
        if self.ep >= 0:
            key ^= Z_EP[self.ep]
        self.mg, self.eg, self.phase, self.key = mg, eg, phase, key

    # ------------------------------------------------------------ tấn công
    def attacked(self, square: int, by: int, occ: int) -> int:
        """Khác 0 nếu bên `by` đang tấn công `square` với bố cục chiếm ô `occ`."""
        bb = self.bb
        base = 6 * by
        if _KNIGHT[square] & bb[base + 2]:
            return 1
        if _PATT[by ^ 1][square] & bb[base + 1]:
            return 1
        if _KING[square] & bb[base + 6]:
            return 1
        queens = bb[base + 5]
        if _DIAG_ATT[square][_DIAG_MASK[square] & occ] & (bb[base + 3] | queens):
            return 1
        if (_FILE_ATT[square][_FILE_MASK[square] & occ]
                | _RANK_ATT[square][_RANK_MASK[square] & occ]) & (bb[base + 4] | queens):
            return 1
        return 0

    def in_check(self) -> int:
        """Bên đang đi có bị chiếu không (viết thẳng thay vì gọi attacked() cho nhanh)."""
        bb = self.bb
        side = self.stm
        square = bb[6 + 6 * side].bit_length() - 1
        base = 6 - 6 * side                      # mã quân của đối phương bắt đầu từ base + 1
        if _KNIGHT[square] & bb[base + 2] or _PATT[side][square] & bb[base + 1]:
            return 1
        occ = self.occ[0] | self.occ[1]
        queens = bb[base + 5]
        if _DIAG_ATT[square][_DIAG_MASK[square] & occ] & (bb[base + 3] | queens):
            return 1
        if (_FILE_ATT[square][_FILE_MASK[square] & occ]
                | _RANK_ATT[square][_RANK_MASK[square] & occ]) & (bb[base + 4] | queens):
            return 1
        return 0

    def left_in_check(self) -> int:
        """Gọi SAU make(): bên vừa đi có để vua mình bị ăn không (nước không hợp lệ)."""
        bb = self.bb
        mover = self.stm ^ 1
        square = bb[6 + 6 * mover].bit_length() - 1
        base = 6 - 6 * mover
        if _KNIGHT[square] & bb[base + 2] or _PATT[mover][square] & bb[base + 1]:
            return 1
        if _KING[square] & bb[base + 6]:
            return 1
        occ = self.occ[0] | self.occ[1]
        queens = bb[base + 5]
        if _DIAG_ATT[square][_DIAG_MASK[square] & occ] & (bb[base + 3] | queens):
            return 1
        if (_FILE_ATT[square][_FILE_MASK[square] & occ]
                | _RANK_ATT[square][_RANK_MASK[square] & occ]) & (bb[base + 4] | queens):
            return 1
        return 0

    def see(self, m: int) -> int:
        """Static exchange evaluation: lãi/lỗ vật chất nếu hai bên ăn qua lại trên ô đến của `m`.

        Mỗi bên lần lượt ăn lại bằng quân rẻ nhất; kết quả < 0 nghĩa là nước ăn này lỗ quân.
        """
        sq = self.sq
        bb = self.bb
        frm = m & 63
        to = (m >> 6) & 63
        flag = m >> 12
        side = self.stm
        occ_side = self.occ
        occ = (occ_side[0] | occ_side[1]) ^ _SQ[frm]
        on_square = SEE_VALUE[sq[frm]]            # giá trị quân đang đứng trên ô tranh chấp
        gains = [SEE_VALUE[sq[to]]]
        if flag == 2:
            gains[0] = 100
            occ ^= _SQ[to - 8 if side == 0 else to + 8]
        elif flag >= 4:
            on_square = SEE_VALUE[flag - 2]
            gains[0] += on_square - 100
        diag = bb[3] | bb[5] | bb[9] | bb[11]
        orth = bb[4] | bb[5] | bb[10] | bb[11]
        attackers = ((_KNIGHT[to] & (bb[2] | bb[8])) | (_PATT[1][to] & bb[1])
                     | (_PATT[0][to] & bb[7]) | (_KING[to] & (bb[6] | bb[12]))
                     | (_DIAG_ATT[to][_DIAG_MASK[to] & occ] & diag)
                     | ((_FILE_ATT[to][_FILE_MASK[to] & occ]
                         | _RANK_ATT[to][_RANK_MASK[to] & occ]) & orth)) & occ
        side ^= 1
        while True:
            mine = attackers & occ_side[side]
            if not mine:
                break
            base = 6 * side
            kind = 1
            while True:
                x = mine & bb[base + kind]
                if x:
                    break
                kind += 1
            if kind == 6 and attackers & occ_side[side ^ 1]:
                break                             # vua không được ăn vào ô còn bị bảo vệ
            occ ^= x & -x
            gains.append(on_square - gains[-1])
            on_square = SEE_VALUE[kind]
            if kind == 1 or kind == 3 or kind == 5:   # mở đường cho quân trượt đứng sau (x-ray)
                attackers |= _DIAG_ATT[to][_DIAG_MASK[to] & occ] & diag
            if kind == 4 or kind == 5:
                attackers |= (_FILE_ATT[to][_FILE_MASK[to] & occ]
                              | _RANK_ATT[to][_RANK_MASK[to] & occ]) & orth
            attackers &= occ
            side ^= 1
        i = len(gains) - 1
        while i > 0:
            if -gains[i] < gains[i - 1]:
                gains[i - 1] = -gains[i]
            i -= 1
        return gains[0]

    # ------------------------------------------------------------ sinh nước
    def gen_noisy(self) -> list[int]:
        """Nước ăn quân (kể cả bắt tốt qua đường) và mọi nước phong cấp."""
        moves: list[int] = []
        add = moves.append
        bb = self.bb
        side = self.stm
        own = self.occ[side]
        enemy = self.occ[side ^ 1]
        occ = own | enemy
        base = 6 * side
        pawns = bb[base + 1]
        if side == 0:
            for shift, mask in ((7, _NOT_H), (9, _NOT_A)):
                t = (pawns << shift) & mask & enemy
                while t:
                    low = t & -t
                    t ^= low
                    to = low.bit_length() - 1
                    m = (to - shift) | (to << 6)
                    if to >= 56:
                        add(m | 28672)
                        add(m | 24576)
                        add(m | 20480)
                        add(m | 16384)
                    else:
                        add(m)
            t = (pawns << 8) & ~occ & _RANK_8
            while t:
                low = t & -t
                t ^= low
                to = low.bit_length() - 1
                m = (to - 8) | (to << 6)
                add(m | 28672)
                add(m | 24576)
                add(m | 20480)
                add(m | 16384)
        else:
            for shift, mask in ((7, _NOT_A), (9, _NOT_H)):
                t = (pawns >> shift) & mask & enemy
                while t:
                    low = t & -t
                    t ^= low
                    to = low.bit_length() - 1
                    m = (to + shift) | (to << 6)
                    if to < 8:
                        add(m | 28672)
                        add(m | 24576)
                        add(m | 20480)
                        add(m | 16384)
                    else:
                        add(m)
            t = (pawns >> 8) & ~occ & _RANK_1
            while t:
                low = t & -t
                t ^= low
                to = low.bit_length() - 1
                m = (to + 8) | (to << 6)
                add(m | 28672)
                add(m | 24576)
                add(m | 20480)
                add(m | 16384)
        ep = self.ep
        if ep >= 0:
            t = _PATT[side ^ 1][ep] & pawns
            while t:
                low = t & -t
                t ^= low
                add((low.bit_length() - 1) | (ep << 6) | 8192)

        x = bb[base + 2]
        while x:
            low = x & -x
            x ^= low
            frm = low.bit_length() - 1
            t = _KNIGHT[frm] & enemy
            while t:
                low = t & -t
                t ^= low
                add(frm | ((low.bit_length() - 1) << 6))
        x = bb[base + 3]
        while x:
            low = x & -x
            x ^= low
            frm = low.bit_length() - 1
            t = _DIAG_ATT[frm][_DIAG_MASK[frm] & occ] & enemy
            while t:
                low = t & -t
                t ^= low
                add(frm | ((low.bit_length() - 1) << 6))
        x = bb[base + 4]
        while x:
            low = x & -x
            x ^= low
            frm = low.bit_length() - 1
            t = (_FILE_ATT[frm][_FILE_MASK[frm] & occ]
                 | _RANK_ATT[frm][_RANK_MASK[frm] & occ]) & enemy
            while t:
                low = t & -t
                t ^= low
                add(frm | ((low.bit_length() - 1) << 6))
        x = bb[base + 5]
        while x:
            low = x & -x
            x ^= low
            frm = low.bit_length() - 1
            t = (_DIAG_ATT[frm][_DIAG_MASK[frm] & occ] | _FILE_ATT[frm][_FILE_MASK[frm] & occ]
                 | _RANK_ATT[frm][_RANK_MASK[frm] & occ]) & enemy
            while t:
                low = t & -t
                t ^= low
                add(frm | ((low.bit_length() - 1) << 6))
        frm = bb[base + 6].bit_length() - 1
        t = _KING[frm] & enemy
        while t:
            low = t & -t
            t ^= low
            add(frm | ((low.bit_length() - 1) << 6))
        return moves

    def gen_quiet(self) -> list[int]:
        """Nước không ăn quân, không phong cấp; gồm cả nhập thành."""
        moves: list[int] = []
        add = moves.append
        bb = self.bb
        side = self.stm
        occ = self.occ[0] | self.occ[1]
        empty = ~occ
        base = 6 * side
        pawns = bb[base + 1]
        if side == 0:
            single = (pawns << 8) & empty
            t = single & ~_RANK_8
            while t:
                low = t & -t
                t ^= low
                to = low.bit_length() - 1
                add((to - 8) | (to << 6))
            t = ((single & _RANK_3) << 8) & empty
            while t:
                low = t & -t
                t ^= low
                to = low.bit_length() - 1
                add((to - 16) | (to << 6) | 4096)
        else:
            single = (pawns >> 8) & empty
            t = single & ~_RANK_1
            while t:
                low = t & -t
                t ^= low
                to = low.bit_length() - 1
                add((to + 8) | (to << 6))
            t = ((single & _RANK_6) >> 8) & empty
            while t:
                low = t & -t
                t ^= low
                to = low.bit_length() - 1
                add((to + 16) | (to << 6) | 4096)

        x = bb[base + 2]
        while x:
            low = x & -x
            x ^= low
            frm = low.bit_length() - 1
            t = _KNIGHT[frm] & empty
            while t:
                low = t & -t
                t ^= low
                add(frm | ((low.bit_length() - 1) << 6))
        x = bb[base + 3]
        while x:
            low = x & -x
            x ^= low
            frm = low.bit_length() - 1
            t = _DIAG_ATT[frm][_DIAG_MASK[frm] & occ] & empty
            while t:
                low = t & -t
                t ^= low
                add(frm | ((low.bit_length() - 1) << 6))
        x = bb[base + 4]
        while x:
            low = x & -x
            x ^= low
            frm = low.bit_length() - 1
            t = (_FILE_ATT[frm][_FILE_MASK[frm] & occ]
                 | _RANK_ATT[frm][_RANK_MASK[frm] & occ]) & empty
            while t:
                low = t & -t
                t ^= low
                add(frm | ((low.bit_length() - 1) << 6))
        x = bb[base + 5]
        while x:
            low = x & -x
            x ^= low
            frm = low.bit_length() - 1
            t = (_DIAG_ATT[frm][_DIAG_MASK[frm] & occ] | _FILE_ATT[frm][_FILE_MASK[frm] & occ]
                 | _RANK_ATT[frm][_RANK_MASK[frm] & occ]) & empty
            while t:
                low = t & -t
                t ^= low
                add(frm | ((low.bit_length() - 1) << 6))
        frm = bb[base + 6].bit_length() - 1
        t = _KING[frm] & empty
        while t:
            low = t & -t
            t ^= low
            add(frm | ((low.bit_length() - 1) << 6))
        if self.castle & (3 << (2 * side)):
            self._gen_castles(moves)
        return moves

    def _gen_castles(self, moves: list[int]) -> None:
        """Nhập thành Chess960, kiểm đầy đủ điều kiện (giống hệt python-chess)."""
        side = self.stm
        occ = self.occ[0] | self.occ[1]
        enemy = side ^ 1
        castle = self.castle
        for index in (2 * side, 2 * side + 1):
            info = self.castle_info[index]
            if info is None or not castle & info[0]:
                continue
            _, king, rook, king_to, empty, walk, final_toggle, move = info
            if occ & empty:
                continue
            occ_no_king = occ ^ _SQ[king]
            for square in walk:
                if self.attacked(square, enemy, occ_no_king):
                    break
            else:
                if not self.attacked(king_to, enemy, occ ^ final_toggle):
                    moves.append(move)

    def legal_moves(self) -> list[int]:
        """Mọi nước hợp lệ (dùng ở gốc và khi kiểm thử)."""
        result = []
        for move in self.gen_noisy() + self.gen_quiet():
            self.make(move)
            if not self.left_in_check():
                result.append(move)
            self.unmake()
        return result

    # ------------------------------------------------------------ đi / lùi
    def make(self, m: int) -> None:
        sq = self.sq
        bb = self.bb
        occ = self.occ
        side = self.stm
        other = side ^ 1
        frm = m & 63
        to = (m >> 6) & 63
        flag = m >> 12
        piece = sq[frm]
        captured = sq[to]
        key = self.key
        mg = self.mg
        eg = self.eg
        castle = self.castle
        old_ep = self.ep
        hmc = self.hmc
        self.stack.append((m, captured, castle, old_ep, hmc, key, mg, eg, self.phase))
        self.keys.append(key)
        key ^= Z_SIDE
        if old_ep >= 0:
            key ^= Z_EP[old_ep]
        ep = -1
        from_bb = _SQ[frm]
        to_bb = _SQ[to]

        if flag == 3:
            # Nhập thành: `to` là ô xe của chính mình. Gỡ vua và xe ra trước rồi mới đặt lại,
            # vì trong Chess960 ô đích của quân này có thể trùng ô xuất phát của quân kia.
            rook = piece - 2
            base = 56 * side
            if to > frm:
                king_to, rook_to = base + 6, base + 5
            else:
                king_to, rook_to = base + 2, base + 3
            sq[frm] = 0
            sq[to] = 0
            sq[king_to] = piece
            sq[rook_to] = rook
            king_to_bb = _SQ[king_to]
            rook_to_bb = _SQ[rook_to]
            bb[piece] ^= from_bb ^ king_to_bb
            bb[rook] ^= to_bb ^ rook_to_bb
            occ[side] ^= from_bb ^ to_bb ^ king_to_bb ^ rook_to_bb
            zp = Z_PIECE[piece]
            zr = Z_PIECE[rook]
            key ^= zp[frm] ^ zp[king_to] ^ zr[to] ^ zr[rook_to]
            mgp = MG[piece]
            mgr = MG[rook]
            mg += mgp[king_to] - mgp[frm] + mgr[rook_to] - mgr[to]
            egp = EG[piece]
            egr = EG[rook]
            eg += egp[king_to] - egp[frm] + egr[rook_to] - egr[to]
            hmc += 1
        else:
            new_piece = piece
            if captured:
                bb[captured] ^= to_bb
                occ[other] ^= to_bb
                key ^= Z_PIECE[captured][to]
                mg -= MG[captured][to]
                eg -= EG[captured][to]
                self.phase -= PHASE_WEIGHT[captured]
                hmc = 0
            elif flag == 2:
                cap_sq = to - 8 if side == 0 else to + 8
                cap_piece = sq[cap_sq]
                cap_bb = _SQ[cap_sq]
                sq[cap_sq] = 0
                bb[cap_piece] ^= cap_bb
                occ[other] ^= cap_bb
                key ^= Z_PIECE[cap_piece][cap_sq]
                mg -= MG[cap_piece][cap_sq]
                eg -= EG[cap_piece][cap_sq]
            else:
                hmc += 1
            if flag >= 4:
                new_piece = flag - 2 + 6 * side
                self.phase += PHASE_WEIGHT[new_piece]
            sq[frm] = 0
            sq[to] = new_piece
            bb[piece] ^= from_bb
            bb[new_piece] ^= to_bb
            occ[side] ^= from_bb ^ to_bb
            key ^= Z_PIECE[piece][frm] ^ Z_PIECE[new_piece][to]
            mg += MG[new_piece][to] - MG[piece][frm]
            eg += EG[new_piece][to] - EG[piece][frm]
            if piece == 1 or piece == 7:
                hmc = 0
                if flag == 1:
                    middle = (frm + to) >> 1
                    if _PATT[side][middle] & bb[1 + 6 * other]:
                        ep = middle
                        key ^= Z_EP[middle]

        if castle:
            mask = self.castle_mask
            new_castle = castle & mask[frm] & mask[to]
            if new_castle != castle:
                key ^= Z_CASTLE[castle] ^ Z_CASTLE[new_castle]
                self.castle = new_castle
        self.ep = ep
        self.hmc = hmc
        self.key = key
        self.mg = mg
        self.eg = eg
        self.stm = other

    def unmake(self) -> None:
        (m, captured, self.castle, self.ep, self.hmc, self.key, self.mg, self.eg,
         self.phase) = self.stack.pop()
        self.keys.pop()
        sq = self.sq
        bb = self.bb
        occ = self.occ
        other = self.stm
        side = other ^ 1
        self.stm = side
        frm = m & 63
        to = (m >> 6) & 63
        flag = m >> 12
        from_bb = _SQ[frm]
        to_bb = _SQ[to]
        if flag == 3:
            piece = 6 + 6 * side
            rook = piece - 2
            base = 56 * side
            if to > frm:
                king_to, rook_to = base + 6, base + 5
            else:
                king_to, rook_to = base + 2, base + 3
            sq[king_to] = 0
            sq[rook_to] = 0
            sq[frm] = piece
            sq[to] = rook
            king_to_bb = _SQ[king_to]
            rook_to_bb = _SQ[rook_to]
            bb[piece] ^= from_bb ^ king_to_bb
            bb[rook] ^= to_bb ^ rook_to_bb
            occ[side] ^= from_bb ^ to_bb ^ king_to_bb ^ rook_to_bb
            return
        new_piece = sq[to]
        piece = new_piece if flag < 4 else 1 + 6 * side
        sq[frm] = piece
        sq[to] = captured
        bb[piece] ^= from_bb
        bb[new_piece] ^= to_bb
        occ[side] ^= from_bb ^ to_bb
        if captured:
            bb[captured] ^= to_bb
            occ[other] ^= to_bb
        elif flag == 2:
            cap_sq = to - 8 if side == 0 else to + 8
            cap_piece = 1 + 6 * other
            cap_bb = _SQ[cap_sq]
            sq[cap_sq] = cap_piece
            bb[cap_piece] ^= cap_bb
            occ[other] ^= cap_bb

    def make_null(self) -> None:
        """Nhường lượt (dùng cho null-move pruning)."""
        key = self.key
        self.stack.append((self.ep, self.hmc, key))
        self.keys.append(key)
        key ^= Z_SIDE
        if self.ep >= 0:
            key ^= Z_EP[self.ep]
            self.ep = -1
        self.key = key
        self.hmc = 0          # không so lặp thế xuyên qua một nước "nhường lượt"
        self.stm ^= 1

    def unmake_null(self) -> None:
        self.ep, self.hmc, self.key = self.stack.pop()
        self.keys.pop()
        self.stm ^= 1

    # ------------------------------------------------------------ tiện ích
    def is_pseudo_legal(self, m: int) -> bool:
        """Nước `m` (lấy từ bảng chuyển vị/killer) có đi được ở thế hiện tại không."""
        sq = self.sq
        side = self.stm
        frm = m & 63
        to = (m >> 6) & 63
        flag = m >> 12
        piece = sq[frm]
        if piece == 0 or (piece > 6) != (side == 1):
            return False
        kind = piece - 6 * side
        target = sq[to]
        if flag == 3:
            if kind != 6 or not self.castle & (3 << (2 * side)):
                return False
            found: list[int] = []
            self._gen_castles(found)
            return m in found
        if target and (target > 6) == (side == 1):
            return False
        to_bb = _SQ[to]
        if kind == 1:
            if flag == 2:
                return to == self.ep and bool(_PATT[side][frm] & to_bb)
            last_rank = (to >> 3) == (7 if side == 0 else 0)
            if last_rank != (flag >= 4):
                return False
            step = 8 if side == 0 else -8
            if flag == 1:
                return (not target and (frm >> 3) == (1 if side == 0 else 6)
                        and to == frm + 2 * step and sq[frm + step] == 0)
            if target:
                return bool(_PATT[side][frm] & to_bb)
            return to == frm + step
        if flag:
            return False
        if kind == 2:
            return bool(_KNIGHT[frm] & to_bb)
        if kind == 6:
            return bool(_KING[frm] & to_bb)
        occ = self.occ[0] | self.occ[1]
        attacks = 0
        if kind != 4:
            attacks = _DIAG_ATT[frm][_DIAG_MASK[frm] & occ]
        if kind != 3:
            attacks |= _FILE_ATT[frm][_FILE_MASK[frm] & occ] | _RANK_ATT[frm][_RANK_MASK[frm] & occ]
        return bool(attacks & to_bb)

    def encode(self, move: chess.Move) -> int:
        """Đổi `chess.Move` (hợp lệ ở thế hiện tại) sang nước dạng số nguyên."""
        sq = self.sq
        frm = move.from_square
        to = move.to_square
        piece = sq[frm]
        kind = piece if piece <= 6 else piece - 6
        if move.promotion:
            return frm | (to << 6) | ((move.promotion + 2) << 12)
        if kind == 6:
            if sq[to] == piece - 2:
                return frm | (to << 6) | 12288
            if abs((to & 7) - (frm & 7)) > 1:      # dạng cờ vua chuẩn: quy về "vua tới ô xe"
                index = 2 * self.stm + (0 if to > frm else 1)
                info = self.castle_info[index]
                if info is not None:
                    return info[7]
        elif kind == 1:
            if abs(to - frm) == 16:
                return frm | (to << 6) | 4096
            if (to & 7) != (frm & 7) and sq[to] == 0:
                return frm | (to << 6) | 8192
        return frm | (to << 6)

    @staticmethod
    def decode(m: int) -> chess.Move:
        """Đổi nước dạng số nguyên sang `chess.Move` (nhập thành = vua tới ô xe, đúng chuẩn Chess960)."""
        flag = m >> 12
        return chess.Move(m & 63, (m >> 6) & 63, flag - 2 if flag >= 4 else None)
