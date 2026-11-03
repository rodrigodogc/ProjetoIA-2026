"""Conexão com o coletor (mesmo protocolo do ESP32, ver collector/README.md) e laço em tempo real."""
from __future__ import annotations

import json
import random
import struct
import threading
import time

import numpy as np
from websockets.sync.client import connect

from .engine import FS, LSB_G, RANGE_G, Engine

BLOCK = 16                 # amostras por pacote, como o firmware
RING = 8192                # amostras recentes guardadas para os gráficos


def build_packet(seq: int, raw: np.ndarray) -> bytes:
    """A5 5A | seq u16 | count u8 | 0 | count × (x, y, z int16), little-endian."""
    return struct.pack("<2sHBB", b"\xa5\x5a", seq & 0xFFFF, len(raw), 0) + np.ascontiguousarray(raw, dtype="<i2").tobytes()


class Link:
    """Cliente WebSocket que reconecta sozinho. `send_block` é chamado pelo laço de tempo real."""

    def __init__(self, device_name: str = "sim-motor"):
        self.device_name = device_name
        self.url = ""
        self.state = "desconectado"        # desconectado | conectando | conectado | reconectando
        self.error = ""
        self.recording = False             # o coletor está gravando?
        self.rec_label = ""
        self.drop = 0.0                    # probabilidade de perder cada pacote
        self.sent = 0
        self.seq = 0
        self._ws = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def connect(self, url: str) -> None:
        self.disconnect()
        self.url = url
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def disconnect(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        self._thread = None
        self.state = "desconectado"
        self.recording = False

    def _run(self) -> None:
        while not self._stop.is_set():
            self.state = "conectando"
            try:
                with connect(self.url, max_size=None, open_timeout=4) as ws:
                    ws.send(json.dumps({"type": "hello", "device": self.device_name, "fw": "sim-0.1", "fs": FS,
                                        "lsb_g": LSB_G, "range_g": RANGE_G}))
                    self.seq, self.error, self._ws, self.state = 0, "", ws, "conectado"
                    while not self._stop.is_set():
                        try:
                            msg = ws.recv(timeout=0.5)
                        except TimeoutError:
                            continue
                        self._on_text(msg)
            except Exception as e:        # recusada, fechada, timeout...
                self.error = str(e) or type(e).__name__
            finally:
                self._ws = None
                self.recording = False
            self.state = "desconectado" if self._stop.is_set() else "reconectando"
            self._stop.wait(2.0)

    def _on_text(self, msg) -> None:
        if not isinstance(msg, str):
            return
        try:
            d = json.loads(msg)
        except ValueError:
            return
        if d.get("type") == "recording":
            self.recording = bool(d.get("active"))
            self.rec_label = d.get("label", "")

    def send_block(self, raw: np.ndarray) -> None:
        ws = self._ws
        if ws is None:
            return
        seq, self.seq = self.seq, (self.seq + 1) & 0xFFFF
        if self.drop and random.random() < self.drop:      # perda simulada: o seq avança, nada é enviado
            return
        try:
            ws.send(build_packet(seq, raw))
            self.sent += 1
        except Exception:
            pass


class Runner(threading.Thread):
    """Gera amostras na taxa real do sensor, guarda as últimas e envia ao coletor se conectado."""

    def __init__(self, engine: Engine, link: Link):
        super().__init__(daemon=True)
        self.engine, self.link = engine, link
        self.ring = np.zeros((RING, 3), np.float32)
        self.total = 0
        self._lock = threading.Lock()
        self._stop_evt = threading.Event()

    def stop(self) -> None:
        self._stop_evt.set()

    def snapshot(self, n: int) -> np.ndarray:
        """Últimas n amostras em g (n, 3), da mais antiga para a mais nova."""
        with self._lock:
            n = min(n, self.total, RING)
            end = self.total % RING
            return self.ring[np.arange(end - n, end) % RING].copy()

    def run(self) -> None:
        nxt = time.perf_counter()
        while not self._stop_evt.is_set():
            raw = self.engine.read(BLOCK)
            g = raw.astype(np.float32) * LSB_G
            with self._lock:
                i = self.total % RING
                idx = (np.arange(BLOCK) + i) % RING
                self.ring[idx] = g
                self.total += BLOCK
            self.link.send_block(raw)
            nxt += BLOCK / self.engine.fs_true
            wait = nxt - time.perf_counter()
            if wait > 0:
                time.sleep(wait)
            elif wait < -1.0:             # ficou muito atrasado: ressincroniza em vez de rajada
                nxt = time.perf_counter()
