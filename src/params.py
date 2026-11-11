# -*- coding: utf-8 -*-
"""
파라미터 중앙 정의 — 모든 상수는 여기에만 존재하고, 각자 '근거'와 '등급'을 갖는다.

등급
  A : 본 프로젝트가 보유 데이터로 직접 산출 (src/validate.py 에서 재현 가능)
  B : 보유 데이터로 타당성을 확인했으나 최종 판단에 운영·정책 요소가 섞임
  C : 근거 없음. 임의 가정이거나 외부 자료·실증이 있어야 확정 가능
  X : 근거가 불필요 (시민이 직접 조작하는 값 / 계산 편의 / 재현성 목적)

C 등급은 숨기지 않는다. docs/근거대장.md 와 앱 「근거 대장」 탭에 그대로 노출된다.

3안의 설계 목표는 'C등급을 만들지 않는 구조'다.
4안에서 집객력 가중합(w_poi·w_hub·w_dem·w_dist)이 결과의 50~85%를 좌우한 사고가
있었으므로, 3안은 처음부터 가중합을 쓰지 않는다. 자세한 것은 route.py 주석 참조.
"""
from dataclasses import dataclass
from typing import Any, List


@dataclass
class Param:
    value: Any
    grade: str                      # A / B / C / X
    basis: str                      # 왜 이 값인가
    source: str = ""                # 근거 데이터·문헌
    replace: str = ""               # 어떻게 하면 등급을 올릴 수 있는가
    need: str = ""                  # 담당자에게 요청할 자료
    note: str = ""
    name: str = ""
    scope: str = "core"             # core = 3안 본체 / proto = 시연 프로토타입(임의값 데이터) 전용

    def pick(self, override=None):
        return self.value if override is None else override


P: List[Param] = []
# 시연 프로토타입 전용 — 본체 근거 대장(P)과 섞지 않는다. 섞으면 기존 앱 「근거 대장」 탭과
# README·근거·기능 문서의 파라미터 개수(15개 · A2/B8/C1/X4)가 프로토타입 때문에 바뀐다
PROTO: List[Param] = []


def reg(name, scope="core", **kw):
    p = Param(name=name, scope=scope, **kw)
    (PROTO if scope == "proto" else P).append(p)
    return p


def summary(items=None):
    c = {"A": 0, "B": 0, "C": 0, "X": 0}
    for p in (P if items is None else items):
        c[p.grade] = c.get(p.grade, 0) + 1
    return c


# ══ 시간 정의 ════════════════════════════════════════════════
NIGHT_HOURS = reg(
    "NIGHT_HOURS", value=[22, 23, 0, 1], grade="B",
    basis="기획이 정의한 '심야'는 22~02시다. 통신(DS-014·032)의 TIME_CD는 0~23 정시라 "
          "22·23·0·1 네 칸으로 정확히 표현된다. 카드는 DS-054(1시간 단위)만 같은 절단이 "
          "가능하고, DS-047·049·052·053은 hour='01'이 00:00~06:59 7시간 통짜라 "
          "22~02시를 잘라낼 수 없다",
    source="인벤토리 03_컬럼사전 DS-014 TIME_CD / DS-054 hour / DS-047 hour",
    note="★ 이 한 줄이 3안의 데이터 선택을 전부 결정한다. "
         "심야 해상도를 가진 카드 테이블은 DS-054 하나뿐이고 그것은 대민개방 X다",
)

NIGHT_HOURS_CARD_OPEN = reg(
    "NIGHT_HOURS_CARD_OPEN", value=["09", "10", "01"], grade="B",
    basis="대민개방 카드(DS-047)로 심야를 표현할 수 있는 최대치. "
          "09=21:00~22:59, 10=23:00~23:59, 01=00:00~06:59. "
          "09는 21시가, 01은 02~06시가 섞여 들어오므로 22~02시와 정확히 일치하지 않는다",
    source="인벤토리 07_코드값사전 '카드 시간대 hour'",
    replace="DS-054(1시간 단위) 사용 승인 시 불필요해진다",
    note="화면 표출용으로만 쓴다. 점수 계산에 쓰면 21시 저녁 상권이 심야로 오염된다",
)

# ══ 공간 정의 ════════════════════════════════════════════════
EXCLUDE_DONG = reg(
    "EXCLUDE_DONG", value=["대부동"], grade="A",
    basis="대부동은 인구>0 격자 155개 중 45개(29%)를 차지하나 인구는 7,575명(1.1%)뿐이고, "
          "시화호·바다로 본토와 끊겨 있어 격자 그래프가 수면 위를 지나간다. "
          "심야 보행 경로 안내의 대상지가 아니다",
    source="SGIS 1km 격자 인구 (src/validate.py::e_exclude)",
)

CELL_M = reg(
    "CELL_M", value=100, grade="B",
    basis="카드 블록(blk_cd)이 100m급이고 개인신용 격자(DS-082)도 100m다. "
          "점수 레이어를 이 해상도에 맞추면 재집계 없이 바로 조인된다. "
          "50m(DS-032)까지 내려갈 수 있으나 그 테이블은 639GB·대민개방 X다",
    source="인벤토리 02 DS-048 blk_cd / DS-082 공간단위",
)

WALK_NET = reg(
    "WALK_NET", value="OSM highway=footway|path|pedestrian|steps|living_street|"
                      "residential|service|unclassified|track|tertiary|secondary|primary",
    grade="A",
    basis="실제 보행 가능 도로망을 그대로 쓴다. 안산 24개 동으로 클립 후 way 8,157개 → "
          "노드 34,263 · 간선 39,940 · 평균 간선장 36m. foot=no / access=private 은 제외",
    source="OpenStreetMap Overpass API 추출 (data/raw/ansan_walk.geojson) · 2026-09-21 수집",
    note="종전 GRAPH_STEP_M(100m 격자 8-근접, C등급)을 대체. 연결요소 1,406개(80.6%) → "
         "105개(94.3%). 우회예산 δ 0→40% 저활성 감소가 8.6% → 25.8% 로 3배가 됐다 "
         "— 우회할 길이 실제로 생겼다는 뜻이다. "
         "다만 저활성 노출 감소율 자체는 19% → 19.7% 로 제자리다. 정황상 병목이 "
         "'우회할 길이 없다'에서 '우회해 갈 밝은 곳이 없다'(점수 해상도)로 옮겨간 것으로 "
         "보이나 이는 검증되지 않은 가설이다 — 해상도만 바꿔 개선되는지 봐야 한다 (#04·#05)",
)

SNAP_M = reg(
    "SNAP_M", value=1.0, grade="X",
    basis="OSM 좌표를 1m 격자로 반올림해 노드를 병합한다. 끊어져 들어온 way 들이 "
          "교차로에서 실제로 이어지게 하려는 계산 편의이며 결과에 영향이 없다",
    source="재현성 목적",
)

SCORE_UNIT = reg(
    "SCORE_UNIT", value="100m 셀 (노드가 아님)", grade="B",
    basis="분위(percentile)를 100m 셀에서 매기고 보행 노드는 최근접 셀 값을 물려받는다. "
          "노드 집합에서 직접 매기면 인구 상위25% 셀에 노드 13,710개(40.0%), "
          "하위25% 셀에 5,192개(15.2%)로 2.6배 몰려 분위의 의미가 달라진다",
    source="실측 #05 — 셀 10,270 / 노드 34,263 의 인구분위별 분포",
    note="영향은 제한적이다. 노드분위로 바꾸면 저활성 판정이 뒤바뀌는 간선 3.6%, "
         "경로 간선 일치도 90.0%, 저활성 노출 감소 19.7% → 18.1%. "
         "가중합 폐기의 근거였던 불안정(일치도 46% · 85% 변동)보다 훨씬 작다. "
         "#04 에서 이를 핵심 설계인 양 서술한 것은 과장이었다 (#05 에서 정정)",
    replace="DS-082(100m)·DS-032(50m) 실데이터가 오면 셀이 곧 실측 단위가 되어 "
            "이 선택의 여지 자체가 줄어든다",
)

NODE_CELL_MAX_M = reg(
    "NODE_CELL_MAX_M", value=150.0, grade="B",
    basis="보행 노드가 물려받을 100m 셀의 최대 허용 거리. 셀 대각선(141m)보다 살짝 크게 잡아 "
          "경계 노드가 누락되지 않게 한다. 실측 중앙값 42m · 초과 4.5%",
    source="CELL_M=100 의 대각선 141m",
    replace="DS-082(100m) 또는 DS-032(50m) 실데이터가 오면 셀이 촘촘해져 이 값이 줄어든다",
)

ANCHOR_R_M = reg(
    "ANCHOR_R_M", value=100, grade="B",
    basis="기획 원안의 '반경 100m'를 그대로 쓴다. 밤에 편의점 간판이 눈에 들어오고 "
          "위급 시 뛰어들 수 있는 거리로 100m는 타당한 범위이며, "
          "카드 블록 한 칸(100m급)과도 일치해 경계가 어긋나지 않는다",
    source="기획 원안 + 인벤토리 DS-048 blk_cd 해상도",
    replace="보행 네트워크 확보 시 '직선 100m'가 아니라 '보행 100m'로 바꿀 수 있다",
)

# ══ 점수 ════════════════════════════════════════════════════
DARK_Q = reg(
    "DARK_Q", value=0.25, grade="B",
    basis="'저활성 구간'의 정의. 활성도 하위 25% 분위 미만인 간선을 저활성으로 본다. "
          "절대 기준선을 그을 근거가 없어 분위수를 쓴다 — 통신·카드 값이 표본 확대 "
          "추정치라 절대값 비교가 금지돼 있기 때문이다(인벤토리 Q-21)",
    source="인벤토리 05_데이터품질_주의 Q-21",
    note="이 값은 '어느 구간을 빨갛게 칠할지'만 정한다. 경로 계산 자체에는 안 들어간다",
)

FLOW_AGE = reg(
    "FLOW_AGE", value=["20", "25", "30", "35", "40", "45", "50"], grade="B",
    basis="기획 원안의 '20~50대'. DS-014/032의 컬럼은 5세 단위 M_20_CNT~F_50_CNT이므로 "
          "20~54세가 실제 범위가 된다. 심야 보행 수요의 주축(야근 귀가·심야 산책)이고, "
          "10대 미만·70대 이상은 심야 표본이 얇아 값이 튄다",
    source="인벤토리 03_컬럼사전 DS-014 컬럼 6~31",
    note="FORN_GB='N'(내국인)만 합산한다. 국적코드 행을 같이 더하면 이중계산(Q-21 관련)",
)

# ══ 경로 ════════════════════════════════════════════════════
DETOUR = reg(
    "DETOUR", value=0.20, grade="X",
    basis="근거가 필요 없다. '최단거리보다 몇 % 더 걸어도 좋은가'는 시민이 화면에서 "
          "직접 정하는 값이다. 0.20은 슬라이더의 초기 위치일 뿐이다",
    source="—",
    note="★ 3안이 가중치를 없앤 자리. 4안의 p-median 전환과 같은 성격이다. "
         "자세한 것은 route.py 상단 주석",
)

ALPHA_MAX = reg(
    "ALPHA_MAX", value=50.0, grade="X",
    basis="우회예산 δ를 만족하는 α를 이분탐색할 때의 탐색 상한. "
          "α가 이 값에서도 우회예산을 다 못 쓰면 더 키워도 경로가 안 바뀐다",
    source="—",
)

BISECT_ITER = reg(
    "BISECT_ITER", value=18, grade="X",
    basis="이분탐색 반복 횟수. 2^-18 ≈ 4e-6 로 α가 수렴한다",
    source="—",
)

WALK_MPS = reg(
    "WALK_MPS", value=1.2, grade="C",
    basis="근거 없음. 보행속도를 1.2m/s(4.3km/h)로 가정. 화면의 '+N분' 표시에만 쓰이고 "
          "경로 선택에는 영향을 주지 않는다",
    source="미인용",
    replace="도로교통공단 보행자 횡단 설계 기준(1.0~1.2m/s) 인용 시 B등급",
)


# ══ 시연 프로토타입 (임의값 인벤토리 데이터) ══════════════════════
# scope="proto" 는 PROTO 목록에만 들어간다. 본체 근거 대장(P)·기존 앱 화면은 바뀌지 않는다.
# 쓰는 곳: src/synth_inventory.py · src/ingest_inventory.py · src/night_core.py · src/proto_app.py

SYNTH_DATA = reg(
    "SYNTH_DATA", scope="proto",
    value="DS-001·004·008·014·048·054·082 + 보안등·CCTV 표준데이터", grade="C",
    basis="★ 시연 프로토타입의 유동인구·카드결제·OD·보안등·CCTV 수치는 전부 임의값이다. "
          "인벤토리 규격(파일명·컬럼명·코드값·인코딩 cp949)만 실물과 같고 값은 실데이터가 아니다. "
          "길(OSM 보행망)·상가 위치(소상공인)·버스 노선(TAGO)·인구 총량(SGIS)만 실데이터다. "
          "이 화면의 어떤 활성 수치도 보고서에 인용하지 않는다",
    source="src/synth_inventory.py — 잠재 모형 1개에서 규격 파일 9종을 만든다(서로 앞뒤가 맞게)",
    need="★ 인벤토리 86종 실데이터 납품. 도착하면 ingest_inventory.py 의 입력 폴더만 원본으로 바꾼다",
)

SYNTH_SEED = reg(
    "SYNTH_SEED", scope="proto", value=20260611, grade="X",
    basis="임의값 생성 시드. 같은 시드면 같은 파일이 나온다(재현성 목적)",
    source="—",
)

SYNTH_MONTH = reg(
    "SYNTH_MONTH", scope="proto", value="202606", grade="X",
    basis="임의값을 만드는 기준월. 실데이터 보유기간(202501~202606) 중 DS-054 가 있는 마지막 달. "
          "2026-06-01 이 월요일이라 요일별 밤이 4~5회씩 고르게 들어간다",
    source="인벤토리 02 DS-054 보유기간 202601~202606",
)

SLOT_NIGHT_OF = reg(
    "SLOT_NIGHT_OF", scope="proto", value="0·1시 행은 전날 밤으로 묶는다", grade="B",
    basis="시민이 말하는 '금요일 밤 1시'는 달력으로 토요일 01시다. 원자료 일자(ETL_YMD·ta_ymd)를 "
          "그대로 요일로 바꾸면 금요일 밤의 0·1시가 토요일 밤으로 잘못 들어간다. "
          "실측 헤더상 DS-014·008·004·001·054 가 전부 일 단위(예: 20260501)라 이 처리가 가능하다",
    source="인벤토리 04_규격_실측_비교 샘플 행(DS-014 37,200행 = 25동×24시×31일×내외국인 2)",
    note="요일 7 × 시각 4(22·23·0·1) = 28개 시간대",
)

SLOT_PCT_POOL = reg(
    "SLOT_PCT_POOL", scope="proto", value="28개 시간대 × 셀을 한 분포로 합쳐 분위", grade="B",
    basis="분위를 시간대마다 따로 매기면 어느 시간대든 하위 25%가 정의상 늘 25%라 "
          "'화 01시가 금 23시보다 사람 드문 길이 많다'를 보일 수 없다. 시간대를 합쳐 순위를 매기면 "
          "같은 잣대로 비교된다. 순위만 쓰므로 절대값 금지(Q-21)와도 맞는다",
    source="인벤토리 05_데이터품질_주의 Q-21",
    note="한 시간대 안의 경로 선택도 영향을 받는다 — min 이 어느 항을 따를지가 전체 분포 기준으로 정해지기 때문",
)

FLOW_FORM = reg(
    "FLOW_FORM", scope="proto",
    value="유동 = max(분위(주민 보행), 분위(방문 결제)) · 주민 보행 = DS-008 도보 출발 × DS-082 거주 비중",
    grade="B",
    basis="① 주민 보행은 DS-008 의 도보(TRANS_GB=3) 출발 통행량을 그대로 쓴다. 문서의 "
          "'DS-014 유동인구 × 도보 비중'은 자정 이후 집에 들어온 사람까지 곱해져 "
          "01시가 22시보다 걷는 사람이 많다는 쪽으로 기운다(유동인구는 '그 자리에 있는 사람'이다). "
          "② 문서의 Phase 2 계획(동 유동인구를 DS-082 100m 거주인구로 안분)은 상가만 있는 셀을 0 으로 만든다. "
          "실측(OSM 주거건물 28,268동 × 3안 cells.csv): 심야 앵커가 있는 셀 1,749개 중 35.0% 가 주거건물 0, "
          "거주 기준으로 안분하면 27.6% 가 유동 하위 25% 로 떨어진다(지금의 1km 균등 안분은 2.9%). "
          "min 은 낮은 쪽을 따르므로 앵커가 이 오차를 메우지 못한다. '사람이 있다'를 "
          "'주민이 걷는다 OR 방문객이 있다'(선언 → max)로 바꿔 가중치 없이 보정한다. "
          "방문 신호 = DS-054 결제건수 중 앵커·유흥을 뺀 업종(음식 등)",
    source="실측 — data/base/osm_homes.json(OSM 주거건물) × data/processed/cells.csv (수정사항 #09)",
    replace="DS-032(50m 유동인구, 방문객 포함 실측)가 들어오면 두 항을 그것 하나로 대체한다",
    need="DS-032 내부 사용 승인",
    note="두 항 모두 반경 100m(ANCHOR_R_M) 안의 합. 0 이 많은 항이라 동점은 최솟값 순위로 매긴다 — "
         "결제가 없는 곳이 평균 순위(0.3 안팎)를 받아 '사람이 있는 곳'으로 둔갑하지 않게",
)

ACT_TIEBREAK = reg(
    "ACT_TIEBREAK", scope="proto", value="사전식(min → max)", grade="X",
    basis="활성도 = min(유동, 앵커) 이 같으면 나머지 한 항(max)이 큰 쪽을 더 밝게 본다. "
          "산업단지·공원처럼 두 항이 모두 0 인 셀이 길이의 25% 를 넘으면 임계가 동점 값에 걸려 "
          "'사람 드문 구간'이 하나도 안 잡히는 문제를 막는다. 가중치 없는 순서 규칙이다",
    source="계산 규칙",
)

ACTIVE_NIGHT_SHARE = reg(
    "ACTIVE_NIGHT_SHARE", scope="proto", value=0.5, grade="B",
    basis="블록의 앵커 업종 결제가 그 요일·시각의 밤 가운데 절반 이상에서 발생하면 "
          "'그 시각에 대체로 문을 연다'로 본다(과반 규칙 = 운영 판단). 결제 '건수'의 크기는 "
          "표본 확대 추정치라 쓰지 않고 발생 여부만 쓴다",
    source="인벤토리 DS-054 cnt · Q-21",
    replace="가맹점 영업시간 실측 자료가 있으면 그것으로 대체",
)

CARD_ANCHOR_NM3 = reg(
    "CARD_ANCHOR_NM3", scope="proto", value=["편의점", "주유소", "PC방"], grade="B",
    basis="3안 심야 앵커 정의(prep.ANCHOR)를 카드 업종 소분류명(card_tpbuz_nm_3)으로 옮긴 것. "
          "DS-048 은 중분류(nm_2)까지만 있어 편의점이 '종합소매점' 아래 소분류면 DS-048 로는 "
          "편의점만 골라낼 수 없다 — 그래서 앵커 판정은 DS-054(소분류)로만 한다",
    source="인벤토리 04 DS-054 샘플 행: 소매/유통 > 종합소매점 > 슈퍼마켓",
    need="카드사 업종 분류표(소분류명 전체) — 임의값의 업종명은 지어낸 것이다",
)

CARD_NIGHTLIFE_NM3 = reg(
    "CARD_NIGHTLIFE_NM3", scope="proto",
    value=["요리주점", "일반유흥주점", "호프/맥주", "무도유흥주점", "노래방"], grade="B",
    basis="3안 유흥 정의(prep.NIGHTLIFE)의 카드 소분류명. 앵커에서도, 방문 신호에서도 뺀다 — "
          "유흥 결제로 '사람이 있다'를 세면 경로가 유흥가로 끌려간다",
    source="prep.NIGHTLIFE",
    need="카드사 업종 분류표(소분류명 전체)",
)

CARD_BLOCK_XY = reg(
    "CARD_BLOCK_XY", scope="proto", value="임의 규칙(blk_cd → 약 100m 격자 중심)", grade="C",
    basis="카드 블록코드(blk_cd)는 실측상 6자리 정수(예: 159533 · 163698)이고 규격서 설명은 "
          "'좌표계 WGS84 자체 그리드'뿐이다. 블록 → 좌표 변환표가 인벤토리 86종 어디에도 없다. "
          "프로토타입은 임의 규칙으로 좌표를 붙였다",
    source="인벤토리 04_규격_실측_비교 DS-048·054 샘플 행 · 09_파일목록(경계 파일 없음)",
    need="★ 카드사 블록 경계(또는 중심좌표) 파일 — 없으면 DS-048·054 를 지도에 올릴 수 없다",
)

LIGHT_R_M = reg(
    "LIGHT_R_M", scope="proto", value=20, grade="C",
    basis="근거 없음. 보안등 한 개가 간선을 '비춘다'고 볼 거리를 20m 로 가정했다",
    source="미인용",
    replace="안산시 보안등 설치 기준(간격·조도) 또는 KS 도로조명 기준 인용 시 B",
    need="안산시 보안등 설치 기준",
)

CCTV_R_M = reg(
    "CCTV_R_M", scope="proto", value=50, grade="C",
    basis="근거 없음. CCTV 가 간선을 비춘다고 볼 거리를 50m 로 가정했다",
    source="미인용",
    replace="CCTV 촬영 반경·화각 기준 인용 시 B",
    need="안산시 CCTV 설치·촬영 기준",
)

SEG_MIN_M = reg(
    "SEG_MIN_M", scope="proto", value=100, grade="X",
    basis="화면에서 '구간 N곳'으로 셀 최소 길이. 짧은 토막까지 세면 N 이 부풀려진다. "
          "표출 기준일 뿐 활성도·경로 계산에는 영향이 없다",
    source="—",
)

WALK_TRIP_MAX_M = reg(
    "WALK_TRIP_MAX_M", scope="proto", value=2500, grade="C",
    basis="근거 없음. 심야 귀가를 '걸어서' 한다고 볼 최대 직선거리를 2.5km 로 가정했다. "
          "동 간 OD(DS-004)에 이동수단이 없어서 생긴 자리다",
    source="미인용",
    replace="DS-005(행정동 OD × 이동수단)에서 도보 통행의 거리 분포를 산출하면 B",
    need="DS-005 사용(대민개방 O — 승인 불필요)",
)

OD_SAMPLE = reg(
    "OD_SAMPLE", scope="proto", value={"origins": 300, "per_origin": 10, "seed": 11}, grade="X",
    basis="개선 우선 구간을 구할 때 뽑는 귀가 통행 표본(출발 300곳 × 도착 10곳)과 시드. "
          "계산 편의와 재현성 목적",
    source="—",
)

BUS_WALK_MAX_M = reg(
    "BUS_WALK_MAX_M", scope="proto", value=1000, grade="X",
    basis="집에서 직선 1km 안의 정류장만 후보로 보여준다. 화면 범위일 뿐 순위 계산에는 영향이 없다",
    source="—",
)

ALPHA_GRID = reg(
    "ALPHA_GRID", scope="proto",
    value=[0, 0.25, 0.5, 1, 1.5, 2, 3, 4, 6, 8, 12, 16, 24, 32, 50], grade="X",
    basis="route.plan 의 α 이분탐색 대신 α 격자의 경로를 한 번에 구해 δ 마다 고른다"
          "(앱 전환 검토 §4-3 'α 이산화'). 같은 경로 집합에서 '+N분 ↔ 사람 드문 구간' 곡선이 바로 나온다. "
          "이분탐색과의 차이는 tests/test_proto.py 가 측정한다",
    source="3안 설명/앱 전환 검토.md §4",
)

PRIORITY_TOP_N = reg(
    "PRIORITY_TOP_N", scope="proto", value=15, grade="X",
    basis="개선 우선 구간 표에 보여줄 개수. 표출 기준",
    source="—",
)
