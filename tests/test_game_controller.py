from __future__ import annotations

import asyncio
from typing import Any

import chess
import pytest

from app.game_controller import GameController


def test_game_can_be_stopped_and_started_again() -> None:
    async def scenario() -> None:
        states: list[dict[str, Any]] = []

        async def broadcast(state: dict[str, Any]) -> None:
            states.append(state)

        controller = GameController(broadcast)
        try:
            await controller.start("black", 10, 518)
            assert controller.status == "running"
            assert controller.bot is not None

            await controller.stop()
            stopped = controller.state()
            assert stopped["status"] == "idle"
            assert stopped["result"] is None
            assert stopped["legal_moves"] == []
            assert controller.bot is None
            stopped_clocks = stopped["white_ms"], stopped["black_ms"]
            await asyncio.sleep(0.06)
            assert (
                controller.state()["white_ms"], controller.state()["black_ms"]
            ) == stopped_clocks

            await controller.start("black", 10, 0)
            restarted = controller.state()
            assert restarted["status"] == "running"
            assert restarted["chess960_id"] == 0
            assert restarted["history"] == []
            assert states[-1]["status"] == "running"
        finally:
            await controller.close()

    asyncio.run(scenario())


def test_invalid_human_move_does_not_stop_the_clock() -> None:
    async def scenario() -> None:
        async def broadcast(_: dict[str, Any]) -> None:
            return None

        controller = GameController(broadcast)
        controller.status = "running"
        controller.bot_color = chess.BLACK
        controller.clock.start(chess.WHITE)

        with pytest.raises(ValueError, match="Illegal or stale move token"):
            await controller.human_move("a1a1")

        assert controller.clock.active == chess.WHITE
        await controller.close()

    asyncio.run(scenario())
