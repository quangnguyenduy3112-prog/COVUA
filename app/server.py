from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .chess960_rules import new_board
from .game_controller import GameController
from .schemas import MoveRequest, StartGameRequest

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static" / "built-ui"
connections: set[WebSocket] = set()


async def broadcast(payload: dict[str, Any]) -> None:
    dead: list[WebSocket] = []
    for socket in list(connections):
        try:
            await socket.send_json(payload)
        except Exception:  # noqa: BLE001 - a dead client must not break other sockets.
            dead.append(socket)
    for socket in dead:
        connections.discard(socket)


game = GameController(broadcast)


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await game.close()


app = FastAPI(title="ChessLab", lifespan=lifespan)


@app.get("/api/state")
async def get_state() -> dict[str, Any]:
    return game.state()


@app.get("/api/preview/{position_id}")
async def preview_position(position_id: int) -> dict[str, Any]:
    if not 0 <= position_id <= 959:
        raise HTTPException(status_code=422, detail="Chess960 ID must be from 0 to 959")
    board = new_board(position_id)
    return {"chess960_id": position_id, "fen": board.fen(shredder=True)}


@app.post("/api/start")
async def start_game(request: StartGameRequest) -> dict[str, Any]:
    await game.start(request.bot_color, request.time_seconds, request.chess960_id)
    return game.state()


@app.post("/api/stop")
async def stop_game() -> dict[str, Any]:
    await game.stop()
    return game.state()


@app.post("/api/move")
async def submit_move(request: MoveRequest) -> dict[str, Any]:
    try:
        await game.human_move(request.token)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return game.state()


@app.websocket("/ws")
async def websocket_endpoint(socket: WebSocket) -> None:
    await socket.accept()
    connections.add(socket)
    await socket.send_json(game.state())
    try:
        while True:
            await socket.receive_text()
    except WebSocketDisconnect:
        connections.discard(socket)


if STATIC.exists():
    app.mount("/assets", StaticFiles(directory=STATIC / "assets"), name="assets")


@app.get("/chesslab-icon.svg", include_in_schema=False)
async def app_icon() -> FileResponse:
    return FileResponse(STATIC / "chesslab-icon.svg", media_type="image/svg+xml")


@app.get("/manifest.webmanifest", include_in_schema=False)
async def web_manifest() -> FileResponse:
    return FileResponse(
        STATIC / "manifest.webmanifest",
        media_type="application/manifest+json",
    )


@app.get("/{path:path}")
async def frontend(path: str) -> FileResponse:
    index = STATIC / "index.html"
    if not index.exists():
        raise HTTPException(status_code=503, detail="Frontend has not been built")
    return FileResponse(index)
