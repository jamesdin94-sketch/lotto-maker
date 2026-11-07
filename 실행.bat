@echo off
setlocal
title 로또 조합 메이커
cd /d "%~dp0"
if not exist lotto_maker.py (
  echo.
  echo [안내] 이 파일은 압축을 푼 폴더 안에서 실행해야 합니다.
  echo        ZIP 파일 안에서 바로 열지 말고, 먼저 압축을 푼 다음 다시 실행해 주세요.
  echo        ^(ZIP 파일을 오른쪽 마우스로 누르고 "모두 압축 풀기"^)
  echo.
  pause
  exit /b 1
)
set "PYCMD="
py -3 --version >nul 2>&1 && set "PYCMD=py -3"
if not defined PYCMD python --version >nul 2>&1 && set "PYCMD=python"
if not defined PYCMD (
  echo.
  echo [안내] 파이썬이 설치되어 있지 않거나, 설치할 때 'Add python.exe to PATH' 칸을 체크하지 않았습니다.
  echo        설명서의 1단계를 보고 파이썬을 설치해 주세요. ^(python.org/downloads/windows^)
  echo.
  pause
  exit /b 1
)
mode con: cols=130 lines=60 >nul 2>&1
%PYCMD% lotto_maker.py
echo.
echo 프로그램이 끝났습니다. 이 창을 닫으려면 아무 키나 누르세요.
pause >nul
