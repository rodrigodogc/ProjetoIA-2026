"""Interface gráfica do simulador de motor (tkinter): controles à esquerda, sinal ao vivo à direita."""
from __future__ import annotations

import math
import time
import tkinter as tk
from tkinter import ttk

import numpy as np

from .engine import FS, Engine, Params, Session, suggest_label
from .link import Link, Runner

BG, PANEL, PANEL2, BORDER = "#0b0f14", "#111722", "#161e2c", "#1f2a3b"
FG, MUTED, GRID = "#e7edf5", "#8a9bb0", "#1b2536"
ACCENT, OK, WARN, BAD = "#4cc2ff", "#4ade80", "#fbbf24", "#ff5d6c"
AXIS_COLORS = ["#4cc2ff", "#ffb347", "#7ee08a"]       # mesmas cores do coletor

PRESETS = {
    "Normal": {}, "Parado": {"run": False}, "Peso pequeno": {"unb": 25}, "Peso grande": {"unb": 80},
    "Parafuso frouxo": {"loo": 75}, "Calço (desalinhado)": {"mis": 75},
}


def nice_ticks(a: float, b: float, n: int = 5) -> list[float]:
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

    def __init__(self, parent, height: int):
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
        def fy(v):                                   # funciona para escalar e para array
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
        xt = nice_ticks(x0, x1, max(3, pw // 90))
        for v in xt:
            x = fx(v)
            cv.create_line(x, T, x, T + ph, fill=GRID)
            anchor = "ne" if x > L + pw - 24 else "nw" if x < L + 12 else "n"     # não corta nas bordas
            cv.create_text(x, T + ph + 5, text=(xfmt(v) if xfmt else f"{v:g}"), fill=MUTED, anchor=anchor, font=("Consolas", 8))
        if ylabel:
            cv.create_text(L + 6, T + 2, text=ylabel, fill=MUTED, anchor="nw", font=("Consolas", 8))

        for xs, ys, color in series:
            if len(xs) < 2:
                continue
            px = L + (xs - x0) / (x1 - x0) * pw
            py = np.clip(fy(ys), T, T + ph)
            if len(px) > 2 * pw:                                     # decimação min/max por coluna de pixel
                k = -(-len(px) // pw)                                # arredonda para cima: não perde o fim da série
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
    def __init__(self, url: str, auto_connect: bool = False, shot: str | None = None, shot_after: float = 6.0):
        super().__init__()
        self.title("Simulador de vibração de motor")
        self.geometry("1320x800")
        self.minsize(1000, 600)
        self.configure(bg=BG)
        self._style()

        seed = int(time.time()) % 1_000_000
        self.engine = Engine(Session(seed), Params(), seed=seed)
        self.link = Link()
        self.runner = Runner(self.engine, self.link)
        self.runner.start()
        self.ylim = 0.05
        self.shot = shot

        self.v = {k: tk.DoubleVar(value=val) for k, val in
                  dict(rpm=1800, load=50, unb=0, mis=0, loo=0, noise=2.0, drop=0).items()}
        self.v_run = tk.BooleanVar(value=True)
        self.v_supply = tk.StringVar(value="inversor")
        self.v_url = tk.StringVar(value=url)
        self.v_axis = tk.StringVar(value="Z")
        self._build()
        self._sync()
        if auto_connect:
            self.link.connect(self.v_url.get())
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.after(150, self._tick)
        if shot:
            self.after(int(shot_after * 1000), self._take_shot)

    # ------------------------------------------------------------------ visual
    def _style(self) -> None:
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure(".", background=PANEL, foreground=FG, fieldbackground=PANEL2, bordercolor=BORDER,
                    lightcolor=PANEL2, darkcolor=PANEL2, troughcolor=PANEL2, font=("Segoe UI", 9))
        s.configure("TFrame", background=PANEL)
        s.configure("TLabel", background=PANEL, foreground=FG)
        s.configure("Muted.TLabel", foreground=MUTED)
        s.configure("Val.TLabel", foreground=ACCENT, font=("Consolas", 9))
        s.configure("Big.TLabel", font=("Consolas", 13, "bold"), foreground=ACCENT)
        s.configure("TLabelframe", background=PANEL, bordercolor=BORDER)
        s.configure("TLabelframe.Label", background=PANEL, foreground=MUTED, font=("Segoe UI", 9, "bold"))
        s.configure("TButton", background=PANEL2, foreground=FG, padding=(8, 4), borderwidth=1)
        s.map("TButton", background=[("active", "#1b2638"), ("disabled", PANEL)], foreground=[("disabled", MUTED)])
        s.configure("Accent.TButton", background="#1f6f9f", foreground="#ffffff")
        s.map("Accent.TButton", background=[("active", "#2a86bd")])
        s.configure("TCheckbutton", background=PANEL, foreground=FG)
        s.configure("TRadiobutton", background=PANEL, foreground=FG)
        s.map("TCheckbutton", background=[("active", PANEL)])
        s.map("TRadiobutton", background=[("active", PANEL)])
        s.configure("Horizontal.TScale", background=PANEL, troughcolor=PANEL2)
        s.configure("TCombobox", fieldbackground=PANEL2, background=PANEL2, foreground=FG, arrowcolor=FG)
        s.map("TCombobox", fieldbackground=[("readonly", PANEL2)], foreground=[("readonly", FG)],
              selectbackground=[("readonly", PANEL2)], selectforeground=[("readonly", FG)])
        self.option_add("*TCombobox*Listbox.background", PANEL2)
        self.option_add("*TCombobox*Listbox.foreground", FG)

    def _scale(self, parent, text, key, lo, hi, fmt):
        f = ttk.Frame(parent)
        f.pack(fill="x", pady=1)
        top = ttk.Frame(f)
        top.pack(fill="x")
        ttk.Label(top, text=text).pack(side="left")
        val = ttk.Label(top, style="Val.TLabel")
        val.pack(side="right")
        sc = ttk.Scale(f, from_=lo, to=hi, variable=self.v[key], orient="horizontal")
        sc.pack(fill="x")
        upd = lambda *_: val.config(text=fmt(self.v[key].get()))
        self.v[key].trace_add("write", upd)
        upd()
        return sc

    def _section(self, parent, title):
        lf = ttk.LabelFrame(parent, text=title, padding=(8, 4))
        lf.pack(fill="x", pady=(0, 6))
        return lf

    def _build(self) -> None:
        root = ttk.Frame(self, padding=8)
        root.pack(fill="both", expand=True)
        root.columnconfigure(1, weight=1)
        root.rowconfigure(0, weight=1)

        # painel esquerdo com rolagem (telas baixas)
        holder = tk.Frame(root, bg=PANEL, width=340)
        holder.grid(row=0, column=0, sticky="ns", padx=(0, 8))
        holder.pack_propagate(False)
        cv = tk.Canvas(holder, bg=PANEL, highlightthickness=0, width=320)
        sb = ttk.Scrollbar(holder, orient="vertical", command=cv.yview)
        cv.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        cv.pack(side="left", fill="both", expand=True)
        left = ttk.Frame(cv, padding=(2, 2, 6, 2))
        win = cv.create_window(0, 0, window=left, anchor="nw")
        left.bind("<Configure>", lambda e: cv.configure(scrollregion=cv.bbox("all")))
        cv.bind("<Configure>", lambda e: cv.itemconfigure(win, width=e.width))
        self.bind_all("<MouseWheel>", lambda e: cv.yview_scroll(int(-e.delta / 120), "units") if self.winfo_containing(e.x_root, e.y_root) and str(self.winfo_containing(e.x_root, e.y_root)).startswith(str(holder)) else None)

        sec = self._section(left, "Coletor")
        ttk.Entry(sec, textvariable=self.v_url).pack(fill="x")
        cf = ttk.Frame(sec)
        cf.pack(fill="x", pady=(4, 0))
        self.btn_conn = ttk.Button(cf, text="Conectar", style="Accent.TButton", command=self._toggle_conn)
        self.btn_conn.pack(side="left")
        self.lbl_conn = ttk.Label(cf, text="desconectado", foreground=BAD, wraplength=190)
        self.lbl_conn.pack(side="left", padx=8)
        self._scale(sec, "Perda de pacotes", "drop", 0, 20, lambda x: f"{x:.1f} %")

        sec = self._section(left, "Rótulo para digitar no coletor")
        self.lbl_label = ttk.Label(sec, style="Big.TLabel", text="normal")
        self.lbl_label.pack(anchor="w")
        self.lbl_rec = ttk.Label(sec, style="Muted.TLabel", text="coletor: sem conexão")
        self.lbl_rec.pack(anchor="w")

        sec = self._section(left, "Falhas (severidade)")
        self._scale(sec, "Peso preso ao eixo (desbalanceamento)", "unb", 0, 100, lambda x: f"{x:.0f} %")
        self._scale(sec, "Parafuso de fixação frouxo (folga)", "loo", 0, 100, lambda x: f"{x:.0f} %")
        self._scale(sec, "Calço sob o motor (desalinhamento)", "mis", 0, 100, lambda x: f"{x:.0f} %")
        pf = ttk.Frame(sec)
        pf.pack(fill="x", pady=(6, 0))
        for i, name in enumerate(PRESETS):
            ttk.Button(pf, text=name, command=lambda n=name: self._preset(n)).grid(row=i // 2, column=i % 2, sticky="ew", padx=2, pady=2)
        pf.columnconfigure((0, 1), weight=1)

        sec = self._section(left, "Motor")
        ttk.Checkbutton(sec, text="Ligado", variable=self.v_run).pack(anchor="w")
        rf = ttk.Frame(sec)
        rf.pack(fill="x")
        ttk.Radiobutton(rf, text="Inversor (rpm livre)", value="inversor", variable=self.v_supply).pack(side="left")
        ttk.Radiobutton(rf, text="Rede 60 Hz", value="rede", variable=self.v_supply).pack(side="left", padx=8)
        self.sc_rpm = self._scale(sec, "Velocidade", "rpm", 600, 6000, lambda x: f"{x:.0f} rpm")
        self._scale(sec, "Carga", "load", 0, 100, lambda x: f"{x:.0f} %")

        sec = self._section(left, "Sensor")
        self._scale(sec, "Ruído branco", "noise", 0.5, 10, lambda x: f"{x:.1f} mg")
        bf = ttk.Frame(sec)
        bf.pack(fill="x", pady=(4, 0))
        ttk.Button(bf, text="Remontar sensor (nova sessão)", command=self._remount).pack(fill="x")
        self.lbl_sess = ttk.Label(sec, style="Muted.TLabel", justify="left")
        self.lbl_sess.pack(anchor="w", pady=(4, 0))

        # direita: gráficos
        right = ttk.Frame(root)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=3)
        right.columnconfigure(1, weight=1)
        right.rowconfigure(1, weight=3)
        right.rowconfigure(3, weight=2)
        self.lbl_info = ttk.Label(right, style="Muted.TLabel", font=("Consolas", 9))
        self.lbl_info.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 4))
        self.p_wave = Plot(right, 260)
        self.p_wave.cv.grid(row=1, column=0, columnspan=2, sticky="nsew")
        hf = ttk.Frame(right)
        hf.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 2))
        ttk.Label(hf, text="Espectro — eixo:", style="Muted.TLabel").pack(side="left")
        ttk.Combobox(hf, textvariable=self.v_axis, values=["X", "Y", "Z"], width=3, state="readonly").pack(side="left", padx=6)
        ttk.Label(hf, text="X radial horizontal · Y axial · Z radial vertical (gravidade)", style="Muted.TLabel").pack(side="left", padx=10)
        self.p_spec = Plot(right, 220)
        self.p_spec.cv.grid(row=3, column=0, sticky="nsew", padx=(0, 6))
        self.p_orbit = Plot(right, 220)
        self.p_orbit.cv.grid(row=3, column=1, sticky="nsew")

    # ------------------------------------------------------------------ ações
    def _preset(self, name: str) -> None:
        for k in ("unb", "mis", "loo"):
            self.v[k].set(0)
        self.v_run.set(True)
        for k, val in PRESETS[name].items():
            if k == "run":
                self.v_run.set(val)
            else:
                self.v[k].set(val)

    def _remount(self) -> None:
        self.engine.set_session(Session(int(time.time() * 1000) % 1_000_000))

    def _toggle_conn(self) -> None:
        if self.link.state in ("conectado", "conectando", "reconectando"):
            self.link.disconnect()
        else:
            self.link.connect(self.v_url.get().strip())

    def _sync(self) -> None:
        p, v = self.engine.p, self.v
        p.running = self.v_run.get()
        p.supply = self.v_supply.get()
        p.rpm = v["rpm"].get()
        p.load = v["load"].get() / 100
        p.unbalance, p.misalignment, p.looseness = v["unb"].get() / 100, v["mis"].get() / 100, v["loo"].get() / 100
        p.noise_mg = v["noise"].get()
        self.link.drop = v["drop"].get() / 100
        self.sc_rpm.state(["disabled"] if p.supply == "rede" else ["!disabled"])

    # ------------------------------------------------------------------ laço de tela
    def _tick(self) -> None:
        try:
            self._sync()
            self._update_labels()
            self._draw()
        finally:
            self.after(100, self._tick)

    def _update_labels(self) -> None:
        e, lk = self.engine, self.link
        info = e.info()
        self.lbl_label.config(text=suggest_label(e.p))
        st = lk.state
        self.lbl_conn.config(text=st + (f" · {lk.error}" if st != "conectado" and lk.error else ""),
                             foreground=OK if st == "conectado" else WARN if st in ("conectando", "reconectando") else BAD)
        self.btn_conn.config(text="Desconectar" if st != "desconectado" else "Conectar")
        self.lbl_rec.config(text=("coletor GRAVANDO: " + lk.rec_label) if lk.recording else
                            ("coletor: conectado, ocioso" if st == "conectado" else "coletor: sem conexão"),
                            foreground=BAD if lk.recording else MUTED)
        s = e.s
        self.lbl_sess.config(text=f"sessão {s.seed} · ODR real {info['fs_true']:.0f} Hz ({s.odr_err * 100:+.1f} %)\n"
                                  f"inclinação {np.degrees(np.arccos(s.gvec[2])):.1f}° · offsets "
                                  f"{s.bias[0] * 1000:+.0f}/{s.bias[1] * 1000:+.0f}/{s.bias[2] * 1000:+.0f} mg")
        self.lbl_info.config(text=f"rotor {info['rpm']:.0f} rpm ({info['f_rotor_hz']:.2f} Hz) · alimentação {info['f_eletrica_hz']:.1f} Hz · "
                                  f"escorregamento {info['slip'] * 100:.1f} % · pacotes enviados {lk.sent}")

    def _draw(self) -> None:
        fs = self.engine.fs_true
        info = self.engine.info()
        data = self.runner.snapshot(int(2 * fs))
        if len(data) < 200:
            return
        ac = data - data.mean(0)

        m = max(float(np.abs(ac).max()) * 1.15, 0.01)
        self.ylim = m if m > self.ylim else self.ylim * 0.92 + m * 0.08
        t = (np.arange(len(ac)) - len(ac) + 1) / fs
        self.p_wave.draw([(t, ac[:, a], AXIS_COLORS[a]) for a in range(3)], (-2, 0), (-self.ylim, self.ylim),
                         xfmt=lambda v: f"{v:g} s", ylabel="g (sem DC)")

        n = 4096
        seg = self.runner.snapshot(n)
        if len(seg) >= 1024:
            ax = "XYZ".index(self.v_axis.get())
            x = seg[:, ax] - seg[:, ax].mean()
            w = np.hanning(len(x))
            amp = 2 * np.abs(np.fft.rfft(x * w)) / w.sum()
            f = np.fft.rfftfreq(len(x), 1 / fs)
            top = 10 ** math.ceil(math.log10(max(amp[2:].max() * 1.3, 2e-4)))
            fr = info["f_rotor_hz"]
            marks = [(k * fr, MUTED, f"{k}×") for k in (1, 2, 3, 4)] if fr > 3 else []
            if self.engine.p.looseness > 0.05 and fr > 3:                  # sub-harmônicos da folga
                marks += [(k * fr, WARN, f"{k:g}×") for k in (0.5, 1.5)]
            self.p_spec.draw([(f, amp, AXIS_COLORS[ax])], (0, fs / 2), (1e-4, top), ylog=True, xfmt=lambda v: f"{v:g} Hz",
                             ylabel="g (pico)", vlines=marks)

        fr = info["f_rotor_hz"]
        o = ac[-int(0.3 * fs) - 64:]
        k = int(max(1, min(40, fs / (8 * fr)))) if fr > 3 else 1      # passa-baixa: mantém até ~4× a rotação
        if k > 1:
            o = np.apply_along_axis(lambda c: np.convolve(c, np.ones(k) / k, mode="valid"), 0, o)
        o = o[-int(0.3 * fs):]
        r = max(float(np.abs(o[:, [0, 2]]).max()) * 1.2, 0.02)
        self.p_orbit.draw([(o[:, 0], o[:, 2], AXIS_COLORS[0])], (-r, r), (-r, r), ylabel="órbita X × Z (g)",
                          xfmt=lambda v: f"{v:.2f}")

    # ------------------------------------------------------------------ saída
    def _take_shot(self) -> None:
        try:
            from PIL import ImageGrab
            self.update_idletasks()
            x, y, w, h = self.winfo_rootx(), self.winfo_rooty(), self.winfo_width(), self.winfo_height()
            ImageGrab.grab(bbox=(x, y, x + w, y + h)).save(self.shot)
        finally:
            self._close()

    def _close(self) -> None:
        self.runner.stop()
        self.link.disconnect()
        self.destroy()
