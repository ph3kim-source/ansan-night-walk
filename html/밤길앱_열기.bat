@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem 안산 밤길 앱 - 이 PC에서만 열린다(127.0.0.1). 시연판: 사람 수는 가상 데이터
start "" http://localhost:8787/app/
where py >nul 2>nul && (py -3 -m http.server 8787 --bind 127.0.0.1) || (python -m http.server 8787 --bind 127.0.0.1)
