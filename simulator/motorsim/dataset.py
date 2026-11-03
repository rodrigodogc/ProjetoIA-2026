"""Gera gravações sintéticas direto em disco, no mesmo formato do coletor (.npy int16 + .json).

Gravar o dataset inteiro pelo WebSocket levaria horas (a taxa é a do sensor); aqui o mesmo motor de sinal roda
mais rápido que o tempo real. Cada sessão = uma montagem do sensor (ressonâncias, inclinação, ODR...), com todas as
classes e velocidades; dentro da sessão, cada gravação sorteia severidade, rpm exato e carga.

    python -m motorsim.dataset --sessions 4 --duration 60       # grava em simulator/data/recordings
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from .engine import FS, LSB_G, RANGE_G, Engine, Params, Session

CLASSES: dict[str, dict] = {
    "parado": {"running": False},
    "normal": {},
    "desbalanceado_leve": {"unbalance": (0.15, 0.40)},
    "desbalanceado_forte": {"unbalance": (0.60, 1.00)},
    "desalinhado": {"misalignment": (0.50, 1.00)},
    "folga": {"looseness": (0.50, 1.00)},
}
# O que dá para provocar na bancada: peso no eixo (leve/forte) e parafuso frouxo. Desalinhado só com --classes.
DEFAULT_CLASSES = ["parado", "normal", "desbalanceado_leve", "desbalanceado_forte", "folga"]
SPEEDS = {"baixa": 1200, "media": 1800, "alta": 2700}      # rpm programado no inversor
TRIM_S = 2.0


def make_params(label: str, rpm_nominal: float, rng: np.random.Generator) -> Params:
    kw = {}
    for k, v in CLASSES[label].items():
        kw[k] = float(rng.uniform(*v)) if isinstance(v, tuple) else v
    return Params(supply="inversor", rpm=float(rpm_nominal * (1 + rng.uniform(-0.02, 0.02))),
                  load=float(rng.uniform(0.3, 0.8)), noise_mg=float(rng.uniform(1.5, 3.0)), **kw)


def record(label: str, speed: str, session: Session, rng: np.random.Generator, duration_s: float):
    p = make_params(label, SPEEDS[speed], rng)
    e = Engine(session, p, seed=int(rng.integers(1 << 31)))
    e.read(int(3 * FS))                                   # assenta filtros e flutuação de velocidade
    n_total = int(round(duration_s * FS))
    blocks, left = [], n_total
    while left > 0:
        k = min(2048, left)
        blocks.append(e.read(k))
        left -= k
    raw = np.concatenate(blocks)
    return raw, p, e.info()


def generate(out: Path, sessions: int, duration_s: float, seed: int, classes=None, speeds=None) -> int:
    out.mkdir(parents=True, exist_ok=True)
    classes = classes or DEFAULT_CLASSES
    speeds = speeds or list(SPEEDS)
    t_start = datetime.now().astimezone()
    count = 0
    t0 = time.perf_counter()
    for sess in range(1, sessions + 1):
        session = Session(seed + 1000 * sess)
        rng = np.random.default_rng(seed + 7 * sess)
        for label in classes:
            for speed in speeds:
                raw, p, info = record(label, speed, session, rng, duration_s)
                when = t_start + timedelta(seconds=count)
                rid = f"{label}_{speed}_s{sess}_{when:%Y%m%d-%H%M%S}"
                clipped = int((np.abs(raw.astype(np.int32)) >= int(RANGE_G * 0.98 / LSB_G)).any(axis=1).sum())
                meta = {
                    "id": rid, "label": label, "speed": speed, "session": str(sess), "notes": "simulado",
                    "started_at": when.isoformat(timespec="seconds"), "device": "sim-motor", "fw": "sim-0.1",
                    "fs": FS, "lsb_g": LSB_G, "range_g": RANGE_G, "axes": ["x", "y", "z"],
                    "target_duration_s": duration_s, "trim_s": TRIM_S,
                    "format": "int16 little-endian, shape (n_samples, 3) = x,y,z; g = raw * lsb_g",
                    "n_samples": int(len(raw)), "duration_s": round(len(raw) / FS, 3), "stopped_by": "target",
                    "lost_packets": 0, "gaps": [], "clipped": clipped, "issues": [], "quality": "ok",
                    # verdade-terreno do simulador: serve para diagnosticar, NÃO para treinar
                    "source": "simulator",
                    "sim": {"params": p.asdict(), "session_seed": session.seed, **{k: round(v, 5) for k, v in info.items()
                                                                                   if k != "session_seed"}},
                }
                np.save(out / f"{rid}.npy", raw)
                (out / f"{rid}.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), "utf-8")
                count += 1
                print(f"[{count:3d}] {rid}  rpm={info['rpm']:.0f}  {time.perf_counter() - t0:.0f}s", flush=True)
    return count


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parents[1] / "data" / "recordings",
                    help="pasta de saída (padrão: simulator/data/recordings, separada dos dados reais do coletor)")
    ap.add_argument("--sessions", type=int, default=4)
    ap.add_argument("--duration", type=float, default=60.0, help="segundos por gravação")
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--classes", nargs="*", choices=list(CLASSES))
    ap.add_argument("--speeds", nargs="*", choices=list(SPEEDS))
    a = ap.parse_args()
    n = generate(a.out, a.sessions, a.duration, a.seed, a.classes, a.speeds)
    print(f"{n} gravações em {a.out}")
