"""Motor de sinal: vibração de um motor elétrico medida por um acelerômetro MEMS de 3 eixos (LSM6DS3).

O que é modelado (da física até o dado bruto que o ESP32 mandaria):

 1. Velocidade do rotor: rede 60 Hz (indução, escorregamento ~ carga) ou inversor (rpm ajustável), com inércia
    e flutuação lenta (Ornstein-Uhlenbeck), o que alarga os picos como num motor real.
 2. Excitação síncrona (1×, 2×, 3× ... da rotação) com amplitude e fase por eixo; cada falha tem a sua assinatura:
      desbalanceamento -> 1× radial forte, órbita ~circular, pouco axial
      desalinhamento   -> 1× e 2× axiais, 2× radial (angular + paralelo), harmônicos 3×, 4×
      folga mecânica   -> muitos harmônicos, sub-harmônicos 0,5× 1,5× 2,5× intermitentes, impactos 1×/rot,
                          piso de ruído mais alto
    São só falhas que dá para provocar na bancada: peso preso ao eixo (desbalanceamento, leve ou forte), parafuso
    de fixação frouxo (folga) e, opcionalmente, calço sob o motor (desalinhamento). Rolamentos não são simulados.
 3. Estrutura: cada eixo tem sua ressonância (resposta de 1 grau de liberdade a uma excitação rotativa), então a
    amplitude depende da rotação como na prática (~f⁴ abaixo da ressonância) e muda a cada remontagem do sensor.
 4. Elétrico: componente magnética em 2× a frequência da rede/inversor, com modulação pelo escorregamento.
 5. Ruído: piso estrutural colorido pelas ressonâncias, deriva lenta e ruído branco do sensor.
 6. Cadeia do sensor: gravidade projetada pela inclinação da montagem, offset e ganho por eixo, filtro
    anti-aliasing, decimação (superamostragem interna 4×), erro do ODR real (±1,5 %), quantização de 0,122 mg
    e saturação em ±4 g.

Cada `Session` representa uma montagem do sensor (ressonâncias, inclinação, offsets, acoplamento, ODR real...).
Remontar o sensor = nova sessão. É isso que faz o aprendizado generalizar (ou não) entre sessões.

Eixos: X = radial horizontal, Y = axial (ao longo do eixo do motor), Z = radial vertical (gravidade).
Amplitudes de referência vêm de ISO 10816-3 (motores pequenos): 7 mm/s RMS ~ 0,19 g de pico a 1800 rpm.
"""
from __future__ import annotations

import math
import threading
from dataclasses import asdict, dataclass

import numpy as np
from scipy import signal

FS = 1666.0           # taxa nominal declarada ao coletor (ODR 1,66 kHz do LSM6DS3)
LSB_G = 0.000122      # ±4 g
RANGE_G = 4.0
OS = 4                # superamostragem interna
AA_HZ = 520.0         # banda do filtro anti-aliasing do sensor
G = 9.81
F_REF = 30.0          # Hz = 1800 rpm: velocidade em que as amplitudes de referência são dadas
POLES = 4
FN_NOM = np.array([200.0, 280.0, 400.0])   # ressonâncias nominais X, Y, Z
TWO_PI = 2.0 * math.pi


@dataclass
class Params:
    """Estado do motor controlado pelo usuário em tempo real. Severidades em 0..1."""
    running: bool = True
    supply: str = "inversor"      # "rede" (60 Hz, indução) | "inversor" (rpm ajustável)
    rpm: float = 1800.0           # rpm programado (só vale no inversor)
    load: float = 0.5             # 0..1
    unbalance: float = 0.0
    misalignment: float = 0.0
    looseness: float = 0.0
    noise_mg: float = 2.0         # ruído branco do sensor (RMS)

    def asdict(self) -> dict:
        return asdict(self)


def suggest_label(p: Params) -> str:
    """Rótulo que o usuário deve digitar no coletor para o estado atual (nomes das classes do projeto)."""
    if not p.running:
        return "parado"
    sev = {"desbalanceado": p.unbalance, "desalinhado": p.misalignment, "folga": p.looseness}
    act = {k: v for k, v in sev.items() if v >= 0.05}
    if not act:
        return "normal"
    if len(act) > 1:
        return "combinado_" + "+".join(act)
    k, v = next(iter(act.items()))
    if k == "desbalanceado":
        return "desbalanceado_leve" if v < 0.5 else "desbalanceado_forte"
    return k


class Session:
    """Uma montagem do sensor no motor. Tudo que muda quando você desmonta e remonta."""

    def __init__(self, seed: int):
        r = np.random.default_rng(seed)
        self.seed = int(seed)
        self.fn = FN_NOM * r.uniform(0.88, 1.12, 3)            # ressonância por eixo
        self.zeta = r.uniform(0.04, 0.09, 3)
        self.ring_f = float(r.uniform(480, 720))               # ressonância excitada por impactos
        self.ring_zeta = float(r.uniform(0.02, 0.05))
        tilt = np.deg2rad(r.normal(0, 2.5, 2))                 # roll, pitch da montagem
        self.gvec = np.array([math.sin(tilt[1]),
                              -math.sin(tilt[0]) * math.cos(tilt[1]),
                              math.cos(tilt[0]) * math.cos(tilt[1])])
        self.bias = r.normal(0, 0.02, 3)                       # offset de zero-g (g)
        self.gain = 1 + r.normal(0, 0.008, 3)
        self.odr_err = float(r.uniform(-0.015, 0.015))         # ODR real vs nominal
        self.coupling = r.uniform(0.75, 1.3, 3)                # quanto cada eixo "enxerga" a vibração
        self.base_1x = float(r.uniform(0.018, 0.04))           # 1× do motor saudável a 1800 rpm (g pico)
        self.th = r.uniform(0, TWO_PI, (3, 21))                # fase por eixo e ordem (índice = 2*ordem)
        self.th[2, 2] = self.th[0, 2] + math.pi / 2 + r.normal(0, 0.3)   # órbita ~circular no 1×
        self.th_u = float(r.uniform(0, TWO_PI))
        self.th_u_z = self.th_u + math.pi / 2 + float(r.normal(0, 0.25))
        self.anis = float(r.uniform(0.6, 1.0))                 # rigidez vertical > horizontal -> órbita elíptica
        self.fault_scale = float(r.uniform(0.85, 1.15))        # posição do sensor em relação à falha
        self.ang = float(r.uniform(0.3, 1.0))                  # componente angular do desalinhamento
        self.par = float(r.uniform(0.3, 1.0))                  # componente paralela
        self.noise_floor = float(r.uniform(0.002, 0.004))      # g RMS do piso estrutural (antes do filtro)
        self.drift = float(r.uniform(0.002, 0.006))            # deriva lenta (g)
        self.hum = float(r.uniform(0.004, 0.012))              # componente elétrica 2×f (g pico a 120 Hz)
        self.imp_phase = float(r.uniform(0, TWO_PI))
        self.slip_rated = float(r.uniform(0.025, 0.045))


def _ring_sos(f0: float, zeta: float, fs: float) -> np.ndarray:
    """Ressonador amortecido: resposta ao impulso = oscilação de f0 que decai (zeta)."""
    w0 = TWO_PI * f0 / fs
    r = math.exp(-zeta * w0)
    return np.array([[1.0, 0.0, 0.0, 1.0, -2.0 * r * math.cos(w0 * math.sqrt(1 - zeta * zeta)), r * r]])


def _transfer(f: np.ndarray, fn: float, zeta: float) -> np.ndarray:
    """Transmissibilidade de deslocamento de uma excitação rotativa (1 GDL): r² / (1 - r² + 2jζr)."""
    r = f / fn
    return r * r / (1.0 - r * r + 2j * zeta * r)


class Engine:
    """Gera o sinal do sensor em blocos: `read(n)` devolve n amostras int16 (n, 3), prontas para o coletor."""

    def __init__(self, session: Session | None = None, params: Params | None = None, seed: int | None = None):
        self.p = params or Params()
        self.rng = np.random.default_rng(seed)
        self._lock = threading.Lock()
        self.set_session(session or Session(1), settle=True)

    # ------------------------------------------------------------------ estado
    @property
    def fs_true(self) -> float:
        return FS * (1.0 + self.s.odr_err)

    def set_session(self, session: Session, settle: bool = False) -> None:
        with self._lock:
            self.s = session
            self.fs_int = self.fs_true * OS
            self._build_filters()
            if settle or not hasattr(self, "f_state"):
                self.f_state = self._target_speed()
                self.f_eff = self.f_state
                self.eps = 0.0
                self.phase = float(self.rng.uniform(0, TWO_PI))
                self.phase_e = 0.0
                self.phase_sl = 0.0
                self.drift_state = np.zeros(3)
                self.sub_state = 0.0
                self.sub_mod = 0.5
                self._q: dict[str, float] = {}

    def _build_filters(self) -> None:
        s, fi = self.s, self.fs_int
        self.aa_sos = signal.butter(4, AA_HZ, btype="low", fs=fi, output="sos")
        self.aa_zi = np.zeros((self.aa_sos.shape[0], 3, 2))
        self.noise_sos, self.noise_zi, self.noise_norm = [], [], []
        for a in range(3):
            b1, a1 = signal.iirpeak(s.fn[a], 1.0 / (2.0 * s.zeta[a]), fs=fi)
            b2, a2 = signal.iirpeak(s.ring_f, 12.0, fs=fi)
            sos = (signal.tf2sos(b1, a1), signal.tf2sos(b2, a2))
            self.noise_sos.append(sos)
            self.noise_zi.append([np.zeros((1, 2)), np.zeros((1, 2))])
            w = np.random.default_rng(1).standard_normal(40000)
            y = 0.4 * w + 4.0 * signal.sosfilt(sos[0], w) + 3.0 * signal.sosfilt(sos[1], w)
            self.noise_norm.append(float(np.std(y)))
        self.ring_sos = {"loose": _ring_sos(0.9 * s.ring_f, s.ring_zeta, fi)}
        self.ring_zi = {k: np.zeros((1, 2)) for k in self.ring_sos}

    def _slip(self) -> float:
        return self.s.slip_rated * (0.15 + 0.85 * self.p.load)

    def _target_speed(self) -> float:
        p = self.p
        if not p.running:
            return 0.0
        if p.supply == "rede":
            return (2.0 * 60.0 / POLES) * (1.0 - self._slip())
        return p.rpm / 60.0 * (1.0 - self._slip())

    def info(self) -> dict:
        """Estado instantâneo (para a interface e para os metadados)."""
        fr = self.f_eff
        return {"f_rotor_hz": fr, "rpm": fr * 60.0, "f_eletrica_hz": fr * (POLES / 2) / (1 - self._slip()),
                "slip": self._slip(), "fs_true": self.fs_true, "session_seed": self.s.seed}

    # ------------------------------------------------------------------ componentes síncronos
    def _components(self, a: int) -> list[tuple]:
        """Lista (ordem k, amplitude de referência g, fase, expoente em f, modulada) do eixo `a`."""
        p, s = self.p, self.s
        cp, th = s.coupling[a], s.th[a]
        ph = lambda k: th[int(round(2 * k))]
        out = []
        w1 = (1.0, 0.35, 0.8)[a]
        w2 = (1.0, 0.6, 0.9)[a]
        base = s.base_1x * cp * (1 + 0.3 * p.load)
        out += [(1, base * w1, ph(1), -2.0, 0), (2, 0.22 * base * w2, ph(2), 0.0, 0),
                (3, 0.10 * base * w2, ph(3), 0.0, 0), (4, 0.05 * base * w2, ph(4), 0.0, 0)]

        su = p.unbalance * s.fault_scale
        if su > 0:
            amp = (0.19 * s.coupling[0], 0.04 * s.coupling[1], 0.19 * s.anis * s.coupling[2])[a]
            thu = (s.th_u, s.th_u + 1.3, s.th_u_z)[a]
            out += [(1, amp * su, thu, 0.0, 0), (2, 0.015 * su * cp, ph(2) + 0.7, 0.0, 0)]

        sm = p.misalignment * s.fault_scale
        if sm > 0:
            if a == 1:        # axial
                out += [(1, 0.16 * s.ang * sm * cp, ph(1) + 2.0, 0.0, 0), (2, 0.12 * (0.4 + s.ang) * sm * cp, ph(2) + 1.1, 0.0, 0),
                        (3, 0.03 * sm * cp, ph(3), 0.0, 0)]
            else:             # radial
                w = 1.0 if a == 0 else 0.8
                out += [(2, 0.11 * s.par * w * sm * cp, ph(2) + 0.4, 0.0, 0), (1, 0.03 * w * sm * cp, ph(1) + 2.5, 0.0, 0),
                        (3, 0.045 * w * sm * cp, ph(3) + 0.9, 0.0, 0), (4, 0.02 * w * sm * cp, ph(4), 0.0, 0)]

        sl = p.looseness * s.fault_scale
        if sl > 0:
            sl = sl ** 1.3
            wl = (0.9, 0.4, 1.0)[a]
            out.append((1, 0.04 * sl * wl * cp, ph(1) + 1.7, 0.0, 0))
            for k in range(2, 9):
                out.append((k, 0.05 * sl * wl * cp * k ** -0.6, ph(k) + 0.3 * k, 0.0, 0))
            for k, ak in ((0.5, 0.05), (1.5, 0.035), (2.5, 0.025)):     # sub-harmônicos intermitentes
                out.append((k, ak * sl * wl * cp, ph(k), 0.0, 1))
        return out

    def _harmonics(self, a: int, f_r: np.ndarray, phase: np.ndarray, run: np.ndarray, sub_mod: np.ndarray) -> np.ndarray:
        comps = self._components(a)
        K = np.array([c[0] for c in comps])
        A = np.array([c[1] for c in comps])
        TH = np.array([c[2] for c in comps])
        EX = np.array([c[3] for c in comps])
        SUB = np.array([c[4] for c in comps], dtype=bool)
        fh = K[:, None] * f_r[None, :]
        D = _transfer(fh, self.s.fn[a], self.s.zeta[a])
        gain = (TWO_PI * fh) ** 2 * np.abs(D)
        ref = (TWO_PI * K * F_REF) ** 2 * np.abs(_transfer(K * F_REF, FN_NOM[a], 0.06))
        amp = A[:, None] * gain / ref[:, None] * (np.maximum(f_r, 0.5) / F_REF)[None, :] ** EX[:, None]
        amp = np.where(SUB[:, None], amp * sub_mod[None, :], amp)
        arg = K[:, None] * phase[None, :] + TH[:, None] + np.angle(D)
        return (amp * np.sin(arg)).sum(axis=0) * run

    # ------------------------------------------------------------------ impulsos (folga)
    def _cross(self, ph: np.ndarray, offset: float, key: str) -> np.ndarray:
        q = np.floor((ph - offset) / TWO_PI)
        prev = self._q.get(key, q[0])
        inc = np.diff(np.concatenate(([prev], q)))
        self._q[key] = q[-1]
        return np.flatnonzero(inc > 0)

    def _ring(self, key: str, x: np.ndarray) -> np.ndarray:
        y, self.ring_zi[key] = signal.sosfilt(self.ring_sos[key], x, zi=self.ring_zi[key])
        return y

    # ------------------------------------------------------------------ bloco
    def read(self, n: int) -> np.ndarray:
        with self._lock:
            return self._read(n)

    def _read(self, n: int) -> np.ndarray:
        p, s, rng = self.p, self.s, self.rng
        N = n * OS
        dt = 1.0 / self.fs_int
        blk = N * dt
        ramp = np.arange(1, N + 1) / N

        # velocidade: inércia + flutuação lenta
        target = self._target_speed()
        tau = 0.8 if p.running else 2.5
        f_new = self.f_state + (target - self.f_state) * (1 - math.exp(-blk / tau))
        sig = 0.0005 if p.supply == "rede" else 0.0012
        aj = math.exp(-blk / 1.5)
        eps_new = self.eps * aj + sig * math.sqrt(1 - aj * aj) * rng.standard_normal()
        f_eff_new = f_new * (1 + eps_new)
        f_r = self.f_eff + (f_eff_new - self.f_eff) * ramp
        self.f_state, self.f_eff, self.eps = f_new, f_eff_new, eps_new
        phase = self.phase + TWO_PI * np.cumsum(f_r) * dt
        self.phase = float(phase[-1] % (2 * TWO_PI))      # período 4π: vale também para 0,5× 1,5× 2,5×
        run = np.clip(f_r / 2.0, 0.0, 1.0)

        # sub-harmônicos da folga: amplitude que liga e desliga lentamente
        a_s = math.exp(-blk / 0.7)
        self.sub_state = self.sub_state * a_s + math.sqrt(1 - a_s * a_s) * rng.standard_normal()
        sub_prev = self.sub_mod
        self.sub_mod = float(1.0 / (1.0 + math.exp(-2.2 * self.sub_state)))
        sub_mod = sub_prev + (self.sub_mod - sub_prev) * ramp

        vib = np.zeros((3, N))
        for a in range(3):
            vib[a] = self._harmonics(a, f_r, phase, run, sub_mod)

        # componente elétrica em 2× a frequência de alimentação, modulada pelo escorregamento
        slip = self._slip()
        f_e = f_r * (POLES / 2) / (1.0 - slip)
        ph_e = self.phase_e + TWO_PI * np.cumsum(2.0 * f_e) * dt
        self.phase_e = float(ph_e[-1] % TWO_PI)
        ph_sl = self.phase_sl + TWO_PI * np.cumsum(2.0 * slip * f_e) * dt
        self.phase_sl = float(ph_sl[-1] % TWO_PI)
        am = 1.0 + 0.15 * np.sin(ph_sl)
        for a in range(3):
            D = _transfer(2.0 * f_e, s.fn[a], s.zeta[a])
            gain = (TWO_PI * 2.0 * f_e) ** 2 * np.abs(D)
            ref = (TWO_PI * 120.0) ** 2 * np.abs(_transfer(120.0, FN_NOM[a], 0.06))
            amp = s.hum * (0.5 + 0.5 * p.load) * (1.0, 0.5, 0.7)[a] * s.coupling[a] * gain / ref * am
            vib[a] += run * amp * np.sin(ph_e + s.th[a, 20] + np.angle(D))

        # impactos da folga: 1×/rot (e 2×/rot quando severa) excitando a ressonância da carcaça
        sl = (p.looseness * s.fault_scale) ** 1.3 if p.looseness > 0 else 0.0
        imp = np.zeros(N)
        if sl > 0:
            for idx in self._cross(phase, s.imp_phase, "loose"):
                imp[idx] += 0.12 * sl * rng.uniform(0.5, 1.2) * run[idx]
            if sl > 0.45:
                for idx in self._cross(phase, s.imp_phase + math.pi, "loose2"):
                    imp[idx] += 0.06 * sl * rng.uniform(0.4, 1.0) * run[idx]
        ring_loose = self._ring("loose", imp)

        for a, w_loose in enumerate((0.8, 0.5, 1.0)):
            vib[a] += s.coupling[a] * w_loose * ring_loose

        # piso de ruído estrutural: sobe com a folga e com a carga
        run_avg = float(run.mean())
        lvl = s.noise_floor * (0.25 + 0.75 * run_avg) * (1 + 2.5 * sl + 0.6 * p.load)
        for a in range(3):
            w = rng.standard_normal(N)
            y1, self.noise_zi[a][0] = signal.sosfilt(self.noise_sos[a][0], w, zi=self.noise_zi[a][0])
            y2, self.noise_zi[a][1] = signal.sosfilt(self.noise_sos[a][1], w, zi=self.noise_zi[a][1])
            vib[a] += lvl * (0.4 * w + 4.0 * y1 + 3.0 * y2) / self.noise_norm[a]

        # filtro anti-aliasing do sensor + decimação
        vib, self.aa_zi = signal.sosfilt(self.aa_sos, vib, axis=-1, zi=self.aa_zi)
        out = vib[:, OS - 1::OS]

        # deriva lenta (térmica/ambiente), gravidade, offset, ganho e ruído branco
        ad = math.exp(-blk / 3.0)
        d_new = self.drift_state * ad + s.drift * math.sqrt(1 - ad * ad) * rng.standard_normal(3)
        ramp_n = np.arange(1, n + 1) / n
        drift = self.drift_state[:, None] + (d_new - self.drift_state)[:, None] * ramp_n[None, :]
        self.drift_state = d_new
        g = (out + drift + s.gvec[:, None]) * s.gain[:, None] + s.bias[:, None]
        g += rng.standard_normal((3, n)) * (p.noise_mg / 1000.0)
        raw = np.clip(np.rint(g / LSB_G), -32768, 32767).astype("<i2")
        return np.ascontiguousarray(raw.T)
