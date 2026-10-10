from __future__ import annotations

from pydantic import BaseModel, Field


class StartGameRequest(BaseModel):
    bot_color: str = Field(pattern="^(white|black)$")
    time_seconds: int = Field(default=240, ge=10, le=3600)
    chess960_id: int | None = Field(default=None, ge=0, le=959)


class MoveRequest(BaseModel):
    token: str = Field(min_length=4, max_length=8)
