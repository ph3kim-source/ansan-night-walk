# -*- coding: utf-8 -*-
"""시민용 웹 지도 앱(html/app) 검증 (수정사항 #24) — py -3.12 -m pytest tests/test_app.py -q
① 금지어 없음 · '공식 서비스 아님' · '가상 데이터' 표시 · 담당자 화면 없음
② 임의값 판(data/proto) · 공개 자료만 — 실데이터 경로가 섞이지 않는다
③ 자료 구조 — 보행망 · 28개 시간대 활성도 · 길 종류 · 러닝 코스(드로잉 런 12 · 차 없는 길)
브라우저 안 경로 계산이 night_core 와 같은 답을 내는지는 헤드리스 크롬으로 따로 쟀다(수정사항 #24 결과 표)."""
import base64
import json
import pathlib
import re
import sys

import numpy as np
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
APP_FILES = [SRC / "app" / f for f in ("index.html", "app.css", "app.js")] + [SRC / "build_app.py"]


def test_no_forbidden_words():
    """CLAUDE.md 0절 — 시민 앱 코드 · 러닝 코스 생성기 · 본체 앱(app.py, #39)에 '안전' · '안심'이 없어야 한다.
    기관 서비스 이름 '생활안전지도'(자료 출처)만 예외."""
    files = APP_FILES + [p for p in [SRC / "build_runs.py", SRC / "app.py"] if p.exists()]
    hits = [(f.name, m) for f in files for m in re.findall("(?<!생활)안전|안심", f.read_text(encoding="utf-8"))]
    assert hits == []


def test_app_texts():
    html = (SRC / "app" / "index.html").read_text(encoding="utf-8")
    js = (SRC / "app" / "app.js").read_text(encoding="utf-8")
    assert "공식 서비스 아님" in html and "공식 서비스가 아닙니다" in js        # 시청 서비스로 읽히지 않게
    assert "가상 데이터" in html and "범죄 여부는 알려 주지 않" in js
    assert "보안등 대조" not in html and "개선 우선 구간" not in html            # 담당자 화면은 시민 앱에 없다
    assert "_pct)}%" not in js                                                # 코스 비율은 말(조금 · 절반쯤 …)이나 km 로 — 시민 화면에 % 통계 없음
    assert "보행 사고가 잦았던 곳" in js and 'data-dn="day"' in js and 'data-dn="night"' in js   # #26 사고 다발 · 낮 · 밤 기준
    assert "지금은 달라졌을 수 있어요" in js                                     # 다발지는 과거 사실 — 지금 판정처럼 말하지 않는다
    # #28 — 길은 % 대신 카드 세 개, 러닝은 '몇 분' → 추천 세 개('이런 분께')
    assert "data-detour" not in js and 'data-opt="' in js
    assert all(t in js for t in ("추천 경로", "빠른 길", "사람 많은 길 우선", "몇 분 달릴 거예요?", "분께 —", "코스 전체 보기"))
    # #30 — 지금 코스는 예시, 운영은 주민 추천 → 담당자 직접 확인(시연판은 보내지 않음)
    assert all(t in js for t in ("시연용 예시", "내가 아는 길 추천하기", "담당자가 직접 확인", "보내지지 않아요", "run_suggest"))
    # #31 — 설치형 웹앱 · 아래 탭 · 첫 실행 안내 · 첫 화면 바로가기 · 우리 집(이 휴대폰에만)
    assert all(t in html for t in ('rel="manifest"', 'id="tabbar"', "둘러보기만 할게요", "범죄 여부는 알려 주지 않아요", "홈 화면에 추가"))
    assert all(t in js for t in ("serviceWorker", "beforeinstallprompt", "도착을 집으로 등록", "이 휴대폰에만 저장", "문 연 가게"))


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    import build_app as BA
    out = tmp_path_factory.mktemp("app") / "app"
    return out, BA.build(out)


def test_build_outputs(built):
    out, _ = built
    for f in ("index.html", "app.css", "app.js", "data.js"):
        assert (out / f).exists(), f
    assert (out.parent / "밤길앱_열기.bat").read_bytes().startswith(b"@echo off\r\n")
    js = (out / "data.js").read_text(encoding="utf-8")
    assert js.startswith("window.APP_DATA = ")
    assert "data/real" not in js and "terms.npz" not in js
    assert (out / "data.js").stat().st_size < 6 * 2 ** 20                    # 폰에서도 받을 만한 크기
    import collect_api as CA                                                 # #41 — 바탕지도 키(브이월드)만 싣고, 다른 키는 절대 싣지 않는다
    env = CA.load_env()
    assert all(env[k] not in js for k in ("SGIS_KEY", "SGIS_SECRET", "DATA_GO_KR_KEY", "VWORLD_DOMAIN") if env.get(k) and len(env[k]) > 8)
    assert built[1]["meta"].get("vworld_key", "") == env.get("VWORLD_KEY", "")
    man = json.loads((out / "manifest.webmanifest").read_text(encoding="utf-8"))   # #31 설치형 웹앱
    assert man["display"] == "standalone" and man["start_url"].startswith("./") and man["name"] == "안산 밤길"
    assert {i["sizes"] for i in man["icons"]} >= {"192x192", "512x512"} and any(i.get("purpose") == "maskable" for i in man["icons"])
    sw = (out / "sw.js").read_text(encoding="utf-8")
    assert "__VERSION__" not in sw and "openstreetmap" in sw and "data.js" in sw   # 판 번호 · 지도 타일은 저장 안 함 · 자료는 저장
    from PIL import Image
    for name, s in (("icon-192.png", 192), ("icon-512.png", 512), ("icon-maskable-512.png", 512), ("apple-touch-icon.png", 180)):
        assert Image.open(out / "icons" / name).size == (s, s), name


def test_data_shapes(built):
    _, d = built
    M = d["meta"]
    assert M["synthetic"] is True and len(M["slots"]) == 28 and M["hours"] == [22, 23, 0, 1]
    dec = lambda s, t: np.frombuffer(base64.b64decode(s), dtype=t)          # noqa: E731
    n, m = M["n"], M["m"]
    lat = dec(d["lat"], "<i4") / 1e6
    assert len(lat) == n and 37.1 < lat.min() and lat.max() < 37.5
    assert len(dec(d["u"], "<i4")) == m and len(dec(d["len"], "<f4")) == m
    assert "act" not in d and dec(d["act2"], "u1").size == -(-28 * m // 4)     # #38 등급만 — 2비트씩 묶음
    lv = M["act_levels"]
    assert len(lv) == 3 and lv[0] < M["thr"] <= lv[1] < M["thr_hi"] <= lv[2]
    road = dec(d["road"], "u1")
    assert set(np.unique(road)) == {0, 1, 2, 3}                              # 3 = 차도 옆 보도(OSM, #26)
    assert dec(d["trail"], "u1").size == m and dec(d["acc_edge"], "u1").size == m
    assert dec(d["giant"], "u1").sum() > 0.9 * n
    assert M["route_options"]["fast"] == 0 and M["route_options"]["rec"] < M["route_options"]["people"]
    assert M["run_pick"]["n"] == 3 and M["run_pick"]["default"] in M["run_pick"]["minutes"]
    sun = M["sun"]
    assert len(sun["rise"]) in (365, 366) and all(300 < r < 480 and 1000 < s < 1220 for r, s in zip(sun["rise"], sun["set"]))
    acc = d["acc"]
    assert acc and all({"lat", "lng", "name", "types", "years", "ring"} <= set(a) for a in acc)
    assert {t for a in acc for t in a["types"]} <= {"보행노인", "보행어린이", "스쿨존어린이"}       # 자전거 다발지는 싣지 않는다
    assert M["ped_acc"]["years"][1] - M["ped_acc"]["years"][0] == 4
    ae = dec(d["acc_edge"], "u1")
    assert ae.max() <= len(acc) and (ae > 0).sum() > 0
    assert 0 < M["thr"] < M["thr_hi"] < 1
    assert all(len(s) == 4 and 0 <= s[3] < 2 ** 28 for s in d["shops"])
    assert {p["k"] for p in d["places"]} == {"역", "동", "지구대"}
    assert "rung" not in d and "run_bands" not in M and "gr" not in d      # 실데이터 판 전용(#32 · #35) 자료가 공개 판에 없다


def test_courses(built):
    if not (ROOT / "data" / "processed" / "run_courses.json").exists():
        pytest.skip("run_courses.json 없음 — py -3.12 src/build_runs.py")
    cs = built[1]["courses"]
    drawing = [c for c in cs if c["type"] == "drawing"]
    assert len(drawing) == 12 and {"whale", "rabbit"} <= {c["shape"] for c in drawing}
    m = built[1]["meta"]["m"]
    road = np.frombuffer(base64.b64decode(built[1]["road"]), dtype="u1")
    ln = np.frombuffer(base64.b64decode(built[1]["len"]), dtype="<f4")
    for c in cs:
        assert len(c["path"]) > 10 and c["length_m"] > 1000 and "nodes" not in c
        assert 0 <= c["car_free_pct"] <= 100 and re.findall("안전|안심", c["name"]) == []
        assert 0 <= c["trail_pct"] <= 100                                    # 밤 불빛 안내(RUN_TRAIL_NOTE)에 쓴다
        assert len(c["e"]) == len(c["path"]) - 1 and max(c["e"]) < m           # 간선 번호 열(낮 · 밤 기준 · 사고 다발 셈)
        assert abs(ln[c["e"]].sum() - c["length_m"]) < 2
    carfree = [c for c in cs if c["type"] == "carfree"]
    assert carfree and all(c["car_free_pct"] >= 80 for c in carfree)
    for c in carfree:                                                        # 차도 옆 보도는 차 없는 길이 아니다(#26)
        e = np.array(c["e"])
        assert ln[e][road[e] == 3].sum() / ln[e].sum() < 0.2, c["id"]
    assert built[1]["meta"]["trail_note"] == pytest.approx(0.4)


@pytest.mark.skipif(not (ROOT / "data" / "real" / "proto" / "terms.npz").exists(), reason="실데이터 적재 결과 없음(이 PC 전용)")
def test_real_app_build(tmp_path):
    """#32 실데이터 판 — html/ 밖에만 쓰고, 화면 등급(가림 · 합침) · 실데이터 표시를 싣는다. html/ 아래로는 쓰지 못한다."""
    import build_app as BA
    with pytest.raises(SystemExit):
        BA.build(ROOT / "html" / "app_real_test", real=True)
    d = BA.build(tmp_path / "app", real=True)
    M = d["meta"]
    assert M["real"] is True and M["synthetic"] is False and len(M["months"]) >= 1 and M["mask_borrow_sigma_m"] > 0
    assert "mask_merge_m" not in M and "gr" not in d and "act" not in d      # #38 화면 등급 = 길 찾기 등급 하나만(act2)
    codes = BA.unpack2(np.frombuffer(base64.b64decode(d["act2"]), dtype="u1"), 28 * M["m"])
    assert set(np.unique(codes)) == {0, 1, 2}                                  # #34 가린 칸도 빌린 값 — '자료 부족' 없음
    assert (tmp_path / "밤길앱_실데이터.bat").exists() and (tmp_path / "밤길앱_실데이터_휴대폰으로_보기.bat").exists()
    js = (SRC / "app" / "app.js").read_text(encoding="utf-8")
    assert all(t in js for t in ("통신 유동인구", "심야 업종 가게", "자료 부족", "내부 시연용", "주변 칸 값으로 채워요"))
    assert "블록으로 합치거나" not in js and "mask_merge_m" not in js
    # #35 러닝 새벽 · 저녁 — 적재 결과(run_terms.npz)가 있으면 시간대마다 등급(1~3)만 싣는다
    if (BA.REAL_PROTO / "run_terms.npz").exists():
        import params as PM
        assert M["run_bands"] == PM.RUN_BANDS.value and set(d["rung"]) == set(PM.RUN_BANDS.value)
        for k, s in d["rung"].items():
            g = np.frombuffer(base64.b64decode(s), dtype="u1")
            assert g.size == M["m"] and set(np.unique(g)) == {1, 2, 3}, k
            assert 0.15 < (ln := np.frombuffer(base64.b64decode(d["len"]), dtype="<f4"))[g == 1].sum() / ln.sum() < 0.35, k   # 길이 하위 25%
    assert all(t in js for t in ("🌅 새벽", "🌆 저녁", "에 달리는 분께", "오늘 해 뜨는 시각", "run_bands"))


def test_grade_codes_pack():
    """#38 등급만 — 경계는 NC.grades 와 같고(값 == 임계는 위 등급), 대표값은 경계 안이며, 2비트 묶음은 되풀어진다.
    대표값으로 판정한 '사람 드묾'(act < thr)이 원래 값의 판정과 하나도 다르지 않다."""
    import build_app as BA
    import night_core as NC
    rng = np.random.default_rng(1)
    ea = rng.random((28, 501))
    ea[0, :3] = [0.25, 0.75, 0.2]                                              # 경계에 걸린 값
    L = rng.random(501) * 100 + 1
    b, rep = BA.grade_codes(ea, 0.25, 0.75, L)
    assert np.array_equal(b + 1, NC.grades(ea, 0.25, 0.75)) and list(b[0, :3]) == [1, 2, 0]
    assert rep[0] < 0.25 <= rep[1] < 0.75 <= rep[2]
    qa = BA.shipped_act(ea, 0.25, 0.75, L)
    assert np.array_equal(qa < 0.25, ea < 0.25) and np.array_equal(qa < 0.75, ea < 0.75)
    p = BA.pack2(b)
    assert p.size == -(-b.size // 4) and np.array_equal(BA.unpack2(p, b.size), b.ravel())


def _toy_world(seed=0, n=12):
    """가상 격자 — 100m 칸 n×n, 28 시간대. 빌리기 시험용(실데이터 없이 어디서나 돈다)."""
    rng = np.random.default_rng(seed)
    g = np.arange(n) * 100.0
    xy = np.array([(x, y) for x in g for y in g])
    C = len(xy)
    P = rng.gamma(1.5, 20, (28, C))
    R, V, A_d = rng.random((28, C)), rng.random((28, C)), rng.random((28, C)) * 800
    masked = rng.random(C) < 0.15
    return xy, P, R, V, A_d, masked


def test_borrow_masked_ignores_own_values():
    """#34 — 가린 칸 원래 유동을 10배 · 0 으로 바꿔도 빌린 값 · 활성도가 같다(가린 칸 값은 결과에 들어가지 않는다).
    가리지 않은 칸 값은 그대로, 가린 칸은 3σ 안 가리지 않은 이웃의 가우스 가중 평균, 빌릴 이웃이 없으면 0."""
    import build_app as BA
    import night_core as NC
    xy, P, R, V, A_d, masked = _toy_world()
    sig = 100.0
    B1, w1 = BA.borrow_masked(P, masked, xy, sig)
    for f in (10.0, 0.0):
        P2 = P.copy()
        P2[:, masked] *= f
        B2, _ = BA.borrow_masked(P2, masked, xy, sig)
        assert np.array_equal(B1, B2)
        assert np.array_equal(NC.activity(R, V, A_d, B1)["act"], NC.activity(R, V, A_d, B2)["act"])
    assert np.array_equal(B1[:, ~masked], P[:, ~masked])
    i = np.flatnonzero(masked)[0]                                              # 손으로 계산한 가중 평균과 비교
    d = np.hypot(*(xy[~masked] - xy[i]).T)
    w = np.where(d <= 3 * sig, np.exp(-d ** 2 / (2 * sig ** 2)), 0)
    assert np.allclose(B1[:, i], P[:, ~masked] @ w / w.sum())
    assert (w1 > 0).all()
    lone = np.ones(len(xy), bool)                                              # 가리지 않은 칸이 5km 밖 하나뿐 → 빌릴 이웃 없음 → 0
    lone[0] = False
    far = xy.copy()
    far[0] += 5000
    B3, w3 = BA.borrow_masked(P, lone, far, sig)
    assert (w3 == 0).all() and (B3[:, lone] == 0).all() and np.array_equal(B3[:, 0], P[:, 0])


@pytest.mark.skipif(not (ROOT / "data" / "real" / "proto" / "terms.npz").exists(), reason="실데이터 적재 결과 없음(이 PC 전용)")
def test_real_masked_values_not_used():
    """#34 — 실데이터에서도 가린 칸 원래 유동을 10배로 바꿔 계산한 활성도가 앱이 쓰는 값과 같다."""
    import pandas as pd
    import build_app as BA
    import night_core as NC
    import params as PM
    t = np.load(BA.REAL_PROTO / "terms.npz")
    xy = pd.read_csv(BA.PROC / "cells.csv", encoding="utf-8-sig")[["x", "y"]].to_numpy(float)
    masked = np.asarray(t["masked"], bool)
    assert masked.any()
    sig = float(PM.MASK_BORROW_SIGMA_M.value)
    P2 = np.array(t["P"], float)
    P2[:, masked] *= 10
    a1 = NC.activity(t["R"], t["V"], t["A_d"], BA.borrow_masked(t["P"], masked, xy, sig)[0])["act"]
    a2 = NC.activity(t["R"], t["V"], t["A_d"], BA.borrow_masked(P2, masked, xy, sig)[0])["act"]
    assert np.array_equal(a1, a2)
    BA.world(BA.REAL_PROTO, True)
    assert BA.world.real["borrow"] is True and np.array_equal(BA.world.real["act"], a1)


def test_course_rules_from_params():
    """'차 없는 길' 정의 · 코스 기준은 params.py 한 곳에서 — 앱(길 종류)과 코스 생성기가 같은 목록을 쓴다."""
    import params as PM
    import build_app as BA
    assert BA.CAR_FREE == set(PM.RUN_CAR_FREE_HW.value)
    src = (SRC / "build_runs.py").read_text(encoding="utf-8")
    for name in ("RUN_CAR_FREE_HW", "RUN_COURSE_KM", "RUN_CF_SHARE_MIN", "RUN_TRAIL_NOTE"):
        assert f"PM.{name}" in src, name
    assert "AppData" not in src and "scratchpad" not in src                 # 이 PC 임시 폴더 경로가 공유본에 실리지 않게
    js = (SRC / "app" / "app.js").read_text(encoding="utf-8")
    assert "밤에는 불빛이 적을 수 있어" in js
