"""Espectros e picos para visualização (amplitude de pico, em g)."""
from __future__ import annotations

import numpy as np


def amp_spectrum(x: np.ndarray) -> np.ndarray:
    """x: (n, 3) em g -> amplitude de pico (n//2+1, 3), janela Hann, sem DC."""
    n = len(x)
    w = np.hanning(n)
    X = np.fft.rfft((x - x.mean(axis=0)) * w[:, None], axis=0)
    return 2.0 * np.abs(X) / w.sum()


def welch(x: np.ndarray, nper: int = 1024, overlap: float = 0.5):
    """Espectro médio (Welch). Devolve (amp (nper//2+1, 3), nper) ou None se faltar dado."""
    n = len(x)
    if n < 64:
        return None
    if n < nper:
        nper = 1 << (n.bit_length() - 1)
    step = max(1, int(nper * (1 - overlap)))
    w = np.hanning(nper)
    acc, k = 0.0, 0
    for s in range(0, n - nper + 1, step):
        seg = x[s : s + nper]
        X = np.fft.rfft((seg - seg.mean(axis=0)) * w[:, None], axis=0)
        acc = acc + (2.0 * np.abs(X) / w.sum()) ** 2
        k += 1
    return np.sqrt(acc / k), nper


def dominant(amp: np.ndarray, fs: float, n: int, fmin: float = 3.0) -> list[dict]:
    """Pico dominante por eixo (acima de fmin), com interpolação parabólica."""
    df = fs / n
    k0 = max(2, int(np.ceil(fmin / df)))
    peaks = []
    for a in range(amp.shape[1]):
        col = amp[:, a]
        if len(col) - 1 <= k0 + 1:
            peaks.append({"f": 0.0, "a": 0.0})
            continue
        k = k0 + int(np.argmax(col[k0:-1]))
        y0, y1, y2 = col[k - 1], col[k], col[k + 1]
        den = y0 - 2 * y1 + y2
        delta = float(np.clip(0.5 * (y0 - y2) / den, -0.5, 0.5)) if den != 0 else 0.0
        peaks.append({"f": round((k + delta) * df, 2), "a": round(float(y1), 5)})
    return peaks
