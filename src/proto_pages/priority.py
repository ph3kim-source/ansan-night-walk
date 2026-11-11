# -*- coding: utf-8 -*-
"""담당자 · 개선 우선 구간 — 많은 밤 귀갓길이 지나는 사람 드문 구간. 우회로 풀리는가, 시설 개선이 필요한가."""
import numpy as np
import pandas as pd
import streamlit as st
from pyproj import Transformer

import night_core as NC
import params as PM
import proto_ui as UI

W = UI.world()
G = W.G
S = UI.current_slot()
N = PM.PRIORITY_TOP_N.value

st.title("개선이 필요한 구간")
st.caption(f"{UI.when(S)} · 밤 귀갓길이 많이 지나는데 사람이 드문 구간")
UI.notice(formal=True)

use = NC.trip_usage(W.inc, W.W[:, S])
dark = W.eact[S] < W.thr
lab_e, seg = NC.segments(G, dark & (use > 0))
if seg.empty:
    st.info("이 시간에는 해당하는 구간이 없습니다.")
    st.stop()
df = pd.DataFrame({"seg": lab_e, "score": use * G.length, "lit": W.lit})
agg = df[df.seg >= 0].groupby("seg").agg(score=("score", "sum"), lit=("lit", "sum"))
n_seg = len(seg)
seg = seg.join(agg, on="seg").sort_values("score", ascending=False).reset_index(drop=True).head(N)
seg["지수"] = (100 * seg["score"] / seg["score"].max()).round().astype(int)
seg["검토 방향"] = np.where(seg["lit"] > 0, "심야 편의시설·동선 검토", "조명 설치 검토")

c = st.columns(3)
c[0].metric("분석한 귀갓길", f"{W.W.shape[0]:,}건",
            help=f"직선 {PM.WALK_TRIP_MAX_M.value:,}m 이하는 걸어서 귀가한다고 가정(가정값)")
c[1].metric("해당 구간", f"{n_seg:,}곳", help=f"{PM.SEG_MIN_M.value}m 이상 이어진 구간")
c[2].metric(f"상위 {N}곳 길이", f"{seg['len_m'].sum() / 1000:,.1f}km")
st.caption("귀갓길 지수는 1위를 100으로 둔 상대값입니다.")


@st.cache_data(show_spinner="돌아갈 길을 확인하고 있습니다…")
def avoid_check(slot, seg_ids):
    out = {}
    inc = W.inc.tocsc()
    for s in seg_ids:
        e_ids = np.flatnonzero(lab_e == s)
        k = np.unique(inc[:, e_ids].nonzero()[0])
        if not len(k):
            out[s] = "—"
            continue
        k = k[np.argsort(-W.W[k, slot])][:2]
        ok = []
        for kk in k:
            F = G.frontier(int(W.o_node[kk]), int(W.d_node[kk]), W.eact[slot], W.thr)
            b = NC.NightGraph.choose(F, PM.DETOUR.value)
            ok.append(not np.isin(b["edges"], e_ids).any())
        out[s] = "있음 (길 안내로 해결)" if all(ok) else ("일부" if any(ok) else "없음 (시설 개선 필요)")
    return out


if st.toggle("돌아갈 길이 있는지 확인", key="avoid",
             help=f"구간마다 귀갓길 2건을 골라, 최단보다 {PM.DETOUR.value:.0%} 안에서 피해 갈 길이 있는지 봅니다"):
    res = avoid_check(S, tuple(int(x) for x in seg["seg"]))
    seg["돌아갈 길"] = seg["seg"].map(res)
show = seg.copy()
show.insert(0, "순위", np.arange(1, len(show) + 1))
show["len_m"] = show["len_m"].round().astype(int)
cols = ["순위", "dong", "len_m", "지수", "lit", "검토 방향"] + (["돌아갈 길"] if "돌아갈 길" in show else [])
t = show[cols].rename(columns={"dong": "동", "len_m": "길이(m)", "지수": "귀갓길 지수", "lit": "보안등"})
st.dataframe(t, hide_index=True, width="stretch")
st.caption("돌아갈 길이 없는 구간은 길 안내로 해결되지 않아, 시설 개선을 먼저 검토할 곳입니다.")

colors = np.array([[255, 60, 60], [255, 140, 40], [255, 200, 60]])
layers = []
for i, s in enumerate(seg["seg"]):
    e_ids = np.flatnonzero(lab_e == s)
    layers.append(UI.path_layer(G, e_ids, np.tile(colors[min(i // 5, 2)], (len(e_ids), 1)), 7, f"seg{i}"))
xy = Transformer.from_crs(5179, 4326, always_xy=True)
lon, lat = xy.transform(seg["x"].to_numpy(), seg["y"].to_numpy())
lab = pd.DataFrame({"lon": lon, "lat": lat, "tip": [f"{i + 1}위 · {d} · {L:,.0f}m" for i, (d, L)
                                                      in enumerate(zip(seg["dong"], seg["len_m"]))]})
layers.append(UI.dots(lab, [255, 255, 255], 14, "rank"))
UI.deck(layers, float(np.mean(lon)), float(np.mean(lat)), zoom=12.5, height=560)
st.caption("빨강 1–5위 · 주황 6–10위 · 노랑 11위 이하")
