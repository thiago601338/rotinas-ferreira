@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
title Rotinas Ferreira - atualização

rem ==========================================================================
rem  Rotinas Ferreira - atualização. Rode com duplo clique, de dentro da pasta
rem  do sistema. Para o vigia, baixa a versão nova com git pull, atualiza as
rem  dependências, liga o vigia de novo e confere a instalação.
rem  Pode rodar quantas vezes quiser.
rem  Sem variável definida dentro de bloco: o fluxo usa goto e rótulos.
rem ==========================================================================

set "PADRAO=%USERPROFILE%\Documents\Rotinas Ferreira\sistema"
set "GIT_TERMINAL_PROMPT=0"
set "PIP_DISABLE_PIP_VERSION_CHECK=1"
set "FALHAS=0"

rem O git pull pode trocar este arquivo enquanto o cmd ainda o lê; por isso a
rem atualização roda de uma cópia na pasta temporária.
if defined ROTINAS_ATUALIZAR_ORIGEM goto :copia
set "ROTINAS_ATUALIZAR_ORIGEM=%~dp0"
copy /y "%~f0" "%TEMP%\rotinas-ferreira-atualizar.bat" >nul 2>&1
if errorlevel 1 goto :copia
call "%TEMP%\rotinas-ferreira-atualizar.bat" %* & exit /b

:copia
rem Aqui roda a cópia (ou este mesmo arquivo, se a cópia falhou).
set "SISTEMA=%ROTINAS_ATUALIZAR_ORIGEM:~0,-1%"
set "ROTINAS_ATUALIZAR_ORIGEM="
if not exist "%SISTEMA%\rotinas\__main__.py" set "SISTEMA=%PADRAO%"
set "VENVPY=%SISTEMA%\.venv\Scripts\python.exe"

echo.
echo ============================================================
echo   Rotinas Ferreira - atualização
echo ============================================================
echo   Pasta do sistema: "%SISTEMA%"
echo.
if not exist "%VENVPY%" goto :sem_instalacao
cd /d "%SISTEMA%"

rem -------------------------------------------------------------- 1. parar o vigia
echo [1/5] Parando o vigia da fila...
"%VENVPY%" -m rotinas instalar --parar-vigia
rem 3 = o vigia está no meio de um pedido e não parou
if errorlevel 3 if not errorlevel 4 goto :vigia_ocupado
if errorlevel 1 echo       AVISO: não consegui conferir o vigia pelo Python. Sigo com a atualização.

rem -------------------------------------------------------------- 2. git pull
echo.
echo [2/5] Baixando a versão nova com git pull...
call :achar_git
if not defined GIT goto :sem_git
rem Põe o Git no PATH desta janela: a conferência do fim também precisa achar.
for %%D in ("%GIT%") do set "PATH=%%~dpD;%PATH%"
"%GIT%" -C "%SISTEMA%" pull --ff-only
if errorlevel 1 goto :pull_falhou
echo       OK: código atualizado.
goto :dependencias

:sem_git
set /a FALHAS+=1
echo       FALHOU: não achei o Git. Rode o instalar.bat.
goto :dependencias

:pull_falhou
set /a FALHAS+=1
echo       FALHOU: o git pull não funcionou. Sigo com o código que já está na pasta.
echo       Se algum arquivo do sistema foi mudado à mão, é isso que trava: mande esta tela para a IA.

rem -------------------------------------------------------------- 3. dependências
:dependencias
echo.
echo [3/5] Dependências Python...
"%VENVPY%" -m pip install --upgrade pip
if errorlevel 1 echo       AVISO: não consegui atualizar o pip; sigo com o que tem.
"%VENVPY%" -m pip install -r "%SISTEMA%\requirements.txt"
if errorlevel 1 goto :pip_falhou
echo       OK: dependências em dia.
goto :ligar_vigia

:pip_falhou
set /a FALHAS+=1
echo       FALHOU: o pip não instalou tudo. Veja a mensagem acima.

rem -------------------------------------------------------------- 4. ligar o vigia
:ligar_vigia
echo.
echo [4/5] Ligando o vigia de novo...
rem Pelo Python: apaga um parar.flag que tenha sobrado, inicia solto desta janela
rem e só diz OK quando o vigia dá sinal de vida.
"%VENVPY%" -m rotinas instalar --iniciar-vigia
if errorlevel 1 goto :vigia_nao_ligou
goto :conferir

:vigia_nao_ligou
set /a FALHAS+=1
echo       FALHOU: o vigia não ligou. Veja a mensagem acima; se repetir, rode o instalar.bat.

rem -------------------------------------------------------------- 5. conferência
:conferir
echo.
echo [5/5] Conferindo a instalação...
"%VENVPY%" -m rotinas verificar
if errorlevel 1 set /a FALHAS+=1
goto :fim

:vigia_ocupado
set /a FALHAS+=1
echo.
echo O vigia está no meio de um pedido. Não atualizei nada, para não atrapalhar.
echo Espere o pedido terminar, uns minutos, e rode o atualizar.bat de novo.
goto :fim

:sem_instalacao
set /a FALHAS+=1
echo Não achei a instalação em "%SISTEMA%". Rode o instalar.bat primeiro.

:fim
echo.
echo ============================================================
if "%FALHAS%"=="0" echo   Atualização concluída: tudo certo.
if not "%FALHAS%"=="0" echo   A atualização terminou com pendências: veja os FALHOU e os ✗ acima.
echo ============================================================
echo.
echo Aperte uma tecla para fechar.
pause >nul
endlocal & exit /b %FALHAS%

rem ==================================================================== sub-rotinas

:achar_git
set "GIT="
for /f "delims=" %%G in ('where git 2^>nul') do if not defined GIT set "GIT=%%G"
if not defined GIT if exist "%ProgramFiles%\Git\cmd\git.exe" set "GIT=%ProgramFiles%\Git\cmd\git.exe"
if not defined GIT if exist "%LOCALAPPDATA%\Programs\Git\cmd\git.exe" set "GIT=%LOCALAPPDATA%\Programs\Git\cmd\git.exe"
if not defined GIT if exist "%ProgramFiles(x86)%\Git\cmd\git.exe" set "GIT=%ProgramFiles(x86)%\Git\cmd\git.exe"
goto :eof
