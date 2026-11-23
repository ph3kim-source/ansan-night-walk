# -*- coding: utf-8 -*-
"""
3안 — 안산 심야 보행 경로 (프로토타입)
실행:  streamlit run src/app.py

용어 주의: 이 화면은 CLAUDE.md 0절 금지어를 쓰지 않는다(#39 — tests/test_app.py 가 검사). 유동인구·카드결제는 사람이 있다는 지표이지
          범죄가 없다는 지표가 아니다. 화면 문구는 '사람이 많은 길 / 불 켜진 길' 로만 쓴다.
"""
import json, pathlib, sys
import numpy as np
import pandas as pd
import geopandas as gpd
import streamlit as st
import pydeck as pdk
import plotly.express as px
import networkx as nx

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import params as PM, score as SC, route as RT, alloc as AL

P = ROOT / "data" / "processed"
st.set_page_config(page_title="안산 심야 보행 경로", layout="wide", page_icon="🌙")


@st.cache_data
def load():
    c = pd.read_csv(P / "cells.csv", encoding="utf-8-sig")     # 점수 격자 100m
    n = pd.read_csv(P / "nodes.csv", encoding="utf-8-sig")     # 그래프 노드 (OSM 보행망)
    e = pd.read_csv(P / "edges.csv")
    a = pd.read_csv(P / "anchors.csv", encoding="utf-8-sig")
    d = gpd.read_file(P / "dong.geojson")
    ev = json.loads((P / "evidence.json").read_text(encoding="utf-8")) \
        if (P / "evidence.json").exists() else {}
    # 공개 실데이터 근거(수정사항 #15) — validate_public.py 산출. 본체 evidence.json 과 따로 둔다
    evp = ROOT / "data" / "public" / "evidence_public.json"
    ev["public"] = json.loads(evp.read_text(encoding="utf-8")) if evp.exists() else {}
    # 5179 -> 4326 (점수 셀 표출용). nodes.csv 는 prep 에서 이미 lon/lat 을 갖고 나온다
    g = gpd.GeoDataFrame(c, geometry=gpd.points_from_xy(c.x, c.y), crs=5179).to_crs(4326)
    c["lon"], c["lat"] = g.geometry.x.values, g.geometry.y.values
    # 점수 첫 항 — POP_ALLOC(기본 uniform = pop_night 그대로, #13)
    c["flow"] = AL.flow(c)
    return c, n, e, a, d, ev


@st.cache_resource
def graph(_c, _e, act):
    ee = SC.edge_score(_c, _e, act)
    thr = SC.dark_threshold(ee, PM.DARK_Q.value)
    G = RT.build(_c, ee)
    big = sorted(max(nx.connected_components(G), key=len))
    return G, ee, thr, np.array(big)


cells, nodes, edges, anchors, dong, EV = load()
# 점수는 100m 셀에서 매긴다. 노드로 분위를 매기면 교차로가 촘촘한 도심이 과대표집된다
ACT, F_PCT, A_PCT = SC.cell_score(cells, flow_col="flow")
cells["act"] = ACT
NODE_ACT = ACT[nodes["cell"].to_numpy()]          # 노드는 최근접 셀의 활성도를 물려받는다
nodes["act"] = NODE_ACT
G, EDG, THR, BIG = graph(nodes, edges, NODE_ACT)

# ── 사이드바 ────────────────────────────────────────────────
st.sidebar.title("🌙 설정")
detour = st.sidebar.slider(
    "최단거리보다 몇 % 더 걸어도 괜찮으신가요?", 0, 60, int(PM.DETOUR.value * 100), 5,
    help="이 값이 이 서비스의 유일한 조절값입니다. 나머지 가중치는 여기서 자동으로 역산됩니다.") / 100
st.sidebar.divider()
cg = PM.summary()
st.sidebar.markdown(
    f"**근거 등급**  A {cg['A']} · B {cg['B']} · **C {cg['C']}** · X {cg['X']}\n\n"
    "「📋 근거 대장」 탭 참조")
st.sidebar.caption(
    "**현재 데이터**\n\n"
    "- **OSM 보행망 (2026-09-21) → 실측 ✅**\n"
    "- SGIS 1km 격자 인구 (2024) → 야간 유동인구 **대체재**\n"
    "- 소상공인 상가정보 (2026.06) → 심야 결제 가맹점 **대체재**\n"
    "- **안산시 보안등 (2022-12) · 코레일 역별 시간대 하차 → 실측 ✅** (대조용, 점수에는 안 씀 — #15)\n\n"
    "보행망은 실제 도로입니다. 대체재 둘은 DS-082·054 가 오면 로더만 교체합니다.")

st.title("🌙 안산 심야 보행 경로")
st.caption("**프로토타입** · 이 화면은 *사람이 많고 불이 켜진 길* 을 안내합니다.")

k = st.columns(5)
k[0].metric("100m 점수 셀", f"{len(cells):,}개", f"{dong['ADM_NM'].nunique()}개 동")
k[1].metric("심야 앵커", f"{int((anchors.kind=='앵커').sum()):,}곳", "편의점·주유소·PC방")
k[2].metric("유흥 (점수 제외)", f"{int((anchors.kind=='유흥').sum()):,}곳",
            f"앵커의 {EV.get('nightlife_ratio','—')}배", delta_color="off")
k[3].metric("OSM 보행망", f"간선 {len(edges):,}개",
            f"노드 {len(nodes):,} · 연결 {EV.get('giant_pct','—')}%", delta_color="off")
k[4].metric("저활성 임계", f"{THR:.3f}", f"하위 {PM.DARK_Q.value:.0%} 분위", delta_color="off")

t0, t1, t2, t3, t4 = st.tabs(
    ["🚶 경로 찾기", "🗺️ 야간 활성도", "🔬 왜 가중치를 안 쓰는가", "📋 근거 대장", "⚠️ 한계"])

# ══ 경로 찾기 ═══════════════════════════════════════════════
with t0:
    st.subheader("출발지·도착지를 고르면 두 경로를 비교해 드립니다")
    cA, cB = st.columns(2)
    dongs = sorted(nodes["dong"].unique())
    d1 = cA.selectbox("출발 동", dongs, index=0)
    d2 = cB.selectbox("도착 동", dongs, index=min(3, len(dongs) - 1))

    def pick(dn, seed):
        idx = nodes.index[(nodes["dong"] == dn)].intersection(pd.Index(BIG))
        if len(idx) == 0:
            return None
        return int(idx[np.random.default_rng(seed).integers(len(idx))])

    seed = st.number_input("지점 추첨 번호 (주소 검색 자리)", 0, 9999, 0, 1,
                           help="주소→좌표 변환은 4안 geocode.py 를 이식하면 됩니다. "
                                "지금은 동 안에서 지점을 무작위로 고릅니다.")
    s, t = pick(d1, seed), pick(d2, seed + 1000)

    if s is None or t is None or s == t:
        st.warning("해당 동에 연결된 지점이 없습니다. 다른 동을 고르십시오.")
    elif not nx.has_path(G, s, t):
        st.warning("두 지점이 보행망에서 끊겨 있습니다(연결요소 문제 — 「한계」 탭 참조).")
    else:
        r = RT.plan(G, s, t, detour, THR, PM.ALPHA_MAX.value, PM.BISECT_ITER.value)
        b, w = r["base"], r["best"]
        mps = PM.WALK_MPS.value
        m = st.columns(4)
        m[0].metric("거리", f"{w['len_m']:,.0f}m", f"{w['len_m']-b['len_m']:+,.0f}m")
        m[1].metric("걷는 시간", f"{w['len_m']/mps/60:.0f}분",
                    f"{(w['len_m']-b['len_m'])/mps/60:+.0f}분")
        m[2].metric("저활성 구간", f"{w['dark_m']:,.0f}m",
                    f"{w['dark_m']-b['dark_m']:+,.0f}m", delta_color="inverse")
        m[3].metric("가장 긴 연속 저활성", f"{w['worst_run_m']:,.0f}m",
                    f"{w['worst_run_m']-b['worst_run_m']:+,.0f}m", delta_color="inverse")

        if w["dark_m"] < b["dark_m"]:
            st.success(f"**{(w['len_m']-b['len_m'])/mps/60:.0f}분 더 걸어서**, 사람이 드문 구간을 "
                       f"{b['dark_m']:,.0f}m → {w['dark_m']:,.0f}m 로 줄였습니다. "
                       f"(역산된 α = {r['alpha']:.1f})")
        else:
            st.info("최단경로에 이미 저활성 구간이 없거나, 우회해도 더 나은 길이 없습니다.")

        def line(path, color):
            pts = nodes.loc[list(path), ["lon", "lat"]].values.tolist()
            return {"path": pts, "color": color}

        layers = [
            pdk.Layer("PathLayer", [line(r["base_path"], [150, 150, 150])],
                      get_path="path", get_color="color", width_min_pixels=3),
            pdk.Layer("PathLayer", [line(r["path"], [255, 190, 60])],
                      get_path="path", get_color="color", width_min_pixels=5),
            pdk.Layer("ScatterplotLayer",
                      anchors[anchors.kind == "앵커"], get_position=["lon", "lat"],
                      get_fill_color=[80, 200, 255, 160], get_radius=25, pickable=True),
        ]
        mid = nodes.loc[list(r["path"]), ["lon", "lat"]].mean()
        st.pydeck_chart(pdk.Deck(
            layers=layers, map_style=None,
            initial_view_state=pdk.ViewState(latitude=mid.lat, longitude=mid.lon, zoom=13),
            tooltip={"text": "{name}\n{biz}"}))
        st.caption("회색 = 최단경로 · 노란색 = 추천경로 · 하늘색 점 = 심야 앵커(편의점·주유소·PC방)")

# ══ 야간 활성도 ═════════════════════════════════════════════
with t1:
    st.subheader("100m 셀별 야간 활성도")
    st.markdown("`활성도 = min( 분위(야간 유동인구), 분위(심야 앵커 접근성) )` — 가중치 없음")
    sub = cells.sample(min(6000, len(cells)), random_state=0).copy()
    sub["r"] = (255 * (1 - sub.act)).astype(int)
    sub["g"] = (200 * sub.act).astype(int)
    st.pydeck_chart(pdk.Deck(
        layers=[pdk.Layer("ScatterplotLayer", sub, get_position=["lon", "lat"],
                          get_fill_color=["r", "g", 80, 140], get_radius=55, pickable=True)],
        map_style=None,
        initial_view_state=pdk.ViewState(latitude=sub.lat.mean(), longitude=sub.lon.mean(), zoom=11),
        tooltip={"text": "{dong}\n활성도 {act}"}))
    c1, c2 = st.columns(2)
    d = cells.groupby("dong")["act"].mean().sort_values()
    c1.plotly_chart(px.bar(d, orientation="h", title="동별 평균 야간 활성도",
                           labels={"value": "활성도", "dong": ""}), width="stretch")
    c2.plotly_chart(px.histogram(pd.DataFrame(
        {"유동인구 분위": F_PCT, "앵커 접근성 분위": A_PCT, "활성도 = min": ACT}).melt(),
        x="value", color="variable", barmode="overlay", nbins=40,
        title="두 성분과 min 결과"), width="stretch")

    ct = EV.get("public", {}).get("crosstab")
    if ct:
        st.divider()
        st.subheader("보안등 대조 — 실데이터끼리 (#15)")
        st.markdown(f"위 활성도(실데이터 대체재) × **안산시 보안등 실데이터**(2022-12, 24개 동 "
                    f"{EV['public']['lights']['lights']['동안']:,}개). 보안등 자료에는 큰길 가로등이 없어 "
                    f"**골목 {ct['minor_km']:,}km** 만 셉니다(큰길 {ct['major_km']:,}km 는 가로등 구간). "
                    f"길에서 {PM.LIGHT_R_M.value}m 안에 보안등이 있으면 '있음'.")
        st.dataframe(pd.DataFrame({
            "": ["보안등 있음", "보안등 없음"],
            "사람 많음 (km)": [ct["lit_busy"], ct["unlit_busy"]],
            "저활성 (km)": [ct["lit_dark"], ct["unlit_dark"]]}), hide_index=True, width="stretch")
        st.info(f"**보안등은 있는데 저활성인 골목 {ct['lit_dark']}km** — 보안등이 있는 골목의 "
                f"{ct['lit_dark_share_of_lit']}%, 100m 이상 이어진 구간 {ct['lit_dark_segments_100m']}곳. "
                "기획의 출발점('가로등만으로는 부족하다')을 실데이터로 보여주는 첫 수치입니다. "
                "단, 활성도가 1km 균등 안분 대체재라 구간 위치는 DS-082·054 가 오면 바뀝니다.")

# ══ 왜 가중치를 안 쓰는가 ═══════════════════════════════════
with t2:
    st.subheader("기획 원안의 가중합을 그대로 쓰면 어떻게 되는가")
    st.markdown(f"""
원안은 `활성도 = 유동인구 밀도 + 반경 100m 내 결제 가맹점 수 × **가중치**` 였습니다.
같은 데이터로 가중치만 0.25 ↔ 4 로 흔들어 경로를 다시 뽑아봤습니다.

| | 결과 |
|---|---|
| 경로 간선 일치도 | **{EV.get('w_jaccard_mean', 0):.0%}** |
| 경로가 바뀐 쌍의 비율 | **{EV.get('w_changed_pct', '—')}%** |

근거를 댈 수 없는 숫자 하나가 안내 경로의 대부분을 바꿉니다.
4안에서도 같은 모양의 가중합(집객력 = w1·상가 + w2·노선 + w3·수요 − w4·거리)을 썼다가
집결지의 50~85%가 뒤바뀌어 방식 자체를 폐기한 전례가 있습니다.

**3안의 대응**
1. 활성도는 더하지 않고 `min(분위 A, 분위 B)` — '사람도 있고 가게도 있어야 한다'는 연언
2. 경로는 α 를 고정하지 않고, 시민이 정한 우회 예산 δ 를 다 쓰는 α 를 이분탐색으로 역산
""")
    if EV.get("detour_curve"):
        dc = pd.DataFrame(EV["detour_curve"])
        dc["detour"] = (dc["detour"] * 100).round().astype(int).astype(str) + "%"
        st.dataframe(dc.rename(columns={"detour": "우회 예산 δ", "len_m": "평균 거리(m)",
                                        "dark_m": "평균 저활성 노출(m)",
                                        "pairs_with_dark": "저활성이 남은 쌍"}),
                     width="stretch", hide_index=True)
        st.warning(
            f"δ 를 0%→40% 로 올려도 저활성 노출이 "
            f"{EV['detour_curve'][0]['dark_m']}m → {EV['detour_curve'][-1]['dark_m']}m 밖에 안 줄어듭니다. "
            f"우회 예산을 다 못 쓴 쌍이 **{EV.get('alpha_saturated_pct','—')}%** 입니다. "
            "보행망 교체로 δ 반응은 8.6% → 25.8% 로 3배가 됐습니다. **우회할 길은 생겼습니다.** "
            "남은 것은 우회해서 갈 **밝은 곳** 입니다 — `pop_night` 이 1km 격자 인구를 "
            "균등 안분한 값이라 1km 안이 전부 같은 숫자입니다. 이것이 DS-082(100m) 가 "
            "필요한 정량적 근거입니다.")

    st.divider()
    st.subheader("업종 필터가 필수인 이유")
    bb = pd.DataFrame([{"구분": k.split("|")[0], "업종": k.split("|")[1], "개수": v}
                       for k, v in EV.get("biz_breakdown", {}).items()])
    if len(bb):
        c1, c2 = st.columns([2, 3])
        c1.dataframe(bb, width="stretch", hide_index=True)
        c2.plotly_chart(px.bar(bb, x="개수", y="업종", color="구분", orientation="h",
                               title="안산 상가 중 심야 관련 업종"), width="stretch")
    st.error(f"심야에 결제가 발생하는 업종을 그냥 세면 **유흥 {EV.get('nightlife_n','—')}곳 > "
             f"앵커 {EV.get('anchor_n','—')}곳 ({EV.get('nightlife_ratio','—')}배)** 입니다. "
             "필터 없이 '결제 가맹점 수'로 점수를 매기면 **1등이 유흥가**가 됩니다.")

# ══ 근거 대장 ═══════════════════════════════════════════════
with t3:
    st.subheader("모든 파라미터의 근거와 등급")
    rows = [{"파라미터": p.name, "값": str(p.value), "등급": p.grade,
             "근거": p.basis, "출처": p.source, "요청자료": p.need} for p in PM.P]
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    st.divider()
    st.subheader("인벤토리에서 자동 산출한 데이터 제약")
    if EV.get("datasets"):
        st.dataframe(pd.DataFrame(EV["datasets"]), width="stretch", hide_index=True)
        st.error(
            f"**100m급 공간해상도 + 심야(22~02시) 절단 가능** 을 동시에 만족하는 테이블은 "
            f"{EV.get('fine_hour_ok')} 이고, **그중 대민개방은 "
            f"{EV.get('fine_hour_ok_open') or '한 종도 없습니다'}.** "
            "→ 계산은 비개방 데이터로 하고 집계 결과만 공개하는 2층 구조가 불가피합니다.")
    st.caption("전체 문서: `docs/근거대장.md` (python src/gen_docs.py 로 재생성)")

# ══ 한계 ════════════════════════════════════════════════════
with t4:
    st.subheader("이 프로토타입이 아직 못 하는 것")
    st.markdown(f"""
| # | 한계 | 영향 | 해소 방법 |
|---|---|---|---|
| ~~1~~ | ~~**보행 네트워크가 없다**~~ | **해소됨 (#04).** OSM 보행망 34,263노드·39,940간선으로 교체. 연결요소 1,406개(80.6%) → 105개(94.3%), 최대요소만 사용 | ~~OSM Overpass~~ **2026-09-21 수집 완료** |
| **1** | **점수 해상도가 1km다** ★ 지금의 병목 | 보행망이 들어와 우회할 **길** 은 생겼다(δ 반응 8.6%→25.8%). 그런데 우회해서 갈 **밝은 곳** 이 없다. `pop_night` 이 1km 격자 인구를 100칸에 균등 안분한 값이라 1km 안이 전부 같은 숫자다 | DS-082(100m) 또는 DS-032(50m). 무료 대안으로 **OSM 건물 면적 기반 dasymetric 안분** 이 가능하다 |
| 2 | **심야 결제가 없다** | 상가 '존재'만 알 뿐 그 시간에 문을 열었는지는 모른다 | DS-054(블록·1시간). 단 대민개방 X, 2026.01~06 6개월뿐 |
| 3 | **실시간이 아니다** | 전 데이터가 월 단위 납품된 과거 집계다. 원안의 "실시간 안내"는 성립하지 않는다 | 문구를 **"요일 × 시간대 평시 패턴"** 으로 바꾼다 |
| 4 | **범죄가 없다는 증거가 아니다** | 사람이 많은 곳 ≠ 범죄가 없는 곳. 유흥가가 대표적 반례다 | 경찰청 5대 범죄 발생지점 / 생활안전지도 |
| 5 | **가로등·CCTV 대조가 반쪽이다** (#15 부분 해소) | 안산시 보안등(골목) 실데이터는 확보해 「야간 활성도」 탭에서 대조한다. 그러나 큰길 **가로등**은 자료에 없고, CCTV·비상벨 공개분은 각 500개뿐(기관당 500행에서 잘림, 상록구 일부 동에 몰림)이라 쓰지 않는다 | 안산시 가로등 위치(도로과) · CCTV 전수 위치(도시정보센터) |
| 6 | OSM 태그 한계 | 도로폭·조명·계단 유무가 태그로 안 들어온 곳이 많다. 보행 난이도를 반영 못 한다 | 국토부 보행자도로 데이터와 대조 |
| 7 | 카드 표본 편향 | 단일 카드사 표본이라 절대 금액이 아니다 | 순위·비중으로만 해석 (인벤토리 Q-21) |
| 8 | 값이 소수·지수 표기 | 8.84e-06 같은 값이 나온다. 반올림하면 소규모 셀 정보가 사라진다 | float 명시 파싱, 반올림 금지 |

**요청 자료 우선순위** (#04 에서 1번이 해소돼 순위가 바뀌었습니다)
1. ★ **DS-082(100m 격자) 또는 DS-032(50m)** — 지금의 병목. 무료 대안은 OSM 건물 dasymetric
2. 안산시 가로등 · CCTV 전수 위치 — 기획의 대조군 (보안등은 #15 에서 공개 실데이터로 확보)
3. DS-054 내부 사용 승인 — 심야 결제 실측
4. 경찰청 5대 범죄 발생지점 (읍면동 단위라도) — '범죄가 적은 길'이라고 말하려면 필수
""")
