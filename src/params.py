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
# 검증 실험 전용(scope="exp") — 본체 계산 방식을 바꿔 보는 스위치. 기본값은 늘 현행과 같은 결과를 낸다.
# 채택하면 본체 목록(P)으로 옮기고 문서의 파라미터 개수를 함께 고친다 (수정사항 #13)
EXP: List[Param] = []


def reg(name, scope="core", **kw):
    p = Param(name=name, scope=scope, **kw)
    {"proto": PROTO, "exp": EXP}.get(scope, P).append(p)
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
    value="유동 = 분위(DS-032 50m 유동인구) — DS-032 가 있을 때(#20). 없으면 max(분위(주민 보행), 분위(방문 결제)) · "
          "주민 보행 = DS-008 도보 출발 × DS-082 거주 비중",
    grade="B",
    basis="① 주민 보행은 DS-008 의 도보(TRANS_GB=3) 출발 통행량을 그대로 쓴다. 문서의 "
          "'DS-014 유동인구 × 도보 비중'은 자정 이후 집에 들어온 사람까지 곱해져 "
          "01시가 22시보다 걷는 사람이 많다는 쪽으로 기운다(유동인구는 '그 자리에 있는 사람'이다). "
          "② 문서의 Phase 2 계획(동 유동인구를 DS-082 100m 거주인구로 안분)은 상가만 있는 셀을 0 으로 만든다. "
          "실측(OSM 주거건물 28,268동 × 3안 cells.csv): 심야 앵커가 있는 셀 1,749개 중 35.0% 가 주거건물 0, "
          "거주 기준으로 안분하면 27.6% 가 유동 하위 25% 로 떨어진다(지금의 1km 균등 안분은 2.9%). "
          "min 은 낮은 쪽을 따르므로 앵커가 이 오차를 메우지 못한다. '사람이 있다'를 "
          "'주민이 걷는다 OR 방문객이 있다'(선언 → max)로 바꿔 가중치 없이 보정한다. "
          "방문 신호 = DS-054 결제건수 중 앵커·유흥을 뺀 업종(음식 등). "
          "③ #20 — DS-032(50m · 시간대별)가 있으면 계획대로 두 항을 그것 하나로 대체한다. 다른 꼴(max(주민 보행, 방문 결제, DS-032) · "
          "시간대별 비중)도 견줘 봤다. 민간 실데이터 판에서 잰 값과 한계는 내부 기록(3안 수정사항 #20)에만 둔다 — "
          "비개방 자료로 잰 값은 공유본에 싣지 않는다(화면의 주의 문구는 실행 때 자료에서 잰다)",
    source="실측 — data/base/osm_homes.json(OSM 주거건물) × data/processed/cells.csv (수정사항 #09) · DS-032 (민간 실데이터 판 · 내부 기록 #20)",
    replace="통신사 산출 기준(시간대 · 날짜 경계 · 소수 칸 처리)으로 시간대 값의 뜻을 확인하면 A",
    need="DS-032 산출 기준서(통신사) — 시간대별 값을 어떻게 집계하는가(날짜 경계 · 소수 칸 처리). 동 유동인구 DS-014 도 같은 질문",
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
    "CARD_ANCHOR_NM3", scope="proto", value=["편의점", "주유소", "PC방", "인터넷PC방"], grade="B",
    basis="3안 심야 앵커 정의(prep.ANCHOR)를 카드 업종 소분류명(card_tpbuz_nm_3)으로 옮긴 것. "
          "DS-048 은 중분류(nm_2)까지만 있어 편의점이 '종합소매점' 아래 소분류면 DS-048 로는 "
          "편의점만 골라낼 수 없다 — 그래서 앵커 판정은 DS-054(소분류)로만 한다. "
          "PC방은 소분류 표기가 'PC방' · '인터넷PC방' 두 가지일 수 있어 둘 다 둔다(#20)",
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
          "프로토타입은 임의 규칙으로 좌표를 붙였다. 구글 드라이브 원본(#18 · #19)에도 블록 좌표표가 없어, 민간 실데이터 판은 "
          "카드 결제를 지도에 올리지 못하고 앵커를 상가정보 심야 업종 위치로 대신한다(영업 여부 모름)",
    source="인벤토리 04_규격_실측_비교 DS-048·054 샘플 행 · 09_파일목록(경계 파일 없음) · ../data/드라이브_DS대응.csv",
    need="★ 카드사 블록 경계(또는 중심좌표) 파일 — 없으면 DS-048·054 를 지도에 올릴 수 없다",
)

LIGHT_R_M = reg(
    "LIGHT_R_M", scope="proto", value=20, grade="B",
    basis="보안등이 길을 '비춘다'고 보는 거리. 안산시 보안등 실데이터(24개 동 안 9,651개)에서 좌표 → 가장 가까운 보행망 간선 "
          "거리를 재면 중앙값 12.5m · 20m 안 77.5% · 10m 안 26.7% 다. 좌표가 기둥 위치가 아니라 지번 근처로 찍혀 있어"
          "(같은 좌표에 다른 보안등이 여럿 — 9,651행 → 고유 위치 7,750곳) 10m 로 잡으면 4분의 3을 놓친다. "
          "고유 위치 사이 최근접 간격 중앙값 24.4m(간격의 절반 + 좌표 오차)와도 맞는다. 간선 중점이 아니라 선분 전체와의 거리로 잰다",
    source="실측 — src/public_data.py → data/public/derived/report.json (light_dist · light_spacing) · 수정사항 #15",
    replace="보안등 기둥 실측 좌표 또는 안산시 보안등 설치 기준(간격 · 조도) 인용 시 A",
    need="안산시 보안등 설치 기준",
    note="#09 의 임의값 시절에는 C(근거 없음)였다. 값은 그대로 두고 근거만 실측으로 바뀌었다",
)

CCTV_R_M = reg(
    "CCTV_R_M", scope="proto", value=50, grade="C",
    basis="근거 없음. CCTV 가 간선을 비춘다고 볼 거리를 50m 로 가정했다. "
          "공개된 안산 CCTV 가 500대뿐(일부)이라 지금은 계산에 쓰지 않는다(FACILITY_PARTIAL) — 전수 자료가 오면 쓴다",
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


# ══ 공개 실데이터 (승인 · 인증키 없이 받은 실데이터 — 수정사항 #15) ══════════════════
# 받기: src/collect_public.py → data/public/raw   정제: src/public_data.py → data/public/derived → (ingest) data/proto
# 근거: src/validate_public.py → data/public/evidence_public.json. 본체 P(15개)와 validate.py 는 건드리지 않는다

PUBLIC_DATA = reg(
    "PUBLIC_DATA", scope="proto",
    value="보안등(안산시 2022-12) · 역 시간대별 하차(코레일 월별) · 경찰 시설 · 역 위치(OSM) · CCTV · 비상벨 공개분(일부)",
    grade="B",
    basis="승인 · 인증키 없이 받은 실데이터. 보안등은 안산시가 공공데이터포털에 올린 전수 목록(12,938개 — 대부동 · 경계 밖 3,287개를 빼면 "
          "24개 동 안 9,651개)이라 "
          "그대로 쓴다. 다만 2022-12-20 기준이고(차기 등록 예정일 2023-12-20 이 지났는데 갱신 없음) 골목 보안등만 있어 큰길 가로등은 빠져 있다"
          "(MAJOR_ROAD). 코레일 역별 시간대 하차는 승하차 게이트 실측이라 밤 10시 이후 역에서 내려 걷기 시작하는 사람을 세는 유일한 공개 자료다. "
          "CCTV · 비상벨은 일부만 공개돼 계산에 쓰지 않는다(FACILITY_PARTIAL)",
    source="src/collect_public.py → data/public/raw/MANIFEST.json (출처 · 받은 날 · sha256)",
    replace="보안등 최신본 · 가로등 · CCTV 전수가 오면 A",
    need="안산시 가로등 위치(도로과) · 보안등 최신본 · CCTV 전수(도시정보센터)",
    note="사람 수 · 카드 결제 · 이동(인벤토리 7종)은 여전히 임의값이다(SYNTH_DATA). 화면에 실데이터 · 임의값 배지를 따로 단다",
)

MAJOR_ROAD = reg(
    "MAJOR_ROAD", scope="proto",
    value=["trunk", "trunk_link", "primary", "primary_link", "secondary", "secondary_link", "tertiary", "tertiary_link"],
    grade="B",
    basis="보안등 자료에는 골목 보안등만 있고 큰길 가로등은 없다 — 실측: 호수동 0개 · 성포동 11개 · 중앙동 57개(초지동은 1,601개). "
          "그래서 OSM 도로 등급이 이 목록인 간선은 '가로등 구간'으로 따로 두고 '보안등 없음'으로 세지 않는다. "
          "보안등 대조 · 조명 검토는 골목(나머지 등급)에서만 판정한다",
    source="data/raw/ansan_walk.geojson 의 highway 태그 · data/public/derived/report.json (lights_by_dong · edge_road)",
    replace="안산시 가로등 위치가 오면 큰길도 실측으로 판정",
    need="안산시 가로등 위치(도로과)",
)

FACILITY_PARTIAL = reg(
    "FACILITY_PARTIAL", scope="proto", value="CCTV · 비상벨은 지도에 표시만 하고 계산하지 않는다", grade="B",
    basis="공개 표준데이터의 안산 CCTV 500대(2019-08 기준) · 비상벨 500개(2020-04 기준)는 일부다 — 전국본에서 경기 시군 다수가 "
          "정확히 500행이고(기관당 500행에서 잘림), 안산분은 상록구 남쪽 동(본오1 · 일동 · 사동 · 이동 · 사이동 · 해양동 등)에 몰려 있다. "
          "'CCTV 없음'으로 판정하면 단원구는 공개분이 중앙동 1대뿐이라 거의 전부 CCTV 가 없다고 나온다",
    source="data/public/raw/MANIFEST.json (gyeonggi_rows_by_institution) · data/public/derived/report.json (CCTV_partial · 비상벨_partial)",
    need="★ 안산시 CCTV 전수 위치(도시정보센터) — 공공데이터포털 인증키로 행안부 CCTV 정보 API 를 쓰는 방법도 있다",
)

POLICE_NIGHT = reg(
    "POLICE_NIGHT", scope="proto", value=["지구대", "파출소"], grade="B",
    basis="'밤에 열려 있는 곳'으로 지구대 · 파출소만 센다(24시간 교대 근무). 치안센터는 주간 운영 · 유휴가 많고, "
          "경찰서는 민원 창구가 밤에 닫는다. 위치는 OSM(이름에 지구대 · 파출소가 들어간 경찰 시설) — 공식 목록과 대조하지 않았다",
    source="data/public/raw/osm_police_fire.json → data/public/derived/police.csv",
    replace="경찰청 '경기도 지구대(파출소) 현황'(위경도 포함)으로 목록 · 운영 시간을 대조하면 A",
    need="경찰청 경기도 지구대(파출소) 현황 (공공데이터포털 연계 · 경기데이터드림)",
)

STATION_NIGHT_COLS = reg(
    "STATION_NIGHT_COLS", scope="proto", value={"22시": 22, "23시": 23, "24시 이후": 0}, grade="B",
    basis="코레일 시간대별 승하차 표의 칸 이름은 '시작 시각' 기준이다(22시 = 22:00~22:59). 근거: 광역전철 전체 승차가 "
          "23시 칸 633,202명 · 24시 이후 칸 44,908명(2026-09). '끝 시각' 기준이면 24시 이후 칸이 23:00~23:59 운행분인데 "
          "그 시간 승차가 4만 명일 수는 없다. '24시 이후'는 0시 · 1시를 합친 값이라 시간대 0시 · 1시에 같은 값을 쓴다. "
          "요일 구분이 없는 월 합계라 하루 평균(월 합계 ÷ 그 달 일수)만 쓴다",
    source="data/public/raw/korail_시간대별승하차_*.xlsx 노선별 표 · data/public/derived/report.json (korail_cols)",
    replace="코레일에 칸 정의를 확인하면 A",
)

INDUSTRIAL_STATION = reg(
    "INDUSTRIAL_STATION", scope="proto", value={"r_m": 1000, "rule": "제조업 종사자 > 거주인구"}, grade="B",
    basis="역 반경 1km(SGIS 1km 격자를 면적 비례로 자름)에 제조업 종사자가 거주인구보다 많은 역은 산업단지역으로 보고 "
          "밤 하차를 귀가로 세지 않는다. 실측: 원시역 거주 895명 · 종사자 15,884명, 시우역 3,083 · 9,945명. 나머지 역은 종사자가 "
          "거주인구의 18% 이하다. 두 역의 밤 하차는 합쳐 하루 81명(안산 밤 하차의 1.0%)이라 결과에 주는 영향은 작다. "
          "★ 처음에는 원시역 밤 하차를 하루 3,981명(34%)으로 잘못 읽었다 — 코레일 표의 서해선 소계 행이 원시역에 붙은 파서 버그였다(#15)",
    source="data/base/grid_1km.geojson(인구 · 제조업종사자) × data/public/derived/stations.csv · report.json (industrial)",
    replace="DS-004(목적 OD)로 원시역 밤 하차의 목적(귀가 · 출근)을 직접 확인하면 A",
)

STATION_WALK_MAX_M = reg(
    "STATION_WALK_MAX_M", scope="proto", value=1500, grade="C",
    basis="근거 없음. 밤에 역에서 내려 걸어서 집에 간다고 볼 최대 거리를 보행망 거리 1.5km(약 21분)로 가정했다 — 그보다 먼 집은 "
          "버스 · 택시를 탄다고 본다. 내린 사람이 전부 걷는다고 보는 셈이라 흐름은 상대 지수로만 쓴다. "
          "1.0 · 2.0km 로 바꿔 상위 구간이 얼마나 바뀌는지 validate_public.py 가 잰다",
    source="미인용",
    replace="DS-008(시간대 × 이동수단) 도보 통행의 거리 분포 또는 역 도보 접근거리 연구 인용 시 B",
    need="DS-008 사용(대민개방 O — 승인 불필요)",
)

MAP_WALK_MIN = reg(
    "MAP_WALK_MIN", scope="proto", value={"flow": 1.0, "len_m": 10}, grade="X",
    basis="밤길지도(html, #21)에 '역에서 집 가는 밤길'로 그릴 블록의 기준 — 밤 10시~막차 하차 인원이 그 블록을 하루 평균 flow 명 이상 "
          "지난다고 계산된 곳(교차로 사이 블록의 길이 가중 평균), 길이 len_m 이상(1m 짜리 자투리 블록 제외). "
          "화면을 덜 어지럽히려는 표시 기준이라 근거가 필요 없다",
    source="data/public/derived/edge_public.csv(f22 · f23 · f24 — 수정사항 #15)",
)

# ── 민간 실데이터 판의 화면 규칙 (수정사항 #19) — data/real/proto 로 띄울 때만 쓴다. 경로 계산에는 쓰지 않는다 ──
MASK_MIN_POP = reg(
    "MASK_MIN_POP", scope="proto", value=10, grade="C",
    basis="근거 없음(공개 기준 임시값). 100m 격자(DS-082)의 20~54세 거주 인구(월 평균)가 1명 이상 이 값 미만인 칸은 "
          "화면에서 '자료 부족'으로 가린다 — 몇 명 안 사는 칸의 밤 보행이 등급으로라도 드러나지 않게. 거주 0명 칸(상가 · 공단)은 "
          "표본이 적은 게 아니라 사는 사람이 없는 것이라 가리지 않는다. 4안 공개 최소 인원(PUBLIC_MIN_COUNT 5)보다 보수적으로 잡았다. "
          "5 · 10 · 30명일 때 가려지는 칸 수는 ingest_report 'mask_counts'",
    source="미인용 · 인벤토리 Q-17('충분히 집계 · 최소 표본 수 확보한 결과만')",
    need="★ 자료 담당 부서 · 시 개인정보 보호책임자의 공개 최소 인원 기준",
)

GRADE_HI_Q = reg(
    "GRADE_HI_Q", scope="proto", value=0.75, grade="C",
    basis="민간 실데이터 판은 활성도 0~1 을 그대로 보이지 않고 3단계(사람 드묾 · 보통 · 사람 많음)로만 보인다. "
          "아래 경계는 DARK_Q(길이 가중 하위 25%), 위 경계는 이 값(상위 25%)이다 — 표시용 구간이고 근거는 없다",
    source="미인용 · 3안 설명/앱 전환 검토.md 5-②('원시 점수 대신 구간 등급')",
    replace="담당 부서와 공개 등급 수(3~5단계)를 합의하면 X(정책 결정)",
)

MASK_BORROW_SIGMA_M = reg(
    "MASK_BORROW_SIGMA_M", scope="proto", value=100, grade="C",
    basis="실데이터 판 시민 앱(real_app)에서 가린 칸(MASK_MIN_POP)의 유동(DS-032)은 그 칸 값을 쓰지 않고, 가리지 않은 이웃 칸 유동을 "
          "가우스 가중(이 σ, 3σ 안)으로 빌려 채운다. 자기 칸 · 다른 가린 칸은 섞지 않는다. 그 칸의 공개 앵커 항(심야 업종 가게까지 거리)은 그 칸 값을 쓴다. "
          "빌린 값은 화면 등급과 경로 계산에 함께 쓰여, 가린 칸의 원래 유동은 앱 파일(data.js)에도 실리지 않는다. "
          "σ 는 기법 비교(내부 기록 #33 — 블록 평균 · 네모 · H3 · 가우스 σ50~300m · 보행망 이웃 · 기계학습)에서 고른 값이다. "
          "#32 의 MASK_MERGE_M(500m 블록 평균 · 경로는 원래 값)을 #34 에서 이것으로 바꿨다. 공개 기준은 부서 합의 전이라 C",
    source="내부 기록 #33 · #34 · 사용자 결정 2026-11-20(다음 주 적용)",
    replace="담당 부서 · 개인정보 담당과 공개 최소 인원 · 가린 칸 방식을 정하면 B",
    need="★ 공개 최소 인원 기준(MASK_MIN_POP 과 함께)",
)

# ── 시민용 웹 지도 앱 (수정사항 #24 · html/app) — 화면 동작 · 러닝 인증 규칙. 경로 계산(DETOUR · ALPHA_GRID · DARK_Q)은 시연판과 같다 ──
APP_SNAP_MAX_M = reg(
    "APP_SNAP_MAX_M", scope="proto", value=300, grade="X",
    basis="지도에서 누른 곳이 가장 가까운 보행망 지점에서 이 거리보다 멀면 출발 · 도착으로 받지 않는다(안산 밖 · 바다를 누른 경우). "
          "화면 동작 기준이라 근거가 필요 없다",
    source="화면 규칙",
)

APP_ROUTE_OPTIONS = reg(
    "APP_ROUTE_OPTIONS", scope="proto", value={"fast": 0.0, "rec": 0.2, "people": 0.4}, grade="X",
    basis="시민 앱 길 찾기 결과의 세 카드 — 빠른 길(최단, δ 0) · 추천 경로(δ = DETOUR 20%) · 사람 많은 길 우선(δ 40%). "
          "#24 의 '얼마나 더 걸어도 돼요? +10 · 20 · 40%' 질문을 사용자 검토(#28)에서 바꿨다 — 목적지로 가는 사람에게 % 를 묻는 건 어색하다. "
          "3안의 원칙(가중치 대신 시민이 고른다)은 그대로다: 우회 예산 δ 를 숫자 대신 카드로 고른다. 같은 길이 나오면 카드 하나로 합친다. "
          "사용자가 제안한 이름('○○ 우선')은 CLAUDE.md 0절 금지어라 '사람 많은 길 우선'으로 바꿨다",
    source="화면 규칙 · DETOUR · 사용자 검토 #28",
)

RUN_SUGGEST = reg(
    "RUN_SUGGEST", scope="proto", value={"trim_m": 200}, grade="C",
    basis="근거 없음(다음 단계 안내용, #30). 지금 러닝 코스 20개는 시연용 예시이고, 운영에서는 주민이 추천한 길을 담당자가 자료(차 없는 길 · 밤 사람 드문 구간 · "
          "보행 사고 다발지 · 산길)와 현장으로 직접 확인한 뒤 '주민 추천 코스'로 올린다(사용자 결정). 보낼 때 출발 · 도착 근처 trim_m 을 지워 집 위치가 드러나지 않게 한다. "
          "시연판에는 서버가 없어 안내 창만 있다",
    source="사용자 결정 #30",
    replace="개인정보 · 위치정보 담당 검토로 지우는 거리 · 보관 기간을 정하면 B",
    need="★ 위치정보법(개인위치정보) 검토 · 추천 받을 서버 · 검토 담당",
)

RUN_PICK = reg(
    "RUN_PICK", scope="proto", value={"minutes": [15, 30, 45, 60], "default": 30, "window": 0.3, "n": 3, "max_laps": 2}, grade="C",
    basis="근거 없음(화면 규칙, #28). 러닝 탭 첫 화면 '몇 분 달릴 거예요?' — 고른 시간의 ±30% 안에 드는 코스(한 바퀴 코스는 최대 두 바퀴까지 셈)에서 "
          "추천 3개를 고른다: ① 지금 기준(낮 · 밤, RUN_DAYNIGHT)에 가장 맞는 코스 ② 드로잉 런(뱃지) ③ 차 없는 길. 칸에 맞는 코스가 없으면 시간에 가까운 코스로 채운다. "
          "'이런 분께' 문구는 코스 자료(길 종류 · 산길 · 사람 드문 구간 · 그림)로만 만든다 — 오르막 · 노면 · 조명은 자료가 없어 말하지 않는다. "
          "달리기 시간은 RUN_PACE_MIN_KM(1km 6분 30초) 기준",
    source="화면 규칙 · 사용자 검토 #28",
    replace="시범 운영에서 사람들이 고르는 시간 · 실제 페이스로 맞추면 B",
)

RUN_PACE_MIN_KM = reg(
    "RUN_PACE_MIN_KM", scope="proto", value=6.5, grade="X",
    basis="러닝 코스의 '달리기 약 N분' 표시에 쓰는 1km 당 분. 사람마다 다르므로 화면에 기준(1km 6분 30초)을 같이 적는다 — 표시용",
    source="표시 규칙",
)

RUN_DONE = reg(
    "RUN_DONE", scope="proto", value={"cover": 0.8, "r_m": 30, "step_m": 25}, grade="C",
    basis="근거 없음. 러닝 코스 완주 인증 — 코스를 step_m 간격 점으로 나눠, 휴대폰 GPS 기록이 r_m 안으로 지나간 점이 cover 이상이면 완주로 본다. "
          "GPS 오차와 길 건너편으로 달리는 경우를 감안한 임시값. GPS 기록은 휴대폰 밖으로 보내지 않는다",
    source="미인용",
    replace="시범 운영에서 완주자 · 미완주자의 GPS 기록으로 기준을 맞추면 B",
)

# 러닝 코스 고르는 기준 — src/build_runs.py 가 쓴다. 그림 자리 찾기 · 흩어놓기의 탐색 손잡이(격자 · 반복 수 · 벌점 무게)는
# 코스 모양만 바꾸는 값이라 build_runs.py 맨 위 '조정값' 블록에 둔다(CLAUDE.md 2절 예외, 수정사항 #24).
RUN_CAR_FREE_HW = reg(
    "RUN_CAR_FREE_HW", scope="proto",
    value=["path", "footway", "pedestrian", "steps", "track", "cycleway", "bridleway", "corridor"], grade="B",
    basis="'차 없는 길' — OSM highway 태그가 이 목록인 간선(산길 · 오솔길 · 보도 · 보행자 거리 · 계단 · 농로 · 임도 · 자전거길 · 건물 통로). "
          "living_street · service · residential · unclassified 는 차가 들어오므로 넣지 않는다. 태그 뜻은 OSM 위키를 따랐고, "
          "track(농로 · 임도)을 넣은 것은 판단이다 — 차가 드물지만 농기계 · 관리 차량은 다닐 수 있다. "
          "안산 보행망에는 cycleway · bridleway · corridor 간선이 없다. "
          "단 OSM 에 차도 옆 보도로 따로 그린 길(footway=sidewalk · 36.3km, 이 목록 길이의 12.6%)은 #26 부터 빼고 '차도 옆 보도'로 따로 센다 — "
          "#24 의 차 없는 길 코스 하나(초지동)가 97% 보도였다. 큰길 · 골목 자체에 보도가 있는지는 OSM 에 거의 없다(2km 남짓)",
    source="OpenStreetMap wiki Key:highway · data/proto/edge_public.csv (highway · sidewalk)",
    replace="코스 구간을 현장에서 확인(차량 진입 차단 여부)하면 A",
)

RUN_COURSE_KM = reg(
    "RUN_COURSE_KM", scope="proto", value={"drawing": [3.0, 7.0], "carfree": [2.0, 8.0]}, grade="C",
    basis="근거 없음. 러닝 코스 길이 범위(km). 드로잉 런은 그림을 알아볼 만큼 커야 해서 3~7km(5km 안팎), "
          "차 없는 길은 동네 한 바퀴 2~8km. 드로잉 런은 범위를 벗어난 자리에 벌점을 주고, 차 없는 길은 범위 밖 코스를 뺀다",
    source="미인용",
    replace="러닝 앱 · 동호회의 1회 달리기 거리 분포를 인용하면 B",
)

RUN_CF_SHARE_MIN = reg(
    "RUN_CF_SHARE_MIN", scope="proto", value=0.8, grade="C",
    basis="근거 없음. '차 없는 길' 코스로 내놓으려면 코스 길이의 80% 이상이 RUN_CAR_FREE_HW 간선이어야 한다 — "
          "차 없는 길끼리 이을 때 건널목 · 골목을 조금 지나는 것은 허용한다",
    source="미인용",
    replace="시범 운영 의견으로 기준을 맞추면 B",
)

RUN_TRAIL_NOTE = reg(
    "RUN_TRAIL_NOTE", scope="proto", value={"classes": ["path", "track"], "share": 0.4}, grade="C",
    basis="근거 없음. 코스 길이 중 산길 · 오솔길(path) · 농로 · 임도(track) 비중이 share 이상이면 코스 설명에 "
          "'밤에는 불빛이 적을 수 있다'고 적는다. 보안등 공개 자료에는 큰길 가로등 · 공원등이 없고 보안등이 0개인 동도 있어(MAJOR_ROAD) "
          "코스 조명을 직접 재지 못한다 — 그래서 길 종류로만 알린다",
    source="data/proto/edge_public.csv (highway) · MAJOR_ROAD",
    replace="공원등 · 가로등 위치가 오면 코스 조명을 직접 잰다",
    need="안산시 공원등(공원과) · 가로등(도로과) 위치",
)

RUN_DAYNIGHT = reg(
    "RUN_DAYNIGHT", scope="proto", value={"night_hour": 22, "bin": 0.1}, grade="C",
    basis="근거 없음(제안, #26). 러닝 코스를 낮과 밤에 다르게 줄 세운다. "
          "낮 — 차가 같이 다니는 골목 · 단지 길(residential · service 등 — 보도가 있는지는 자료에 없다)이 짧은 순, bin(10%) 단위로 같으면 큰 찻길 옆이 짧은 순. "
          "밤(해 진 뒤) — 사람이 드물거나(그 요일 night_hour 시 활성도가 DARK_Q 아래) 산길 · 농로(RUN_TRAIL_NOTE)인 구간이 짧은 순, 같으면 골목이 짧은 순. "
          "사람 수 자료가 밤 10시~새벽 1시뿐이라 밤 기준은 밤 10시 값을 쓴다. 낮 · 밤은 해 뜨고 지는 시각(NOAA 계산 · 안산 중심)으로 가르고, 이용자가 바꿀 수 있다. "
          "보행 사고가 잦았던 곳(PED_ACC)은 줄 세우기에 넣지 않고 코스마다 알린다",
    source="미인용 · data/proto(활성도 — 임의값) · edge_public.csv(highway · sidewalk) · RUN_TRAIL_NOTE · public_data.sun_times",
    replace="시범 운영에서 낮 · 밤 이용 기록과 의견으로 기준을 맞추면 B",
)

REFRESH_BREAK = reg(
    "REFRESH_BREAK", scope="proto", value={"ratio": 1.5, "min_weeks": 2}, grade="C",
    basis="근거 없음(경고 기준, #36). 월간 갱신(src/refresh_real.py)이 DS-032 를 주 단위로 다시 접은 뒤, 달마다 '0·1시 칸 평균 ÷ 22·23시 칸 평균'이 "
          "전달보다 ratio 배 넘게 오르거나 1/ratio 배 아래로 내려가면 '달 사이 단절'로 경고한다(통신사 산출 방식이 바뀌었을 수 있음 — 내부 기록 #33 의 2026-04 사례를 잡는 정도). "
          "주가 min_weeks 개 미만인 달(기간 끝의 걸친 주)은 보지 않는다. 경고만 하고 계산은 바꾸지 않는다",
    source="미인용 · 내부 기록 #33(달별 집계)",
    replace="통신사 산출 기준서로 달마다 바뀐 점을 확인하면 경고 대신 그 달을 표시하는 규칙(B)",
)

RUN_BANDS = reg(
    "RUN_BANDS", scope="proto", value={"dawn": [5, 6], "eve": [18, 19, 20, 21]}, grade="C",
    basis="근거 없음(사람들이 달리는 시간대 가정, 로드맵 §3 · #35). 실데이터 판 러닝 탭에 새벽(5~7시) · 저녁(6~10시) 기준을 더한다 — DS-032 에서 이 시각(TIME_CD)을 "
          "밤 28칸과 따로 적재하고(요일 구분 없이 시각 × 날짜 평균), 가린 칸은 MASK_BORROW_SIGMA_M 으로 이웃 값을 빌린 뒤 시간대 안에서 칸 유동 분위 → 간선(양 끝 평균) → "
          "길이 가중 DARK_Q · GRADE_HI_Q 로 '사람 드묾 · 보통 · 많음' 3등급만 앱에 싣는다. 앵커(문 연 가게) 항은 쓰지 않는다 — 실데이터에 영업 시간이 없다. "
          "저녁은 밤 시간대(22시~)와 이어지게 21시까지. 공개 판(가상 데이터)에는 이 자료가 없어 낮 · 밤만 보인다",
    source="미인용 · DS-032(TIME_CD 0~23시) · 로드맵 §3 '러닝 시간대 확장 범위' 권고(둘 다)",
    replace="시범 운영의 러닝 기록 시각 분포로 시간대를 맞추면 B",
)

PED_ACC = reg(
    "PED_ACC", scope="proto", value={"types": ["보행노인", "보행어린이", "스쿨존어린이"], "years": 5}, grade="B",
    basis="'보행 사고가 잦았던 곳'(#26) — 한국도로교통공단 교통사고 다발지역 표준데이터 중 보행 사고 유형(65세 이상 보행노인 · 보행 어린이 · "
          "스쿨존 어린이)만, 가장 최근 연도부터 5년(안산 2020~2024: 보행노인 4 · 보행어린이 9 · 스쿨존 12곳). 자전거 다발지는 보행 사고가 아니라 뺀다. "
          "이 표에는 일반 성인 보행자 · 무단횡단 다발지와 사고 한 건 한 건의 위치가 없다 — 그래서 '어르신 · 어린이 보행 사고가 잦았던 곳'이라고만 말한다. "
          "다발지는 사고가 많이 났던 곳이지 지금도 그렇다는 판정이 아니다(그 뒤 도로가 바뀌었을 수 있다). 경로 계산에는 넣지 않고 표시 · 셈만 한다",
    source="공공데이터포털 전국교통사고다발지역표준데이터(15029185) → data/public/derived/accidents.csv",
    replace="사고 한 건 단위 자료(차대사람 · 시각)로 밤 시간 보행 사고만 따로 보면 A",
    need="도로교통공단 TAAS 보행자 사고(전 연령 · 무단횡단) 위치 — 공공데이터포털 활용신청 또는 공단 협조",
)


# ══ 검증 실험 (본체 계산 방식을 바꿔 보는 스위치 — 수정사항 #13) ══════════════
# scope="exp" 는 EXP 목록에만 들어간다. 기본값은 현행과 같은 결과를 낸다 → 본체 근거 대장(P) · 문서 수치 불변.
# 쓰는 곳: src/alloc.py · src/app.py · src/validate.py (python src/validate.py --resolution 이 세 방식을 비교)

POP_ALLOC = reg(
    "POP_ALLOC", scope="exp", value="uniform", grade="C",
    basis="본체 점수 첫 항(야간 유동인구 대체값 = SGIS 1km 격자 인구)을 100m 셀로 나누는 방식. "
          "'uniform'(현행)은 1km 안 100칸에 똑같이 나눈다 — 1km 안이 고르다는 가정이고 근거가 없다. "
          "'homes' 는 1km 합계를 그대로 두고 같은 1km 안의 OSM 주거건물 규모(HOME_W)에 비례해 나눈다. "
          "'homes_or_shops' 는 max(분위(homes), 분위(반경 100m 상가 수 — 앵커 · 유흥 제외)) — '주민이 산다 OR 가게가 있다'(선언, 가중치 없음)로 "
          "homes 가 상가만 있는 셀을 0 으로 만드는 문제(#09 실측 — 앵커 셀 27.6% 가 유동 하위 25%)를 시연판 FLOW_FORM 과 같은 방식으로 보정한다",
    source="수정사항 #13 · src/alloc.py · python src/validate.py --resolution → evidence.json 'resolution'",
    replace="DS-082(100m 거주) 또는 DS-032(50m 유동) 실데이터가 오면 안분 자체가 필요 없어진다",
    need="DS-032 내부 사용 승인 (또는 DS-082)",
    note="기본값 uniform 은 현행과 바이트 단위로 같은 점수를 낸다. 바꾸면 README · 설명 · 기능 · 근거 문서와 보고서의 경로 수치가 바뀐다. "
         "#13 측정(같은 120쌍): 100m 안분은 경로 지표를 올리지만(사전식 동점 처리 기준 저활성 감소 22.5 → 34.0%, 예산 미소진 69.2 → 45.0%) "
         "같은 1km 안에서 자리만 무작위로 섞은 대조군도 37.0% · 48.3% 로 똑같이 오른다 — 경로 지표가 안분의 참거짓을 가리지 못하므로 "
         "실데이터 전까지 기본값을 바꾸지 않는다",
)

HOME_W = reg(
    "HOME_W", scope="exp", value="size", grade="C",
    basis="POP_ALLOC='homes' 에서 주거건물 하나의 규모. 'size' = 세대수(building:flats) > 층수(building:levels) > 1 "
          "(synth_inventory 의 DS-082 임의값과 같은 규칙). OSM 주거건물 28,268동 중 세대수 태그 3,582 · 층수만 269 · "
          "둘 다 없음 24,417(86%, 규모 1) — 태그가 붙은 아파트 단지가 같은 1km 안의 태그 없는 건물보다 수십 배 무겁게 잡힌다. "
          "'count' = 건물마다 1 (태그 편차의 영향을 보는 대조용)",
    source="data/base/osm_homes.json 태그 집계 (수정사항 #13)",
    replace="건축물대장 표제부(세대수)를 건물에 붙이면 B",
    need="건축물대장 표제부 또는 주민등록 집계구 인구",
)

RES_SHUFFLE_SEED = reg(
    "RES_SHUFFLE_SEED", scope="exp", value=13, grade="X",
    basis="해상도 실험의 대조군 시드 — 같은 1km 안에서 셀별 주거건물 규모를 무작위로 섞은 안분(alloc.shuffled). "
          "개선이 '주거건물이 실제로 있는 자리' 덕인지 '1km 안에 높낮이가 생긴 것' 자체 덕인지 가른다. 재현성 목적",
    source="—",
)
