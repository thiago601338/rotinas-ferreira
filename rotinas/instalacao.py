"""Instalação no PC do usuário: parte Python do ``instalar.bat`` e a verificação final.

- ``python -m rotinas instalar``: ffmpeg/ffprobe e adb (pelo winget, se faltarem), pastas de trabalho,
  ``.env`` (cópia do ``.env.example``; nunca sobrescreve), identidade do git só neste clone, registro do
  vigia no logon (tarefa agendada → schtasks → atalho em Inicializar) e início do vigia.
  ``--parar-vigia`` / ``--iniciar-vigia`` servem ao ``instalar.bat`` e ao ``atualizar.bat``.
- ``python -m rotinas verificar``: tabela ✓/✗ de tudo o que as rotinas precisam; ``--json`` para o
  diagnóstico. Código de saída = número de itens com ✗.

Tudo o que chama programas do Windows passa por ``executar`` e ``iniciar_destacado`` (trocados por mock
nos testes). Do ``.env`` só aparece "preenchido"/"vazio" e o status HTTP da conexão, nunca um valor.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import importlib
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

from . import config, ferramentas, fila, registro

log = registro.obter("instalacao")

NO_WINDOWS = ferramentas.NO_WINDOWS

# estado de um passo do instalar
OK, FALHOU, PULADO = "ok", "falhou", "pulado"
# estado de um item do verificar
VERDE, VERMELHO, NAO_SE_APLICA = "ok", "falha", "na"

# Consulta de teste do Supabase: só a coluna id (nunca cost_price, nunca *).
DESCRICAO_VIGIA = "Vigia da fila das Rotinas Ferreira: executa os pedidos gravados em fila\\pendente."

_RESET = "\x1b[0m"
_CORES = {VERDE: "\x1b[32m", VERMELHO: "\x1b[31m", NAO_SE_APLICA: "\x1b[90m", PULADO: "\x1b[33m"}
_SIMBOLOS = {VERDE: "✓", VERMELHO: "✗", NAO_SE_APLICA: "–"}


def _conf() -> dict:
    return config.carregar("instalacao")


# ---------------------------------------------------------------- chamadas ao sistema (mock nos testes)

@dataclass
class Saida:
    codigo: int
    texto: str = ""


def executar(cmd: list, timeout: float = 120, mostrar: bool = False) -> Saida:
    """Roda winget, PowerShell, schtasks ou git e devolve código + saída. Nunca levanta erro.

    ``mostrar=True`` deixa a saída aparecer na janela (progresso do winget) em vez de capturar.
    """
    cmd = [str(c) for c in cmd]
    try:
        if mostrar:
            return Saida(subprocess.run(cmd, timeout=timeout).returncode)
        r = ferramentas.rodar(cmd, timeout=timeout, verificar=False)
    except (ferramentas.FerramentaAusente, ferramentas.ErroComando, OSError, subprocess.SubprocessError) as e:
        return Saida(-1, str(e))
    return Saida(r.returncode, "\n".join(t for t in (r.stdout, r.stderr) if t).strip())


_DETACHED_PROCESS = 0x00000008
_CREATE_NEW_PROCESS_GROUP = 0x00000200
_CREATE_BREAKAWAY_FROM_JOB = 0x01000000


def iniciar_destacado(cmd: list, cwd: Path | None = None) -> int | None:
    """Inicia um programa sem esperar e solto desta janela (Bloco de Notas, vigia). Devolve o pid."""
    cmd = [str(c) for c in cmd]
    opcoes: dict = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        close_fds=True, cwd=str(cwd) if cwd else None)
    if os.name == "nt":
        base = _DETACHED_PROCESS | _CREATE_NEW_PROCESS_GROUP
        variantes = [dict(creationflags=base | _CREATE_BREAKAWAY_FROM_JOB), dict(creationflags=base)]
    else:
        variantes = [dict(start_new_session=True)]
    erro: Exception | None = None
    for extra in variantes:
        try:
            return subprocess.Popen(cmd, **opcoes, **extra).pid
        except OSError as e:  # ex.: o job da janela atual não deixa sair dele
            erro = e
    log.warning("Não consegui iniciar %s: %s", Path(cmd[0]).name, erro)
    return None


def _importavel(modulo: str) -> tuple[bool, str]:
    """Importa de verdade (pega DLL faltando, não só pacote ausente). Devolve (ok, versão ou erro)."""
    try:
        m = importlib.import_module(modulo)
    except Exception as e:  # noqa: BLE001 - ImportError, OSError de DLL etc.
        return False, f"{e.__class__.__name__}: {str(e)[:150]}"
    return True, str(getattr(m, "__version__", "") or "importa")


# ---------------------------------------------------------------- utilidades

@dataclass
class Passo:
    estado: str  # ok | falhou | pulado
    detalhe: str
    extra: dict = field(default_factory=dict)


@dataclass
class Item:
    chave: str
    nome: str
    estado: str  # ok | falha | na
    detalhe: str = ""
    acao: str = ""


def _preparar_saida() -> None:
    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception:
            pass


def _habilitar_cores() -> bool:
    """Cores ANSI só no terminal. No Windows, liga o modo VT do console."""
    if os.environ.get("NO_COLOR"):
        return False
    try:
        if not sys.stdout.isatty():
            return False
    except Exception:
        return False
    if os.name == "nt":
        try:
            import ctypes

            k = ctypes.windll.kernel32  # type: ignore[attr-defined]
            h = k.GetStdHandle(-11)
            modo = ctypes.c_uint32()
            if not k.GetConsoleMode(h, ctypes.byref(modo)):
                return False
            k.SetConsoleMode(h, modo.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        except Exception:
            os.system("")
    return True


def _pintar(texto: str, estado: str, cores: bool) -> str:
    return f"{_CORES[estado]}{texto}{_RESET}" if cores and estado in _CORES else texto


def _resumo_saida(s: Saida, limite: int = 300) -> str:
    texto = " ".join((s.texto or "").split())
    return (texto[-limite:] if texto else f"código {s.codigo}")


def _so_do_windows(caminho: Path) -> bool:
    """Caminho ``C:\\...`` da config lido fora do Windows (nuvem): não criar nada com ele."""
    return not NO_WINDOWS and bool(re.match(r"^[A-Za-z]:[\\/]", str(caminho)))


def _apagar(caminho: Path) -> None:
    try:
        caminho.unlink()
    except FileNotFoundError:
        pass


def _mtime(caminho: Path) -> float | None:
    try:
        return caminho.stat().st_mtime
    except OSError:
        return None


def caminho_pythonw() -> Path:
    for c in (config.RAIZ / ".venv" / "Scripts" / "pythonw.exe", Path(sys.executable).with_name("pythonw.exe")):
        if c.is_file():
            return c
    return Path(sys.executable)


def caminho_vigia() -> Path:
    return config.RAIZ / "vigia.pyw"


def caminho_atalho() -> Path:
    c = _conf()
    return config.expandir(c["pasta_inicializar"]) / c["atalho_vigia"]


def candidatos_adb() -> list[str]:
    try:
        return list(config.carregar("bluestacks").get("adb_candidatos") or [])
    except config.ErroConfig:
        return []


def descrever_adb(caminho: str) -> str:
    nome = re.split(r"[\\/]", str(caminho))[-1].lower()
    origem = "do BlueStacks (HD-Adb.exe)" if nome == "hd-adb.exe" else "do platform-tools"
    return f"adb {origem}: {caminho}"


def pastas_de_trabalho() -> list[Path]:
    """Pastas que o instalar cria em ``config.pastas().rotinas`` (e em ``videos``)."""
    p = config.pastas()
    lista = [p.fila / e for e in fila.ESTADOS]
    lista += [p.logs, p.registros, p.trabalho_stories]
    lista += [p.videos / s for s in _conf().get("subpastas_videos", [])]
    lista.append(p.backups)
    return lista


# ---------------------------------------------------------------- winget

def localizar_winget() -> str | None:
    return ferramentas.localizar("winget", _conf().get("winget_candidatos") or [])


def instalar_pelo_winget(id_pacote: str) -> Saida:
    winget = localizar_winget()
    if not winget:
        return Saida(-1, 'winget não encontrado: instale o "Instalador de Aplicativo" da Microsoft Store e rode de novo')
    print(f"        instalando {id_pacote} pelo winget (pode levar alguns minutos)...", flush=True)
    cmd = [winget, "install", "-e", "--id", id_pacote, "--source", "winget",
           "--accept-source-agreements", "--accept-package-agreements", "--silent"]
    return executar(cmd, timeout=float(_conf().get("winget_espera_s", 900)), mostrar=True)


def _falha_winget(nome: str, s: Saida) -> str:
    texto = f"o {nome} não apareceu depois do winget ({_resumo_saida(s)})"
    return texto + ". Rode o instalar.bat de novo; se repetir, instale à mão: winget install -e --id " + _conf()["winget"][nome]


# ---------------------------------------------------------------- passos do instalar

def passo_ffmpeg(usar_winget: bool = True) -> Passo:
    def achar() -> dict:
        return {n: ferramentas.localizar(n) for n in ("ffmpeg", "ffprobe")}

    achados = achar()
    if all(achados.values()):
        return Passo(OK, f"já instalados ({achados['ffmpeg']})", achados)
    if not NO_WINDOWS:
        return Passo(PULADO, "fora do Windows: instale o ffmpeg pelo gerenciador de pacotes do sistema")
    if not usar_winget:
        return Passo(FALHOU, "ffmpeg/ffprobe não encontrados (rodei com --sem-winget)")
    s = instalar_pelo_winget(_conf()["winget"]["ffmpeg"])
    achados = achar()
    if all(achados.values()):
        return Passo(OK, f"instalados pelo winget ({achados['ffmpeg']})", achados)
    return Passo(FALHOU, _falha_winget("ffmpeg", s))


def passo_adb(usar_winget: bool = True) -> Passo:
    achado = ferramentas.localizar("adb", candidatos_adb())
    if achado:
        return Passo(OK, f"já disponível: {descrever_adb(achado)}", {"adb": achado})
    if not NO_WINDOWS:
        return Passo(PULADO, "fora do Windows não se aplica (o adb é para o BlueStacks do PC)")
    if not usar_winget:
        return Passo(FALHOU, "adb não encontrado (rodei com --sem-winget)")
    s = instalar_pelo_winget(_conf()["winget"]["adb"])
    achado = ferramentas.localizar("adb", candidatos_adb())
    if achado:
        return Passo(OK, f"instalado pelo winget: {descrever_adb(achado)}", {"adb": achado})
    return Passo(FALHOU, _falha_winget("adb", s))


def passo_pastas() -> Passo:
    lista = pastas_de_trabalho()
    rotinas = config.pastas().rotinas
    if _so_do_windows(rotinas):
        return Passo(PULADO, f"caminho do Windows ({rotinas}); fora do Windows não crio")
    criadas = [q for q in lista if not q.is_dir()]
    for q in criadas:
        q.mkdir(parents=True, exist_ok=True)
    return Passo(OK, f"{len(criadas)} criada(s), {len(lista) - len(criadas)} já existiam, em {rotinas}")


def passo_env(abrir: bool = True) -> Passo:
    """Copia ``.env.example`` → ``.env`` se não existir. Nunca sobrescreve o ``.env``."""
    env = config.caminho_env()
    exemplo = config.RAIZ / ".env.example"
    criado = False
    if not env.exists():
        if not exemplo.is_file():
            return Passo(FALHOU, f"não achei o {exemplo} para copiar")
        try:
            with open(env, "xb") as f:  # "x": falha se o .env aparecer no meio do caminho
                f.write(exemplo.read_bytes())
            criado = True
        except FileExistsError:
            pass
    vazias = [n for n in _conf().get("env_obrigatorias", []) if not config.ler_env(env).get(n)]
    partes = ["criado a partir do .env.example" if criado else "já existia (não mexi)"]
    if vazias:
        partes.append("falta preencher " + ", ".join(vazias))
        if abrir and NO_WINDOWS:
            iniciar_destacado(["notepad.exe", env])
            partes.append("abri no Bloco de Notas: preencha, salve e feche")
        else:
            partes.append(f"abra e preencha: {env}")
    return Passo(OK, "; ".join(partes), {"env": str(env)})


def passo_git() -> Passo:
    """Define user.name/user.email só neste clone (sem --global), se faltarem."""
    git = ferramentas.localizar("git")
    if not git:
        return Passo(FALHOU, "git não encontrado; rode o instalar.bat de novo")
    if not (config.RAIZ / ".git").exists():
        return Passo(PULADO, f"{config.RAIZ} não é um clone do git")
    ident = _conf()["git_usuario"]
    definidos = []
    for chave, valor in (("user.name", ident["nome"]), ("user.email", ident["email"])):
        atual = executar([git, "-C", config.RAIZ, "config", "--get", chave], timeout=30)
        if atual.codigo == 0 and atual.texto.strip():
            continue
        s = executar([git, "-C", config.RAIZ, "config", "--local", chave, valor], timeout=30)
        if s.codigo != 0:
            return Passo(FALHOU, f"não consegui definir {chave}: {_resumo_saida(s)}")
        definidos.append(f"{chave}={valor}")
    if not definidos:
        return Passo(OK, "já configurado")
    return Passo(OK, "definido neste clone: " + ", ".join(definidos))


# -- registro do vigia no logon

def _ps_texto(valor) -> str:
    """Texto entre aspas simples do PowerShell (aspas simples, inclusive as tipográficas, dobradas)."""
    texto = str(valor)
    for aspa in ("'", "\u2018", "\u2019"):
        texto = texto.replace(aspa, aspa * 2)
    return f"'{texto}'"


def _powershell(script: str, timeout: float = 90) -> Saida:
    """Roda um script do PowerShell codificado (sem problema de aspas, espaços ou acentos)."""
    completo = (
        "$ErrorActionPreference = 'Stop'\n"
        "$ProgressPreference = 'SilentlyContinue'\n"
        "try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}\n"
        "try {\n" + script + "\n'ok'\n} catch {\n"
        "  Write-Output ('ERRO: ' + $_.Exception.Message)\n  exit 1\n}\n"
    )
    codificado = base64.b64encode(completo.encode("utf-16-le")).decode("ascii")
    exe = ferramentas.localizar("powershell", _conf().get("powershell_candidatos") or []) or "powershell.exe"
    return executar([exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", codificado],
                    timeout=timeout)


def _registrar_tarefa_powershell(pythonw: Path, vigia: Path, pasta: Path) -> tuple[bool, str]:
    script = "\n".join([
        "$usuario = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name",
        f"$acao = New-ScheduledTaskAction -Execute {_ps_texto(pythonw)} -Argument {_ps_texto(chr(34) + str(vigia) + chr(34))}"
        f" -WorkingDirectory {_ps_texto(pasta)}",
        "$gatilho = New-ScheduledTaskTrigger -AtLogOn -User $usuario",
        "$principal = New-ScheduledTaskPrincipal -UserId $usuario -LogonType Interactive -RunLevel Limited",
        # ExecutionTimeLimit zero = sem limite (o padrão de 72 h mataria o vigia); é notebook: roda na bateria
        "$ajustes = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries"
        " -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew",
        f"Register-ScheduledTask -TaskName {_ps_texto(_conf()['tarefa_vigia'])} -Description {_ps_texto(DESCRICAO_VIGIA)}"
        " -Action $acao -Trigger $gatilho -Principal $principal -Settings $ajustes -Force | Out-Null",
    ])
    s = _powershell(script)
    return s.codigo == 0, _resumo_saida(s)


def _usuario_windows() -> str:
    dominio, nome = os.environ.get("USERDOMAIN", ""), os.environ.get("USERNAME", "")
    return f"{dominio}\\{nome}" if dominio else nome


def xml_tarefa(pythonw: Path, vigia: Path, pasta: Path, usuario: str) -> str:
    """Definição da tarefa para ``schtasks /Create /XML``: gatilho no logon do usuário, sem limite de tempo."""
    e = escape
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>{e(DESCRICAO_VIGIA)}</Description>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>{e(usuario)}</UserId>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{e(usuario)}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>false</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{e(str(pythonw))}</Command>
      <Arguments>"{e(str(vigia))}"</Arguments>
      <WorkingDirectory>{e(str(pasta))}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def _registrar_tarefa_schtasks(pythonw: Path, vigia: Path, pasta: Path) -> tuple[bool, str]:
    # /XML em vez de só /SC ONLOGON: é o jeito de o schtasks tirar o limite de 72 h e definir a pasta de trabalho.
    fd, nome = tempfile.mkstemp(prefix="rotinas-vigia-", suffix=".xml")
    os.close(fd)
    arq = Path(nome)
    try:
        arq.write_bytes(xml_tarefa(pythonw, vigia, pasta, _usuario_windows()).encode("utf-16"))
        s = executar(["schtasks", "/Create", "/TN", _conf()["tarefa_vigia"], "/XML", arq, "/F"], timeout=60)
    finally:
        _apagar(arq)
    return s.codigo == 0, _resumo_saida(s)


def _registrar_atalho(pythonw: Path, vigia: Path, pasta: Path) -> tuple[bool, str]:
    lnk = caminho_atalho()
    lnk.parent.mkdir(parents=True, exist_ok=True)
    script = "\n".join([
        f"$atalho = (New-Object -ComObject WScript.Shell).CreateShortcut({_ps_texto(lnk)})",
        f"$atalho.TargetPath = {_ps_texto(pythonw)}",
        f"$atalho.Arguments = {_ps_texto(chr(34) + str(vigia) + chr(34))}",
        f"$atalho.WorkingDirectory = {_ps_texto(pasta)}",
        "$atalho.WindowStyle = 7",
        f"$atalho.Description = {_ps_texto(DESCRICAO_VIGIA)}",
        "$atalho.Save()",
    ])
    s = _powershell(script)
    if s.codigo == 0 and lnk.exists():
        return True, str(lnk)
    return False, _resumo_saida(s) if s.codigo != 0 else "o atalho não apareceu"


def passo_registrar_vigia() -> Passo:
    """Vigia no logon, janela oculta. Tenta tarefa agendada (PowerShell), depois schtasks, depois atalho."""
    if not NO_WINDOWS:
        return Passo(PULADO, "só no Windows")
    pythonw, vigia, pasta = caminho_pythonw(), caminho_vigia(), config.RAIZ
    if not vigia.is_file():
        return Passo(FALHOU, f"não achei {vigia}")
    aviso = "" if pythonw.name.lower() == "pythonw.exe" else f" (aviso: sem pythonw.exe, vai usar {pythonw.name})"
    erros = []
    for metodo, descricao, funcao in (
        ("tarefa-powershell", "tarefa agendada (PowerShell)", _registrar_tarefa_powershell),
        ("tarefa-schtasks", "tarefa agendada (schtasks)", _registrar_tarefa_schtasks),
        ("atalho", "atalho na pasta Inicializar", _registrar_atalho),
    ):
        try:
            ok, detalhe = funcao(pythonw, vigia, pasta)
        except Exception as e:  # noqa: BLE001 - uma tentativa com problema não impede a seguinte
            ok, detalhe = False, f"erro inesperado: {e.__class__.__name__}: {e}"
        if ok:
            if metodo != "atalho":
                _apagar(caminho_atalho())  # atalho de uma instalação antiga: a tarefa já cobre
            return Passo(OK, f"registrado como {descricao}{aviso}", {"vigia_registro": metodo})
        erros.append(f"{descricao}: {detalhe}")
    return Passo(FALHOU, " | ".join(erros), {"vigia_registro": None})


# -- vigia rodando

def _trava_ocupada(caminho: Path) -> bool | None:
    """True se outro processo segura a trava do vigia; None se não deu para testar."""
    if not caminho.exists():
        return False
    trava = fila.Trava(caminho)
    try:
        livre = trava.adquirir()
    except OSError:
        return None
    if livre:
        trava.liberar()
        return False
    return True


def estado_vigia() -> dict:
    """Se o vigia está rodando: a trava (``fila/vigia.lock``) manda; ``vigia.vivo`` recente é o plano B."""
    raiz = fila.pasta_fila()
    vivo = raiz / "vigia.vivo"
    info: dict = {}
    idade = None
    m = _mtime(vivo)
    if m is not None:
        idade = max(0.0, time.time() - m)
        try:
            info = json.loads(vivo.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            info = {}
    trava = _trava_ocupada(raiz / "vigia.lock")
    recente = idade is not None and idade < float(_conf().get("vigia_vivo_max_s", 120))
    rodando = trava if trava is not None else recente
    return {
        "rodando": bool(rodando),
        "trava_ocupada": trava,
        "sinal_recente": recente,
        "idade_sinal_s": None if idade is None else round(idade),
        "estado": info.get("estado"),
        "pedido": info.get("pedido"),
    }


def _tempo(segundos: float | None) -> str:
    if segundos is None:
        return "nunca"
    if segundos < 120:
        return f"{segundos:.0f} s"
    if segundos < 7200:
        return f"{segundos / 60:.0f} min"
    return f"{segundos / 3600:.0f} h"


def passo_iniciar_vigia(espera_s: float | None = None) -> Passo:
    if not NO_WINDOWS:
        return Passo(PULADO, "fora do Windows o vigia não é iniciado aqui (use: python -m rotinas vigia)")
    if estado_vigia()["rodando"]:
        return Passo(OK, "já estava rodando")
    vigia = caminho_vigia()
    if not vigia.is_file():
        return Passo(FALHOU, f"não achei {vigia}")
    raiz = fila.preparar_pastas()
    _apagar(raiz / "parar.flag")  # sobra de uma parada antiga faria o vigia sair na hora
    vivo = raiz / "vigia.vivo"
    antes = _mtime(vivo)
    pid = iniciar_destacado([caminho_pythonw(), vigia], cwd=config.RAIZ)
    if pid is None:
        return Passo(FALHOU, f"não consegui iniciar {caminho_pythonw()}")
    espera = float(espera_s if espera_s is not None else _conf().get("vigia_iniciar_espera_s", 15))
    limite = time.monotonic() + espera
    while True:
        # confere pelo sinal de vida novo (e não pela trava, para não disputar a trava com o vigia que está subindo)
        m = _mtime(vivo)
        if m is not None and (antes is None or m > antes):
            return Passo(OK, f"iniciado (processo {pid})", {"pid": pid})
        if time.monotonic() >= limite:
            break
        time.sleep(0.5)
    # Com pedido pendente na fila, o vigia pega a trava e já começa a trabalhar: o primeiro sinal de vida
    # só vem quando o pedido termina. Trava ocupada aqui = ele subiu.
    if _trava_ocupada(raiz / "vigia.lock"):
        return Passo(OK, f"iniciado (processo {pid}); já está executando um pedido da fila", {"pid": pid})
    return Passo(FALHOU, f"iniciei o processo {pid}, mas ele não deu sinal de vida em {espera:.0f} s; "
                         f"veja {config.pastas().logs} (vigia-*.log e vigia-falha.txt)")


def parar_vigia(espera_s: float | None = None) -> int:
    """Grava ``fila/parar.flag`` e espera o vigia sair. 0 = parado (ou não rodava); 3 = ocupado, não parou."""
    espera = float(espera_s if espera_s is not None else _conf().get("vigia_parar_espera_s", 30))
    raiz = fila.pasta_fila()
    flag = raiz / "parar.flag"
    if not estado_vigia()["rodando"]:
        if not _so_do_windows(raiz):
            _apagar(flag)
        print("O vigia não está rodando. Nada a parar.", flush=True)
        return 0
    raiz.mkdir(parents=True, exist_ok=True)
    flag.write_text(f"parada pedida em {datetime.now().isoformat(timespec='seconds')}\n", encoding="utf-8")
    print(f"Pedi para o vigia parar (fila\\parar.flag). Esperando até {espera:.0f} s...", flush=True)
    limite = time.monotonic() + espera
    while time.monotonic() < limite:
        time.sleep(0.5)
        if not estado_vigia()["rodando"]:
            _apagar(flag)
            print("Vigia parado.", flush=True)
            return 0
    _apagar(flag)  # não deixa o flag para trás: o vigia segue trabalhando normalmente
    pedido = estado_vigia().get("pedido")
    qual = f" ({pedido})" if pedido else ""
    print(f"O vigia ainda está executando um pedido{qual}. Não parei nada: ele continua trabalhando. "
          "Espere o pedido terminar e rode de novo.", flush=True)
    return 3


# -- execução do instalar

def _executar_passo(funcao) -> Passo:
    try:
        return funcao()
    except Exception as e:  # noqa: BLE001 - um passo com problema não derruba os outros
        log.debug("Passo falhou", exc_info=True)
        return Passo(FALHOU, f"erro inesperado: {e.__class__.__name__}: {e}")


def _mostrar_passo(passo: Passo, cores: bool) -> None:
    rotulo = {OK: "OK", FALHOU: "FALHOU", PULADO: "PULADO"}.get(passo.estado, passo.estado)
    estado_cor = {OK: VERDE, FALHOU: VERMELHO, PULADO: PULADO}.get(passo.estado, "")
    print(f"        {_pintar(rotulo, estado_cor, cores)}: {registro.ocultar(passo.detalhe)}", flush=True)


def _gravar_registro(resultados: list[tuple[str, Passo]]) -> None:
    """Guarda em ``registros/instalacao.json`` o que funcionou (qual adb, como o vigia foi registrado)."""
    try:
        pasta = config.pastas().registros
        if _so_do_windows(pasta):
            return
        extras: dict = {}
        for _, p in resultados:
            extras.update(p.extra)
        dados = {
            "em": datetime.now().astimezone().isoformat(timespec="seconds"),
            "sistema": str(config.RAIZ),
            "python": platform.python_version(),
            "passos": [{"passo": t, "estado": p.estado, "detalhe": p.detalhe} for t, p in resultados],
            **{k: v for k, v in extras.items() if isinstance(v, (str, int, type(None)))},
        }
        pasta.mkdir(parents=True, exist_ok=True)
        (pasta / "instalacao.json").write_text(registro.ocultar(json.dumps(dados, ensure_ascii=False, indent=2)),
                                               encoding="utf-8")
    except Exception as e:  # noqa: BLE001 - o registro é só informativo
        print(f"        (aviso: não consegui gravar registros/instalacao.json: {e})", flush=True)


def cli_instalar(argv: list[str]) -> int:
    p = argparse.ArgumentParser(
        prog="python -m rotinas instalar",
        description="Parte Python do instalar.bat: ffmpeg, adb, pastas, .env, git e vigia. Pode rodar de novo à vontade.",
    )
    p.add_argument("--sem-winget", action="store_true", help="não instala nada pelo winget, só confere")
    p.add_argument("--sem-vigia", action="store_true", help="não registra nem inicia o vigia")
    p.add_argument("--nao-abrir-env", action="store_true", help="não abre o .env no Bloco de Notas")
    so = p.add_mutually_exclusive_group()
    so.add_argument("--parar-vigia", action="store_true",
                    help="só para o vigia (grava fila/parar.flag e espera ele sair); sai com 3 se ele estiver ocupado")
    so.add_argument("--iniciar-vigia", action="store_true", help="só inicia o vigia, se ele não estiver rodando")
    p.add_argument("--espera", type=float, help="segundos de espera do --parar-vigia / --iniciar-vigia")
    a = p.parse_args(argv)
    _preparar_saida()
    cores = _habilitar_cores()

    if a.parar_vigia:
        return parar_vigia(a.espera)
    if a.iniciar_vigia:
        passo = _executar_passo(lambda: passo_iniciar_vigia(a.espera))
        _mostrar_passo(passo, cores)
        return 1 if passo.estado == FALHOU else 0

    pular_vigia = lambda: Passo(PULADO, "rodei com --sem-vigia")  # noqa: E731
    passos = [
        ("ffmpeg e ffprobe", lambda: passo_ffmpeg(not a.sem_winget)),
        ("adb (para o BlueStacks)", lambda: passo_adb(not a.sem_winget)),
        ("pastas de trabalho", lambda: passo_pastas()),
        ("arquivo .env", lambda: passo_env(not a.nao_abrir_env)),
        ("identidade do git neste clone", lambda: passo_git()),
        ("vigia no logon do Windows", pular_vigia if a.sem_vigia else lambda: passo_registrar_vigia()),
        ("iniciar o vigia agora", pular_vigia if a.sem_vigia else lambda: passo_iniciar_vigia()),
    ]
    print(f"Rotinas Ferreira: instalação (parte Python) em {config.RAIZ}", flush=True)
    resultados: list[tuple[str, Passo]] = []
    for n, (titulo, funcao) in enumerate(passos, 1):
        print(f"  ({n}/{len(passos)}) {titulo}...", flush=True)
        passo = _executar_passo(funcao)
        _mostrar_passo(passo, cores)
        resultados.append((titulo, passo))
    _gravar_registro(resultados)
    falhas = [t for t, x in resultados if x.estado == FALHOU]
    if falhas:
        print(_pintar(f"  {len(falhas)} passo(s) com FALHOU: {', '.join(falhas)}. O resto foi feito; "
                      "resolva o que a mensagem diz e rode de novo.", VERMELHO, cores), flush=True)
    else:
        print(_pintar("  Parte Python terminada sem falhas.", VERDE, cores), flush=True)
    return len(falhas)


# ---------------------------------------------------------------- verificar

def _versao_minima() -> tuple[int, ...]:
    return tuple(int(x) for x in str(_conf().get("python_minimo", "3.10")).split("."))


def _v_python() -> list[Item]:
    minimo = _versao_minima()
    ok = sys.version_info[: len(minimo)] >= minimo
    txt_min = ".".join(map(str, minimo))
    return [Item("python", f"Python >= {txt_min}", VERDE if ok else VERMELHO,
                 f"{platform.python_version()} ({sys.executable})",
                 "" if ok else f"Instale o Python 3.12 (winget install -e --id {_conf()['winget']['python']} "
                               "--scope user) e rode o instalar.bat de novo.")]


def _v_pacotes() -> list[Item]:
    itens = []
    requisitos = config.RAIZ / "requirements.txt"
    for modulo, pacote in (_conf().get("pacotes_python") or {}).items():
        ok, info = _importavel(modulo)
        acao = "" if ok else f'Rode o atualizar.bat, ou: "{sys.executable}" -m pip install -r "{requisitos}"'
        itens.append(Item(f"pacote:{modulo}", f"pacote {modulo} ({pacote})", VERDE if ok else VERMELHO, info, acao))
    return itens


def _v_programas() -> list[Item]:
    ids = _conf()["winget"]
    itens = []
    for nome in ("ffmpeg", "ffprobe"):
        c = ferramentas.localizar(nome)
        itens.append(Item(nome, nome, VERDE if c else VERMELHO, c or "não encontrado",
                          "" if c else f"Rode o instalar.bat de novo (ou: winget install -e --id {ids['ffmpeg']})."))
    adb = ferramentas.localizar("adb", candidatos_adb())
    if adb:
        itens.append(Item("adb", "adb", VERDE, descrever_adb(adb)))
    elif not NO_WINDOWS:
        itens.append(Item("adb", "adb", NAO_SE_APLICA, "não encontrado; fora do Windows não se aplica"))
    else:
        itens.append(Item("adb", "adb", VERMELHO, "não encontrado",
                          f"Rode o instalar.bat de novo (ou: winget install -e --id {ids['adb']}); "
                          "o HD-Adb.exe do BlueStacks também serve."))
    git = ferramentas.localizar("git")
    itens.append(Item("git", "git", VERDE if git else VERMELHO, git or "não encontrado",
                      "" if git else f"Rode o instalar.bat de novo (ou: winget install -e --id {ids['git']})."))
    return itens


def _v_pastas() -> list[Item]:
    rotinas = config.pastas().rotinas
    if _so_do_windows(rotinas):
        return [Item("pastas", "pastas de trabalho", NAO_SE_APLICA, f"caminho do Windows ({rotinas})")]
    lista = pastas_de_trabalho()
    faltando = [q for q in lista if not q.is_dir()]
    if not faltando:
        return [Item("pastas", "pastas de trabalho", VERDE, f"{len(lista)} pastas em {rotinas}")]

    def nome(q: Path) -> str:
        try:
            return str(q.relative_to(rotinas))
        except ValueError:
            return str(q)

    return [Item("pastas", "pastas de trabalho", VERMELHO, "faltam: " + ", ".join(nome(q) for q in faltando),
                 f'Rode: cd /d "{config.RAIZ}" && "{sys.executable}" -m rotinas instalar')]


def _v_env() -> list[Item]:
    env = config.caminho_env()
    existe = env.is_file()
    itens = [Item("env", "arquivo .env", VERDE if existe else VERMELHO, str(env) if existe else "não existe",
                  "" if existe else "Rode o instalar.bat: ele copia o .env.example para .env e abre no Bloco de Notas.")]
    for nome in _conf().get("env_obrigatorias", []):
        cheio = bool(config.segredo(nome))
        itens.append(Item(f"env:{nome}", f"{nome} no .env", VERDE if cheio else VERMELHO,
                          "preenchido" if cheio else "vazio",
                          "" if cheio else f'Abra o .env (notepad "{env}"), preencha {nome}, salve e rode de novo.'))
    return itens


def _v_supabase() -> list[Item]:
    """Login do usuário das rotinas + leitura de 1 produto (as tabelas têm RLS só para usuário logado)."""
    from . import banco

    nome = "Supabase (leitura)"
    r = banco.testar_leitura(float(_conf().get("supabase_timeout_s", 15)))
    if r["ok"]:
        return [Item("supabase", nome, VERDE, r["mensagem"])]
    if not r["configurado"]:
        return [Item("supabase", nome, VERMELHO, "não testei: " + r["mensagem"],
                     "Preencha no .env SUPABASE_URL, SUPABASE_KEY (chave pública), SUPABASE_EMAIL e SUPABASE_SENHA "
                     "(usuário das rotinas) e rode de novo.")]
    return [Item("supabase", nome, VERMELHO, r["mensagem"],
                 "Confira no .env o usuário das rotinas (SUPABASE_EMAIL/SUPABASE_SENHA), a SUPABASE_KEY e a internet.")]


def estado_registro_vigia() -> tuple[str | None, str]:
    nome = _conf()["tarefa_vigia"]
    if executar(["schtasks", "/Query", "/TN", nome], timeout=30).codigo == 0:
        return "tarefa", f'tarefa agendada "{nome}"'
    lnk = caminho_atalho()
    if lnk.exists():
        return "atalho", f"atalho em Inicializar ({lnk.name})"
    return None, "não registrado"


def _v_vigia() -> list[Item]:
    itens = []
    if not NO_WINDOWS:
        itens.append(Item("vigia_registrado", "vigia no logon", NAO_SE_APLICA, "só no Windows"))
    else:
        tipo, detalhe = estado_registro_vigia()
        itens.append(Item("vigia_registrado", "vigia no logon", VERDE if tipo else VERMELHO, detalhe,
                          "" if tipo else f'Rode: cd /d "{config.RAIZ}" && "{sys.executable}" -m rotinas instalar'))
    est = estado_vigia()
    sinal = _tempo(est["idade_sinal_s"])
    if est["rodando"]:
        extra = f", executando {est['pedido']}" if est.get("estado") == "executando" and est.get("pedido") else ""
        itens.append(Item("vigia_vivo", "vigia rodando", VERDE, f"sim (último sinal de vida há {sinal}{extra})"))
    elif not NO_WINDOWS:
        itens.append(Item("vigia_vivo", "vigia rodando", NAO_SE_APLICA, "fora do Windows o vigia não roda sozinho"))
    else:
        detalhe = "nunca rodou" if est["idade_sinal_s"] is None else f"parado (último sinal de vida há {sinal})"
        itens.append(Item("vigia_vivo", "vigia rodando", VERMELHO, detalhe,
                          f'Inicie: cd /d "{config.RAIZ}" && "{sys.executable}" -m rotinas instalar --iniciar-vigia '
                          "(ou faça logoff e logon)"))
    return itens


def verificacoes() -> list[Item]:
    itens: list[Item] = []
    for chave, funcao in (("python", _v_python), ("pacotes", _v_pacotes), ("programas", _v_programas),
                          ("pastas", _v_pastas), ("env", _v_env), ("supabase", _v_supabase), ("vigia", _v_vigia)):
        try:
            itens += funcao()
        except Exception as e:  # noqa: BLE001 - um item com problema não derruba a tabela
            itens.append(Item(chave, chave, VERMELHO, f"erro ao conferir: {e.__class__.__name__}: {e}",
                              "Mande esta tela para a IA."))
    return itens


def _tabela(itens: list[Item], cores: bool) -> str:
    largura = max(len(i.nome) for i in itens)
    linhas = ["Verificação da instalação: Rotinas Ferreira", f"Pasta do sistema: {config.RAIZ}", ""]
    for i in itens:
        simbolo = _pintar(_SIMBOLOS.get(i.estado, "?"), i.estado, cores)
        linhas.append(f"  {simbolo} {i.nome.ljust(largura)}  {i.detalhe}")
        if i.estado == VERMELHO and i.acao:
            linhas.append(f"      → O que fazer: {i.acao}")
    falhas = sum(1 for i in itens if i.estado == VERMELHO)
    linhas.append("")
    if falhas:
        linhas.append(_pintar(f"{falhas} item(ns) com ✗. Faça o que está em \"O que fazer\" e confira de novo: "
                              "python -m rotinas verificar", VERMELHO, cores))
    else:
        linhas.append(_pintar("Tudo verde.", VERDE, cores))
    return "\n".join(linhas)


def cli_verificar(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="python -m rotinas verificar",
                                description="Confere a instalação e mostra o que está verde e o que falta.")
    p.add_argument("--json", action="store_true", help="saída em JSON (usada pelo diagnóstico)")
    a = p.parse_args(argv)
    _preparar_saida()
    if a.json:
        # no --json a saída padrão é só o JSON: o que alguma biblioteca imprimir ao ser importada vai para o stderr
        with contextlib.redirect_stdout(sys.stderr):
            itens = verificacoes()
    else:
        itens = verificacoes()
    falhas = sum(1 for i in itens if i.estado == VERMELHO)
    if a.json:
        dados = {
            "gerado_em": datetime.now().astimezone().isoformat(timespec="seconds"),
            "sistema_operacional": platform.platform(),
            "python": platform.python_version(),
            "pasta_sistema": str(config.RAIZ),
            "resumo": {
                "ok": sum(1 for i in itens if i.estado == VERDE),
                "falhas": falhas,
                "nao_se_aplica": sum(1 for i in itens if i.estado == NAO_SE_APLICA),
            },
            "itens": [asdict(i) for i in itens],
        }
        print(registro.ocultar(json.dumps(dados, ensure_ascii=False, indent=2)))
    else:
        print(registro.ocultar(_tabela(itens, _habilitar_cores())))
    return falhas
