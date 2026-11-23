@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem 안산 밤길지도 - 이 PC에서만 열린다(127.0.0.1). 카카오 · 브이월드 바탕은 각 사이트에 http://localhost:8787 를 등록해야 뜬다(키가 없으면 OpenStreetMap)
start "" http://localhost:8787/안산_밤길지도.html
py -3.12 -m http.server 8787 --bind 127.0.0.1
