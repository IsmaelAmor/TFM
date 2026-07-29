"""
main.py — Backend FastAPI del TFM (T23, T25, T26, T30, T32).
Arrancar desde backend/:  uvicorn main:app --reload --port 8000
"""
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from ib_async import IB   

load_dotenv()

IB_HOST = os.getenv("IB_HOST", "127.0.0.1")
IB_PORT = int(os.getenv("IB_PORT", "4002"))
IB_CLIENT_ID = int(os.getenv("IB_CLIENT_ID", "1"))
FRONT_ORIGIN = os.getenv("FRONT_ORIGIN", "http://localhost:4200")

ib = IB()


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await ib.connectAsync(IB_HOST, IB_PORT, clientId=IB_CLIENT_ID, timeout=10)
        print(f"✓ Conectado a IB Gateway {IB_HOST}:{IB_PORT}")
    except Exception as e:
        print(f"⚠ No se pudo conectar a IB Gateway al arrancar: {e}")
    yield
    if ib.isConnected():
        ib.disconnect()


app = FastAPI(title="TFM Cartera IBKR", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONT_ORIGIN],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def ensure_connected():
    """Reconecta si la sesión con IB Gateway se ha caído (reinicio diario)."""
    if not ib.isConnected():
        try:
            await ib.connectAsync(IB_HOST, IB_PORT, clientId=IB_CLIENT_ID, timeout=10)
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"IB Gateway no disponible: {e}")


@app.get("/api/status")
async def status():
    """T23 — Health-check del propio servidor."""
    return {"service": "backend-tfm", "status": "ok"}


@app.get("/api/session")
async def session():
    """T30 — Estado de la sesión con IB Gateway."""
    return {
        "connected": ib.isConnected(),
        "host": IB_HOST,
        "port": IB_PORT,
        "clientId": IB_CLIENT_ID,
        "accounts": ib.managedAccounts() if ib.isConnected() else [],
    }


@app.get("/api/account")
async def account():
    """T32 — Resumen de cuenta (saldo, valor neto, fondos disponibles)."""
    await ensure_connected()
    summary = await ib.accountSummaryAsync()
    interesting = {"NetLiquidation", "TotalCashValue", "AvailableFunds", "BuyingPower"}
    return [
        {"account": s.account, "tag": s.tag, "value": s.value, "currency": s.currency}
        for s in summary
        if s.tag in interesting
    ]


@app.get("/api/portfolio")
async def portfolio():
    """T31 — Posiciones abiertas de la cartera."""
    await ensure_connected()
    return [
        {
            "symbol": p.contract.symbol,
            "secType": p.contract.secType,
            "currency": p.contract.currency,
            "position": p.position,
            "avgCost": p.avgCost,
        }
        for p in ib.positions()
    ]