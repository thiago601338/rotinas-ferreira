@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
title Rotinas Ferreira - instalação

rem ==========================================================================
rem  Rotinas Ferreira - instalação no PC. Rode com duplo clique.
rem  Pode rodar de novo quantas vezes quiser: pula o que já existe.
rem    instalar.bat           usa o ramo main
rem    instalar.bat RAMO      usa outro ramo, ex.: instalar.bat claude/fase-1-briefing-x8e3im
rem  Funciona baixado sozinho ou de dentro do clone.
rem  O endereço do repositório e os ids do winget também estão em
rem  config\instalacao.json: mudou aqui, mude lá.
rem  Sem variável definida dentro de bloco: o fluxo usa goto e rótulos.
rem ==========================================================================

set "REPO_URL=https://github.com/thiago601338/rotinas-ferreira.git"
set "RAMO_PADRAO=main"
set "DESTINO=%USERPROFILE%\Documents\Rotinas Ferreira\sistema"
set "WINGET_GIT=Git.Git"
set "WINGET_PYTHON=Python.Python.3.12"
set "GIT_TERMINAL_PROMPT=0"
set "PIP_DISABLE_PIP_VERSION_CHECK=1"
set "RAMO=%~1"
set "FALHAS=0"

rem Rodando de dentro de um clone? O git pull pode trocar este arquivo enquanto
rem o cmd ainda lê o .bat, então a instalação roda de uma cópia na pasta temporária.
if defined ROTINAS_INSTALAR_CLONE goto :clone_da_copia
if not exist "%~dp0rotinas\__main__.py" goto :usar_destino
if not exist "%~dp0.git" goto :usar_destino
set "ROTINAS_INSTALAR_CLONE=%~dp0"
copy /y "%~f0" "%TEMP%\rotinas-ferreira-instalar.bat" >nul 2>&1
if errorlevel 1 goto :clone_da_copia
call "%TEMP%\rotinas-ferreira-instalar.bat" %* & exit /b

:clone_da_copia
rem Aqui roda a cópia (ou este mesmo arquivo, se a cópia falhou).
set "SISTEMA=%ROTINAS_INSTALAR_CLONE:~0,-1%"
set "ROTINAS_INSTALAR_CLONE="
set "DENTRO_DO_CLONE=1"
goto :inicio

:usar_destino
set "SISTEMA=%DESTINO%"
set "DENTRO_DO_CLONE=0"

:inicio
echo.
echo ============================================================
echo   Rotinas Ferreira - instalação
echo ============================================================
echo   Pasta do sistema: "%SISTEMA%"
if defined RAMO echo   Ramo pedido: %RAMO%
echo   Se o Windows pedir permissão durante a instalação, clique em Sim.
echo.

rem -------------------------------------------------------------- 1. winget
echo [1/7] Conferindo o winget, o instalador de programas do Windows...
set "WINGET="
for /f "delims=" %%W in ('where winget 2^>nul') do if not defined WINGET set "WINGET=%%W"
if not defined WINGET if exist "%LOCALAPPDATA%\Microsoft\WindowsApps\winget.exe" set "WINGET=%LOCALAPPDATA%\Microsoft\WindowsApps\winget.exe"
if defined WINGET echo       OK: winget encontrado.
if not defined WINGET echo       AVISO: winget não encontrado. Se faltar algum programa, explico o que fazer.

rem -------------------------------------------------------------- 2. Git
echo.
echo [2/7] Git...
call :achar_git
if defined GIT goto :git_ok
if not defined WINGET goto :sem_winget
echo       Instalando o Git pelo winget...
"%WINGET%" install -e --id %WINGET_GIT% --source winget --silent --accept-source-agreements --accept-package-agreements
call :achar_git
if defined GIT goto :git_ok
echo       FALHOU: o Git não apareceu depois do winget.
echo       Instale à mão com: winget install -e --id %WINGET_GIT%
echo       e rode este instalar.bat de novo.
goto :fim_com_falha
:git_ok
rem Põe o Git no PATH desta janela: o Python chamado daqui também precisa achar.
for %%D in ("%GIT%") do set "PATH=%%~dpD;%PATH%"
echo       OK: "%GIT%"

rem -------------------------------------------------------------- 3. Python
echo.
echo [3/7] Python 3.10 ou mais novo...
call :achar_python
if defined PY goto :python_ok
if not defined WINGET goto :sem_winget
echo       Instalando o Python 3.12 pelo winget, só para este usuário...
"%WINGET%" install -e --id %WINGET_PYTHON% --scope user --source winget --silent --accept-source-agreements --accept-package-agreements
call :achar_python
if defined PY goto :python_ok
echo       FALHOU: o Python não apareceu depois do winget.
echo       Instale à mão com: winget install -e --id %WINGET_PYTHON% --scope user
echo       e rode este instalar.bat de novo.
goto :fim_com_falha
:python_ok
echo       OK: "%PY%"

rem -------------------------------------------------------------- 4. código
echo.
echo [4/7] Código do sistema...
if "%DENTRO_DO_CLONE%"=="1" goto :clone_existe
if exist "%SISTEMA%\.git" goto :clone_existe
if not exist "%SISTEMA%" goto :clonar
for /f "delims=" %%A in ('dir /b /a "%SISTEMA%" 2^>nul') do goto :pasta_ocupada

:clonar
set "RAMO_CLONE=%RAMO%"
if not defined RAMO_CLONE set "RAMO_CLONE=%RAMO_PADRAO%"
for %%D in ("%SISTEMA%\..") do set "PAI=%%~fD"
if not exist "%PAI%" mkdir "%PAI%"
echo       Baixando o repositório, ramo %RAMO_CLONE%...
"%GIT%" clone --branch "%RAMO_CLONE%" "%REPO_URL%" "%SISTEMA%"
if errorlevel 1 goto :clone_falhou
echo       OK: repositório baixado.
goto :passo_venv

:clone_existe
echo       Clone encontrado.
call :parar_vigia
if not defined RAMO goto :pull
echo       Trocando para o ramo %RAMO%...
"%GIT%" -C "%SISTEMA%" fetch origin "%RAMO%"
if errorlevel 1 goto :ramo_falhou
"%GIT%" -C "%SISTEMA%" checkout "%RAMO%"
if errorlevel 1 goto :ramo_falhou
:pull
echo       Atualizando com git pull...
"%GIT%" -C "%SISTEMA%" pull --ff-only
if errorlevel 1 goto :pull_rebase
echo       OK: código atualizado.
goto :passo_venv

:pull_rebase
rem O pull --ff-only falha quando este PC tem commit que não subiu, em geral uma
rem execução do testar.bat em execucoes\. Reaplica esses commits por cima do GitHub.
echo       O git pull simples não deu. Tentando de novo com git pull --rebase --autostash...
"%GIT%" -C "%SISTEMA%" pull --rebase --autostash
if errorlevel 1 goto :pull_abortar
rem O --autostash devolve 0 mesmo quando a mudança feita à mão bate com a versão nova e
rem deixa marcas de conflito no arquivo. Se sobrou arquivo em conflito, volta ele para a
rem versão do GitHub; a mudança feita à mão continua guardada no git stash.
"%GIT%" -C "%SISTEMA%" diff --quiet --diff-filter=U
if errorlevel 1 goto :pull_conflito
echo       OK: código atualizado. Os commits que só estavam neste PC foram mantidos.
goto :passo_venv

:pull_conflito
"%GIT%" -C "%SISTEMA%" reset --merge
if errorlevel 1 echo       AVISO: não consegui desfazer o conflito. Não rode nada; mande esta tela para a IA.
set /a FALHAS+=1
echo       FALHOU: o código foi atualizado, mas um arquivo do sistema tinha sido mudado à mão
echo       e batia com a versão nova. Os arquivos ficaram como no GitHub e a mudança feita à mão
echo       ficou guardada no git stash. Mande esta tela para a IA.
goto :passo_venv

:pull_abortar
rem Se o rebase parou no meio, desfaz: a pasta volta a ficar como estava antes do pull.
"%GIT%" -C "%SISTEMA%" rebase --abort >nul 2>&1
goto :pull_falhou

:ramo_falhou
set /a FALHAS+=1
echo       FALHOU: não consegui trocar para o ramo %RAMO%. Confira o nome. Sigo no ramo atual.
goto :pull

:pull_falhou
set /a FALHAS+=1
echo       FALHOU: o git pull não funcionou. Sigo com o código que já está na pasta.
echo       Causas comuns: sem internet; arquivo do sistema mudado à mão; ou uma execução do
echo       testar.bat que não subiu para o GitHub. Rode testar.bat enviar e depois este arquivo
echo       de novo. Se continuar, mande esta tela para a IA.
goto :passo_venv

:pasta_ocupada
echo       FALHOU: a pasta "%SISTEMA%" já existe, tem arquivos e não é um clone do git.
echo       Não mexo nela. Renomeie essa pasta, por exemplo para sistema-antigo, e rode o instalar.bat de novo.
goto :fim_com_falha

:clone_falhou
echo       FALHOU: não consegui baixar o repositório. Confira a internet e o nome do ramo, e rode de novo.
goto :fim_com_falha

rem -------------------------------------------------------------- 5. .venv + pip
:passo_venv
echo.
echo [5/7] Ambiente Python do sistema, .venv, e dependências...
if not exist "%SISTEMA%\requirements.txt" goto :sem_codigo
set "VENVPY=%SISTEMA%\.venv\Scripts\python.exe"
if not exist "%VENVPY%" goto :criar_venv
"%VENVPY%" -c "import sys" >nul 2>&1
if not errorlevel 1 goto :venv_pronta
echo       A .venv que existe não funciona, talvez o Python tenha mudado. Recriando...
"%PY%" -m venv --clear "%SISTEMA%\.venv"
goto :conferir_venv
:criar_venv
echo       Criando a .venv...
"%PY%" -m venv "%SISTEMA%\.venv"
:conferir_venv
if not exist "%VENVPY%" goto :venv_falhou
:venv_pronta
echo       Atualizando o pip...
"%VENVPY%" -m pip install --upgrade pip
if errorlevel 1 echo       AVISO: não consegui atualizar o pip; sigo com o que tem.
echo       Instalando as dependências. Na primeira vez demora alguns minutos...
"%VENVPY%" -m pip install -r "%SISTEMA%\requirements.txt"
if errorlevel 1 goto :pip_falhou
echo       OK: dependências instaladas.
goto :passo_python

:pip_falhou
set /a FALHAS+=1
echo       FALHOU: o pip não instalou tudo. Veja a mensagem acima; sigo com o resto.
goto :passo_python

:venv_falhou
echo       FALHOU: não consegui criar a .venv em "%SISTEMA%\.venv".
goto :fim_com_falha

:sem_codigo
echo       FALHOU: não achei o requirements.txt em "%SISTEMA%": este ramo não tem o sistema.
echo       Rode de novo informando o ramo certo, por exemplo: instalar.bat claude/fase-1-briefing-x8e3im
goto :fim_com_falha

rem -------------------------------------------------------------- 6. parte Python
:passo_python
echo.
echo [6/7] Parte Python: ffmpeg, adb, pastas de trabalho, .env e vigia...
cd /d "%SISTEMA%"
"%VENVPY%" -m rotinas instalar
if errorlevel 1 set /a FALHAS+=1

rem -------------------------------------------------------------- 7. conferência
echo.
echo [7/7] Conferência final...
"%VENVPY%" -m rotinas verificar
if errorlevel 1 set /a FALHAS+=1
goto :fim

:sem_winget
echo       FALHOU: falta este programa e o winget não está disponível para instalar.
echo       Instale o "Instalador de Aplicativo" da Microsoft Store: abra a Store,
echo       procure Instalador de Aplicativo e clique em Obter ou Atualizar.
echo       Vou abrir a página dele na Store agora. Depois, rode este instalar.bat de novo.
start "" "ms-windows-store://pdp/?ProductId=9NBLGGH4NNS1"
goto :fim_com_falha

:fim_com_falha
set /a FALHAS+=1

:fim
echo.
echo ============================================================
if "%FALHAS%"=="0" echo   Instalação concluída: tudo certo.
if not "%FALHAS%"=="0" echo   A instalação terminou com pendências: veja os FALHOU e os ✗ acima.
echo   Se o .env abriu no Bloco de Notas: preencha SUPABASE_URL e SUPABASE_KEY,
echo   salve e rode este instalar.bat de novo.
echo   Para atualizar depois: atualizar.bat, dentro de "%SISTEMA%".
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

:achar_python
rem Primeiro os locais do instalador do python.org, sem depender do PATH desta janela;
rem depois o py.exe e o PATH. Nada da pasta WindowsApps: é o atalho falso da
rem Microsoft Store ou o Python da Store, que não serve para a .venv do vigia.
rem PYTHONIOENCODING: o caminho impresso pelo py chega em UTF-8, como o chcp 65001 lê.
set "PY="
set "PYTHONIOENCODING=utf-8"
for %%V in (312 313 311 310) do if not defined PY call :testar_python "%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe"
for %%V in (312 313 311 310) do if not defined PY call :testar_python "%ProgramFiles%\Python%%V\python.exe"
if not defined PY for /f "delims=" %%P in ('py -3 -c "import sys; print(sys.executable)" 2^>nul') do if not defined PY call :testar_python "%%P"
if not defined PY for /f "delims=" %%P in ('where python 2^>nul') do if not defined PY call :testar_python "%%P"
set "PYTHONIOENCODING="
goto :eof

:testar_python
if not exist "%~1" goto :eof
set "PY_TESTE=%~1"
if not "%PY_TESTE:\WindowsApps\=%"=="%PY_TESTE%" goto :eof
"%~1" -c "import sys; sys.exit(0 if sys.version_info[:2] >= (3, 10) else 1)" >nul 2>&1
if errorlevel 1 goto :eof
set "PY=%~1"
goto :eof

:parar_vigia
rem Para o vigia antes de mexer no código e nas dependências; o passo 6 liga de novo.
if not exist "%SISTEMA%\.venv\Scripts\python.exe" goto :eof
echo       Parando o vigia da fila antes de atualizar; ele volta no passo 6...
pushd "%SISTEMA%"
"%SISTEMA%\.venv\Scripts\python.exe" -m rotinas instalar --parar-vigia
set "PARADA=%ERRORLEVEL%"
popd
if "%PARADA%"=="3" echo       AVISO: o vigia está no meio de um pedido. Sigo mesmo assim; se o pip falhar, rode de novo depois.
goto :eof
