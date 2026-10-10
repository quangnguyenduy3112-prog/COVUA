from __future__ import annotations

from dataclasses import dataclass

import chess


@dataclass(frozen=True, slots=True)
class BotConfig:
    color: chess.Color
    chess960_id: int
    initial_time_ms: int
    seed: int


@dataclass(frozen=True, slots=True)
class SearchContext:
    time_remaining_ms: int
    opponent_time_remaining_ms: int
    ply: int
