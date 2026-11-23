# -*- coding: utf-8 -*-
"""
공개 실데이터 근거 산출 — 문서에 적는 공개 실데이터 수치를 전부 여기서 다시 만든다 (수정사항 #15)
실행:  python src/public_data.py        # 정제 (먼저)
       python src/validate_public.py    # → data/public/evidence_public.json
       python src/gen_docs.py           # 근거대장에 반영

validate.py(본체 근거)와 따로 둔 이유: validate.py 는 자기 코드까지 지문에 넣어 해상도 실험(#13, 40분) 결과를 옮겨 두는데,
그 파일을 고치면 지문이 바뀌어 실험 결과가 버려진다. 본체 수치(19.7% 등)는 이 파일과 무관하다.

산출
  lights       보안등 행 수 · 고유 위치 · 동별 · 좌표 → 보행망 거리
  partial      CCTV · 비상벨 공개분이 일부라는 근거(경기 시군 중 정확히 500행인 기관 수 · 안산분의 동 편중)
  crosstab     ★ 본체 활성도(실데이터 — SGIS 1km 인구 · 상가 · OSM 보행망) × 보안등(실데이터) — 골목 기준
  stations     역별 밤 하차(하루 평균) · 산업단지역
  station_walk 밤 역 귀갓길 흐름이 지나는 골목 중 보안등 없는 곳 + STATION_WALK_MAX_M 민감도(1.0 · 1.5 · 2.0km)
  korail_cols  칸 정의(시작 시각 기준) 근거
  sunset       월별 해 지는 시각 · 어두워지는 시각 · 밤 10시가 해 진 뒤 몇 시간인가
"""
import json
import pathlib
import sys

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parent.parent
P = ROOT / "data" / "processed"
PUB = ROOT / "data" / "public"
DER = PUB / "derived"
sys.path.insert(0, str(ROOT / "src"))
import params as PM, score as SC, alloc as AL, night_core as NC, public_data as PD  # noqa: E401,E402

E = {}


def log(m):
    print(m, flush=True)


def km(x):
    return round(float(x) / 1000, 1)


def segs(G, mask, val):
    """mask 간선 덩어리(구간) → 값 합 순위. val = 간선별 사람·m."""
    lab, seg = NC.segments(G, mask)
    if seg.empty:
        return seg, lab
    s = pd.Series(val).groupby(lab).sum()
    seg["pm"] = seg["seg"].map(s).fillna(0)
    return seg.sort_values("pm", ascending=False).reset_index(drop=True), lab


def main():
    rep = json.loads((DER / "report.json").read_text(encoding="utf-8"))
    man = rep.get("_meta", {}).get("manifest", {})
    nodes = pd.read_csv(P / "nodes.csv", encoding="utf-8-sig")
    edges = pd.read_csv(P / "edges.csv")
    cells = pd.read_csv(P / "cells.csv", encoding="utf-8-sig")
    ep = pd.read_csv(DER / "edge_public.csv", encoding="utf-8-sig")
    st = pd.read_csv(DER / "stations.csv", encoding="utf-8-sig")
    assert len(ep) == len(edges), "edge_public.csv 가 edges.csv 와 행 수가 다르다 — public_data.py 를 다시 돌릴 것"
    G = NC.NightGraph(nodes, edges)
    L = G.length
    major = ep["major"].to_numpy(bool)
    minor = ~major
    lit = ep["lights_n"].to_numpy() > 0

    # ── 보안등 · 일부 공개 자료 ──
    E["lights"] = {k: rep[k] for k in ("lights", "lights_by_dong", "light_dist", "light_spacing", "light_cover")}
    gg = {k: v for k, v in man.items() if "gyeonggi_rows_by_institution" in v}
    E["partial"] = {}
    for name, m in gg.items():
        d = m["gyeonggi_rows_by_institution"]
        E["partial"][name] = {"gyeonggi_institutions": len(d), "exactly_500": sum(v == 500 for v in d.values()),
                              "ansan_rows": m.get("rows"), "national_rows": m.get("national_rows")}
    for k in ("CCTV_partial", "비상벨_partial"):
        if k in rep:
            E["partial"][k] = rep[k]
    log(f"[일부 공개] {E['partial']}")

    # ── ★ 본체 활성도(실데이터) × 보안등(실데이터) — 골목만 ──
    cells["flow"] = AL.flow(cells)                                   # POP_ALLOC 기본 uniform = 본체와 같은 점수
    act = SC.cell_score(cells, flow_col="flow")[0][nodes["cell"].to_numpy()]
    ee = SC.edge_score(nodes, edges, act)
    thr = SC.dark_threshold(ee, PM.DARK_Q.value)
    dark = ee["act"].to_numpy() < thr
    ct = {}
    for nm, m in (("lit_busy", minor & lit & ~dark), ("lit_dark", minor & lit & dark),
                  ("unlit_dark", minor & ~lit & dark), ("unlit_busy", minor & ~lit & ~dark)):
        ct[nm] = km(L[m].sum())
    ct["minor_km"], ct["major_km"] = km(L[minor].sum()), km(L[major].sum())
    ct["lit_dark_share_of_lit"] = round(float(L[minor & lit & dark].sum() / L[minor & lit].sum()) * 100, 1)
    ct["dark_share_minor"] = round(float(L[minor & dark].sum() / L[minor].sum()) * 100, 1)
    ct["dark_share_major"] = round(float(L[major & dark].sum() / L[major].sum()) * 100, 1)
    ct["threshold"] = round(float(thr), 4)
    seg, _ = segs(G, minor & lit & dark, L)
    ct["lit_dark_segments_100m"] = int(len(seg))
    ct["lit_dark_by_dong_km"] = (pd.Series(L[minor & lit & dark], index=G.dong[G.u[minor & lit & dark]])
                                 .groupby(level=0).sum().div(1000).round(1).sort_values(ascending=False).head(8).to_dict())
    E["crosstab"] = ct
    log(f"[대조] 골목 {ct['minor_km']}km · 보안등 있음 & 사람 드묾 {ct['lit_dark']}km(보안등 있는 골목의 "
        f"{ct['lit_dark_share_of_lit']}%) · 보안등 없음 & 사람 드묾 {ct['unlit_dark']}km · 구간 {ct['lit_dark_segments_100m']}곳")

    # ── 역 · 밤 하차 ──
    E["korail_cols"] = rep["korail_cols"]
    E["stations"] = {
        "month": st["month"].iloc[0],
        "night_total": round(float(st["night"].sum())),
        "industrial": rep["industrial"],
        "table": st[["station", "line", "dong", "a22", "a23", "a24", "night", "a_day", "pop_r", "mfg_r", "industrial",
                     "mean_walk_m"]].assign(**{c: lambda d, c=c: d[c].round(1) for c in
                                               ["a22", "a23", "a24", "night", "a_day", "pop_r", "mfg_r", "mean_walk_m"]})
                     .sort_values("night", ascending=False).to_dict("records"),
    }
    log(f"[역] {E['stations']['month']} 밤 하차 하루 {E['stations']['night_total']:,}명 · 산업단지역 {rep['industrial']['역']}")

    # ── 밤 역 귀갓길 × 보안등 없는 골목 블록 + 민감도 ──
    # 단위 = 블록(교차로 사이 사슬, NightGraph.links). 처음엔 연결된 간선 덩어리(NC.segments)로 셌는데
    # 보안등 없는 골목이 그물처럼 이어져 1위가 6.8km 한 덩어리가 됐다 — 담당자가 쓸 단위가 아니라 바꿨다(#15)
    lk = G.links()
    home = st[~st["industrial"].astype(bool)]
    out, tops = {}, {}
    w = AL.homes(cells)
    N = PM.PRIORITY_TOP_N.value
    for mx in (1000, 1500, 2000):
        F, use = PD.station_walk(nodes, edges, cells, st.drop(columns=["node", "cells", "homes_w", "mean_walk_m"],
                                                                errors="ignore"), max_m=mx, w=w)
        pm = F.sum(axis=0) * L
        t = pd.DataFrame({"lk": lk, "len": L, "pm": pm, "gap": minor & ~lit, "dk": L * dark,
                          "x": G.mid[:, 0], "y": G.mid[:, 1], "dong": G.dong[G.u]})
        g = t.groupby("lk")
        bl = pd.DataFrame({"len_m": g["len"].sum(), "pm": g["pm"].sum(), "gap": g["gap"].all(),
                           "dark_m": g["dk"].sum(), "x": g["x"].mean(), "y": g["y"].mean(), "dong": g["dong"].first()})
        cand = bl[bl["gap"] & (bl["pm"] > 0)].sort_values("pm", ascending=False)
        dk = cand["dark_m"] > cand["len_m"] / 2                        # 블록의 과반이 저활성(본체 기준)
        top = cand.head(N)
        tops[mx] = set(top.index)
        dd = np.hypot(top["x"].to_numpy()[:, None] - home["x"].to_numpy()[None, :],
                      top["y"].to_numpy()[:, None] - home["y"].to_numpy()[None, :])
        out[mx] = {"assigned_per_night": round(float(use[["a22", "a23", "a24"]].sum().sum())),
                   "unlit_minor_share_pm": round(float(pm[minor & ~lit].sum() / pm.sum()) * 100, 1),
                   "major_share_pm": round(float(pm[major].sum() / pm.sum()) * 100, 1),
                   "lit_minor_share_pm": round(float(pm[minor & lit].sum() / pm.sum()) * 100, 1),
                   "blocks": int(len(cand)), "blocks_dark": int(dk.sum()),
                   "pm_share_blocks_dark": round(float(cand.loc[dk, "pm"].sum() / pm.sum()) * 100, 1),
                   "top": [{"rank": i + 1, "dong": r.dong, "len_m": round(r.len_m),
                            "index": round(100 * r.pm / top["pm"].iloc[0]),
                            "dark_main": round(r.dark_m / r.len_m * 100),
                            "station": home["station"].iloc[int(dd[i].argmin())],
                            "station_m": round(float(dd[i].min()), -1)}
                           for i, r in enumerate(top.itertuples())],
                   "top_dark": [{"rank": i + 1, "dong": r.dong, "len_m": round(r.len_m),
                                 "index": round(100 * r.pm / cand.loc[dk, "pm"].iloc[0])}
                                for i, r in enumerate(cand[dk].head(N).itertuples())] if dk.any() else []}
    base = tops[PM.STATION_WALK_MAX_M.value]
    for mx in out:
        out[mx]["top_overlap_vs_default"] = round(len(tops[mx] & base) / max(len(tops[mx] | base), 1), 3)
    E["station_walk"] = {"default_max_m": PM.STATION_WALK_MAX_M.value, "unit": "블록(교차로 사이)", "runs": out}
    d = out[PM.STATION_WALK_MAX_M.value]
    log(f"[귀갓길] 배정 {d['assigned_per_night']:,}명/밤 · 사람·m 중 보안등 없는 골목 {d['unlit_minor_share_pm']}% · "
        f"큰길 {d['major_share_pm']}% · 보안등 골목 {d['lit_minor_share_pm']}% · 보안등 없는 골목 블록 {d['blocks']}곳 "
        f"(그중 본체 기준 저활성 {d['blocks_dark']}곳 · 사람·m {d['pm_share_blocks_dark']}%) · 상위 {N}곳 평균 길이 "
        f"{np.mean([r['len_m'] for r in d['top']]):.0f}m · 민감도(상위 {N}곳 일치) " +
        " · ".join(f"{mx}m {out[mx]['top_overlap_vs_default']:.0%}" for mx in out))

    # ── 해 지는 시각 ──
    E["sunset"] = rep["_sunset"]
    t = {r["month"]: r for r in E["sunset"]["table"]}
    log(f"[해] 6월 {t[6]['sunset']}(밤 10시 = 해 진 뒤 {t[6]['h22_after_sunset']}시간) · "
        f"12월 {t[12]['sunset']}(밤 10시 = {t[12]['h22_after_sunset']}시간 뒤) · 12월 어두워지는 시각 {t[12]['dusk']}")
    E["police"] = rep["police"]

    (PUB / "evidence_public.json").write_text(json.dumps(E, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    log(f"\n[v] {PUB / 'evidence_public.json'} ({len(E)}개 항목)")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
