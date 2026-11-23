# -*- coding: utf-8 -*-
"""담당자 · 보안등 점검
  ① 보안등은 있는데 밤에 사람이 드문 골목 — 시설 데이터만으로는 안 보이는 것(사람 수는 아직 임의값)
  ② 밤에 역에서 걸어 집에 가는 길인데 보안등이 없는 골목 — 공개 실데이터만으로 계산(수정사항 #15)
큰길(MAJOR_ROAD)은 가로등 구간이라 보안등 자료 밖이다. 두 탭 모두 골목에서만 판정한다."""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from pyproj import Transformer

import night_core as NC
import params as PM
import proto_ui as UI

W = UI.world()
G = W.G
S = UI.current_slot()
TO4326 = Transformer.from_crs(5179, 4326, always_xy=True)

st.title("보안등 점검")
st.caption(f"{UI.when(S)} · 보안등이 있지만 사람이 드문 골목 · 밤 귀갓길인데 보안등이 없는 골목")
UI.notice(formal=True)

L = G.length
dark = UI.dark_mask(S)               # 실데이터 판은 '자료 부족'(가린 칸)을 뺀다(#19)
lit = W.lit > 0
alley = ~W.major                     # 골목. 큰길은 가로등 구간이라 보안등 자료로 판정하지 않는다
km = lambda m: L[m].sum() / 1000


def center(seg):
    lon, lat = TO4326.transform(float(seg["x"].mean()), float(seg["y"].mean()))
    return lon, lat


t1, t2 = st.tabs(["보안등은 있는데 사람이 드문 골목", "역에서 집 가는 밤길인데 보안등이 없는 골목"])

# ══ ① 보안등 O · 사람 드묾 ═══════════════════════════════════════════
with t1:
    c = st.columns(4)
    c[0].metric("보안등 O · 사람 많음", f"{km(alley & lit & ~dark):,.0f}km")
    c[1].metric("보안등 O · 사람 드묾",
                f"{km(alley & lit & dark):,.0f}km ({km(alley & lit & dark) / max(km(alley & lit), 1e-9):.0%})")
    c[2].metric("보안등 X · 사람 드묾", f"{km(alley & ~lit & dark):,.0f}km")
    c[3].metric("보안등 X · 사람 많음", f"{km(alley & ~lit & ~dark):,.0f}km")
    if W.real:
        st.caption(f"골목 {km(alley):,.0f}km 기준 · 보안등 {len(W.lights):,}개 {UI.REAL} 안산시 2022-12 · "
                   f"길에서 {PM.LIGHT_R_M.value}m 안이면 '보안등 있음' · 큰길 {km(W.major):,.0f}km는 가로등 구간이라 뺐습니다 · "
                   + (f"사람 다니는 정도 {UI.REAL} {UI.months_txt()} 통신 · 신용(3단계 · 가린 칸 {km(alley & W.emask):,.0f}km 제외)"
                      if W.priv else f"사람 수 {UI.SYN}"))
    else:
        st.caption(f"보안등 {len(W.lights):,}개 {UI.SYN} · 보안등에서 {PM.LIGHT_R_M.value}m 안의 길을 '보안등 있음'으로 집계")

    lab_e, seg = NC.segments(G, alley & lit & dark)
    agg = pd.DataFrame({"seg": lab_e, "lit": W.lit}).query("seg >= 0").groupby("seg")["lit"].sum()
    seg["보안등"] = seg["seg"].map(agg).fillna(0).astype(int)
    st.subheader(f"보안등은 있는데 사람이 드문 골목 {len(seg):,}곳")
    st.caption(f"{PM.SEG_MIN_M.value}m 이상 이어진 구간 · 불은 켜져 있어도 밤에 지나는 사람이 드문 곳이라 "
               "조명만으로는 해결되지 않는 구간입니다")
    sw = st.columns(2)
    show_l = sw[0].toggle("보안등 위치", key="show_lights")
    show_c = sw[1].toggle("CCTV · 비상벨(공개분 일부)" if W.real else "CCTV", key="show_cctv")
    col1, col2 = st.columns([3, 2])
    with col1:
        layers = []
        top = seg.head(300)
        idx = np.flatnonzero(np.isin(lab_e, top["seg"].to_numpy()))
        layers.append(UI.path_layer(G, idx, np.tile(np.array([255, 70, 160]), (len(idx), 1)), 4, "litdark"))
        if show_l:
            lt = W.lights.sample(min(8000, len(W.lights)), random_state=0).copy()
            lt["tip"] = lt["보안등위치명"].astype(str)
            layers.append(UI.dots(lt, [255, 230, 120], 4, "lights", tooltip=False))
        if show_c:
            cc = W.cctv.copy()
            cc["tip"] = "CCTV · " + cc["설치목적구분"].astype(str)
            layers.append(UI.dots(cc, [90, 160, 255], 8, "cctv"))
            if len(W.bells):
                bb = W.bells.copy()
                bb["tip"] = "비상벨 · " + bb["설치위치"].astype(str)
                layers.append(UI.dots(bb, [255, 120, 80], 7, "bells"))
        lon, lat = center(top) if len(top) else (126.83, 37.32)
        UI.deck(layers, lon, lat, zoom=12.5, height=520)
        st.caption("분홍 선: 보안등은 있는데 사람이 드문 골목(긴 순 300곳)"
                   + (" · 파란 점 CCTV · 주황 점 비상벨 — 공개된 각 500개뿐이라(상록구 일부 동) 없는 곳이 없다는 뜻은 아닙니다"
                      if W.real else " · 파란 점: CCTV"))
    with col2:
        t = seg.head(20)[["dong", "len_m", "보안등"]].copy()
        t["len_m"] = t["len_m"].round().astype(int)
        t.columns = ["동", "길이(m)", "보안등"]
        st.dataframe(t, hide_index=True, width="stretch", height=520)

    st.subheader("동별 · 요일·시간별")
    c1, c2 = st.columns(2)
    m = alley & lit & dark
    with c1:
        by = pd.Series(L[m], index=G.dong[G.u[m]]).groupby(level=0).sum().sort_values() / 1000
        f = go.Figure(go.Bar(x=by.values, y=by.index, orientation="h", marker_color="#ff46a0",
                             hovertemplate="%{y} · %{x:.1f}km<extra></extra>"))
        f.update_layout(height=520, margin=dict(l=10, r=10, t=10, b=10),
                        xaxis=dict(title="보안등 있는데 사람 드문 골목(km)"))
        st.plotly_chart(f, width="stretch", key="bydong")
    with c2:
        vals = [km(alley & lit & UI.dark_mask(i)) for i in range(len(NC.SLOTS))]
        grid = np.array(vals).reshape(7, len(NC.HOURS))
        f = go.Figure(go.Heatmap(z=grid, x=[UI.HOUR_LABEL[h] for h in NC.HOURS], y=[f"{x}요일 밤" for x in UI.DOWS],
                                 colorscale="RdPu", zmin=0,
                                 text=np.vectorize(lambda v: f"{v:,.0f}", otypes=[object])(grid),
                                 texttemplate="%{text}km",
                                 hovertemplate="%{y} %{x} · %{z:,.0f}km<extra></extra>", showscale=False))
        f.update_layout(height=520, margin=dict(l=10, r=10, t=10, b=10), yaxis=dict(autorange="reversed"))
        st.plotly_chart(f, width="stretch", key="byslot")

# ══ ② 밤 역 귀갓길 × 보안등 없는 골목 (실데이터만) ══════════════════════════════
with t2:
    if not W.real:
        st.info("공개 실데이터가 없습니다. `python src/collect_public.py` → `python src/ingest_inventory.py` 를 먼저 실행하십시오.")
        st.stop()
    sts = W.stations
    home = sts[~sts["industrial"].astype(bool)]
    F = W.flow_st.sum(axis=0)                                  # 22시 ~ 막차, 사람/밤 (요일 구분 없는 월 평균)
    pm = F * L
    # 단위 = 블록(교차로와 교차로 사이). 이어진 덩어리로 묶으면 보안등 없는 골목이 그물처럼 이어져 수 km 가 된다
    t = pd.DataFrame({"lk": W.links, "len": L, "pm": pm, "gap": alley & ~lit, "dk": L * dark,
                      "x": G.mid[:, 0], "y": G.mid[:, 1], "dong": G.dong[G.u]})
    g = t.groupby("lk")
    bl = pd.DataFrame({"len_m": g["len"].sum(), "pm": g["pm"].sum(), "gap": g["gap"].all(), "dark_m": g["dk"].sum(),
                       "x": g["x"].mean(), "y": g["y"].mean(), "dong": g["dong"].first()})
    cand = bl[bl["gap"] & (bl["pm"] > 0)].sort_values("pm", ascending=False)
    N = PM.PRIORITY_TOP_N.value
    top2 = cand.head(N).copy()
    if len(top2):
        top2["지수"] = (100 * top2["pm"] / top2["pm"].iloc[0]).round().astype(int)
        d = np.hypot(top2["x"].to_numpy()[:, None] - home["x"].to_numpy()[None, :],
                     top2["y"].to_numpy()[:, None] - home["y"].to_numpy()[None, :])
        top2["역"] = home["station"].to_numpy()[d.argmin(axis=1)] + "역"
        top2["드묾"] = np.where(top2["dark_m"] > top2["len_m"] / 2, "예", "")
    month = str(sts["month"].iloc[0]) if len(sts) else ""
    c = st.columns(3)
    c[0].metric("밤 10시~막차 하차 (하루 평균)", f"{home['night'].sum():,.0f}명",
                help=f"코레일 {month} 역별 시간대 하차 · 산업단지역 제외")
    c[1].metric("그중 보안등 없는 골목을 지나는 몫", f"{pm[alley & ~lit].sum() / max(pm.sum(), 1e-9):.0%}",
                help="사람 × 걸은 거리 기준. 큰길(가로등 구간)을 지나는 몫은 따로 셉니다")
    c[2].metric("밤 귀갓길이 지나는 보안등 없는 골목", f"{len(cand):,}블록", help="블록 = 교차로와 교차로 사이")
    st.caption(f"{UI.REAL} 코레일 {month} 역별 시간대 하차 · 안산시 보안등 · OpenStreetMap 보행망으로 순위를 매겼습니다(임의값 없음). "
               f"내린 사람이 보행망 {PM.STATION_WALK_MAX_M.value / 1000:.1f}km 안의 집까지 최단 경로로 걷는다고 보고 "
               "집 쪽은 1km 인구를 주거건물 규모로 나눴습니다. 버스 · 택시로 갈아타는 사람도 걷는다고 본 셈이라 "
               "귀갓길 지수는 1위를 100으로 둔 상대값입니다. 표의 '사람 드묾'은 "
               + (f"{UI.REAL} {UI.months_txt()} 통신 · 신용(가린 칸 제외)입니다." if W.priv else f"{UI.SYN}입니다."))

    col1, col2 = st.columns([3, 2])
    with col1:
        layers = []
        cols = np.array([[255, 60, 60], [255, 140, 40], [255, 200, 60]])
        for i, s in enumerate(top2.index):
            e_ids = np.flatnonzero(W.links == s)
            layers.append(UI.path_layer(G, e_ids, np.tile(cols[min(i // 5, 2)], (len(e_ids), 1)), 7, f"gap{i}"))
        sd = sts.copy()
        sd["tip"] = (sd["station"] + "역 · 밤 하차 하루 " + sd["night"].round().astype(int).map("{:,}명".format)
                     + np.where(sd["industrial"].astype(bool), " (산업단지역 — 귀갓길에서 뺌)", ""))
        sd["r"] = 40 + np.sqrt(sd["night"].clip(lower=1)) * 6
        layers.append(UI.pdk.Layer("ScatterplotLayer", sd, id="stations", get_position=["lon", "lat"], get_radius="r",
                                   get_fill_color=[120, 170, 255, 150], pickable=True, stroked=True,
                                   get_line_color=[20, 20, 30, 255], line_width_min_pixels=1))
        lon, lat = center(top2) if len(top2) else (126.83, 37.32)
        UI.deck(layers, lon, lat, zoom=12.5, height=520)
        st.caption("빨강 1–5위 · 주황 6–10위 · 노랑 11위 이하 · 파란 원: 역(크기 = 밤 하차 인원)")
    with col2:
        if len(top2):
            t = top2[["dong", "len_m", "지수", "역", "드묾"]].copy()
            t.insert(0, "순위", np.arange(1, len(t) + 1))
            t["len_m"] = t["len_m"].round().astype(int)
            t.columns = ["순위", "동", "길이(m)", "귀갓길 지수", "가까운 역", "사람 드묾(이 시간)"]
            st.dataframe(t, hide_index=True, width="stretch", height=520)

    with st.expander(f"역별 밤 하차 — 코레일 {month} (하루 평균)"):
        t = sts[["station", "line", "a22", "a23", "a24", "night", "industrial"]].copy()
        t = t.sort_values("night", ascending=False)
        for k in ["a22", "a23", "a24", "night"]:
            t[k] = t[k].round().astype(int)
        t["industrial"] = np.where(t["industrial"].astype(bool), "산업단지역(뺌)", "")
        t.columns = ["역", "노선", "밤 10시대", "밤 11시대", "자정 이후", "합", "비고"]
        st.dataframe(t, hide_index=True, width="stretch")
        st.caption("산업단지역 = 역 반경 1km에 제조업 종사자가 거주인구보다 많은 역. 밤에 내리는 사람이 집이 아니라 "
                   "일터로 가는 것으로 보여(확인 전 가설) 귀갓길 계산에서 뺐습니다.")
