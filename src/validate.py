# -*- coding: utf-8 -*-
"""
근거 산출 — 문서에 적힌 숫자를 전부 여기서 다시 만든다.
실행:  python src/validate.py
출력:  data/processed/evidence.json

원칙: 인벤토리 엑셀을 직접 읽어 제약을 산출한다. '규격서에 그렇게 적혀 있다'를
      사람이 옮겨 적지 않는다. 인벤토리가 갱신되면 숫자도 같이 바뀌어야 한다.
"""
import json, pathlib, sys, time
import numpy as np
import pandas as pd
import networkx as nx

ROOT = pathlib.Path(__file__).resolve().parent.parent
P = ROOT / "data" / "processed"
# 인벤토리 파일명이 한 번 바뀐 적이 있다(.backup.xlsx -> .xlsx). 둘 다 받는다
_INV_DIR = ROOT.parent / "data"
INV = next((_INV_DIR / n for n in
            ("안산시_민간데이터_데이터셋_인벤토리_v1.0.xlsx",
             "안산시_민간데이터_데이터셋_인벤토리_v1.0.backup.xlsx")
            if (_INV_DIR / n).exists()),
           _INV_DIR / "안산시_민간데이터_데이터셋_인벤토리_v1.0.xlsx")
BASE = ROOT / "data" / "base"
sys.path.insert(0, str(ROOT / "src"))
import params as PM, score as SC, route as RT

E = {}


def log(m):
    print(m, flush=True)


# 1. 인벤토리에서 직접 산출하는 제약
def e_inventory():
    d = pd.read_excel(INV, sheet_name="02_데이터셋_인벤토리")
    cd = pd.read_excel(INV, sheet_name="03_컬럼사전")
    use = ["DS-014", "DS-024", "DS-032", "DS-033", "DS-047", "DS-048",
           "DS-049", "DS-052", "DS-053", "DS-054", "DS-017", "DS-082"]
    t = d[d["인벤ID"].isin(use)][
        ["인벤ID", "테이블명(영문)", "공간단위", "시간해상도", "대민개방",
         "보유기간", "총용량(GB)", "총행수(실측/추정)"]]
    E["datasets"] = t.to_dict("records")

    # 심야(22~02시)를 정확히 자를 수 있는 테이블만 고른다
    h = cd[(cd["컬럼명(원문)"].astype(str).str.lower().isin(["hour", "time_cd", "timezn_cd"]))
           & (cd["인벤ID"].isin(use))][["인벤ID", "컬럼명(원문)", "코드값/참고사항"]]
    h.columns = ["ds", "col", "code"]
    ok, ng = [], []
    for r in h.itertuples():
        s = str(r.code)
        rec = {"ds": r.ds, "col": r.col, "code": s[:70]}
        (ok if ("0~23" in s or "00 : 00:00" in s or "00 ~ 23" in s) else ng).append(rec)
    E["hour_ok"], E["hour_ng"] = ok, ng
    log(f"[인벤토리] 대상 {len(t)}종 · 심야 절단 가능 {len(ok)}종 / 불가 {len(ng)}종")
    for r in ng:
        log(f"           불가 {r['ds']} {r['col']}={r['code'][:40]}")

    fine = t[t["공간단위"].astype(str).str.contains("셀|블록|클러스터")]
    E["fine_total"] = int(len(fine))
    E["fine_open"] = int((fine["대민개방"] == "O").sum())
    E["fine_open_ids"] = fine.loc[fine["대민개방"] == "O", "인벤ID"].tolist()
    log(f"[인벤토리] 블록·셀 단위 {E['fine_total']}종 중 대민개방 {E['fine_open']}종 "
        f"{E['fine_open_ids']}")

    # 심야 절단 가능 + 100m급 공간 + 대민개방 을 동시에 만족하는 것
    okids = {r["ds"] for r in ok}
    both = fine[fine["인벤ID"].isin(okids)]
    E["fine_hour_ok"] = both["인벤ID"].tolist()
    E["fine_hour_ok_open"] = both.loc[both["대민개방"] == "O", "인벤ID"].tolist()
    log(f"[인벤토리] 100m급 + 심야절단 가능 = {E['fine_hour_ok']} · "
        f"그중 대민개방 = {E['fine_hour_ok_open'] or '없음'}")


# 2. 공간 정의
def e_exclude():
    import geopandas as gpd
    g = gpd.read_file(BASE / "grid_1km.geojson")
    g.columns = ["GRID_CD", "ADM_CD", "ADM_NM", "인구", "제조업종사자", "geometry"]
    g = g[g["인구"] > 0]
    db = g[g["ADM_NM"].isin(PM.EXCLUDE_DONG.value)]
    E["grid_all"], E["grid_db"] = int(len(g)), int(len(db))
    E["pop_all"], E["pop_db"] = int(g["인구"].sum()), int(db["인구"].sum())
    log(f"[제외] 인구>0 격자 {E['grid_all']}개 중 대부동 {E['grid_db']}개"
        f"({E['grid_db']/E['grid_all']:.0%}) · 인구 {E['pop_db']:,}명"
        f"({E['pop_db']/E['pop_all']:.1%})")


# 3. 업종 필터의 필요성
def e_nightlife():
    a = pd.read_csv(P / "anchors.csv", encoding="utf-8-sig")
    n = a.groupby("kind").size()
    E["anchor_n"], E["nightlife_n"] = int(n.get("앵커", 0)), int(n.get("유흥", 0))
    E["nightlife_ratio"] = round(E["nightlife_n"] / max(E["anchor_n"], 1), 2)
    E["biz_breakdown"] = {f"{k}|{b}": int(v) for (k, b), v
                          in a.groupby(["kind", "biz"]).size().sort_values(ascending=False).items()}
    log(f"[업종] 심야앵커 {E['anchor_n']:,} vs 유흥 {E['nightlife_n']:,} = "
        f"{E['nightlife_ratio']}배. 업종 필터 없이 결제 가맹점 수를 세면 유흥가가 1위가 된다")


# 4. 가중합의 불안정 (기획 원안 재현)
def e_sensitivity(c, n, e, pairs, curve_pairs):
    """기획 원안의 가중합을 그대로 재현해 가중치가 결과를 지배하는지 본다.
    점수는 셀에서 매기고 노드(n)가 물려받는다."""
    cell = n["cell"].to_numpy()
    f = SC.pct(c["pop_night"])
    a = SC.pct(-c["anchor_d"])
    res = {}
    for w in [0.25, 0.5, 1.0, 2.0, 4.0]:
        act = ((f + w * a) / (1 + w))[cell]
        ee = SC.edge_score(n, e, act)
        thr = SC.dark_threshold(ee, PM.DARK_Q.value)
        g = RT.build(n, ee)
        res[w] = [frozenset(map(frozenset, zip(p[:-1], p[1:])))
                  for p in (RT.plan(g, s, t, PM.DETOUR.value, thr)["path"] for s, t in pairs)]

    def jac(A, B):
        return len(A & B) / max(len(A | B), 1)

    sims = [jac(x, y) for x, y in zip(res[0.25], res[4.0])]
    E["w_jaccard_mean"] = round(float(np.mean(sims)), 3)
    E["w_changed_pct"] = round(float(np.mean([s < 0.999 for s in sims])) * 100, 1)
    log(f"[민감도] 가중합 w=0.25 vs w=4 : 경로 간선 일치도 {E['w_jaccard_mean']:.0%} · "
        f"{E['w_changed_pct']:.0f}%의 쌍에서 경로가 바뀜 -> 가중치가 결과를 지배한다")

    act = SC.cell_score(c)[0][cell]
    ee = SC.edge_score(n, e, act)
    thr = SC.dark_threshold(ee, PM.DARK_Q.value)
    g = RT.build(n, ee)
    curve = []
    for d in [0.0, 0.1, 0.2, 0.4]:
        r = [RT.plan(g, s, t, d, thr) for s, t in curve_pairs]
        curve.append({"detour": d,
                      "dark_m": round(float(np.mean([x["best"]["dark_m"] for x in r]))),
                      "len_m": round(float(np.mean([x["best"]["len_m"] for x in r]))),
                      "pairs_with_dark": int(sum(x["best"]["dark_m"] > 0 for x in r))})
    E["detour_curve"] = curve
    log(f"[민감도] 우회예산 반응 ({len(curve_pairs)}쌍 평균): " + " -> ".join(
        f"d{x['detour']:.0%} 저활성{x['dark_m']}m/거리{x['len_m']}m/저활성쌍{x['pairs_with_dark']}"
        for x in curve))
    return thr, g


# 5. 경로 품질
def e_route(G, thr, pairs):
    t0 = time.time()
    R = [RT.plan(G, s, t, PM.DETOUR.value, thr) for s, t in pairs]
    E["route_sec_per_pair"] = round((time.time() - t0) / len(R), 3)
    b = pd.DataFrame([{"L0": r["base"]["len_m"], "D0": r["base"]["dark_m"],
                       "W0": r["base"]["worst_run_m"], "L1": r["best"]["len_m"],
                       "D1": r["best"]["dark_m"], "W1": r["best"]["worst_run_m"],
                       "a": r["alpha"]} for r in R])
    m = b[b.D0 > 0]
    E["pairs"] = int(len(b))
    E["pairs_with_dark"] = int(len(m))
    E["dark_before_m"] = round(float(m.D0.mean()), 1)
    E["dark_after_m"] = round(float(m.D1.mean()), 1)
    E["dark_cut_pct"] = round((1 - m.D1.mean() / m.D0.mean()) * 100, 1)
    E["worst_before_m"] = round(float(m.W0.mean()), 1)
    E["worst_after_m"] = round(float(m.W1.mean()), 1)
    E["extra_pct"] = round(float((m.L1 / m.L0 - 1).mean()) * 100, 1)
    E["alpha_saturated_pct"] = round(float((b.a >= PM.ALPHA_MAX.value * .999).mean()) * 100, 1)
    log(f"[경로] {E['pairs']}쌍 중 최단경로에 저활성 구간이 있는 쌍 {E['pairs_with_dark']}쌍 · "
        f"노출 {E['dark_before_m']:.0f}m->{E['dark_after_m']:.0f}m({E['dark_cut_pct']:.0f}%감소) · "
        f"최장연속 {E['worst_before_m']:.0f}m->{E['worst_after_m']:.0f}m · "
        f"거리 +{E['extra_pct']:.1f}%")
    log(f"[경로] 우회예산을 다 못 쓴 쌍 {E['alpha_saturated_pct']:.0f}%")


# 6. 그래프 상태
def e_graph(G):
    comp = list(nx.connected_components(G))
    big = max(comp, key=len)
    E["nodes"], E["edges_n"] = G.number_of_nodes(), G.number_of_edges()
    E["components"] = len(comp)
    E["giant_pct"] = round(len(big) / G.number_of_nodes() * 100, 1)
    log(f"[그래프] 노드 {E['nodes']:,} 간선 {E['edges_n']:,} · 연결요소 {E['components']:,}개 · "
        f"최대요소가 전체의 {E['giant_pct']:.0f}%")
    return sorted(big)


if __name__ == "__main__":
    e_inventory()
    e_exclude()
    e_nightlife()

    c = pd.read_csv(P / "cells.csv", encoding="utf-8-sig")      # 점수 격자 100m
    n = pd.read_csv(P / "nodes.csv", encoding="utf-8-sig")      # 그래프 노드 (OSM 보행망)
    e = pd.read_csv(P / "edges.csv")
    # 분위는 100m 셀에서 매기고 노드가 물려받는다. 노드로 매기면 교차로 밀집 지역이
    # 과대표집돼 분위의 의미가 달라진다
    act_cell, _, _ = SC.cell_score(c)
    act = act_cell[n["cell"].to_numpy()]
    G0 = RT.build(n, SC.edge_score(n, e, act))
    big = e_graph(G0)

    rng = np.random.default_rng(7)
    pairs = []
    while len(pairs) < 120:
        s, t = [int(x) for x in rng.choice(big, 2, replace=False)]
        if 800 < np.hypot(n.x[s] - n.x[t], n.y[s] - n.y[t]) < 4000:
            pairs.append((s, t))
    E["pair_seed"], E["pair_range_m"] = 7, [800, 4000]

    thr, G = e_sensitivity(c, n, e, pairs[:40], pairs)
    E["dark_threshold"] = round(thr, 4)
    e_route(G, thr, pairs)

    (P / "evidence.json").write_text(
        json.dumps(E, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    log(f"\n[v] evidence.json ({len(E)}개 항목)")
