"""Inferidor de falhas em motor: aplicativo único (tkinter), sem depender de nenhuma outra parte do projeto.

Carregue um modelo (.joblib), clique em "Iniciar escuta" e aponte o sensor (ESP32) ou o simulador para a URL mostrada
(ws://<ip deste PC>:8766/ws/device, o mesmo protocolo do coletor). A cada 1 s a última janela de 2 s é classificada e
a falha aparece na tela. Este programa NÃO precisa do coletor: ele ocupa o lugar dele.

    python inferidor.py [--modelo arquivo.joblib] [--porta 8766] [--rpm 1800] [--iniciar]

As funções de features (seção "features") são uma cópia de analysis/vibfeatures.py: se mudar lá, mude aqui.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import signal
import socket
import struct
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

import joblib
import numpy as np
from scipy import signal as sps
from scipy import stats
from websockets.sync.server import serve

HERE = Path(__file__).resolve().parent
CONFIG = HERE / "inferidor.json"  # só guarda o último modelo escolhido pela interface
WIN_S, STEP_S = 2.0, 1.0          # janela classificada e intervalo entre classificações
LONG_S, MIN_S = 10.0, 5.0         # trecho para achar a rotação; mínimo antes de decidir
STALE_S = 1.5                     # sem pacotes há mais que isso = "sem dados"
TIMELINE_S = 120

# ------------------------------------------------------------------------------------------------ features
AXES = "xyz"
ORDERS = [0.5, 1, 1.5, 2, 2.5, 3, 4, 5, 6, 7, 8]
BANDS = [(2, 10), (10, 50), (50, 100), (100, 200), (200, 400), (400, 800)]
EPS = 1e-5


def estimar_fr(g, fs, faixa, thr=1.0, min_peakiness=6.0):
    """Frequência de rotação (Hz) dentro de `faixa`, ou NaN se o motor parece parado."""
    f, P = sps.welch(g - g.mean(0), fs=fs, nperseg=min(8192, len(g)), axis=0)
    A = np.sqrt(P.sum(axis=1))
    band = (f >= faixa[0]) & (f <= faixa[1])
    idx, _ = sps.find_peaks(np.where(band, A, 0.0))
    if len(idx) == 0 or A[idx].max() / (np.median(A[band]) + 1e-12) < min_peakiness:
        return float("nan")
    k = idx[A[idx] >= thr * A[idx].max()].min()
    y0, y1, y2 = A[k - 1], A[k], A[k + 1]
    den = y0 - 2 * y1 + y2
    delta = 0.5 * (y0 - y2) / den if den != 0 else 0.0
    return float((k + np.clip(delta, -0.5, 0.5)) * (f[1] - f[0]))


def _peak_in(amp, f, f0, tol, df):
    w = max(tol * f0, 1.5 * df)
    m = (f >= f0 - w) & (f <= f0 + w)
    if not m.any():
        return np.full((amp.shape[0],) + amp.shape[2:], EPS)
    return amp[:, m].max(axis=1)


def features(W, fs, fr):
    """Features de um lote de janelas W (m, n, 3) em g, dada a rotação fr (Hz)."""
    m, n, _ = W.shape
    W = W - W.mean(axis=1, keepdims=True)
    hann = np.hanning(n)
    amp = 2.0 * np.abs(np.fft.rfft(W * hann[None, :, None], axis=1)) / hann.sum()
    f = np.fft.rfftfreq(n, 1.0 / fs)
    df = f[1]
    F = {}
    lg = lambda x: np.log10(np.asarray(x) + EPS)

    rms = W.std(axis=1)
    peak = np.abs(W).max(axis=1)
    kurt = stats.kurtosis(W, axis=1)
    A1 = {}
    for a, ax in enumerate(AXES):
        F[f"rms_{ax}"] = lg(rms[:, a])
        F[f"crest_{ax}"] = peak[:, a] / (rms[:, a] + EPS)
        F[f"kurt_{ax}"] = kurt[:, a]
    for k in ORDERS:
        Ak = _peak_in(amp, f, k * fr, 0.04, df)
        for a, ax in enumerate(AXES):
            F[f"o{k:g}_{ax}"] = lg(Ak[:, a])
        if k == 1:
            A1 = Ak
    for k in (0.5, 2, 3):
        Ak = _peak_in(amp, f, k * fr, 0.04, df)
        for a, ax in enumerate(AXES):
            F[f"r{k:g}_{ax}"] = lg(Ak[:, a]) - lg(A1[:, a])
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
    F["ax_rad_1x"] = F["o1_y"] - 0.5 * (F["o1_x"] + F["o1_z"])
    F["ax_rad_2x"] = F["o2_y"] - 0.5 * (F["o2_x"] + F["o2_z"])
    F["fr"] = np.full(m, np.log10(fr))
    return F


# ------------------------------------------------------------------------------------------------ sensor + inferência
def pacotes(buf):
    """Pacotes do sensor: A5 5A | seq u16 | n u8 | 0 | n × (x, y, z int16). Vários podem vir juntos."""
    i = 0
    while i + 6 <= len(buf):
        magic, seq, n, _ = struct.unpack_from("<2sHBB", buf, i)
        end = i + 6 + 6 * n
        if magic != b"\xa5\x5a" or end > len(buf):
            return
        yield seq, np.frombuffer(buf, "<i2", 3 * n, i + 6).reshape(n, 3)
        i = end


def grupo(c):
    """Família de uma feature, pelo nome."""
    if c == "fr":
        return "rotação"
    if c.startswith(("rms", "crest", "kurt")):
        return "tempo"
    if c.startswith("ax_rad"):
        return "eixos"
    if c.startswith(("centroid", "hf")):
        return "forma"
    if c.startswith("b"):
        return "bandas"
    return "razões" if c[0] == "r" else "ordens" if c[0] == "o" else "outros"


def detalhes_modelo(caminho, b, classes):
    """Resumo do arquivo do modelo para a barra lateral."""
    m, feats = b["model"], list(b["features"])
    p = m.get_params() if hasattr(m, "get_params") else {}
    nomes = {"RandomForestClassifier": "Random Forest", "ExtraTreesClassifier": "Extra Trees", "SVC": "SVM",
             "LogisticRegression": "Regressão logística", "HistGradientBoostingClassifier": "Gradient Boosting",
             "MLPClassifier": "Rede MLP", "Pipeline": "Pipeline"}
    alg = nomes.get(type(m).__name__, type(m).__name__)
    extra = [t for t in (f"{p['n_estimators']} árvores" if "n_estimators" in p else "",
                         f"folha mín. {p['min_samples_leaf']}" if "min_samples_leaf" in p else "",
                         f"pesos {p['class_weight']}" if p.get("class_weight") else "") if t]
    fam: dict[str, int] = {}
    for c in feats:
        fam[grupo(c)] = fam.get(grupo(c), 0) + 1
    imp = None
    if getattr(m, "feature_importances_", None) is not None:
        imp: dict[str, float] = {}
        for c, v in zip(feats, m.feature_importances_):
            imp[grupo(c)] = imp.get(grupo(c), 0.0) + float(v)
        imp = sorted(imp.items(), key=lambda kv: -kv[1])
    win = b.get("win_s")
    return {"arquivo": Path(caminho).name, "tamanho": os.path.getsize(caminho),
            "salvo": time.strftime("%d/%m/%Y %H:%M", time.localtime(os.path.getmtime(caminho))),
            "algoritmo": alg + (" · " + " · ".join(extra) if extra else ""), "treino": b.get("trained_on", "?"),
            "janela": win, "fs": b.get("fs"), "n_feats": len(feats), "familias": fam, "importancia": imp, "classes": classes,
            "aviso": f"janela do modelo ({win:g} s) difere da usada aqui ({WIN_S:g} s)" if win and abs(win - WIN_S) > 1e-6 else ""}


class Fluxo:
    """Servidor do sensor + classificação. A tela só lê atributos (atribuições atômicas, sem trava)."""

    def __init__(self):
        self.modelo, self.detalhes = None, {}                  # modelo = (estimador, features, classes), trocado de uma vez só
        self.rpm, self.limiar, self.suave = 1800.0, 0.6, 3
        self.srv, self.ws, self.erro = None, None, ""
        self.linha: list[tuple[float, str]] = []              # (instante, classe) para a linha do tempo
        self.zerar()

    def zerar(self):
        self.fs, self.lsb, self.device = 1600.0, 0.0039, ""
        self.buf = np.zeros((0, 3), np.float32)
        self.total = self.valido_de = self.proximo = 0
        self.last_seq = None
        self.hist: list[np.ndarray] = []
        self.lost, self.conectado, self.t_ultimo = 0, False, 0.0
        self.resultado, self.nota = None, ""

    @property
    def faixa(self):
        fr0 = self.rpm / 60.0
        return fr0 * 0.75, fr0 * 1.25                          # onde procurar o 1×

    @property
    def classes(self):
        return self.modelo[2] if self.modelo else []

    def carregar(self, caminho):
        """Troca o modelo (pode ser feito com o sensor transmitindo). Levanta ValueError se o arquivo não servir."""
        b = joblib.load(caminho)
        if not (isinstance(b, dict) and "model" in b and "features" in b):
            raise ValueError("não é um modelo deste projeto (esperado um dicionário com 'model' e 'features')")
        model, feats = b["model"], list(b["features"])
        teste = np.random.default_rng(0).normal(0, 0.02, (1, int(WIN_S * 1666), 3))
        falta = sorted(set(feats) - set(features(teste, 1666.0, 30.0)))
        if falta:
            raise ValueError(f"o modelo usa features que este inferidor não calcula ({', '.join(falta[:3])}...)")
        classes = [str(c) for c in model.classes_]
        det = detalhes_modelo(caminho, b, classes)
        self.modelo, self.detalhes = (model, feats, classes), det
        self.hist, self.resultado, self.linha = [], None, []

    # ---- servidor
    def iniciar(self, porta):
        self.srv = serve(self.atender, "0.0.0.0", porta, max_size=None)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def parar(self):
        srv, ws, self.srv, self.conectado = self.srv, self.ws, None, False
        for fn in ((ws.close if ws else None), (srv.shutdown if srv else None)):
            if fn:
                threading.Thread(target=lambda f=fn: self._seguro(f), daemon=True).start()

    @staticmethod
    def _seguro(fn):
        try:
            fn()
        except Exception:
            pass

    def atender(self, ws):
        """Uma conexão de sensor."""
        if self.ws is not None and self.ws is not ws:          # um sensor por vez: o novo substitui o antigo
            self._seguro(self.ws.close)
        self.ws = ws
        self.zerar()
        self.conectado = True
        try:
            for msg in ws:
                if isinstance(msg, str):
                    d = json.loads(msg)
                    if d.get("type") == "hello":
                        self.fs, self.lsb = float(d["fs"]), float(d["lsb_g"])
                        self.device = str(d.get("device", "sensor"))
                        ws.send(json.dumps({"type": "welcome", "server": "inferidor", "protocol": 1, "recording": False}))
                    elif d.get("type") == "ping":
                        ws.send(json.dumps({"type": "pong"}))
                    continue
                for seq, raw in pacotes(msg):
                    self.entrada(seq, raw)
        except Exception:
            pass
        finally:
            if self.ws is ws:
                self.ws, self.conectado, self.resultado = None, False, None

    def entrada(self, seq, raw):
        if self.last_seq is not None:
            salto = (seq - self.last_seq - 1) & 0xFFFF
            if 0 < salto < 0x8000:                             # perdeu pacotes: a janela só vale depois daqui
                self.lost += salto
                self.valido_de = self.total
        self.last_seq = seq
        self.t_ultimo = time.monotonic()
        fs = self.fs
        self.buf = np.concatenate([self.buf, raw * np.float32(self.lsb)])[-int((LONG_S + WIN_S) * fs):]
        self.total += len(raw)
        if self.total < self.proximo:
            return
        self.proximo = self.total + int(STEP_S * fs)
        if self.modelo is None:
            self.nota = "carregue um modelo para classificar"
        elif len(self.buf) < MIN_S * fs:
            self.nota = f"enchendo o buffer ({len(self.buf) / fs:.0f}/{MIN_S:.0f} s)"
        elif self.total - self.valido_de < int(WIN_S * fs):
            self.nota = "perda de pacotes: esperando uma janela limpa"
        else:
            try:
                self.classificar()
            except Exception as e:                             # um erro aqui não pode derrubar a conexão do sensor
                self.nota = f"erro ao classificar: {e}"

    def classificar(self):
        model, feats, classes = self.modelo                    # uma leitura só: a troca de modelo não pega no meio
        fs, t0 = self.fs, time.perf_counter()
        fr = estimar_fr(self.buf[-int(LONG_S * fs):], fs, self.faixa)
        F = features(self.buf[-int(WIN_S * fs):][None], fs, fr if np.isfinite(fr) else 30.0)   # parado: fr neutro, como no treino
        self.hist = (self.hist + [model.predict_proba(np.array([[F[k][0] for k in feats]]))[0]])[-8:]
        p = np.mean([h for h in self.hist[-self.suave:] if len(h) == len(classes)], axis=0)
        k = int(p.argmax())
        classe = classes[k] if p[k] >= self.limiar else "incerto"
        rms = self.buf[-int(WIN_S * fs):].std(axis=0) * 1000
        self.nota = ""
        self.resultado = {"probs": p, "classes": classes, "conf": float(p[k]), "classe": classe, "melhor": classes[k],
                          "fr": fr, "rms_mg": rms, "ms": (time.perf_counter() - t0) * 1000, "t": time.strftime("%H:%M:%S")}
        self.linha = (self.linha + [(time.time(), classe)])[-400:]


# ------------------------------------------------------------------------------------------------ tela
BG, PANEL, PANEL2, BORDER = "#0b0f14", "#111722", "#161e2c", "#1f2a3b"
FG, MUTED, GRID = "#e7edf5", "#8a9bb0", "#1b2536"
ACCENT, OK, WARN, BAD = "#4cc2ff", "#4ade80", "#fbbf24", "#ff5d6c"
AXIS_COLORS = ["#4cc2ff", "#ffb347", "#7ee08a"]
COR = {"normal": OK, "parado": "#6b7a90", "desbalanceado_leve": WARN, "desbalanceado_forte": BAD, "folga": "#e879f9",
       "desalinhado": "#22d3ee", "incerto": "#475569"}
NOME = {"desbalanceado_leve": "DESBALANCEADO LEVE", "desbalanceado_forte": "DESBALANCEADO FORTE",
        "folga": "FOLGA (parafuso frouxo)"}
cor = lambda c: COR.get(c, "#7aa2f7")
nome = lambda c: NOME.get(c, c.replace("_", " ").upper())


def nice_ticks(a, b, n=5):
    if not b > a:
        return [a]
    raw = (b - a) / n
    p = 10 ** math.floor(math.log10(raw))
    f = raw / p
    step = (1 if f < 1.5 else 2 if f < 3 else 5 if f < 7 else 10) * p
    v = math.ceil(a / step - 1e-9) * step
    out = []
    while v <= b + step * 1e-6:
        out.append(0.0 if abs(v) < step * 1e-9 else round(v, 12))
        v += step
    return out


class Plot:
    """Gráfico de linhas simples num Canvas (eixos, grade, séries decimadas, linhas verticais)."""
    L, R, T, B = 54, 12, 14, 24

    def __init__(self, parent, height):
        self.cv = tk.Canvas(parent, bg=PANEL, highlightthickness=0, height=height)

    def draw(self, series, xr, yr, ylog=False, xfmt=None, ylabel="", vlines=(), empty=""):
        cv = self.cv
        cv.delete("all")
        w, h = cv.winfo_width(), cv.winfo_height()
        if w < 80 or h < 60:
            return
        L, R, T, B = self.L, self.R, self.T, self.B
        pw, ph = w - L - R, h - T - B
        x0, x1 = xr
        y0, y1 = yr

        def fy(v):
            if ylog:
                lo, hi = math.log10(y0), math.log10(y1)
                return T + (1 - (np.log10(np.maximum(v, y0)) - lo) / (hi - lo)) * ph
            return T + (1 - (v - y0) / (y1 - y0)) * ph

        fx = lambda v: L + (v - x0) / (x1 - x0) * pw
        yt = [10 ** e for e in range(math.ceil(math.log10(y0)), math.floor(math.log10(y1)) + 1)] if ylog else nice_ticks(y0, y1, 5)
        ystep = (yt[1] - yt[0]) if len(yt) > 1 else 1
        dec = 0 if ylog else max(0, -math.floor(math.log10(ystep) + 1e-9))
        for v in yt:
            y = fy(v)
            cv.create_line(L, y, L + pw, y, fill=GRID)
            cv.create_text(L - 6, y, text=(f"{v:g}" if ylog else f"{v:.{dec}f}"), fill=MUTED, anchor="e", font=("Consolas", 8))
        for v in nice_ticks(x0, x1, max(3, pw // 90)):
            x = fx(v)
            cv.create_line(x, T, x, T + ph, fill=GRID)
            anchor = "ne" if x > L + pw - 24 else "nw" if x < L + 12 else "n"
            cv.create_text(x, T + ph + 5, text=(xfmt(v) if xfmt else f"{v:g}"), fill=MUTED, anchor=anchor, font=("Consolas", 8))
        if ylabel:
            cv.create_text(L + 6, T + 2, text=ylabel, fill=MUTED, anchor="nw", font=("Consolas", 8))
        for xs, ys, color in series:
            if len(xs) < 2:
                continue
            px = L + (xs - x0) / (x1 - x0) * pw
            py = np.clip(fy(ys), T, T + ph)
            if len(px) > 2 * pw:                                     # decimação min/max por coluna de pixel
                k = -(-len(px) // pw)
                cols = len(px) // k
                m = cols * k
                a = py[:m].reshape(cols, k)
                px = np.repeat(px[:m].reshape(cols, k)[:, 0], 2)
                py = np.stack([a.min(1), a.max(1)], 1).ravel()
            cv.create_line(np.column_stack([px, py]).ravel().tolist(), fill=color, width=1)
        for x, color, label in vlines:
            if x0 <= x <= x1:
                cv.create_line(fx(x), T, fx(x), T + ph, fill=color, dash=(3, 4))
                cv.create_text(fx(x) + 3, T + 16, text=label, fill=color, anchor="nw", font=("Consolas", 8))
        if empty:
            cv.create_text(L + pw / 2, T + ph / 2, text=empty, fill=MUTED, font=("Consolas", 10))


class App(tk.Tk):
    def __init__(self, args):
        super().__init__()
        self.title("Inferidor de falhas em motor")
        self.geometry("1240x860")
        self.minsize(1000, 700)
        self.configure(bg=BG)
        self._style()
        self.fluxo = Fluxo()
        self.shot, self._closing = args.shot, False
        self.v_porta = tk.StringVar(value=str(args.porta))
        self.v_rpm = tk.StringVar(value=f"{args.rpm:g}")
        self.v_limiar = tk.DoubleVar(value=60)
        self.v_suave = tk.DoubleVar(value=3)
        self._build()
        modelo = args.modelo or self._ultimo_modelo() or next(iter(sorted((HERE / "modelos").glob("*.joblib"))), None)
        if modelo:
            self._carregar(modelo)
        if args.iniciar:
            self._toggle_escuta()
        signal.signal(signal.SIGINT, lambda *_: self.after(0, self._close))     # Ctrl+C no terminal
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.after(100, self._tick)
        if self.shot:
            self.after(int(args.shot_after * 1000), self._take_shot)

    # ------------------------------------------------------------------ visual
    def _style(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure(".", background=PANEL, foreground=FG, fieldbackground=PANEL2, bordercolor=BORDER,
                    lightcolor=PANEL2, darkcolor=PANEL2, troughcolor=PANEL2, font=("Segoe UI", 9))
        s.configure("TFrame", background=PANEL)
        s.configure("TLabel", background=PANEL, foreground=FG)
        s.configure("Muted.TLabel", foreground=MUTED)
        s.configure("Val.TLabel", foreground=ACCENT, font=("Consolas", 9))
        s.configure("TLabelframe", background=PANEL, bordercolor=BORDER)
        s.configure("TLabelframe.Label", background=PANEL, foreground=MUTED, font=("Segoe UI", 9, "bold"))
        s.configure("TButton", background=PANEL2, foreground=FG, padding=(8, 4), borderwidth=1)
        s.map("TButton", background=[("active", "#1b2638"), ("disabled", PANEL)], foreground=[("disabled", MUTED)])
        s.configure("Accent.TButton", background="#1f6f9f", foreground="#ffffff")
        s.map("Accent.TButton", background=[("active", "#2a86bd")])
        s.configure("Horizontal.TScale", background=PANEL, troughcolor=PANEL2)
        s.configure("TCombobox", fieldbackground=PANEL2, background=PANEL2, foreground=FG, arrowcolor=FG)
        self.option_add("*TCombobox*Listbox.background", PANEL2)
        self.option_add("*TCombobox*Listbox.foreground", FG)

    def _section(self, parent, title):
        lf = ttk.LabelFrame(parent, text=title, padding=(8, 4))
        lf.pack(fill="x", pady=(0, 6))
        return lf

    def _scale(self, parent, text, var, lo, hi, fmt):
        f = ttk.Frame(parent)
        f.pack(fill="x", pady=1)
        top = ttk.Frame(f)
        top.pack(fill="x")
        ttk.Label(top, text=text).pack(side="left")
        val = ttk.Label(top, style="Val.TLabel")
        val.pack(side="right")
        ttk.Scale(f, from_=lo, to=hi, variable=var, orient="horizontal").pack(fill="x")
        upd = lambda *_: val.config(text=fmt(var.get()))
        var.trace_add("write", upd)
        upd()

    def _build(self):
        root = ttk.Frame(self, padding=8)
        root.pack(fill="both", expand=True)
        root.columnconfigure(1, weight=1)
        root.rowconfigure(0, weight=1)

        left = ttk.Frame(root, width=310)
        left.grid(row=0, column=0, sticky="ns", padx=(0, 8))
        left.grid_propagate(False)

        sec = self._section(left, "Modelo")
        ttk.Button(sec, text="Carregar outro modelo (.joblib)...", style="Accent.TButton", command=self._escolher_modelo).pack(fill="x")
        self.lbl_modelo = ttk.Label(sec, style="Muted.TLabel", wraplength=280, text="nenhum modelo carregado")
        self.lbl_modelo.pack(anchor="w", pady=(4, 0))
        self.det = ttk.Frame(sec)
        self.det.pack(fill="x", pady=(4, 0))

        sec = self._section(left, "Sensor")
        ttk.Label(sec, text="Aponte o sensor ou o simulador para:", style="Muted.TLabel").pack(anchor="w")
        self.e_url = ttk.Entry(sec, state="readonly")
        self.e_url.pack(fill="x", pady=(2, 4))
        pf = ttk.Frame(sec)
        pf.pack(fill="x")
        ttk.Label(pf, text="Porta").pack(side="left")
        ttk.Entry(pf, textvariable=self.v_porta, width=7).pack(side="left", padx=6)
        self.btn_escuta = ttk.Button(pf, text="Iniciar escuta", style="Accent.TButton", command=self._toggle_escuta)
        self.btn_escuta.pack(side="right")
        self.lbl_sensor = ttk.Label(sec, text="escuta desligada", foreground=BAD, wraplength=280)
        self.lbl_sensor.pack(anchor="w", pady=(4, 0))
        self.v_porta.trace_add("write", lambda *_: self._url())

        sec = self._section(left, "Motor")
        rf = ttk.Frame(sec)
        rf.pack(fill="x")
        ttk.Label(rf, text="Rotação aproximada").pack(side="left")
        ttk.Label(rf, text="rpm").pack(side="right")
        ttk.Combobox(rf, textvariable=self.v_rpm, values=["1200", "1800", "2700"], width=7).pack(side="right", padx=6)
        self.lbl_faixa = ttk.Label(sec, style="Muted.TLabel")
        self.lbl_faixa.pack(anchor="w", pady=(2, 0))

        sec = self._section(left, "Decisão")
        self._scale(sec, "Limiar de confiança", self.v_limiar, 30, 95, lambda x: f"{x:.0f} %")
        self._scale(sec, "Média de janelas", self.v_suave, 1, 8, lambda x: f"{x:.0f}")
        ttk.Label(sec, style="Muted.TLabel", wraplength=280,
                  text="Abaixo do limiar a resposta é INCERTO. Mais janelas = resposta mais estável, porém mais lenta.").pack(anchor="w", pady=(4, 0))

        right = ttk.Frame(root)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(3, weight=1)
        right.rowconfigure(4, weight=1)

        card = tk.Frame(right, bg=PANEL2, highlightbackground=BORDER, highlightthickness=1)
        card.grid(row=0, column=0, sticky="ew")
        card.columnconfigure(0, weight=1)
        self.lbl_diag = tk.Label(card, text="", bg=PANEL2, fg=MUTED, font=("Segoe UI", 30, "bold"), anchor="w")
        self.lbl_diag.grid(row=0, column=0, sticky="ew", padx=16, pady=(10, 0))
        self.lbl_sub = tk.Label(card, text="", bg=PANEL2, fg=MUTED, font=("Segoe UI", 11), anchor="w")
        self.lbl_sub.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 10))
        self.lbl_stats = tk.Label(card, text="", bg=PANEL2, fg=MUTED, font=("Consolas", 9), justify="left", anchor="e")
        self.lbl_stats.grid(row=0, column=1, rowspan=2, padx=16)

        self.cv_bars = tk.Canvas(right, bg=PANEL, highlightthickness=0, height=150)
        self.cv_bars.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        self.cv_time = tk.Canvas(right, bg=PANEL, highlightthickness=0, height=62)
        self.cv_time.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        self.p_wave = Plot(right, 200)
        self.p_wave.cv.grid(row=3, column=0, sticky="nsew", pady=(8, 0))
        self.p_spec = Plot(right, 200)
        self.p_spec.cv.grid(row=4, column=0, sticky="nsew", pady=(8, 0))
        self._url()

    # ------------------------------------------------------------------ ações
    def _url(self):
        try:
            ip = socket.gethostbyname(socket.gethostname())
        except OSError:
            ip = "<ip-deste-pc>"
        self.e_url.config(state="normal")
        self.e_url.delete(0, "end")
        self.e_url.insert(0, f"ws://{ip}:{self.v_porta.get()}/ws/device")
        self.e_url.config(state="readonly")

    def _ultimo_modelo(self):
        """Último modelo carregado pela interface (guardado ao lado do programa), se o arquivo ainda existir."""
        try:
            p = Path(json.loads(CONFIG.read_text("utf-8"))["modelo"])
            return p if p.is_file() else None
        except Exception:
            return None

    def _escolher_modelo(self):
        ultimo = self._ultimo_modelo()
        p = filedialog.askopenfilename(title="Escolha o modelo (.joblib)", initialdir=(ultimo.parent if ultimo else HERE / "modelos"),
                                       filetypes=[("Modelo joblib", "*.joblib"), ("Todos os arquivos", "*.*")])
        if p:
            self._carregar(p, lembrar=True)

    def _carregar(self, caminho, lembrar=False):
        """Se o arquivo não servir, o modelo anterior continua valendo."""
        try:
            self.fluxo.carregar(caminho)
        except Exception as e:
            aviso = f"não foi possível carregar {Path(caminho).name}: {(str(e).splitlines() or [type(e).__name__])[0][:90]}"
            self.lbl_modelo.config(text=aviso, foreground=BAD)
            self.after(8000, lambda: self.lbl_modelo.cget("text") == aviso and self.lbl_modelo.config(text=""))
            return
        self.lbl_modelo.config(text="", foreground=FG)
        self._detalhes()
        if lembrar:
            try:
                CONFIG.write_text(json.dumps({"modelo": str(Path(caminho).resolve())}), "utf-8")
            except OSError:
                pass

    def _detalhes(self):
        """Resumo do modelo carregado na barra lateral."""
        for w in self.det.winfo_children():
            w.destroy()
        d = self.fluxo.detalhes
        if not d:
            return

        def linha(chave, valor, cor_=FG):
            r = ttk.Frame(self.det)
            r.pack(fill="x", pady=1)
            ttk.Label(r, text=chave, style="Muted.TLabel", width=12).pack(side="left", anchor="n")
            tk.Label(r, text=valor, bg=PANEL, fg=cor_, font=("Segoe UI", 9), justify="left", anchor="w",
                     wraplength=180).pack(side="left", fill="x")

        linha("arquivo", f"{d['arquivo']} ({d['tamanho'] / 1e6:.1f} MB)")
        linha("salvo em", d["salvo"])
        linha("algoritmo", d["algoritmo"])
        linha("treinado com", f"dados '{d['treino']}'")
        if d["janela"]:
            linha("janela", f"{d['janela']:g} s" + (f" · {d['fs']:g} Hz" if d["fs"] else ""))
        linha("entradas", f"{d['n_feats']} features: " + " · ".join(f"{k} {v}" for k, v in d["familias"].items()))
        if d["aviso"]:
            linha("atenção", d["aviso"], BAD)
        r = ttk.Frame(self.det)
        r.pack(fill="x", pady=1)
        ttk.Label(r, text=f"{len(d['classes'])} classes", style="Muted.TLabel", width=12).pack(side="left", anchor="n")
        col = ttk.Frame(r)
        col.pack(side="left", fill="x")
        for c in d["classes"]:
            tk.Label(col, text="● " + (nome(c).lower() if c in NOME else c), bg=PANEL, fg=cor(c), anchor="w",
                     font=("Segoe UI", 9)).pack(anchor="w")
        if d["importancia"]:
            ttk.Label(self.det, style="Muted.TLabel", wraplength=280, text="Peso de cada grupo nas árvores (Gini); "
                      "grupos são redundantes, então é só uma pista:").pack(anchor="w", pady=(6, 2))
            cv = tk.Canvas(self.det, bg=PANEL, highlightthickness=0, width=280, height=16 * len(d["importancia"]))
            cv.pack(anchor="w")
            top = max(v for _, v in d["importancia"]) or 1.0
            for i, (g, v) in enumerate(d["importancia"]):
                y = 16 * i
                cv.create_text(0, y + 8, text=g, fill=FG, anchor="w", font=("Segoe UI", 8))
                cv.create_rectangle(62, y + 3, 62 + 160 * v / top, y + 13, fill=ACCENT, outline="")
                cv.create_text(228, y + 8, text=f"{v:.0%}", fill=MUTED, anchor="w", font=("Consolas", 8))

    def _toggle_escuta(self):
        f = self.fluxo
        if f.srv is not None:
            f.parar()
            f.zerar()
            return
        try:
            f.iniciar(int(self.v_porta.get()))
            f.erro = ""
        except (OSError, ValueError) as e:
            f.erro = f"não foi possível escutar: {e}"

    def _ler_controles(self):
        f = self.fluxo
        try:
            f.rpm = max(60.0, float(self.v_rpm.get().replace(",", ".")))
        except ValueError:
            pass
        f.limiar, f.suave = self.v_limiar.get() / 100, int(round(self.v_suave.get()))
        self.lbl_faixa.config(text=f"1× procurado em {f.faixa[0]:.0f}–{f.faixa[1]:.0f} Hz")

    # ------------------------------------------------------------------ laço de tela
    def _tick(self):
        if self._closing:
            return
        try:
            self._ler_controles()
            self._textos()
            self._barras()
            self._tempo()
            self._sinal()
        finally:
            self.after(100, self._tick)

    def _textos(self):
        f = self.fluxo
        stale = f.conectado and time.monotonic() - f.t_ultimo > STALE_S
        ligado = f.srv is not None
        self.btn_escuta.config(text="Parar escuta" if ligado else "Iniciar escuta")
        if f.erro and not ligado:
            self.lbl_sensor.config(text=f.erro, foreground=BAD)
        elif not ligado:
            self.lbl_sensor.config(text="escuta desligada", foreground=BAD)
        elif not f.conectado:
            self.lbl_sensor.config(text="aguardando o sensor conectar...", foreground=WARN)
        else:
            self.lbl_sensor.config(text=f"{f.device}: {f.fs:.0f} Hz · pacotes perdidos {f.lost}" + (" · SEM DADOS" if stale else ""),
                                   foreground=WARN if stale else OK)
        r = f.resultado
        if f.modelo is None:
            txt, c, sub = "SEM MODELO", MUTED, "clique em Carregar modelo, à esquerda"
        elif not ligado:
            txt, c, sub = "ESCUTA DESLIGADA", MUTED, "clique em Iniciar escuta"
        elif not f.conectado:
            txt, c, sub = "AGUARDANDO SENSOR", MUTED, "aponte o sensor para a URL à esquerda"
        elif stale:
            txt, c, sub = "SEM DADOS", WARN, "o sensor parou de enviar"
        elif r is None:
            txt, c, sub = "COLETANDO...", MUTED, f.nota
        else:
            txt, c = nome(r["classe"]), cor(r["classe"])
            sub = f"confiança {r['conf']:.0%}" + (f" · mais provável: {nome(r['melhor']).lower()}" if r["classe"] == "incerto" else "") \
                  + (f" · {f.nota}" if f.nota else "")
        self.lbl_diag.config(text=txt, fg=c)
        self.lbl_sub.config(text=sub)
        if r is not None and f.conectado:
            rot = f"{r['fr'] * 60:.0f} rpm ({r['fr']:.1f} Hz)" if np.isfinite(r["fr"]) else "sem rotação detectada"
            self.lbl_stats.config(text=f"rotação estimada  {rot}\nrms X/Y/Z  " + " / ".join(f"{v:.1f}" for v in r["rms_mg"])
                                       + f" mg\njanela das {r['t']} · inferência {r['ms']:.0f} ms")
        else:
            self.lbl_stats.config(text="")

    def _barras(self):
        cv, f, r = self.cv_bars, self.fluxo, self.fluxo.resultado
        cv.delete("all")
        w = cv.winfo_width()
        classes = r["classes"] if r is not None else f.classes     # as classes do resultado, mesmo se o modelo acabou de trocar
        n = max(len(classes), 1)
        if w < 200 or not classes:
            return
        x0, x1, h = 190, w - 70, 150 / n
        cv.create_text(8, 4, text="Probabilidade por classe (média das últimas janelas)", fill=MUTED, anchor="nw", font=("Segoe UI", 8))
        for i, c in enumerate(classes):
            y = 18 + i * (150 - 22) / n
            hh = (150 - 22) / n
            p = float(r["probs"][i]) if r is not None and f.conectado else 0.0
            cv.create_text(8, y + hh / 2, text=nome(c).lower() if c in NOME else c, fill=FG, anchor="w", font=("Segoe UI", 9))
            cv.create_rectangle(x0, y + 3, x1, y + hh - 3, fill=PANEL2, outline="")
            if p > 0:
                cv.create_rectangle(x0, y + 3, x0 + (x1 - x0) * p, y + hh - 3, fill=cor(c), outline="")
            cv.create_text(x1 + 8, y + hh / 2, text=f"{p:.0%}", fill=FG, anchor="w", font=("Consolas", 9))
        xl = x0 + (x1 - x0) * f.limiar
        cv.create_line(xl, 16, xl, 148, fill=MUTED, dash=(3, 3))
        cv.create_text(xl + 3, 4, text=f"limiar {f.limiar:.0%}", fill=MUTED, anchor="nw", font=("Segoe UI", 8))

    def _tempo(self):
        cv, f = self.cv_time, self.fluxo
        cv.delete("all")
        w = cv.winfo_width()
        if w < 200:
            return
        x0, x1, now = 8, w - 8, time.time()
        cv.create_text(x0, 3, text=f"Diagnóstico nos últimos {TIMELINE_S // 60} min", fill=MUTED, anchor="nw", font=("Segoe UI", 8))
        cv.create_rectangle(x0, 20, x1, 44, fill=PANEL2, outline="")
        fx = lambda t: x0 + (x1 - x0) * (1 - (now - t) / TIMELINE_S)
        for i, (t, c) in enumerate(f.linha):
            fim = f.linha[i + 1][0] if i + 1 < len(f.linha) else t + STEP_S
            fim = min(fim, t + 2.5 * STEP_S)                       # buraco (sensor caiu): deixa em branco
            a, b = max(fx(t), x0), min(fx(fim), x1)
            if b > a:
                cv.create_rectangle(a, 20, b, 44, fill=cor(c), outline="")
        cv.create_text(x0, 48, text=f"-{TIMELINE_S} s", fill=MUTED, anchor="nw", font=("Consolas", 8))
        cv.create_text(x1, 48, text="agora", fill=MUTED, anchor="ne", font=("Consolas", 8))

    def _sinal(self):
        f = self.fluxo
        fs = f.fs
        if not f.conectado or len(f.buf) < int(fs):
            for p, msg in ((self.p_wave, "sem sinal"), (self.p_spec, "sem sinal")):
                p.draw([], (0, 1), (0, 1), empty=msg)
            return
        buf = f.buf
        ac = buf[-int(2 * fs):] - buf[-int(2 * fs):].mean(0)
        m = max(float(np.abs(ac).max()) * 1.15, 0.01)
        self._ylim = m if m > getattr(self, "_ylim", 0) else self._ylim * 0.92 + m * 0.08
        t = (np.arange(len(ac)) - len(ac) + 1) / fs
        self.p_wave.draw([(t, ac[:, a], AXIS_COLORS[a]) for a in range(3)], (-2, 0), (-self._ylim, self._ylim),
                         xfmt=lambda v: f"{v:g} s", ylabel="g (sem DC) · X azul · Y laranja · Z verde")
        seg = buf[-4096:]
        if len(seg) >= 1024:
            x = seg - seg.mean(0)
            w = np.hanning(len(x))[:, None]
            amp = 2 * np.abs(np.fft.rfft(x * w, axis=0)) / w.sum()
            fr_ = np.fft.rfftfreq(len(x), 1 / fs)
            top = 10 ** math.ceil(math.log10(max(amp[2:].max() * 1.3, 2e-4)))
            r = f.resultado
            fr = r["fr"] if r is not None and np.isfinite(r["fr"]) else float("nan")
            marks = [(k * fr, MUTED, f"{k:g}×") for k in (0.5, 1, 2, 3, 4)] if np.isfinite(fr) else []
            self.p_spec.draw([(fr_, amp[:, a], AXIS_COLORS[a]) for a in range(3)], (0, min(400, fs / 2)), (1e-4, top), ylog=True,
                             xfmt=lambda v: f"{v:g} Hz", ylabel="g (pico)", vlines=marks)

    # ------------------------------------------------------------------ saída
    def _take_shot(self):
        try:
            from PIL import ImageGrab
            self.attributes("-topmost", True)                      # nada por cima da janela na hora da captura
            self.update()
            time.sleep(0.5)
            self.update()
            x, y, w, h = self.winfo_rootx(), self.winfo_rooty(), self.winfo_width(), self.winfo_height()
            ImageGrab.grab(bbox=(x, y, x + w, y + h)).save(self.shot)
        finally:
            self._close()

    def _close(self):
        if self._closing:
            return
        self._closing = True
        self.fluxo.parar()
        self.destroy()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--modelo", type=Path, help="padrão: o primeiro .joblib da pasta modelos/")
    ap.add_argument("--porta", type=int, default=8766)
    ap.add_argument("--rpm", type=float, default=1800, help="rotação aproximada do motor")
    ap.add_argument("--iniciar", action="store_true", help="já começa escutando")
    ap.add_argument("--shot", help="(dev) salva uma captura da janela e fecha")
    ap.add_argument("--shot-after", type=float, default=6.0)
    args = ap.parse_args()
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)             # nítido em telas com escala > 100 %
    except Exception:
        pass
    try:
        App(args).mainloop()
    except KeyboardInterrupt:
        pass
    finally:
        os._exit(0)                                                 # garante o fim mesmo com threads de conexão abertas


if __name__ == "__main__":
    main()
