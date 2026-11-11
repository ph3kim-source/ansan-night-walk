# -*- coding: utf-8 -*-
"""
시연 프로토타입의 계산 코어 — 화면(proto_app.py)은 여기 함수만 부르고 숫자를 만들지 않는다.

  시간대    28개 = 밤 기준 요일 7 × 시각 4(22·23·0·1)                        params.SLOT_NIGHT_OF
  활성도    min( 분위(유동), 분위(앵커) ),  유동 = max(분위(주민 보행), 분위(방문 결제))  params.FLOW_FORM
            분위는 28개 시간대를 합쳐서 매긴다                                   params.SLOT_PCT_POOL
            동점은 사전식(min → max)                                             params.ACT_TIEBREAK
  경로      α 격자의 경로를 한 번에 구하고 δ(우회 예산)마다 고른다                 params.ALPHA_GRID
            cost = 길이 × (1 + α × 어두움)  — route.py 와 같은 식, 탐색만 scipy 희소행렬

입력은 ingest_inventory.py 가 만든 data/proto/ 와 3안 본체의 cells/nodes/edges.csv 다.
점수는 100m 셀에서 매기고 보행 노드는 최근접 셀 값을 물려받는다(CLAUDE.md §3.5).
"""
import pathlib
import sys

import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix, coo_matrix
from scipy.sparse.csgraph import dijkstra, connected_components
from scipy.spatial import cKDTree

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import params as PM
import score as SC

DOW_KR = "월화수목금토일"
HOURS = [h for h in PM.NIGHT_HOURS.value]                      # [22, 23, 0, 1]
SLOTS = [(d, h) for d in range(7) for h in HOURS]


def slot_index(dow, hour):
    return dow * len(HOURS) + HOURS.index(hour)


def slot_label(i, long=False):
    d, h = SLOTS[i]
    if not long:
        return f"{DOW_KR[d]} {h:02d}시"
    if h < 12:                                                  # 0·1시는 다음날 달력 — 시민 혼동 방지
        return f"{DOW_KR[d]}요일 밤 {h}시 (달력상 {DOW_KR[(d + 1) % 7]}요일 {h:02d}:00)"
    return f"{DOW_KR[d]}요일 밤 {h}시"


# ══ 활성도 ═══════════════════════════════════════════════════════════
def _pct_min(a):
    """동점은 최솟값 순위 — 0 이 많은 항(결제 없음)이 평균 순위를 받아 올라가지 않게."""
    return pd.Series(np.ravel(a)).rank(method="min", pct=True).to_numpy().reshape(np.shape(a))


def _pct_avg(a):
    return pd.Series(np.ravel(a)).rank(method="average", pct=True).to_numpy().reshape(np.shape(a))


def activity(R, V, A_d):
    """(시간대, 셀) 활성도. R=주민 보행 · V=방문 결제 · A_d=문 연 앵커까지 거리(m). 28개 시간대를 합쳐 분위.

    반환 dict: act(0~1, 클수록 사람 많고 불 켜짐) · flow · anchor · lo(min) · who(min 을 정한 항)"""
    pR, pV = _pct_min(R), _pct_min(V)
    flow = _pct_avg(np.maximum(pR, pV))                         # 선언(OR) — 주민이 걷거나 방문객이 있거나
    anchor = _pct_avg(-A_d)
    lo, hi = np.minimum(flow, anchor), np.maximum(flow, anchor)   # 연언(AND) = min
    # 사전식 순위: min 이 같으면 max 가 큰 쪽이 밝다 (가중치 없음)
    order = np.lexsort((hi.ravel(), lo.ravel()))
    act = np.empty(order.size)
    act[order] = (np.arange(order.size) + 1) / order.size
    return {"act": act.reshape(lo.shape), "flow": flow, "anchor": anchor, "lo": lo,
            "flow_from_visit": pV > pR, "who": np.where(flow <= anchor, "유동", "앵커")}


def edge_activity(act_cells, node_cell, u, v):
    """(시간대, 간선) 활성도 = 양 끝 노드(= 최근접 셀)의 평균 — score.edge_score 와 같은 정의."""
    a = act_cells[:, node_cell]
    return (a[:, u] + a[:, v]) / 2


def dark_threshold(edge_act, length, q=None):
    """사람 드문 구간 임계 — 28개 시간대 × 간선을 합친 길이 가중 하위 q 분위(score.dark_threshold 와 같은 정의)."""
    q = PM.DARK_Q.value if q is None else q
    df = pd.DataFrame({"act": edge_act.ravel(), "len_m": np.tile(length, edge_act.shape[0])})
    return SC.dark_threshold(df, q)


# ══ 그래프 · 경로 ════════════════════════════════════════════════════
class NightGraph:
    """OSM 보행망. 간선 가중치 벡터만 바꿔 끼우면 scipy Dijkstra 한 번에 2~3ms."""

    def __init__(self, nodes, edges):
        self.n, self.m = len(nodes), len(edges)
        self.u = edges["u"].to_numpy(np.int64)
        self.v = edges["v"].to_numpy(np.int64)
        self.length = edges["len_m"].to_numpy(float)
        self.xy = nodes[["x", "y"]].to_numpy(float)
        self.lonlat = nodes[["lon", "lat"]].to_numpy(float)
        self.dong = nodes["dong"].to_numpy()
        self.cell = nodes["cell"].to_numpy(np.int64)
        rows = np.r_[self.u, self.v]
        cols = np.r_[self.v, self.u]
        eid = np.r_[np.arange(self.m), np.arange(self.m)]
        o = np.lexsort((cols, rows))
        self._cols, self._eid = cols[o].astype(np.int32), eid[o]
        self._indptr = np.r_[0, np.cumsum(np.bincount(rows, minlength=self.n))].astype(np.int32)
        key = np.minimum(self.u, self.v) * self.n + np.maximum(self.u, self.v)
        self._ko = np.argsort(key)
        self._ks = key[self._ko]
        self.tree = cKDTree(self.xy)
        self.mid = (self.xy[self.u] + self.xy[self.v]) / 2

    def _mat(self, w):
        return csr_matrix((w[self._eid], self._cols, self._indptr), shape=(self.n, self.n))

    def edge_ids(self, path):
        a, b = np.asarray(path[:-1]), np.asarray(path[1:])
        key = np.minimum(a, b) * self.n + np.maximum(a, b)
        return self._ko[np.searchsorted(self._ks, key)]

    def snap(self, x, y):
        return int(self.tree.query([x, y])[1])

    def sssp(self, s, w, limit=np.inf):
        return dijkstra(self._mat(w), directed=True, indices=int(s), return_predecessors=True, limit=limit)

    @staticmethod
    def walk_back(pred, s, t):
        if t != s and pred[t] < 0:
            return None
        p = [int(t)]
        while p[-1] != s:
            p.append(int(pred[p[-1]]))
        return p[::-1]

    def path(self, s, t, w, limit=np.inf):
        _, pred = self.sssp(s, w, limit)
        return self.walk_back(pred, s, t)

    # ── 경로 요약 ─────────────────────────────────────────────
    def stats(self, e, act_e, thr):
        L = self.length[e]
        dk = act_e[e] < thr
        worst = run = 0.0
        for li, di in zip(L, dk):
            run = run + li if di else 0.0
            worst = max(worst, run)
        return {"len_m": float(L.sum()), "dark_m": float(L[dk].sum()), "worst_run_m": float(worst)}

    def frontier(self, s, t, act_e, thr, alphas=None):
        """α 격자마다 경로 하나 → 서로 다른 경로만 남긴 목록(길이순). [0] 이 최단경로."""
        alphas = PM.ALPHA_GRID.value if alphas is None else alphas
        dark = 1.0 - act_e
        base = self.path(s, t, self.length)
        if base is None:
            return []
        be = self.edge_ids(base) if len(base) > 1 else np.array([], dtype=np.int64)
        out, seen = [], set()
        for a in alphas:
            if a == 0:
                p, e = base, be
            else:
                w = self.length * (1 + a * dark)
                lim = float(w[be].sum()) * (1 + 1e-9) + 1e-6       # 최단경로의 α 비용이 상한 → 탐색 범위 절약
                p = self.path(s, t, w, lim)
                if p is None:
                    continue
                e = self.edge_ids(p) if len(p) > 1 else np.array([], dtype=np.int64)
            k = e.tobytes()
            if k in seen:
                continue
            seen.add(k)
            out.append({"alpha": float(a), "path": p, "edges": e, **self.stats(e, act_e, thr)})
        out.sort(key=lambda r: (r["len_m"], r["dark_m"]))
        return out

    @staticmethod
    def choose(front, detour):
        """우회 예산 δ 안에서 사람 드문 구간이 가장 짧은 경로(동률이면 최장 연속 → 거리)."""
        if not front:
            return None
        budget = front[0]["len_m"] * (1 + detour) + 1e-6
        ok = [r for r in front if r["len_m"] <= budget]
        return min(ok, key=lambda r: (r["dark_m"], r["worst_run_m"], r["len_m"]))

    @staticmethod
    def pareto(front):
        """'+N분 ↔ 사람 드문 구간' 곡선 — 더 길면서 더 어둡지도 않은 경로는 뺀다."""
        out, best = [], np.inf
        for r in sorted(front, key=lambda r: (r["len_m"], r["dark_m"])):
            if r["dark_m"] < best - 1e-6:
                out.append(r)
                best = r["dark_m"]
        return out

    def profile(self, e, act_e, thr):
        """경로를 따라 간 거리별 활성도 — 화면의 '밝기 프로파일'."""
        L = self.length[e]
        x1 = np.cumsum(L)
        return pd.DataFrame({"from_m": x1 - L, "to_m": x1, "act": act_e[e], "dark": act_e[e] < thr,
                             "len_m": L})

    def segments_lonlat(self, path):
        return self.lonlat[np.asarray(path)].tolist()


# ══ 경로 주변의 '문 연 가게' ═════════════════════════════════════════
def anchors_along(G, path, blocks_xy, active, radius=None):
    """경로 노드 반경 내 활성 앵커 블록 → (블록 행번호, 출발 후 m, 경로까지 m)."""
    radius = PM.ANCHOR_R_M.value if radius is None else radius
    idx = np.flatnonzero(active)
    if not len(idx) or len(path) < 2:
        return pd.DataFrame(columns=["block", "at_m", "off_m"])
    e = G.edge_ids(path)
    cum = np.r_[0, np.cumsum(G.length[e])]
    pts = G.xy[np.asarray(path)]
    d, j = cKDTree(pts).query(blocks_xy[idx], distance_upper_bound=radius)
    ok = np.isfinite(d)
    return (pd.DataFrame({"block": idx[ok], "at_m": cum[j[ok]], "off_m": d[ok]})
            .sort_values("at_m").reset_index(drop=True))


# ══ 담당자 화면 ══════════════════════════════════════════════════════
def near_count(G, pts_xy, radius):
    """간선 중점 반경 radius 안의 점 개수 (보안등·CCTV)."""
    if not len(pts_xy):
        return np.zeros(G.m, dtype=int)
    t = cKDTree(pts_xy)
    return np.array([len(x) for x in t.query_ball_point(G.mid, radius)])


def segments(G, mask, min_len=None):
    """mask 간선끼리 이어진 덩어리 = '구간'. 반환: (간선별 구간번호 −1=없음, 구간 표)."""
    min_len = PM.SEG_MIN_M.value if min_len is None else min_len
    ids = np.flatnonzero(mask)
    lab_e = np.full(G.m, -1)
    if not len(ids):
        return lab_e, pd.DataFrame(columns=["seg", "len_m", "n_edges", "x", "y", "dong"])
    a = coo_matrix((np.ones(len(ids)), (G.u[ids], G.v[ids])), shape=(G.n, G.n))
    _, lab = connected_components(a, directed=False)
    seg = lab[G.u[ids]]
    df = pd.DataFrame({"e": ids, "seg": seg, "len_m": G.length[ids],
                       "x": G.mid[ids, 0], "y": G.mid[ids, 1], "dong": G.dong[G.u[ids]]})
    t = df.groupby("seg").agg(len_m=("len_m", "sum"), n_edges=("e", "size"), x=("x", "mean"),
                              y=("y", "mean"), dong=("dong", lambda s: s.mode().iat[0])).reset_index()
    t = t[t["len_m"] >= min_len].sort_values("len_m", ascending=False).reset_index(drop=True)
    keep = set(t["seg"])
    lab_e[ids] = np.where(np.isin(seg, list(keep)), seg, -1)
    return lab_e, t


def trip_usage(inc, w_slot):
    """귀가 통행 표본(K) × 간선 사건행렬 · 시간대 가중치 → 간선별 통행량(상대값)."""
    return np.asarray(inc.T @ w_slot).ravel()


# ══ 귀가 통행 표본 (ingest 단계에서 한 번) ═══════════════════════════════
def build_trips(G, cells, od, terms, cell_res_share, log=print):
    """동 OD(밤·도보·귀가) → 출발·도착 셀 표본 → 최단경로 사건행렬.

    출발: 출발 동 안에서 방문 결제(V) 많은 셀 (밤에 사람들이 머물던 곳)
    도착: 도착 동 안에서 거주 비중 큰 셀 (DS-082)
    """
    cfg = PM.OD_SAMPLE.value
    rng = np.random.default_rng(cfg["seed"])
    maxd = PM.WALK_TRIP_MAX_M.value
    dong_names = sorted(cells["dong"].unique())
    di = {d: i for i, d in enumerate(dong_names)}
    cdong = cells["dong"].map(di).to_numpy()
    cxy = cells[["x", "y"]].to_numpy()
    V_mean = terms["V"].mean(axis=0)
    pair = od.groupby(["o_dong", "d_dong"])["trips"].sum()
    pair = pair[pair > 0]
    o_tot = pair.groupby(level=0).sum()
    o_tot = o_tot[o_tot.index.isin(di)]
    cell_node = G.tree.query(cxy)[1]

    def pick_cell(dong, weight):
        idx = np.flatnonzero(cdong == di[dong])
        w = weight[idx]
        w = w / w.sum() if w.sum() > 0 else None
        return int(rng.choice(idx, p=w))

    trips = []
    origins = rng.choice(o_tot.index.to_numpy(), cfg["origins"], p=(o_tot / o_tot.sum()).to_numpy())
    for od_ in origins:
        oc = pick_cell(od_, V_mean)
        dests = pair.loc[od_]
        dests = dests[dests.index.isin(di)]
        got = 0
        for _ in range(cfg["per_origin"] * 6):
            if got >= cfg["per_origin"]:
                break
            dd = rng.choice(dests.index.to_numpy(), p=(dests / dests.sum()).to_numpy())
            dc = pick_cell(dd, cell_res_share)
            if np.hypot(*(cxy[oc] - cxy[dc])) > maxd or oc == dc:
                continue
            trips.append((od_, dd, oc, dc))
            got += 1
    T = pd.DataFrame(trips, columns=["o_dong", "d_dong", "o_cell", "d_cell"])
    T["o_node"], T["d_node"] = cell_node[T["o_cell"]], cell_node[T["d_cell"]]
    T = T[T["o_node"] != T["d_node"]].reset_index(drop=True)

    rows, cols, lens = [], [], []
    for o_node, g in T.groupby("o_node"):
        _, pred = G.sssp(o_node, G.length, limit=maxd * 2.5)
        for k, d_node in zip(g.index, g["d_node"]):
            p = G.walk_back(pred, o_node, d_node)
            if p is None or len(p) < 2:
                lens.append((k, np.nan))
                continue
            e = G.edge_ids(p)
            rows.append(np.full(len(e), k))
            cols.append(e)
            lens.append((k, float(G.length[e].sum())))
    T["len_m"] = pd.Series(dict(lens))
    ok = T["len_m"].notna().to_numpy()
    inc = csr_matrix((np.ones(sum(len(c) for c in cols)), (np.concatenate(rows), np.concatenate(cols))),
                     shape=(len(T), G.m))
    # 시간대 가중치: 그 동 쌍의 밤 도보 귀가 통행 / 그 쌍에서 뽑은 표본 수
    n_pair = T.groupby(["o_dong", "d_dong"]).size()
    W = np.zeros((len(T), len(SLOTS)))
    odx = od.set_index(["o_dong", "d_dong", "slot"])["trips"]
    for k, r in T.iterrows():
        cnt = n_pair[(r.o_dong, r.d_dong)]
        for s_ in range(len(SLOTS)):
            W[k, s_] = odx.get((r.o_dong, r.d_dong, s_), 0.0) / cnt
    W[~ok] = 0
    log(f"    귀가 통행 표본 {len(T):,}건 (경로 {ok.sum():,}) · 출발 {T.o_node.nunique():,}곳 · "
        f"평균 {np.nanmean(T.len_m):,.0f}m · 사건행렬 nnz {inc.nnz:,}")
    return T, inc, W
