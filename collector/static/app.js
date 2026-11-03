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

async function api(path, opts = {}) {
  const r = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...opts });
  if (!r.ok) {
    let d = r.statusText;
    try { const j = await r.json(); d = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail); } catch { /* corpo vazio */ }
    throw new Error(d);
  }
  return r.json();
}

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

/* ======================================================= estado */
const state = { status: null, spec: null, config: null, recs: [], lastSaved: undefined, countdownTotal: 1 };
const buf = { fs: 0, cap: 0, d: [], n: 0 };
let paused = false, snap = null, dirty = true;
const view = { lo: -0.1, hi: 0.1 };

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

/* ======================================================= gráficos ao vivo */
function drawWave() {
  const cv = $('#cv-wave'), src = paused && snap ? snap : buf;
  const sec = +$('#w-window').value, fs = src.fs || 1600;
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
  if (dirty) { dirty = false; drawWave(); drawSpec(); }
  requestAnimationFrame(frame);
}

/* ======================================================= status / espectro */
function buildAxesTable() {
  $('#axes-body').innerHTML = AXES.map(a =>
    `<tr><td style="color:${a.color}">${a.name}</td><td id="t-rms-${a.k}">—</td><td id="t-mean-${a.k}">—</td>` +
    `<td id="t-p2p-${a.k}">—</td><td id="t-f-${a.k}">—</td><td id="t-rpm-${a.k}">—</td></tr>`).join('');
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

function onStatus(st) {
  state.status = st;
  if (!st.connected) setPill('pill-dev', 'Dispositivo desconectado', 'off');
  else setPill('pill-dev', `${st.device.name} · ${st.device.ip}${st.stale ? ' · sem dados' : ''}`, 'live' + (st.stale ? ' warn' : ''));
  const fs = st.device.fs;
  setPill('pill-rate', `${st.rate_hz ? Math.round(st.rate_hz) : '—'} / ${Math.round(fs)} Hz`,
    st.rate_hz && Math.abs(st.rate_hz - fs) / fs > .05 ? 'warn' : '');
  setPill('pill-lost', `${st.lost_packets} perdidos`, st.lost_packets ? 'bad' : '');
  setPill('pill-clip', `${st.clipped} saturadas`, st.clipped ? 'warn' : '');
  updateRec(st);
}

/* ======================================================= gravação */
const FORM = ['f-label', 'f-speed', 'f-session', 'f-duration', 'f-delay', 'f-trim', 'f-notes'];

function updateRec(st) {
  const r = st.recording, idle = r.state === 'idle';
  [...FORM, 'f-session-inc'].forEach(id => { $('#' + id).disabled = !idle; });
  $('#btn-start').disabled = !(st.connected && idle);
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
  } else if (st.connected) say('check', 'Pronto para gravar.');
  else say('info', 'Conecte o dispositivo para gravar.');

  if (r.last_saved !== state.lastSaved) {
    if (state.lastSaved !== undefined) loadRecs();
    state.lastSaved = r.last_saved;
  }
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
  $('#rec-form').addEventListener('submit', async e => {
    e.preventDefault();
    const body = formBody();
    state.countdownTotal = Math.max(body.delay_s, 1);
    try { await api('/api/recordings/start', { method: 'POST', body: JSON.stringify(body) }); }
    catch (err) { toast(err.message, 'error'); }
  });
  $('#btn-stop').onclick = () => api('/api/recordings/stop', { method: 'POST' }).catch(err => toast(err.message, 'error'));
  $('#btn-cancel').onclick = () => {
    if (state.status?.recording.state === 'recording' && !confirm('Descartar a gravação em andamento?')) return;
    api('/api/recordings/cancel', { method: 'POST' }).catch(err => toast(err.message, 'error'));
  };
}

/* ======================================================= listas */
async function loadConfig() {
  state.config = await api('/api/config');
  $('#dl-labels').innerHTML = state.config.classes.map(c => `<option value="${esc(c)}">`).join('');
  $('#dl-speeds').innerHTML = state.config.speeds.map(c => `<option value="${esc(c)}">`).join('');
}

async function loadRecs() {
  try {
    [state.recs] = await Promise.all([api('/api/recordings'), loadConfig()]);
  } catch (err) { toast(err.message, 'error'); return; }
  renderRecs();
}

const fmtDate = iso => new Date(iso).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'medium' });

function renderRecs() {
  const rs = state.recs;
  $('#recs-count').textContent = rs.length ? `(${rs.length})` : '';
  $('#recs-body').innerHTML = rs.length ? rs.map(r => {
    const id = esc(r.id), issues = (r.issues || []).join('; ');
    const ok = r.quality === 'ok';
    return `<tr><td>${fmtDate(r.started_at)}</td><td><span class="tag">${esc(r.label)}</span></td><td>${esc(r.speed || '—')}</td>` +
      `<td>${esc(r.session)}</td><td>${num(r.duration_s, 1)} s</td>` +
      `<td><span class="badge ${r.quality}" title="${esc(issues)}">${ico(ok ? 'check' : 'alert')}${ok ? 'OK' : 'Atenção'}</span></td>` +
      `<td class="notes" title="${esc(r.notes)}">${esc(r.notes)}</td>` +
      `<td class="act"><button class="lnk" data-act="view" data-id="${id}" title="Ver gráficos">${ico('eye')}Ver</button>` +
      `<a class="lnk" href="/api/recordings/${encodeURIComponent(r.id)}/download" title="Baixar .npy">${ico('download')}.npy</a>` +
      `<button class="lnk del" data-act="del" data-id="${id}" title="Excluir">${ico('trash')}</button></td></tr>`;
  }).join('') : `<tr><td class="empty" colspan="8">${ico('inbox')}Nenhuma gravação ainda. Conecte o dispositivo e clique em Gravar.</td></tr>`;
}

/* ======================================================= pré-visualização */
let preview = null;

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
  try { preview = await api(`/api/recordings/${encodeURIComponent(id)}/preview`); }
  catch (err) { toast(err.message, 'error'); return; }
  const m = preview.meta;
  $('#dlg-title').textContent = m.id;
  $('#dlg-meta').textContent = `${m.label} · vel. ${m.speed || '—'} · sessão ${m.session} · ${num(m.duration_s, 1)} s · ${m.fs} Hz · ` +
    `descartando ${m.trim_s} s nas pontas` + (m.issues?.length ? ` · ⚠ ${m.issues.join('; ')}` : '') + (m.notes ? ` · “${m.notes}”` : '');
  $('#dlg').showModal();
  requestAnimationFrame(drawPreview);
}

/* ======================================================= inicialização */
function connectUi() {
  const ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/ui`);
  ws.onopen = () => setPill('pill-ui', 'UI', 'live');
  ws.onclose = () => { setPill('pill-ui', 'UI offline', 'off'); setTimeout(connectUi, 1000); };
  ws.onmessage = ev => {
    const m = JSON.parse(ev.data);
    if (m.t === 'wave') pushWave(m);
    else if (m.t === 'spectrum') onSpectrum(m);
    else if (m.t === 'status') onStatus(m);
    else if (m.t === 'event') toast(m.text, m.level === 'info' ? '' : m.level);
  };
}

function init() {
  buildAxesTable();
  setupForm();

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

  $('#recs-body').addEventListener('click', async e => {
    const b = e.target.closest('button[data-act]');
    if (!b) return;
    if (b.dataset.act === 'view') openPreview(b.dataset.id);
    else if (confirm(`Excluir ${b.dataset.id}?\nOs arquivos .npy e .json serão apagados.`)) {
      try { await api(`/api/recordings/${encodeURIComponent(b.dataset.id)}`, { method: 'DELETE' }); loadRecs(); }
      catch (err) { toast(err.message, 'error'); }
    }
  });
  $('#btn-folder').onclick = () => api('/api/open-folder', { method: 'POST' }).catch(err => toast(err.message, 'error'));
  $('#dlg-close').onclick = () => $('#dlg').close();
  $('#dlg').addEventListener('click', e => { if (e.target === e.currentTarget) e.currentTarget.close(); });
  $('#dlg').addEventListener('close', () => { preview = null; });
  window.addEventListener('resize', () => { dirty = true; drawPreview(); });

  loadRecs();
  connectUi();
  requestAnimationFrame(frame);
}

init();
