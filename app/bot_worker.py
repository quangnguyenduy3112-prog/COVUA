from __future__ import annotations

import contextlib
import importlib
import json
import random
import sys
import traceback
from typing import Any

import chess
import numpy as np

from chesslab_sdk import BotConfig, SearchContext

PROTOCOL_VERSION = "1.0"
PROTOCOL_OUT = sys.stdout


def emit(payload: dict[str, Any]) -> None:
    PROTOCOL_OUT.write(json.dumps(payload, separators=(",", ":")) + "\n")
    PROTOCOL_OUT.flush()


def build_board(position_id: int, moves: list[str]) -> chess.Board:
    board = chess.Board.from_chess960_pos(position_id)
    for token in moves:
        board.push_uci(token)
    return board


def main() -> None:
    bot: Any = None
    emit({"type": "ready", "protocol_version": PROTOCOL_VERSION})
    for line in sys.stdin:
        try:
            request = json.loads(line)
            request_type = request.get("type")
            if request_type == "init":
                seed = int(request["seed"])
                random.seed(seed)
                np.random.seed(seed & 0xFFFFFFFF)
                config = BotConfig(
                    color=bool(request["color"]),
                    chess960_id=int(request["chess960_id"]),
                    initial_time_ms=int(request["initial_time_ms"]),
                    seed=seed,
                )
                with contextlib.redirect_stdout(sys.stderr):
                    module = importlib.import_module("student.bot")
                    bot = module.StudentBot(config)
                emit({"type": "initialized"})
            elif request_type == "move":
                if bot is None:
                    raise RuntimeError("Bot has not been initialized")
                board = build_board(int(request["chess960_id"]), list(request["moves"]))
                context = SearchContext(
                    time_remaining_ms=int(request["time_remaining_ms"]),
                    opponent_time_remaining_ms=int(request["opponent_time_remaining_ms"]),
                    ply=len(request["moves"]),
                )
                with contextlib.redirect_stdout(sys.stderr):
                    move = bot.choose_move(board.copy(stack=True), context)
                if not isinstance(move, chess.Move):
                    raise TypeError("choose_move() must return chess.Move")
                emit({"type": "move", "move": board.uci(move, chess960=True)})
            elif request_type == "shutdown":
                emit({"type": "bye"})
                return
            else:
                raise ValueError(f"Unknown request type: {request_type!r}")
        except BaseException as exc:  # noqa: BLE001 - report every student-code failure.
            traceback.print_exc(file=sys.stderr)
            emit({"type": "error", "error": type(exc).__name__, "message": str(exc)})


if __name__ == "__main__":
    main()
