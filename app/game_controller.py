from __future__ import annotations

import asyncio
import secrets
import time
from collections.abc import Awaitable, Callable
from typing import Any

import chess

from .bot_process import BotProcess, BotProcessError
from .chess960_rules import display_legal_moves, move_for_token, new_board
from .clock import ChessClock

Broadcast = Callable[[dict[str, Any]], Awaitable[None]]


BOT_MOVE_MINIMUM_MS = 500
BOT_MOVE_MAXIMUM_MS = 1_000


class GameController:
    def __init__(self, broadcast: Broadcast) -> None:
        self.broadcast = broadcast
        self.board = new_board(518)
        self.position_id = 518
        self.bot_color = chess.BLACK
        self.initial_time_ms = 240_000
        self.clock = ChessClock(self.initial_time_ms)
        self.moves: list[str] = []
        self.history: list[dict[str, Any]] = []
        self.status = "idle"
        self.result: str | None = None
        self.termination: str | None = None
        self.bot: BotProcess | None = None
        self._guard = asyncio.Lock()
        self._bot_task: asyncio.Task[None] | None = None
        self._ticker_task: asyncio.Task[None] | None = None

    async def start(self, bot_color: str, time_seconds: int, position_id: int | None) -> None:
        await self._cancel_background_tasks()
        async with self._guard:
            await self._release_bot()
            self.position_id = position_id if position_id is not None else secrets.randbelow(960)
            self.board = new_board(self.position_id)
            self.bot_color = chess.WHITE if bot_color == "white" else chess.BLACK
            self.initial_time_ms = time_seconds * 1000
            self.clock = ChessClock(self.initial_time_ms)
            self.moves = []
            self.history = []
            self.status = "starting"
            self.result = None
            self.termination = None
            self.bot = BotProcess()
            await self.bot.start()
            started = time.monotonic_ns()
            try:
                await self.bot.request(
                    {
                        "type": "init",
                        "color": self.bot_color,
                        "chess960_id": self.position_id,
                        "initial_time_ms": self.initial_time_ms,
                        "seed": secrets.randbits(63),
                    },
                    timeout=self.initial_time_ms / 1000,
                )
            except BotProcessError as exc:
                elapsed = (time.monotonic_ns() - started) // 1_000_000
                self.clock.remaining[self.bot_color] = max(0, self.initial_time_ms - elapsed)
                self._finish("0-1" if self.bot_color else "1-0", f"bot initialization: {exc}")
                await self._release_bot()
                await self.broadcast(self.state())
                return
            elapsed = (time.monotonic_ns() - started) // 1_000_000
            self.clock.remaining[self.bot_color] = max(0, self.initial_time_ms - elapsed)
            if self.clock.remaining[self.bot_color] == 0:
                self._finish("0-1" if self.bot_color else "1-0", "bot timeout during initialization")
            else:
                self.status = "running"
                self.clock.start(self.board.turn)
                self._ticker_task = asyncio.create_task(self._ticker())
            if self.status == "finished":
                await self._release_bot()
            await self.broadcast(self.state())
            self._schedule_bot_if_needed()

    async def stop(self) -> None:
        await self._cancel_background_tasks()
        async with self._guard:
            self.clock.stop()
            await self._release_bot()
            self.status = "idle"
            self.result = None
            self.termination = None
            state = self.state()
        await self.broadcast(state)

    async def human_move(self, token: str) -> None:
        async with self._guard:
            if self.status != "running" or self.board.turn == self.bot_color:
                raise ValueError("It is not the human player's turn")
            if self.clock.value(self.board.turn) <= 0:
                self.clock.stop()
                self._finish("0-1" if self.board.turn else "1-0", "human timeout")
                await self.broadcast(self.state())
                return
            move = move_for_token(self.board, token)
            elapsed = self.clock.stop()
            self._apply_move(move, elapsed)
            await self._after_move()

    async def _bot_turn(self) -> None:
        async with self._guard:
            if self.status != "running" or self.board.turn != self.bot_color or self.bot is None:
                return
            remaining = self.clock.value(self.bot_color)
            opponent = self.clock.value(not self.bot_color)
            if remaining <= 0:
                self._finish("0-1" if self.bot_color else "1-0", "bot timeout")
                await self.broadcast(self.state())
                return
            try:
                request_started_ns = time.monotonic_ns()
                response = await self.bot.request(
                    {
                        "type": "move",
                        "chess960_id": self.position_id,
                        "moves": self.moves,
                        "time_remaining_ms": remaining,
                        "opponent_time_remaining_ms": opponent,
                    },
                    timeout=remaining / 1000,
                )
                response_elapsed_ms = max(
                    0, (time.monotonic_ns() - request_started_ns) // 1_000_000
                )
                target_elapsed_ms = BOT_MOVE_MINIMUM_MS + secrets.randbelow(
                    BOT_MOVE_MAXIMUM_MS - BOT_MOVE_MINIMUM_MS + 1
                )
                delay_ms = max(0, target_elapsed_ms - response_elapsed_ms)
                if delay_ms:
                    await asyncio.sleep(min(delay_ms, self.clock.value(self.bot_color)) / 1000)
                elapsed = self.clock.stop()
                if self.clock.remaining[self.bot_color] <= 0:
                    raise BotProcessError("Bot timed out")
                move = move_for_token(self.board, str(response.get("move", "")))
                self._apply_move(move, elapsed)
            except (BotProcessError, ValueError) as exc:
                self.clock.stop()
                self._finish("0-1" if self.bot_color else "1-0", f"bot failure: {exc}")
                await self._release_bot()
                await self.broadcast(self.state())
                return
            await self._after_move()

    def _apply_move(self, move: chess.Move, elapsed_ms: int) -> None:
        san = self.board.san(move)
        color = self.board.turn
        token = self.board.uci(move, chess960=True)
        self.board.push(move)
        self.moves.append(token)
        self.history.append(
            {
                "ply": len(self.moves),
                "color": "white" if color else "black",
                "san": san,
                "uci": token,
                "elapsed_ms": elapsed_ms,
            }
        )

    async def _after_move(self) -> None:
        outcome = self.board.outcome(claim_draw=True)
        if outcome is not None:
            self._finish(outcome.result(), outcome.termination.name.lower())
        elif len(self.moves) >= 300:
            self._finish("1/2-1/2", "300-ply limit")
        else:
            self.clock.start(self.board.turn)
        await self.broadcast(self.state())
        if self.status == "finished":
            await self._release_bot()
        else:
            self._schedule_bot_if_needed()

    def _schedule_bot_if_needed(self) -> None:
        if self.status == "running" and self.board.turn == self.bot_color:
            self._bot_task = asyncio.create_task(self._bot_turn())

    async def _ticker(self) -> None:
        while self.status == "running":
            await asyncio.sleep(0.05)
            if self.clock.value(self.board.turn) <= 0:
                async with self._guard:
                    if self.status == "running" and self.clock.value(self.board.turn) <= 0:
                        loser = self.board.turn
                        self.clock.stop()
                        self._finish("0-1" if loser else "1-0", "timeout")
            await self.broadcast(self.state())
        await self._release_bot()

    def _finish(self, result: str, termination: str) -> None:
        self.status = "finished"
        self.result = result
        self.termination = termination
        self.clock.stop()

    async def _cancel_background_tasks(self) -> None:
        current = asyncio.current_task()
        tasks: list[asyncio.Task[None]] = []
        for attribute in ("_ticker_task", "_bot_task"):
            task = getattr(self, attribute)
            setattr(self, attribute, None)
            if task and task is not current and not task.done():
                task.cancel()
                tasks.append(task)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _release_bot(self) -> None:
        bot, self.bot = self.bot, None
        if bot:
            await bot.stop()

    async def close(self) -> None:
        await self._cancel_background_tasks()
        async with self._guard:
            await self._release_bot()

    def state(self) -> dict[str, Any]:
        human_turn = self.status == "running" and self.board.turn != self.bot_color
        return {
            "status": self.status,
            "result": self.result,
            "termination": self.termination,
            "chess960_id": self.position_id,
            "fen": self.board.fen(shredder=True),
            "turn": "white" if self.board.turn else "black",
            "bot_color": "white" if self.bot_color else "black",
            "white_ms": self.clock.value(chess.WHITE),
            "black_ms": self.clock.value(chess.BLACK),
            "history": self.history,
            "legal_moves": display_legal_moves(self.board) if human_turn else [],
        }
