@echo off
chcp 65001 > nul
cd /d "%~dp0"
where python > nul 2>&1 && (python lotto_maker.py) || (py lotto_maker.py)
pause
