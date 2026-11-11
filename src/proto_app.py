# -*- coding: utf-8 -*-
"""
3안 시연 프로토타입 — 안산 밤길 (임의값 인벤토리 데이터)
실행:  python -m streamlit run src/proto_app.py
준비:  python src/synth_inventory.py  →  python src/ingest_inventory.py   (한 번)

기존 src/app.py(근거·방법론 대시보드)와 별개다. 계산 코어(params·score·night_core)는 공유한다.
표현 규칙: CLAUDE.md 0절.
"""
import pathlib
import sys

import streamlit as st

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import proto_ui as UI

st.set_page_config(page_title="안산 밤길", page_icon="🌙", layout="wide")

pg = st.navigation({
    "시민": [st.Page("proto_pages/route.py", title="밤길 찾기", icon="🚶", default=True),
             st.Page("proto_pages/bus.py", title="막차 내릴 곳", icon="🚌")],
    "담당자": [st.Page("proto_pages/lights.py", title="보안등 대조", icon="💡"),
               st.Page("proto_pages/priority.py", title="개선 우선 구간", icon="🛠️")],
    "정보": [st.Page("proto_pages/sources.py", title="데이터 출처", icon="🧾")],
}, position="top")

UI.slot_picker()
pg.run()
