# -*- coding: utf-8 -*-
"""시민 · 밤길 — 요일·시간별 경로 · 우회 선택 · 가는 길 살펴보기 · 문 연 가게."""
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

st.title("밤길")
st.caption(UI.when(S))
UI.notice()

# 임의값 기준으로 우회 효과가 잘 보이는 쌍(금 밤 11시 · 수 새벽 1시 탐색) — 한대앞역→고잔동은 시간에 따라 +2분/+5분으로 갈린다
PRESETS = [("상록수역", "성포동"), ("한대앞역", "고잔동"), ("안산역", "백운동"), ("중앙역", "일동")]
pick = st.pills("예시 경로", [f"{a} → {b}" for a, b in PRESETS], default=f"{PRESETS[0][0]} → {PRESETS[0][1]}",
                key="preset", label_visibility="collapsed")
if pick and st.session_state.get("_preset_applied") != pick:
    a, b = pick.split(" → ")
    st.session_state["o_txt"], st.session_state["d_txt"] = a, b
    st.session_state["_preset_applied"] = pick
c1, c2 = st.columns(2)
o_txt = c1.text_input("출발", key="o_txt", placeholder="주소, 정류장, 동 이름")
d_txt = c2.text_input("도착", key="d_txt", placeholder="주소, 정류장, 동 이름")
o, d = UI.locate(o_txt), UI.locate(d_txt)
for txt, h in ((o_txt, o), (d_txt, d)):
    if h is None:
        st.warning(f"'{txt}' 위치를 찾지 못했어요. 도로명 주소나 정류장 이름으로 검색해 보세요.")
        st.stop()
c1.caption(f"📍 {UI.place(o)}")
c2.caption(f"📍 {UI.place(d)}")
if o["node"] == d["node"]:
    st.info("출발지와 도착지가 같아요.")
    st.stop()


@st.cache_data(show_spinner="길을 찾고 있어요…", max_entries=256)
def front(s, t, slot):
    return [dict(r) for r in G.frontier(s, t, W.eact[slot], W.thr)]


def options(F):
    """고를 만한 경로만 — 앞 경로보다 사람 드문 길이 50m·20% 이상 줄어야 새 선택지. 최대 4개."""
    keep = [F[0]]
    for r in NC.NightGraph.pareto(F)[1:]:
        if keep[-1]["dark_m"] - r["dark_m"] >= max(50.0, .2 * keep[-1]["dark_m"]):
            keep.append(r)
    return keep[:4]


F = front(o["node"], d["node"], S)
if not F:
    st.error("두 곳을 잇는 길을 찾지 못했어요.")
    st.stop()
base = F[0]
opts = options(F)
rec = NC.NightGraph.choose(opts, PM.DETOUR.value)


def label(r):
    tag = "최단" if r is base else ("추천" if r is rec else "")
    return f"{tag} {UI.mins(r['len_m'])}분 · 사람 드문 길 {UI.dark_txt(r['dark_m'])}".strip()


labels = [label(r) for r in opts]
sel = st.segmented_control("경로", labels, default=labels[opts.index(rec)],
                           key=f"opt_{o['node']}_{d['node']}_{S}", label_visibility="collapsed")
best = opts[labels.index(sel)] if sel in labels else rec
st.session_state["detour"] = best["len_m"] / base["len_m"] - 1

extra = UI.mins(best["len_m"]) - UI.mins(base["len_m"])
saved = base["dark_m"] - best["dark_m"]
m = st.columns(4)
m[0].metric("소요 시간", f"{UI.mins(best['len_m'])}분", f"+{extra}분" if extra > 0 else None, delta_color="off")
m[1].metric("거리", UI.km(best["len_m"]))
m[2].metric("사람 드문 길", UI.dark_txt(best["dark_m"]), f"-{UI.km(saved)}" if saved >= 5 else None,
            delta_color="inverse")
m[3].metric("가장 길게 이어지는 구간", UI.dark_txt(best["worst_run_m"]),
            help="사람 드문 길이 끊기지 않고 이어지는 가장 긴 거리예요")
if saved >= 5:
    st.success(f"걷는 시간은 거의 같고, 사람 드문 길이 {UI.km(saved)} 줄어요." if extra <= 0
               else f"{extra}분 더 걸으면 사람 드문 길이 {UI.km(saved)} 줄어요.")
elif base["dark_m"] < 5:
    st.success("가는 길 내내 사람이 다니는 길이에요.")
elif len(opts) == 1:
    st.info("이 시간에는 돌아가도 더 나은 길이 없어요.")

# ── 지도 ───────────────────────────────────────────────────────
ea = W.eact[S]
near = NC.anchors_along(G, best["path"], W.abxy, W.active[:, S])
layers = [UI.line_layer(G, base["path"], UI.BASE_RGB, 4, "base", 170),
          UI.path_layer(G, best["edges"], UI.act_rgb(ea[best["edges"]], W.thr), 7, "best")]
other = None
if st.toggle("다른 시간과 비교", key="cmp_on"):
    names = [UI.when(i) for i in range(len(NC.SLOTS))]
    oth = st.selectbox("비교할 시간", names, index=NC.slot_index(1, 1), key="cmp_slot")
    other = NC.NightGraph.choose(options(front(o["node"], d["node"], names.index(oth))), PM.DETOUR.value)
    layers.append(UI.line_layer(G, other["path"], [170, 120, 255], 4, "other", 230))
if len(near):
    a = W.ab.iloc[near["block"].to_numpy()].copy()
    a["tip"] = ("출발 후 " + near["at_m"].round(-1).astype(int).map("{:,}m".format).to_numpy() + "\n"
                + a["names"].fillna("").str.split(" · ").str[0].str.replace(r"\(.*\)", "", regex=True))
    layers.append(UI.dots(a, [80, 220, 255], 22, "anchors"))
ends = pd.DataFrame({"lon": [o["lon"], d["lon"]], "lat": [o["lat"], d["lat"]], "tip": ["출발", "도착"]})
layers.append(UI.dots(ends, [255, 255, 255], 30, "ends"))
mid = G.lonlat[np.asarray(best["path"])].mean(axis=0)
UI.deck(layers, mid[0], mid[1], zoom=14)
st.caption("🔴 사람 드문 길 · 🟡 사람 다니는 길 · ⚪ 최단 경로 · 🔵 문 연 가게"
           + (" · 🟣 비교한 시간의 경로" if other else ""))
if other:
    st.markdown(f"**{oth}에는**")
    c = st.columns(3)
    c[0].metric("소요 시간", f"{UI.mins(other['len_m'])}분")
    c[1].metric("사람 드문 길", UI.dark_txt(other["dark_m"]))
    c[2].metric("가장 길게 이어지는 구간", UI.dark_txt(other["worst_run_m"]))

# ── 가는 길 ────────────────────────────────────────────────────
st.subheader("가는 길")
pr = G.profile(best["edges"], ea, W.thr)
pb = G.profile(base["edges"], ea, W.thr)
fig = go.Figure()
fig.add_trace(go.Scatter(x=np.r_[pb["from_m"], pb["to_m"].iat[-1]], y=np.r_[pb["act"], pb["act"].iat[-1]],
                         mode="lines", line=dict(shape="hv", width=1.5, color="rgba(150,150,160,0.8)"),
                         name="최단 경로", hovertemplate="출발 후 %{x:,.0f}m<extra>최단 경로</extra>"))
fig.add_trace(go.Scatter(x=np.r_[pr["from_m"], pr["to_m"].iat[-1]], y=np.r_[pr["act"], pr["act"].iat[-1]],
                         mode="lines", line=dict(shape="hv", width=2.5, color="#f5a623"),
                         name="선택한 경로", hovertemplate="출발 후 %{x:,.0f}m<extra>선택한 경로</extra>"))
for r in pr[pr["dark"]].itertuples():
    fig.add_vrect(x0=r.from_m, x1=r.to_m, fillcolor="rgba(235,64,52,0.18)", line_width=0, layer="below")
fig.add_hline(y=W.thr, line=dict(color="rgba(235,64,52,0.9)", width=1, dash="dot"),
              annotation_text="이 아래는 사람 드문 길", annotation_position="bottom left")
if len(near):
    nm = (W.ab.iloc[near["block"].to_numpy()]["names"].fillna("").str.split(" · ").str[0]
          .str.replace(r"\(.*\)", "", regex=True).str[:20])
    fig.add_trace(go.Scatter(x=near["at_m"], y=np.full(len(near), 1.05), mode="markers",
                             marker=dict(symbol="triangle-down", size=10, color="#50dcff"),
                             name="문 연 가게", text=nm, hovertemplate="%{text}<extra>출발 후 %{x:,.0f}m</extra>"))
fig.update_layout(height=260, margin=dict(l=10, r=10, t=10, b=10),
                  yaxis=dict(range=[0, 1.12], title="사람", showticklabels=False, showgrid=False),
                  xaxis=dict(title="출발 후 거리(m)"), legend=dict(orientation="h", y=-0.35), hovermode="x unified")
st.plotly_chart(fig, width="stretch", key="profile")

c1, c2 = st.columns(2)
with c1:
    st.markdown("**더 걸을수록 얼마나 줄어들까**")
    P = NC.NightGraph.pareto(F)
    f2 = go.Figure(go.Scatter(x=[UI.minutes(r["len_m"] - base["len_m"]) for r in P], y=[r["dark_m"] for r in P],
                              mode="lines+markers", line=dict(width=2, color="#f5a623"), marker=dict(size=9),
                              hovertemplate="+%{x:.0f}분 · 사람 드문 길 %{y:,.0f}m<extra></extra>"))
    f2.add_trace(go.Scatter(x=[UI.minutes(best["len_m"] - base["len_m"])], y=[best["dark_m"]], mode="markers",
                            marker=dict(size=16, color="rgba(0,0,0,0)", line=dict(color="#888", width=2)),
                            hoverinfo="skip"))
    f2.update_layout(height=250, margin=dict(l=10, r=10, t=10, b=10), showlegend=False,
                     xaxis=dict(title="더 걷는 시간(분)"), yaxis=dict(title="사람 드문 길(m)", rangemode="tozero"))
    st.plotly_chart(f2, width="stretch", key="curve")
with c2:
    st.markdown("**요일·시간별 (최단 경로)**")
    ids = base["edges"]
    L = G.length[ids]
    grid = np.array([[float(L[W.eact[NC.slot_index(dd, hh)][ids] < W.thr].sum()) for hh in NC.HOURS]
                     for dd in range(7)])
    f3 = go.Figure(go.Heatmap(z=grid, x=[UI.HOUR_LABEL[h] for h in NC.HOURS], y=[f"{x}요일 밤" for x in UI.DOWS],
                              colorscale="OrRd", zmin=0, zmax=max(float(grid.max()), 1.0),
                              text=np.vectorize(UI.dark_txt, otypes=[object])(grid), texttemplate="%{text}",
                              hovertemplate="%{y} %{x} · 사람 드문 길 %{text}<extra></extra>", showscale=False))
    f3.update_layout(height=250, margin=dict(l=10, r=10, t=10, b=10), yaxis=dict(autorange="reversed"))
    st.plotly_chart(f3, width="stretch", key="grid")

with st.expander(f"지나가는 길에 문 연 가게 {len(near)}곳"):
    if len(near):
        t = W.ab.iloc[near["block"].to_numpy()][["names", f"s{S}"]].copy()
        t.insert(0, "위치", "출발 후 " + near["at_m"].round(-1).astype(int).map("{:,}m".format).to_numpy())
        t[f"s{S}"] = (t[f"s{S}"] * 100).round().astype(int).astype(str) + "%"
        t.columns = ["위치", "가게", "평소 이 시간 영업"]
        st.dataframe(t, hide_index=True, width="stretch")
        st.caption("가게는 100m 단위 구역으로 묶여 있어서, 구역 안의 어느 가게가 열었는지까지는 알 수 없어요.")
dong = W.nodes["dong"].iat[d["node"]]
cv = W.curve[(W.curve["dong"] == dong) & (W.curve["dow"] == NC.SLOTS[S][0])].sort_values("hour")
if len(cv):
    with st.expander(f"{dong} 시간대별 유동인구"):
        f4 = go.Figure(go.Scatter(x=cv["hour"], y=cv["pop_20_54"], mode="lines", line=dict(width=2, color="#8ab4f8"),
                                  hovertemplate="%{x}시 · %{y:,.0f}명<extra></extra>"))
        f4.update_layout(height=220, margin=dict(l=10, r=10, t=10, b=10),
                         xaxis=dict(title="시", dtick=2), yaxis=dict(title="20~54세", rangemode="tozero"))
        st.plotly_chart(f4, width="stretch", key="dongcurve")
        st.caption("집에 있는 사람까지 포함한 숫자라 밤에도 높게 나와요.")

with st.expander("어떻게 계산하나요?"):
    st.markdown(f"""
- 사람이 다니는 정도와 그 시간에 문을 연 편의점·주유소·PC방을 함께 봐요. 둘 중 하나라도 부족하면 **사람 드문 길**로 표시해요.
- 같은 요일·시간의 평소 모습이에요. 실시간 정보는 아니에요.
- 범죄 정보는 반영하지 않아요.
- 걷는 시간은 초속 {PM.WALK_MPS.value}m로 계산했어요(가정값).
- 지금은 시연용으로 만든 데이터라 실제 거리와 달라요.
""")
