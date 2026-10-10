"""Hàm lượng giá (heuristic) tự thiết kế tay.

Mọi con số trong tệp này đều do nhóm tự đặt theo nguyên tắc cờ vua phổ thông
(giá trị quân, kiểm soát trung tâm, cấu trúc tốt, an toàn vua, độ linh hoạt),
không lấy từ mô hình hay dữ liệu đã huấn luyện.

Điểm luôn tính theo góc nhìn của Trắng (dương = Trắng tốt hơn), đơn vị centipawn.
Điểm được tách thành hai phần: trung cuộc (mg) và tàn cuộc (eg), sau đó nội suy
theo `phase` (lượng quân nặng/nhẹ còn lại trên bàn).

Mã quân (piece code): 0 = trống, 1..6 = Trắng P N B R Q K, 7..12 = Đen P N B R Q K.
"""
import chess

# --------------------------------------------------------------------------
# Giá trị quân và bảng điểm theo ô (piece-square tables) sinh bằng công thức
# --------------------------------------------------------------------------
MG_VALUE = (0, 88, 320, 335, 495, 960, 0)
EG_VALUE = (0, 118, 305, 325, 540, 990, 0)
PHASE_WEIGHT = (0, 0, 1, 1, 2, 4, 0, 0, 1, 1, 2, 4, 0)  # theo mã quân
MAX_PHASE = 24
TEMPO = 10

_PAWN_MG_RANK = (0, 0, 2, 6, 14, 28, 55, 0)
_PAWN_EG_RANK = (0, 2, 6, 12, 24, 40, 60, 0)


def _pst(piece_type: int, file: int, rank: int) -> tuple[int, int]:
    """Điểm cộng (mg, eg) của một quân Trắng đứng ở (file, rank)."""
    cf = min(file, 7 - file)          # 0 = cột biên, 3 = cột giữa
    cr = min(rank, 7 - rank)
    center = cf + cr                  # 0 = góc, 6 = trung tâm
    if piece_type == chess.PAWN:
        mg = _PAWN_MG_RANK[rank]
        if rank == 1:
            mg += (2, 2, 0, -10)[cf]  # giữ tốt cánh che vua, đẩy tốt trung tâm
        elif rank == 2:
            mg += (0, 0, 4, 6)[cf]
        elif rank == 3:
            mg += (-2, 0, 10, 22)[cf]
        elif rank == 4:
            mg += (0, 2, 10, 20)[cf]
        return mg, _PAWN_EG_RANK[rank]
    if piece_type == chess.KNIGHT:
        mg = center * 11 - 38 + (6 if 3 <= rank <= 5 else 0) - (8 if rank == 0 else 0)
        return mg, center * 7 - 24
    if piece_type == chess.BISHOP:
        return center * 5 - 14 - (8 if rank == 0 else 0), center * 4 - 12
    if piece_type == chess.ROOK:
        return cf * 3 - 4 + (18 if rank == 6 else 0), (8 if rank == 6 else 0)
    if piece_type == chess.QUEEN:
        return center * 2 - 6 - (2 if rank == 0 else 0), center * 5 - 15
    # Vua: trung cuộc trốn ở góc sau hàng tốt, tàn cuộc tiến ra trung tâm.
    if rank == 0:
        mg = (22, 28, 12, -6)[cf]
    elif rank == 1:
        mg = (0, 0, -15, -25)[cf]
    else:
        mg = -35 - 12 * (rank - 2)
    return mg, center * 11 - 33


def _build_tables() -> tuple[list[list[int]], list[list[int]]]:
    mg = [[0] * 64 for _ in range(13)]
    eg = [[0] * 64 for _ in range(13)]
    for piece_type in range(1, 7):
        for square in range(64):
            pm, pe = _pst(piece_type, square & 7, square >> 3)
            mg[piece_type][square] = MG_VALUE[piece_type] + pm
            eg[piece_type][square] = EG_VALUE[piece_type] + pe
            # Quân Đen: lật bàn theo chiều dọc và đổi dấu.
            mg[piece_type + 6][square ^ 56] = -(MG_VALUE[piece_type] + pm)
            eg[piece_type + 6][square ^ 56] = -(EG_VALUE[piece_type] + pe)
    return mg, eg


MG, EG = _build_tables()

# --------------------------------------------------------------------------
# Mặt nạ bitboard dựng sẵn
# --------------------------------------------------------------------------
_ALL = chess.BB_ALL
_NOT_A = _ALL & ~chess.BB_FILE_A
_NOT_H = _ALL & ~chess.BB_FILE_H
FILE_BB = [chess.BB_FILES[sq & 7] for sq in range(64)]            # theo ô
_ADJ_FILES = []
_PASSED_W, _PASSED_B, _AHEAD_W, _AHEAD_B = [], [], [], []
_SHIELD_W, _SHIELD_B, _SHIELD2_W, _SHIELD2_B = [], [], [], []
KING_ZONE = []
for _sq in range(64):
    _f, _r = _sq & 7, _sq >> 3
    _adj = 0
    if _f > 0:
        _adj |= chess.BB_FILES[_f - 1]
    if _f < 7:
        _adj |= chess.BB_FILES[_f + 1]
    _ADJ_FILES.append(_adj)
    _above = 0
    for _rr in range(_r + 1, 8):
        _above |= chess.BB_RANKS[_rr]
    _below = 0
    for _rr in range(0, _r):
        _below |= chess.BB_RANKS[_rr]
    _three = _adj | chess.BB_FILES[_f]
    _PASSED_W.append(_three & _above)
    _PASSED_B.append(_three & _below)
    _AHEAD_W.append(chess.BB_FILES[_f] & _above)
    _AHEAD_B.append(chess.BB_FILES[_f] & _below)
    _SHIELD_W.append(_three & (chess.BB_RANKS[_r + 1] if _r < 7 else 0))
    _SHIELD2_W.append(_three & (chess.BB_RANKS[_r + 2] if _r < 6 else 0))
    _SHIELD_B.append(_three & (chess.BB_RANKS[_r - 1] if _r > 0 else 0))
    _SHIELD2_B.append(_three & (chess.BB_RANKS[_r - 2] if _r > 1 else 0))
    KING_ZONE.append(chess.BB_KING_ATTACKS[_sq] | chess.BB_SQUARES[_sq])

_KNIGHT = chess.BB_KNIGHT_ATTACKS
_KING = chess.BB_KING_ATTACKS
_DIAG_MASK, _DIAG_ATT = chess.BB_DIAG_MASKS, chess.BB_DIAG_ATTACKS
_FILE_MASK, _FILE_ATT = chess.BB_FILE_MASKS, chess.BB_FILE_ATTACKS
_RANK_MASK, _RANK_ATT = chess.BB_RANK_MASKS, chess.BB_RANK_ATTACKS
_PAWN_ATT_W = chess.BB_PAWN_ATTACKS[chess.WHITE]   # ô mà tốt Trắng ở sq tấn công
_PAWN_ATT_B = chess.BB_PAWN_ATTACKS[chess.BLACK]

# Khoảng cách tới trung tâm và giữa hai ô (dùng cho tàn cuộc dồn vua)
DIST = [[max(abs((a & 7) - (b & 7)), abs((a >> 3) - (b >> 3))) for b in range(64)]
        for a in range(64)]
_PASSER_KING = (0, 0, 0, 2, 4, 7, 10, 0)      # trọng số khoảng cách vua tới tốt thông theo hàng
_LIGHT_SQUARES = chess.BB_LIGHT_SQUARES
CENTER_DIST = [max(3 - (sq & 7), (sq & 7) - 4) + max(3 - (sq >> 3), (sq >> 3) - 4)
               for sq in range(64)]

# --------------------------------------------------------------------------
# Cấu trúc tốt (có bộ nhớ đệm vì hình tốt ít thay đổi giữa các nút search)
# --------------------------------------------------------------------------
_PASSED_MG = (0, 4, 8, 16, 32, 56, 90, 0)
_PASSED_EG = (0, 10, 18, 34, 62, 105, 170, 0)
_DOUBLED = (10, 20)
_ISOLATED = (12, 14)
_SUPPORTED = (6, 4)

_pawn_cache: dict[tuple[int, int], tuple[int, int, int, int]] = {}


def pawn_structure(wp: int, bp: int) -> tuple[int, int, int, int]:
    """Điểm (mg, eg) của hình tốt: tốt chồng, tốt cô lập, tốt thông, tốt có bảo vệ.

    Trả thêm bitboard tốt thông của Trắng và của Đen để phần lượng giá phụ thuộc
    vị trí vua/quân chặn dùng lại.
    """
    key = (wp, bp)
    hit = _pawn_cache.get(key)
    if hit is not None:
        return hit
    mg = eg = 0
    w_passed = b_passed = 0
    bb = wp
    while bb:
        low = bb & -bb
        sq = low.bit_length() - 1
        bb ^= low
        if _AHEAD_W[sq] & wp:
            mg -= _DOUBLED[0]
            eg -= _DOUBLED[1]
        if not _ADJ_FILES[sq] & wp:
            mg -= _ISOLATED[0]
            eg -= _ISOLATED[1]
        elif _PAWN_ATT_B[sq] & wp:
            mg += _SUPPORTED[0]
            eg += _SUPPORTED[1]
        if not _PASSED_W[sq] & bp and not _AHEAD_W[sq] & wp:
            rank = sq >> 3
            mg += _PASSED_MG[rank]
            eg += _PASSED_EG[rank]
            w_passed |= low
    bb = bp
    while bb:
        low = bb & -bb
        sq = low.bit_length() - 1
        bb ^= low
        if _AHEAD_B[sq] & bp:
            mg += _DOUBLED[0]
            eg += _DOUBLED[1]
        if not _ADJ_FILES[sq] & bp:
            mg += _ISOLATED[0]
            eg += _ISOLATED[1]
        elif _PAWN_ATT_W[sq] & bp:
            mg -= _SUPPORTED[0]
            eg -= _SUPPORTED[1]
        if not _PASSED_B[sq] & wp and not _AHEAD_B[sq] & bp:
            rank = 7 - (sq >> 3)
            mg -= _PASSED_MG[rank]
            eg -= _PASSED_EG[rank]
            b_passed |= low
    if len(_pawn_cache) > 200_000:
        _pawn_cache.clear()
    result = (mg, eg, w_passed, b_passed)
    _pawn_cache[key] = result
    return result


# --------------------------------------------------------------------------
# Các yếu tố vị trí tính ở nút lá
# --------------------------------------------------------------------------
# Hình phạt (mg) cho vua theo tổng "đơn vị tấn công" của quân địch vào vùng quanh vua.
_KING_DANGER = (0, 0, 2, 6, 12, 20, 30, 42, 56, 72, 90, 110, 130, 150, 170, 190, 210,
                230, 250, 270, 290, 310, 330, 350, 370)
_KING_DANGER_MAX = len(_KING_DANGER) - 1


def positional(wp: int, wn: int, wb: int, wr: int, wq: int, wk: int,
               bp: int, bn: int, bb: int, br: int, bq: int, bk: int,
               wocc: int, bocc: int) -> tuple[int, int]:
    """Điểm vị trí (mg, eg) ngoài giá trị quân + bảng ô.

    wp..wq, bp..bq là bitboard từng loại quân; wk, bk là Ô của vua (0..63).
    Gồm: cấu trúc tốt, cặp tượng, xe cột mở, độ linh hoạt, an toàn vua.
    """
    occ = wocc | bocc
    mg, eg, w_passed, b_passed = pawn_structure(wp, bp)

    # Ô bị tốt đối phương khống chế: quân nhẹ/nặng không nên tính là "đi được".
    w_pawn_att = ((wp << 7) & _NOT_H) | ((wp << 9) & _NOT_A)
    b_pawn_att = ((bp >> 7) & _NOT_A) | ((bp >> 9) & _NOT_H)
    w_safe = ~(wocc | b_pawn_att)
    b_safe = ~(bocc | w_pawn_att)
    w_zone = KING_ZONE[wk]
    b_zone = KING_ZONE[bk]
    all_pawns = wp | bp

    if wb & (wb - 1):
        mg += 28
        eg += 48
    if bb & (bb - 1):
        mg -= 28
        eg -= 48

    # ---------------- Trắng ----------------
    units = attackers = 0
    x = wn
    while x:
        low = x & -x
        x ^= low
        a = _KNIGHT[low.bit_length() - 1]
        n = (a & w_safe).bit_count()
        mg += 4 * n - 16
        eg += 4 * n - 16
        if a & b_zone:
            units += 2
            attackers += 1
    x = wb
    while x:
        low = x & -x
        x ^= low
        sq = low.bit_length() - 1
        a = _DIAG_ATT[sq][_DIAG_MASK[sq] & occ]
        n = (a & w_safe).bit_count()
        mg += 4 * n - 24
        eg += 5 * n - 30
        if a & b_zone:
            units += 2
            attackers += 1
    x = wr
    while x:
        low = x & -x
        x ^= low
        sq = low.bit_length() - 1
        a = _FILE_ATT[sq][_FILE_MASK[sq] & occ] | _RANK_ATT[sq][_RANK_MASK[sq] & occ]
        n = (a & w_safe).bit_count()
        mg += 2 * n - 14
        eg += 4 * n - 28
        file_bb = FILE_BB[sq]
        if not file_bb & wp:
            if not file_bb & bp:
                mg += 22
                eg += 10
            else:
                mg += 10
                eg += 5
        if a & b_zone:
            units += 3
            attackers += 1
    x = wq
    while x:
        low = x & -x
        x ^= low
        sq = low.bit_length() - 1
        a = (_DIAG_ATT[sq][_DIAG_MASK[sq] & occ] | _FILE_ATT[sq][_FILE_MASK[sq] & occ]
             | _RANK_ATT[sq][_RANK_MASK[sq] & occ])
        n = (a & w_safe).bit_count()
        mg += n - 13
        eg += 2 * n - 26
        if a & b_zone:
            units += 5
            attackers += 1
    if attackers >= 2:
        # Vua Đen bị tấn công: phạt nặng hơn khi thiếu tốt che.
        units += 3 - (_SHIELD_B[bk] & bp).bit_count()
        mg += _KING_DANGER[units if units < _KING_DANGER_MAX else _KING_DANGER_MAX]

    # ---------------- Đen ----------------
    units = attackers = 0
    x = bn
    while x:
        low = x & -x
        x ^= low
        a = _KNIGHT[low.bit_length() - 1]
        n = (a & b_safe).bit_count()
        mg -= 4 * n - 16
        eg -= 4 * n - 16
        if a & w_zone:
            units += 2
            attackers += 1
    x = bb
    while x:
        low = x & -x
        x ^= low
        sq = low.bit_length() - 1
        a = _DIAG_ATT[sq][_DIAG_MASK[sq] & occ]
        n = (a & b_safe).bit_count()
        mg -= 4 * n - 24
        eg -= 5 * n - 30
        if a & w_zone:
            units += 2
            attackers += 1
    x = br
    while x:
        low = x & -x
        x ^= low
        sq = low.bit_length() - 1
        a = _FILE_ATT[sq][_FILE_MASK[sq] & occ] | _RANK_ATT[sq][_RANK_MASK[sq] & occ]
        n = (a & b_safe).bit_count()
        mg -= 2 * n - 14
        eg -= 4 * n - 28
        file_bb = FILE_BB[sq]
        if not file_bb & bp:
            if not file_bb & wp:
                mg -= 22
                eg -= 10
            else:
                mg -= 10
                eg -= 5
        if a & w_zone:
            units += 3
            attackers += 1
    x = bq
    while x:
        low = x & -x
        x ^= low
        sq = low.bit_length() - 1
        a = (_DIAG_ATT[sq][_DIAG_MASK[sq] & occ] | _FILE_ATT[sq][_FILE_MASK[sq] & occ]
             | _RANK_ATT[sq][_RANK_MASK[sq] & occ])
        n = (a & b_safe).bit_count()
        mg -= n - 13
        eg -= 2 * n - 26
        if a & w_zone:
            units += 5
            attackers += 1
    if attackers >= 2:
        units += 3 - (_SHIELD_W[wk] & wp).bit_count()
        mg -= _KING_DANGER[units if units < _KING_DANGER_MAX else _KING_DANGER_MAX]

    # ---------------- Lá chắn tốt trước vua (chỉ có ý nghĩa ở trung cuộc) ----------------
    mg += 9 * (_SHIELD_W[wk] & wp).bit_count() + 4 * (_SHIELD2_W[wk] & wp).bit_count()
    mg -= 9 * (_SHIELD_B[bk] & bp).bit_count() + 4 * (_SHIELD2_B[bk] & bp).bit_count()
    if not FILE_BB[wk] & all_pawns:
        mg -= 16
    if not FILE_BB[bk] & all_pawns:
        mg += 16

    # ---------------- Tốt thông: vua hai bên ở gần/xa và ô phía trước có bị chặn không ----------------
    x = w_passed
    while x:
        low = x & -x
        x ^= low
        sq = low.bit_length() - 1
        rank = sq >> 3
        stop = sq + 8
        weight = _PASSER_KING[rank]
        if weight:
            d_them = DIST[bk][stop]
            d_us = DIST[wk][stop]
            eg += weight * (2 * (d_them if d_them < 5 else 5) - (d_us if d_us < 5 else 5)) // 2
            if occ & (low << 8):
                mg -= _PASSED_MG[rank] // 3
                eg -= _PASSED_EG[rank] // 3
    x = b_passed
    while x:
        low = x & -x
        x ^= low
        sq = low.bit_length() - 1
        rank = 7 - (sq >> 3)
        stop = sq - 8
        weight = _PASSER_KING[rank]
        if weight:
            d_them = DIST[wk][stop]
            d_us = DIST[bk][stop]
            eg -= weight * (2 * (d_them if d_them < 5 else 5) - (d_us if d_us < 5 else 5)) // 2
            if occ & (low >> 8):
                mg += _PASSED_MG[rank] // 3
                eg += _PASSED_EG[rank] // 3
    return mg, eg


def endgame_adjust(score: int, phase: int, wk: int, bk: int,
                   pawns_w: int, pawns_b: int, minors_w: int, minors_b: int,
                   majors: int, bishops: int) -> int:
    """Hiệu chỉnh điểm (góc nhìn Trắng) cho tàn cuộc.

    - Không đủ quân để chiếu hết  => gần như hòa.
    - Bên hơn quân không còn tốt và hơn chưa tới một xe => rất khó thắng, giảm điểm.
    - Hơn quân lớn ở tàn cuộc     => thưởng dồn vua yếu ra biên, kéo vua mạnh lại gần.
    """
    if (minors_w == 1 and minors_b == 1 and not majors and bishops & (bishops - 1)
            and bishops & _LIGHT_SQUARES and bishops & ~_LIGHT_SQUARES):
        # Mỗi bên đúng một tượng và hai tượng khác màu ô: tàn cuộc rất dễ hòa => giảm nửa điểm.
        score = score // 2 if score >= 0 else -(-score // 2)
    if not pawns_w and not pawns_b and not majors:
        # Mỗi bên tối đa một quân nhẹ, hoặc chỉ còn mã (hai mã không ép chiếu hết được).
        if (minors_w <= 1 and minors_b <= 1) or (not bishops and minors_w <= 2 and minors_b <= 2):
            return int(score / 16)
    if score > 0:
        if not pawns_w and score < 420:
            return score >> 2
        if phase <= 8 and score > 380:
            dist = abs((wk & 7) - (bk & 7)) + abs((wk >> 3) - (bk >> 3))
            return score + 10 * CENTER_DIST[bk] + 4 * (14 - dist)
    elif score < 0:
        if not pawns_b and score > -420:
            return -(-score >> 2)
        if phase <= 8 and score < -380:
            dist = abs((wk & 7) - (bk & 7)) + abs((wk >> 3) - (bk >> 3))
            return score - 10 * CENTER_DIST[wk] - 4 * (14 - dist)
    return score


def evaluate_board(board: chess.Board) -> int:
    """Lượng giá đầy đủ một `chess.Board` (góc nhìn bên đang đi). Dùng để đối chiếu/kiểm thử."""
    mg, eg, phase = material_pst(board)
    return full_score(board, mg, eg, phase)


def material_pst(board: chess.Board) -> tuple[int, int, int]:
    """Tính từ đầu (mg, eg, phase) = giá trị quân + bảng ô. Search cập nhật gia tăng 3 số này."""
    mg = eg = phase = 0
    white = board.occupied_co[chess.WHITE]
    for piece_type, bitboard in ((1, board.pawns), (2, board.knights), (3, board.bishops),
                                 (4, board.rooks), (5, board.queens), (6, board.kings)):
        while bitboard:
            low = bitboard & -bitboard
            bitboard ^= low
            code = piece_type if low & white else piece_type + 6
            sq = low.bit_length() - 1
            mg += MG[code][sq]
            eg += EG[code][sq]
            phase += PHASE_WEIGHT[code]
    return mg, eg, phase


def full_score(board: chess.Board, mg: int, eg: int, phase: int) -> int:
    """Ghép điểm gia tăng với các yếu tố vị trí, trả về điểm theo bên đang đi."""
    wocc = board.occupied_co[chess.WHITE]
    bocc = board.occupied_co[chess.BLACK]
    pawns, knights, bishops = board.pawns, board.knights, board.bishops
    rooks, queens, kings = board.rooks, board.queens, board.kings
    wk = (kings & wocc).bit_length() - 1
    bk = (kings & bocc).bit_length() - 1
    pm, pe = positional(pawns & wocc, knights & wocc, bishops & wocc, rooks & wocc,
                        queens & wocc, wk,
                        pawns & bocc, knights & bocc, bishops & bocc, rooks & bocc,
                        queens & bocc, bk, wocc, bocc)
    ph = phase if phase < MAX_PHASE else MAX_PHASE
    score = (mg + pm) * ph + (eg + pe) * (MAX_PHASE - ph)
    # chia làm tròn về 0 để điểm đối xứng tuyệt đối giữa Trắng và Đen
    score = score // MAX_PHASE if score >= 0 else -(-score // MAX_PHASE)
    if ph <= 8:
        minors = knights | bishops
        score = endgame_adjust(score, ph, wk, bk, pawns & wocc, pawns & bocc,
                               (minors & wocc).bit_count(), (minors & bocc).bit_count(),
                               rooks | queens, bishops)
    return (score if board.turn else -score) + TEMPO


def move_delta(board: chess.Board, move: chess.Move) -> tuple[int, int, int]:
    """Thay đổi (mg, eg, phase) nếu đi `move` trên `board` (gọi TRƯỚC khi push).

    Xử lý đủ: ăn quân, bắt tốt qua đường, phong cấp, nhập thành Chess960
    (python-chess mã hóa nhập thành là "vua đi tới ô xe của mình").
    """
    frm = move.from_square
    to = move.to_square
    white = board.turn
    piece_type = board.piece_type_at(frm)
    code = piece_type if white else piece_type + 6
    to_mask = chess.BB_SQUARES[to]

    if piece_type == chess.KING:
        own_rook_on_target = bool(to_mask & board.occupied_co[white] & board.rooks)
        if own_rook_on_target or abs((to & 7) - (frm & 7)) > 1:
            base = 0 if white else 56
            kingside = (to & 7) > (frm & 7)
            if own_rook_on_target:
                rook_from = to
            else:  # dạng cờ vua chuẩn e1g1/e1c1
                rook_from = base + (7 if kingside else 0)
            king_to = base + (6 if kingside else 2)
            rook_to = base + (5 if kingside else 3)
            rook = code - 2
            return (MG[code][king_to] - MG[code][frm] + MG[rook][rook_to] - MG[rook][rook_from],
                    EG[code][king_to] - EG[code][frm] + EG[rook][rook_to] - EG[rook][rook_from],
                    0)

    new_code = code
    if move.promotion:
        new_code = move.promotion if white else move.promotion + 6
    dmg = MG[new_code][to] - MG[code][frm]
    deg = EG[new_code][to] - EG[code][frm]
    dphase = PHASE_WEIGHT[new_code] - PHASE_WEIGHT[code]

    victim = board.piece_type_at(to)
    if victim:
        vcode = victim + 6 if white else victim
        dmg -= MG[vcode][to]
        deg -= EG[vcode][to]
        dphase -= PHASE_WEIGHT[vcode]
    elif piece_type == chess.PAWN and (to & 7) != (frm & 7):
        cap_sq = to - 8 if white else to + 8   # bắt tốt qua đường
        vcode = 7 if white else 1
        dmg -= MG[vcode][cap_sq]
        deg -= EG[vcode][cap_sq]
    return dmg, deg, dphase
