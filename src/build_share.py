# -*- coding: utf-8 -*-
"""
공유 시연판 만들기 — ../3안_공유 (GitHub: ph3kim-source/ansan-night-walk)
실행:  python src/build_share.py

2안·4안과 같은 방식이다. 원본(3안)을 고치고 이 스크립트로 다시 만든다. 공유본을 직접 고치지 않는다.
담는 것: 시연 앱 실행과 가상 데이터 재생성에 필요한 코드·데이터 / 빼는 것: 연구 문서 · 작업 지침 · 로컬 실행 파일
"""
import pathlib
import shutil

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT.parent / "3안_공유"

KEEP = [
    "src/params.py", "src/score.py", "src/route.py", "src/osm.py", "src/prep.py", "src/validate.py",
    "src/gen_docs.py", "src/app.py", "src/night_core.py", "src/geocode.py", "src/synth_inventory.py",
    "src/ingest_inventory.py", "src/proto_ui.py", "src/proto_app.py", "src/proto_pages", "src/build_share.py",
    "tests/test_proto.py",
    "data/processed", "data/proto", "data/synthetic", "data/base", "data/bus", "data/geocode",
    "data/raw/overpass_쿼리.txt", "data/raw/overpass_건물.txt",
]

README = """# 안산 밤길 — 시연판

밤에 걸어서 집에 갈 때 최단 경로 대신 사람이 다니고 가게가 문을 연 길을 고를 수 있게 하는
서비스 아이디어(3안)의 프로토타입입니다.

⚠️ 사람 수 · 카드 결제 · 이동 · 보안등 · CCTV 값은 가상 데이터입니다. 안산시 민간데이터(통신 · 카드 · 신용)
규격(파일명 · 컬럼명 · 코드값)을 따라 임의로 만든 값이며 실제 분포가 아닙니다. 안산시 공식 서비스가 아닙니다.

## 둘러보기

- 왼쪽에서 요일과 시간(밤 10시 ~ 새벽 1시)을 고르면 모든 화면이 그 시간 기준으로 바뀝니다.
- 시민 화면: 밤길 · 막차, 어디서 내릴까
- 담당자 화면: 보안등 점검 · 개선이 필요한 구간
- 데이터 출처: 실데이터와 가상 데이터 구분, 계산 기준값

## 로컬 실행

    pip install -r requirements.txt
    streamlit run src/proto_app.py

가상 데이터를 다시 만들려면 `python src/synth_inventory.py` → `python src/ingest_inventory.py`.
실데이터가 들어오면 `python src/ingest_inventory.py <원본 폴더>` 로 바꿔 끼웁니다(화면 코드는 그대로).

## 배포 설정

시작 파일 `src/proto_app.py`, 파이썬 3.12. 비밀 설정은 없습니다.

## 폴더

| 폴더 | 내용 |
|---|---|
| `src/proto_app.py` · `src/proto_pages/` | 시연 앱 |
| `data/proto/` | 앱이 읽는 계산 결과 |
| `data/synthetic/` | 가상 데이터 원천(인벤토리 규격 그대로) |
| `data/base/` · `data/bus/` · `data/geocode/` | 공개 기초 데이터 |
| `data/processed/` | 100m 점수 격자 · OSM 보행망 |

이 저장소는 원본 프로젝트에서 `src/build_share.py` 로 만든 복사본입니다. 고칠 때는 원본을 고치고 다시 만듭니다.

## 자료

통계청 SGIS(행정동 경계 · 1km 격자 인구), 국토교통부 TAGO(버스 노선 · 정류장), 소상공인시장진흥공단 상가(상권)정보,
행안부 동별 내 · 외국인 인구(주민등록), 보행망 · 건물 · 지도 © OpenStreetMap contributors (ODbL 1.0).
"""

REQ = """streamlit==1.55.0
geopandas==1.1.1
pyogrio==0.11.1
shapely==2.1.2
pyproj==3.7.2
pandas==2.3.3
numpy==2.3.5
scipy==1.16.2
networkx==3.6.1
pydeck==0.9.1
plotly==6.7.0
"""

CONFIG = """[client]
toolbarMode = "minimal"

[browser]
gatherUsageStats = false
"""

GITIGNORE = """__pycache__/
.pytest_cache/
*.lock
.streamlit/secrets.toml
"""

# 데이터 파일은 줄바꿈 변환 없이 바이트 그대로
GITATTR = """*.csv -text
*.geojson -text
*.json -text
*.gz binary
*.npz binary
"""


def main():
    keep_git = OUT / ".git"
    if OUT.exists():                                   # .git 만 남기고 다시 만든다
        for p in OUT.iterdir():
            if p != keep_git:
                shutil.rmtree(p) if p.is_dir() else p.unlink()
    OUT.mkdir(exist_ok=True)
    ign = shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache")
    for rel in KEEP:
        src, dst = ROOT / rel, OUT / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dst, ignore=ign)
        else:
            shutil.copy2(src, dst)
    (OUT / "README.md").write_text(README, encoding="utf-8")
    (OUT / "requirements.txt").write_text(REQ, encoding="utf-8")
    (OUT / ".streamlit").mkdir(exist_ok=True)
    (OUT / ".streamlit" / "config.toml").write_text(CONFIG, encoding="utf-8")
    (OUT / ".gitignore").write_text(GITIGNORE, encoding="utf-8")
    (OUT / ".gitattributes").write_text(GITATTR, encoding="utf-8")
    files = [p for p in OUT.rglob("*") if p.is_file() and ".git" not in p.parts]
    mb = sum(p.stat().st_size for p in files) / 1e6
    big = max(files, key=lambda p: p.stat().st_size)
    print(f"[v] {OUT} · 파일 {len(files)}개 · {mb:.1f}MB · 가장 큰 파일 {big.relative_to(OUT)} "
          f"{big.stat().st_size / 1e6:.1f}MB")


if __name__ == "__main__":
    main()
