# -*- coding: utf-8 -*-
"""
근거 문서 자동 생성 — params.py + evidence.json → docs/근거대장.md
실행:  python src/gen_docs.py

문서를 손으로 쓰지 않는 이유: 코드와 문서가 갈라지면 문서를 믿을 수 없기 때문.
파라미터를 바꾸면 validate.py 를 돌린 뒤 이 스크립트를 다시 돌린다.
"""
import json, pathlib, sys, datetime
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import params as PM

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
DOCS.mkdir(exist_ok=True)
EVP = ROOT / "data" / "processed" / "evidence.json"

GRADE_DESC = {
    "A": "보유 데이터로 직접 산출 — `src/validate.py` 로 재현 가능",
    "B": "보유 데이터로 타당성을 확인했으나 최종 판단에 운영·정책 요소가 섞임",
    "C": "**근거 없음.** 임의 가정이거나 외부 자료·실증이 있어야 확정 가능",
    "X": "근거 불필요 (시민이 직접 정하는 값 / 계산 편의 / 재현성 목적)",
}


def main():
    ev = json.loads(EVP.read_text(encoding="utf-8")) if EVP.exists() else {}
    c = PM.summary()
    today = datetime.date.today().isoformat()
    L = []
    A = L.append

    A("# 3안 — 파라미터 근거 대장")
    A("")
    A(f"> 자동 생성: `python src/gen_docs.py` · 기준일 {today}")
    A("> 이 문서는 손으로 쓰지 않습니다. `src/params.py` 를 고치고 "
      "`validate.py` → `gen_docs.py` 순으로 다시 돌리십시오.")
    A("")
    A("## 요약")
    A("")
    A(f"전체 **{len(PM.P)}개** 파라미터 중 "
      f"A등급 {c['A']}개 · B등급 {c['B']}개 · **C등급 {c['C']}개** · X등급 {c['X']}개")
    A("")
    A("| 등급 | 개수 | 의미 |")
    A("|---|---|---|")
    for g in "ABCX":
        if c[g]:
            A(f"| **{g}** | {c[g]}개 | {GRADE_DESC[g]} |")
    A("")
    if c["C"]:
        A(f"⚠️ **C등급 {c['C']}개가 남아 있습니다.** 아래 「확보가 필요한 자료」를 참조하십시오.")
        A("")

    for g in "ABCX":
        items = [p for p in PM.P if p.grade == g]
        if not items:
            continue
        A(f"## {g}등급 — {GRADE_DESC[g]}")
        A("")
        for p in items:
            A(f"### `{p.name}` = `{p.value}`")
            A("")
            A(f"**근거** — {p.basis}")
            A("")
            if p.source:
                A(f"- 출처: {p.source}")
            if p.replace:
                A(f"- 등급을 올리려면: {p.replace}")
            if p.need:
                A(f"- 🙋 **요청 자료**: {p.need}")
            if p.note:
                A(f"- 비고: {p.note}")
            A("")

    # ── 인벤토리에서 자동 산출된 제약 ──
    if ev.get("datasets"):
        A("## 데이터 제약 (인벤토리에서 자동 산출)")
        A("")
        A("`validate.py::e_inventory` 가 `안산시_민간데이터_데이터셋_인벤토리_v1.0.backup.xlsx` 를 "
          "직접 읽어 만든 표입니다. 사람이 옮겨 적은 값이 아닙니다.")
        A("")
        k = ["인벤ID", "테이블명(영문)", "공간단위", "시간해상도", "대민개방",
             "보유기간", "총용량(GB)", "총행수(실측/추정)"]
        A("| " + " | ".join(k) + " |")
        A("|" + "|".join(["---"] * len(k)) + "|")
        for r in ev["datasets"]:
            A("| " + " | ".join(str(r.get(x, "")) for x in k) + " |")
        A("")
        A(f"- 심야(22~02시)를 정확히 자를 수 있는 시간대 컬럼: "
          f"**{len(ev.get('hour_ok', []))}종** / 불가 {len(ev.get('hour_ng', []))}종")
        for r in ev.get("hour_ng", []):
            A(f"  - ❌ `{r['ds']}` `{r['col']}` = {r['code']}")
        A(f"- 100m급(블록·셀) 공간단위 {ev.get('fine_total')}종 중 **대민개방 "
          f"{ev.get('fine_open')}종** {ev.get('fine_open_ids')}")
        A(f"- 100m급 **그리고** 심야 절단 가능 = {ev.get('fine_hour_ok')} → "
          f"**그중 대민개방 = {ev.get('fine_hour_ok_open') or '없음'}**")
        A("")
        A("> 마지막 줄이 3안의 구조를 결정합니다. 시민 화면에 그대로 띄울 수 있는 "
          "「100m 해상도 × 심야 시간대」 데이터는 인벤토리 86종 안에 **존재하지 않습니다.** "
          "→ 계산은 비개방 데이터로 하고 **집계 결과만** 공개하는 2층 구조가 불가피합니다.")
        A("")

    # ── 산출 수치 ──
    if ev:
        A("## 산출 수치 (`src/validate.py` 실행 결과)")
        A("")
        A("| 항목 | 값 | 의미 |")
        A("|---|---|---|")
        rows = [
            ("대부동 제외", f"인구>0 격자 {ev.get('grid_all')}개 중 {ev.get('grid_db')}개"
                          f"({ev.get('grid_db',0)/max(ev.get('grid_all',1),1):.0%}), "
                          f"인구 {ev.get('pop_db',0):,}명"
                          f"({ev.get('pop_db',0)/max(ev.get('pop_all',1),1):.1%})",
             "면적은 29%인데 인구는 1%. 바다로 끊겨 격자 그래프가 수면을 지난다"),
            ("심야 앵커 vs 유흥", f"{ev.get('anchor_n'):,} vs {ev.get('nightlife_n'):,} "
                               f"= {ev.get('nightlife_ratio')}배",
             "업종 필터 없이 '결제 발생 가맹점 수'를 세면 유흥가가 1위가 된다"),
            ("보행 그래프", f"노드 {ev.get('nodes'):,} · 간선 {ev.get('edges_n'):,} · "
                        f"연결요소 {ev.get('components'):,}개(최대 {ev.get('giant_pct')}%)",
             "격자 대체 그래프. 실제 도로가 아니라 19%가 섬으로 끊긴다"),
            ("가중합 민감도", f"w=0.25 vs w=4 일치도 {ev.get('w_jaccard_mean',0):.0%}, "
                         f"{ev.get('w_changed_pct')}% 의 쌍에서 경로 변경",
             "기획 원안의 가중합을 그대로 쓰면 가중치가 결과를 지배한다"),
            ("경로 개선", f"저활성 노출 {ev.get('dark_before_m')}m → {ev.get('dark_after_m')}m "
                       f"({ev.get('dark_cut_pct')}% 감소), 거리 +{ev.get('extra_pct')}%",
             f"{ev.get('pairs')}쌍 중 최단경로에 저활성 구간이 있는 {ev.get('pairs_with_dark')}쌍 기준"),
            ("최장 연속 저활성", f"{ev.get('worst_before_m')}m → {ev.get('worst_after_m')}m",
             "'한 번에 얼마나 오래 혼자 걷는가'. 총합보다 체감에 가깝다"),
            ("우회 예산 미소진", f"{ev.get('alpha_saturated_pct')}%",
             "우회를 허용해도 더 나은 길이 없다 = 보행 네트워크가 필요하다는 증거"),
            ("계산 속도", f"{ev.get('route_sec_per_pair')}초/건",
             "실시간 응답 가능"),
        ]
        for a_, b_, c_ in rows:
            A(f"| {a_} | {b_} | {c_} |")
        A("")
        if ev.get("detour_curve"):
            A("### 우회 예산 δ 반응 곡선")
            A("")
            A("| δ | 평균 거리 | 평균 저활성 노출 | 저활성 구간이 남은 쌍 |")
            A("|---|---|---|---|")
            for r in ev["detour_curve"]:
                A(f"| {r['detour']:.0%} | {r['len_m']:,}m | {r['dark_m']}m | "
                  f"{r['pairs_with_dark']} / {ev.get('pairs')} |")
            A("")
            A("> δ를 0%에서 40%까지 올려도 저활성 노출이 크게 줄지 않습니다. "
              "대체 데이터(1km 인구 안분)와 격자 그래프에서는 **우회할 더 나은 길 자체가 없기 때문**입니다. "
              "이 표가 곧 '보행 네트워크와 50m 유동인구가 없으면 이 서비스는 성립하지 않는다'는 증거입니다.")
            A("")

    # ── 요청 자료 ──
    needs = [p for p in PM.P if p.need]
    A("## 🙋 확보가 필요한 자료")
    A("")
    A("| 우선순위 | 파라미터 | 현재값 | 필요한 자료 |")
    A("|---|---|---|---|")
    for i, p in enumerate(sorted(needs, key=lambda x: "★" not in x.need), 1):
        star = "★" if "★" in p.need else ""
        A(f"| {i} {star} | `{p.name}` | {p.value} | {p.need.replace('★','').strip()} |")
    A("")
    A("### 자료 없이도 등급을 올릴 수 있는 경로")
    A("")
    for p in PM.P:
        if p.replace:
            A(f"- `{p.name}` — {p.replace}")
    A("")

    # ── 방법론 ──
    A("## 방법론 결정 기록")
    A("")
    A("### ① 활성도: 가중합 → min(연언) 으로 교체")
    A("")
    A("기획 원안은 `활성도 = 유동인구 밀도 + 결제 가맹점 수 × 가중치` 였습니다. "
      "단위가 다른 두 값을 더하려면 정규화 상수와 가중치가 필요한데 둘 다 근거가 없습니다. "
      f"실제로 가중치를 0.25↔4 로 흔들자 **{ev.get('w_changed_pct','—')}% 의 경로가 바뀌었고 "
      f"간선 일치도는 {ev.get('w_jaccard_mean',0):.0%}** 였습니다.")
    A("")
    A("`min(분위(유동인구), 분위(앵커))` 로 바꾸면 "
      "'사람도 있고 문 연 가게도 있어야 한다'는 연언이 되어 가중치가 사라집니다. "
      "4안이 집객력 가중합을 p-median 으로 교체한 것과 같은 성격의 결정입니다.")
    A("")
    A("### ② 경로: α 고정 → 우회 예산 δ 역산")
    A("")
    A("`cost = 거리 × (1 + α·어두움)` 의 α 도 근거를 댈 수 없습니다. "
      "대신 시민이 '최단거리보다 몇 % 더 걸어도 좋은가(δ)' 를 정하면 "
      "그 예산을 다 쓰는 최대 α 를 이분탐색으로 역산합니다. "
      "근거가 필요한 상수가 0개가 되고, 결과가 '+N분 / 저활성 M m 감소' 로 검증 가능해집니다.")
    A("")
    A("### ③ 업종 필터는 선택이 아니라 필수")
    A("")
    A(f"안산 상가에서 심야 결제가 발생하는 업종을 세면 유흥 {ev.get('nightlife_n','—')}곳 > "
      f"심야 앵커(편의점·주유소·PC방) {ev.get('anchor_n','—')}곳으로 "
      f"{ev.get('nightlife_ratio','—')}배입니다. 필터 없이 결제 건수를 세면 "
      "**점수 1위가 유흥가로 나옵니다.** 유흥가는 심야 활성도는 최고지만 그것이 "
      "안전의 근거는 아닙니다.")
    A("")
    A("### ④ 서비스명에서 '안심'을 뺄 것")
    A("")
    A("유동인구와 카드결제는 **활성(사람이 있음)** 의 지표이지 **안전(범죄가 없음)** 의 지표가 "
      "아닙니다. 지자체가 '안심 귀갓길' 이라고 안내한 경로에서 사고가 나면 책임 문제가 됩니다. "
      "화면 문구는 `사람이 많은 길 · 불 켜진 길` 로 쓰고, 안전 주장은 하지 않습니다. "
      "범죄 데이터(경찰청 5대 범죄 발생 지점)를 확보하기 전까지 이 원칙을 유지합니다.")
    A("")

    # ── 시연 프로토타입 · 공개 실데이터 (본체와 별도 목록 PM.PROTO) ──
    if getattr(PM, "PROTO", None):
        cp = PM.summary(PM.PROTO)
        A("## 시연 프로토타입 · 공개 실데이터 파라미터 (본체 집계에 포함하지 않음)")
        A("")
        A(f"`src/proto_app.py` · `src/public_data.py` 가 쓰는 {len(PM.PROTO)}개 — A {cp['A']} · B {cp['B']} · **C {cp['C']}** · "
          f"X {cp['X']}. ★ 시연 앱의 사람 수 · 카드 결제 · 이동은 임의값(`SYNTH_DATA`)이고, 보안등 · 역 하차 · 경찰 시설 위치는 "
          "공개 실데이터(`PUBLIC_DATA`)입니다.")
        A("")
        A("| 파라미터 | 값 | 등급 | 근거 | 요청 자료 |")
        A("|---|---|---|---|---|")
        for p in PM.PROTO:
            A(f"| `{p.name}` | {str(p.value)[:60]} | {p.grade} | {p.basis[:160]}… | {p.need} |")
        A("")

    # ── 공개 실데이터 근거 (수정사항 #15 — src/validate_public.py) ──
    evp = ROOT / "data" / "public" / "evidence_public.json"
    if evp.exists():
        pv = json.loads(evp.read_text(encoding="utf-8"))
        lt, ld = pv["lights"]["lights"], pv["lights"]["light_dist"]
        bd, cov, sp = pv["lights"]["lights_by_dong"], pv["lights"]["light_cover"], pv["lights"]["light_spacing"]
        A("## 공개 실데이터 근거 (`src/validate_public.py` 실행 결과)")
        A("")
        A("승인 · 인증키 없이 받은 실데이터(`src/collect_public.py` → `data/public/raw`, 출처 · sha256 은 `MANIFEST.json`). "
          "본체 점수에는 넣지 않고 대조 · 시연 화면에만 씁니다.")
        A("")
        A("### 보안등 (안산시 · 공공데이터포털 15017320)")
        A("")
        A(f"- {lt['원행']:,}행 중 24개 동 안 **{lt['동안']:,}개** (대부동 · 경계 밖 {lt['버림']:,}개 제외) · 고유 위치 {lt['고유위치']:,}곳 · "
          f"기준일 {lt['기준일']}")
        A(f"- 큰길 가로등은 자료에 없다: 보안등 0개 동 {bd['없는동']} · 적은 동 {bd['적은동']} · 많은 동 {bd['많은동']}")
        A(f"- 좌표 → 가장 가까운 보행망 간선: 중앙값 {ld['중앙값m']}m · 75% {ld['p75m']}m · 10m 안 {ld['안10m']} · "
          f"**20m 안 {ld['안20m']}** (`LIGHT_R_M`) · 고유 위치 간 간격 중앙값 {sp['중앙값m']}m")
        A(f"- 골목 {cov['골목km']}km 중 보안등 20m 안 {cov['보안등있음']} · 큰길(가로등 구간) {cov['큰길km']}km")
        A("")
        A("### CCTV · 비상벨 공개분은 일부다")
        A("")
        for k, v in pv["partial"].items():
            if "exactly_500" in v:
                A(f"- `{k}`: 전국 {v['national_rows']:,}행 · 경기 제공기관 {v['gyeonggi_institutions']}곳 중 "
                  f"**정확히 500행인 기관 {v['exactly_500']}곳** · 안산 {v['ansan_rows']}행")
            elif "상위7개동비중" in v:
                A(f"- {v['verdict']}: 상위 7개 동 비중 {v['상위7개동비중']} {v['상위7개동']}")
        A("")
        ct = pv["crosstab"]
        A("### ★ 본체 활성도(실데이터 대체재) × 보안등(실데이터) — 골목만")
        A("")
        A("| | 사람 많음 | 저활성 |")
        A("|---|---|---|")
        A(f"| 보안등 있음 | {ct['lit_busy']}km | **{ct['lit_dark']}km** ({ct['lit_dark_share_of_lit']}%) |")
        A(f"| 보안등 없음 | {ct['unlit_busy']}km | {ct['unlit_dark']}km |")
        A("")
        A(f"골목 {ct['minor_km']}km · 큰길 {ct['major_km']}km(가로등 구간, 판정 제외) · 저활성 임계 {ct['threshold']} · "
          f"보안등 있는데 저활성인 100m 이상 구간 {ct['lit_dark_segments_100m']}곳 · 동별 상위 {ct['lit_dark_by_dong_km']}")
        A("")
        s = pv["stations"]
        A(f"### 역별 밤 하차 (코레일 {s['month']} · 하루 평균) — 합 {s['night_total']:,}명")
        A("")
        A("| 역 | 노선 | 22시대 | 23시대 | 자정 이후 | 밤 합 | 반경 1km 거주 | 제조업 종사자 | 산업단지역 |")
        A("|---|---|---|---|---|---|---|---|---|")
        for r in s["table"]:
            A(f"| {r['station']} | {r['line']} | {r['a22']} | {r['a23']} | {r['a24']} | **{r['night']}** | "
              f"{r['pop_r']:,.0f} | {r['mfg_r']:,.0f} | {'예' if r['industrial'] else ''} |")
        A("")
        kc = pv["korail_cols"]
        A(f"- 칸 정의(`STATION_NIGHT_COLS`): {kc['노선']} 승차 22시 {kc['승차_22시']:,} · 23시 {kc['승차_23시']:,} · "
          f"24시 이후 {kc['승차_24시이후']:,} → 칸 이름은 시작 시각 기준")
        A("")
        sw = pv["station_walk"]
        d = sw["runs"][str(sw["default_max_m"])] if str(sw["default_max_m"]) in sw["runs"] else sw["runs"][sw["default_max_m"]]
        A(f"### 밤 역 귀갓길 × 보안등 없는 골목 (`STATION_WALK_MAX_M` = {sw['default_max_m']:,}m)")
        A("")
        A(f"하루 {d['assigned_per_night']:,}명이 보행망으로 집까지 걷는다고 보면(사람 × 거리 기준) **보안등 없는 골목 "
          f"{d['unlit_minor_share_pm']}%** · 큰길 {d['major_share_pm']}% · 보안등 있는 골목 {d['lit_minor_share_pm']}%. "
          f"단위는 {sw.get('unit', '블록')}이고, 보안등이 하나도 없는 골목 블록 {d['blocks']}곳 중 본체 기준 저활성이 과반인 블록은 "
          f"{d['blocks_dark']}곳(사람·m 의 {d['pm_share_blocks_dark']}%)이다.")
        A("")
        A("| 최대 보행 거리 | 보안등 없는 골목 비중 | 상위 15곳 블록 일치(기본값 대비) |")
        A("|---|---|---|")
        for mx, r in sw["runs"].items():
            A(f"| {int(mx):,}m | {r['unlit_minor_share_pm']}% | {r['top_overlap_vs_default']:.0%} |")
        A("")
        A("귀갓길 지수 상위 — 보안등 없는 골목 블록 (지수는 1위 = 100)")
        A("")
        A("| 순위 | 동 | 길이 | 귀갓길 지수 | 가까운 역 | 본체 기준 저활성 비중 |")
        A("|---|---|---|---|---|---|")
        for r in d["top"]:
            A(f"| {r['rank']} | {r['dong']} | {r['len_m']}m | {r['index']} | {r['station']}역 {r['station_m']:,.0f}m | "
              f"{r['dark_main']}% |")
        A("")
        if d.get("top_dark"):
            A("같은 조건에 **본체 기준 저활성 과반**까지 겹치는 블록 — 보안등도 없고 사람도 드문데 밤 귀갓길이 지나는 곳")
            A("")
            A("| 순위 | 동 | 길이 | 귀갓길 지수 |")
            A("|---|---|---|---|")
            for r in d["top_dark"]:
                A(f"| {r['rank']} | {r['dong']} | {r['len_m']}m | {r['index']} |")
            A("")
        A("### 해 지는 시각 (NOAA 태양 위치 식 · 매달 15일 · 안산 중심)")
        A("")
        A("| 월 | 해 지는 시각 | 어두워지는 시각(시민박명 끝) | 밤 10시 = 해 진 뒤 |")
        A("|---|---|---|---|")
        for r in pv["sunset"]["table"]:
            A(f"| {r['month']}월 | {r['sunset']} | {r['dusk']} | {r['h22_after_sunset']}시간 |")
        A("")
        A("> 같은 '밤 10시'가 6월엔 해 진 뒤 2시간, 12월엔 5시간 가까이 뒤다. 겨울 퇴근길(18~21시)은 이미 어둡지만 "
          "지금의 시간 창(22~02시) 밖이다 — `3안 설명/3안 수정사항.md` #15 남은 작업 참조. "
          "식의 검증: 서울 좌표로 timeanddate.com 표와 2분 안(`tests/test_public.py`).")
        A("")

    # ── 검증 실험 (본체와 별도 목록 PM.EXP — 수정사항 #13) ──
    if getattr(PM, "EXP", None):
        ce = PM.summary(PM.EXP)
        A("## 검증 실험 — 점수 해상도 (본체 집계에 포함하지 않음 · 기본값은 현행)")
        A("")
        A(f"`src/alloc.py` 가 쓰는 스위치 {len(PM.EXP)}개 — A {ce['A']} · B {ce['B']} · **C {ce['C']}** · X {ce['X']}. "
          f"지금 값 `POP_ALLOC = {PM.POP_ALLOC.value}` 은 현행과 같은 점수를 냅니다.")
        A("")
        A("| 파라미터 | 값 | 등급 | 근거 | 요청 자료 |")
        A("|---|---|---|---|---|")
        for p in PM.EXP:
            A(f"| `{p.name}` | {p.value} | {p.grade} | {p.basis[:200]}… | {p.need} |")
        A("")
        r = ev.get("resolution")
        if r:
            A(f"### 같은 {r['pairs']}쌍 · 같은 경로 엔진 · 같은 δ 로 잰 결과 (`python src/validate.py --resolution`)")
            A("")
            A("활성 규칙 — `min` = 본체 현행, `lex` = 사전식 동점 처리(시연판 `ACT_TIEBREAK`). "
              f"저활성은 어느 줄이든 그 줄 활성도의 길이 기준 하위 {PM.DARK_Q.value:.0%} 입니다. "
              "`homes(count)` 는 건물마다 1, `homes(shuffled)` 는 같은 1km 안에서 자리만 무작위로 섞은 대조군입니다.")
            A("")
            A("| 방식 · 규칙 | 저활성 길이 | δ 0→40% 반응 | 저활성 노출(δ 20%) | 거리 | 예산 미소진 | uniform 대비 경로 일치 |")
            A("|---|---|---|---|---|---|---|")
            for k, x in r["runs"].items():
                if "dark_cut_pct" not in x:
                    A(f"| {k} | {x['dark_len_pct']}% (임계와 같은 값 {x['tie_at_thr_pct']}%) | — | — | — | — | — |")
                    continue
                A(f"| {k} | {x['dark_len_pct']}% | {x['detour_resp_pct']}% | "
                  f"{x['dark_before_m']:,.0f} → {x['dark_after_m']:,.0f}m ({x['dark_cut_pct']}% 감소, {x['pairs_with_dark']}쌍) | "
                  f"+{x['extra_pct']}% | {x['alpha_saturated_pct']}% | {x['jaccard_vs_uniform']:.0%} |")
            A("")
            A(f"| 유동 값 | 1km 안 값이 한 가지뿐인 블록 | 유동 0 셀 | min 이 유동을 따르는 셀 | 앵커 셀 중 유동 하위 {PM.DARK_Q.value:.0%} |")
            A("|---|---|---|---|---|")
            for k, x in r["cells"].items():
                A(f"| {k} | {x['blocks_const']} / {x['blocks']} | {x['zero_flow_cells_pct']}% | "
                  f"{x['flow_binding_pct']}% | {x['anchor_cells_flow_low_pct']}% |")
            A("")
            A(f"- 앵커 셀 {r['anchor_cells']:,}개 중 주거건물 0: {r['anchor_cells_no_home_pct']}%")
            A(f"- 자기 검증(uniform·min = 위 「산출 수치」 본값): {r['self_check']}")
            A("- 판정과 해석: `3안 설명/3안 수정사항.md` #13")
            A("")

    A("## 재현 방법")
    A("")
    A("```bash")
    A("python src/prep.py        # 기초 데이터(data/base) → 3안 스키마 (셀·앵커·그래프)")
    A("python src/validate.py    # 인벤토리 제약 + 근거 산출 → evidence.json")
    A("python src/validate.py --resolution   # + 점수 해상도 실험(#13, 10분 남짓 더)")
    A("python src/collect_public.py    # 공개 실데이터 받기(네트워크) → data/public/raw")
    A("python src/public_data.py       # 공개 실데이터 정제 → data/public/derived")
    A("python src/validate_public.py   # 공개 실데이터 근거 → data/public/evidence_public.json")
    A("python src/gen_docs.py    # 이 문서 재생성")
    A("streamlit run src/app.py  # 앱")
    A("```")
    A("")
    A("| 모듈 | 역할 |")
    A("|---|---|")
    A("| `params.py` | 모든 상수 + 근거 + 등급 (단일 출처) |")
    A("| `prep.py` | 100m 셀 · 심야 앵커 분류 · 보행 그래프 |")
    A("| `score.py` | 야간 활성도 = min(분위 유동인구, 분위 앵커) |")
    A("| `alloc.py` | 유동 대체값의 100m 안분 방식(검증 실험 스위치, 기본은 현행) |")
    A("| `route.py` | 우회 예산 δ 역산 경로 탐색 |")
    A("| `validate.py` | 인벤토리 제약 + 근거를 데이터로 산출 |")
    A("| `collect_public.py` · `public_data.py` · `validate_public.py` | 공개 실데이터 받기 · 정제 · 근거 (보안등 · 역 하차 · 경찰 시설 · 해 지는 시각) |")
    A("| `app.py` | Streamlit 화면 |")
    A("")

    out = DOCS / "근거대장.md"
    out.write_text("\n".join(L), encoding="utf-8")
    print(f"[v] {out} 생성 ({len(L)}줄)")
    print(f"    A {c['A']} / B {c['B']} / C {c['C']} / X {c['X']} · 요청자료 {len(needs)}건")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
