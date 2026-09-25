"""Diagnóstico do PC (BRIEFING §6): versões, pastas, ``.env`` (só nomes), BlueStacks/ADB,
tela inicial do Instagram, gabarito do CapCut e leitura do Supabase.

Grava ``diagnostico.json`` + arquivos (XML e print da tela, cópia do rascunho "0925", árvore do
projeto) na pasta de saída e monta um resumo em português. Cada item roda isolado: um erro vira
``{"erro": ...}`` no JSON e não derruba os outros. Nunca grava nada na pasta do CapCut e nunca
mostra valor do ``.env``.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import importlib.util
import json
import os
import platform
import re
import shutil
import sys
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path

from . import __version__, config, ferramentas, registro
from .contexto import Contexto, carimbo

log = registro.obter("diagnostico")

dormir = time.sleep  # trocado nos testes

ESTADOS_ADB = ("device", "offline", "unauthorized", "no permissions", "recovery", "sideload",
               "bootloader", "authorizing", "connecting", "host")

INSTRUCAO_ADB = ("Abra o BlueStacks > Configurações (engrenagem) > Avançado > ligue "
                 "'Android Debug Bridge (ADB)' > Salvar alterações. Depois rode o diagnostico.bat de novo.")


# ---------------------------------------------------------------- utilidades

def _cfg() -> dict:
    return config.carregar("diagnostico")


def _cfg_bluestacks() -> dict:
    try:
        return config.carregar("bluestacks")
    except config.ErroConfig:
        return {}


def _erro(e: BaseException) -> dict:
    return {
        "erro": registro.ocultar(str(e) or e.__class__.__name__),
        "tipo_erro": e.__class__.__name__,
        "detalhe": registro.ocultar(traceback.format_exc()[-1500:]),
    }


def _seguro(funcao, *args, **kwargs):
    """Roda um item do diagnóstico; erro vira ``{"erro": ...}`` em vez de derrubar o resto."""
    try:
        return funcao(*args, **kwargs)
    except Exception as e:  # noqa: BLE001 - um item com erro não derruba os outros
        log.warning("Item do diagnóstico com erro (%s): %s", getattr(funcao, "__name__", "?"), e)
        return _erro(e)


def _tem_erro(valor) -> bool:
    return isinstance(valor, dict) and "erro" in valor


def _texto(r) -> str:
    return "\n".join(t for t in ((r.stdout or "").strip(), (r.stderr or "").strip()) if t)


def _linhas(r, n: int = 1) -> str | None:
    linhas = [x.strip() for x in _texto(r).splitlines() if x.strip()]
    return " | ".join(linhas[:n]) if linhas else None


def _mb(tamanho: int) -> float:
    return round(tamanho / (1024 * 1024), 2)


def _legivel(tamanho: int) -> str:
    if tamanho < 1024:
        return f"{tamanho} B"
    if tamanho < 1024 * 1024:
        return f"{tamanho / 1024:.1f} KB"
    return f"{tamanho / (1024 * 1024):.1f} MB"


def _ocultar_dados(dados):
    """Aplica ``registro.ocultar`` em todos os textos de uma estrutura (dict/list)."""
    if isinstance(dados, str):
        return registro.ocultar(dados)
    if isinstance(dados, dict):
        return {k: _ocultar_dados(v) for k, v in dados.items()}
    if isinstance(dados, (list, tuple)):
        return [_ocultar_dados(v) for v in dados]
    return dados


def gravar_json(caminho: Path, dados: dict) -> None:
    texto = json.dumps(_ocultar_dados(dados), ensure_ascii=False, indent=2, default=str)
    Path(caminho).write_text(registro.ocultar(texto), encoding="utf-8")


def _com_limite(funcao, segundos: float, nome: str):
    """Roda ``funcao`` numa thread e desiste depois de ``segundos`` (o uiautomator2 pode travar)."""
    caixa: dict = {}

    def alvo():
        try:
            caixa["valor"] = funcao()
        except BaseException as e:  # noqa: BLE001 - devolvido para quem chamou
            caixa["erro"] = e

    t = threading.Thread(target=alvo, name=f"diagnostico-{nome}", daemon=True)
    t.start()
    t.join(segundos)
    if t.is_alive():
        raise TimeoutError(f"{nome} não respondeu em {segundos:.0f} s")
    if "erro" in caixa:
        raise caixa["erro"]
    return caixa.get("valor")


class _Adb:
    """``adb`` puro via ``ferramentas.rodar`` (sem janela, UTF-8)."""

    def __init__(self, caminho: str, serial: str | None = None, timeout: float = 30):
        self.caminho = caminho
        self.serial = serial
        self.timeout = timeout

    def __call__(self, *args: str, timeout: float | None = None, verificar: bool = False):
        cmd = [self.caminho] + (["-s", self.serial] if self.serial else []) + list(args)
        return ferramentas.rodar(cmd, timeout=timeout or self.timeout, verificar=verificar)

    def shell(self, comando: str, **kw):
        return self("shell", comando, **kw)

    def saida(self, comando: str) -> str:
        return (self.shell(comando, verificar=True).stdout or "").strip()


# ---------------------------------------------------------------- versões

def _sistema() -> dict:
    d = {
        "plataforma": platform.platform(),
        "sistema": platform.system(),
        "release": platform.release(),
        "versao": platform.version(),
        "maquina": platform.machine(),
    }
    edicao = getattr(platform, "win32_edition", None)
    if edicao and platform.system() == "Windows":
        d["edicao"] = edicao()
    return d


def _python() -> dict:
    return {"versao": platform.python_version(), "executavel": sys.executable, "bits": 64 if sys.maxsize > 2**32 else 32}


def _pacotes() -> dict:
    pacotes = {}
    for modulo, distribuicao in _cfg()["pacotes_python"].items():
        try:
            pacotes[modulo] = importlib.metadata.version(distribuicao)
        except importlib.metadata.PackageNotFoundError:
            pacotes[modulo] = None
    return pacotes


def _programa(nome: str, argumento: str = "-version", candidatos: list[str] | None = None, linhas: int = 1) -> dict:
    caminho = ferramentas.localizar(nome, candidatos)
    if not caminho:
        return {"encontrado": False}
    r = ferramentas.rodar([caminho, argumento], timeout=30, verificar=False)
    return {"encontrado": True, "caminho": caminho, "versao": _linhas(r, linhas)}


def _repositorio() -> dict:
    git = ferramentas.localizar("git")
    if not git:
        return {"git": False}

    def g(*args: str) -> str | None:
        r = ferramentas.rodar([git, *args], timeout=30, verificar=False, cwd=config.RAIZ)
        return (r.stdout or "").strip() if r.returncode == 0 else None

    status = g("status", "--porcelain")
    return {
        "raiz": str(config.RAIZ),
        "commit": g("rev-parse", "HEAD"),
        "ramo": g("rev-parse", "--abbrev-ref", "HEAD"),
        "data_commit": g("log", "-1", "--format=%ci"),
        "alteracoes_locais": len(status.splitlines()) if status is not None else None,
    }


def _bluestacks_registro() -> dict:
    reg = ferramentas.localizar("reg")
    if not reg:
        return {"disponivel": False, "motivo": "comando 'reg' não existe (não é Windows)"}
    chave = _cfg()["bluestacks_registro"]
    r = ferramentas.rodar([reg, "query", chave], timeout=30, verificar=False)
    if r.returncode != 0:
        return {"disponivel": True, "encontrado": False, "saida": _linhas(r, 2)}
    permitidos = set(_cfg()["bluestacks_registro_valores"])
    valores = {}
    for linha in (r.stdout or "").splitlines():
        m = re.match(r"^\s+(.+?)\s{2,}REG_\w+\s{2,}(.*)$", linha)
        if m and m.group(1).strip() in permitidos:
            valores[m.group(1).strip()] = m.group(2).strip()
    return {"disponivel": True, "encontrado": True, **valores}


def ler_conf(caminho: Path) -> dict[str, str]:
    """Lê o ``bluestacks.conf`` (linhas ``chave="valor"``)."""
    valores: dict[str, str] = {}
    for linha in Path(caminho).read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r'^\s*([^=#\s]+)\s*=\s*"?(.*?)"?\s*$', linha)
        if m:
            valores[m.group(1)] = m.group(2)
    return valores


def _caminho_conf() -> Path:
    caminho = config.expandir(_cfg_bluestacks().get("bluestacks_conf") or "bluestacks.conf")
    if caminho.is_file():
        return caminho
    reg = _seguro(_bluestacks_registro)
    pasta = reg.get("UserDefinedDir") if isinstance(reg, dict) else None
    if pasta and (Path(pasta) / "bluestacks.conf").is_file():
        return Path(pasta) / "bluestacks.conf"
    return caminho


def _bluestacks_versao() -> dict:
    d = {"registro": _seguro(_bluestacks_registro)}
    caminho = _caminho_conf()
    if caminho.is_file():
        d["conf"] = {k: v for k, v in ler_conf(caminho).items() if "version" in k.lower()}
    return d


def _capcut_versoes() -> dict:
    apps = config.pastas().capcut_apps
    if not apps.is_dir():
        return {"pasta_apps": str(apps), "existe": False}
    versoes = sorted(
        (p.name for p in apps.iterdir() if p.is_dir() and re.fullmatch(r"\d+(\.\d+)+", p.name)),
        key=lambda v: tuple(int(x) for x in v.split(".")),
    )
    return {"pasta_apps": str(apps), "existe": True, "instaladas": versoes, "mais_recente": versoes[-1] if versoes else None}


def versoes_principais() -> dict:
    """Versões que vão em toda execução do ``testar`` (rápido)."""
    adb = _cfg_bluestacks().get("adb_candidatos")
    return {
        "rotinas": __version__,
        "gerado_em": datetime.now().astimezone().isoformat(timespec="seconds"),
        "sistema": _seguro(_sistema),
        "python": _seguro(_python),
        "pacotes": _seguro(_pacotes),
        "repositorio": _seguro(_repositorio),
        "ffmpeg": _seguro(_programa, "ffmpeg"),
        "git": _seguro(_programa, "git", "--version"),
        "adb": _seguro(_programa, "adb", "version", adb, 2),
    }


def versoes() -> dict:
    d = versoes_principais()
    d["ffprobe"] = _seguro(_programa, "ffprobe")
    d["bluestacks"] = _seguro(_bluestacks_versao)
    d["capcut"] = _seguro(_capcut_versoes)
    return d


def verificar_instalacao() -> dict:
    """Reaproveita ``python -m rotinas verificar --json`` quando ele já existe nesta versão."""
    if importlib.util.find_spec("rotinas.instalacao") is None:
        return {"disponivel": False, "motivo": "rotinas.instalacao ainda não existe nesta versão"}
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    r = ferramentas.rodar(
        [sys.executable, "-m", "rotinas", "verificar", "--json"],
        timeout=_cfg()["verificar_timeout_s"], verificar=False, cwd=config.RAIZ,
    )
    try:
        dados = json.loads(r.stdout or "")
    except ValueError:
        dados = None
    d = {"disponivel": True, "codigo": r.returncode, "resultado": dados}
    if dados is None:
        d["saida"] = _texto(r)[-3000:]
    return d


# ---------------------------------------------------------------- pastas e .env

def pastas() -> dict:
    p = config.pastas()
    d = {}
    for nome in ("stories_fonte", "rotinas", "sistema", "capcut_rascunhos", "capcut_apps", "videos", "fila", "logs", "registros"):
        caminho = getattr(p, nome)
        d[nome] = {"caminho": str(caminho), "existe": caminho.is_dir()}
    d["stories_fonte"]["pastas_de_data"] = _pastas_de_data(p.stories_fonte)
    return d


def _pastas_de_data(fonte: Path) -> list[dict]:
    """Só os nomes das pastas de data e quantos arquivos cada uma tem (nada de conteúdo)."""
    if not fonte.is_dir():
        return []
    limite = int(_cfg()["max_pastas_de_data"])
    subpastas = sorted((q for q in fonte.iterdir() if q.is_dir()), key=lambda q: q.name, reverse=True)[:limite]
    itens = []
    for q in subpastas:
        try:
            itens.append({"nome": q.name, "arquivos": sum(1 for x in q.iterdir() if x.is_file())})
        except OSError as e:
            itens.append({"nome": q.name, "erro": str(e)})
    return itens


def _nomes_env_exemplo() -> list[str]:
    exemplo = config.RAIZ / ".env.example"
    if not exemplo.exists():
        return []
    return list(config.ler_env(exemplo).keys())


def env() -> dict:
    """Só os NOMES das variáveis e se estão preenchidas. Nunca os valores."""
    caminho = config.caminho_env()
    valores = config.ler_env(caminho)
    nomes = sorted(set(valores) | set(_nomes_env_exemplo()))
    variaveis = {}
    for nome in nomes:
        if nome not in valores:
            variaveis[nome] = "ausente"
        else:
            variaveis[nome] = "preenchida" if valores[nome].strip() else "vazia"
    return {"arquivo": str(caminho), "existe": caminho.exists(), "variaveis": variaveis}


# ---------------------------------------------------------------- BlueStacks / ADB

def _resumo_conf(caminho: Path) -> dict:
    if not caminho.is_file():
        return {"caminho": str(caminho), "existe": False}
    chaves = ler_conf(caminho)
    instancias: dict[str, dict] = {}
    for k, v in chaves.items():
        m = re.fullmatch(r"bst\.instance\.([^.]+)\.(status\.adb_port|adb_port|display_name|enable_adb_access)", k)
        if m:
            instancias.setdefault(m.group(1), {})[m.group(2)] = v
    return {
        "caminho": str(caminho),
        "existe": True,
        "enable_adb_access": chaves.get("bst.enable_adb_access"),
        "instancias": instancias,
    }


def _portas_do_conf(conf: dict) -> set[int]:
    portas = set()
    for inst in (conf.get("instancias") or {}).values():
        for chave in ("status.adb_port", "adb_port"):
            valor = str(inst.get(chave) or "").strip()
            if valor.isdigit() and int(valor) > 0:
                portas.add(int(valor))
    return portas


def dispositivos(adb: str) -> list[dict]:
    r = _Adb(adb, timeout=_cfg()["adb_timeout_s"])("devices", "-l")
    itens = []
    padrao = re.compile(r"^(\S+)\s+(" + "|".join(re.escape(e) for e in ESTADOS_ADB) + r")\b\s*(.*)$")
    for linha in (r.stdout or "").splitlines():
        m = padrao.match(linha.strip())
        if m:
            itens.append({"serial": m.group(1), "estado": m.group(2), "detalhes": m.group(3).strip()})
    return itens


def conectar(adb: str, endereco: str) -> dict:
    r = _Adb(adb, timeout=_cfg()["adb_timeout_s"])("connect", endereco)
    texto = _texto(r)
    baixo = texto.lower()
    ok = "connected to" in baixo and "cannot" not in baixo and "failed" not in baixo
    return {"ok": ok, "saida": texto[-300:]}


def _escolher_serial(lista, conexoes: dict, padrao: str | None) -> str | None:
    if not isinstance(lista, list):
        return None
    prontos = [d["serial"] for d in lista if d.get("estado") == "device"]
    preferidos = ([padrao] if padrao else []) + [e for e, c in conexoes.items() if isinstance(c, dict) and c.get("ok")]
    for s in preferidos:
        if s in prontos:
            return s
    return prontos[0] if prontos else None


def bluestacks() -> dict:
    cfg_b, cfg_d = _cfg_bluestacks(), _cfg()
    res: dict = {"conf": _seguro(_resumo_conf, _caminho_conf())}
    conf = res["conf"] if isinstance(res["conf"], dict) else {}
    padrao = cfg_b.get("dispositivo_padrao")
    portas = set(int(p) for p in cfg_d.get("adb_portas_padrao") or []) | _portas_do_conf(conf)
    if padrao and padrao.startswith("127.0.0.1:") and padrao.rsplit(":", 1)[1].isdigit():
        portas.add(int(padrao.rsplit(":", 1)[1]))
    res["portas"] = sorted(portas)
    flag = conf.get("enable_adb_access")

    adb = ferramentas.localizar("adb", cfg_b.get("adb_candidatos"))
    res["adb"] = adb
    if not adb:
        res["ligado"] = None
        res["mensagem"] = ("Não encontrei o adb (nem o HD-Adb.exe do BlueStacks). Rode o instalar.bat de novo.")
        return res

    res["dispositivos_antes"] = _seguro(dispositivos, adb)
    res["conexoes"] = {f"127.0.0.1:{p}": _seguro(conectar, adb, f"127.0.0.1:{p}") for p in sorted(portas)}
    res["dispositivos"] = _seguro(dispositivos, adb)
    serial = _escolher_serial(res["dispositivos"], res["conexoes"], padrao)
    res["serial"] = serial

    if serial:
        res["ligado"] = True
        res["mensagem"] = f"ADB do BlueStacks ligado e conectado em {serial}."
    elif flag == "0":
        res["ligado"] = False
        res["mensagem"] = "O ADB do BlueStacks está DESLIGADO. " + INSTRUCAO_ADB
    elif flag == "1":
        res["ligado"] = True
        res["mensagem"] = ("O ADB está ligado na configuração do BlueStacks, mas não conectou. "
                           "Abra o BlueStacks (tela inicial do Android) e rode o diagnostico.bat de novo.")
    else:
        res["ligado"] = None
        res["mensagem"] = ("Não consegui conectar ao BlueStacks pelo ADB. Confira se o BlueStacks está aberto. "
                           "Se estiver: " + INSTRUCAO_ADB)
    return res


# ---------------------------------------------------------------- Android / Instagram

def _instagram_versao(a: _Adb, pacote: str) -> dict:
    r = a.shell(f"dumpsys package {pacote}")
    texto = r.stdout or ""
    nome = re.search(r"versionName=(\S+)", texto)
    codigo = re.search(r"versionCode=(\d+)", texto)
    return {"pacote": pacote, "instalado": bool(nome), "versao": nome.group(1) if nome else None,
            "versionCode": codigo.group(1) if codigo else None}


def _listar_pastas_android(a: _Adb, pasta: str) -> dict:
    r = a.shell(f'ls -l "{pasta}"')
    if r.returncode != 0:
        return {"existe": False, "saida": _linhas(r, 2)}
    nomes = []
    for linha in (r.stdout or "").splitlines():
        partes = linha.split(None, 7)
        if linha.startswith("d") and len(partes) == 8:
            nomes.append(partes[7])
    return {"existe": True, "pastas": sorted(nomes)}


def _mediastore(a: _Adb) -> dict:
    r = a.shell('content query --uri content://media/external/file --projection _id --where "_id>0"', timeout=90)
    texto = r.stdout or ""
    itens = sum(1 for linha in texto.splitlines() if linha.startswith("Row:"))
    responde = r.returncode == 0 and (itens > 0 or "No result found" in texto)
    d = {"responde": responde, "itens": itens}
    if not responde:
        d["saida"] = _texto(r)[-300:]
    return d


def _salvar_xml(a: _Adb, remoto: str, destino: Path) -> dict:
    texto = ""
    for _ in range(2):
        r = a.shell(f"uiautomator dump {remoto}")
        texto = _texto(r)
        if "dumped to" in texto.lower():
            break
        dormir(2)
    a("pull", remoto, str(destino), verificar=True)
    a.shell(f"rm -f {remoto}")
    conteudo = destino.read_text(encoding="utf-8", errors="replace")
    pacote = re.search(r'package="([^"]+)"', conteudo)
    return {"arquivo": destino.name, "pacote_na_tela": pacote.group(1) if pacote else None, "saida_dump": texto[-200:]}


def _salvar_print(a: _Adb, remoto: str, destino: Path) -> dict:
    a.shell(f"screencap -p {remoto}", verificar=True)
    a("pull", remoto, str(destino), verificar=True)
    a.shell(f"rm -f {remoto}")
    return {"arquivo": destino.name, "tamanho_kb": round(destino.stat().st_size / 1024, 1)}


def _tela_inicial(a: _Adb, pacote: str, pasta: Path) -> dict:
    cfg_d = _cfg()
    tmp = cfg_d["android_pasta_temporaria"].rstrip("/")
    r = a.shell(f"monkey -p {pacote} -c android.intent.category.LAUNCHER 1")
    res: dict = {"abrir": {"ok": r.returncode == 0 and "aborted" not in _texto(r).lower(), "saida": _texto(r)[-300:]}}
    log.info("Instagram aberto; esperando %s s", cfg_d["instagram_espera_s"])
    dormir(float(cfg_d["instagram_espera_s"]))
    res["xml"] = _seguro(_salvar_xml, a, f"{tmp}/rotinas_diag_tela.xml", pasta / "tela_inicial_instagram.xml")
    res["print"] = _seguro(_salvar_print, a, f"{tmp}/rotinas_diag_tela.png", pasta / "tela_inicial_instagram.png")
    return res


def _testar_u2(serial: str, pasta: Path) -> dict:
    def trabalho() -> dict:
        import uiautomator2 as u2

        d = u2.connect(serial)
        info = d.info
        xml = d.dump_hierarchy()
        (pasta / "tela_inicial_u2.xml").write_text(xml, encoding="utf-8")
        try:
            d.stop_uiautomator()  # libera o uiautomator para o "uiautomator dump" do adb puro
        except Exception:  # noqa: BLE001 - opcional
            pass
        return {"ok": True, "info": json.loads(json.dumps(info, default=str)), "xml": "tela_inicial_u2.xml"}

    return _com_limite(trabalho, float(_cfg()["u2_timeout_s"]), "uiautomator2")


def android(adb: str, serial: str, pasta: Path, instagram: bool = True, u2: bool = True) -> dict:
    cfg_d = _cfg()
    pacote = _cfg_bluestacks().get("pacote_instagram") or "com.instagram.android"
    a = _Adb(adb, serial, timeout=cfg_d["adb_timeout_s"])
    res: dict = {"serial": serial}
    res["android_versao"] = _seguro(a.saida, "getprop ro.build.version.release")
    res["modelo"] = _seguro(a.saida, "getprop ro.product.model")
    res["tela"] = _seguro(a.saida, "wm size")
    res["densidade"] = _seguro(a.saida, "wm density")
    res["instagram"] = _seguro(_instagram_versao, a, pacote)
    res["pastas_android"] = {p: _seguro(_listar_pastas_android, a, p) for p in cfg_d["android_pastas_listar"]}
    res["mediastore"] = _seguro(_mediastore, a)
    instalado = isinstance(res["instagram"], dict) and res["instagram"].get("instalado")
    if not instagram:
        res["tela_inicial"] = {"pulado": "opção --sem-instagram"}
    elif not instalado:
        res["tela_inicial"] = {"pulado": "Instagram não encontrado no BlueStacks"}
    else:
        log.info("Abrindo o Instagram para salvar a tela inicial")
        res["tela_inicial"] = _seguro(_tela_inicial, a, pacote, pasta)
    if u2:
        log.info("Testando o uiautomator2")
        res["uiautomator2"] = _seguro(_testar_u2, serial, pasta)
    else:
        res["uiautomator2"] = {"pulado": "opção --sem-u2"}
    return res


# ---------------------------------------------------------------- CapCut (só leitura)

def _listar_projetos(rascunhos: Path) -> list[str]:
    return sorted(p.name for p in rascunhos.iterdir() if p.is_dir() and not p.name.startswith("."))


def _copiar_raiz(rascunhos: Path, destino: Path, limite: int) -> dict:
    copiados, omitidos, erros = [], [], []
    for arq in sorted(rascunhos.iterdir()):
        if not arq.is_file():
            continue
        try:
            tamanho = arq.stat().st_size
            if tamanho > limite:
                omitidos.append({"arquivo": arq.name, "tamanho_mb": _mb(tamanho)})
                continue
            destino.mkdir(parents=True, exist_ok=True)
            shutil.copy2(arq, destino / arq.name)
            copiados.append(arq.name)
        except OSError as e:
            erros.append({"arquivo": arq.name, "erro": str(e)})
    return {"destino": destino.name, "copiados": copiados, "omitidos": omitidos, "erros": erros}


def _achar_projeto(rascunhos: Path, projeto: str) -> Path | None:
    direto = rascunhos / projeto
    if direto.is_dir():
        return direto
    for pasta in sorted(p for p in rascunhos.iterdir() if p.is_dir()):
        meta = pasta / "draft_meta_info.json"
        try:
            if meta.is_file() and json.loads(meta.read_text(encoding="utf-8-sig")).get("draft_name") == projeto:
                return pasta
        except (OSError, ValueError, AttributeError):
            continue
    return None


def copiar_projeto(origem: Path, destino: Path, limite: int, arvore: Path) -> dict:
    """Copia o projeto preservando a estrutura (só arquivos até ``limite`` bytes) e grava a árvore."""
    copiados, total, tamanho_total = 0, 0, 0
    omitidos: list[dict] = []
    erros: list[dict] = []
    linhas = [f"Projeto: {origem.name}  ({origem})", ""]
    for pasta_atual, subpastas, arquivos in os.walk(origem):
        subpastas.sort()
        atual = Path(pasta_atual)
        rel_pasta = atual.relative_to(origem).as_posix()
        if rel_pasta != ".":
            linhas.append(f"{rel_pasta}/")
        for nome in sorted(arquivos):
            arq = atual / nome
            rel = arq.relative_to(origem).as_posix()
            try:
                tamanho = arq.stat().st_size
            except OSError as e:
                erros.append({"arquivo": rel, "erro": str(e)})
                continue
            total += 1
            tamanho_total += tamanho
            marca = ""
            if tamanho > limite:
                omitidos.append({"arquivo": rel, "tamanho_mb": _mb(tamanho)})
                marca = "  [não copiado: grande]"
            else:
                alvo = destino / Path(rel)
                alvo.parent.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.copy2(arq, alvo)
                    copiados += 1
                except OSError as e:
                    erros.append({"arquivo": rel, "erro": str(e)})
                    marca = "  [erro ao copiar]"
            linhas.append(f"{rel}  {_legivel(tamanho)}{marca}")
    linhas += ["", f"Total: {total} arquivos, {_legivel(tamanho_total)}"]
    arvore.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    return {
        "origem": str(origem),
        "destino": destino.name,
        "arquivos": total,
        "copiados": copiados,
        "tamanho_total_mb": _mb(tamanho_total),
        "omitidos": omitidos,
        "erros": erros,
        "arvore": arvore.name,
    }


def formato_rascunho(caminho: Path) -> dict:
    """Diz se o arquivo do rascunho é JSON aberto ou parece criptografado (só lê)."""
    tamanho = caminho.stat().st_size
    with open(caminho, "rb") as f:
        inicio = f.read(4096)
    limpo = inicio.lstrip(b"\xef\xbb\xbf").lstrip()
    base = {"tamanho_kb": round(tamanho / 1024, 1)}
    if not limpo:
        return {"formato": "vazio", **base}
    if not limpo.startswith(b"{"):
        return {"formato": "parece_criptografado", "inicio_hex": limpo[:16].hex(), **base}
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8-sig"))
    except ValueError as e:
        return {"formato": "json_invalido", "erro": str(e)[:200], **base}
    info = {"formato": "json_aberto", **base}
    if isinstance(dados, dict):
        info["chaves"] = list(dados)[:80]
        for chave in ("version", "new_version", "duration", "fps", "draft_name", "tm_duration", "canvas_config"):
            if chave in dados and not isinstance(dados[chave], list):
                info[chave] = dados[chave]
        for chave in ("platform", "last_modified_platform"):
            plataforma = dados.get(chave)
            if isinstance(plataforma, dict):
                info[chave] = {k: plataforma.get(k) for k in ("app_source", "app_version", "os", "os_version") if k in plataforma}
    return info


def _dentro(filho: Path, pai: Path) -> bool:
    try:
        Path(filho).resolve().relative_to(Path(pai).resolve())
        return True
    except ValueError:
        return False


def capcut(pasta_saida: Path, projeto: str | None = None) -> dict:
    cfg_d = _cfg()
    rascunhos = config.pastas().capcut_rascunhos
    projeto = projeto or cfg_d["capcut_projeto_gabarito"]
    limite = int(float(cfg_d["capcut_max_mb_por_arquivo"]) * 1024 * 1024)
    res: dict = {"pasta_rascunhos": str(rascunhos), "existe": rascunhos.is_dir(), "gabarito": projeto}
    if not res["existe"]:
        res["mensagem"] = "Pasta de rascunhos do CapCut não encontrada (confira config/pastas.json)."
        return res
    if _dentro(pasta_saida, rascunhos):
        raise ValueError("A pasta de saída não pode ficar dentro da pasta do CapCut.")
    res["projetos"] = _seguro(_listar_projetos, rascunhos)
    res["raiz"] = _seguro(_copiar_raiz, rascunhos, pasta_saida / "capcut_raiz", limite)
    origem = _achar_projeto(rascunhos, projeto)
    res["gabarito_encontrado"] = origem is not None
    if origem is None:
        res["mensagem"] = f"Não achei o projeto '{projeto}' nos rascunhos do CapCut."
        return res
    nome_destino = "capcut_" + re.sub(r"[^\w.\-]+", "_", projeto)
    res["copia"] = _seguro(copiar_projeto, origem, pasta_saida / nome_destino, limite, pasta_saida / "arvore_capcut.txt")
    formatos = {}
    for nome in cfg_d["capcut_arquivos_principais"]:
        arq = origem / nome
        formatos[nome] = _seguro(formato_rascunho, arq) if arq.is_file() else {"formato": "ausente"}
    res["formato"] = formatos
    return res


# ---------------------------------------------------------------- Supabase (só leitura)

def _http_get(url: str, **kwargs):
    import requests

    return requests.get(url, **kwargs)


def supabase() -> dict:
    """Leitura de teste: só o status HTTP. Seleciona só ``id`` (nunca ``cost_price``)."""
    url, chave = config.segredo("SUPABASE_URL"), config.segredo("SUPABASE_KEY")
    if not url or not chave:
        return {"configurado": False, "ok": False, "mensagem": "SUPABASE_URL ou SUPABASE_KEY vazio no .env."}
    r = _http_get(
        url.rstrip("/") + "/rest/v1/products",
        params={"select": "id", "limit": "1"},
        headers={"apikey": chave, "Authorization": f"Bearer {chave}"},
        timeout=float(_cfg()["supabase_timeout_s"]),
    )
    status = int(r.status_code)
    if 200 <= status < 300:
        mensagem = "Leitura do banco ok."
    elif status in (401, 403):
        mensagem = "O Supabase recusou a chave: confira SUPABASE_KEY no .env."
    elif status == 404:
        mensagem = "Endereço não encontrado: confira SUPABASE_URL no .env."
    else:
        mensagem = f"O Supabase respondeu {status}."
    return {"configurado": True, "status_http": status, "ok": 200 <= status < 300, "mensagem": mensagem}


# ---------------------------------------------------------------- execução e resumo

def executar(
    pasta_saida: Path,
    instagram: bool = True,
    u2: bool = True,
    supabase_: bool = True,
    verificar: bool = True,
    projeto: str | None = None,
) -> dict:
    """Roda o diagnóstico inteiro e grava ``diagnostico.json`` + ``resumo.txt`` em ``pasta_saida``."""
    pasta = Path(pasta_saida)
    try:
        rascunhos = config.pastas().capcut_rascunhos
    except config.ErroConfig:
        rascunhos = None
    if rascunhos is not None and _dentro(pasta, rascunhos):
        raise ValueError("A pasta de saída do diagnóstico não pode ficar dentro da pasta do CapCut.")
    pasta.mkdir(parents=True, exist_ok=True)
    inicio = time.time()
    log.info("Diagnóstico: gravando em %s", pasta)
    dados: dict = {"rotinas": __version__, "gerado_em": datetime.now().astimezone().isoformat(timespec="seconds")}
    log.info("Coletando versões")
    dados["versoes"] = _seguro(versoes)
    if verificar:
        log.info("Rodando o verificar da instalação")
        dados["verificar"] = _seguro(verificar_instalacao)
    dados["pastas"] = _seguro(pastas)
    dados["env"] = _seguro(env)
    log.info("Conferindo o BlueStacks e o ADB")
    dados["bluestacks"] = _seguro(bluestacks)
    b = dados["bluestacks"]
    serial = b.get("serial") if isinstance(b, dict) else None
    if serial:
        dados["android"] = _seguro(android, b["adb"], serial, pasta, instagram, u2)
    else:
        dados["android"] = {"pulado": "nenhum dispositivo ADB conectado"}
    log.info("Copiando o gabarito do CapCut (só leitura)")
    dados["capcut"] = _seguro(capcut, pasta, projeto)
    if supabase_:
        log.info("Testando a leitura do Supabase")
        dados["supabase"] = _seguro(supabase)
    else:
        dados["supabase"] = {"pulado": "opção --sem-supabase"}
    dados["problemas"] = _seguro(problemas, dados)
    dados["duracao_s"] = round(time.time() - inicio, 1)
    dados = _ocultar_dados(dados)
    gravar_json(pasta / "diagnostico.json", dados)
    (pasta / "resumo.txt").write_text(registro.ocultar(resumo(dados)) + "\n", encoding="utf-8")
    log.info("Diagnóstico pronto em %.1f s", dados["duracao_s"])
    return dados


def _g(d, *chaves, padrao=None):
    for c in chaves:
        if not isinstance(d, dict):
            return padrao
        d = d.get(c)
    return padrao if d is None else d


def problemas(dados: dict) -> list[str]:
    """Lista curta do que precisa de atenção, em português."""
    lista: list[str] = []
    for nome in ("versoes", "verificar", "pastas", "env", "bluestacks", "android", "capcut", "supabase"):
        if _tem_erro(dados.get(nome)):
            lista.append(f"O item '{nome}' deu erro: {dados[nome]['erro']}")
    v = dados.get("versoes") or {}
    pac = v.get("pacotes")
    if isinstance(pac, dict) and not _tem_erro(pac):
        faltando = [k for k, val in pac.items() if not val]
        if faltando:
            lista.append(f"Pacotes Python faltando: {', '.join(faltando)} (rode o instalar.bat).")
    for prog in ("ffmpeg", "ffprobe", "git", "adb"):
        if isinstance(v.get(prog), dict) and v[prog].get("encontrado") is False:
            lista.append(f"Não encontrei o programa {prog} (rode o instalar.bat).")
    itens_verificar = _g(dados, "verificar", "resultado", "itens")
    if isinstance(itens_verificar, list):
        falhas = [str(i.get("nome") or i.get("chave")) for i in itens_verificar if isinstance(i, dict) and i.get("estado") == "falha"]
        if falhas:
            lista.append(f"O verificar da instalação marcou com falha: {', '.join(falhas)}.")
    e = dados.get("env") or {}
    if isinstance(e, dict) and not _tem_erro(e):
        if not e.get("existe"):
            lista.append("O arquivo .env não existe (o instalar.bat cria a partir do .env.example).")
        vazias = [n for n, s in (e.get("variaveis") or {}).items() if s != "preenchida"]
        if vazias and e.get("existe"):
            lista.append(f"No .env, sem valor: {', '.join(vazias)}.")
    p = dados.get("pastas") or {}
    if isinstance(p, dict) and not _tem_erro(p):
        for nome in ("stories_fonte", "rotinas"):  # capcut_rascunhos: avisado no item capcut
            if isinstance(p.get(nome), dict) and not p[nome].get("existe"):
                lista.append(f"Pasta não encontrada ({nome}): {p[nome].get('caminho')}")
    b = dados.get("bluestacks") or {}
    if isinstance(b, dict) and not _tem_erro(b) and b.get("adb") and not b.get("serial") and b.get("mensagem"):
        lista.append(b["mensagem"])
    a = dados.get("android") or {}
    if isinstance(a, dict) and a.get("serial"):
        if _g(a, "instagram", "instalado") is False:
            lista.append("O Instagram não foi encontrado no BlueStacks.")
        tela = a.get("tela_inicial") or {}
        if isinstance(tela, dict) and "pulado" not in tela:
            if _tem_erro(tela) or _tem_erro(tela.get("xml")):
                lista.append("Não consegui salvar o XML da tela do Instagram.")
            if _tem_erro(tela) or _tem_erro(tela.get("print")):
                lista.append("Não consegui salvar o print da tela do Instagram.")
        u = a.get("uiautomator2") or {}
        if _tem_erro(u):
            lista.append(f"uiautomator2 falhou: {u['erro']}")
        ms = a.get("mediastore") or {}
        if _tem_erro(ms) or (isinstance(ms, dict) and ms.get("responde") is False):
            lista.append("A galeria do Android (MediaStore) não respondeu à consulta.")
    c = dados.get("capcut") or {}
    if isinstance(c, dict) and not _tem_erro(c):
        if c.get("mensagem"):
            lista.append(c["mensagem"])
        for nome, f in (c.get("formato") or {}).items():
            textos = {"parece_criptografado": "parece criptografado", "json_invalido": "não é um JSON válido"}
            if isinstance(f, dict) and f.get("formato") in textos:
                lista.append(f"O {nome} do gabarito do CapCut {textos[f['formato']]}.")
        copia = c.get("copia") or {}
        if isinstance(copia, dict) and copia.get("erros"):
            lista.append(f"{len(copia['erros'])} arquivo(s) do gabarito do CapCut não puderam ser copiados (CapCut aberto?).")
    s = dados.get("supabase") or {}
    if isinstance(s, dict) and not _tem_erro(s) and s.get("ok") is False:
        lista.append(f"Supabase: {s.get('mensagem')}")
    return lista


def _v(valor, padrao: str = "?") -> str:
    if _tem_erro(valor):
        return f"ERRO ({valor['erro']})"
    return padrao if valor in (None, "") else str(valor)


def resumo(dados: dict) -> str:
    v = dados.get("versoes") or {}
    L = [f"Diagnóstico do PC — Rotinas Ferreira {dados.get('rotinas', '')} ({dados.get('gerado_em', '')})", ""]
    L.append(f"Windows: {_v(_g(v, 'sistema', 'plataforma'))}")
    L.append(f"Python: {_v(_g(v, 'python', 'versao'))}")
    rep = v.get("repositorio") or {}
    L.append(f"Repositório: ramo {_v(rep.get('ramo'))}, commit {_v((rep.get('commit') or '')[:10])}")
    pac = v.get("pacotes")
    if isinstance(pac, dict) and not _tem_erro(pac):
        faltando = [k for k, val in pac.items() if not val]
        L.append("Pacotes Python: " + ("todos instalados" if not faltando else "FALTANDO " + ", ".join(faltando)))
    for prog in ("ffmpeg", "ffprobe", "git", "adb"):
        item = v.get(prog) or {}
        L.append(f"{prog}: {_v(item.get('versao')) if item.get('encontrado') else ('NÃO ENCONTRADO' if not _tem_erro(item) else _v(item))}")
    L.append(f"BlueStacks: {_v(_g(v, 'bluestacks', 'registro', 'Version'), 'versão não encontrada no registro')}")
    capv = v.get("capcut") or {}
    L.append(f"CapCut instalado: {_v(capv.get('mais_recente'), 'não encontrado')}")
    L.append("")
    b = dados.get("bluestacks") or {}
    L.append(f"ADB do BlueStacks: {_v(b.get('mensagem') if not _tem_erro(b) else b)}")
    a = dados.get("android") or {}
    if isinstance(a, dict) and a.get("serial"):
        L.append(f"Android {_v(a.get('android_versao'))}, modelo {_v(a.get('modelo'))}, {_v(a.get('tela'))}, {_v(a.get('densidade'))}")
        ig = a.get("instagram") or {}
        L.append(f"Instagram: {_v(ig.get('versao'), 'não instalado') if not _tem_erro(ig) else _v(ig)}")
        tela = a.get("tela_inicial") or {}
        if isinstance(tela, dict) and "pulado" in tela:
            L.append(f"Tela inicial: não capturada ({tela['pulado']})")
        else:
            xml_ok = isinstance(tela.get("xml"), dict) and not _tem_erro(tela.get("xml"))
            png_ok = isinstance(tela.get("print"), dict) and not _tem_erro(tela.get("print"))
            L.append(f"Tela inicial do Instagram: XML {'salvo' if xml_ok else 'FALHOU'}, print {'salvo' if png_ok else 'FALHOU'}")
        u = a.get("uiautomator2") or {}
        L.append("uiautomator2: " + ("ok" if u.get("ok") else (u.get("pulado") or _v(u))))
        ms = a.get("mediastore") or {}
        L.append("Galeria (MediaStore): " + (f"responde ({ms.get('itens')} itens)" if ms.get("responde") else "NÃO respondeu"))
    else:
        L.append(f"Android/Instagram: {_v(a.get('pulado') if not _tem_erro(a) else a)}")
    c = dados.get("capcut") or {}
    if _tem_erro(c):
        L.append(f"CapCut: {_v(c)}")
    elif not c.get("existe"):
        L.append(f"CapCut: {c.get('mensagem')}")
    else:
        projetos = c.get("projetos")
        L.append(f"Rascunhos do CapCut: {len(projetos) if isinstance(projetos, list) else _v(projetos)} projeto(s)")
        if c.get("gabarito_encontrado"):
            copia = c.get("copia") or {}
            if _tem_erro(copia):
                L.append(f"Gabarito '{c.get('gabarito')}': {_v(copia)}")
            else:
                L.append(f"Gabarito '{c.get('gabarito')}': {copia.get('copiados')} de {copia.get('arquivos')} arquivos copiados"
                         f" ({len(copia.get('omitidos') or [])} grandes ficaram de fora)")
            for nome, f in (c.get("formato") or {}).items():
                L.append(f"  {nome}: {_v(f.get('formato') if not _tem_erro(f) else f)}")
        else:
            L.append(f"Gabarito: {c.get('mensagem')}")
    s = dados.get("supabase") or {}
    L.append("Supabase: " + (s.get("pulado") or s.get("mensagem") or _v(s)))
    probs = dados.get("problemas") or []
    L.append("")
    if isinstance(probs, list) and probs:
        L.append("Precisa de atenção:")
        L += [f"  - {x}" for x in probs]
    elif isinstance(probs, list):
        L.append("Nada precisa de atenção.")
    return "\n".join(L)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m rotinas diagnostico",
        description="Coleta versões, ADB do BlueStacks, tela do Instagram e o rascunho de teste do CapCut. "
                    "Não grava nada na pasta do CapCut e não mostra segredos.",
    )
    p.add_argument("--saida", help="pasta onde gravar (padrão: <Rotinas Ferreira>\\logs\\diagnostico\\<data_hora>)")
    p.add_argument("--projeto", help="projeto do CapCut usado como gabarito (padrão: config/diagnostico.json)")
    p.add_argument("--sem-instagram", action="store_true", help="não abre o Instagram nem salva a tela")
    p.add_argument("--sem-u2", action="store_true", help="não testa o uiautomator2")
    p.add_argument("--sem-supabase", action="store_true", help="não testa a leitura do banco")
    p.add_argument("--sem-verificar", action="store_true", help="não roda o 'verificar' da instalação")
    p.add_argument("--json", action="store_true", help="mostra o JSON completo em vez do resumo")
    return p


def opcoes(a: argparse.Namespace) -> dict:
    return {
        "instagram": not a.sem_instagram,
        "u2": not a.sem_u2,
        "supabase_": not a.sem_supabase,
        "verificar": not a.sem_verificar,
        "projeto": a.projeto,
    }


def cli(argv: list[str]) -> int:
    a = parser().parse_args(argv)
    if a.saida:
        saida = Path(a.saida)
    else:
        try:
            saida = config.pastas().logs / "diagnostico" / carimbo()
        except config.ErroConfig:
            saida = config.RAIZ / "saida_local" / "diagnostico" / carimbo()
    dados = executar(saida, **opcoes(a))
    if a.json:
        print(json.dumps(dados, ensure_ascii=False, indent=2, default=str))
    else:
        print(resumo(dados))
    print(f"\nArquivos em: {saida}")
    return 0


def tarefa(args: dict, ctx: Contexto) -> dict:
    """Pedido da fila tipo ``diagnostico``. Args opcionais: instagram, u2, supabase, verificar (bool), projeto."""
    return executar(
        ctx.pasta_saida,
        instagram=bool(args.get("instagram", True)),
        u2=bool(args.get("u2", True)),
        supabase_=bool(args.get("supabase", True)),
        verificar=bool(args.get("verificar", True)),
        projeto=args.get("projeto"),
    )
