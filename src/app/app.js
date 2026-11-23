/* 안산 밤길 — 시민용 웹 지도 앱 (3안 수정사항 #24)
   자료: data.js — src/build_app.py 가 만든다(임의값 판 data/proto + 공개 자료. 민간 실데이터 없음).
   경로: night_core.NightGraph.frontier · choose 를 그대로 옮겼다 — α 격자마다 Dijkstra 한 번,
         우회 예산 안에서 '사람 드문 구간'이 가장 짧은 길(같으면 최장 연속 → 거리).
   표현(3안 CLAUDE.md 0절): '사람이 다니는 길 · 문 연 가게'로만 말한다. 범죄 여부는 알려 주지 않는다. */
"use strict";
(function () {
const D = window.APP_DATA, M = D.meta;
const $ = id => document.getElementById(id);
const esc = s => String(s == null ? "" : s).replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
const KEY_VW = "ansan_night_map_vworld_key";      // 밤길지도(#21 · #22)와 같은 이름 — 같은 주소라 키를 한 번만 넣는다
const KEY_BADGE = "ansan_night_app_badges", KEY_BASE = "ansan_night_app_base";
const KEY_OB = "ansan_night_app_onboarded", KEY_HOME = "ansan_night_app_home";   // 첫 실행 안내 본 적 · 우리 집(#31, 이 휴대폰에만)
const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* 저장 못 하면 이번 화면에서만 */ } },
  raw(k) { try { return localStorage.getItem(k) || ""; } catch (e) { return ""; } },
  put(k, v) { try { if (v) localStorage.setItem(k, v); else localStorage.removeItem(k); } catch (e) { /* 무시 */ } },
};
const km = m => m >= 1000 ? (m / 1000).toFixed(1) + "km" : Math.round(m / 10) * 10 + "m";
const darkTxt = m => m < 5 ? "없음" : km(m);
const walkMin = m => Math.max(1, Math.round(m / M.walk_mps / 60));
const runMin = m => Math.max(1, Math.round(m / 1000 * M.run_pace));
const mmss = s => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
const paceTxt = () => { const a = Math.floor(M.run_pace), b = Math.round((M.run_pace - a) * 60); return b ? `${a}분 ${b}초` : `${a}분`; };
let toastT = 0;
function toast(msg, ms) { const t = $("toast"); t.textContent = msg; t.classList.add("on"); clearTimeout(toastT); toastT = setTimeout(() => t.classList.remove("on"), ms || 2600); }
function dist(a, b) { const c = Math.cos((a[0] + b[0]) / 360 * Math.PI), dy = (a[0] - b[0]) * 111320, dx = (a[1] - b[1]) * 111320 * c; return Math.sqrt(dx * dx + dy * dy); }

/* ── 1. 자료 풀기 · 보행망(CSR) ─────────────────────────────── */
function dec(s, T) { const bin = atob(s), b = new Uint8Array(bin.length); for (let i = 0; i < bin.length; i++) b[i] = bin.charCodeAt(i); return new T(b.buffer); }
const N = M.n, E = M.m;
const LAT = dec(D.lat, Int32Array), LNG = dec(D.lng, Int32Array), GIANT = dec(D.giant, Uint8Array);
const U = dec(D.u, Int32Array), V = dec(D.v, Int32Array), LEN = dec(D.len, Float32Array);
/* 활성도는 등급만(#38) — (시간대 × 간선) 0 사람 드묾 · 1 보통 · 2 사람 많음을 한 바이트에 넷씩(2비트) 묶어 싣는다. 행 = 시간대.
   길 찾기 비용은 등급 대표값(그 등급 길들의 길이 가중 평균 활성도, M.act_levels)으로 — 드묾 · 많음 경계는 임계 그대로라 판정이 바뀌지 않는다 */
function unpack2(p, n) { const out = new Uint8Array(n); for (let i = 0; i < n; i++) out[i] = (p[i >> 2] >> ((i & 3) << 1)) & 3; return out; }
const ACTC = unpack2(dec(D.act2, Uint8Array), M.slots.length * M.m);
const DK = M.act_levels.map(v => 1 - v);              // 등급별 어두움 = 1 − 대표값(NightGraph.frontier 의 1 − act)
const ROAD = dec(D.road, Uint8Array);                 // 길 종류 0 차 없는 길 · 1 차가 같이 다니는 골목 · 2 큰 찻길 · 3 차도 옆 보도(#26)
const TRAIL = D.trail ? dec(D.trail, Uint8Array) : new Uint8Array(M.m);       // 산길 · 오솔길 · 농로(밤 기준)
const ACCE = D.acc_edge ? dec(D.acc_edge, Uint8Array) : new Uint8Array(M.m);  // 보행 사고가 잦았던 곳 번호(1부터, 0 = 없음)
const ACC = D.acc || [];
const ll = i => [LAT[i] / 1e6, LNG[i] / 1e6];
const START = new Int32Array(N + 1);
for (let e = 0; e < E; e++) { START[U[e] + 1]++; START[V[e] + 1]++; }
for (let i = 0; i < N; i++) START[i + 1] += START[i];
const NB = new Int32Array(2 * E), NE = new Int32Array(2 * E);
(function () { const p = START.slice(0, N); for (let e = 0; e < E; e++) { NB[p[U[e]]] = V[e]; NE[p[U[e]]++] = e; NB[p[V[e]]] = U[e]; NE[p[V[e]]++] = e; } })();

/* ── 2. 경로 — night_core.NightGraph 와 같은 규칙 ─────────────── */
function Heap() { this.k = []; this.v = []; this.topk = 0; }
Heap.prototype.push = function (k, v) {
  const K = this.k, X = this.v; let i = K.length; K.push(k); X.push(v);
  while (i > 0) { const p = (i - 1) >> 1; if (K[p] <= k) break; K[i] = K[p]; X[i] = X[p]; i = p; }
  K[i] = k; X[i] = v;
};
Heap.prototype.pop = function () {
  const K = this.k, X = this.v, tk = K[0], tv = X[0], lk = K.pop(), lv = X.pop(), n = K.length;
  if (n) {
    let i = 0;
    for (;;) {
      const l = 2 * i + 1, r = l + 1; let m = i, mk = lk;
      if (l < n && K[l] < mk) { m = l; mk = K[l]; }
      if (r < n && K[r] < mk) { m = r; }
      if (m === i) break;
      K[i] = K[m]; X[i] = X[m]; i = m;
    }
    K[i] = lk; X[i] = lv;
  }
  this.topk = tk; return tv;
};
const DIST = new Float64Array(N), PN = new Int32Array(N), PE = new Int32Array(N), DONE = new Uint8Array(N);
function dijkstra(s, t, w, limit) {
  if (s === t) return {nodes: [s], edges: []};
  DIST.fill(Infinity); PN.fill(-1); DONE.fill(0);
  const H = new Heap(); DIST[s] = 0; H.push(0, s);
  while (H.k.length) {
    const x = H.pop(), d = H.topk;
    if (DONE[x]) continue;
    DONE[x] = 1;
    if (x === t || d > limit) break;
    for (let j = START[x], j1 = START[x + 1]; j < j1; j++) {
      const y = NB[j]; if (DONE[y]) continue;
      const nd = d + w[NE[j]];
      if (nd < DIST[y]) { DIST[y] = nd; PN[y] = x; PE[y] = NE[j]; H.push(nd, y); }
    }
  }
  if (!DONE[t] || PN[t] < 0) return null;
  const nodes = [t], edges = [];
  while (nodes[nodes.length - 1] !== s) { const y = nodes[nodes.length - 1]; edges.push(PE[y]); nodes.push(PN[y]); }
  return {nodes: nodes.reverse(), edges: edges.reverse()};
}
function stats(edges, slot) {           // NightGraph.stats — 길이 · 사람 드문 구간 · 최장 연속
  const o = slot * E; let L = 0, dk = 0, run = 0, worst = 0;
  for (const e of edges) { const l = LEN[e]; L += l; if (ACTC[o + e] === 0) { dk += l; run += l; if (run > worst) worst = run; } else run = 0; }
  return {len: L, dark: dk, worst};
}
function frontier(s, t, slot) {         // NightGraph.frontier — α 격자마다 길 하나, 같은 길은 한 번만. [0] = 최단경로
  const w = new Float64Array(E); for (let e = 0; e < E; e++) w[e] = LEN[e];
  const base = dijkstra(s, t, w, Infinity);
  if (!base) return [];
  const out = [], seen = new Set(), o = slot * E;
  const add = (a, p) => { const k = p.edges.join(","); if (seen.has(k)) return; seen.add(k); out.push(Object.assign({alpha: a}, p, stats(p.edges, slot))); };
  add(0, base);
  for (const a of M.alpha_grid) {
    if (a === 0) continue;
    for (let e = 0; e < E; e++) w[e] = LEN[e] * (1 + a * DK[ACTC[o + e]]);
    let lim = 0; for (const e of base.edges) lim += w[e];
    const p = dijkstra(s, t, w, lim * (1 + 1e-9) + 1e-6);     // 최단경로의 α 비용이 상한
    if (p) add(a, p);
  }
  out.sort((x, y) => (x.len - y.len) || (x.dark - y.dark));
  return out;
}
function choose(front, detour) {        // NightGraph.choose — 예산 안에서 (사람 드문 구간, 최장 연속, 거리) 순
  if (!front.length) return null;
  const budget = front[0].len * (1 + detour) + 1e-6; let best = null;
  for (const r of front) {
    if (r.len > budget) continue;
    if (!best || r.dark < best.dark || (r.dark === best.dark && (r.worst < best.worst || (r.worst === best.worst && r.len < best.len)))) best = r;
  }
  return best;
}
function snap(la, ln) {                 // 가장 가까운 보행망 지점(가장 큰 연결요소 안에서만)
  const c = Math.cos(la * Math.PI / 180), a6 = la * 1e6, b6 = ln * 1e6; let bi = -1, bd = Infinity;
  for (let i = 0; i < N; i++) { if (!GIANT[i]) continue; const dy = LAT[i] - a6, dx = (LNG[i] - b6) * c, d = dx * dx + dy * dy; if (d < bd) { bd = d; bi = i; } }
  return {i: bi, m: Math.sqrt(bd) / 1e6 * 111320};
}

/* ── 3. 시간대 ── (시연 앱 proto_ui.when 과 같은 표기: 새벽 1시는 다음 날 이름) */
const DOWS = "월화수목금토일", HOURS = M.hours;
const HOUR_TXT = {22: "밤 10시", 23: "밤 11시", 0: "밤 12시", 1: "새벽 1시"};
const slotOf = (night, h) => night * HOURS.length + HOURS.indexOf(h);
function when(s) { const [night, h] = M.slots[s]; return h === 1 ? `${DOWS[(night + 1) % 7]}요일 새벽 1시` : `${DOWS[night]}요일 ${HOUR_TXT[h]}`; }
function nowSlot() {
  const d = new Date(), wd = (d.getDay() + 6) % 7, h = d.getHours();
  if (h === 22 || h === 23) return slotOf(wd, h);
  if (h === 0 || h === 1) return slotOf((wd + 6) % 7, h);
  return slotOf(wd, 23);
}

/* ── 4. 지도 · 바탕 ─────────────────────────────────────────── */
const map = L.map("map", {zoomControl: false, preferCanvas: true, minZoom: 11, maxZoom: 19}).setView([37.3155, 126.8336], 13);
const osm = cls => L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png",
  {maxZoom: 19, className: cls || "", attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'});
const VKEY = store.raw(KEY_VW) || M.vworld_key || "";  // 이 브라우저에 넣은 키 → 앱에 넣어 둔 키(#41, 사용자 결정) → 없으면 OSM
const vw = layer => L.tileLayer(`https://api.vworld.kr/req/wmts/1.0.0/${encodeURIComponent(VKEY)}/${layer}/{z}/{y}/{x}.png`,
  {maxZoom: 19, attribution: '&copy; <a href="https://www.vworld.kr">브이월드</a>(국토교통부)'});
const BASES = VKEY ? [{t: "일반", l: vw("Base"), vw: 1}, {t: "야간", l: vw("midnight"), vw: 1}, {t: "OSM", l: osm()}, {t: "OSM 어둡게", l: osm("dark-tiles")}]
                   : [{t: "일반", l: osm()}, {t: "어둡게", l: osm("dark-tiles")}];
let baseI = 0;
function setBase(i) { BASES.forEach((b, k) => { if (k === i) b.l.addTo(map); else map.removeLayer(b.l); }); baseI = i; $("baseLabel").textContent = BASES[i].t; store.set(KEY_BASE, i); }
function note(msg) { const n = $("baseNote"); n.textContent = msg; n.style.display = "block"; setTimeout(() => { n.style.display = "none"; }, 7000); }
function dropBase(b) {                  // 키가 틀리면 브이월드는 그림 대신 XML 을 보낸다 → 그 바탕을 빼고 다음 것으로
  const i = BASES.indexOf(b); if (i < 0) return;
  const shown = map.hasLayer(b.l); map.removeLayer(b.l); BASES.splice(i, 1);
  if (shown) setBase(0); else if (baseI > i) baseI--;
  if (!BASES.some(x => x.vw)) note("브이월드 지도를 못 불러왔습니다(인증키 · 서비스 URL 확인) · OpenStreetMap 바탕");
}
BASES.filter(b => b.vw).forEach(b => { let ok = 0, bad = 0; b.l.on("tileload", () => ok++); b.l.on("tileerror", () => { if (++bad >= 4 && !ok) dropBase(b); }); });
{ const b = store.get(KEY_BASE, null);                // 처음 여는 사람 — 브이월드가 있으면 해 진 뒤엔 야간 지도(#41)
  setBase(Number.isInteger(b) && b >= 0 && b < BASES.length ? b : (BASES[1] && BASES[1].vw && isNight() ? 1 : 0)); }
$("baseBtn").onclick = () => setBase((baseI + 1) % BASES.length);

const LY = {walk: L.layerGroup().addTo(map), run: L.layerGroup(), me: L.layerGroup().addTo(map), shops: L.layerGroup().addTo(map)};
const pin = (txt, cls) => L.divIcon({className: "pinwrap", html: `<span class="mk ${cls || ""}">${esc(txt)}</span>`, iconSize: [0, 0]});
const REAL = !!M.real;                                // 실데이터 판(#32) — real_app 에만. 공개 판은 가상 데이터
function monthsTxt() { const m = M.months || []; if (!m.length) return ""; const f = s => `${s.slice(0, 4)}년 ${+s.slice(4)}월`; return m.length > 1 ? `${f(m[0])}~${+m[m.length - 1].slice(4)}월` : f(m[0]); }
const SHOP_T = M.hours_known ? "문 연 가게" : "심야 업종 가게";     // 실데이터 판은 카드 블록 위치가 없어 영업 여부를 모른다
const SHOP_NOTE = M.hours_known ? "영업 여부는 가상 데이터" : "밤에 여는 업종 — 영업 여부는 확인하지 못했어요";
const SHOP_SVG = '<svg viewBox="0 0 24 24" width="12" height="12" aria-hidden="true"><path d="M3 9h18l-2-5H5zM5 10v10h14V10M10 20v-5h4v5" fill="none" stroke="#fff" stroke-width="2.4" stroke-linejoin="round"/></svg>';
const poiIcon = (html, cls) => L.divIcon({className: "pinwrap", html: `<div class="poi ${cls}">${html}</div>`, iconSize: [0, 0]});
const meIcon = () => L.divIcon({className: "pinwrap", html: '<div class="me"></div>', iconSize: [0, 0]});
/* 보행 사고가 잦았던 곳(#26) — 도로교통공단 사고다발지역(공개). 사고가 많이 났던 곳이라는 사실만 알린다(경로 계산에는 안 씀) */
const ACC_TXT = "어르신 · 어린이 보행 사고가 잦았던 곳";
const ACC_KIND = {"보행노인": "어르신 보행", "보행어린이": "어린이 보행", "스쿨존어린이": "스쿨존 어린이"};
function accOn(edges) { const s = new Set(); for (const e of edges) if (ACCE[e]) s.add(ACCE[e] - 1); return [...s]; }
function accDraw(ids, layer) {
  ids.forEach(k => {
    const a = ACC[k]; if (!a) return;
    if (a.ring) L.polygon(a.ring, {color: "#d93025", weight: 1.5, opacity: .85, fillColor: "#d93025", fillOpacity: .1, interactive: false}).addTo(layer);
    L.marker([a.lat, a.lng], {icon: poiIcon("!", "acc")}).bindPopup(`<b>${ACC_TXT}</b><br>${esc(a.name)}<div class="note">${
      esc(a.types.map(t => ACC_KIND[t] || t).join(" · "))} · ${a.years.join(" · ")}년 · 도로교통공단 사고다발지역 — 사고가 많이 났던 곳이에요(지금은 달라졌을 수 있어요)</div>`).addTo(layer);
  });
}
const accLine = n => n ? `<div class="mut acc">⚠️ ${ACC_TXT} ${n}곳을 지나요</div>` : "";
function fitTo(pts) {
  if (!pts || !pts.length) return;
  const b = L.latLngBounds(pts);
  if (innerWidth >= 900) map.fitBounds(b, {paddingTopLeft: [430, 50], paddingBottomRight: [90, 50], maxZoom: 17});
  else map.fitBounds(b, {paddingTopLeft: [24, 120], paddingBottomRight: [70, $("sheet").offsetHeight + 24], maxZoom: 17});
}
function locate(cb, fail) {             // fail — 위치를 못 받으면(권한 · 실내 · PC) 할 일. 없으면 안내만
  if (!navigator.geolocation) { if (fail) fail(); else toast("이 브라우저는 위치를 쓸 수 없어요"); return; }
  navigator.geolocation.getCurrentPosition(p => { const q = [p.coords.latitude, p.coords.longitude]; LY.me.clearLayers(); L.marker(q, {icon: meIcon(), interactive: false}).addTo(LY.me); if (cb) cb(q); },
    () => { if (fail) fail(); else toast("위치를 받지 못했어요 · 브라우저 위치 권한을 확인하세요"); }, {enableHighAccuracy: true, timeout: 10000, maximumAge: 30000});
}
$("locBtn").onclick = () => locate(q => map.setView(q, Math.max(map.getZoom(), 16)));

/* ── 5. 밤길 ───────────────────────────────────────────────── */
const S = {mode: "walk"};
const W = {s: null, e: null, slot: nowSlot(), detour: M.detour, front: null, base: null, best: null, busy: false, nShops: 0, nCops: 0,
           opt: "rec", routes: null};                  // opt — 고른 길 카드(rec · fast · people, #28)
const GRADE = {0: ["#c4c7cc", "자료 부족"], 1: ["#9aa0a6", "사람 드묾"], 2: ["#8ab4f8", "보통"], 3: ["#1a73e8", "사람 많음"]};
// 화면 등급 = 길 찾기에 쓰는 등급 그대로(#38). 실데이터 판 가린 칸도 이웃에서 빌린 값이라(#34) 0 '자료 부족'은 없다
const gradeOf = (e, s) => ACTC[s * E + e] + 1;
function darkDisp(edges, s) { let d = 0; for (const e of edges) if (gradeOf(e, s) === 1) d += LEN[e]; return d; }   // 보이는 '사람 드문 구간'(가린 곳 빼고)
function placeName(i) {
  const p = ll(i); let best = null, bd = Infinity;
  for (const q of D.places) { if (q.k === "동") continue; const d = dist(p, [q.lat, q.lng]); if (d < bd) { bd = d; best = q; } }
  if (best && bd < 400) return `${best.t} 근처`;
  best = null; bd = Infinity;
  for (const q of D.places) { if (q.k !== "동") continue; const d = dist(p, [q.lat, q.lng]); if (d < bd) { bd = d; best = q; } }
  return best ? `${best.t} 일대` : "지도에서 고른 곳";
}
function poisAlong(nodes) {             // 그 시각에 문 연 가게(가상) · 밤에 문 여는 지구대
  const out = [], r = M.anchor_r_m, step = Math.max(1, Math.floor(nodes.length / 250)), samp = [];
  for (let k = 0; k < nodes.length; k += step) samp.push(ll(nodes[k]));
  samp.push(ll(nodes[nodes.length - 1]));
  const near = (p, rr) => samp.some(q => Math.abs(q[0] - p[0]) < 0.004 && dist(q, p) <= rr);
  const open = D.shops.filter(s => ((s[3] >> W.slot) & 1) && near(s, r));
  const every = Math.max(1, Math.ceil(open.length / 10));          // 표시는 10개 안팎으로 고르게 — 개수는 전부 센다
  open.forEach((s, k) => {
    if (k % every) return;
    out.push(L.marker([s[0], s[1]], {icon: poiIcon(SHOP_SVG, "shop")})
      .bindPopup(`<b>${SHOP_T}</b><br>${s[2].length ? s[2].map(esc).join("<br>") : "심야 업종 가게"}<div class="note">${esc(when(W.slot))} 기준 · ${SHOP_NOTE}</div>`));
  });
  const cops = D.police.filter(p => near(p, r * 2));
  cops.forEach(p => out.push(L.marker([p[0], p[1]], {icon: poiIcon("경", "cop")}).bindPopup(`<b>${esc(p[2])}</b><br>${esc(p[3])} · 밤에도 문을 엽니다`)));
  W.nShops = open.length; W.nCops = cops.length;
  return out;
}
function drawWalk(fit) {
  LY.walk.clearLayers();
  if (W.best && W.base) {
    const others = new Set(Object.values(W.routes || {}).filter(r => r && r !== W.best));   // 고르지 않은 길은 회색 점선
    others.forEach(r => L.polyline(r.nodes.map(ll), {color: "#5f6368", weight: 4, opacity: .5, dashArray: "6 8", interactive: false}).addTo(LY.walk));
    const pts = W.best.nodes.map(ll);
    L.polyline(pts, {color: "#fff", weight: 11, opacity: .95, interactive: false}).addTo(LY.walk);
    let g0 = null, seg = [];
    const flush = () => { if (seg.length > 1) L.polyline(seg, {color: GRADE[g0][0], weight: 7, opacity: .96, interactive: false}).addTo(LY.walk); };
    W.best.edges.forEach((e, k) => {
      const g = gradeOf(e, W.slot);
      if (g !== g0 && seg.length) { flush(); seg = [seg[seg.length - 1]]; }
      if (!seg.length) seg.push(pts[k]);
      seg.push(pts[k + 1]); g0 = g;
    });
    flush();
    poisAlong(W.best.nodes).forEach(m => m.addTo(LY.walk));
    accDraw(accOn(W.best.edges), LY.walk);
  }
  if (W.s != null) L.marker(ll(W.s), {icon: pin("출발"), interactive: false}).addTo(LY.walk);
  if (W.e != null) L.marker(ll(W.e), {icon: pin("도착", "e"), interactive: false}).addTo(LY.walk);
  if (fit && W.best) fitTo([...new Set(Object.values(W.routes || {}).filter(Boolean))].flatMap(r => r.nodes.map(ll)));
}
/* 길 고르기(#28 · APP_ROUTE_OPTIONS) — '얼마나 더 걸어도 돼요?' % 대신 카드 세 개. 같은 우회 예산 규칙(choose)을 프리셋으로 */
const RO = M.route_options || {fast: 0, rec: M.detour, people: 0.4};
const OPT = [{k: "rec", t: "추천 경로"}, {k: "fast", t: "빠른 길"}, {k: "people", t: "사람 많은 길 우선"}];
function pickRoute(k) { W.opt = k; W.best = W.routes ? W.routes[k] : null; W.detour = RO[k] || 0; }
function compute() {
  if (W.s == null || W.e == null) return;
  if (W.s === W.e) { toast("출발과 도착이 같은 곳이에요"); return; }
  W.busy = true; LY.shops.clearLayers(); renderWalk();
  setTimeout(() => {
    const t0 = performance.now();
    W.front = frontier(W.s, W.e, W.slot);
    W.base = W.front[0] || null;
    W.routes = W.base ? {fast: W.base, rec: choose(W.front, RO.rec), people: choose(W.front, RO.people)} : null;
    pickRoute(W.opt || "rec");
    W.ms = Math.round(performance.now() - t0); W.busy = false;
    if (!W.best) toast("두 곳을 잇는 길을 찾지 못했어요");
    drawWalk(true); renderWalk();
  }, 20);
}
function setPoint(which, i) {
  W[which] = i; W.front = W.base = W.best = W.routes = null;
  if (W.s != null && W.e != null) { drawWalk(); compute(); } else { drawWalk(); renderWalk(); }
}
map.on("click", ev => {
  if (S.mode !== "walk") return;
  const p = snap(ev.latlng.lat, ev.latlng.lng);
  if (p.i < 0 || p.m > M.snap_max_m) { toast("안산 밤길 지도 안의 길 가까이를 눌러 주세요"); return; }
  if (W.s == null) setPoint("s", p.i);
  else if (W.e == null) setPoint("e", p.i);
  else { setPoint("e", p.i); toast("도착지를 바꿨어요"); }
});
const ptsHtml = () => `<div class="pts">${W.s != null ? `<div class="pt"><i class="s"></i>출발 <span>${esc(placeName(W.s))}</span></div>` : ""}${
  W.e != null ? `<div class="pt"><i class="e"></i>도착 <span>${esc(placeName(W.e))}</span></div>` : ""}</div>`;
function timeHtml() {
  const [night, h] = M.slots[W.slot];
  return `<div class="row"><span class="lab">언제 걸어요? · <b>${esc(when(W.slot))}</b></span>${[...DOWS].map((d, i) =>
      `<button class="chip day ${i === night ? "on" : ""}" data-night="${i}">${d}</button>`).join("")}</div>
    <div class="row">${HOURS.map(x => `<button class="chip ${x === h ? "on" : ""}" data-hour="${x}">${HOUR_TXT[x]}</button>`).join("")}</div>${
    REAL && (h === 0 || h === 1) ? `<p class="note" style="text-align:left;margin:0 0 6px">밤 12시가 넘으면 통신 유동인구가 크게 줄어드는데, 통신사 집계 기준 때문인지 확인하고 있어요 — 사람 드문 구간이 실제보다 많게 나올 수 있어요.</p>` : ""}`;
}
function routeGroups() {                // 같은 길은 카드 하나로 — [{keys, names, r}]
  const g = [];
  for (const o of OPT) {
    const r = W.routes && W.routes[o.k]; if (!r) continue;
    const hit = g.find(x => x.r === r);
    if (hit) { hit.keys.push(o.k); hit.names.push(o.t); } else g.push({keys: [o.k], names: [o.t], r});
  }
  return g;
}
function resultHtml() {
  if (W.busy) return `<p class="sub"><span class="spin"></span>사람 다니는 길을 찾는 중…</p>`;
  if (!W.best) return `<p class="sub">두 곳을 잇는 길을 찾지 못했어요. 다른 곳을 눌러 보세요.</p>`;
  const f = W.routes.fast, groups = routeGroups(), along = `${SHOP_T} ${W.nShops}곳 · 지구대 ${W.nCops}곳 근처를 지나요`;
  const cards = groups.map(g => {
    const r = g.r, on = g.keys.includes(W.opt), dm = walkMin(r.len) - walkMin(f.len), cut = darkDisp(f.edges, W.slot) - darkDisp(r.edges, W.slot);
    const vs = g.keys.includes("fast")
      ? (groups.length === 1 ? "가장 빠른 길이 사람도 가장 많이 다니는 길이에요" : "가장 짧은 길이에요")
      : `빠른 길보다 ${dm > 0 ? `${dm}분 더 걷고` : "비슷한 시간에"}, 사람 드문 구간은 ${cut >= 5 ? `${km(cut)} 줄어요` : "비슷해요"}`;
    return `<div class="rcard opt ${on ? "pick" : ""}" data-opt="${g.keys[0]}" role="button" tabindex="0">
      <div class="t"><h4>${g.names.join(" · ")}</h4><span class="big">${walkMin(r.len)}분</span></div>
      <div class="mut">${km(r.len)} · 사람 드문 구간 ${darkTxt(darkDisp(r.edges, W.slot))}</div>
      <div class="mut">${vs}${on ? ` · ${along}` : ""}</div>${accLine(accOn(r.edges).length)}</div>`;
  }).join("");
  const legend = `<div class="legend">${[3, 2, 1].map(g => `<span><i class="sw" style="background:${GRADE[g][0]}"></i>${GRADE[g][1]}</span>`).join("")}${
    groups.length > 1 ? `<span><i class="sw" style="background:#5f6368;opacity:.6"></i>다른 길</span>` : ""}</div>`;
  return `<div class="lab2">어떤 길로 갈까요? <small>누르면 지도에 그 길을 보여 드려요</small></div>${cards}${legend}`;
}
/* 첫 화면 인사 · 바로가기 · 우리 집(#31) — 집은 이 휴대폰에만 저장 */
const home = () => store.get(KEY_HOME, null);
function homeName() { const h = home(), x = $("homeName"); if (x) x.textContent = h ? h.name : ""; }
function goHome() {
  const h = home();
  if (!h) { toast("길을 찾은 뒤 '도착을 집으로 등록'을 누르면, 다음부터 '집으로' 한 번에 가요", 4200); return; }
  W.s = null; W.e = h.i; W.front = W.base = W.best = W.routes = null; LY.shops.clearLayers();
  drawWalk(); renderWalk(); map.setView(ll(h.i), 15);                // 바로 '도착: 집'으로 — 위치는 그다음에(못 받으면 지도에서 출발)
  toast("내 위치를 찾고 있어요 · 출발할 곳을 지도에서 눌러도 돼요", 3000);
  locate(q => {
    if (W.s != null || W.e !== h.i) return;                         // 그사이 지도에서 출발을 눌렀으면 그대로
    const p = snap(q[0], q[1]);
    if (p.i < 0 || p.m > M.snap_max_m) { toast("지금 위치가 안산 밤길 지도 밖이에요 · 출발할 곳을 지도에서 눌러 주세요", 3600); return; }
    setPoint("s", p.i);
  }, () => toast("위치를 받지 못했어요 · 출발할 곳을 지도에서 눌러 주세요", 3600));
}
function showOpenShops() {              // 지금 화면 안에서 그 시각 문 연 가게(가상 데이터) — 길을 찾기 전에도 보이게
  LY.shops.clearLayers();
  const b = map.getBounds(), open = D.shops.filter(s => ((s[3] >> W.slot) & 1) && b.contains([s[0], s[1]]));
  const every = Math.max(1, Math.ceil(open.length / 60));
  open.forEach((s, k) => {
    if (k % every) return;
    L.marker([s[0], s[1]], {icon: poiIcon(SHOP_SVG, "shop")}).bindPopup(`<b>${SHOP_T}</b><br>${s[2].length ? s[2].map(esc).join("<br>") : "심야 업종 가게"}<div class="note">${esc(when(W.slot))} 기준 · ${SHOP_NOTE}</div>`).addTo(LY.shops);
  });
  toast(open.length ? (M.hours_known ? `${when(W.slot)} 기준 문 연 가게 ${open.length}곳을 표시했어요(가상 데이터)`
                                     : `밤에 여는 업종 가게 ${open.length}곳을 표시했어요 · 영업 여부는 확인하지 못했어요`)
                    : `이 화면 안에는 ${SHOP_T}가 없어요 · 지도를 옮겨 보세요`, 3600);
}
function renderWalk() {
  let h;
  if (W.s == null && W.e == null) {
    const hm0 = home();
    h = `<div class="greet"><b>${isNight() ? "오늘 하루도 수고했어요 🌙" : "밤길을 미리 살펴보세요 ☀️"}</b><span>${esc(when(W.slot))} 기준 · 어디로 갈까요?</span></div>
      <div class="tiles">
        <button class="tile t1" id="tHome"><span class="em">🏠</span>집으로<small>${hm0 ? esc(hm0.name) : "등록하기"}</small></button>
        <button class="tile t2" id="fromMe"><span class="em">🧭</span>내 위치<small>여기서 출발</small></button>
        <button class="tile t3" id="tMap"><span class="em">📍</span>지도에서<small>두 번 누르기</small></button>
        <button class="tile t4" id="tShops"><span class="em">🏪</span>${M.hours_known ? "문 연 가게" : "심야 가게"}<small>${M.hours_known ? "지금 열린 곳" : "밤에 여는 업종"}</small></button>
      </div>
      <p class="sub">지도를 눌러 출발 · 도착을 고르거나, 위 검색으로 역 · 동을 찾아도 돼요.</p>`;
  } else if (W.s == null) {
    h = `${ptsHtml()}<div class="hint">어디서 출발해요?</div><p class="sub">지도에서 출발할 곳을 누르세요.</p>
      <div class="btns"><button class="btn" id="fromMe">내 위치에서 출발</button><button class="btn ghost" id="reset">처음으로</button></div>`;
  } else if (W.e == null) {
    h = `${ptsHtml()}<div class="hint">어디로 가요?</div><p class="sub">지도에서 도착할 곳을 누르세요.</p>
      <div class="btns"><button class="btn ghost" id="reset">출발 다시 고르기</button></div>`;
  } else {
    const isHome = home() && home().i === W.e;
    h = `${ptsHtml()}${timeHtml()}${resultHtml()}
      <div class="btns"><button class="btn line" id="swap">출발 ↔ 도착</button><button class="btn line" id="reset">다시 찍기</button></div>
      ${isHome ? "" : `<div class="btns"><button class="btn ghost" id="setHome">🏠 도착을 집으로 등록</button></div>`}
      <p class="note">${REAL
        ? `사람이 다니는 정도는 통신 유동인구(50m 칸, ${esc(monthsTxt())} 평균)로 계산했어요. 사는 사람이 적은 칸은 그 칸 값을 쓰지 않고 주변 칸 값으로 채워요. 가게 영업 여부는 확인하지 못했어요.`
        : "사람이 다니는 정도와 가게 영업은 가상 데이터로 만든 시연이에요."} 이 앱은 사람이 다니는 길 · 문 연 가게를 기준으로 길을 고를 뿐, 범죄 여부는 알려 주지 않아요.</p>`;
  }
  $("sheetBody").innerHTML = h;
  const B = $("sheetBody"), on = (id, f) => { const x = $(id); if (x) x.onclick = f; };
  on("fromMe", () => locate(q => { const p = snap(q[0], q[1]); if (p.i < 0 || p.m > M.snap_max_m) { toast("지금 위치가 안산 밤길 지도 밖이에요"); return; } map.setView(q, 16); setPoint("s", p.i); }));
  on("tHome", goHome);
  on("tMap", () => toast("지도에서 출발할 곳을 누르고, 이어서 도착할 곳을 누르세요", 3200));
  on("tShops", showOpenShops);
  on("setHome", () => { store.set(KEY_HOME, {i: W.e, name: placeName(W.e)}); homeName(); toast("집으로 등록했어요 · 첫 화면 '집으로'로 한 번에 가요", 3200); renderWalk(); });
  on("reset", () => { W.s = W.e = null; W.front = W.base = W.best = W.routes = null; drawWalk(); renderWalk(); });
  on("swap", () => { const t = W.s; W.s = W.e; W.e = t; compute(); });
  B.querySelectorAll("[data-night]").forEach(b => { b.onclick = () => { W.slot = slotOf(+b.dataset.night, M.slots[W.slot][1]); compute(); }; });
  B.querySelectorAll("[data-hour]").forEach(b => { b.onclick = () => { W.slot = slotOf(M.slots[W.slot][0], +b.dataset.hour); compute(); }; });
  B.querySelectorAll("[data-opt]").forEach(b => { b.onclick = () => { if (!W.routes) return; pickRoute(b.dataset.opt); drawWalk(); renderWalk(); }; });
  placeFabs();
}

/* ── 6. 러닝 — 드로잉 런 · 차 없는 길 · 완주 뱃지 ─────────────────── */
const COURSES = D.courses || [];
/* 낮 · 밤 기준(#26 · RUN_DAYNIGHT) — 해 뜨고 지는 시각으로 가르고, 이용자가 바꿀 수 있다 */
function sunToday() {
  const s = M.sun; if (!s || !s.rise) return null;
  const d = new Date(), j = Math.round((Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()) - Date.UTC(d.getFullYear(), 0, 1)) / 864e5);
  const k = Math.max(0, Math.min(j, s.rise.length - 1)); return {rise: s.rise[k], set: s.set[k]};
}
function isNight() { const t = sunToday(), d = new Date(), m = d.getHours() * 60 + d.getMinutes(); return t ? (m < t.rise || m >= t.set) : (d.getHours() >= 19 || d.getHours() < 6); }
const hm = m => `${Math.floor(m / 60)}:${String(m % 60).padStart(2, "0")}`;
function nightSlot() {                  // 밤 기준 시각 — 오늘(새벽이면 어젯밤) 밤 10시. 사람 수 자료가 밤 10시~새벽 1시뿐
  const d = new Date(), wd = (d.getDay() + 6) % 7;
  return slotOf(d.getHours() < 6 ? (wd + 6) % 7 : wd, (M.day_night && M.day_night.night_hour) || 22);
}
/* 러닝 새벽 · 저녁(#35 · RUN_BANDS) — 실데이터 판만. 그 시간대 통신 유동인구로 매긴 등급(1 사람 드묾 · 2 보통 · 3 사람 많음)만 실려 있다.
   공개 판(가상 데이터)에는 없어서 낮 · 밤만 보인다 */
const RUNG = {}; if (D.rung) for (const k in D.rung) RUNG[k] = dec(D.rung[k], Uint8Array);
const RB = M.run_bands || {};
const isBand = dn => !!RUNG[dn];
const DN = [["dawn", "🌅 새벽"], ["day", "☀️ 낮"], ["eve", "🌆 저녁"], ["night", "🌙 밤"]].filter(([k]) => k === "day" || k === "night" || isBand(k));
function bandTxt(dn) { const h = RB[dn] || []; if (!h.length) return ""; const f = x => x > 12 ? x - 12 : x; return `${f(h[0])}~${f(h[h.length - 1] + 1)}시`; }
function bandDark(dn) {                 // 오늘 그 시간대 가운데 시각에 해가 져 있나 — 어두우면 산길 · 농로도 같이 센다
  const h = RB[dn], s = sunToday(); if (!h || !h.length || !s) return true;
  const mid = (h[0] + h[h.length - 1] + 1) / 2 * 60; return mid < s.rise || mid >= s.set;
}
const darkMode = () => R.dn === "night" || (isBand(R.dn) && bandDark(R.dn));
const runKey = () => isBand(R.dn) ? R.dn : nightSlot();
const badLen = t => darkMode() ? t.nightBad : t.sparse;   // 낮이 아닐 때 줄 세우는 길이 — 어두우면 산길까지
function initDn() { const h = new Date().getHours(); for (const k of ["dawn", "eve"]) if (isBand(k) && (RB[k] || []).includes(h)) return k; return isNight() ? "night" : "day"; }
const CST = {};
function cstats(c, slot) {              // 코스 위 길 종류 · 사람 드문 구간 · 산길 · 보행 사고 잦았던 곳 (m). slot — 밤 시간대 번호 또는 'dawn' · 'eve'
  const key = c.id + ":" + slot; if (CST[key]) return CST[key];
  const band = typeof slot === "string" ? RUNG[slot] : null;
  const t = {L: 0, free: 0, mixed: 0, major: 0, side: 0, trail: 0, sparse: 0, nightBad: 0};
  for (const e of c.e || []) {
    const l = LEN[e], r = ROAD[e]; t.L += l;
    if (r === 0) t.free += l; else if (r === 1) t.mixed += l; else if (r === 2) t.major += l; else t.side += l;
    const sp = band ? band[e] === 1 : gradeOf(e, slot) === 1, tr = TRAIL[e] === 1;   // 보이는 등급 기준
    if (sp) t.sparse += l; if (tr) t.trail += l; if (sp || tr) t.nightBad += l;
  }
  t.acc = accOn(c.e || []);
  return (CST[key] = t);
}
const pct = (x, t) => 100 * x / (t.L || 1);
function ordered(list) {                // 낮: 골목이 짧은 순(같으면 큰 찻길) · 밤: 사람 드물거나 산길인 구간이 짧은 순(같으면 골목) · 새벽 · 저녁: 그 시간대 사람 드문 구간(어두우면 산길까지)
  const bin = (M.day_night && M.day_night.bin) || 0.1, s = runKey(), q = x => Math.round(x / bin);
  const key = c => { const t = cstats(c, s), L = t.L || 1; return R.dn !== "day" ? [q(badLen(t) / L), t.mixed / L] : [q(t.mixed / L), t.major / L]; };
  return list.map(c => [key(c), c]).sort((a, b) => (a[0][0] - b[0][0]) || (a[0][1] - b[0][1])).map(x => x[1]);
}
const RP = M.run_pick || {minutes: [15, 30, 45, 60], default: 30, window: 0.3, n: 3, max_laps: 2};
// view — 'pick'(몇 분 달릴지 고르고 추천 3개, #28) · 'list'(코스 전체)
const R = {tab: "drawing", sel: null, T: null, dn: initDn(), view: "pick", min: RP.default};
const badges = () => store.get(KEY_BADGE, {});
const courseColor = c => c.type === "drawing" ? "#6f42c1" : "#0f9d58";
const dim = c => c.trail_pct != null && c.trail_pct >= (M.trail_note ?? 1) * 100;   // 산길 · 농로 비중 — 밤 불빛 안내(RUN_TRAIL_NOTE)
// 시민 화면에는 비율(%)을 내놓지 않는다 — 말로 바꾼다(기억: 시민 화면은 통계표가 아니다)
const share = p => p < 5 ? "거의 없어요" : p < 20 ? "조금 있어요" : p < 40 ? "3분의 1쯤 돼요" : p < 60 ? "절반쯤 돼요" : p < 85 ? "대부분이에요" : "거의 전부예요";
const shareN = p => p < 5 ? "거의 없음" : p < 20 ? "조금" : p < 40 ? "3분의 1쯤" : p < 60 ? "절반쯤" : p < 85 ? "대부분" : "거의 전부";
function shapeSvg(c, size, color) {     // 코스 모양 그대로 아이콘(드로잉 런은 그림 틀)
  const pts = c.type === "drawing" && c.template && c.template.length > 2 ? c.template : c.path;
  if (!pts || pts.length < 2) return "";
  const lat0 = pts.reduce((a, p) => a + p[0], 0) / pts.length, cx = Math.cos(lat0 * Math.PI / 180);
  const xs = pts.map(p => p[1] * cx), ys = pts.map(p => -p[0]);
  let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
  for (let k = 0; k < xs.length; k++) { x0 = Math.min(x0, xs[k]); x1 = Math.max(x1, xs[k]); y0 = Math.min(y0, ys[k]); y1 = Math.max(y1, ys[k]); }
  const sc = 40 / Math.max(x1 - x0, y1 - y0, 1e-9), ox = (48 - (x1 - x0) * sc) / 2, oy = (48 - (y1 - y0) * sc) / 2;
  const step = Math.max(1, Math.floor(pts.length / 200)); let d = "";
  for (let k = 0; k < pts.length; k += step) d += (d ? "L" : "M") + ((xs[k] - x0) * sc + ox).toFixed(1) + " " + ((ys[k] - y0) * sc + oy).toFixed(1);
  const col = color || "#16325c", closed = c.type === "drawing";
  return `<svg viewBox="0 0 48 48" width="${size}" height="${size}" aria-hidden="true"><path d="${d}${closed ? "Z" : ""}" fill="${closed ? col + "22" : "none"}" stroke="${col}" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round"/></svg>`;
}
function samples(path, step) {          // 코스를 step m 간격 점으로
  const out = [path[0]]; let need = step;
  for (let k = 1; k < path.length; k++) {
    let a = path[k - 1]; const b = path[k]; let d = dist(a, b);
    while (d >= need) { const t = need / d; a = [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]; out.push(a); d -= need; need = step; }
    need -= d;
  }
  return out;
}
function arrows(path, every) {          // 달리는 방향 표시
  const out = []; let acc = 0, next = every / 2;
  for (let k = 1; k < path.length; k++) {
    const a = path[k - 1], b = path[k], d = dist(a, b);
    while (d > 0 && acc + d >= next) {
      const t = (next - acc) / d, p = [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
      const ang = Math.atan2((b[1] - a[1]) * Math.cos(a[0] * Math.PI / 180), b[0] - a[0]) * 180 / Math.PI;
      out.push(L.marker(p, {interactive: false, icon: L.divIcon({className: "pinwrap", iconSize: [0, 0],
        html: `<div class="arrow" style="transform:translate(-50%,-50%) rotate(${ang.toFixed(0)}deg)"></div>`})}));
      next += every;
    }
    acc += d;
  }
  return out;
}
function drawCourse(c) {
  const col = courseColor(c);
  if (c.type === "drawing" && c.template)          // 그림 틀 — 옅게 칠해 무슨 그림인지 먼저 보이게(길만으로는 바둑판 동네에서 네모가 된다)
    L.polygon(c.template, {color: col, weight: 2, opacity: .6, dashArray: "4 6", fillColor: col, fillOpacity: .12, interactive: false}).addTo(LY.run);
  L.polyline(c.path, {color: "#fff", weight: 10, opacity: .95, interactive: false}).addTo(LY.run);
  L.polyline(c.path, {color: col, weight: 6, opacity: .95, interactive: false}).addTo(LY.run);
  arrows(c.path, 400).forEach(m => m.addTo(LY.run));
  L.marker(c.start || c.path[0], {icon: pin("출발", "run"), interactive: false}).addTo(LY.run);
  accDraw(accOn(c.e || []), LY.run);
}
function drawRun(fit) {
  LY.run.clearLayers();
  const c = R.T ? R.T.c : R.sel;
  if (c) {
    drawCourse(c);
    if (R.T) {
      R.T.trail = L.polyline(R.T.pts, {color: "#1a73e8", weight: 5, opacity: .9, interactive: false}).addTo(LY.run);
      R.T.me = L.marker(R.T.pts.length ? R.T.pts[R.T.pts.length - 1] : (c.start || c.path[0]), {icon: meIcon(), interactive: false}).addTo(LY.run);
    }
    if (fit) fitTo(c.path);
    return;
  }
  const list = R.view === "pick" ? recs(R.min).map(r => r.c) : COURSES.filter(x => x.type === R.tab), all = [];
  list.forEach(x => {
    L.polyline(x.path, {color: "#fff", weight: 7, opacity: .9, interactive: false}).addTo(LY.run);
    const pl = L.polyline(x.path, {color: courseColor(x), weight: 4, opacity: .92}).addTo(LY.run);
    pl.bindTooltip(x.name, {sticky: true}); pl.on("click", () => selectCourse(x.id));
    x.path.forEach(p => all.push(p));
  });
  if (fit && all.length) fitTo(all);
}
function selectCourse(id) { R.sel = COURSES.find(x => x.id === id) || null; drawRun(true); renderRun(); }
function dnRowHtml(orderTxt) {
  const sun = sunToday(), chip = (k, lab) => isBand(k) ? `<button class="chip ${R.dn === k ? "on" : ""}" data-dn="${k}">${lab}</button>` : "";
  const ord = R.dn === "day" ? "차가 같이 다니는 골목이 짧은 순" : darkMode() ? "사람 드물거나 어두운 구간이 짧은 순" : "사람 드문 구간이 짧은 순";
  return `<div class="row dn">${chip("dawn", "🌅 새벽")}<button class="chip ${R.dn === "day" ? "on" : ""}" data-dn="day">☀️ 낮</button>${chip("eve", "🌆 저녁")}<button class="chip ${R.dn === "night" ? "on" : ""}" data-dn="night">🌙 밤</button>
    <span class="lab">${orderTxt ? ord + " · " : ""}${sun ? (R.dn === "dawn" ? `오늘 해 뜨는 시각 ${hm(sun.rise)}` : `오늘 해 지는 시각 ${hm(sun.set)}`) : ""}</span></div>`;
}
function tagsHtml(c, t) {
  const tag = R.dn === "day" ? `<span class="tg day">차 다니는 골목 ${shareN(pct(t.mixed, t))}</span>`
    : darkMode() ? `<span class="tg night">사람 드문 길 · 산길 ${shareN(pct(t.nightBad, t))}</span>` : `<span class="tg night">사람 드문 길 ${shareN(pct(t.sparse, t))}</span>`;
  return `<div class="tags">${tag}${t.acc.length ? `<span class="tg acc">⚠️ 사고 잦았던 곳 ${t.acc.length}</span>` : ""}${dim(c) && darkMode() ? `<span class="tg dim">불빛 적을 수 있음</span>` : ""}</div>`;
}
/* 추천 3개(#28 · RUN_PICK) — 고른 시간 ±30% 안(한 바퀴 코스는 두 바퀴까지)에서
   ① 지금 기준(낮 · 밤)에 가장 맞는 코스 ② 드로잉 런 ③ 차 없는 길. '이런 분께'는 코스 자료로만 만든다(오르막 · 노면 · 조명은 모름) */
function recs(minutes) {
  const s = runKey(), bin = (M.day_night && M.day_night.bin) || 0.1, q = x => Math.round(x / bin);
  const rows = COURSES.map(c => {
    const m1 = runMin(c.length_m);
    let laps = 1;
    if (c.loop !== false) for (let k = 2; k <= (RP.max_laps || 1); k++) if (Math.abs(m1 * k - minutes) < Math.abs(m1 * laps - minutes)) laps = k;
    const t = cstats(c, s), L = t.L || 1;
    return {c, t, laps, min: m1 * laps, err: Math.abs(m1 * laps - minutes) / minutes,
            key: R.dn !== "day" ? [q(badLen(t) / L), t.mixed / L] : [q(t.mixed / L), t.major / L]};
  });
  let pool = rows.filter(r => r.err <= RP.window);
  if (pool.length < RP.n) pool = rows.slice().sort((a, b) => a.err - b.err).slice(0, RP.n + 2);
  const byKey = (a, b) => (a.key[0] - b.key[0]) || (a.err - b.err) || (a.key[1] - b.key[1]);
  const out = [], used = new Set();
  const take = (ok, why) => {
    const r = pool.filter(x => !used.has(x.c.id) && ok(x)).sort(byKey)[0];
    if (r) { used.add(r.c.id); out.push(Object.assign({}, r, {why: why(r)})); }
  };
  take(() => true, r => R.dn === "night"
    ? `밤에 달리는 분께 — 사람 드물거나 어두운 구간이 ${share(pct(r.t.nightBad, r.t))}`
    : isBand(R.dn) ? `${R.dn === "dawn" ? "새벽" : "저녁"}에 달리는 분께 — 사람 드문 구간${darkMode() ? "이나 어두운 산길" : ""}이 ${share(pct(badLen(r.t), r.t))}`
    : `차가 신경 쓰이는 분께 — 차가 같이 다니는 골목이 ${share(pct(r.t.mixed, r.t))}`);
  take(x => x.c.type === "drawing", r => `그림 뱃지를 모으는 분께 — 달리면 지도에 ${esc(r.c.name.replace(/런$/, ""))} 그림이 돼요`);
  take(x => x.c.type === "carfree", r => `차 없는 길을 원하는 분께 — 보행로 · 산책로가 ${share(pct(r.t.free, r.t))}` +
    (dim(r.c) ? (R.dn === "night" ? ". 밤에는 산길이라 어두울 수 있어요" : darkMode() ? ". 어두운 시간이라 산길은 불빛이 적을 수 있어요" : ". 공원 · 산길을 좋아하는 분께도 좋아요") : ""));
  while (out.length < RP.n) { const k = out.length; take(() => true, r => `시간에 잘 맞는 코스 — 약 ${r.min}분`); if (out.length === k) break; }
  return out;
}
function pickHtml() {
  if (!COURSES.length) return `<h3>러닝</h3><p class="sub">러닝 코스 자료가 아직 없어요.</p>`;
  const bd = badges(), got = COURSES.filter(c => bd[c.id]).length, rs = recs(R.min);
  return `<div style="display:flex;justify-content:space-between;align-items:center"><h3>러닝</h3><button class="chip" id="myBadges">내 뱃지 ${got}/${COURSES.length}</button></div>
    <div class="row"><span class="lab">몇 분 달릴 거예요?</span>${RP.minutes.map(m => `<button class="chip ${m === R.min ? "on" : ""}" data-min="${m}">${m >= 60 ? "1시간" : m + "분"}</button>`).join("")}</div>
    ${dnRowHtml(false)}
    <div class="lab2">추천 코스 <small>시연용 예시 · 1km ${paceTxt()} 기준</small></div>
    ${rs.map(r => `<div class="course rec ${bd[r.c.id] ? "got" : ""}" data-id="${esc(r.c.id)}"><div class="ic">${shapeSvg(r.c, 40, bd[r.c.id] ? "#0f9d58" : courseColor(r.c))}</div>
      <div class="tx"><b>${esc(r.c.name)}</b><div class="mut">${r.laps > 1 ? `${r.laps === 2 ? "두" : r.laps} 바퀴 · ` : ""}약 ${r.min}분 · ${km(r.c.length_m * r.laps)} · ${esc(r.c.dong || "")}</div>
        <div class="why">${r.why}</div>${tagsHtml(r.c, r.t)}</div>
      ${bd[r.c.id] ? `<span class="st">완주${bd[r.c.id].demo ? "(시연)" : ""}</span>` : ""}</div>`).join("")}
    <div class="btns"><button class="btn ghost" id="allCourses">코스 전체 보기 · ${COURSES.length}개</button><button class="btn line" id="suggest">내가 아는 길 추천하기</button></div>
    <p class="note">지금 코스는 시연용 예시예요. 운영할 때는 주민이 추천한 길을 담당자가 직접 확인한 뒤 올려요.</p>`;
}
/* 주민 추천 코스(#30 · RUN_SUGGEST) — 다음 단계 안내. 시연판에는 서버가 없어 보내지 않는다 */
function showSuggest() {
  const trim = (M.run_suggest && M.run_suggest.trim_m) || 200;
  modal(`<button class="x" id="mX" aria-label="닫기">×</button><h3>내가 아는 길 추천하기</h3>
    <p class="sub">지금 보이는 코스는 시연용 예시예요. 실제로 운영할 때는 동네를 잘 아는 주민이 추천한 길을 모아, 담당자가 직접 확인한 뒤 '주민 추천 코스'로 올려요.</p>
    <ol class="steps">
      <li><b>길 보내기</b> — 달린 기록을 고르거나 지도에 길을 그리고, 코스 이름 · 어떤 분께 좋은지 · 좋았던 점을 적어요.</li>
      <li><b>집 위치 지우기</b> — 출발 · 도착 근처 ${trim}m는 지우고 보내요.</li>
      <li><b>자료 점검</b> — 차 없는 길 · 밤에 사람 드문 구간 · 산길 · 보행 사고가 잦았던 곳을 자동으로 살펴 함께 적어요.</li>
      <li><b>담당자 확인</b> — 담당자가 현장을 직접 보고 추천할 만한 길만 올려요. 올라간 뒤에도 의견을 받아 고쳐요.</li></ol>
    <p class="note">시연판이라 지금은 보내지지 않아요.</p>
    <div class="btns"><button class="btn" id="mOk2">알겠어요</button></div>`);
  $("mOk2").onclick = closeModal;
}
function listHtml() {
  if (!COURSES.length) return `<h3>러닝 코스</h3><p class="sub">러닝 코스 자료가 아직 없어요.</p>`;
  const bd = badges(), got = COURSES.filter(c => bd[c.id]).length, list = ordered(COURSES.filter(c => c.type === R.tab));
  const nd = COURSES.filter(c => c.type === "drawing").length, nc = COURSES.length - nd, s = runKey();
  const sub = (R.tab === "drawing" ? "달린 길이 지도 위에 그림이 되는 코스예요. 완주하면 그림 뱃지를 드려요."
                                   : "보행로 · 산책로처럼 차가 다니지 않는 길 위주로 고른 코스예요. 차도 옆 보도는 빼고 셌어요." +
                                     (R.dn === "night" ? " 밤에는 이 코스들 대부분이 산길 · 공원길이라 어두울 수 있어요."
                                       : darkMode() ? " 어두운 시간에는 이 코스들 대부분이 산길 · 공원길이라 불빛이 적을 수 있어요." : "")) + " (시연용 예시 코스)";
  return `<div style="display:flex;justify-content:space-between;align-items:center"><button class="chip" id="toPick">← 추천</button><h3 style="margin:0">러닝 코스 전체</h3><button class="chip" id="myBadges">내 뱃지 ${got}/${COURSES.length}</button></div>
    <div class="seg"><button data-tab="drawing" class="${R.tab === "drawing" ? "on" : ""}">드로잉 런 ${nd}</button><button data-tab="carfree" class="${R.tab === "carfree" ? "on" : ""}">차 없는 길 ${nc}</button></div>
    ${dnRowHtml(true)}<p class="sub">${sub}</p>
    ${list.map(c => { const t = cstats(c, s);
      return `<div class="course ${bd[c.id] ? "got" : ""}" data-id="${esc(c.id)}"><div class="ic">${shapeSvg(c, 40, bd[c.id] ? "#0f9d58" : courseColor(c))}</div>
      <div class="tx"><b>${esc(c.name)}</b><div class="mut">${km(c.length_m)} · 달리기 ${runMin(c.length_m)}분 · ${esc(c.dong || "")}</div>
        ${tagsHtml(c, t)}</div>
      ${bd[c.id] ? `<span class="st">완주${bd[c.id].demo ? "(시연)" : ""}</span>` : ""}</div>`; }).join("")}`;
}
function factsHtml(c) {                // 낮에 달리면 · 밤에 달리면 — 지금 기준을 위에
  const s = nightSlot(), t = cstats(c, s);
  const day = `<div class="fx ${R.dn === "day" ? "on" : ""}"><b>☀️ 낮에 달리면</b>
      <div>차가 같이 다니는 골목 · 단지 길이 ${share(pct(t.mixed, t))}.</div>
      <div>큰 찻길 옆을 달리는 구간이 ${share(pct(t.major, t))}.${t.side >= 50 ? ` 차도 옆 보도는 ${km(t.side)}예요.` : ""}</div></div>`;
  const night = `<div class="fx ${R.dn === "night" ? "on" : ""}"><b>🌙 밤에 달리면 <small>${esc(when(s))} 기준</small></b>
      <div>사람 드문 구간이 ${share(pct(t.sparse, t))}.</div>${
      dim(c) ? `<div>산길 · 오솔길 · 농로가 ${share(c.trail_pct)} — 밤에는 불빛이 적을 수 있어 밝을 때 달리기를 권해요.</div>` : ""}</div>`;
  const fx = {day, night};               // 새벽 · 저녁(#35, 실데이터 판만) — 그 시간대 통신 유동인구 등급
  for (const k of ["dawn", "eve"]) if (isBand(k)) {
    const tb = cstats(c, k), dk = bandDark(k);
    fx[k] = `<div class="fx ${R.dn === k ? "on" : ""}"><b>${k === "dawn" ? "🌅 새벽" : "🌆 저녁"} ${esc(bandTxt(k))}에 달리면 <small>통신 유동인구${monthsTxt() ? " " + esc(monthsTxt()) : ""} 평균</small></b>
      <div>사람 드문 구간이 ${share(pct(tb.sparse, tb))}.</div>${
      dim(c) && dk ? `<div>산길 · 오솔길 · 농로가 ${share(c.trail_pct)} — 오늘은 이 시간에 어두워 불빛이 적을 수 있어요.</div>` : ""}</div>`;
  }
  return [R.dn, ...DN.map(x => x[0]).filter(k => k !== R.dn)].map(k => fx[k] || "").join("") +
    (t.acc.length ? `<div class="mut acc" style="margin:0 0 8px">⚠️ ${ACC_TXT} ${t.acc.length}곳을 지나요 — 건널목에서 살펴 주세요</div>` : "");
}
function detailHtml(c) {
  const bd = badges()[c.id], t = cstats(c, nightSlot());
  return `<button class="chip" id="back">← ${R.view === "pick" ? "추천" : "목록"}</button>
    <div style="display:flex;gap:12px;align-items:center;margin:10px 0 4px"><div style="width:58px;height:58px;border-radius:14px;background:#eef3fb;display:grid;place-items:center;flex:none">${shapeSvg(c, 46, courseColor(c))}</div>
      <div><h3 style="margin:0">${esc(c.name)}</h3><div class="sub" style="margin:2px 0 0">${c.type === "drawing" ? "드로잉 런" : "차 없는 길"} · ${esc(c.dong || "")}에서 출발 · ${c.loop === false ? "왕복 코스" : "한 바퀴 코스"}</div></div></div>
    <div class="kv"><div><b>${km(c.length_m)}</b><span>거리</span></div><div><b>${runMin(c.length_m)}분</b><span>달리기(1km ${paceTxt()})</span></div><div><b>${t.free < 1 ? "없음" : km(t.free)}</b><span>차 없는 길</span></div></div>
    ${factsHtml(c)}${bd ? `<p class="sub"><b style="color:#0f9d58">${esc(bd.at)} 완주${bd.demo ? " (시연)" : ""} — 뱃지를 받았어요.</b></p>` : ""}
    <div class="btns"><button class="btn" id="go">이 코스 달리기</button></div>
    <div class="btns"><button class="btn ghost" id="demo">시연: 완주한 것으로 보기</button></div>
    <p class="note">'이 코스 달리기'를 누르면 휴대폰 GPS로 달린 길을 기록해, 코스의 ${Math.round(M.run_done.cover * 100)}% 이상을 ${M.run_done.r_m}m 안으로 지나면 완주 뱃지를 드려요. 기록은 이 휴대폰 안에만 남아요.</p>`;
}
function trackHtml() {
  const T = R.T, pr = T.hit.reduce((a, b) => a + b, 0) / T.samples.length;
  return `<h3>${esc(T.c.name)} ${T.demo ? '<span class="tag gray">시연</span>' : '<span class="tag g">기록 중</span>'}</h3>
    <div class="kv"><div><b id="tkPct">${Math.round(pr * 100)}%</b><span>코스 진행</span></div><div><b id="tkDist">${km(T.dist)}</b><span>달린 거리</span></div><div><b id="tkTime">${mmss(Math.round((Date.now() - T.t0) / 1000))}</b><span>시간</span></div></div>
    <div class="bar"><i id="tkBar" style="width:${Math.round(pr * 100)}%"></i></div>
    <p class="sub">${T.demo ? "코스를 따라 달린 것처럼 움직여 봅니다." : `코스 위를 달리면 진행이 올라가요. ${Math.round(M.run_done.cover * 100)}%를 넘기면 완주예요.`}</p>
    <div class="btns"><button class="btn ghost" id="stop">그만하기</button></div>`;
}
function renderRun() {
  $("sheetBody").innerHTML = R.T ? trackHtml() : R.sel ? detailHtml(R.sel) : R.view === "pick" ? pickHtml() : listHtml();
  const B = $("sheetBody"), on = (id, f) => { const x = $(id); if (x) x.onclick = f; };
  B.querySelectorAll("[data-tab]").forEach(b => { b.onclick = () => { R.tab = b.dataset.tab; drawRun(true); renderRun(); }; });
  B.querySelectorAll("[data-dn]").forEach(b => { b.onclick = () => { R.dn = b.dataset.dn; if (R.view === "pick" && !R.sel) drawRun(true); renderRun(); }; });
  B.querySelectorAll("[data-min]").forEach(b => { b.onclick = () => { R.min = +b.dataset.min; drawRun(true); renderRun(); }; });
  B.querySelectorAll(".course").forEach(el => { el.onclick = () => selectCourse(el.dataset.id); });
  on("allCourses", () => { R.view = "list"; drawRun(true); renderRun(); });
  on("suggest", showSuggest);
  on("toPick", () => { R.view = "pick"; drawRun(true); renderRun(); });
  on("myBadges", showBadges);
  on("back", () => { R.sel = null; drawRun(true); renderRun(); });
  on("go", () => startRun(false));
  on("demo", () => startRun(true));
  on("stop", stopRun);
  placeFabs();
}
function startRun(demo) {
  const c = R.sel; if (!c) return;
  if (!demo && !navigator.geolocation) { toast("이 브라우저는 위치를 쓸 수 없어요"); return; }
  const sm = samples(c.path, M.run_done.step_m);
  R.T = {c, demo: !!demo, samples: sm, hit: new Uint8Array(sm.length), pts: [], dist: 0, t0: Date.now(), done: false, watch: null, tick: 0, anim: 0};
  drawRun(true); renderRun();
  R.T.tick = setInterval(updTrack, 1000);
  if (demo) demoMove(R.T);
  else R.T.watch = navigator.geolocation.watchPosition(p => addPos(p.coords.latitude, p.coords.longitude),
    () => toast("위치를 받지 못했어요 · 위치 권한을 확인하세요"), {enableHighAccuracy: true, maximumAge: 2000, timeout: 20000});
}
function addPos(la, ln) {
  const T = R.T; if (!T) return;
  const p = [la, ln], last = T.pts[T.pts.length - 1];
  if (last) { const d = dist(last, p); if (d < 2) return; T.dist += d; }
  T.pts.push(p);
  const r = M.run_done.r_m;
  for (let k = 0; k < T.samples.length; k++) if (!T.hit[k] && Math.abs(T.samples[k][0] - la) < 0.001 && dist(T.samples[k], p) <= r) T.hit[k] = 1;
  if (T.trail) T.trail.setLatLngs(T.pts);
  if (T.me) T.me.setLatLng(p);
  updTrack();
}
function updTrack() {
  const T = R.T; if (!T) return;
  const pr = T.hit.reduce((a, b) => a + b, 0) / T.samples.length, set = (id, v) => { const x = $(id); if (x) x.textContent = v; };
  set("tkPct", Math.round(pr * 100) + "%"); set("tkDist", km(T.dist)); set("tkTime", mmss(Math.round((Date.now() - T.t0) / 1000)));
  const bar = $("tkBar"); if (bar) bar.style.width = Math.round(pr * 100) + "%";
  if (!T.done && pr >= M.run_done.cover) { T.done = true; finishRun(T); }
}
function demoMove(T) {                  // 시연 — 코스를 따라 달린 것처럼 점을 찍는다(실제 GPS 아님)
  const P = samples(T.c.path, 12); let k = 0;
  T.anim = setInterval(() => {
    if (R.T !== T) { clearInterval(T.anim); return; }
    for (let j = 0; j < 6 && k < P.length; j++, k++) addPos(P[k][0], P[k][1]);
    if (k >= P.length) clearInterval(T.anim);
  }, 40);
}
function stopTimers(T) { if (T.watch != null && navigator.geolocation) navigator.geolocation.clearWatch(T.watch); clearInterval(T.tick); clearInterval(T.anim); }
function stopRun() { if (R.T) stopTimers(R.T); R.T = null; drawRun(true); renderRun(); }
function finishRun(T) { stopTimers(T); award(T.c, T.demo); }
function award(c, demo) {
  const bd = badges();
  if (!bd[c.id] || (bd[c.id].demo && !demo)) bd[c.id] = {at: new Date().toISOString().slice(0, 10), demo: !!demo, km: Math.round(c.length_m / 100) / 10};
  store.set(KEY_BADGE, bd); badgeCount();
  modal(`<div class="won"><div class="b">${shapeSvg(c, 72, "#0f9d58")}</div><h3 style="padding:0">${esc(c.name)} 완주!</h3>
    <p class="sub">${demo ? "시연으로 받은 뱃지예요 — 실제로 달려 완주하면 '시연' 표시가 사라져요." : "코스를 따라 끝까지 달렸어요."}<br>'내 뱃지'에서 모아 볼 수 있어요.</p>
    <div class="btns"><button class="btn ghost" id="mBadges">내 뱃지 보기</button><button class="btn" id="mOk">확인</button></div></div>`);
  const back = () => { R.T = null; drawRun(true); renderRun(); };
  $("mOk").onclick = () => { closeModal(); back(); };
  $("mBadges").onclick = () => { back(); showBadges(); };
}
function badgeCount() { const bd = badges(); $("badgeCount").textContent = COURSES.length ? `${COURSES.filter(c => bd[c.id]).length}/${COURSES.length}` : ""; }

/* ── 7. 메뉴 · 안내 창 · 검색 ───────────────────────────────── */
function modal(html) { $("modalBody").innerHTML = html; $("modal").classList.add("on"); const x = $("mX"); if (x) x.onclick = closeModal; }
function closeModal() { $("modal").classList.remove("on"); }
$("modal").onclick = e => { if (e.target.id === "modal") closeModal(); };
function drawer(open) { $("drawer").classList.toggle("open", open); $("scrim").classList.toggle("on", open); }
$("menuBtn").onclick = () => drawer(true);
$("scrim").onclick = () => drawer(false);
function showBadges() {
  const bd = badges(), list = COURSES.slice().sort((a, b) => (a.type === b.type ? 0 : a.type === "drawing" ? -1 : 1));
  modal(`<button class="x" id="mX" aria-label="닫기">×</button><h3>내 뱃지 · ${list.filter(c => bd[c.id]).length}/${list.length}</h3>
    ${list.length ? `<div class="badges">${list.map(c => `<div class="badge ${bd[c.id] ? "" : "off"}" data-id="${esc(c.id)}"><div class="b">${shapeSvg(c, 40, bd[c.id] ? "#0f9d58" : "#16325c")}</div>${esc(c.name)}<small>${
      bd[c.id] ? esc(bd[c.id].at) + (bd[c.id].demo ? " · 시연" : "") : km(c.length_m)}</small></div>`).join("")}</div>` : "<p class='sub'>러닝 코스 자료가 아직 없어요.</p>"}
    <p class="note">뱃지는 이 브라우저에만 저장돼요. 뱃지를 누르면 그 코스로 가요.</p>`);
  $("modalBody").querySelectorAll(".badge").forEach(el => {
    el.onclick = () => { closeModal(); const c = COURSES.find(x => x.id === el.dataset.id); if (!c) return; R.tab = c.type; setMode("run"); selectCourse(c.id); };
  });
}
function showGuide() {
  const nd = COURSES.filter(c => c.type === "drawing").length;
  modal(`<button class="x" id="mX" aria-label="닫기">×</button><h3>이용 안내</h3>
    <p><b>밤길</b> — 지도에서 출발 · 도착을 차례로 누르면 길을 세 가지로 보여 드려요. <b>빠른 길</b>은 가장 짧은 길,
      <b>추천 경로</b>는 조금만 더 걸어 사람이 드문 구간을 줄인 길, <b>사람 많은 길 우선</b>은 더 걷더라도 사람이 드문 구간이 가장 적은 길이에요.
      요일 · 시각에 따라 길이 달라져요. 길 색이 진할수록 그 시각에 사람이 많이 다니는 길이에요.</p>
    <p><b>러닝</b> — 몇 분 달릴지 고르면 코스 세 개를 추천해 드려요(지금 시간에 맞는 코스 · 드로잉 런 · 차 없는 길).
      달린 길이 지도에 그림이 되는 '드로잉 런' ${nd}개와 '차 없는 길' 코스가 있고, 완주하면 뱃지를 드려요.</p>
    <p>이 앱은 사람이 다니는 길과 문 연 가게를 기준으로 길을 고를 뿐, 범죄가 나는 곳인지는 알려 주지 않아요.</p>
    <p class="note">${REAL ? `내부 시연판이에요 — 사람이 다니는 정도는 통신 유동인구 실데이터(${esc(monthsTxt())})예요. 가게 영업 여부는 확인하지 못했어요.`
                            : "시연판이에요 — 사람이 다니는 정도와 가게 영업 여부는 가상 데이터예요."}</p>`);
}
function showSources() {
  modal(`<button class="x" id="mX" aria-label="닫기">×</button><h3>자료 출처</h3><ol>
    <li>길 — OpenStreetMap 보행망(© OpenStreetMap contributors, ODbL)</li>
    ${REAL ? `<li>사람이 다니는 정도 — 안산시 민간데이터: 통신 50m 유동인구(DS-032) · 100m 거주인구(DS-082) · 이동수단(DS-008), ${esc(monthsTxt())}.
        등급으로만 보여 주고, 사는 사람이 적은 칸은 그 칸 값을 쓰지 않고 주변 칸 값으로 채워요(길 찾기에도 같은 값). <b>내부 시연용</b> — 공개 전 확인이 필요해요</li>
      <li>가게 이름 · 위치 — 소상공인시장진흥공단 상가(상권)정보 · 영업 여부는 모름(카드 결제 자료의 위치가 없어요)</li>`
    : `<li>사람이 다니는 정도 · 가게 영업 — 안산시 민간데이터(통신 · 카드) 규격을 따라 만든 <b>가상 데이터</b>. 실제 분포가 아닙니다</li>
      <li>가게 이름 · 위치 — 소상공인시장진흥공단 상가(상권)정보</li>`}
    <li>지구대 · 파출소 — OpenStreetMap</li>
    <li>역 — 코레일 · OpenStreetMap / 행정동 — 통계청 SGIS</li>
    <li>러닝 코스 — OpenStreetMap 보행망으로 계산${M.courses_built ? ` (${esc(M.courses_built)})` : ""}. 차도 옆 보도는 OpenStreetMap 에 따로 그려진 곳만 알아요</li>
    <li>보행 사고가 잦았던 곳 — 한국도로교통공단 교통사고 다발지역(공공데이터포털)${M.ped_acc && M.ped_acc.years ? `, ${M.ped_acc.years[0]}~${M.ped_acc.years[1]}년` : ""}. 어르신 · 어린이 보행 사고만 있어요</li>
    <li>해 뜨고 지는 시각 — 안산 중심 좌표로 계산(NOAA 식)</li></ol>
    <p><b>안산시 공식 서비스가 아닙니다.</b> 서비스 아이디어를 보여 주는 시연판이에요. 담당자용 분석 화면(보안등 대조 · 개선 우선 구간)은 따로 있어요.</p>
    <p class="note">만든 날 ${esc(M.built)}</p>`);
}
function showBaseSet() {
  modal(`<button class="x" id="mX" aria-label="닫기">×</button><h3>바탕지도 설정</h3>
    <p>${M.vworld_key ? "이 앱에는 브이월드(국토교통부) 지도가 들어 있어요. 다른 인증키를 쓰려면 아래에 넣으세요." :
      "키가 없어도 OpenStreetMap 바탕으로 볼 수 있어요. 브이월드(국토교통부) 인증키를 넣으면 브이월드 일반 · 야간 지도로 바뀌어요."}</p>
    <ol><li>vworld.kr → 오픈API → 인증키 발급 — 배경지도(WMTS)도 쓰도록 신청</li><li>서비스 URL: <b>${esc(location.origin)}</b></li></ol>
    <input type="text" id="vk" value="${esc(store.raw(KEY_VW))}" placeholder="${M.vworld_key ? "비워 두면 앱에 들어 있는 지도를 써요" : "브이월드 인증키 붙여넣기"}">
    <div class="btns"><button class="btn" id="vSave">저장하고 다시 열기</button><button class="btn ghost" id="vDel">키 지우기</button></div>
    <p class="note">여기 넣은 키는 이 브라우저에만 저장돼요. 지금 바탕: ${BASES.some(b => b.vw) ? "브이월드" : "OpenStreetMap"}</p>`);
  $("vSave").onclick = () => { store.put(KEY_VW, $("vk").value.trim()); location.reload(); };
  $("vDel").onclick = () => { store.put(KEY_VW, ""); location.reload(); };
}
function showHome() {
  const h = home();
  modal(`<button class="x" id="mX" aria-label="닫기">×</button><h3>우리 집</h3>
    ${h ? `<p>지금 등록된 집: <b>${esc(h.name)}</b></p><p class="sub">첫 화면 '집으로'를 누르면 내 위치에서 집까지 길을 찾아요.</p>
      <div class="btns"><button class="btn ghost" id="hDel">집 지우기</button></div>`
        : `<p class="sub">아직 등록된 집이 없어요. 밤길에서 도착을 집으로 정해 길을 찾은 뒤 '🏠 도착을 집으로 등록'을 누르세요.</p>`}
    <p class="note">집 위치는 이 휴대폰에만 저장돼요.</p>`);
  const x = $("hDel"); if (x) x.onclick = () => { store.put(KEY_HOME, ""); homeName(); closeModal(); if (S.mode === "walk" && W.s == null) renderWalk(); toast("집을 지웠어요"); };
}
/* 홈 화면에 추가(#31) — 브라우저가 설치 창을 줄 수 있으면 그것을, 아니면 기기별 방법 */
let installEv = null;
addEventListener("beforeinstallprompt", e => { e.preventDefault(); installEv = e; });
function showInstall() {
  if (installEv) { window.__installPrompted = true; installEv.prompt(); installEv.userChoice.finally(() => { installEv = null; }); return; }
  const standalone = matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
  modal(`<button class="x" id="mX" aria-label="닫기">×</button><h3>홈 화면에 추가</h3>
    ${standalone ? `<p class="sub">이미 앱으로 열려 있어요.</p>` : `<p class="sub">앱처럼 쓰려면 홈 화면(바탕 화면)에 추가하세요. 추가하면 주소창 없이 전체 화면으로 열리고, 인터넷이 끊겨도 앱은 열려요(지도 바탕은 인터넷 필요).</p>
    <ol class="steps"><li><b>안드로이드 · 크롬</b> — 오른쪽 위 ⋮ → '앱 설치' 또는 '홈 화면에 추가'</li>
      <li><b>아이폰 · 사파리</b> — 아래 공유 버튼 → '홈 화면에 추가'</li>
      <li><b>PC · 크롬 / 엣지</b> — 주소창 오른쪽 설치 아이콘 → '설치'</li></ol>`}
    <p class="note">휴대폰에 설치하려면 이 앱이 인터넷 주소(https)로 올라가 있어야 해요. 지금 시연판은 이 PC에서만 열려요.</p>`);
}
document.querySelectorAll("[data-go]").forEach(el => {
  el.onclick = ev => { ev.preventDefault(); drawer(false); ({badges: showBadges, guide: showGuide, base: showBaseSet, sources: showSources, home: showHome, install: showInstall})[el.dataset.go](); };
});
const q = $("q"), qres = $("qres");
q.oninput = () => {
  const v = q.value.trim();
  if (!v) { qres.classList.remove("on"); return; }
  const hits = D.places.filter(p => p.t.includes(v) || (p.s || "").includes(v)).slice(0, 20)
    .concat(COURSES.filter(c => c.name.includes(v)).map(c => ({t: c.name, s: "러닝 코스", course: c.id})));
  qres.innerHTML = hits.length ? hits.map((h, i) => `<li data-i="${i}">${esc(h.t)}<small>${esc(h.s || "")}</small></li>`).join("") : `<li class="none">찾은 곳이 없어요</li>`;
  qres.classList.add("on");
  qres.querySelectorAll("li[data-i]").forEach(li => { li.onclick = () => pick(hits[+li.dataset.i]); });
};
function pick(h) {
  qres.classList.remove("on"); q.value = h.t; q.blur();
  if (h.course) { const c = COURSES.find(x => x.id === h.course); R.tab = c.type; setMode("run"); selectCourse(c.id); return; }
  map.setView([h.lat, h.lng], h.k === "동" ? 15 : 17);
  if (S.mode !== "walk") return;
  const sp = snap(h.lat, h.lng);
  L.popup({maxWidth: 240}).setLatLng([h.lat, h.lng]).setContent(`<div class="pop"><b>${esc(h.t)}</b><br><span style="color:#6b7280">${esc(h.s || "")}</span>
    <div class="btns"><button class="btn" data-pt="s">여기서 출발</button><button class="btn ghost" data-pt="e">여기로 도착</button></div></div>`).openOn(map);
  setTimeout(() => document.querySelectorAll(".pop [data-pt]").forEach(b => { b.onclick = () => { map.closePopup(); setPoint(b.dataset.pt, sp.i); }; }), 0);
}
document.addEventListener("click", e => { if (!$("search").contains(e.target)) qres.classList.remove("on"); });

/* ── 8. 모드 · 시트 ─────────────────────────────────────────── */
function setMode(m) {
  S.mode = m;
  document.querySelectorAll("#modes button").forEach(b => b.classList.toggle("on", b.dataset.mode === m));
  document.querySelectorAll("#tabbar [data-tab2]").forEach(b => b.classList.toggle("on", b.dataset.tab2 === m));
  if (m === "walk") { map.removeLayer(LY.run); LY.walk.addTo(map); renderWalk(); }
  else { map.removeLayer(LY.walk); LY.shops.clearLayers(); LY.run.addTo(map); drawRun(true); renderRun(); }
}
document.querySelectorAll("#modes button").forEach(b => { b.onclick = () => setMode(b.dataset.mode); });
// 아래 탭(휴대폰) — 밤길 · 러닝은 모드, 뱃지는 뱃지 창, 더보기는 메뉴
document.querySelectorAll("#tabbar [data-tab2]").forEach(b => {
  b.onclick = () => { const k = b.dataset.tab2; if (k === "walk" || k === "run") setMode(k); else if (k === "badge") showBadges(); else drawer(true); };
});
$("grab").onclick = () => {
  const s = $("sheet");
  if (s.classList.contains("tall")) { s.classList.remove("tall"); s.classList.add("mini"); }
  else if (s.classList.contains("mini")) s.classList.remove("mini");
  else s.classList.add("tall");
  placeFabs();
};
function placeFabs() {
  if (innerWidth >= 900) { $("fabs").style.bottom = ""; $("toast").style.bottom = ""; return; }
  const t = $("tabbar") ? $("tabbar").offsetHeight : 0, h = $("sheet").offsetHeight;   // 시트는 아래 탭 위에 놓인다(#31)
  document.documentElement.style.setProperty("--tabh", t + "px");
  $("fabs").style.bottom = (h + t + 12) + "px"; $("toast").style.bottom = (h + t + 70) + "px";
}
if (window.ResizeObserver) new ResizeObserver(placeFabs).observe($("sheet"));
addEventListener("resize", placeFabs);

$("built").textContent = `만든 날 ${M.built} · ${REAL ? "내부 시연판(실데이터)" : "시연판"}`;
if (REAL) {                                           // 실데이터 판(#32) — 위 표시 · 첫 실행 안내 아래 줄
  $("demoTag").textContent = `내부 시연 · 실데이터(${monthsTxt()})`;
  const f = document.querySelector("#ob .ob-foot"); if (f) f.textContent = "내부 시연판 · 통신 유동인구 실데이터 · 안산시 공식 서비스 아님";
  document.title = "안산 밤길 · 실데이터";
}
badgeCount();
homeName();
setMode("walk");
// 첫 실행 안내(#31) — 처음 한 번만
(function onboard() {
  const ob = $("ob"); if (!ob || store.get(KEY_OB, false)) return;
  ob.hidden = false;
  const done = () => { ob.hidden = true; store.set(KEY_OB, true); };
  $("obGo").onclick = () => { done(); locate(q => map.setView(q, Math.max(map.getZoom(), 15)), () => toast("위치를 받지 못했어요 · 지도에서 출발할 곳을 눌러도 돼요", 3600)); };
  $("obSkip").onclick = done;
})();
// 설치형 웹앱(#31) — 앱 파일을 저장해 인터넷이 끊겨도 열리게(지도 바탕은 저장하지 않음). https 또는 이 PC(localhost)에서만
if ("serviceWorker" in navigator && (location.protocol === "https:" || ["localhost", "127.0.0.1"].includes(location.hostname))) {
  const had = !!navigator.serviceWorker.controller;
  navigator.serviceWorker.register("sw.js").catch(() => { /* 저장 못 해도 앱은 그대로 */ });
  navigator.serviceWorker.addEventListener("controllerchange", () => { if (had && !window.__swReload) { window.__swReload = true; location.reload(); } });
}
addEventListener("offline", () => toast("인터넷이 끊겼어요 · 지도 바탕이 안 보일 수 있어요", 3600));
// 점검용(헤드리스 브라우저 시험) — 화면 동작과 같은 함수
window.APP = {frontier, choose, snap, dijkstra, stats, when, slotOf, setPoint, setMode, selectCourse, startRun, W, R, M, ll, COURSES,
              map, setBase, LY, accOn, cstats, nightSlot, goHome, showOpenShops, gradeOf};   // 점검 · 화면 예시 캡처용(#25 · #26 · #31)
})();
