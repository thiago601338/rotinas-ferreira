@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
chcp 65001 > nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
title Rotinas Ferreira - testar
if exist ".venv\Scripts\python.exe" goto rodar
echo Não encontrei o Python das rotinas (pasta .venv) aqui.
echo Rode primeiro o instalar.bat com duplo clique e depois abra este arquivo de novo.
echo.
pause
exit /b 1

:rodar
if "%~1"=="" goto alvos
".venv\Scripts\python.exe" -m rotinas testar %*
set CODIGO=%ERRORLEVEL%
echo.
pause
exit /b %CODIGO%

:alvos
echo Uso: testar.bat ^<alvo^> [argumentos do alvo]
echo.
".venv\Scripts\python.exe" -m rotinas testar
echo.
pause
exit /b 0
