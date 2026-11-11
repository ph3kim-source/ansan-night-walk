# -*- coding: utf-8 -*-
"""시민 · 막차 내릴 곳 — 같은 버스의 집 근처 정류장 중 어디서 내리면 집까지 사람 다니는 길로 가나."""
import numpy as np
import pandas as pd
import streamlit as st

import night_core as NC
import params as PM
import proto_ui as UI

W = UI.world()
G = W.G
S = UI.current_slot()
routes, stops = UI.bus()

st.title("막차, 어디서 내릴까")
st.caption(UI.when(S))
UI.notice()

c1, c2 = st.columns([2, 3])
# 기본값: 임의값 기준으로 가장 가까운 정류장과 추천 정류장이 갈리는 예(고잔동 · 6번)
home_txt = c1.text_input("집", "고잔동", key="bus_home", placeholder="주소, 정류장, 동 이름")
home = UI.locate(home_txt)
if home is None:
    st.warning(f"'{home_txt}' 위치를 찾지 못했어요. 도로명 주소나 동 이름으로 검색해 보세요.")
    st.stop()
c1.caption(f"📍 {UI.place(home)}")
# 집 근처(직선 BUS_WALK_MAX_M)에 서는 노선만, 근처 정류장이 많은 순
stops = stops.assign(d0=np.hypot(stops["x"] - home["x"], stops["y"] - home["y"]))
near_all = stops[stops["d0"] <= PM.BUS_WALK_MAX_M.value]
n_by = near_all.groupby("routeid")["nodeid"].nunique()
routes = routes[routes["routeid"].isin(n_by.index)].assign(n_near=lambda d: d["routeid"].map(n_by))
routes = routes.sort_values("n_near", ascending=False).reset_index(drop=True)
if routes.empty:
    st.info("집 근처에 서는 버스가 없어요.")
    st.stop()
labels = [f"{no}번 · 막차 {t}" for no, t in zip(routes["routeno"], routes["막차"].fillna("-"))]
six = [i for i, x in enumerate(routes["routeno"]) if x == "6"]
lab = c2.selectbox("타는 버스", labels, index=six[0] if six else 0, key=f"bus_route_{home['node']}",
                   help="집 근처에 서는 버스만 보여요")
r = routes.iloc[labels.index(lab)]
c2.caption(f"{r['startnodenm']} → {r['endnodenm']} · 첫차 {r['첫차']} · 막차 {r['막차']}(출발 정류장 기준)")

ea = W.eact[S]
rows, paths = [], {}
for c in near_all[near_all["routeid"] == r["routeid"]].sort_values("d0").drop_duplicates("nodeid").itertuples():
    s_node = G.snap(c.x, c.y)
    if s_node == home["node"]:
        continue
    F = G.frontier(s_node, home["node"], ea, W.thr)
    if not F:
        continue
    b = NC.NightGraph.choose(F, PM.DETOUR.value)   # 밤길 화면의 선택과 무관하게 같은 기준
    rows.append({"정류장": c.nodenm, "d0": c.d0, "len": b["len_m"], "dark": b["dark_m"], "run": b["worst_run_m"],
                 "lon": c.lon, "lat": c.lat, "key": f"{c.nodenm}_{c.nodeid}"})
    paths[f"{c.nodenm}_{c.nodeid}"] = b
t = pd.DataFrame(rows)
if t.empty:
    st.info("이 버스 정류장에서 집까지 이어지는 길을 찾지 못했어요.")
    st.stop()
# 같은 이름(길 건너 맞은편) 정류장은 나은 쪽 하나만
t = (t.sort_values(["dark", "run", "len"]).drop_duplicates("정류장").reset_index(drop=True))
near = t.loc[t["d0"].idxmin()]
best = t.iloc[0]

if best["정류장"] != near["정류장"] and near["dark"] - best["dark"] >= 5:
    dt = UI.mins(best["len"]) - UI.mins(near["len"])
    more = "걷는 시간은 비슷해요." if abs(dt) < 1 else (f"대신 {dt}분 더 걸어요." if dt > 0 else f"걷는 시간도 {-dt}분 줄어요.")
    gain = ("집까지 사람 드문 길이 없어요." if best["dark"] < 5
            else f"사람 드문 길이 {UI.km(near['dark'])}에서 {UI.km(best['dark'])}로 줄어요.")
    st.success(f"**{best['정류장']}**에서 내리세요. {gain}  \n"
               f"가장 가까운 {near['정류장']}에서 내리면 사람 드문 길 {UI.km(near['dark'])}를 지나요. {more}")
else:
    st.success(f"가장 가까운 **{best['정류장']}**에서 내리는 게 가장 좋아요.")

show = pd.DataFrame({"정류장": t["정류장"], "걸어서": t["len"].map(lambda v: f"{UI.mins(v)}분"),
                     "사람 드문 길": t["dark"].map(UI.dark_txt), "가장 길게 이어지는 구간": t["run"].map(UI.dark_txt)})
st.dataframe(show.head(6), hide_index=True, width="stretch")

layers = []
for i, row in t.head(5).iterrows():
    b = paths[row["key"]]
    if i == 0:
        layers.append(UI.path_layer(G, b["edges"], UI.act_rgb(ea[b["edges"]], W.thr), 7, "best"))
    else:
        layers.append(UI.line_layer(G, b["path"], UI.BASE_RGB, 3, f"p{i}", 150))
pts = t.head(5).copy()
pts["tip"] = pts["정류장"] + " · 사람 드문 길 " + pts["dark"].map(UI.dark_txt)
layers.append(UI.dots(pts, [80, 220, 255], 26, "stops"))
layers.append(UI.dots(pd.DataFrame({"lon": [home["lon"]], "lat": [home["lat"]], "tip": ["집"]}), [255, 255, 255], 30, "home"))
UI.deck(layers, home["lon"], home["lat"], zoom=15)
st.caption("🔵 정류장 · ⚪ 집 · 🔴 사람 드문 길 · 🟡 사람 다니는 길 · 회색 선은 다른 정류장에서 오는 길")
