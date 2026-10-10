from __future__ import annotations

import asyncio
import json
import sys
from typing import Any


class BotProcessError(RuntimeError):
    pass


class BotProcess:
    def __init__(self) -> None:
        self.process: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        self.process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-u",
            "-m",
            "app.bot_worker",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
        )
        ready = await self._read(10.0)
        if ready.get("type") != "ready":
            raise BotProcessError(f"Worker failed to start: {ready}")

    async def request(self, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        async with self._lock:
            if self.process is None or self.process.stdin is None:
                raise BotProcessError("Worker is not running")
            self.process.stdin.write((json.dumps(payload) + "\n").encode())
            await self.process.stdin.drain()
            response = await self._read(timeout)
            if response.get("type") == "error":
                raise BotProcessError(f"{response.get('error')}: {response.get('message')}")
            return response

    async def _read(self, timeout: float) -> dict[str, Any]:
        if self.process is None or self.process.stdout is None:
            raise BotProcessError("Worker is not running")
        try:
            line = await asyncio.wait_for(self.process.stdout.readline(), timeout=timeout)
        except TimeoutError as exc:
            await self.stop()
            raise BotProcessError("Bot timed out") from exc
        if not line:
            code = await self.process.wait()
            raise BotProcessError(f"Worker exited with code {code}")
        return json.loads(line)

    async def stop(self) -> None:
        process = self.process
        self.process = None
        if process is None or process.returncode is not None:
            return
        process.kill()
        await process.wait()
