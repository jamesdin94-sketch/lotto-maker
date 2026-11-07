@echo off
chcp 65001 > nul
mode con: cols=130 lines=60
cd /d "%~dp0"
where python > nul 2>&1 && (python lotto_maker.py) || (py lotto_maker.py)
echo.
echo 프로그램이 끝났습니다. 이 창을 닫으려면 아무 키나 누르세요.
pause > nul
