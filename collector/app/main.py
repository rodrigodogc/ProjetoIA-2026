"""API HTTP + WebSockets + frontend estático."""
from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import dsp
from .collector import ApiError, Collector
from .storage import Store, slug

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
DATA = Path(os.environ.get("COLLECTOR_DATA", ROOT / "data"))

store = Store(DATA)
collector = Collector(store)


@asynccontextmanager
async def lifespan(_: FastAPI):
    task = asyncio.create_task(collector.pump())
    yield
    task.cancel()


app = FastAPI(title="Coletor de vibração", lifespan=lifespan)


@app.exception_handler(ApiError)
async def _api_error(_: Request, e: ApiError):
    return JSONResponse({"detail": e.detail}, status_code=e.status)


# ----------------------------------------------------------------- modelos
class StartReq(BaseModel):
    label: str = Field(min_length=1, max_length=60)
    speed: str = Field(default="", max_length=40)
    session: str = Field(default="1", max_length=20)
    notes: str = Field(default="", max_length=1000)
    duration_s: float = Field(default=90, ge=1, le=3600)
    delay_s: float = Field(default=0, ge=0, le=120)
    trim_s: float = Field(default=2.0, ge=0, le=30)


class ConfigIn(BaseModel):
    classes: list[str] | None = None
    speeds: list[str] | None = None
    targets: dict | None = None
    trim_s: float | None = None


class PatchReq(BaseModel):
    label: str | None = None
    speed: str | None = None
    session: str | None = None
    notes: str | None = Field(default=None, max_length=1000)


# ----------------------------------------------------------------- REST
@app.get("/api/status")
def get_status():
    return collector.status()


@app.get("/api/config")
def get_config():
    return store.load_config()


@app.put("/api/config")
def put_config(body: ConfigIn):
    cfg = store.load_config()
    for key in ("classes", "speeds"):
        v = getattr(body, key)
        if v is not None:
            cfg[key] = list(dict.fromkeys(s for s in (slug(x) for x in v) if s))
    if body.targets is not None:
        cfg["targets"] = {**cfg["targets"], **body.targets}
    if body.trim_s is not None:
        cfg["trim_s"] = body.trim_s
    store.save_config(cfg)
    return cfg


@app.post("/api/recordings/start")
async def start_recording(body: StartReq):
    collector.start_recording(body)
    return collector.rec_status()


@app.post("/api/recordings/stop")
async def stop_recording():
    return {"saved": collector.stop_recording(save=True)}


@app.post("/api/recordings/cancel")
async def cancel_recording():
    collector.stop_recording(save=False)
    return {"ok": True}


@app.get("/api/recordings")
def list_recordings():
    return store.list()


@app.patch("/api/recordings/{rid}")
def patch_recording(rid: str, body: PatchReq):
    fields = {}
    for k in ("label", "speed", "session"):
        v = getattr(body, k)
        if v is not None:
            fields[k] = slug(v, "1" if k == "session" else "")
    if body.notes is not None:
        fields["notes"] = body.notes.strip()
    meta = store.patch(rid, fields)
    if meta is None:
        raise HTTPException(404, "Gravação não encontrada")
    return meta


@app.delete("/api/recordings/{rid}")
def delete_recording(rid: str):
    if not store.delete(rid):
        raise HTTPException(404, "Gravação não encontrada")
    return {"ok": True}


@app.get("/api/recordings/{rid}/download")
def download_recording(rid: str):
    if store.get(rid) is None or not store.npy_path(rid).exists():
        raise HTTPException(404, "Gravação não encontrada")
    return FileResponse(store.npy_path(rid), filename=f"{rid}.npy")


@app.get("/api/recordings/{rid}/preview")
def preview_recording(rid: str):
    meta = store.get(rid)
    if meta is None or not store.npy_path(rid).exists():
        raise HTTPException(404, "Gravação não encontrada")
    fs = float(meta["fs"])
    g = np.load(store.npy_path(rid)).astype(np.float32) * float(meta["lsb_g"])

    a = int(meta.get("trim_s", 0) * fs)
    b = len(g) - a
    if b - a < fs:            # trim maior que a gravação: usa tudo
        a, b = 0, len(g)
    useful = g[a:b].astype(np.float64)

    win = max(1, int(0.25 * fs))
    m = len(g) // win
    rms = g[: m * win].reshape(m, win, 3).std(axis=1) if m else np.zeros((0, 3))

    mid = (a + b) // 2
    s0 = max(0, min(mid - int(fs), len(g) - int(2 * fs)))
    seg = g[s0 : s0 + int(2 * fs)].astype(np.float64)
    seg = seg - seg.mean(axis=0)

    w = dsp.welch(useful)
    spectrum = None
    if w is not None:
        amp, nper = w
        spectrum = {"df": fs / nper, "amp": np.round(amp.T, 5).tolist(),
                    "peaks": dsp.dominant(amp, fs, nper)}

    return {
        "meta": meta,
        "trim_s": [a / fs, b / fs],
        "rms": {"dt": win / fs, "series": np.round(rms.T, 5).tolist()},
        "wave": {"t0": s0 / fs, "series": np.round(seg.T, 4).tolist()},
        "spectrum": spectrum,
    }


@app.post("/api/open-folder")
def open_folder(request: Request):
    if not request.client or request.client.host not in ("127.0.0.1", "::1"):
        raise HTTPException(403, "Só disponível no próprio computador")
    if not hasattr(os, "startfile"):
        raise HTTPException(501, "Disponível apenas no Windows")
    os.startfile(store.rec_dir)  # noqa: S606
    return {"ok": True}


# ----------------------------------------------------------------- WebSockets
@app.websocket("/ws/device")
async def ws_device(ws: WebSocket):
    """ESP32: texto JSON ("hello") + mensagens binárias com pacotes de amostras."""
    await ws.accept()
    await collector.on_device_connect(ws)
    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            if msg.get("bytes") is not None:
                collector.ingest_bytes(msg["bytes"])
            elif msg.get("text"):
                await collector.on_device_text(msg["text"])
    except Exception:
        pass
    finally:
        await collector.on_device_disconnect(ws)


@app.websocket("/ws/ui")
async def ws_ui(ws: WebSocket):
    await ws.accept()
    collector.ui_clients.add(ws)
    try:
        await ws.send_text(json.dumps(collector.status()))
        while True:
            await ws.receive_text()
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        collector.ui_clients.discard(ws)


# O frontend precisa vir por último, senão engole as rotas acima.
app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
