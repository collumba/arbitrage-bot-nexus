"""
╔══════════════════════════════════════════════════════════════╗
║       ARBITRAGE BOT — MAIN SERVER (FastAPI + WebSocket)      ║
║       5 Estratégias · Paper/Live · Dashboard em tempo real   ║
╚══════════════════════════════════════════════════════════════╝
"""
import asyncio
import json
import time
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
import uvicorn

from config import (
    EXCHANGES, STRATEGIES, TRADING_MODE, INITIAL_BALANCE_USD,
    SERVER_HOST, SERVER_PORT, RISK,
)
from exchange.connector import ExchangeConnector
from utils.portfolio import PortfolioManager
from engines.cross_exchange import CrossExchangeEngine
from engines.triangular import TriangularEngine
from engines.statistical import StatisticalEngine
from engines.funding_rate import FundingRateEngine
from engines.dex_cex import DexCexEngine


# ─── GLOBALS ────────────────────────────────────────────────
connector = ExchangeConnector()
portfolio = PortfolioManager(INITIAL_BALANCE_USD, TRADING_MODE)
engines: dict[str, object] = {}
engine_tasks: dict[str, asyncio.Task] = {}
ws_clients: list[WebSocket] = []


async def start_engines():
    """Initialize and start all enabled strategy engines"""
    print("\n╔══════════════════════════════════════════════════╗")
    print("║       ARBITRAGE BOT — INITIALIZING               ║")
    print(f"║       Mode: {TRADING_MODE.upper():>6}  |  Balance: ${INITIAL_BALANCE_USD:,.0f}       ║")
    print("╚══════════════════════════════════════════════════╝\n")

    # Connect to exchanges
    print("→ Connecting to exchanges...")
    for ex_id, ex_config in EXCHANGES.items():
        try:
            await connector.connect(ex_id, ex_config)
        except Exception as e:
            print(f"  ✗ Skipping {ex_id}: {e}")

    if not connector.get_connected_exchanges():
        print("\n⚠ No exchanges connected. Running in simulation-only mode.")
        # Create a minimal binance connection for price data
        try:
            await connector.connect("binance", {"sandbox": True})
        except Exception:
            pass

    # Initialize strategy engines
    print("\n→ Starting strategy engines...")

    if STRATEGIES["cross_exchange"]["enabled"]:
        engines["cross_exchange"] = CrossExchangeEngine(
            STRATEGIES["cross_exchange"], connector, portfolio
        )

    if STRATEGIES["triangular"]["enabled"]:
        engines["triangular"] = TriangularEngine(
            STRATEGIES["triangular"], connector, portfolio
        )

    if STRATEGIES["statistical"]["enabled"]:
        engines["statistical"] = StatisticalEngine(
            STRATEGIES["statistical"], connector, portfolio
        )

    if STRATEGIES["funding_rate"]["enabled"]:
        engines["funding_rate"] = FundingRateEngine(
            STRATEGIES["funding_rate"], connector, portfolio
        )

    if STRATEGIES["dex_cex"]["enabled"]:
        engines["dex_cex"] = DexCexEngine(
            STRATEGIES["dex_cex"], connector, portfolio
        )

    # Start engine loops
    for name, engine in engines.items():
        task = asyncio.create_task(engine.run())
        engine_tasks[name] = task
        print(f"  ✓ {name} engine started")

    # Start WebSocket broadcaster
    asyncio.create_task(broadcast_loop())

    print(f"\n✦ All systems online. Dashboard: http://localhost:{SERVER_PORT}")
    print(f"  WebSocket: ws://localhost:{SERVER_PORT}/ws\n")


async def stop_engines():
    """Stop all engines and disconnect"""
    for engine in engines.values():
        engine.stop()
    for task in engine_tasks.values():
        task.cancel()
    # Cleanup DEX sessions
    dex = engines.get("dex_cex")
    if dex and hasattr(dex, "cleanup"):
        await dex.cleanup()
    await connector.disconnect_all()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await start_engines()
    yield
    await stop_engines()


# ─── FASTAPI APP ────────────────────────────────────────────
app = FastAPI(title="Arbitrage Bot", lifespan=lifespan)


# Serve dashboard
dashboard_dir = Path(__file__).parent / "dashboard"


@app.get("/")
async def serve_dashboard():
    html_path = dashboard_dir / "index.html"
    if html_path.exists():
        return FileResponse(html_path)
    return HTMLResponse("<h1>Dashboard not found</h1>")


# ─── REST API ───────────────────────────────────────────────

@app.get("/api/status")
async def get_status():
    return {
        "mode": TRADING_MODE,
        "portfolio": portfolio.get_stats(),
        "strategy_breakdown": portfolio.get_strategy_breakdown(),
        "engines": {name: eng.get_status() for name, eng in engines.items()},
        "exchanges": connector.get_connected_exchanges(),
        "risk_config": RISK,
        "timestamp": time.time(),
    }


@app.get("/api/portfolio")
async def get_portfolio():
    return portfolio.get_stats()


@app.get("/api/strategies")
async def get_strategies():
    return {name: eng.get_status() for name, eng in engines.items()}


@app.get("/api/trades")
async def get_trades():
    return {
        "trades": [t.to_dict() for t in portfolio.trades[-100:]],
        "total": len(portfolio.trades),
    }


@app.post("/api/engine/{engine_name}/toggle")
async def toggle_engine(engine_name: str):
    engine = engines.get(engine_name)
    if not engine:
        return {"error": "Engine not found"}

    if engine.running:
        engine.stop()
        return {"status": "stopped", "engine": engine_name}
    else:
        task = asyncio.create_task(engine.run())
        engine_tasks[engine_name] = task
        return {"status": "started", "engine": engine_name}


@app.post("/api/mode/{mode}")
async def switch_mode(mode: str):
    global portfolio
    if mode not in ("paper", "live"):
        return {"error": "Mode must be 'paper' or 'live'"}

    portfolio = PortfolioManager(INITIAL_BALANCE_USD, mode)
    for engine in engines.values():
        engine.portfolio = portfolio

    return {"status": "ok", "mode": mode}


# ─── WEBSOCKET ──────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    ws_clients.append(ws)
    try:
        # Send initial state
        await ws.send_json({
            "type": "init",
            "data": {
                "mode": TRADING_MODE,
                "portfolio": portfolio.get_stats(),
                "engines": {name: eng.get_status() for name, eng in engines.items()},
            }
        })

        while True:
            # Keep connection alive and handle commands
            try:
                msg = await asyncio.wait_for(ws.receive_text(), timeout=30)
                data = json.loads(msg)

                if data.get("action") == "toggle_engine":
                    engine_name = data.get("engine")
                    engine = engines.get(engine_name)
                    if engine:
                        if engine.running:
                            engine.stop()
                        else:
                            task = asyncio.create_task(engine.run())
                            engine_tasks[engine_name] = task

            except asyncio.TimeoutError:
                # Send ping
                await ws.send_json({"type": "ping"})

    except WebSocketDisconnect:
        pass
    finally:
        if ws in ws_clients:
            ws_clients.remove(ws)


async def broadcast_loop():
    """Broadcast updates to all WebSocket clients every second"""
    while True:
        if ws_clients:
            data = {
                "type": "update",
                "data": {
                    "portfolio": portfolio.get_stats(),
                    "strategy_breakdown": portfolio.get_strategy_breakdown(),
                    "engines": {name: eng.get_status() for name, eng in engines.items()},
                    "timestamp": time.time(),
                }
            }
            dead = []
            for ws in ws_clients:
                try:
                    await ws.send_json(data)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                ws_clients.remove(ws)

        await asyncio.sleep(1)


# ─── MAIN ───────────────────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=SERVER_HOST,
        port=SERVER_PORT,
        reload=False,
        log_level="info",
    )
