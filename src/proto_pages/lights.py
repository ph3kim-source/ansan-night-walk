# -*- coding: utf-8 -*-
"""담당자 · 보안등 대조 — '보안등은 있는데 심야에 사람이 드문 구간'. 시설 데이터만으로는 안 보이는 것."""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import night_core as NC
import params as PM
import proto_ui as UI

W = UI.world()
G = W.G
S = UI.current_slot()

st.title("보안등 점검")
st.caption(f"{UI.when(S)} · 보안등이 있지만 사람이 드문 길")
UI.notice(formal=True)

L = G.length
dark = W.eact[S] < W.thr
lit = W.lit > 0
cam = W.cam > 0
km = lambda m: L[m].sum() / 1000

c = st.columns(4)
c[0].metric("보안등 O · 사람 많음", f"{km(lit & ~dark):,.0f}km")
c[1].metric("보안등 O · 사람 드묾", f"{km(lit & dark):,.0f}km ({km(lit & dark) / max(km(lit), 1e-9):.0%})")
c[2].metric("보안등 X · 사람 드묾", f"{km(~lit & dark):,.0f}km")
c[3].metric("보안등 X · 사람 많음", f"{km(~lit & ~dark):,.0f}km")
st.caption(f"보안등 {len(W.lights):,}개 · 보안등에서 {PM.LIGHT_R_M.value}m 안의 길을 '보안등 있음'으로 집계(가정값)")

lab_e, seg = NC.segments(G, lit & dark)
agg = (pd.DataFrame({"seg": lab_e, "lit": W.lit, "cam": cam})
       .query("seg >= 0").groupby("seg").agg(lit=("lit", "sum"), cam=("cam", "any")))
seg["보안등"] = seg["seg"].map(agg["lit"]).fillna(0).astype(int)
seg["CCTV"] = np.where(seg["seg"].map(agg["cam"]).fillna(False).astype(bool), "있음", "없음")
st.subheader(f"보안등은 있는데 사람이 드문 길 {len(seg):,}곳")
st.caption(f"{PM.SEG_MIN_M.value}m 이상 이어진 구간")

col1, col2 = st.columns([3, 2])
with col1:
    layers = []
    top = seg.head(300)
    show = np.isin(lab_e, top["seg"].to_numpy())
    idx = np.flatnonzero(show)
    layers.append(UI.path_layer(G, idx, np.tile(np.array([255, 70, 160]), (len(idx), 1)), 4, "litdark"))
    if st.toggle("보안등 위치 표시", key="show_lights"):
        lt = W.lights.sample(min(8000, len(W.lights)), random_state=0).copy()
        lt["tip"] = lt["보안등위치명"]
        layers.append(UI.dots(lt, [255, 230, 120], 4, "lights", tooltip=False))
    cc = W.cctv.copy()
    cc["tip"] = "CCTV · " + cc["설치목적구분"].astype(str)
    layers.append(UI.dots(cc, [90, 160, 255], 8, "cctv"))
    x, y = top["x"].mean(), top["y"].mean()
    from pyproj import Transformer
    lon, lat = Transformer.from_crs(5179, 4326, always_xy=True).transform(x, y)
    UI.deck(layers, lon, lat, zoom=12.5, height=560)
    st.caption("분홍 선: 보안등은 있는데 사람이 드문 길(긴 순 300곳) · 파란 점: CCTV")
with col2:
    t = seg.head(20)[["dong", "len_m", "보안등", "CCTV"]].copy()
    t["len_m"] = t["len_m"].round().astype(int)
    t.columns = ["동", "길이(m)", "보안등", "CCTV(50m 안)"]
    st.dataframe(t, hide_index=True, width="stretch", height=560)

st.subheader("동별 · 요일·시간별")
c1, c2 = st.columns(2)
with c1:
    by = pd.Series(L[lit & dark], index=G.dong[G.u[lit & dark]]).groupby(level=0).sum().sort_values() / 1000
    f = go.Figure(go.Bar(x=by.values, y=by.index, orientation="h", marker_color="#ff46a0",
                         hovertemplate="%{y} · %{x:.1f}km<extra></extra>"))
    f.update_layout(height=520, margin=dict(l=10, r=10, t=10, b=10), xaxis=dict(title="보안등 있는데 사람 드문 길(km)"))
    st.plotly_chart(f, width="stretch", key="bydong")
with c2:
    vals = [km(lit & (W.eact[i] < W.thr)) for i in range(len(NC.SLOTS))]
    grid = np.array(vals).reshape(7, len(NC.HOURS))
    f = go.Figure(go.Heatmap(z=grid, x=[UI.HOUR_LABEL[h] for h in NC.HOURS], y=[f"{x}요일 밤" for x in UI.DOWS],
                             colorscale="RdPu", zmin=0,
                             text=np.vectorize(lambda v: f"{v:,.0f}", otypes=[object])(grid), texttemplate="%{text}km",
                             hovertemplate="%{y} %{x} · %{z:,.0f}km<extra></extra>", showscale=False))
    f.update_layout(height=520, margin=dict(l=10, r=10, t=10, b=10), yaxis=dict(autorange="reversed"))
    st.plotly_chart(f, width="stretch", key="byslot")
