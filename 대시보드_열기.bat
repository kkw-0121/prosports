@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 화면 데이터를 최신으로 만드는 중...
python scripts\build_summary.py
echo.
echo 브라우저에서 대시보드를 엽니다. 이 창을 닫으면 대시보드도 꺼집니다.
start "" http://localhost:8765/
python -m http.server 8765 --directory site
