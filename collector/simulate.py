"""Simulador de ESP32 para testar o coletor (cliente WebSocket, só precisa do pacote `websockets`).

    python simulate.py                          # motor normal, 1800 rpm
    python simulate.py --state unbalance        # normal | unbalance | looseness | stopped
    python simulate.py --drop 0.02 --seconds 30 # perde 2% dos pacotes, encerra em 30 s
"""
import argparse
import asyncio
import json
import math
import random
import struct
import time

import websockets

FS, COUNT, LSB_G = 1600, 16, 0.0039      # taxa (Hz), amostras por pacote, g por LSB
# (amplitude em 1x, em 2x, harmônicos 3x..6x) em g, por estado do motor
STATES = {"stopped": (0, 0, 0), "normal": (.02, .005, 0), "unbalance": (.12, .01, 0), "looseness": (.04, .01, .03)}


def sample(n, state, f1):
    a1, a2, ah = STATES[state]
    w = 2 * math.pi * f1 * n / FS
    x = a1 * math.sin(w) + a2 * math.sin(2 * w + .5) + sum(ah * math.sin(h * w + h) for h in range(3, 7))
    y = a1 * math.cos(w) + a2 * math.cos(2 * w + .5) + sum(ah * math.cos(h * w + h) for h in range(3, 7))
    z = 1.0 + .3 * a1 * math.sin(w + 1)                       # gravidade no eixo Z
    out = []
    for g in (x, y, z):
        g += random.gauss(0, .003)
        out.append(max(-512, min(511, round(g / LSB_G))))     # int16 do ADXL345 (±2 g, full-res)
    return out


def packet(seq, first_n, state, f1):
    """Pacote: A5 5A | seq u16 | count u8 | 0 | count x (x,y,z int16), little-endian."""
    body = b"".join(struct.pack("<3h", *sample(first_n + i, state, f1)) for i in range(COUNT))
    return struct.pack("<2sHBB", b"\xa5\x5a", seq, COUNT, 0) + body


async def main(a):
    async with websockets.connect(a.url, max_size=None) as ws:
        await ws.send(json.dumps({"type": "hello", "device": "simulador", "fw": "sim", "fs": FS,
                                  "lsb_g": LSB_G, "range_g": 2}))

        async def listen():
            async for msg in ws:
                print("<-", msg)
        task = asyncio.create_task(listen())

        print(f"Conectado a {a.url}: {a.state}, {a.rpm:.0f} rpm. Ctrl+C para parar.")
        seq, n, t0 = 0, 0, time.monotonic()
        try:
            while not a.seconds or time.monotonic() - t0 < a.seconds:
                if not (a.drop and random.random() < a.drop):       # perda simulada: seq avança, nada é enviado
                    await ws.send(packet(seq, n, a.state, a.rpm / 60))
                seq, n = (seq + 1) & 0xFFFF, n + COUNT
                await asyncio.sleep(max(0, t0 + n / FS - time.monotonic()))
        finally:
            task.cancel()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--url", default="ws://127.0.0.1:8765/ws/device")
    p.add_argument("--state", choices=STATES, default="normal")
    p.add_argument("--rpm", type=float, default=1800)
    p.add_argument("--drop", type=float, default=0.0, help="probabilidade de perder cada pacote")
    p.add_argument("--seconds", type=float, default=0, help="encerra após N s (0 = até Ctrl+C)")
    try:
        asyncio.run(main(p.parse_args()))
    except KeyboardInterrupt:
        pass
