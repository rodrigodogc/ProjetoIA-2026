"""Núcleo: recebe amostras do ESP32, alimenta a UI ao vivo e controla gravações."""
from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from datetime import datetime

import numpy as np
from fastapi import WebSocket

from . import dsp
from .protocol import ProtocolError, parse_packets
from .recorder import Recording
from .storage import Store, slug

RING = 8192          # amostras guardadas para o espectro (~5 s a 1,6 kHz)
SPEC_N = 1024        # tamanho da FFT ao vivo
STALE_S = 1.5        # sem dados há mais que isso = "parado"
PUMP_DT = 0.05       # a UI recebe ondas a 20 Hz, espectro/status a 5 Hz

DEFAULT_DEVICE = {"name": "esp32", "fw": "", "fs": 1600.0, "lsb_g": 0.0039, "range_g": 2.0, "ip": ""}


class ApiError(Exception):
    def __init__(self, status: int, detail: str):
        self.status, self.detail = status, detail


class Collector:
    def __init__(self, store: Store):
        self.store = store
        self.device_ws: WebSocket | None = None
        self.device = dict(DEFAULT_DEVICE)
        self.ui_clients: set[WebSocket] = set()

        self.ring = np.zeros((RING, 3), np.float32)
        self.pending: list[np.ndarray] = []
        self.reset_stream()

        self.state = "idle"            # idle | countdown | recording
        self.params: dict | None = None
        self.countdown_end = 0.0
        self.rec: Recording | None = None
        self.last_saved: str | None = None

    # ------------------------------------------------------------------ fluxo
    def reset_stream(self) -> None:
        self.last_seq: int | None = None
        self.packets = 0
        self.lost = 0
        self.samples = 0
        self.clipped = 0
        self.proto_errors = 0
        self.last_data_t: float | None = None
        self.ring_n = 0
        self.rate_win: deque[tuple[float, int]] = deque()
        self.pending.clear()

    @property
    def connected(self) -> bool:
        return self.device_ws is not None

    @property
    def fs(self) -> float:
        return float(self.device["fs"])

    def age(self) -> float:
        return float("inf") if self.last_data_t is None else time.monotonic() - self.last_data_t

    def rate_hz(self) -> float | None:
        w = self.rate_win
        if len(w) < 2 or w[-1][0] - w[0][0] < 0.5:
            return None
        return sum(n for _, n in list(w)[1:]) / (w[-1][0] - w[0][0])

    def _ring_push(self, g: np.ndarray) -> None:
        total = len(g)
        if total >= RING:
            g = g[-RING:]
        n = len(g)
        i = self.ring_n % RING
        first = min(n, RING - i)
        self.ring[i : i + first] = g[:first]
        if n > first:
            self.ring[: n - first] = g[first:]
        self.ring_n += total

    def _ring_last(self, n: int) -> np.ndarray:
        n = min(n, self.ring_n, RING)
        end = self.ring_n % RING
        return self.ring[np.arange(end - n, end) % RING]

    # --------------------------------------------------------------- dispositivo
    async def on_device_connect(self, ws: WebSocket) -> None:
        old = self.device_ws
        if old is not None:
            self._finish_recording("disconnect")
            try:
                await old.close(code=1012)
            except Exception:
                pass
        self.device_ws = ws
        self.device = dict(DEFAULT_DEVICE, ip=ws.client.host if ws.client else "")
        self.reset_stream()
        await self.send_device({"type": "welcome", "server": "vibration-collector", "protocol": 1,
                                "recording": self.state == "recording"})
        await self.event("info", f"Dispositivo conectado ({self.device['ip']})")
        await self.broadcast_status()

    async def on_device_disconnect(self, ws: WebSocket) -> None:
        if ws is not self.device_ws:
            return
        self.device_ws = None
        was = self.state
        if was == "recording":
            self._finish_recording("disconnect")
        elif was == "countdown":
            self.state, self.params = "idle", None
        await self.event("warn", "Dispositivo desconectado")
        await self.broadcast_status()

    async def on_device_text(self, text: str) -> None:
        try:
            d = json.loads(text)
        except ValueError:
            return
        if d.get("type") == "hello":
            try:
                fs = min(max(float(d.get("fs", 1600)), 10.0), 20000.0)
                lsb = float(d.get("lsb_g", 0.0039))
                rng = float(d.get("range_g", 2.0))
            except (TypeError, ValueError):
                return
            self.device.update(fs=fs, lsb_g=lsb, range_g=rng,
                               name=str(d.get("device", "esp32"))[:40], fw=str(d.get("fw", ""))[:20])
            self.last_seq = None
            await self.broadcast_status()
        elif d.get("type") == "ping":
            await self.send_device({"type": "pong"})

    async def send_device(self, msg: dict) -> None:
        if self.device_ws is None:
            return
        try:
            await self.device_ws.send_text(json.dumps(msg))
        except Exception:
            pass

    # --------------------------------------------------------------- ingestão
    def ingest_bytes(self, buf: bytes) -> None:
        try:
            packets = parse_packets(buf)
        except ProtocolError:
            self.proto_errors += 1
            return
        for seq, raw in packets:
            self._ingest_packet(seq, raw)

    def _ingest_packet(self, seq: int, raw: np.ndarray) -> None:
        lost = 0
        if self.last_seq is not None:
            lost = (seq - ((self.last_seq + 1) & 0xFFFF)) & 0xFFFF
            if lost > 0x8000:      # duplicado/fora de ordem: não conta como perda
                lost = 0
        self.last_seq = seq
        self.packets += 1
        if lost:
            self.lost += lost
            if self.rec:
                self.rec.mark_gap(lost, len(raw))

        d = self.device
        g = raw.astype(np.float32) * d["lsb_g"]
        clip = int((np.abs(g) >= d["range_g"] * 0.98).any(axis=1).sum())
        self.clipped += clip
        self.samples += len(raw)
        now = time.monotonic()
        self.last_data_t = now
        self.rate_win.append((now, len(raw)))
        while self.rate_win and now - self.rate_win[0][0] > 3.0:
            self.rate_win.popleft()

        self._ring_push(g)
        if self.ui_clients:
            self.pending.append(g)

        if self.state == "recording" and self.rec:
            self.rec.clipped += clip
            if self.rec.write(raw):
                self._finish_recording("target")

    # --------------------------------------------------------------- gravação
    def start_recording(self, req) -> None:
        if not self.connected:
            raise ApiError(409, "Dispositivo não conectado")
        if self.state != "idle":
            raise ApiError(409, "Já existe uma gravação em andamento")
        label = slug(req.label)
        if not label:
            raise ApiError(422, "Classe inválida")
        speed = slug(req.speed)
        self.params = {
            "label": label, "speed": speed, "session": slug(req.session, "1"),
            "notes": req.notes.strip(), "duration_s": req.duration_s, "trim_s": req.trim_s,
        }
        self.store.ensure_in_config(label, speed)
        if req.delay_s > 0:
            self.state = "countdown"
            self.countdown_end = time.monotonic() + req.delay_s
            self._schedule(self.broadcast_status())
        else:
            self._begin()

    def _begin(self) -> None:
        p, d = self.params, self.device
        now = datetime.now().astimezone()
        rid = self.store.new_id(p["label"], p["speed"], p["session"], now)
        meta = {
            "id": rid, "label": p["label"], "speed": p["speed"], "session": p["session"],
            "notes": p["notes"], "started_at": now.isoformat(timespec="seconds"),
            "device": d["name"], "fw": d["fw"], "fs": d["fs"], "lsb_g": d["lsb_g"], "range_g": d["range_g"],
            "axes": ["x", "y", "z"], "target_duration_s": p["duration_s"], "trim_s": p["trim_s"],
            "format": "int16 little-endian, shape (n_samples, 3) = x,y,z; g = raw * lsb_g",
        }
        self.rec = Recording(self.store, rid, meta, int(round(p["duration_s"] * d["fs"])))
        self.state = "recording"
        self._schedule(self._notify_recording(True))
        self._schedule(self.broadcast_status())

    def stop_recording(self, save: bool = True) -> dict | None:
        if self.state == "countdown":
            self.state, self.params = "idle", None
            self._schedule(self.broadcast_status())
            return None
        if self.state != "recording" or self.rec is None:
            raise ApiError(409, "Nenhuma gravação em andamento")
        if save:
            return self._finish_recording("user")
        self.rec.cancel()
        self._reset_recording()
        return None

    def _finish_recording(self, stopped_by: str) -> dict | None:
        if self.rec is None:
            return None
        meta = self.rec.finish(stopped_by)
        if meta:
            self.last_saved = meta["id"]
        self._reset_recording()
        if meta:
            level = "ok" if meta["quality"] == "ok" else "warn"
            self._schedule(self.event(level, f"Gravação salva: {meta['id']}"))
        return meta

    def _reset_recording(self) -> None:
        self.rec, self.params, self.state = None, None, "idle"
        self._schedule(self._notify_recording(False))
        self._schedule(self.broadcast_status())

    async def _notify_recording(self, active: bool) -> None:
        await self.send_device({"type": "recording", "active": active,
                                "label": (self.params or {}).get("label", "")})

    @staticmethod
    def _schedule(coro) -> None:
        asyncio.get_running_loop().create_task(coro)

    # --------------------------------------------------------------- UI
    def rec_status(self) -> dict:
        out = {"state": self.state, "last_saved": self.last_saved}
        if self.state == "countdown":
            out.update(label=self.params["label"], countdown_s=max(0.0, self.countdown_end - time.monotonic()))
        elif self.state == "recording" and self.rec:
            out.update(id=self.rec.id, label=self.params["label"], elapsed_s=self.rec.n / self.fs,
                       target_s=self.rec.target / self.fs, lost_packets=self.rec.lost_packets)
        return out

    def status(self) -> dict:
        age = self.age()
        rate = self.rate_hz()
        return {
            "t": "status",
            "connected": self.connected,
            "device": self.device,
            "rate_hz": None if rate is None else round(rate, 1),
            "stale": self.connected and age > STALE_S,
            "packets": self.packets, "lost_packets": self.lost, "samples": self.samples,
            "clipped": self.clipped, "proto_errors": self.proto_errors,
            "recording": self.rec_status(),
        }

    async def broadcast(self, msg: dict) -> None:
        if not self.ui_clients:
            return
        text = json.dumps(msg, separators=(",", ":"))
        for ws in list(self.ui_clients):
            try:
                await asyncio.wait_for(ws.send_text(text), 1.0)
            except Exception:
                self.ui_clients.discard(ws)

    async def broadcast_status(self) -> None:
        await self.broadcast(self.status())

    async def event(self, level: str, text: str) -> None:
        await self.broadcast({"t": "event", "level": level, "text": text})

    async def _push_wave(self) -> None:
        if not self.pending:
            return
        g = np.concatenate(self.pending)
        self.pending.clear()
        r = np.round(g.T, 4)
        await self.broadcast({"t": "wave", "fs": self.fs, "n": len(g),
                              "x": r[0].tolist(), "y": r[1].tolist(), "z": r[2].tolist()})

    async def _push_spectrum(self) -> None:
        if self.ring_n < SPEC_N or self.age() > STALE_S:
            return
        g = self._ring_last(SPEC_N).astype(np.float64)
        amp = dsp.amp_spectrum(g)
        await self.broadcast({
            "t": "spectrum", "fs": self.fs, "n": SPEC_N,
            "amp": np.round(amp.T, 5).tolist(),
            "peaks": dsp.dominant(amp, self.fs, SPEC_N),
            "rms": np.round(g.std(axis=0), 5).tolist(),
            "mean": np.round(g.mean(axis=0), 4).tolist(),
            "p2p": np.round(np.ptp(g, axis=0), 4).tolist(),
        })

    async def pump(self) -> None:
        """Laço de fundo: empurra dados para as UIs e cuida do contador regressivo."""
        tick = 0
        while True:
            await asyncio.sleep(PUMP_DT)
            tick += 1
            if self.state == "countdown" and time.monotonic() >= self.countdown_end:
                self._begin()
            if not self.ui_clients:
                self.pending.clear()
                continue
            await self._push_wave()
            if tick % 4 == 0:
                await self._push_spectrum()
                await self.broadcast_status()
