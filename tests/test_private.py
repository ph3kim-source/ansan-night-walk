# -*- coding: utf-8 -*-
"""민간 실데이터 판 검증 (수정사항 #19) — py -3.12 -m pytest tests/test_private.py -q
① 배포 차단: 실데이터 결과는 data/real/proto 로만 가고, 공유본 빌드는 data/proto 가 임의값이 아니면 멈춘다
② 화면 가림: 표시 등급 · '자료 부족' 기준
③ 실데이터 판 화면: data/real/proto 가 있을 때만(이 PC). 원자료 값은 찍지 않는다"""
import json
import pathlib
import sys

import numpy as np
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
import build_share as BS  # noqa: E402
import ingest_inventory as II  # noqa: E402
import night_core as NC  # noqa: E402

PAGES = ["proto_pages/route.py", "proto_pages/bus.py", "proto_pages/lights.py",
         "proto_pages/priority.py", "proto_pages/sources.py"]
need_real = pytest.mark.skipif(not (ROOT / "data" / "real" / "proto" / "terms.npz").exists(),
                               reason="data/real/proto 없음 — 민간 실데이터는 이 PC에만 있다")


def test_grades():
    g = NC.grades([0.10, 0.30, 0.80, 0.90], thr=0.25, thr_hi=0.75, masked=[False, False, False, True])
    assert g.tolist() == [1, 2, 3, 0]


def test_real_output_goes_to_private_folder(tmp_path):
    _, out, priv = II.output_for(None)
    assert not priv and out == ROOT / "data" / "proto"
    _, out, priv = II.output_for(tmp_path)
    assert priv and out == ROOT / "data" / "real" / "proto"


def test_public_safe_blocks_private(tmp_path):
    p = tmp_path / "data" / "proto"
    p.mkdir(parents=True)
    rep = p / "ingest_report.json"
    rep.write_text(json.dumps({"_meta": {"synthetic": False}}), encoding="utf-8")
    with pytest.raises(SystemExit):
        BS.public_safe(tmp_path, keep=["src/x.py"])
    rep.write_text(json.dumps({"_meta": {"synthetic": True}}), encoding="utf-8")
    BS.public_safe(tmp_path, keep=["src/x.py", ".env.example"])
    for bad in (["data/real/proto"], ["data/api"], [".env"]):
        with pytest.raises(SystemExit):
            BS.public_safe(tmp_path, keep=bad)


def test_text_leaks(tmp_path):
    """실데이터로 잰 값이 공유 파일 글자에 있으면 공유본 빌드가 멈춘다(#22). 목록 파일이 없으면 볼 것이 없다."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x = 1  # 잰 값 12.3%\n", encoding="utf-8")
    (tmp_path / "data" / "proto").mkdir(parents=True)
    (tmp_path / "data" / "proto" / "ingest_report.json").write_text(json.dumps({"_meta": {"synthetic": True}}), encoding="utf-8")
    assert BS.text_leaks(tmp_path, keep=["src/a.py"]) == []
    blk = tmp_path / "data" / "real"
    blk.mkdir(parents=True)
    (blk / "share_block.txt").write_text("# 주석은 건너뛴다\n12.3%\n45.6%\n", encoding="utf-8")
    assert BS.text_leaks(tmp_path, keep=["src/a.py", "data/proto"]) == [("src/a.py", "12.3%")]
    with pytest.raises(SystemExit):
        BS.public_safe(tmp_path, keep=["src/a.py"])


def test_share_is_public_safe_now():
    """지금의 data/proto · KEEP 을 공개 저장소에 실어도 되는가 — 깨지면 공유본을 빌드하지 말 것."""
    BS.public_safe()


def test_dedup_identical_files(tmp_path):
    """이름의 달이 다른데 바이트가 같은 파일(#19) — 한 번만 읽고 기록을 남긴다."""
    a, b, c = (tmp_path / f"T22_X_2026{m}.csv" for m in ("01", "02", "03"))
    a.write_text("ETL_YMD\n20260201\n", encoding="utf-8")
    b.write_text("ETL_YMD\n20260201\n", encoding="utf-8")
    c.write_text("ETL_YMD\n20260301\n", encoding="utf-8")
    II.REP.clear()
    assert [p.name for p in II.dedup("T22_X", [a, b, c])] == [a.name, c.name]
    assert II.REP["dup_T22_X"]["읽은파일"] == 2


def test_mask_cells_threshold():
    II.REP.clear()
    k = II.PM.MASK_MIN_POP.value
    m = II.mask_cells(np.array([0.0, 1.0, k - 0.1, float(k), 50.0]))
    assert m.tolist() == [False, True, True, False, False]          # 거주 0명은 가리지 않는다
    assert II.REP["mask_counts"][f"기준{k}명"] == 2


@need_real
def test_real_report_is_private():
    rep = json.loads((ROOT / "data" / "real" / "proto" / "ingest_report.json").read_text(encoding="utf-8"))
    assert rep["_meta"]["synthetic"] is False and rep["_meta"]["private"] is True and rep["_meta"]["months"]
    t = np.load(ROOT / "data" / "real" / "proto" / "terms.npz")
    assert "masked" in t.files


@need_real
@pytest.mark.parametrize("page", PAGES)
def test_real_pages_render(page, monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv("NIGHT_DATA", "real")
    at = AppTest.from_file(str(SRC / "proto_app.py"), default_timeout=900)
    at.run()                                                          # 첫 화면 = 담당자 '보안등 대조'(#24)
    if page != "proto_pages/lights.py":
        at.switch_page(page).run()
    assert len(at.exception) == 0, [e.value for e in at.exception]
    shown = " ".join(c.value for c in at.caption)
    assert "내부 검토용" in shown                                     # 실데이터 판 표시
    if page == "proto_pages/route.py":
        assert len(at.metric) >= 4
