# -*- coding: utf-8 -*-
"""정보 · 데이터 출처 — 무엇이 실데이터이고 무엇이 임의값인가, 실데이터가 오면 무엇을 바꾸나.
공개 실데이터 수치는 data/proto/public_report.json(public_data.py 판정)에서 읽는다 — 화면에 숫자를 손으로 적지 않는다."""
import pandas as pd
import streamlit as st

import params as PM
import proto_ui as UI

W = UI.world()
R = W.pub
st.title("데이터 출처")
if W.priv:                                                         # 민간 실데이터 판(#19) — 내부 검토용
    UI.notice()
    m = UI.months_txt()
    st.markdown(f"{UI.REAL} 길 · 가게 위치 · 버스 노선 · 보안등 · 역 하차 인원 · 지구대 위치 · "
                f"**주민 보행 · 밤 귀갓길 이동 · 동 시간대 유동인구({m})**   :gray-badge[받았지만 못 씀] 카드 결제(블록 위치 없음)")
    used = ([("50m 셀 × 시간 유동인구(내국인 20~54세)", "DS-032", f"실데이터 {m}", "활성도의 유동 항 · 귀가 표본 출발 칸",
              "주민 보행 · 방문 결제를 대체(FLOW_FORM) — 3단계로만")] if W.has_P else [])
    st.dataframe(pd.DataFrame(used + [
        ("100m 격자 거주인구(20~54세)", "DS-082", f"실데이터 {m}",
         "화면 가림 기준 · 귀가 표본 도착 칸" if W.has_P else "주민 보행의 100m 안분 · 화면 가림 기준",
         f"인구 1명 이상 {PM.MASK_MIN_POP.value}명 미만 칸은 '자료 부족'"),
        ("도보 출발 통행", "DS-008", f"실데이터 {m}", "참고(유동 항은 DS-032)" if W.has_P else "주민 보행(동 총량)", "—"),
        ("동 × 시간 유동인구", "DS-014", f"실데이터 {m}", "동 시간대 곡선", "대민개방 — 숫자 그대로"),
        ("동 OD × 목적 · 구 OD × 시간 × 수단", "DS-004 · 001", f"실데이터 {m}", "밤 귀갓길 OD", "—"),
        ("블록 × 1시간 카드 결제 · 블록 가맹점", "DS-054 · 048", "받았지만 못 씀", "—",
         "블록 좌표표가 없어 지도에 못 올림 → 가게는 상가정보 심야 업종 위치, 영업 여부 모름"),
    ], columns=["자료", "인벤토리", "상태", "쓰는 곳", "화면 처리"]), hide_index=True, width="stretch")
    dups = [v for k, v in W.rep.items() if k.startswith("dup_") and isinstance(v, dict)]
    if dups:                                                       # 파일 이름의 달과 안의 날짜가 다를 수 있다(#19)
        st.caption("같은 내용의 파일이 다른 달 이름으로 들어 있어 한 번만 읽었습니다 — 둘 중 한 달 자료는 없습니다: "
                   + " · ".join(", ".join(d.get("같은파일", [])) for d in dups))
    st.caption("원본은 data/real/raw, 계산 결과는 data/real/proto — 이 PC 밖으로 내보내지 않습니다(공유본 · 드라이브 앱 빌드가 거부). "
               f"활성도는 3단계로만 보입니다 — 아래 경계 DARK_Q · 위 경계 GRADE_HI_Q({PM.GRADE_HI_Q.value:.0%} 분위).")
    if not W.has_P:
        st.warning("**시간에 따른 차이가 약할 수 있습니다.** 임의값 판에서 시간대별 차이를 만든 것은 카드 결제(그 시간에 문 연 가게 · 방문객)였는데, "
                   "실데이터는 블록 위치를 몰라 빠졌습니다. 주민 보행은 사람이 사는 칸에서만 시간에 따라 바뀌고, 그런 칸은 원래 '사람 드묾'이 아닙니다. "
                   "살리는 길은 둘 — 카드사 블록 경계를 받거나, 50m 셀 유동인구(DS-032 · 시간대별)를 더하는 것입니다.")
    else:
        st.info("**유동 = 50m 셀 유동인구(DS-032).** 주민 보행 · 방문 결제 두 항을 대체했습니다(FLOW_FORM). "
                f"이 자료에서 0시 값(안산 합계)은 23시의 {W.mid_ratio:.0%}입니다. 통신사가 시간대를 어떻게 집계하는지(날짜 경계 등) "
                "확인하기 전이라, 자정 전후의 차이가 실제 변화인지 집계 방식 탓인지 아직 모릅니다(FLOW_FORM 요청 자료). "
                "측정 결과와 해석은 내부 기록(수정사항 #20)에 있습니다.")
    st.divider()
elif W.real:
    st.markdown(f"{UI.REAL} 길 · 가게 위치 · 버스 노선 · 인구 총량 · 보안등 · 역 하차 인원 · 지구대 위치   "
                f"{UI.SYN} 사람 수 · 카드 결제 · 이동")
else:
    st.markdown(f"{UI.REAL} 길 · 가게 위치 · 버스 노선 · 인구 총량   {UI.SYN} 사람 수 · 카드 결제 · 이동 · 보안등 · CCTV")

rows = [
    ("OSM 보행망 (노드 34,263 · 간선 39,940)", "—", "실데이터", "경로 탐색의 길", "그대로"),
    ("소상공인 상가정보 2026.06 (34,489곳)", "—", "실데이터", "가게 위치·이름, 임의값 결제의 뼈대", "그대로"),
    ("TAGO 버스 노선·정류장 (2026-09 수집)", "—", "실데이터", "막차 내릴 곳", "그대로"),
    ("SGIS 1km 인구 · OSM 주거건물", "—", "실데이터", "임의값 거주인구의 뼈대 · 역 귀갓길의 집 쪽", "DS-082 가 오면 불필요"),
    ("도보 출발 통행", "DS-008", "임의값", "주민 보행(동 총량)", "원본 T11_…_4127.csv 로 교체"),
    ("100m 격자 거주인구", "DS-082", "임의값", "주민 보행의 100m 안분", "원본 GYEONGGI_CELL_STAT_*.csv"),
    ("블록 × 1시간 카드 결제", "DS-054", "임의값", "문 연 가게 · 방문 결제", "원본 + 블록 좌표표(카드사 요청)"),
    ("블록 가맹점 정보", "DS-048", "임의값", "가게 실재 확인", "원본 tbsh_gyeonggi_mer_s_*.csv"),
    ("동 × 시간 유동인구", "DS-014", "임의값", "동 시간대 곡선(시민 표출)", "원본 T22_…_4127.csv"),
    ("동 OD × 목적", "DS-004", "임의값", "밤 귀갓길 OD", "원본 T13_…_4127.csv"),
    ("구 OD × 시간 × 수단", "DS-001", "임의값", "밤·도보 비율", "원본 T25_…_4127.csv"),
]
if W.real:
    lt, stn = R.get("lights", {}), R.get("stations", {})
    rows += [
        (f"안산시 보안등 ({lt.get('기준일', '')} · 24개 동 {lt.get('동안', 0):,}개)", "인벤토리 밖", "실데이터",
         "보안등 점검 · 밤길 지도 · 개선 구간", "최신본을 받으면 data/public/raw 교체"),
        (f"코레일 역별 시간대 승하차 ({stn.get('verdict', '').split(' · ')[0].replace('코레일 ', '')} · "
         f"{len(stn.get('역별', {}))}개 역)", "인벤토리 밖", "실데이터", "밤 역 귀갓길",
         "매달 새 파일 — python src/collect_public.py korail"),
        (f"지구대 · 파출소 위치 (OSM · {R.get('police', {}).get('밤에열린곳', 0)}곳)", "인벤토리 밖", "실데이터",
         "밤길 '문 연 곳'", "경찰청 목록으로 대조"),
        ("CCTV · 비상벨 공개 표준데이터 (각 500개)", "인벤토리 밖", "실데이터(일부)", "지도 표시만(계산 제외)",
         "안산시 전수 위치 요청"),
    ]
else:
    rows.append(("보안등 · CCTV 표준데이터", "인벤토리 밖", "임의값", "보안등 대조", "python src/collect_public.py"))
if not W.priv:                                                     # 실데이터 판은 위 표가 대신한다
    t = pd.DataFrame(rows, columns=["자료", "인벤토리", "상태", "쓰는 곳", "실데이터가 오면"])
    st.dataframe(t, hide_index=True, width="stretch")
    st.caption("인벤토리 실데이터가 오면 `python src/ingest_inventory.py <원본폴더>` 를 실행하면 됩니다. 화면 코드는 그대로 둡니다. "
               "공개 실데이터는 `python src/collect_public.py` → `python src/public_data.py` 로 다시 받습니다.")

st.subheader("확인된 사항")
find = [
    ("**DS-082 거주인구로 나눠 배정하면 상가 거리가 '사람 드묾'으로 나온다**",
     "실측: 심야 앵커가 있는 셀 1,749개 중 35.0% 가 주거건물 0 · 거주 안분 시 27.6% 가 유동 하위 25%(지금 2.9%)",
     "주민 보행과 방문 결제 중 큰 쪽을 쓰도록 보정 (FLOW_FORM)"),
    ("**카드 블록코드를 좌표로 바꾸는 표가 없다**", "실측 blk_cd 는 6자리 정수(159533 등)",
     "카드사에 블록 경계 파일 요청 필요 (CARD_BLOCK_XY)"),
    ("**DS-048 은 업종 중분류까지만**", "실측 샘플: 편의점이 '종합소매점' 아래 소분류일 가능성", "편의점 판정은 DS-054 소분류로"),
    ("**영업 판정이 손님 적은 가게를 놓친다**", "임의값 대조: 정밀도 100% · 재현율 81.4%", "단일 카드사 표본의 한계. 실데이터로 다시 측정"),
    ("**새 경로 계산이 덜 돌아간다**", "기존 데이터 120쌍: 감소 19.7% vs 19.1% · 추가 거리 +6.4% vs +2.6% · 249 → 28ms/건",
     "본체 route.py 교체 검토"),
]
if W.real:
    bd, ld, ind = R.get("lights_by_dong", {}), R.get("light_dist", {}), R.get("industrial", {})
    few = " · ".join(f"{k} {v}개" for k, v in {**{d: 0 for d in bd.get("없는동", [])}, **bd.get("적은동", {})}.items())
    sun = {r["month"]: r for r in R.get("_sunset", {}).get("table", [])}
    find += [
        ("**보안등 자료에는 큰길 가로등이 없다**", f"동별 보안등: {few}", "큰길은 가로등 구간으로 따로 두고 골목만 판정 (MAJOR_ROAD)"),
        ("**보안등 좌표는 기둥이 아니라 지번 근처다**",
         f"{R['lights']['동안']:,}행 → 고유 위치 {R['lights']['고유위치']:,}곳 · 길까지 중앙값 {ld.get('중앙값m')}m · "
         f"20m 안 {ld.get('안20m')}", f"길에서 {PM.LIGHT_R_M.value}m 안이면 '보안등 있음' (LIGHT_R_M, C → B)"),
        ("**CCTV · 비상벨 공개분은 일부다**",
         f"전국 표준데이터에서 기관당 500행 · 안산분은 상위 7개 동에 CCTV {R.get('CCTV_partial', {}).get('상위7개동비중', '')} 몰림",
         "지도에 표시만, 계산 제외 (FACILITY_PARTIAL)"),
        ("**산업단지역의 밤 하차는 귀가가 아닌 것으로 보인다**",
         f"{', '.join(ind.get('역', []))}역 밤 하차 하루 {ind.get('밤하차', [])}명(안산 밤 하차의 {ind.get('비중', '')}) · "
         f"반경 1km 거주 {ind.get('거주', [])} vs 제조업 종사자 {ind.get('종사자', [])}",
         "귀갓길 계산에서 뺌 (INDUSTRIAL_STATION) — 목적 확인은 DS-004"),
        ("**겨울에는 '밤 10시'보다 훨씬 일찍 어둡다**",
         f"해 지는 시각 6월 {sun.get(6, {}).get('sunset', '')} · 12월 {sun.get(12, {}).get('sunset', '')} "
         f"(12월 어두워지는 시각 {sun.get(12, {}).get('dusk', '')}) — 밤 10시는 6월엔 해 진 뒤 {sun.get(6, {}).get('h22_after_sunset', '')}시간, "
         f"12월엔 {sun.get(12, {}).get('h22_after_sunset', '')}시간",
         "겨울 퇴근길(18~21시)은 지금 시간 창(22~02시) 밖 — 2단계 검토"),
    ]
st.dataframe(pd.DataFrame([(i + 1, *r) for i, r in enumerate(find)], columns=["#", "확인", "근거", "의미"])
             .assign(확인=lambda d: d["확인"].str.replace("**", "", regex=False)), hide_index=True, width="stretch")
st.caption("1·5는 기존 실데이터로, 4는 임의값으로, 6~10은 공개 실데이터로 잰 결과입니다.")

st.subheader("데이터 불러오기 점검")
rep = [{"항목": k, "판정": v.get("verdict", ""), "근거": ", ".join(f"{a}={b}" for a, b in v.items() if a != "verdict")}
       for src in (W.rep, R) for k, v in src.items() if not k.startswith("_") and isinstance(v, dict)]
st.dataframe(pd.DataFrame(rep), hide_index=True, width="stretch")

st.subheader("계산 기준값")
pr = [{"파라미터": p.name, "값": str(p.value)[:60], "등급": p.grade, "근거": p.basis[:140], "요청자료": p.need}
      for p in PM.PROTO]
st.dataframe(pd.DataFrame(pr), hide_index=True, width="stretch")
st.caption("등급 C는 근거 없는 가정값입니다. 3안 본체 근거 대장(15개)과 따로 관리합니다.")
