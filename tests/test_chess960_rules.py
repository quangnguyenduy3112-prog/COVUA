import chess
import pytest

from app.chess960_rules import display_legal_moves, move_for_token, new_board


def test_position_id_range_is_checked() -> None:
    with pytest.raises(ValueError):
        new_board(960)


def test_every_display_token_round_trips_to_a_legal_move() -> None:
    board = new_board(518)
    displayed = display_legal_moves(board)
    assert displayed
    for item in displayed:
        move = move_for_token(board, str(item["token"]))
        assert move in board.legal_moves


def test_chess960_castling_token_and_display_destination() -> None:
    board = chess.Board("4k3/8/8/8/8/8/8/R2K3R w HA - 0 1", chess960=True)
    castles = [item for item in display_legal_moves(board) if item["castling"]]
    assert {item["castling"] for item in castles} == {"kingside", "queenside"}
    assert {item["to"] for item in castles} == {"c1", "g1"}
    for item in castles:
        assert board.is_castling(move_for_token(board, str(item["token"])))
