/* ==========================================================
   교통 관제탑 - 화면 동작
   영상은 브라우저 기본 재생기(controls)에 전적으로 맡기고,
   자바스크립트는 데이터 표시만 담당합니다.
   ========================================================== */

const $  = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));

const RISK_TEXT = {
  safe:    { word: '안전', desc: '제한속도 내에서 통행 중입니다' },
  caution: { word: '주의', desc: '제한속도를 넘는 차량이 있습니다' },
  danger:  { word: '위험', desc: '과속 차량이 확인됩니다' }
};
const RISK_TAG = { safe: '안전', caution: '주의', danger: '위험', unknown: '측정 부족' };

const state = {
  data: null, view: 'yolo', lastSec: -1, filter: 'all', shown: 30,
  evTab: 'stopline',        // 위반 목록에서 보고 있는 종류
  events: { stopline: [], tailgate: [] },
  fired: new Set(),         // 이미 알린 위반
  predict: null,            // 이동경로 예측 데이터
  predictOn: false,
  alertTimer: null
};

/* ----------------------------------------------------------
   서버(Flask) 없이 GitHub Pages 같은 정적 호스팅에서도 돌도록
   경로를 한 곳에서 만들어 씁니다.
   window.STATIC_MODE 는 정적 빌드에서 index.html 에 주입됩니다.
   ---------------------------------------------------------- */
const STATIC = typeof window.STATIC_MODE !== 'undefined' && window.STATIC_MODE;

/* 정적 모드에서는 상대 경로를 씁니다.
   그래야 user.github.io/ 든 user.github.io/저장소/ 든 그대로 동작합니다. */
const api = {
  videos: () => STATIC ? 'data/videos.json' : '/api/videos',
  video:  (id) => STATIC ? `data/video-${id}.json` : `/api/video/${id}`,
  places: () => STATIC ? 'data/places.json' : '/api/places',
  media:  (id, kind) => STATIC ? `media/${id}_${kind}.mp4` : `/media/${id}/${kind}`,
  predict:(id) => STATIC ? `data/predict-${id}.json` : `/api/predict/${id}`
};

const fmtTime = (sec) => {
  sec = Math.max(0, Math.floor(sec || 0));
  return String(Math.floor(sec / 60)).padStart(2, '0') + ':' +
         String(sec % 60).padStart(2, '0');
};

const overallRisk = (d) => d.danger > 0 ? 'danger' : d.caution > 0 ? 'caution' : 'safe';
const icon = (n) => `<svg class="ico"><use href="#${n}"/></svg>`;

function status(msg, kind) {
  const el = $('#videoStatus');
  if (!msg) { el.hidden = true; return; }
  el.textContent = msg;
  el.className = 'video-status' + (kind ? ' is-' + kind : '');
  el.hidden = false;
}

/* ---------- 지점 목록 ---------- */
async function loadList() {
  const grid = $('#cardGrid');
  try {
    const json = await (await fetch(api.videos())).json();
    if (json.weights) {
      $('#footWeights').textContent = json.weights.split('/').slice(-3).join('/');
    }

    grid.innerHTML = '';
    let notReady = 0;

    json.videos.forEach(v => {
      const card = document.createElement('button');
      card.className = 'vcard';
      card.type = 'button';
      if (!v.ready) { card.disabled = true; notReady++; }

      const s = v.summary;
      card.innerHTML = `
        <div>
          <div class="vcard-place">${v.place}</div>
          <div class="vcard-name">${v.name}</div>
          <div class="vcard-desc">${v.desc}${v.duration ? ' · 총 ' + fmtTime(v.duration) : ''}</div>
        </div>
        ${s ? `<div class="vcard-stats">
          <div class="vc-stat"><b>${s.total_vehicles.toLocaleString()}</b><span>인식 차량</span></div>
          <div class="vc-stat"><b>${s.avg_speed}</b><span>평균 km/h</span></div>
          <div class="vc-stat ${s.danger > 0 ? 'is-danger' : ''}"><b>${s.danger.toLocaleString()}</b><span>위험 차량</span></div>
        </div>` : ''}
        ${v.ready
          ? `<div class="vcard-go"><span>관제 화면 열기</span>${icon('i-arrow-right')}</div>`
          : '<div class="vcard-wait">데이터 준비 필요</div>'}`;

      if (v.ready) card.addEventListener('click', () => openDetail(v.id));
      grid.appendChild(card);
    });

    $('#setupHint').hidden = notReady === 0;
    $('#codecHint').hidden = !json.videos.some(v => v.ready && !v.web_ready);
  } catch (e) {
    grid.innerHTML = '<div class="loading-box">목록을 불러오지 못했습니다. 서버 상태를 확인해 주세요.</div>';
  }
}

/* ---------- 관제 화면 ---------- */
async function openDetail(id) {
  const res = await fetch(api.video(id));
  if (!res.ok) {
    const j = await res.json().catch(() => ({}));
    alert(j.error || '데이터를 불러오지 못했습니다.');
    return;
  }
  state.data = await res.json();
  Object.assign(state, { view: 'yolo', lastSec: -1, filter: 'all', shown: 30 });

  $('#viewList').hidden = true;
  $('#viewDetail').hidden = false;
  $('#btnHome').hidden = false;
  $$('.chip').forEach((c, i) => c.classList.toggle('is-on', i === 0));
  window.scrollTo(0, 0);

  const d = state.data;
  $('#dtPlace').textContent = d.place;
  $('#dtTitle').textContent = d.name;
  $('#dtSub').textContent =
    `${d.desc} · 제한속도 ${d.speed_limit}km/h · ${d.fps}fps · 인식 모델 ${d.weights}`;
  $('#totTime').textContent = fmtTime(d.duration);
  $('#riskRule').innerHTML =
    `판정 기준 · 안전 ${d.thresholds.caution}km/h 미만 / 주의 ${d.thresholds.caution}–${d.thresholds.danger}km/h / ` +
    `위험 ${d.thresholds.danger}km/h 이상<br>` +
    `차량 판정에는 단일 최댓값이 아닌 지속 속도를 사용하며, ${d.thresholds.cap}km/h 초과 값은 측정 오류로 제외합니다.`;

  const bev = $$('.seg-btn').find(b => b.dataset.view === 'bev');
  bev.disabled = !d.has_bev;
  const twin = $$('.seg-btn').find(b => b.dataset.view === 'twin');
  twin.disabled = !d.has_twin;
  const twinSpot = $$('.seg-btn').find(b => b.dataset.view === 'twin_spot');
  twinSpot.hidden = !d.has_twin_spot;
  twinSpot.disabled = !d.has_twin_spot;

  state.events = d.events || { stopline: [], tailgate: [] };
  state.fired.clear();
  state.evTab = state.events.stopline.length || !state.events.tailgate.length
    ? 'stopline' : 'tailgate';
  $$('.ev-tab').forEach(b => b.classList.toggle('is-on', b.dataset.ev === state.evTab));
  renderEvents();

  state.predict = null;
  state.predictOn = false;
  setPredictBtn();
  $('#btnPredict').disabled = !(d.predict && d.predict.available);

  renderSummary();
  renderSignal();
  renderTable();
  drawStrip();
  setView('yolo', 0);
  updateLive(0);
}

function setView(view, atTime) {
  state.view = view;
  $$('.seg-btn').forEach(b => {
    const on = b.dataset.view === view;
    b.classList.toggle('is-on', on);
    b.setAttribute('aria-selected', on ? 'true' : 'false');
  });

  const p = $('#player');
  const keep = (atTime !== undefined) ? atTime : (p.currentTime || 0);
  const wasPlaying = !p.paused && !p.ended;

  p.classList.toggle('bev', view === 'bev' || view === 'twin' || view === 'twin_spot');
  status('');
  p.src = api.media(state.data.id, view);

  p.addEventListener('loadedmetadata', function once() {
    p.removeEventListener('loadedmetadata', once);
    if (keep > 0) { try { p.currentTime = keep; } catch (e) {} }
    if (wasPlaying) p.play().catch(() => {});
    drawOverlay();
  });
}

/* ---------- 신호 ---------- */
function renderSignal() {
  const box = $('#signalList');
  const cols = state.data.signal.columns;
  if (!cols.length) {
    box.innerHTML = '<div class="live-empty">신호 정보가 없습니다.</div>';
    return;
  }
  box.innerHTML = cols.map(c => `
    <div class="sig-row" data-key="${c.key}">
      <span class="sig-lamp off"></span>
      <span class="sig-name">${c.label}
        <i class="sig-kind">${c.kind === 'crosswalk' ? '보행 신호' : '차량 신호'}</i>
      </span>
      <span class="sig-state off">—</span>
    </div>`).join('');
}

function findInterval(sec) {
  const iv = state.data.signal.intervals;
  let lo = 0, hi = iv.length - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (sec < iv[mid].start) hi = mid - 1;
    else if (sec >= iv[mid].end) lo = mid + 1;
    else return iv[mid];
  }
  return null;
}

function updateSignal(sec) {
  const iv = findInterval(sec);
  const text = state.data.signal.state_text || {};
  $$('#signalList .sig-row').forEach(row => {
    const st = iv ? (iv.states[row.dataset.key] || 'UNKNOWN') : 'UNKNOWN';
    row.querySelector('.sig-lamp').className = 'sig-lamp ' +
      ({ GREEN: 'green', YELLOW: 'yellow', RED: 'red' }[st] || 'off');
    const se = row.querySelector('.sig-state');
    se.className = 'sig-state ' + st.toLowerCase();
    se.textContent = text[st] || st;
  });
  $('#signalNote').textContent = iv && iv.note ? iv.note : '해당 구간의 신호 설명이 없습니다.';
}

/* ---------- 통행 현황 · 위험도 ---------- */
function updateLive(sec) {
  const d = state.data;
  const tl = d.timeline[Math.min(sec, d.timeline.length - 1)] ||
             { count: 0, avg: 0, max: 0, safe: 0, caution: 0, danger: 0, vehicles: [] };

  $('#stCount').textContent = tl.count;
  $('#stAvg').textContent = tl.avg;
  $('#stMax').textContent = tl.max;

  $('#liveList').innerHTML = tl.vehicles.length
    ? tl.vehicles.map(v => `
      <div class="live-row ${v.risk}">
        <span class="live-bar"></span>
        <span class="live-id">${v.id}</span>
        <span class="live-tag ${v.risk}">${RISK_TAG[v.risk]}</span>
        <span class="live-speed">${v.speed}<small> km/h</small></span>
      </div>`).join('')
    : '<div class="live-empty">현재 통행 차량이 없습니다.</div>';

  const lvl = overallRisk(tl);
  const info = RISK_TEXT[lvl];
  const big = $('#riskBig');
  big.className = 'risk-state is-' + lvl;
  big.querySelector('.rs-word').textContent = info.word;
  big.querySelector('.rs-desc').textContent = info.desc;

  const badge = $('#dtBadge');
  badge.className = 'status-pill is-' + lvl;
  badge.querySelector('.pill-value').textContent = info.word;

  const total = Math.max(tl.count, 1);
  $('#barSafe').style.width = (tl.safe / total * 100) + '%';
  $('#barCaution').style.width = (tl.caution / total * 100) + '%';
  $('#barDanger').style.width = (tl.danger / total * 100) + '%';
  $('#numSafe').textContent = tl.safe;
  $('#numCaution').textContent = tl.caution;
  $('#numDanger').textContent = tl.danger;
}

/* ---------- 위반 감지 ---------- */
const EV_LABEL = { stopline: '정지선 위반', tailgate: '꼬리물기' };

function renderEvents() {
  const ev = state.events[state.evTab] || [];
  $('#cntStop').textContent = state.events.stopline.length;
  $('#cntTail').textContent = state.events.tailgate.length;

  const box = $('#eventList');
  if (!ev.length) {
    box.innerHTML = `<div class="live-empty">${EV_LABEL[state.evTab]} 감지 건이 없습니다.</div>`;
  } else {
    box.innerHTML = ev.map(e => `
      <button class="ev-row" data-sec="${Math.max(0, e.sec - 2)}">
        <span class="ev-time">${fmtTime(e.sec)}</span>
        <span class="ev-main">
          <b>${e.id}번 차량</b>
          <i>${state.evTab === 'stopline'
              ? `${e.lane}차선 · ${e.signal} ${e.state}`
              : `${e.direction} · 정체 ${e.slow}초`}</i>
        </span>
        <span class="ev-go">보기</span>
      </button>`).join('');
    $$('#eventList .ev-row').forEach(b => b.addEventListener('click', () => {
      const p = $('#player');
      try { p.currentTime = Number(b.dataset.sec); } catch (err) {}
      p.play().catch(() => {});
    }));
  }

  const d = state.data;
  $('#eventNote').textContent = state.evTab === 'stopline'
    ? '신호가 적색일 때 정지선을 넘어 일정 시간 이상 유지된 차량입니다.'
    : '교차로 영역 안에서 빠져나가지 못하고 정체한 차량입니다.';
}

function checkEventAlert(t) {
  const all = state.events.stopline.concat(state.events.tailgate);
  for (const e of all) {
    const key = e.kind + e.id + e.sec;
    if (state.fired.has(key)) continue;
    if (t >= e.sec && t < e.sec + 3) {
      state.fired.add(key);
      showAlert(e);
      break;
    }
  }
}

function showAlert(e) {
  const box = $('#eventAlert');
  box.className = 'event-alert is-' + e.kind;
  $('#eaTitle').textContent = `${EV_LABEL[e.kind]} — ${e.id}번 차량`;
  $('#eaDetail').textContent = e.kind === 'stopline'
    ? `${fmtTime(e.sec)} · ${e.lane}차선 · ${e.signal} ${e.state}`
    : `${fmtTime(e.sec)} · ${e.direction} · ${e.slow}초 정체`;
  box.hidden = false;
  if (navigator.vibrate) navigator.vibrate(80);
  clearTimeout(state.alertTimer);
  state.alertTimer = setTimeout(() => { box.hidden = true; }, 6000);
}

/* ---------- 이동경로 예측 ---------- */
function setPredictBtn() {
  const b = $('#btnPredict');
  b.setAttribute('aria-pressed', state.predictOn ? 'true' : 'false');
  b.classList.toggle('primary', state.predictOn);
  $('#btnPredictLabel').textContent = state.predictOn ? '예측 끄기' : '경로 예측';
}

async function togglePredict() {
  if (!state.predictOn && !state.predict) {
    try {
      state.predict = await (await fetch(api.predict(state.data.id))).json();
      state.predict.keys = Object.keys(state.predict.preds)
        .map(Number).sort((a, b) => a - b);
    } catch (e) {
      alert('예측 데이터를 불러오지 못했습니다.');
      return;
    }
  }
  state.predictOn = !state.predictOn;
  setPredictBtn();
  drawOverlay();
}

/* 예측 경로는 BEV 좌표계라 평면 변환·트윈 화면에서만 맞습니다. */
function overlayUsable() {
  return state.predictOn && state.predict && state.view !== 'yolo';
}

function drawOverlay() {
  const cv = $('#overlay');
  const p = $('#player');
  const ctx = cv.getContext('2d');

  const rect = p.getBoundingClientRect();
  const box = p.parentElement.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  cv.width = rect.width * dpr;
  cv.height = rect.height * dpr;
  cv.style.width = rect.width + 'px';
  cv.style.height = rect.height + 'px';
  cv.style.left = (rect.left - box.left) + 'px';
  cv.style.top = (rect.top - box.top) + 'px';
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, rect.width, rect.height);

  if (!overlayUsable() || !p.videoWidth) return;

  const sx = rect.width / p.videoWidth;
  const sy = rect.height / p.videoHeight;

  const fps = state.data.fps || 30;
  const frame = Math.round((p.currentTime || 0) * fps) + 1;
  const keys = state.predict.keys;
  let lo = 0, hi = keys.length - 1, best = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (keys[mid] <= frame) { best = mid; lo = mid + 1; } else { hi = mid - 1; }
  }
  if (best < 0) return;
  const key = keys[best];
  if (frame - key > state.predict.step * 2) return;

  const items = state.predict.preds[String(key)] || [];
  ctx.lineWidth = 2;
  ctx.setLineDash([5, 4]);
  ctx.strokeStyle = '#E86A1C';
  ctx.fillStyle = '#E86A1C';

  items.forEach(row => {
    const n = (row.length - 1) / 2;
    ctx.beginPath();
    for (let i = 0; i < n; i++) {
      const x = row[1 + i * 2] * sx, y = row[2 + i * 2] * sy;
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    ctx.stroke();
    const ex = row[1 + (n - 1) * 2] * sx, ey = row[2 + (n - 1) * 2] * sy;
    ctx.setLineDash([]);
    ctx.beginPath(); ctx.arc(ex, ey, 3.5, 0, 7); ctx.fill();
    ctx.setLineDash([5, 4]);
  });
  ctx.setLineDash([]);
}

/* ---------- 위험도 띠 ---------- */
function drawStrip() {
  const cv = $('#riskStrip');
  const tl = state.data.timeline;
  const w = cv.clientWidth || 800, h = 14;
  const dpr = window.devicePixelRatio || 1;
  cv.width = w * dpr; cv.height = h * dpr;
  const ctx = cv.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  const color = { safe: '#1E8A61', caution: '#C08312', danger: '#CE4A38', none: '#EDF2F7' };
  const bw = w / (tl.length || 1);
  tl.forEach((t, i) => {
    ctx.fillStyle = t.count > 0 ? color[overallRisk(t)] : color.none;
    ctx.fillRect(i * bw, 0, Math.max(bw, 1), h);
  });
}

/* ---------- 요약 · 표 ---------- */
function renderSummary() {
  const s = state.data.summary;
  $('#sumTotal').textContent = s.total_vehicles.toLocaleString();
  $('#sumJudged').textContent = s.judged.toLocaleString();
  $('#sumAvg').textContent = s.avg_speed;
  $('#sumCaution').textContent = s.caution.toLocaleString();
  $('#sumDanger').textContent = s.danger.toLocaleString();
}

function renderTable() {
  const order = { danger: 0, caution: 1, safe: 2, unknown: 3 };
  const all = state.data.vehicles;
  const arr = (state.filter === 'all' ? all.slice() : all.filter(v => v.risk === state.filter))
    .sort((a, b) => (order[a.risk] - order[b.risk]) || (b.stable - a.stable));
  const slice = arr.slice(0, state.shown);

  $('#vtBody').innerHTML = slice.map(v => `
    <tr>
      <td class="vt-id">${v.id}</td>
      <td class="vt-speed">${v.stable}</td>
      <td class="vt-dim">${v.max}</td>
      <td class="vt-dim">${v.seconds}초</td>
      <td class="vt-dim">${fmtTime(v.first)} – ${fmtTime(v.last)}</td>
      <td><span class="tag ${v.risk}">${RISK_TAG[v.risk]}</span></td>
      <td><button class="jump-btn" data-sec="${v.first}">해당 장면</button></td>
    </tr>`).join('') ||
    '<tr><td colspan="7" class="table-empty">해당하는 차량이 없습니다.</td></tr>';

  $('#tableCount').textContent =
    `${arr.length.toLocaleString()}대 중 ${slice.length.toLocaleString()}대 표시`;
  $('#btnMore').hidden = slice.length >= arr.length;

  $$('#vtBody .jump-btn').forEach(b => {
    b.addEventListener('click', () => {
      const p = $('#player');
      try { p.currentTime = Number(b.dataset.sec); } catch (e) {}
      p.play().catch(() => {});
      const stage = document.querySelector('.stage');
      if (stage) stage.scrollIntoView({ behavior: 'smooth', block: 'center' });
    });
  });
}

/* ---------- 이벤트 ---------- */
function bind() {
  const p = $('#player');

  $('#btnHome').addEventListener('click', () => {
    p.pause();
    p.removeAttribute('src');
    p.load();
    status('');
    $('#viewDetail').hidden = true;
    $('#viewList').hidden = false;
    $('#btnHome').hidden = true;
    window.scrollTo(0, 0);
  });

  $('#btnFont').addEventListener('click', (e) => {
    const on = document.body.classList.toggle('big');
    e.currentTarget.setAttribute('aria-pressed', on ? 'true' : 'false');
    $('#btnFontLabel').textContent = on ? '글씨 보통' : '글씨 크게';
    if (state.data) setTimeout(drawStrip, 60);
  });

  $$('.seg-btn').forEach(b =>
    b.addEventListener('click', () => { if (!b.disabled) setView(b.dataset.view); }));

  $('#btnBack').addEventListener('click', () => { p.currentTime = Math.max(0, p.currentTime - 10); });
  $('#btnFwd').addEventListener('click', () => { p.currentTime = Math.min(p.duration || 0, p.currentTime + 10); });

  p.addEventListener('error', () => {
    if (!p.getAttribute('src') || !p.error) return;
    const map = {
      2: '영상을 내려받지 못했습니다. app.py 가 켜져 있는지 확인해 주세요.',
      3: '영상을 해독하지 못했습니다. python transcode.py --force 로 다시 변환해 주세요.',
      4: '이 형식은 재생할 수 없습니다. python transcode.py 를 실행해 주세요.'
    };
    status((map[p.error.code] || '영상을 재생할 수 없습니다.') +
           `  (code ${p.error.code})`, 'error');
  });
  ['loadeddata', 'playing'].forEach(ev => p.addEventListener(ev, () => status('')));

  p.addEventListener('timeupdate', () => {
    const t = p.currentTime || 0;
    $('#curTime').textContent = fmtTime(t);
    const sec = Math.floor(t);
    if (sec !== state.lastSec && state.data) {
      state.lastSec = sec;
      updateSignal(t);
      updateLive(sec);
      checkEventAlert(t);
    }
    if (overlayUsable()) drawOverlay();
  });

  $('#riskStrip').addEventListener('click', (e) => {
    if (!state.data) return;
    const r = e.currentTarget.getBoundingClientRect();
    p.currentTime = Math.max(0, state.data.duration * ((e.clientX - r.left) / r.width));
    p.play().catch(() => {});
  });

  $$('.chip').forEach(b => b.addEventListener('click', () => {
    $$('.chip').forEach(x => x.classList.remove('is-on'));
    b.classList.add('is-on');
    state.filter = b.dataset.filter;
    state.shown = 30;
    renderTable();
  }));

  $('#btnMore').addEventListener('click', () => { state.shown += 50; renderTable(); });

  $$('.ev-tab').forEach(b => b.addEventListener('click', () => {
    $$('.ev-tab').forEach(x => x.classList.remove('is-on'));
    b.classList.add('is-on');
    state.evTab = b.dataset.ev;
    renderEvents();
  }));

  $('#btnPredict').addEventListener('click', togglePredict);
  ['loadedmetadata', 'seeked', 'play'].forEach(ev =>
    p.addEventListener(ev, () => { if (overlayUsable()) drawOverlay(); }));

  window.addEventListener('resize', () => {
    if (state.data) drawStrip();
    drawOverlay();
  });

  document.addEventListener('keydown', (e) => {
    if ($('#viewDetail').hidden || e.target.tagName === 'INPUT') return;
    if (e.code === 'ArrowLeft') $('#btnBack').click();
    if (e.code === 'ArrowRight') $('#btnFwd').click();
  });
}


/* ==========================================================
   현장 모드 - GPS 로 가까운 CCTV 를 자동으로 엽니다
   ========================================================== */

const field = {
  on: false,
  watchId: null,
  places: [],
  radius: 150,
  currentPlace: null,
  lastFix: null,
  denied: false
};

/* 두 좌표 사이 거리(m). 하버사인 공식. */
function distanceM(lat1, lon1, lat2, lon2) {
  const R = 6371008.8, rad = Math.PI / 180;
  const p1 = lat1 * rad, p2 = lat2 * rad;
  const dp = (lat2 - lat1) * rad, dl = (lon2 - lon1) * rad;
  const a = Math.sin(dp / 2) ** 2 +
            Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(a)));
}

const fmtDist = (m) =>
  m < 1000 ? Math.round(m) + 'm' : (m / 1000).toFixed(m < 10000 ? 1 : 0) + 'km';

const PLACE_STORE = 'gwanje.places';

function readLocalPlaces() {
  try { return JSON.parse(localStorage.getItem(PLACE_STORE) || '{}'); }
  catch (e) { return {}; }
}

function writeLocalPlace(id, lat, lon, radius) {
  const all = readLocalPlaces();
  all[id] = { lat, lon, radius_m: radius };
  try { localStorage.setItem(PLACE_STORE, JSON.stringify(all)); } catch (e) {}
}

async function loadPlaces() {
  try {
    const j = await (await fetch(api.places())).json();
    field.places = j.places || [];
    if (STATIC) {
      const saved = readLocalPlaces();
      field.places.forEach(p => {
        const v = saved[p.id];
        if (v) {
          p.lat = v.lat; p.lon = v.lon;
          if (v.radius_m) p.radius_m = v.radius_m;
          p.source = 'saved';
        }
      });
    }
    if (field.places.length) field.radius = field.places[0].radius_m || 150;
    $('#radiusInput').value = field.radius;
    renderPlaces();
  } catch (e) {
    field.places = [];
  }
}

function renderPlaces() {
  const box = $('#placeList');
  if (!field.places.length) {
    box.innerHTML = '<p class="place-hint">등록된 장소가 없습니다.</p>';
    return;
  }
  const mark = { measured: '실측값', saved: '직접 설정함', approx: '대략값 · 보정 권장' };
  box.innerHTML = field.places.map(p => `
    <div class="place-row" data-place="${p.id}">
      <div class="place-info">
        <b>${p.name}</b>
        <span class="place-coord">${p.lat.toFixed(6)}, ${p.lon.toFixed(6)}</span>
        <span class="place-src ${p.source}">${mark[p.source] || p.source}</span>
      </div>
      <div class="place-side">
        <span class="place-dist" data-dist="${p.id}">—</span>
        <button class="place-set" data-set="${p.id}">이 자리로 지정</button>
      </div>
    </div>`).join('');

  $$('#placeList .place-set').forEach(b =>
    b.addEventListener('click', () => setPlaceHere(b.dataset.set, b)));
}

function setPlaceHere(placeId, btn) {
  if (!navigator.geolocation) {
    alert('이 브라우저에서는 위치를 쓸 수 없습니다.');
    return;
  }
  const label = btn.textContent;
  btn.disabled = true;
  btn.textContent = '위치 확인 중…';

  navigator.geolocation.getCurrentPosition(async (pos) => {
    const { latitude, longitude, accuracy } = pos.coords;
    const radius = Number($('#radiusInput').value) || field.radius;
    try {
      let name = placeId;
      if (STATIC) {
        writeLocalPlace(placeId, latitude, longitude, radius);
        const hit = field.places.find(p => p.id === placeId);
        name = hit ? hit.name : placeId;
      } else {
        const res = await fetch('/api/places/' + placeId, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ lat: latitude, lon: longitude, radius_m: radius })
        });
        const j = await res.json();
        if (!res.ok) throw new Error(j.error || '저장 실패');
        name = j.place.name;
      }
      btn.textContent = '저장됨';
      setTimeout(() => { btn.textContent = label; btn.disabled = false; }, 1600);
      await loadPlaces();
      alert(`${name} 위치를 저장했습니다.\n` +
            `${latitude.toFixed(6)}, ${longitude.toFixed(6)} (오차 약 ${Math.round(accuracy)}m)` +
            (STATIC ? '\n\n이 기기에만 저장됩니다.' : ''));
    } catch (e) {
      btn.textContent = label;
      btn.disabled = false;
      alert('저장하지 못했습니다: ' + e.message);
    }
  }, (err) => {
    btn.textContent = label;
    btn.disabled = false;
    alert(geoErrorText(err));
  }, { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 });
}

function geoErrorText(err) {
  if (err.code === 1) {
    return location.protocol === 'https:' || location.hostname === 'localhost'
      ? '위치 권한이 거부되었습니다. 브라우저 설정에서 이 사이트의 위치 접근을 허용해 주세요.'
      : '위치를 쓰려면 HTTPS 로 접속해야 합니다. 터미널에서 python 한번에확인.py 로 실행해 주세요.';
  }
  if (err.code === 2) return '위치를 찾지 못했습니다. 실외에서 다시 시도해 주세요.';
  if (err.code === 3) return '위치 확인이 오래 걸립니다. 잠시 후 다시 시도해 주세요.';
  return '위치를 쓸 수 없습니다.';
}

function fieldStatus(title, detail, kind) {
  $('#fbTitle').textContent = title;
  $('#fbDetail').textContent = detail || '';
  $('#fieldBar').className = 'field-bar' + (kind ? ' is-' + kind : '');
}

function startField() {
  if (!navigator.geolocation) {
    alert('이 브라우저에서는 위치를 쓸 수 없습니다.');
    return;
  }
  if (location.protocol !== 'https:' && location.hostname !== 'localhost'
      && location.hostname !== '127.0.0.1') {
    alert('휴대폰에서 위치를 쓰려면 HTTPS 접속이 필요합니다.\n' +
          '터미널에서  python 한번에확인.py  로 실행한 뒤,\n' +
          '화면에 표시되는 https:// 주소로 접속해 주세요.');
    return;
  }

  field.on = true;
  field.currentPlace = null;
  $('#btnField').setAttribute('aria-pressed', 'true');
  $('#btnFieldLabel').textContent = '현장 모드 끄기';
  $('#fieldBar').hidden = false;
  fieldStatus('위치를 확인하는 중입니다', '잠시만 기다려 주세요', 'wait');

  field.watchId = navigator.geolocation.watchPosition(
    onPosition,
    (err) => {
      field.denied = err.code === 1;
      fieldStatus('위치를 쓸 수 없습니다', geoErrorText(err), 'error');
    },
    { enableHighAccuracy: true, timeout: 20000, maximumAge: 5000 }
  );
}

function stopField() {
  field.on = false;
  if (field.watchId !== null) navigator.geolocation.clearWatch(field.watchId);
  field.watchId = null;
  field.currentPlace = null;
  $('#btnField').setAttribute('aria-pressed', 'false');
  $('#btnFieldLabel').textContent = '현장 모드';
  $('#fieldBar').hidden = true;
  $('#arrivedBar').hidden = true;
  $$('#placeList .place-dist').forEach(el => { el.textContent = '—'; });
}

function onPosition(pos) {
  const { latitude, longitude, accuracy } = pos.coords;
  field.lastFix = { lat: latitude, lon: longitude, acc: accuracy };

  const ranked = field.places
    .map(p => ({ p, d: distanceM(latitude, longitude, p.lat, p.lon) }))
    .sort((a, b) => a.d - b.d);

  ranked.forEach(({ p, d }) => {
    const el = document.querySelector(`[data-dist="${p.id}"]`);
    if (el) el.textContent = fmtDist(d);
  });

  if (!ranked.length) {
    fieldStatus('등록된 장소가 없습니다', '위치 설정에서 지점을 지정해 주세요', 'error');
    return;
  }

  const best = ranked[0];
  const radius = best.p.radius_m || field.radius;
  const inside = best.d <= radius;

  if (inside) {
    fieldStatus(`${best.p.short} 도착`,
      `${fmtDist(best.d)} 이내 · 위치 오차 약 ${Math.round(accuracy)}m`, 'here');
    if (field.currentPlace !== best.p.id) {
      field.currentPlace = best.p.id;
      arriveAt(best.p);
    }
  } else {
    fieldStatus(`가장 가까운 곳은 ${best.p.short}`,
      `${fmtDist(best.d)} 떨어져 있습니다 · ${radius}m 안으로 들어오면 자동으로 열립니다`, 'far');
    if (field.currentPlace) {
      field.currentPlace = null;
      $('#arrivedBar').hidden = true;
    }
  }
}

/* 반경 안에 들어왔을 때 해당 지점 영상을 엽니다. */
function arriveAt(place) {
  const ids = place.videos || [];
  if (!ids.length) return;

  const already = state.data && ids.includes(state.data.id);
  if (!already) openDetail(ids[0]);

  const bar = $('#arrivedBar');
  $('#arrivedText').textContent = `${place.name} 현장입니다`;
  $('#arrivedSwitch').innerHTML = ids.length > 1
    ? '<span class="as-lab">다른 영상</span>' + ids.map(id =>
        `<button class="as-btn" data-go="${id}">${id.replace(/[^0-9]/g, '') || id}</button>`).join('')
    : '';
  bar.hidden = false;

  $$('#arrivedSwitch .as-btn').forEach(b =>
    b.addEventListener('click', () => openDetail(b.dataset.go)));

  if (navigator.vibrate) navigator.vibrate([60, 40, 60]);
}

/* ---------- 웹앱 등록 ---------- */
function registerApp() {
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register(STATIC ? './sw.js' : '/sw.js',
                                     { scope: './' })
      .catch(() => {});
  }
}

function bindField() {
  $('#btnField').addEventListener('click', () => field.on ? stopField() : startField());
  $('#fbStop').addEventListener('click', stopField);
  $('#fbSettings').addEventListener('click', () => {
    const panel = $('#placePanel');
    panel.hidden = !panel.hidden;
    if (!panel.hidden) panel.scrollIntoView({ behavior: 'smooth', block: 'center' });
  });
  $('#radiusInput').addEventListener('change', (e) => {
    const v = Math.min(2000, Math.max(20, Number(e.target.value) || 150));
    e.target.value = v;
    field.radius = v;
    field.places.forEach(p => { p.radius_m = v; });
  });
  loadPlaces();
  registerApp();
}

bind();
bindField();
loadList();
