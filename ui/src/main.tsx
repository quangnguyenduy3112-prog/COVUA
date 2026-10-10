import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { Chessboard } from "react-chessboard";
import "./styles.css";

type Color = "white" | "black";

type LegalMove = {
  token: string;
  from: string;
  to: string;
  promotion: string | null;
  castling: "kingside" | "queenside" | null;
};

type GameState = {
  status: string;
  result: string | null;
  termination: string | null;
  chess960_id: number;
  fen: string;
  turn: Color;
  bot_color: Color;
  white_ms: number;
  black_ms: number;
  legal_moves: LegalMove[];
  history: Array<{ ply: number; color: string; san: string }>;
};

type PositionPreview = {
  chess960_id: number;
  fen: string;
};

const emptyState: GameState = {
  status: "idle",
  result: null,
  termination: null,
  chess960_id: 518,
  fen: "",
  turn: "white",
  bot_color: "black",
  white_ms: 240000,
  black_ms: 240000,
  legal_moves: [],
  history: [],
};

function formatClock(milliseconds: number) {
  const total = Math.max(0, Math.floor(milliseconds));
  const minutes = Math.floor(total / 60000);
  const seconds = Math.floor((total % 60000) / 1000);
  const millis = total % 1000;
  return `${minutes}:${String(seconds).padStart(2, "0")}.${String(millis).padStart(3, "0")}`;
}

function randomPositionId(previous?: number) {
  let next = Math.floor(Math.random() * 960);
  if (previous !== undefined && next === previous) next = (next + 1) % 960;
  return next;
}

function resultTone(result: string, botColor: Color) {
  if (result === "1/2-1/2") return "draw";
  const winner: Color = result === "1-0" ? "white" : "black";
  const humanColor: Color = botColor === "white" ? "black" : "white";
  return winner === humanColor ? "success" : "danger";
}

function resultLabel(result: string, botColor: Color) {
  const tone = resultTone(result, botColor);
  if (tone === "draw") return "Ván đấu hòa";
  return tone === "success" ? "Bạn thắng" : "Bạn thua";
}

async function post(path: string, body: unknown) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const payload = await response.json();
    throw new Error(payload.detail ?? "Không thể thực hiện yêu cầu");
  }
  return response.json();
}

function App() {
  const [game, setGame] = useState<GameState>(emptyState);
  const [botColor, setBotColor] = useState<Color>("black");
  const [timeSeconds, setTimeSeconds] = useState("240");
  const [positionId, setPositionId] = useState(() => randomPositionId());
  const [selectedSquare, setSelectedSquare] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [promotionChoices, setPromotionChoices] = useState<LegalMove[]>([]);
  const [preview, setPreview] = useState<PositionPreview | null>(null);

  useEffect(() => {
    fetch("/api/state").then((response) => response.json()).then(setGame);
    void loadPreview(positionId);
    const scheme = location.protocol === "https:" ? "wss" : "ws";
    const socket = new WebSocket(`${scheme}://${location.host}/ws`);
    socket.onmessage = (event) => {
      const nextGame: GameState = JSON.parse(event.data);
      if (nextGame.status === "starting" || nextGame.status === "running") setPreview(null);
      setGame(nextGame);
    };
    const keepAlive = window.setInterval(() => {
      if (socket.readyState === WebSocket.OPEN) socket.send("ping");
    }, 20000);
    return () => {
      window.clearInterval(keepAlive);
      socket.close();
    };
  }, []);

  useEffect(() => {
    setSelectedSquare(null);
    setPromotionChoices([]);
  }, [game.fen]);

  const moveIndex = useMemo(() => {
    const index = new Map<string, LegalMove[]>();
    for (const move of game.legal_moves) {
      const key = `${move.from}-${move.to}`;
      index.set(key, [...(index.get(key) ?? []), move]);
    }
    return index;
  }, [game.legal_moves]);

  const movesBySource = useMemo(() => {
    const index = new Map<string, LegalMove[]>();
    for (const move of game.legal_moves) {
      index.set(move.from, [...(index.get(move.from) ?? []), move]);
    }
    return index;
  }, [game.legal_moves]);

  const squareStyles = useMemo(() => {
    const styles: Record<string, React.CSSProperties> = {};
    if (!selectedSquare) return styles;
    styles[selectedSquare] = {
      background: "rgba(246, 211, 105, 0.72)",
      boxShadow: "inset 0 0 0 3px rgba(255, 245, 192, 0.82)",
    };
    for (const move of movesBySource.get(selectedSquare) ?? []) {
      styles[move.to] = {
        ...styles[move.to],
        background: move.to === selectedSquare
          ? "rgba(246, 211, 105, 0.9)"
          : "radial-gradient(circle, rgba(246, 211, 105, 0.92) 0 18%, rgba(30, 35, 27, 0.26) 20% 100%)",
      };
    }
    return styles;
  }, [movesBySource, selectedSquare]);

  const humanCanMove = game.status === "running" && game.turn !== game.bot_color;

  async function submit(move: LegalMove) {
    setSelectedSquare(null);
    setPromotionChoices([]);
    setError("");
    try {
      setGame(await post("/api/move", { token: move.token }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  function chooseTarget(sourceSquare: string, targetSquare: string) {
    const choices = moveIndex.get(`${sourceSquare}-${targetSquare}`) ?? [];
    if (choices.length === 1) {
      void submit(choices[0]);
      return true;
    }
    if (choices.length > 1) {
      setSelectedSquare(null);
      setPromotionChoices(choices);
    }
    return false;
  }

  function onPieceDrop(sourceSquare: string, targetSquare: string) {
    if (!humanCanMove) return false;
    return chooseTarget(sourceSquare, targetSquare);
  }

  function onSquareClick(square: string) {
    if (!humanCanMove) return;
    if (selectedSquare === square) {
      setSelectedSquare(null);
      return;
    }
    if (selectedSquare && moveIndex.has(`${selectedSquare}-${square}`)) {
      chooseTarget(selectedSquare, square);
      return;
    }
    if (movesBySource.has(square)) {
      setPromotionChoices([]);
      setSelectedSquare(square);
      return;
    }
    setSelectedSquare(null);
  }

  async function loadPreview(nextPositionId: number) {
    try {
      const response = await fetch(`/api/preview/${nextPositionId}`);
      if (!response.ok) {
        const payload = await response.json();
        throw new Error(payload.detail ?? "Không thể tải thế cờ");
      }
      setPreview(await response.json());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  function shufflePosition() {
    const nextPositionId = randomPositionId(positionId);
    setPositionId(nextPositionId);
    setPreview(null);
    void loadPreview(nextPositionId);
  }

  async function start() {
    setError("");
    const parsedTime = Number(timeSeconds);
    if (!Number.isInteger(parsedTime) || parsedTime < 10 || parsedTime > 3600) {
      setError("Thời gian phải là số nguyên từ 10 đến 3600 giây.");
      return;
    }
    try {
      const nextGame = await post("/api/start", {
        bot_color: botColor,
        time_seconds: parsedTime,
        chess960_id: positionId,
      });
      setPreview(null);
      setGame(nextGame);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  async function stop() {
    setError("");
    setSelectedSquare(null);
    setPromotionChoices([]);
    try {
      setGame(await post("/api/stop", {}));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  const stationaryCastles = game.legal_moves.filter(
    (move) => move.castling && move.from === move.to,
  );
  const gameActive = game.status === "starting" || game.status === "running";
  const previewVisible = preview?.chess960_id === positionId;
  const boardFen = previewVisible ? preview.fen : game.fen;
  const displayedBotColor: Color = previewVisible ? botColor : game.bot_color;
  const boardOrientation = displayedBotColor === "white" ? "black" : "white";
  const topColor: Color = displayedBotColor === "white" ? "white" : "black";
  const bottomColor: Color = topColor === "white" ? "black" : "white";

  function clock(color: Color) {
    const isBot = displayedBotColor === color;
    const milliseconds = color === "white" ? game.white_ms : game.black_ms;
    const active = game.status === "running" && game.turn === color;
    return (
      <div className={`clock ${active ? "active" : ""}`}>
        <span>{color === "white" ? "Trắng" : "Đen"} · {isBot ? "Bot" : "Người chơi"}</span>
        <strong>{formatClock(milliseconds)}</strong>
      </div>
    );
  }

  return (
    <main>
      <section className="layout">
        <div className="board-column">
          {clock(topColor)}
          <div className="board-wrap">
            {boardFen && (
              <Chessboard
                position={boardFen}
                boardOrientation={boardOrientation}
                onPieceDrop={onPieceDrop}
                onSquareClick={onSquareClick}
                customSquareStyles={squareStyles}
                arePiecesDraggable={humanCanMove}
                animationDuration={420}
              />
            )}
          </div>
          {clock(bottomColor)}
        </div>

        <aside>
          <div className="panel config">
            <h2>Tùy chọn ván đấu</h2>
            <label>
              Màu của bot
              <select value={botColor} onChange={(event) => setBotColor(event.target.value as Color)}>
                <option value="black">Đen</option>
                <option value="white">Trắng</option>
              </select>
            </label>
            <label>
              Thời gian mỗi bên (giây)
              <input
                type="number"
                min="10"
                max="3600"
                value={timeSeconds}
                onChange={(event) => setTimeSeconds(event.target.value)}
                placeholder="Nhập từ 10 đến 3600"
              />
            </label>
            <div className="shuffle-row">
              <span>Thế cờ ngẫu nhiên</span>
              <button
                type="button"
                className="shuffle"
                onClick={shufflePosition}
                disabled={gameActive}
              >
                ↻ Xáo lại
              </button>
            </div>
            <div className="game-actions">
              <button className="primary" onClick={start}>
                {game.status === "idle" ? "Bắt đầu" : "Ván mới"}
              </button>
              {gameActive && <button className="stop" onClick={stop}>Dừng ván</button>}
            </div>
          </div>

          {game.result && (
            <div className={`panel notice result ${resultTone(game.result, game.bot_color)}`}>
              <strong>{resultLabel(game.result, game.bot_color)}{game.termination ? ` · ${game.termination}` : ""}</strong>
            </div>
          )}
          {error && (
            <div className="panel notice danger"><span>{error}</span></div>
          )}

          {stationaryCastles.length > 0 && (
            <div className="panel castles">
              <h2>Nhập thành</h2>
              {stationaryCastles.map((move) => (
                <button key={move.token} onClick={() => submit(move)}>
                  {move.castling === "kingside" ? "O-O" : "O-O-O"}
                </button>
              ))}
            </div>
          )}

          {promotionChoices.length > 0 && (
            <div className="panel promotion success">
              <h2>Phong cấp thành</h2>
              {promotionChoices.map((move) => (
                <button key={move.token} onClick={() => submit(move)}>{move.promotion}</button>
              ))}
            </div>
          )}

          <div className="panel moves">
            <h2>Lịch sử nước đi</h2>
            {game.history.length > 0 ? (
              <ol>{game.history.map((move) => <li key={move.ply}>{move.san}</li>)}</ol>
            ) : (
              <p className="empty">Chưa có nước đi</p>
            )}
          </div>
        </aside>
      </section>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
