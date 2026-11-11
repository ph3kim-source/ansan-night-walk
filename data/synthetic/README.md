# data/synthetic — 시연용 임의값 인벤토리

> ★ **전부 임의값입니다.** 실데이터가 아니며 어떤 수치도 인용하지 않습니다 (`params.SYNTH_DATA`, C등급).
> 인벤토리 규격(실측 파일명 · 컬럼명 · 코드값 · cp949)만 실물과 같습니다.

재생성: `python src/synth_inventory.py` (시드 `SYNTH_SEED`, 약 35초) → `python src/ingest_inventory.py`

| 파일 (raw/) | 인벤토리 | 실물과 다른 점 |
|---|---|---|
| `tbsh_gyeonggi_agrde_1tm_202606.csv.gz` | DS-054 | 21~02시만(실물 00~23시). 21·02시는 심야 절단 시험용 |
| `tbsh_gyeonggi_mer_s_202606.csv` | DS-048 | — |
| `GYEONGGI_CELL_STAT_202606.csv.gz` | DS-082 | 108컬럼 중 몇 개만 값, 나머지 0 · 인구 0 행 제외 |
| `T22_GG_ADMI_FLOWPOP_202606_4127.csv` | DS-014 | — (25동×24시×30일×N/F = 36,000행, 실물과 같은 모양) |
| `T11_GG_TRANS_SEXAGE_ADMI_OUTFLOW_202606_4127.csv.gz` | DS-008 | 21~02시만 |
| `T13_GG_PURPOSE_SEXAGE_ADMI_OD_202606_4127.csv.gz` | DS-004 | 7일치 |
| `T25_GG_PURPOSE_TRANS_SEXAGE_SGG_OD_202606_4127.csv.gz` | DS-001 | 14일치 |
| `전국보안등정보표준데이터_안산_임의값.csv` · `전국CCTV표준데이터_안산_임의값.csv` | 인벤토리 밖 | 표준 규격 컬럼 추정 — 실파일 헤더로 확인 필요 |
| `card_block_centroid_임의규칙.csv` | — | ★ 실물에 없는 표. 카드 블록 경계 파일을 받아야 한다 |

`latent/` 는 가상 세계의 정답(가게별 영업시간 등)으로, 적재 코드 검증(`ingest_report.json` 의 latent_check)에만 씁니다.
실데이터가 오면: `python src/ingest_inventory.py <원본폴더>` — 화면 코드는 바꾸지 않습니다.
