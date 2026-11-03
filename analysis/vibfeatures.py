"""Carregamento das gravações do coletor e extração de features para classificar falhas em motores.

Ideia central: a assinatura de uma falha está nas **ordens** da rotação (1×, 2×, 3×, 0,5×...) e nos impactos
(curtose), não em frequências absolutas. Por isso estimamos a rotação de cada gravação e medimos as
amplitudes em múltiplos dela; assim 1200, 1800 e 2700 rpm "falam a mesma língua".

Este módulo é usado pelo notebook e deve ser o MESMO usado depois na classificação ao vivo (evita divergência
entre treino e uso).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import signal, stats

AXES = "xyz"                       # X radial horizontal, Y axial, Z radial vertical (gravidade)
ORDERS = [0.5, 1, 1.5, 2, 2.5, 3, 4, 5, 6, 7, 8]
BANDS = [(2, 10), (10, 50), (50, 100), (100, 200), (200, 400), (400, 800)]   # Hz absolutos
WIN_S, OVERLAP = 2.0, 0.5
EPS = 1e-5


# ---------------------------------------------------------------------------------------------- dados
@dataclass
class Rec:
    meta: dict
    npy: Path

    @property
    def id(self) -> str: return self.meta["id"]
    @property
    def label(self) -> str: return self.meta["label"]
    @property
    def speed(self) -> str: return self.meta.get("speed", "")
    @property
    def session(self) -> str: return str(self.meta.get("session", "1"))
    @property
    def fs(self) -> float: return float(self.meta["fs"])

    def load(self, trim: bool = True) -> np.ndarray:
        """Sinal em g, shape (n, 3). Com trim=True remove o início/fim marcados na coleta."""
        g = np.load(self.npy).astype(np.float32) * float(self.meta["lsb_g"])
        if trim:
            k = int(self.meta.get("trim_s", 0) * self.fs)
            if len(g) > 2 * k + self.fs:
                g = g[k:len(g) - k]
        return g


def load_recordings(root: str | Path, source: str | None = None, quality_ok: bool = False) -> list[Rec]:
    """Lê os .json/.npy do coletor. `source`: 'simulator' (ou None para tudo)."""
    out = []
    for p in sorted(Path(root).glob("*.json")):
        meta = json.loads(p.read_text("utf-8"))
        npy = p.with_suffix(".npy")
        if not npy.exists():
            continue
        if source is not None and meta.get("source") != source:
            continue
        if quality_ok and meta.get("quality") != "ok":
            continue
        out.append(Rec(meta, npy))
    return out


def inventory(recs: list[Rec]) -> pd.DataFrame:
    return pd.DataFrame([{
        "id": r.id, "classe": r.label, "velocidade": r.speed, "sessao": r.session,
        "duracao_s": r.meta.get("duration_s"), "qualidade": r.meta.get("quality"),
        "perdidos": r.meta.get("lost_packets", 0), "fonte": r.meta.get("source", "coletor"),
    } for r in recs])


# ---------------------------------------------------------------------------------------------- rotação
def estimate_fr(g: np.ndarray, fs: float, expected: tuple[float, float] | None = None, fmin: float = 8.0,
                fmax: float = 110.0, thr: float = 0.6, min_peakiness: float = 6.0) -> float:
    """Frequência de rotação (Hz) de uma gravação, ou NaN se o motor parece parado.

    Espectro de Welch somando os 3 eixos.

    * Com `expected=(f_min, f_max)` (faixa de rotação esperada, vinda do setpoint do motor): o maior pico dentro da
      faixa é o 1×. É o modo recomendado.
    * Sem faixa (estimativa cega): entre os picos de pelo menos `thr` do maior, fica o de menor frequência. Isso é
      **ambíguo por natureza**: um espectro com picos em c, 2c, 3c... não diz se c é 0,5×, 1× ou 2× (desalinhamento com
      2× forte e folga com 0,5× forte se confundem). Serve de fallback; num sistema real, informe o rpm.
    """
    if expected:
        fmin, fmax = expected
        thr = 1.0
    nper = min(8192, len(g))
    f, P = signal.welch(g - g.mean(0), fs=fs, nperseg=nper, axis=0)
    A = np.sqrt(P.sum(axis=1))
    band = (f >= fmin) & (f <= fmax)
    idx, _ = signal.find_peaks(np.where(band, A, 0.0))
    if len(idx) == 0:
        return float("nan")
    if A[idx].max() / (np.median(A[band]) + 1e-12) < min_peakiness:
        return float("nan")
    k = idx[A[idx] >= thr * A[idx].max()].min()
    y0, y1, y2 = A[k - 1], A[k], A[k + 1]
    den = y0 - 2 * y1 + y2
    delta = 0.5 * (y0 - y2) / den if den != 0 else 0.0
    return float((k + np.clip(delta, -0.5, 0.5)) * (f[1] - f[0]))


# ---------------------------------------------------------------------------------------------- janelas
def make_windows(g: np.ndarray, fs: float, win_s: float = WIN_S, overlap: float = OVERLAP):
    """(m, n, 3) janelas e o início (em amostras) de cada uma."""
    n = int(win_s * fs)
    step = max(1, int(n * (1 - overlap)))
    starts = np.arange(0, len(g) - n + 1, step)
    idx = starts[:, None] + np.arange(n)[None, :]
    return g[idx], starts


def _peak_in(amp: np.ndarray, f: np.ndarray, f0: float, tol: float, df: float) -> np.ndarray:
    """Maior amplitude em [f0(1-tol), f0(1+tol)] (pelo menos ±1,5 bin), por janela e eixo."""
    w = max(tol * f0, 1.5 * df)
    m = (f >= f0 - w) & (f <= f0 + w)
    if not m.any():
        return np.full((amp.shape[0],) + amp.shape[2:], EPS)
    return amp[:, m].max(axis=1)


def window_features(W: np.ndarray, fs: float, fr: float) -> dict[str, np.ndarray]:
    """Features de um lote de janelas W (m, n, 3) em g, dada a rotação fr (Hz)."""
    m, n, _ = W.shape
    W = W - W.mean(axis=1, keepdims=True)
    hann = np.hanning(n)
    amp = 2.0 * np.abs(np.fft.rfft(W * hann[None, :, None], axis=1)) / hann.sum()     # (m, nf, 3) pico em g
    f = np.fft.rfftfreq(n, 1.0 / fs)
    df = f[1]
    F: dict[str, np.ndarray] = {}
    lg = lambda x: np.log10(np.asarray(x) + EPS)

    rms = W.std(axis=1)
    peak = np.abs(W).max(axis=1)
    kurt = stats.kurtosis(W, axis=1)
    A1 = {}
    for a, ax in enumerate(AXES):
        F[f"rms_{ax}"] = lg(rms[:, a])
        F[f"crest_{ax}"] = peak[:, a] / (rms[:, a] + EPS)
        F[f"kurt_{ax}"] = kurt[:, a]
    # ordens da rotação
    for k in ORDERS:
        Ak = _peak_in(amp, f, k * fr, 0.04, df)                                    # (m, 3)
        for a, ax in enumerate(AXES):
            F[f"o{k:g}_{ax}"] = lg(Ak[:, a])
        if k == 1:
            A1 = Ak
    for k in (0.5, 2, 3):                                                          # razões em relação ao 1×
        Ak = _peak_in(amp, f, k * fr, 0.04, df)
        for a, ax in enumerate(AXES):
            F[f"r{k:g}_{ax}"] = lg(Ak[:, a]) - lg(A1[:, a])
    # bandas absolutas e forma do espectro
    pw = amp ** 2 / 2.0
    for lo, hi in BANDS:
        mb = (f >= lo) & (f < hi)
        e = pw[:, mb].sum(axis=1)
        for a, ax in enumerate(AXES):
            F[f"b{lo}_{hi}_{ax}"] = 0.5 * np.log10(e[:, a] + EPS ** 2)
    ms = (f >= 2) & (f <= 800)
    tot = pw[:, ms].sum(axis=1) + EPS ** 2
    for a, ax in enumerate(AXES):
        F[f"centroid_{ax}"] = (f[ms][None, :] * pw[:, ms, a]).sum(axis=1) / tot[:, a]
        F[f"hf_{ax}"] = pw[:, f > 200, a].sum(axis=1) / tot[:, a]
    # relações entre eixos (axial/radial): desbalanceamento é radial; desalinhamento aparece no axial
    F["ax_rad_1x"] = F["o1_y"] - 0.5 * (F["o1_x"] + F["o1_z"])
    F["ax_rad_2x"] = F["o2_y"] - 0.5 * (F["o2_x"] + F["o2_z"])
    F["fr"] = np.full(m, np.log10(fr))
    return F


def recording_features(rec: Rec, win_s: float = WIN_S, overlap: float = OVERLAP, fr: float | None = None,
                       extra_noise_g: float = 0.0, bands: dict | None = None) -> pd.DataFrame:
    """Uma linha por janela: metadados + features. Descarta janelas que cruzam buracos de pacotes.

    `bands`: {velocidade: (f_min, f_max) Hz} faixa esperada de rotação (ver `estimate_fr`).
    `extra_noise_g`: ruído branco adicional (g RMS), só para testes de robustez."""
    g = rec.load(trim=True)
    fs = rec.fs
    if extra_noise_g:
        g = g + np.random.default_rng(0).normal(0.0, extra_noise_g, g.shape).astype(np.float32)
    est = estimate_fr(g, fs, expected=(bands or {}).get(rec.speed)) if fr is None else fr
    running = not np.isnan(est)
    fr_used = est if running else 30.0                   # parado: valor neutro (as features de ordem viram ruído)
    W, starts = make_windows(g, fs, win_s, overlap)
    if len(W) == 0:
        return pd.DataFrame()
    keep = np.ones(len(W), bool)
    k_trim = int(rec.meta.get("trim_s", 0) * fs)
    for gap in rec.meta.get("gaps", []):
        at = gap["at_sample"] - k_trim
        keep &= ~((starts <= at) & (at < starts + W.shape[1]))
    F = window_features(W[keep], fs, fr_used)
    df = pd.DataFrame(F)
    df.insert(0, "t0", starts[keep] / fs)
    for col, val in (("fr_est", est), ("id", rec.id), ("sessao", rec.session), ("velocidade", rec.speed), ("classe", rec.label)):
        df.insert(0, col, val)
    return df


def build_dataset(recs: list[Rec], verbose: bool = False, **kw) -> pd.DataFrame:
    parts = []
    for i, r in enumerate(recs):
        parts.append(recording_features(r, **kw))
        if verbose and (i + 1) % 20 == 0:
            print(f"  {i + 1}/{len(recs)} gravações")
    return pd.concat(parts, ignore_index=True)


META_COLS = ["classe", "id", "sessao", "velocidade", "fr_est", "t0"]


def feature_columns(df: pd.DataFrame, use_fr: bool = True) -> list[str]:
    cols = [c for c in df.columns if c not in META_COLS]
    return cols if use_fr else [c for c in cols if c != "fr"]
