from __future__ import annotations

import asyncio
from typing import Any

from app.game_controller import GameController


def test_fast_bot_move_uses_human_paced_delay() -> None:
    async def scenario() -> None:
        states: list[dict[str, Any]] = []

        async def broadcast(state: dict[str, Any]) -> None:
            states.append(state)

        controller = GameController(broadcast)
        try:
            await controller.start("white", 10, 518)
            for _ in range(40):
                if controller.history or controller.status == "finished":
                    break
                await asyncio.sleep(0.05)

            assert controller.history
            elapsed_ms = int(controller.history[0]["elapsed_ms"])
            assert 480 <= elapsed_ms <= 1_300
            assert controller.clock.remaining[True] <= 9_520
        finally:
            await controller.close()

    asyncio.run(scenario())
