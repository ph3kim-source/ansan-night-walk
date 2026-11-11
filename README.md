# 안산 밤길 — 시연판

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
