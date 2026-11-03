'use strict';

/* ======================================================= utilidades */
const $ = (s, el = document) => el.querySelector(s);
const AXES = [
  { k: 'x', name: 'X', color: '#4cc2ff' },
  { k: 'y', name: 'Y', color: '#ffb347' },
  { k: 'z', name: 'Z', color: '#7ee08a' },
];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const ico = n => `<svg class="i"><use href="#i-${n}"/></svg>`;
/* Pílulas do cabeçalho: ícone fixo no HTML, só o texto (.t) e a classe mudam. */
function setPill(id, text, cls = '') {
  const el = $('#' + id);
  $('.t', el).textContent = text;
  el.className = 'pill' + (cls ? ' ' + cls : '');
}
const num = (v, d = 2) => (v == null || !isFinite(v)) ? '—' : Number(v).toFixed(d);
const ls = {
  get(k, d) { try { const v = localStorage.getItem('vc.' + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem('vc.' + k, JSON.stringify(v)); } catch { /* sem storage */ } },
};

function toast(text, level = '') {
  const t = document.createElement('div');
  t.className = 'toast ' + level;
  t.innerHTML = ico({ ok: 'check', warn: 'alert', error: 'xcircle' }[level] || 'info');
  const s = document.createElement('span');
  s.textContent = text;
  t.append(s);
  $('#toasts').append(t);
  setTimeout(() => t.remove(), 4500);
}

/* ======================================================= gráfico em canvas */
function niceStep(range, n) {
  const raw = range / n, p = Math.pow(10, Math.floor(Math.log10(raw))), f = raw / p;
  return (f < 1.5 ? 1 : f < 3 ? 2 : f < 7 ? 5 : 10) * p;
}
function linTicks(a, b, n = 5) {
  if (!(b > a)) return [a];
  const s = niceStep(b - a, n), out = [];
  for (let v = Math.ceil(a / s - 1e-9) * s; v <= b + s * 1e-6; v += s) out.push(Math.abs(v) < s * 1e-9 ? 0 : +v.toPrecision(12));
  return out;
}
function logTicks(a, b) {
  const out = [];
  for (let e = Math.ceil(Math.log10(a)); e <= Math.floor(Math.log10(b)); e++) out.push(Math.pow(10, e));
  return out;
}

function drawSeries(ctx, s, X, Y, pw, o) {
  const n = s.y.length;
  if (n < 2) return;
  const i0 = Math.max(0, Math.floor((o.xmin - s.x0) / s.dx)), i1 = Math.min(n - 1, Math.ceil((o.xmax - s.x0) / s.dx));
  if (i1 <= i0) return;
  ctx.strokeStyle = s.color; ctx.lineWidth = s.width || 1.4; ctx.lineJoin = 'round';
  ctx.beginPath();
  const cnt = i1 - i0 + 1;
  if (cnt > pw * 2) {                       // muitos pontos: envelope min/max por coluna de pixel
    const per = cnt / pw;
    for (let c = 0; c < pw; c++) {
      const a = i0 + Math.floor(c * per), b = Math.min(i1, i0 + Math.floor((c + 1) * per));
      let lo = Infinity, hi = -Infinity;
      for (let i = a; i <= b; i++) { const v = s.y[i]; if (v < lo) lo = v; if (v > hi) hi = v; }
      const x = X(s.x0 + a * s.dx);
      ctx.moveTo(x, Y(lo)); ctx.lineTo(x, Y(hi));
    }
  } else {
    for (let i = i0; i <= i1; i++) {
      const x = X(s.x0 + i * s.dx), y = Y(s.y[i]);
      if (i === i0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
  }
  ctx.stroke();
}

/* o: {xmin,xmax,ymin,ymax,ylog,series:[{y,x0,dx,color}],bands,vlines,xfmt,ylabel,empty} */
function plot(canvas, o) {
  const w = canvas.clientWidth, h = canvas.clientHeight;
  if (!w || !h) return;
  const dpr = window.devicePixelRatio || 1;
  if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
    canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
  }
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);

  const L = 52, R = 12, T = 10, B = 24, pw = w - L - R, ph = h - T - B;
  const grid = css('--grid'), muted = css('--muted');
  const lg = v => Math.log10(Math.max(v, o.ymin));
  const X = x => L + (x - o.xmin) / (o.xmax - o.xmin) * pw;
  const Y = o.ylog
    ? y => T + (1 - (lg(y) - lg(o.ymin)) / (lg(o.ymax) - lg(o.ymin))) * ph
    : y => T + (1 - (y - o.ymin) / (o.ymax - o.ymin)) * ph;

  ctx.font = '11px ' + css('--mono');
  ctx.lineWidth = 1; ctx.strokeStyle = grid; ctx.fillStyle = muted;

  const yt = o.ylog ? logTicks(o.ymin, o.ymax) : linTicks(o.ymin, o.ymax, 5);
  const ystep = yt.length > 1 ? yt[1] - yt[0] : 1;
  const ydec = Math.max(0, -Math.floor(Math.log10(ystep) + 1e-9));
  ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
  for (const v of yt) {
    const y = Math.round(Y(v)) + .5;
    ctx.beginPath(); ctx.moveTo(L, y); ctx.lineTo(L + pw, y); ctx.stroke();
    ctx.fillText(o.ylog ? (v >= 0.001 ? String(v) : v.toExponential(0)) : v.toFixed(ydec), L - 6, y);
  }
  const xt = linTicks(o.xmin, o.xmax, Math.max(3, Math.floor(pw / 90)));
  const xstep = xt.length > 1 ? xt[1] - xt[0] : 1;
  const xdec = Math.max(0, -Math.floor(Math.log10(xstep) + 1e-9));
  ctx.textBaseline = 'top';
  for (const v of xt) {
    const x = Math.round(X(v)) + .5;
    ctx.beginPath(); ctx.moveTo(x, T); ctx.lineTo(x, T + ph); ctx.stroke();
    ctx.textAlign = x > L + pw - 24 ? 'right' : x < L + 12 ? 'left' : 'center';   // não corta nas bordas
    ctx.fillText(o.xfmt ? o.xfmt(v) : v.toFixed(xdec), x, T + ph + 6);
  }
  if (o.ylabel) { ctx.textAlign = 'left'; ctx.fillText(o.ylabel, L + 6, T + 4); }

  for (const b of o.bands || []) {
    ctx.fillStyle = b.color;
    const x0 = Math.max(L, X(b.x0)), x1 = Math.min(L + pw, X(b.x1));
    if (x1 > x0) ctx.fillRect(x0, T, x1 - x0, ph);
  }

  ctx.save();
  ctx.beginPath(); ctx.rect(L, T, pw, ph); ctx.clip();
  for (const s of o.series || []) drawSeries(ctx, s, X, Y, pw, o);
  ctx.restore();

  for (const v of o.vlines || []) {
    const x = Math.round(X(v.x)) + .5;
    ctx.setLineDash([4, 4]); ctx.strokeStyle = v.color; ctx.beginPath(); ctx.moveTo(x, T); ctx.lineTo(x, T + ph); ctx.stroke(); ctx.setLineDash([]);
    ctx.fillStyle = v.color; ctx.textBaseline = 'top'; ctx.textAlign = x > L + pw - 90 ? 'right' : 'left';
    ctx.fillText(v.label, x + (ctx.textAlign === 'left' ? 5 : -5), T + 16);
  }

  if (o.empty) {
    ctx.fillStyle = muted; ctx.font = '13px ' + css('--mono'); ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillText(o.empty, L + pw / 2, T + ph / 2);
  }
}

/* ======================================================= DSP (porta de collector/app/dsp.py) */
const fftTab = {};
function fft(re, im) {
  const n = re.length;
  let t = fftTab[n];
  if (!t) {
    t = fftTab[n] = { cos: new Float64Array(n / 2), sin: new Float64Array(n / 2), rev: new Uint32Array(n) };
    for (let i = 0; i < n / 2; i++) { t.cos[i] = Math.cos(2 * Math.PI * i / n); t.sin[i] = -Math.sin(2 * Math.PI * i / n); }
    const bits = Math.log2(n);
    for (let i = 0; i < n; i++) { let r = 0; for (let b = 0; b < bits; b++) r |= ((i >> b) & 1) << (bits - 1 - b); t.rev[i] = r; }
  }
  for (let i = 0; i < n; i++) {
    const j = t.rev[i];
    if (j > i) { let v = re[i]; re[i] = re[j]; re[j] = v; v = im[i]; im[i] = im[j]; im[j] = v; }
  }
  for (let size = 2; size <= n; size <<= 1) {
    const half = size >> 1, step = n / size;
    for (let s = 0; s < n; s += size) {
      for (let k = 0; k < half; k++) {
        const wr = t.cos[k * step], wi = t.sin[k * step], a = s + k, b = a + half;
        const tr = re[b] * wr - im[b] * wi, ti = re[b] * wi + im[b] * wr;
        re[b] = re[a] - tr; im[b] = im[a] - ti; re[a] += tr; im[a] += ti;
      }
    }
  }
}

const hannTab = {};
function hann(n) {                           // igual a np.hanning(n)
  if (!hannTab[n]) {
    const w = new Float64Array(n);
    for (let k = 0; k < n; k++) w[k] = 0.5 - 0.5 * Math.cos(2 * Math.PI * k / (n - 1));
    hannTab[n] = { w, sum: w.reduce((a, b) => a + b, 0) };
  }
  return hannTab[n];
}

/* x: n amostras de um eixo (g) -> amplitude de pico, n/2+1 pontos, janela Hann, sem DC */
function ampSpectrum(x) {
  const n = x.length, { w, sum } = hann(n);
  let mean = 0;
  for (let i = 0; i < n; i++) mean += x[i];
  mean /= n;
  const re = new Float64Array(n), im = new Float64Array(n);
  for (let i = 0; i < n; i++) re[i] = (x[i] - mean) * w[i];
  fft(re, im);
  const out = new Float64Array(n / 2 + 1);
  for (let k = 0; k <= n / 2; k++) out[k] = 2 * Math.hypot(re[k], im[k]) / sum;
  return out;
}

/* Espectro médio (Welch), 50% de sobreposição. Devolve {amp, nper} ou null se faltar dado. */
function welch(x, nper = 1024) {
  const n = x.length;
  if (n < 64) return null;
  if (n < nper) nper = 1 << Math.floor(Math.log2(n));
  const step = Math.max(1, nper >> 1), acc = new Float64Array(nper / 2 + 1);
  let cnt = 0;
  for (let s = 0; s + nper <= n; s += step) {
    const a = ampSpectrum(x.subarray(s, s + nper));
    for (let k = 0; k < a.length; k++) acc[k] += a[k] * a[k];
    cnt++;
  }
  for (let k = 0; k < acc.length; k++) acc[k] = Math.sqrt(acc[k] / cnt);
  return { amp: acc, nper };
}

/* Pico dominante acima de fmin, com interpolação parabólica */
function dominant(col, fs, n, fmin = 3) {
  const df = fs / n, k0 = Math.max(2, Math.ceil(fmin / df));
  if (col.length - 1 <= k0 + 1) return { f: 0, a: 0 };
  let k = k0;
  for (let i = k0; i < col.length - 1; i++) if (col[i] > col[k]) k = i;
  const y0 = col[k - 1], y1 = col[k], y2 = col[k + 1], den = y0 - 2 * y1 + y2;
  const delta = den !== 0 ? Math.max(-0.5, Math.min(0.5, 0.5 * (y0 - y2) / den)) : 0;
  return { f: +((k + delta) * df).toFixed(2), a: y1 };
}

const mean = a => { let s = 0; for (let i = 0; i < a.length; i++) s += a[i]; return s / (a.length || 1); };
const std = a => { const m = mean(a); let s = 0; for (let i = 0; i < a.length; i++) s += (a[i] - m) ** 2; return Math.sqrt(s / (a.length || 1)); };
const ptp = a => { let lo = Infinity, hi = -Infinity; for (let i = 0; i < a.length; i++) { if (a[i] < lo) lo = a[i]; if (a[i] > hi) hi = a[i]; } return hi - lo; };

/* ======================================================= estado */
const SPEC_N = 1024, STALE_MS = 1500, MAX_REC_S = 1800;
const DEFAULT_DEVICE = { name: 'esp32', fw: '', fs: 1666, lsb_g: 0.000122, range_g: 4 };
const DEFAULT_LISTS = {
  classes: ['parado', 'normal', 'desbalanceado_leve', 'desbalanceado_forte', 'folga', 'desalinhado'],
  speeds: ['baixa', 'media', 'alta'],
};
const state = { connected: false, dev: { ...DEFAULT_DEVICE }, spec: null, recs: [], countdownTotal: 1 };
const stream = {};                            // contadores desde que o ESP conectou
const buf = { fs: 0, cap: 0, d: [], n: 0 };
let paused = false, snap = null, dirty = true;
const view = { lo: -0.1, hi: 0.1 };

/* gravação: idle | countdown | recording */
let recState = 'idle', recParams = null, countdownEnd = 0, rec = null;

function resetStream() {
  Object.assign(stream, { lastSeq: null, packets: 0, lost: 0, samples: 0, clipped: 0, protoErrors: 0,
    lastDataT: 0, openT: performance.now(), rateWin: [], pend: [] });
}
resetStream();

function ensureBuf(fs) {
  if (buf.fs === fs) return;
  buf.fs = fs; buf.cap = Math.round(fs * 10);
  buf.d = [0, 1, 2].map(() => new Float32Array(buf.cap));
  buf.n = 0;
}

function pushWave(m) {
  ensureBuf(m.fs);
  AXES.forEach((a, i) => {
    const arr = m[a.k], d = buf.d[i], n = Math.min(arr.length, buf.cap);
    d.copyWithin(0, n);
    d.set(n === arr.length ? arr : arr.slice(-n), buf.cap - n);
  });
  buf.n = Math.min(buf.cap, buf.n + m.n);
  dirty = true;
}

/* junta os pacotes que chegaram desde o último quadro (evita copyWithin a cada pacote) */
function flushPending() {
  if (!stream.pend.length) return;
  let n = 0;
  for (const g of stream.pend) n += g.length / 3;
  const x = new Float32Array(n), y = new Float32Array(n), z = new Float32Array(n);
  let o = 0;
  for (const g of stream.pend) {
    for (let i = 0; i < g.length; i += 3, o++) { x[o] = g[i]; y[o] = g[i + 1]; z[o] = g[i + 2]; }
  }
  stream.pend.length = 0;
  pushWave({ fs: state.dev.fs, n, x, y, z });
}

/* ======================================================= pacotes do ESP */
function onBinary(ab) {
  const dv = new DataView(ab);
  let off = 0;
  while (off + 6 <= ab.byteLength) {         // A5 5A | seq u16 | count u8 | 0 | count × (int16 x,y,z)
    const cnt = dv.getUint8(off + 4), end = off + 6 + cnt * 6;
    if (dv.getUint8(off) !== 0xA5 || dv.getUint8(off + 1) !== 0x5A || end > ab.byteLength) { stream.protoErrors++; return; }
    ingest(dv.getUint16(off + 2, true), new Int16Array(ab.slice(off + 6, end)));
    off = end;
  }
}

function ingest(seq, raw) {
  const n = raw.length / 3, s = stream, d = state.dev;
  let lost = 0;
  if (s.lastSeq !== null) {
    lost = (seq - ((s.lastSeq + 1) & 0xFFFF)) & 0xFFFF;
    if (lost > 0x8000) lost = 0;              // duplicado/fora de ordem: não conta como perda
  }
  s.lastSeq = seq;
  s.packets++;
  if (lost) {
    s.lost += lost;
    if (rec) rec.gaps.push({ at_sample: rec.n, lost_packets: lost, lost_samples_est: lost * n });
  }

  const g = new Float32Array(raw.length), lim = d.range_g * 0.98;
  let clip = 0;
  for (let i = 0; i < n; i++) {
    let c = false;
    for (let a = 0; a < 3; a++) {
      const v = raw[3 * i + a] * d.lsb_g;
      g[3 * i + a] = v;
      if (Math.abs(v) >= lim) c = true;
    }
    if (c) clip++;
  }
  s.clipped += clip;
  s.samples += n;
  const now = performance.now();
  s.lastDataT = now;
  s.rateWin.push([now, n]);
  while (s.rateWin.length && now - s.rateWin[0][0] > 3000) s.rateWin.shift();
  s.pend.push(g);

  if (rec) {
    rec.clipped += clip;
    const m = Math.min(rec.target - rec.n, n);
    rec.data.set(raw.subarray(0, m * 3), rec.n * 3);
    rec.n += m;
    if (rec.n >= rec.target) finishRecording('target');
  }
}

function rateHz() {
  const w = stream.rateWin;
  if (w.length < 2 || w[w.length - 1][0] - w[0][0] < 500) return null;
  let sum = 0;
  for (let i = 1; i < w.length; i++) sum += w[i][1];
  return sum / ((w[w.length - 1][0] - w[0][0]) / 1000);
}

/* ======================================================= gráficos ao vivo */
function drawWave() {
  const cv = $('#cv-wave'), src = paused && snap ? snap : buf;
  const sec = +$('#w-window').value, fs = src.fs || state.dev.fs;
  const m = Math.min(src.n, Math.round(sec * fs));
  const on = AXES.map((a, i) => ({ ...a, i })).filter(a => $('#ax-' + a.k).checked);
  const base = { xmin: -sec, xmax: 0, ymin: view.lo, ymax: view.hi, ylabel: 'g', xfmt: v => v + ' s' };
  if (m < 2 || !on.length) {
    plot(cv, { ...base, series: [], empty: on.length ? 'Aguardando dados do dispositivo…' : 'Selecione um eixo' });
    return;
  }
  const dc = $('#w-dc').checked;
  let lo = Infinity, hi = -Infinity;
  const series = on.map(a => {
    const raw = src.d[a.i].subarray(src.cap - m);
    let mean = 0;
    if (dc) { for (let i = 0; i < m; i++) mean += raw[i]; mean /= m; }
    const y = new Float32Array(m);
    for (let i = 0; i < m; i++) { const v = raw[i] - mean; y[i] = v; if (v < lo) lo = v; if (v > hi) hi = v; }
    return { y, x0: -m / fs, dx: 1 / fs, color: a.color };
  });

  const sel = $('#w-scale').value;
  let tlo, thi;
  if (sel === 'auto') {
    if (dc) { const e = Math.max(Math.abs(lo), Math.abs(hi), 0.01) * 1.15; tlo = -e; thi = e; }
    else { const sp = Math.max(hi - lo, 0.02); tlo = lo - sp * .1; thi = hi + sp * .1; }
    view.lo += (tlo - view.lo) * (tlo < view.lo ? 1 : .12);   // cresce rápido, encolhe devagar
    view.hi += (thi - view.hi) * (thi > view.hi ? 1 : .12);
  } else { view.lo = -sel; view.hi = +sel; }
  plot(cv, { ...base, ymin: view.lo, ymax: view.hi, series });
}

function drawSpec() {
  const cv = $('#cv-spec'), sp = state.spec;
  if (!sp) { plot(cv, { xmin: 0, xmax: 1, ymin: 0, ymax: 1, series: [], empty: 'Aguardando dados do dispositivo…' }); return; }
  const df = sp.fs / sp.n, sel = $('#s-axis').value, log = $('#s-scale').value === 'log';
  const idx = sel === 'all' ? [0, 1, 2] : [AXES.findIndex(a => a.k === sel)];
  const fmax = Math.min(+$('#s-fmax').value || sp.fs / 2, sp.fs / 2);
  const last = Math.floor(fmax / df);
  let mx = 0;
  for (const i of idx) for (let k = 1; k <= last; k++) if (sp.amp[i][k] > mx) mx = sp.amp[i][k];
  const series = idx.map(i => ({ y: sp.amp[i], x0: 0, dx: df, color: AXES[i].color }));
  let best = null;
  for (const i of idx) { const p = sp.peaks[i]; if (p.f > 0 && p.f <= fmax && (!best || p.a > best.a)) best = { ...p, i }; }
  plot(cv, {
    xmin: 0, xmax: fmax, ylog: log, ymin: log ? 1e-4 : 0,
    ymax: log ? Math.pow(10, Math.ceil(Math.log10(Math.max(mx * 1.2, 2e-4)))) : Math.max(mx * 1.15, 0.005),
    ylabel: 'g (pico)', xfmt: v => v + ' Hz', series,
    vlines: best ? [{ x: best.f, color: AXES[best.i].color, label: `${best.f.toFixed(1)} Hz · ${Math.round(best.f * 60)} rpm` }] : [],
  });
}

function frame() {
  flushPending();
  if (dirty) { dirty = false; drawWave(); drawSpec(); }
  requestAnimationFrame(frame);
}

/* ======================================================= status / espectro */
function buildAxesTable() {
  $('#axes-body').innerHTML = AXES.map(a =>
    `<tr><td style="color:${a.color}">${a.name}</td><td id="t-rms-${a.k}">—</td><td id="t-mean-${a.k}">—</td>` +
    `<td id="t-p2p-${a.k}">—</td><td id="t-f-${a.k}">—</td><td id="t-rpm-${a.k}">—</td></tr>`).join('');
}

function computeSpectrum() {
  if (buf.n < SPEC_N || performance.now() - stream.lastDataT > STALE_MS) return;
  const g = buf.d.map(d => d.subarray(buf.cap - SPEC_N));
  const amp = g.map(ampSpectrum);
  onSpectrum({
    fs: buf.fs, n: SPEC_N, amp, peaks: amp.map(a => dominant(a, buf.fs, SPEC_N)),
    rms: g.map(std), mean: g.map(mean), p2p: g.map(ptp),
  });
}

function onSpectrum(sp) {
  state.spec = sp;
  AXES.forEach((a, i) => {
    $('#t-rms-' + a.k).textContent = `${num(sp.rms[i] * 1000, 1)} mg`;
    $('#t-mean-' + a.k).textContent = num(sp.mean[i], 3);
    $('#t-p2p-' + a.k).textContent = `${num(sp.p2p[i] * 1000, 0)} mg`;
    const p = sp.peaks[i];
    $('#t-f-' + a.k).textContent = p.f ? `${num(p.f, 1)} Hz · ${num(p.a * 1000, 1)} mg` : '—';
    $('#t-rpm-' + a.k).textContent = p.f ? Math.round(p.f * 60) : '—';
  });
  dirty = true;
}

function recStatus() {
  const r = { state: recState };
  if (recState === 'countdown') {
    r.label = recParams.label;
    r.countdown_s = Math.max(0, (countdownEnd - performance.now()) / 1000);
  } else if (recState === 'recording' && rec) {
    r.label = recParams.label;
    r.elapsed_s = rec.n / state.dev.fs;
    r.target_s = rec.target / state.dev.fs;
    r.lost_packets = rec.gaps.reduce((a, g) => a + g.lost_packets, 0);
  }
  return r;
}

function onStatus() {
  const d = state.dev, connected = state.connected, rate = rateHz();
  const stale = connected && performance.now() - stream.lastDataT > STALE_MS;
  if (!connected) setPill('pill-dev', 'Dispositivo desconectado', 'off');
  else setPill('pill-dev', `${d.name} · ${location.hostname}${stale ? ' · sem dados' : ''}`, 'live' + (stale ? ' warn' : ''));
  setPill('pill-rate', `${rate ? Math.round(rate) : '—'} / ${Math.round(d.fs)} Hz`,
    rate && Math.abs(rate - d.fs) / d.fs > .05 ? 'warn' : '');
  setPill('pill-lost', `${stream.lost} perdidos`, stream.lost ? 'bad' : '');
  setPill('pill-clip', `${stream.clipped} saturadas`, stream.clipped ? 'warn' : '');
  updateRec(recStatus());
}

/* ======================================================= gravação */
const FORM = ['f-label', 'f-speed', 'f-session', 'f-duration', 'f-delay', 'f-trim', 'f-notes'];

function updateRec(r) {
  const idle = r.state === 'idle', connected = state.connected;
  [...FORM, 'f-session-inc'].forEach(id => { $('#' + id).disabled = !idle; });
  $('#btn-start').disabled = !(connected && idle);
  $('#btn-stop').disabled = idle;
  $('#btn-cancel').disabled = idle;

  const pr = $('#rec-progress'), bar = $('#rec-bar'), pill = $('#rec-pill');
  const say = (icon, text) => { $('#rec-msg').innerHTML = ico(icon) + '<span></span>'; $('#rec-msg span').textContent = text; };
  pr.hidden = pill.hidden = idle;
  pr.classList.toggle('count', r.state === 'countdown');
  if (r.state === 'countdown') {
    bar.style.width = `${100 * (1 - r.countdown_s / state.countdownTotal)}%`;
    say('hourglass', `Começa em ${Math.ceil(r.countdown_s)} s — ${r.label}`);
    $('.t', pill).textContent = `Começa em ${Math.ceil(r.countdown_s)} s`;
  } else if (r.state === 'recording') {
    bar.style.width = `${Math.min(100, 100 * r.elapsed_s / r.target_s)}%`;
    say(r.lost_packets ? 'alert' : 'rec', `Gravando ${r.label}: ${r.elapsed_s.toFixed(1)} / ${r.target_s.toFixed(0)} s` +
      (r.lost_packets ? ` · ${r.lost_packets} pacotes perdidos` : ''));
    const s = Math.floor(r.elapsed_s);
    $('.t', pill).textContent = `REC ${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
  } else if (connected) say('check', 'Pronto para gravar.');
  else say('info', 'Conecte o dispositivo para gravar.');
}

/* 'Desbalanceado Leve' -> 'desbalanceado_leve' (sem acento, só a-z0-9_) */
function slug(text, def = '') {
  const s = String(text).normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
  return s.slice(0, 40) || def;
}

function isoLocal(d) {
  const p = n => String(n).padStart(2, '0'), off = -d.getTimezoneOffset(), a = Math.abs(off);
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}` +
    `${off >= 0 ? '+' : '-'}${p(Math.floor(a / 60))}:${p(a % 60)}`;
}

function startRecording(body) {
  if (!state.connected) return toast('Dispositivo não conectado', 'error');
  if (recState !== 'idle') return toast('Já existe uma gravação em andamento', 'error');
  const label = slug(body.label);
  if (!label) return toast('Classe inválida', 'error');
  const speed = slug(body.speed);
  const duration = Math.min(Math.max(body.duration_s, 1), MAX_REC_S);
  recParams = { label, speed, session: slug(body.session, '1'), notes: body.notes.trim(), duration_s: duration,
    trim_s: Math.min(Math.max(body.trim_s, 0), 30) };
  addToList('classes', label);
  addToList('speeds', speed);
  if (body.delay_s > 0) { recState = 'countdown'; countdownEnd = performance.now() + body.delay_s * 1000; }
  else beginRecording();
  onStatus();
}

function beginRecording() {
  const p = recParams, d = state.dev, now = new Date(), z = n => String(n).padStart(2, '0');
  const stamp = `${now.getFullYear()}${z(now.getMonth() + 1)}${z(now.getDate())}-${z(now.getHours())}${z(now.getMinutes())}${z(now.getSeconds())}`;
  const base = `${p.label}_${p.speed || 'na'}_s${p.session}_${stamp}`;
  let id = base, i = 2;
  while (state.recs.some(r => r.meta.id === id)) id = `${base}-${i++}`;
  const target = Math.round(p.duration_s * d.fs);
  rec = {
    target, n: 0, gaps: [], clipped: 0, data: new Int16Array(target * 3),
    meta: {
      id, label: p.label, speed: p.speed, session: p.session, notes: p.notes, started_at: isoLocal(now),
      device: d.name, fw: d.fw, fs: d.fs, lsb_g: d.lsb_g, range_g: d.range_g, axes: ['x', 'y', 'z'],
      target_duration_s: p.duration_s, trim_s: p.trim_s,
      format: 'int16 little-endian, shape (n_samples, 3) = x,y,z; g = raw * lsb_g',
    },
  };
  recState = 'recording';
}

/* .npy v1.0, int16 little-endian, shape (n, 3) */
function makeNpy(data, n) {
  let h = `{'descr': '<i2', 'fortran_order': False, 'shape': (${n}, 3), }`;
  const pre = 10, total = Math.ceil((pre + h.length + 1) / 64) * 64;
  h = h.padEnd(total - pre - 1, ' ') + '\n';
  const head = new Uint8Array(pre + h.length);
  head.set([0x93, 0x4E, 0x55, 0x4D, 0x50, 0x59, 1, 0]);
  new DataView(head.buffer).setUint16(8, h.length, true);
  for (let i = 0; i < h.length; i++) head[pre + i] = h.charCodeAt(i);
  return new Blob([head, data], { type: 'application/octet-stream' });
}

function download(url, name) {
  const a = document.createElement('a');
  a.href = url; a.download = name;
  document.body.append(a); a.click(); a.remove();
}

function finishRecording(stoppedBy) {
  const r = rec;
  rec = null; recState = 'idle'; recParams = null;
  if (!r || r.n === 0) { onStatus(); return; }
  const data = r.data.slice(0, r.n * 3), m = r.meta;
  const duration = r.n / m.fs, useful = duration - 2 * m.trim_s;
  const lostPk = r.gaps.reduce((a, g) => a + g.lost_packets, 0);
  const issues = [];
  if (stoppedBy === 'disconnect') issues.push('interrompida: dispositivo desconectou');
  if (lostPk) issues.push(`${lostPk} pacotes perdidos`);
  if (r.clipped) issues.push(`${r.clipped} amostras saturadas`);
  if (useful < 10) issues.push(`poucos dados úteis (${Math.max(useful, 0).toFixed(0)} s)`);
  Object.assign(m, {
    n_samples: r.n, duration_s: +duration.toFixed(3), stopped_by: stoppedBy, lost_packets: lostPk, gaps: r.gaps,
    clipped: r.clipped, issues, quality: issues.length ? 'warn' : 'ok',
  });
  const send = driveOn() && driveCfg().auto !== false;
  const entry = makeEntry(m, data, send ? 'pendente' : 'local');
  state.recs.unshift(entry);
  renderRecs();
  idb.put({ id: m.id, meta: m, data, drive: entry.drive });   // guarda no aparelho: sobrevive a recarregar a página
  if (send) driveFlush();
  toast(`Gravação salva: ${m.id}`, m.quality === 'ok' ? 'ok' : 'warn');
  onStatus();
}

function cancelRecording() {
  if (recState === 'recording' && !confirm('Descartar a gravação em andamento?')) return;
  rec = null; recState = 'idle'; recParams = null;
  onStatus();
}

function formBody() {
  return {
    label: $('#f-label').value.trim(), speed: $('#f-speed').value.trim(), session: $('#f-session').value.trim() || '1',
    notes: $('#f-notes').value, duration_s: +$('#f-duration').value || 90, delay_s: +$('#f-delay').value || 0,
    trim_s: +$('#f-trim').value || 0,
  };
}

function setupForm() {
  const saved = ls.get('form', {});
  FORM.forEach(id => {
    if (saved[id] != null) $('#' + id).value = saved[id];
    $('#' + id).addEventListener('input', () => ls.set('form', Object.fromEntries(FORM.map(i => [i, $('#' + i).value]))));
  });
  $('#f-session-inc').onclick = () => {
    $('#f-session').value = String((parseInt($('#f-session').value, 10) || 0) + 1);
    $('#f-session').dispatchEvent(new Event('input'));
  };
  $('#rec-form').addEventListener('submit', e => {
    e.preventDefault();
    const body = formBody();
    state.countdownTotal = Math.max(body.delay_s, 1);
    startRecording(body);
  });
  $('#btn-stop').onclick = () => { if (recState === 'countdown') { recState = 'idle'; recParams = null; onStatus(); } else finishRecording('user'); };
  $('#btn-cancel').onclick = cancelRecording;
}

/* ======================================================= listas */
const listOf = k => [...new Set([...DEFAULT_LISTS[k], ...ls.get('extra.' + k, [])])];
function addToList(k, v) {
  if (v && !listOf(k).includes(v)) ls.set('extra.' + k, [...ls.get('extra.' + k, []), v]);
  renderLists();
}
function renderLists() {
  $('#dl-labels').innerHTML = listOf('classes').map(c => `<option value="${esc(c)}">`).join('');
  $('#dl-speeds').innerHTML = listOf('speeds').map(c => `<option value="${esc(c)}">`).join('');
}

const fmtDate = iso => new Date(iso).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'medium' });

/* ======================================================= Google Drive (via Apps Script, ver drive/LEIA-ME.md) */
/* A página vem de http://, então não dá para usar o login OAuth do Google aqui. Em vez disso, um script
   publicado na conta do usuário recebe POSTs de texto simples (sem preflight CORS) e mexe na pasta. */
const drive = { remote: [], remoteErr: null, busy: false };
const DRIVE_URL_PADRAO = 'https://script.google.com/macros/s/AKfycbxJ5vYNHJgJ8XOFgBNqmsiTlFhzHmYQSChGpKyG5PeseatDQB-R2HVgR5GB8kDgNRH6fQ/exec';
const driveCfg = () => {
  const c = { token: '', auto: true, ...ls.get('drive', {}) };
  return { ...c, url: c.url || DRIVE_URL_PADRAO };     // sem URL salva usa a padrão; a senha nunca vem de fábrica
};
const driveOn = () => { const c = driveCfg(); return !!(c.url && c.token); };

async function driveCall(action, payload = {}, cfg = driveCfg()) {
  const r = await fetch(cfg.url, {
    method: 'POST', redirect: 'follow', headers: { 'Content-Type': 'text/plain;charset=utf-8' },
    body: JSON.stringify({ token: cfg.token, action, ...payload }),
  });
  let j;
  try { j = await r.json(); } catch { throw new Error('Resposta inesperada: confira se a implantação do script está como "Qualquer pessoa"'); }
  if (!j.ok) throw new Error(j.error || 'Erro no Drive');
  return j;
}

const semInternet = err => err.message === 'Failed to fetch' || (typeof navigator !== 'undefined' && navigator.onLine === false);
const OFFLINE = 'sem internet';

const blobB64 = blob => new Promise((res, rej) => {
  const f = new FileReader();
  f.onload = () => res(String(f.result).split(',')[1]);
  f.onerror = () => rej(f.error);
  f.readAsDataURL(blob);
});
const b64Bytes = b64 => Uint8Array.from(atob(b64), c => c.charCodeAt(0));

/* fila persistente: gravação que ainda não subiu sobrevive a recarregar a página (celular sem internet no AP) */
const idb = {
  db: null,
  open() {
    return new Promise(res => {
      if (typeof indexedDB === 'undefined') return res(null);
      const r = indexedDB.open('coletas', 1);
      r.onupgradeneeded = () => r.result.createObjectStore('fila', { keyPath: 'id' });
      r.onsuccess = () => res(r.result);
      r.onerror = () => res(null);
    });
  },
  tx(mode, fn) {
    return new Promise(res => {
      if (!this.db) return res(null);
      const t = this.db.transaction('fila', mode);
      const req = fn(t.objectStore('fila'));
      t.oncomplete = () => res(req && req.result);
      t.onerror = t.onabort = () => res(null);
    });
  },
  put(rec) { return this.tx('readwrite', s => s.put(rec)); },
  del(id) { return this.tx('readwrite', s => s.delete(id)); },
  all() { return this.tx('readonly', s => s.getAll()); },
};

function makeEntry(meta, data, driveState) {
  const npyBlob = makeNpy(data, data.length / 3), jsonText = JSON.stringify(meta, null, 2);
  return {
    meta, data, npyBlob, jsonText, drive: driveState,
    npyUrl: URL.createObjectURL(npyBlob), jsonUrl: URL.createObjectURL(new Blob([jsonText], { type: 'application/json' })),
  };
}

/* depois de enviada, a gravação sai da memória do aparelho (celular não aguenta dezenas de sessões) */
function dropData(e) {
  URL.revokeObjectURL(e.npyUrl); URL.revokeObjectURL(e.jsonUrl);
  e.data = e.npyBlob = e.npyUrl = e.jsonUrl = null;
}

async function driveFlush() {
  if (drive.busy || !driveOn()) return;
  const todo = () => state.recs.filter(e => e.data && (e.drive === 'pendente' || e.drive === 'erro'));
  if (!todo().length) return;
  drive.busy = true;
  let sent = 0;
  try {
    for (const e of todo()) {
      e.drive = 'enviando'; renderRecs();
      try {
        await driveCall('upload', { id: e.meta.id, npy_b64: await blobB64(e.npyBlob), json_text: e.jsonText });
        e.drive = 'enviado'; e.driveErr = null; sent++;
        idb.del(e.meta.id);
        dropData(e);
      } catch (err) {
        const off = semInternet(err);
        e.drive = 'erro'; e.driveErr = off ? OFFLINE : err.message;
        if (!e.driveWarned) {
          e.driveWarned = true;
          toast(off ? 'Sem internet neste aparelho (no Wi-Fi do sensor é normal). A gravação fica guardada e sobe quando houver conexão: abra esta página pelo roteador.'
                    : `Drive: ${err.message}. Vou tentar de novo.`, 'warn');
        }
        break;                                // sem internet/credencial errada: para e tenta no próximo ciclo
      }
    }
  } finally { drive.busy = false; }
  if (sent) toast(`${sent} gravação(ões) enviada(s) ao Drive`, 'ok');
  await refreshRemote();
}

async function refreshRemote() {
  if (!driveOn()) { drive.remote = []; drive.remoteErr = null; renderRecs(); return; }
  try { drive.remote = (await driveCall('list')).items; drive.remoteErr = null; }
  catch (err) { drive.remoteErr = semInternet(err) ? OFFLINE : err.message; }
  renderRecs();
}

function updateDrivePill() {
  const pend = state.recs.filter(e => e.drive && e.drive !== 'enviado' && e.drive !== 'local').length;
  const on = driveOn(), el = $('#btn-drive');
  const off = drive.remoteErr === OFFLINE || state.recs.some(e => e.driveErr === OFFLINE);
  $('.t', el).textContent = !on ? 'Drive' : off ? `Drive · sem internet${pend ? ` · ${pend} na fila` : ''}` : pend ? `Drive · ${pend} na fila` : drive.remoteErr ? 'Drive · erro' : 'Drive';
  el.className = 'pill' + (!on ? '' : off ? ' warn' : drive.remoteErr ? ' bad' : pend ? ' warn' : ' live');
  $('#drive-line').textContent = !on ? 'só neste aparelho' : drive.remoteErr ? (off ? 'sem internet: só os desta página' : drive.remoteErr) : `${drive.remote.length} no Drive`;
}

/* gravação completa: a que está na memória ou, se já subiu, baixada do Drive */
async function entryOf(id) {
  const e = state.recs.find(r => r.meta.id === id);
  if (e && e.data) return e;
  const meta = e ? e.meta : drive.remote.find(m => m.id === id);
  if (!meta) throw new Error('Gravação não encontrada');
  toast('Baixando do Drive…');
  const bytes = b64Bytes((await driveCall('get', { id, kind: 'npy' })).b64);
  const off = 10 + new DataView(bytes.buffer).getUint16(8, true);   // cabeçalho do .npy v1.0
  return { meta, data: new Int16Array(bytes.buffer.slice(off)) };
}

/* lista única: o que está nesta página + o que só existe no Drive */
function rowsAll() {
  const have = new Set(state.recs.map(e => e.meta.id));
  const rows = state.recs.map(e => ({ meta: e.meta, local: e, st: e.drive || 'local' }));
  for (const m of drive.remote) if (!have.has(m.id)) rows.push({ meta: m, local: null, st: 'enviado' });
  return rows.sort((a, b) => new Date(b.meta.started_at) - new Date(a.meta.started_at));
}

const ST = {                                  // estado -> [ícone, texto, classe do selo]
  local: ['info', 'só neste aparelho', 'off'], pendente: ['clock', 'na fila', 'warn'], enviando: ['upload', 'enviando…', 'warn'],
  enviado: ['cloud', 'no Drive', 'ok'], erro: ['alert', 'erro, tentando de novo', 'warn'],
};

function renderRecs() {
  const rs = rowsAll(), on = driveOn();
  $('#recs-count').textContent = rs.length ? `(${rs.length})` : '';
  $('#recs-body').innerHTML = rs.length ? rs.map(({ meta: r, local: e, st }) => {
    const id = esc(r.id), issues = (r.issues || []).join('; '), ok = r.quality === 'ok', [si, stText0, stCls] = ST[st], stText = e?.driveErr === OFFLINE && st === 'erro' ? 'sem internet, na fila' : stText0;
    return `<tr><td>${fmtDate(r.started_at)}</td><td><span class="tag">${esc(r.label)}</span></td><td data-l="vel. ">${esc(r.speed || '—')}</td>` +
      `<td data-l="sessão ">${esc(r.session)}</td><td>${num(r.duration_s, 1)} s</td>` +
      `<td><span class="badge ${r.quality}" title="${esc(issues)}">${ico(ok ? 'check' : 'alert')}${ok ? 'OK' : 'Atenção'}</span></td>` +
      `<td><span class="badge ${stCls}" title="${esc(e?.driveErr || '')}">${ico(si)}${stText}</span></td>` +
      `<td class="notes" title="${esc(r.notes)}">${esc(r.notes)}</td>` +
      `<td class="act"><button class="lnk" data-act="view" data-id="${id}" title="Ver gráficos">${ico('eye')}Ver</button>` +
      `<button class="lnk" data-act="npy" data-id="${id}" title="Baixar .npy">${ico('download')}.npy</button>` +
      `<button class="lnk" data-act="json" data-id="${id}" title="Baixar metadados">${ico('download')}.json</button>` +
      (on && st === 'local' ? `<button class="lnk" data-act="up" data-id="${id}" title="Enviar ao Drive">${ico('upload')}Drive</button>` : '') +
      `<button class="lnk del" data-act="del" data-id="${id}" title="Excluir">${ico('trash')}</button></td></tr>`;
  }).join('') : `<tr><td class="empty" colspan="9">${ico('inbox')}Nenhuma gravação ainda. Conecte o dispositivo e clique em Gravar.</td></tr>`;
  updateDrivePill();
}

async function onRecAction(act, id) {
  const e = state.recs.find(r => r.meta.id === id);
  try {
    if (act === 'view') return await openPreview(id);
    if (act === 'json') {
      const meta = e ? e.meta : drive.remote.find(m => m.id === id);
      const url = e?.jsonUrl || URL.createObjectURL(new Blob([JSON.stringify(meta, null, 2)], { type: 'application/json' }));
      return download(url, id + '.json');
    }
    if (act === 'npy') {
      if (e?.npyUrl) return download(e.npyUrl, id + '.npy');
      const full = await entryOf(id);
      return download(URL.createObjectURL(makeNpy(full.data, full.data.length / 3)), id + '.npy');
    }
    if (act === 'up') { e.drive = 'pendente'; await idb.put({ id, meta: e.meta, data: e.data, drive: 'pendente' }); renderRecs(); return driveFlush(); }
    if (act === 'del') {
      const onDrive = driveOn() && (e?.drive === 'enviado' || drive.remote.some(m => m.id === id));
      if (!confirm(onDrive ? `Excluir ${id}?\nVai para a lixeira do Drive e some desta lista.` : `Remover ${id} da lista?\nArquivos já baixados não são afetados.`)) return;
      if (onDrive) await driveCall('delete', { id });
      if (e) { if (e.data) dropData(e); state.recs.splice(state.recs.indexOf(e), 1); idb.del(id); }
      drive.remote = drive.remote.filter(m => m.id !== id);
      renderRecs();
      if (onDrive) refreshRemote();
    }
  } catch (err) { toast(err.message, 'error'); }
}

/* resultado do teste fica DENTRO do diálogo: o toast ficaria atrás do modal e não seria visto */
function driveResult(kind, text) {
  const icon = { ok: 'check', bad: 'xcircle', warn: 'hourglass' }[kind];
  $('#dr-result').innerHTML = `<span class="badge ${kind}">${ico(icon)}<span></span></span>`;
  $('#dr-result .badge span:last-child').textContent = text;
}

function openDrive() {
  const c = driveCfg();
  $('#dr-url').value = c.url; $('#dr-token').value = c.token;
  $('#dr-auto').checked = c.auto !== false;
  $('#dr-result').innerHTML = '';
  $('#dlg-drive').showModal();
  if (!c.token) $('#dr-token').focus();
}
const driveForm = () => ({ url: $('#dr-url').value.trim() || DRIVE_URL_PADRAO, token: $('#dr-token').value, auto: $('#dr-auto').checked });

async function testDrive() {
  const cfg = driveForm();
  if (!cfg.token) return driveResult('bad', 'Informe a senha para testar');
  driveResult('warn', 'Testando conexão…');
  $('#dr-test').disabled = true;
  try { driveResult('ok', `Conectado à pasta "${(await driveCall('ping', {}, cfg)).folder}"`); }
  catch (err) { driveResult('bad', semInternet(err) ? 'Sem internet neste aparelho. No Wi-Fi do sensor não há internet: use o Wi-Fi do roteador.' : err.message); }
  finally { $('#dr-test').disabled = false; }
}

function saveDrive(e) {
  e.preventDefault();
  const cfg = driveForm();
  if (!cfg.token) return driveResult('bad', 'Informe a senha para ativar o Drive, ou escolha "Não usar o Drive"');
  ls.set('drive', cfg);
  ls.set('driveSkip', false);
  $('#dlg-drive').close();
  toast('Drive configurado', 'ok');
  state.recs.forEach(r => { r.driveWarned = false; });
  refreshRemote().then(driveFlush);
}

function skipDrive() {                          // Drive é opcional: guarda a escolha e não pergunta mais ao abrir
  ls.set('driveSkip', true);
  ls.set('drive', { ...driveForm(), token: '' });
  $('#dlg-drive').close();
  toast('Drive desativado: as gravações ficam só neste aparelho', '');
  refreshRemote();
}

async function restoreQueue() {               // gravações guardadas no aparelho (fila do Drive e só-locais) antes de recarregar
  idb.db = await idb.open();
  for (const r of (await idb.all()) || []) {
    if (!state.recs.some(e => e.meta.id === r.id)) state.recs.push(makeEntry(r.meta, r.data, r.drive || 'pendente'));
  }
  state.recs.sort((a, b) => new Date(b.meta.started_at) - new Date(a.meta.started_at));
  renderRecs();
  driveFlush();
}

/* ======================================================= pré-visualização (porta de /preview do Python) */
let preview = null;

function buildPreview(e) {
  const m = e.meta, fs = m.fs, n = e.data.length / 3;
  const g = [0, 1, 2].map(a => { const y = new Float32Array(n); for (let i = 0; i < n; i++) y[i] = e.data[3 * i + a] * m.lsb_g; return y; });

  let a = Math.floor((m.trim_s || 0) * fs), b = n - a;
  if (b - a < fs) { a = 0; b = n; }           // trim maior que a gravação: usa tudo

  const win = Math.max(1, Math.floor(0.25 * fs)), nw = Math.floor(n / win);
  const rms = g.map(y => Array.from({ length: nw }, (_, w) => std(y.subarray(w * win, (w + 1) * win))));

  const mid = (a + b) >> 1, s0 = Math.max(0, Math.min(mid - Math.floor(fs), n - Math.floor(2 * fs)));
  const wave = g.map(y => { const seg = y.slice(s0, s0 + Math.floor(2 * fs)), mu = mean(seg); return seg.map(v => v - mu); });

  const ws = g.map(y => welch(y.subarray(a, b)));
  const spectrum = ws[0] ? { df: fs / ws[0].nper, amp: ws.map(w => w.amp) } : null;
  return { meta: m, trim_s: [a / fs, b / fs], rms: { dt: win / fs, series: rms }, wave: { t0: s0 / fs, series: wave }, spectrum };
}

function drawPreview() {
  if (!preview) return;
  const p = preview, m = p.meta, fs = m.fs;
  const rmsN = p.rms.series[0].length, total = rmsN * p.rms.dt;
  const shade = 'rgba(0,0,0,.45)';
  let mx = 0.001;
  p.rms.series.forEach(s => s.forEach(v => { if (v > mx) mx = v; }));
  plot($('#cv-rms'), {
    xmin: 0, xmax: total, ymin: 0, ymax: mx * 1.15, ylabel: 'g RMS', xfmt: v => v + ' s',
    series: p.rms.series.map((y, i) => ({ y, x0: p.rms.dt / 2, dx: p.rms.dt, color: AXES[i].color })),
    bands: [{ x0: 0, x1: p.trim_s[0], color: shade }, { x0: p.trim_s[1], x1: total, color: shade }],
  });

  let wm = 0.001;
  p.wave.series.forEach(s => s.forEach(v => { if (Math.abs(v) > wm) wm = Math.abs(v); }));
  plot($('#cv-pwave'), {
    xmin: p.wave.t0, xmax: p.wave.t0 + 2, ymin: -wm * 1.15, ymax: wm * 1.15, ylabel: 'g', xfmt: v => v.toFixed(1) + ' s',
    series: p.wave.series.map((y, i) => ({ y, x0: p.wave.t0, dx: 1 / fs, color: AXES[i].color })),
  });

  const sp = p.spectrum;
  if (!sp) { plot($('#cv-pspec'), { xmin: 0, xmax: 1, ymin: 0, ymax: 1, series: [], empty: 'Trecho útil curto demais' }); return; }
  let sm = 2e-4;
  sp.amp.forEach(s => s.forEach((v, k) => { if (k > 1 && v > sm) sm = v; }));
  plot($('#cv-pspec'), {
    xmin: 0, xmax: fs / 2, ylog: true, ymin: 1e-4, ymax: Math.pow(10, Math.ceil(Math.log10(sm * 1.2))),
    ylabel: 'g (pico)', xfmt: v => v + ' Hz',
    series: sp.amp.map((y, i) => ({ y, x0: 0, dx: sp.df, color: AXES[i].color })),
  });
}

async function openPreview(id) {
  const e = await entryOf(id);
  preview = buildPreview(e);
  const m = e.meta;
  $('#dlg-title').textContent = m.id;
  $('#dlg-meta').textContent = `${m.label} · vel. ${m.speed || '—'} · sessão ${m.session} · ${num(m.duration_s, 1)} s · ${m.fs} Hz · ` +
    `descartando ${m.trim_s} s nas pontas` + (m.issues?.length ? ` · ⚠ ${m.issues.join('; ')}` : '') + (m.notes ? ` · “${m.notes}”` : '');
  $('#dlg').showModal();
  requestAnimationFrame(drawPreview);
}

/* ======================================================= rede (Wi-Fi do roteador) */
async function openNet() {
  $('#dlg-net').showModal();
  try {
    const n = await (await fetch('/api/rede')).json();
    $('#net-ssid').value = n.ssid;
    $('#net-info').textContent = (n.conectado ? `Roteador: conectado (${n.ssid}, IP ${n.ip}). ` : 'Roteador: desconectado. ') +
      `Ponto de acesso do sensor: ${n.ap_ssid} (${n.ap_ip}).`;
  } catch { $('#net-info').textContent = 'Não foi possível ler a configuração.'; }
}

async function saveNet(e) {
  e.preventDefault();
  const r = await fetch('/api/rede', { method: 'POST', body: new URLSearchParams({ ssid: $('#net-ssid').value, pass: $('#net-pass').value }) });
  if (r.ok) { toast('Salvo na flash. Conectando ao roteador…', 'ok'); $('#dlg-net').close(); }
  else toast((await r.json().catch(() => ({}))).detail || 'Erro ao salvar', 'error');
}

/* ======================================================= conexão com o ESP */
let devWs = null;

function connectDevice() {
  const ws = devWs = new WebSocket(`ws://${location.hostname}:81/`);
  ws.binaryType = 'arraybuffer';
  let done = false;
  const connectTimer = setTimeout(() => { if (ws.readyState !== WebSocket.OPEN) ws.kill(); }, 6000);   // handshake que nunca completa
  const closed = () => {
    if (done) return;
    done = true;
    clearTimeout(connectTimer);
    if (devWs === ws) devWs = null;
    if (state.connected) toast('Dispositivo desconectado', 'warn');
    state.connected = false;
    if (rec) finishRecording('disconnect');
    else if (recState === 'countdown') { recState = 'idle'; recParams = null; }
    onStatus();
    setTimeout(connectDevice, 1000);
  };
  /* Conexão que morre sem aviso (ex.: o sensor trocou de rede) nunca dispara onclose: o vigia chama kill() e reconecta. */
  ws.kill = () => { ws.onmessage = null; ws.onclose = null; try { ws.close(); } catch { /* já morta */ } closed(); };
  ws.onopen = () => {
    clearTimeout(connectTimer);
    resetStream();
    state.connected = true;
    toast('Dispositivo conectado', '');
    onStatus();
  };
  ws.onclose = closed;
  ws.onmessage = ev => {
    if (typeof ev.data !== 'string') return onBinary(ev.data);
    let d;
    try { d = JSON.parse(ev.data); } catch { return; }
    if (d.type !== 'hello') return;
    state.dev = {
      name: String(d.device ?? 'esp32').slice(0, 40), fw: String(d.fw ?? '').slice(0, 20),
      fs: Math.min(Math.max(+d.fs || 1666, 10), 20000), lsb_g: +d.lsb_g || DEFAULT_DEVICE.lsb_g, range_g: +d.range_g || DEFAULT_DEVICE.range_g,
    };
    stream.lastSeq = null;
    onStatus();
  };
}

/* sem pacotes por 4 s (8 s se estiver gravando) com a conexão "aberta" = conexão morta: refaz */
function watchStream() {
  if (!state.connected || !devWs) return;
  const idle = performance.now() - Math.max(stream.lastDataT, stream.openT);
  if (idle > (rec ? 8000 : 4000)) devWs.kill();
}

/* ======================================================= inicialização */
function init() {
  buildAxesTable();
  setupForm();
  renderLists();
  renderRecs();

  for (const id of ['ax-x', 'ax-y', 'ax-z', 'w-window', 'w-scale', 'w-dc', 's-axis', 's-scale', 's-fmax']) {
    const el = $('#' + id), saved = ls.get(id);
    if (saved != null) { if (el.type === 'checkbox') el.checked = saved; else el.value = saved; }
    el.addEventListener('change', () => { ls.set(id, el.type === 'checkbox' ? el.checked : el.value); dirty = true; });
  }
  $('#w-pause').onclick = e => {
    paused = !paused;
    snap = paused ? { fs: buf.fs, cap: buf.cap, n: buf.n, d: buf.d.map(a => a.slice()) } : null;
    e.currentTarget.innerHTML = paused ? ico('play') + '<span>Continuar</span>' : ico('pause') + '<span>Pausar</span>';
    dirty = true;
  };

  $('#recs-body').addEventListener('click', e => {
    const b = e.target.closest('button[data-act]');
    if (b) onRecAction(b.dataset.act, b.dataset.id);
  });
  $('#btn-drive').onclick = openDrive;
  $('#drive-close').onclick = () => $('#dlg-drive').close();
  $('#drive-form').addEventListener('submit', saveDrive);
  $('#dr-test').onclick = testDrive;
  $('#dr-skip').onclick = skipDrive;
  $('#btn-refresh').onclick = refreshRemote;
  window.addEventListener('online', driveFlush);
  setInterval(driveFlush, 20000);             // tenta de novo o que ficou na fila
  setInterval(refreshRemote, 120000);         // vê gravações que outro aparelho mandou
  $('#btn-net').onclick = openNet;
  $('#net-close').onclick = () => $('#dlg-net').close();
  $('#net-form').addEventListener('submit', saveNet);
  $('#dlg-close').onclick = () => $('#dlg').close();
  $('#dlg').addEventListener('click', e => { if (e.target === e.currentTarget) e.currentTarget.close(); });
  $('#dlg').addEventListener('close', () => { preview = null; });
  window.addEventListener('resize', () => { dirty = true; drawPreview(); });
  window.addEventListener('beforeunload', e => { if (rec) e.preventDefault(); });   // não perder gravação em andamento

  let tick = 0;
  setInterval(() => {                         // 10 Hz: contador e status; espectro a 5 Hz
    if (recState === 'countdown' && performance.now() >= countdownEnd) beginRecording();
    if (++tick % 2 === 0) computeSpectrum();
    watchStream();
    onStatus();
  }, 100);
  connectDevice();
  requestAnimationFrame(frame);
  restoreQueue().then(refreshRemote);
  if (!driveCfg().token && !ls.get('driveSkip', false)) openDrive();   // pede a senha; o Drive só liga depois de configurada
}

init();
