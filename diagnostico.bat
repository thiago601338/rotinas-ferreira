@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
chcp 65001 > nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
title Rotinas Ferreira - diagnostico
if exist ".venv\Scripts\python.exe" goto rodar
echo Não encontrei o Python das rotinas (pasta .venv) aqui.
echo Rode primeiro o instalar.bat com duplo clique e depois abra este arquivo de novo.
echo.
pause
exit /b 1

:rodar
echo Diagnóstico do PC: versões, ADB do BlueStacks, tela do Instagram e rascunho 0925 do CapCut.
echo Deixe o BlueStacks aberto e o CapCut fechado. Leva cerca de 1 minuto.
echo.
".venv\Scripts\python.exe" -m rotinas testar diagnostico %*
set CODIGO=%ERRORLEVEL%
echo.
pause
exit /b %CODIGO%
