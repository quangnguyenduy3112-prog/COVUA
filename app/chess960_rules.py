from __future__ import annotations

import chess


def new_board(position_id: int) -> chess.Board:
    if not 0 <= position_id <= 959:
        raise ValueError("Chess960 position ID must be between 0 and 959")
    return chess.Board.from_chess960_pos(position_id)


def display_legal_moves(board: chess.Board) -> list[dict[str, object]]:
    moves: list[dict[str, object]] = []
    for move in board.legal_moves:
        destination = move.to_square
        castling_side: str | None = None
        if board.is_castling(move):
            kingside = board.is_kingside_castling(move)
            rank = 0 if board.turn == chess.WHITE else 7
            destination = chess.square(6 if kingside else 2, rank)
            castling_side = "kingside" if kingside else "queenside"
        moves.append(
            {
                "token": board.uci(move, chess960=True),
                "from": chess.square_name(move.from_square),
                "to": chess.square_name(destination),
                "promotion": chess.piece_name(move.promotion) if move.promotion else None,
                "castling": castling_side,
            }
        )
    return moves


def move_for_token(board: chess.Board, token: str) -> chess.Move:
    for move in board.legal_moves:
        if board.uci(move, chess960=True) == token:
            return move
    raise ValueError("Illegal or stale move token")
