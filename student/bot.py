from __future__ import annotations

import chess

from chesslab_sdk import BotConfig, SearchContext


class StudentBot:
    """The only class imported by the local runner and official grader."""

    def __init__(self, config: BotConfig) -> None:
        self.config = config

    def choose_move(self, board: chess.Board, context: SearchContext) -> chess.Move:
        return next(iter(board.legal_moves))
