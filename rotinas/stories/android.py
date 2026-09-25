"""BlueStacks pelo ADB: conexão, envio das mídias para a galeria do Android (MediaStore) e a
``Tela`` (uiautomator2) que acha elementos pelos seletores de ``config/bluestacks.json``.

Nada aqui publica nada no Instagram: o fluxo fica em ``bluestacks.py``.

Regras:
- Um adb só por execução (o caminho escolhido vai para ``ADBUTILS_ADB_PATH``, que o uiautomator2 usa).
- Só mexe dentro de ``pasta_android`` (cópias no emulador; nunca mídia do usuário).
- Mídias vão em ordem inversa, com ``mtime`` decrescente e varredura arquivo a arquivo, para a grade
  do Instagram (mais recente primeiro) mostrar a letra na ordem certa.
"""

from __future__ import annotations

import os
import posixpath
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from .. import config, ferramentas, registro

log = registro.obter("stories.android")

dormir = time.sleep  # trocados nos testes
agora = time.monotonic

RAIZES_ARMAZENAMENTO = ("/sdcard", "/storage/emulated/0", "/storage/self/primary", "/mnt/sdcard")
RE_NOME_MIDIA = re.compile(r"^(?P<letra>[A-Z]{1,2}) - (?P<n>\d+)$")
RE_DATA = re.compile(r"^\d{4}-\d{2}-\d{2}$")
RE_LETRA = re.compile(r"^[A-Z]{1,2}$")
# Caminho no Android que vai para o shell (touch, rm, file://): sem espaço, aspas ou acento.
RE_CAMINHO_SEGURO = re.compile(r"^[A-Za-z0-9_./-]+$")

INSTRUCAO_ADB = ("No BlueStacks: Configurações (engrenagem) > Avançado > ligue 'Android Debug Bridge (ADB)' > "
                 "Salvar alterações. Depois tente de novo.")

# Campos aceitos pelo seletor do uiautomator2 (u2.Selector) + os especiais desta rotina.
CAMPOS_U2 = {
    "text", "textContains", "textMatches", "textStartsWith", "className", "classNameMatches",
    "description", "descriptionContains", "descriptionMatches", "descriptionStartsWith", "checkable",
    "checked", "clickable", "longClickable", "scrollable", "enabled", "focusable", "focused", "selected",
    "packageName", "packageNameMatches", "resourceId", "resourceIdMatches", "index", "instance",
}
ESPECIAIS = ("xpath", "coordenada_relativa", "tecla")


class ErroConexao(RuntimeError):
    """Não deu para falar com o BlueStacks (adb ou uiautomator2)."""


class ErroEnvio(RuntimeError):
    """As mídias não chegaram (todas, na ordem) à galeria do Android."""

    def __init__(self, mensagem: str, faltando: list[str] | None = None):
        super().__init__(mensagem)
        self.faltando = faltando or []


class ErroSeletor(RuntimeError):
    """Seletor inválido na config ou elemento não encontrado na tela."""


def _cfg() -> dict:
    return config.carregar("bluestacks")


# ---------------------------------------------------------------- conexão

@dataclass
class Conexao:
    """``adb -s <serial>`` com o mesmo executável a execução inteira."""

    adb: str
    serial: str
    timeout_s: float = 30.0

    def rodar(self, *args: str, timeout: float | None = None, verificar: bool = True):
        return ferramentas.rodar([self.adb, "-s", self.serial, *args], timeout=timeout or self.timeout_s,
                                 verificar=verificar)

    def shell_completo(self, comando: str, timeout: float | None = None, verificar: bool = False):
        return self.rodar("shell", comando, timeout=timeout, verificar=verificar)

    def shell(self, comando: str, timeout: float | None = None, verificar: bool = True) -> str:
        return self.shell_completo(comando, timeout=timeout, verificar=verificar).stdout or ""

    def info(self, pacote: str) -> dict:
        """Serial, Android, tela e versão do Instagram (para o teste real e o log)."""
        def ler(comando: str) -> str | None:
            try:
                return self.shell(comando).strip() or None
            except Exception as e:  # noqa: BLE001 - informação opcional
                log.warning("Não consegui ler '%s': %s", comando, e)
                return None

        pacote_txt = ler(f"dumpsys package {pacote}") or ""
        versao = re.search(r"versionName=(\S+)", pacote_txt)
        return {
            "serial": self.serial,
            "adb": self.adb,
            "android": ler("getprop ro.build.version.release"),
            "sdk": ler("getprop ro.build.version.sdk"),
            "modelo": ler("getprop ro.product.model"),
            "tela": ler("wm size"),
            "densidade": ler("wm density"),
            "instagram": versao.group(1) if versao else None,
        }


def ler_conf_bluestacks(cfg: dict | None = None) -> dict:
    """Portas do ADB e se o ADB está ligado, lidos do ``bluestacks.conf`` (leitor do diagnóstico)."""
    from .. import diagnostico

    cfg = cfg or _cfg()
    caminho = config.expandir(cfg.get("bluestacks_conf") or "bluestacks.conf")
    if not caminho.is_file() and hasattr(diagnostico, "_caminho_conf"):
        try:
            caminho = diagnostico._caminho_conf()  # procura também pelo registro do Windows
        except Exception:  # noqa: BLE001 - segue com o caminho da config
            pass
    if not caminho.is_file():
        return {"caminho": str(caminho), "existe": False, "adb_ligado": None, "portas": []}
    chaves = diagnostico.ler_conf(caminho)
    status, outras = [], []
    for k, v in chaves.items():
        m = re.fullmatch(r"bst\.instance\.[^.]+\.(status\.adb_port|adb_port)", k)
        if m and str(v).strip().isdigit() and int(v) > 0:
            (status if m.group(1) == "status.adb_port" else outras).append(int(v))
    portas = list(dict.fromkeys(status + outras))  # porta em uso primeiro
    flag = chaves.get("bst.enable_adb_access")
    ligado = True if flag == "1" else False if flag == "0" else None
    return {"caminho": str(caminho), "existe": True, "adb_ligado": ligado, "portas": portas}


def enderecos_candidatos(conf: dict, cfg: dict) -> list[str]:
    enderecos = [f"127.0.0.1:{p}" for p in conf.get("portas") or []]
    if cfg.get("dispositivo_padrao"):
        enderecos.append(cfg["dispositivo_padrao"])
    return list(dict.fromkeys(enderecos))


def dispositivos(adb: str, timeout: float = 30) -> list[tuple[str, str]]:
    r = ferramentas.rodar([adb, "devices"], timeout=timeout, verificar=False)
    itens = []
    for linha in (r.stdout or "").splitlines():
        partes = linha.strip().split()
        if len(partes) >= 2 and not linha.startswith(("List of", "*")):
            itens.append((partes[0], partes[1]))
    return itens


def _eh_emulador(serial: str) -> bool:
    return serial.startswith(("emulator-", "127.0.0.1:", "localhost:"))


def escolher_serial(lista: list[tuple[str, str]], conectados: list[str], padrao: str | None) -> str | None:
    """Prefere o endereço que acabou de conectar; nunca escolhe celular ligado por USB."""
    prontos = [s for s, estado in lista if estado == "device"]
    for s in conectados + ([padrao] if padrao else []):
        if s in prontos:
            return s
    emuladores = [s for s in prontos if _eh_emulador(s)]
    return emuladores[0] if emuladores else None


def _mensagem_sem_conexao(conf: dict, lista: list[tuple[str, str]], enderecos: list[str]) -> str:
    if conf.get("adb_ligado") is False:
        return "O ADB do BlueStacks está DESLIGADO. " + INSTRUCAO_ADB
    nao_prontos = [f"{s} ({estado})" for s, estado in lista if estado != "device" and _eh_emulador(s)]
    if nao_prontos:
        return (f"O BlueStacks apareceu no ADB, mas não está pronto: {', '.join(nao_prontos)}. "
                "Feche e abra o BlueStacks e tente de novo.")
    return (f"Não consegui conectar ao BlueStacks pelo ADB (tentei: {', '.join(enderecos) or 'nenhum endereço'}). "
            "Confira se o BlueStacks está aberto na tela inicial do Android. Se estiver: " + INSTRUCAO_ADB)


def conectar(cfg: dict | None = None) -> Conexao:
    """Acha o adb, conecta nas portas do ``bluestacks.conf`` (ou no ``dispositivo_padrao``) e escolhe o serial."""
    cfg = cfg or _cfg()
    adb = ferramentas.localizar("adb", cfg.get("adb_candidatos"))
    if not adb:
        raise ErroConexao("Não encontrei o adb (nem o HD-Adb.exe do BlueStacks). Rode o instalar.bat de novo.")
    os.environ["ADBUTILS_ADB_PATH"] = adb  # o uiautomator2 usa o mesmo adb (servidor não reinicia)
    log.info("adb usado nesta execução: %s", adb)
    timeout = float(cfg.get("adb_timeout_s", 30))
    ferramentas.rodar([adb, "start-server"], timeout=timeout, verificar=False)
    conf = ler_conf_bluestacks(cfg)
    if conf.get("adb_ligado") is False:
        log.warning("bluestacks.conf diz que o ADB está desligado (bst.enable_adb_access=0)")
    enderecos = enderecos_candidatos(conf, cfg)
    conectados = []
    for endereco in enderecos:
        r = ferramentas.rodar([adb, "connect", endereco], timeout=timeout, verificar=False)
        texto = ((r.stdout or "") + (r.stderr or "")).lower()
        if "connected to" in texto and not any(x in texto for x in ("cannot", "failed", "unable")):
            conectados.append(endereco)
    lista = dispositivos(adb, timeout)
    serial = escolher_serial(lista, conectados, cfg.get("dispositivo_padrao"))
    if not serial:
        raise ErroConexao(_mensagem_sem_conexao(conf, lista, enderecos))
    log.info("Conectado ao BlueStacks em %s", serial)
    return Conexao(adb, serial, timeout)


# ---------------------------------------------------------------- pastas no Android

def _relativo(caminho: str) -> str:
    """Caminho sem a raiz do armazenamento (``/sdcard/Pictures/X`` → ``/Pictures/X``)."""
    for raiz in RAIZES_ARMAZENAMENTO:
        if caminho == raiz or caminho.startswith(raiz + "/"):
            return caminho[len(raiz):]
    return caminho


def _validar_base(base: str) -> str:
    norm = posixpath.normpath(base)
    rel = _relativo(norm)
    partes = [p for p in rel.split("/") if p]
    if rel == norm or ".." in base.split("/") or len(partes) < 2 or not RE_CAMINHO_SEGURO.match(base):
        raise ErroEnvio(
            f"pasta_android inválida em config/bluestacks.json: {base!r}. Use uma subpasta própria dentro do "
            "armazenamento do Android, só com letras sem acento, números, '_', '-' e '/' (sem espaço), "
            "por exemplo /sdcard/Pictures/RotinasFerreira."
        )
    return norm


def pasta_remota(data: str, letra: str, cfg: dict | None = None) -> str:
    cfg = cfg or _cfg()
    if not RE_DATA.match(str(data)) or not RE_LETRA.match(str(letra)):
        raise ErroEnvio(f"Data ou letra inválida para a pasta do emulador: {data!r}, {letra!r}")
    return f"{_validar_base(cfg['pasta_android'])}/{data}_{letra}"


def _dentro(caminho: str, base: str) -> bool:
    norm = posixpath.normpath(caminho)
    return norm.startswith(posixpath.normpath(base) + "/") and ".." not in caminho.split("/")


def nome_remoto(data: str, letra: str, midia: dict, indice: int, sufixo: str = "") -> str:
    """``<data>_<letra>_<n>.<ext>`` (é cópia no emulador; o nome original não importa lá)."""
    m = RE_NOME_MIDIA.match(str(midia.get("nome") or ""))
    n = m.group("n") if m else str(indice)
    ext = Path(str(midia.get("arquivo") or midia.get("caminho") or "")).suffix.lower()
    return f"{data}_{letra}_{n}{sufixo}{ext}"


# ---------------------------------------------------------------- MediaStore

def _linhas_mediastore(saida: str) -> list[dict]:
    linhas = []
    for linha in saida.splitlines():
        m = re.match(r"^Row:\s*\d+\s+(.*)$", linha.strip())
        if not m:
            continue
        campos: dict = {}
        for parte in re.split(r", (?=[A-Za-z_]+=)", m.group(1)):
            chave, _, valor = parte.partition("=")
            campos[chave.strip()] = None if valor == "NULL" else valor
        linhas.append(campos)
    return linhas


def consultar_mediastore(con: Conexao, padrao_like: str, cfg: dict | None = None) -> list[dict]:
    """Linhas do MediaStore com ``_data LIKE padrao_like``. Tenta com as colunas extras e, se falhar, sem."""
    cfg = cfg or _cfg()
    uri = cfg.get("mediastore_uri", "content://media/external/file")
    base = list(cfg.get("mediastore_projecao") or ["_id", "_data", "date_added", "date_modified"])
    extra = list(cfg.get("mediastore_projecao_extra") or [])
    ultimo = ""
    for projecao in ([base + extra, base] if extra else [base]):
        comando = (f"content query --uri {uri} --projection {':'.join(projecao)} "
                   f"--where \"_data LIKE '{padrao_like}'\"")
        r = con.shell_completo(comando, timeout=float(cfg.get("adb_timeout_s", 30)))
        saida = r.stdout or ""
        if "Row:" in saida or "No result found" in saida:
            return _linhas_mediastore(saida)
        ultimo = (saida + (r.stderr or "")).strip()[-300:]
    raise ErroEnvio(f"A galeria do Android (MediaStore) não respondeu à consulta: {ultimo or 'sem resposta'}")


def _padrao_pasta(remoto: str) -> str:
    return f"%{_relativo(remoto)}/%"


def _esperar_arquivo(con: Conexao, remoto: str, espera_s: float, cfg: dict) -> bool:
    limite = agora() + espera_s
    padrao = f"%{_relativo(remoto)}"
    while True:
        if consultar_mediastore(con, padrao, cfg):
            return True
        if agora() >= limite:
            return False
        dormir(float(cfg.get("conferencia_intervalo_s", 0.5)))


def varrer_arquivo(con: Conexao, remoto: str, cfg: dict, preferido: str | None = None) -> str | None:
    """Pede ao Android para pôr o arquivo na galeria. Devolve o nome do método que funcionou (ou ``None``)."""
    metodos = list(cfg.get("varredura_metodos") or [])
    metodos.sort(key=lambda m: 0 if m.get("nome") == preferido else 1)
    for metodo in metodos:
        comando = str(metodo["comando"]).replace("{caminho}", remoto)
        con.shell_completo(comando)
        if _esperar_arquivo(con, remoto, float(cfg.get("varredura_espera_s", 5)), cfg):
            if metodo.get("nome") != preferido:
                log.info("Varredura da galeria que funcionou: %s", metodo.get("nome"))
            return metodo.get("nome")
        log.info("A varredura '%s' não pôs %s na galeria; tentando a próxima", metodo.get("nome"), posixpath.basename(remoto))
    return None


def _hora_android(con: Conexao) -> datetime:
    try:
        texto = con.shell("date +%Y%m%d%H%M%S").strip()
        return datetime.strptime(texto[-14:], "%Y%m%d%H%M%S")
    except Exception as e:  # noqa: BLE001 - relógio do PC serve
        log.warning("Não consegui ler a hora do Android (%s); usando a do PC", e)
        return datetime.now().replace(microsecond=0)


def _preparar_pasta(con: Conexao, remoto: str, cfg: dict, avisos: list[str]) -> str:
    """Limpa a pasta da letra no emulador (só ela) e devolve um sufixo de nome se sobrou registro antigo."""
    base = _validar_base(cfg["pasta_android"])
    if not _dentro(remoto, base):
        raise ErroEnvio(f"Recusei mexer fora de {base}: {remoto}")
    uri = cfg.get("mediastore_uri", "content://media/external/file")
    con.shell_completo(f"content delete --uri {uri} --where \"_data LIKE '{_padrao_pasta(remoto)}'\"")
    con.shell_completo(f"rm -rf '{remoto}'")
    r = con.shell_completo(f"mkdir -p '{remoto}'")
    if r.returncode not in (0, None):
        raise ErroEnvio(f"Não consegui criar a pasta {remoto} no emulador: {(r.stderr or r.stdout or '').strip()[-200:]}")
    restos = consultar_mediastore(con, _padrao_pasta(remoto), cfg)
    if restos:
        avisos.append(f"A galeria ainda listava {len(restos)} arquivo(s) antigo(s) de {remoto}; enviei com nomes novos.")
        log.warning(avisos[-1])
        return "_" + datetime.now().strftime("%H%M%S")
    return ""


def _numero(valor) -> float | None:
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def conferir_ordem(itens: list[dict], por_nome: dict[str, dict], cfg: dict, avisos: list[str]) -> dict[str, bool | None]:
    """A 1ª mídia tem que ser a mais recente e assim por diante (a grade do Instagram mostra o mais novo primeiro).

    Devolve, para cada coluna de ``ordem_avisar``, se a ordem confere (``None`` = a galeria não informou)."""
    def decrescente(coluna: str) -> bool | None:
        valores = [_numero(por_nome[posixpath.basename(it["remoto"])].get(coluna)) for it in itens]
        if any(v is None for v in valores):
            return None
        return all(valores[k] > valores[k + 1] for k in range(len(valores) - 1))

    for coluna in cfg.get("ordem_exigir") or []:
        ok = decrescente(coluna)
        if ok is None:
            avisos.append(f"A galeria não informou {coluna}; não deu para conferir a ordem por essa coluna.")
        elif not ok:
            raise ErroEnvio(f"A ordem das mídias na galeria do BlueStacks não confere ({coluna}). "
                            "Nada foi aberto no Instagram; tente de novo.")
    avisar: dict[str, bool | None] = {}
    for coluna in cfg.get("ordem_avisar") or []:
        avisar[coluna] = decrescente(coluna)
        if avisar[coluna] is False:
            avisos.append(f"A ordem por {coluna} (data da foto/vídeo) é diferente da ordem da letra. Se a galeria "
                          "do Instagram ordenar por essa data, as mídias podem sair fora de ordem: conferir os prints.")
    return avisar


def conferir_galeria(con: Conexao, remoto: str, itens: list[dict], cfg: dict) -> dict[str, dict]:
    """Espera todas as mídias aparecerem no MediaStore. Faltou alguma → ``ErroEnvio`` dizendo quais."""
    limite = agora() + float(cfg.get("conferencia_galeria_s", 30))
    while True:
        por_nome = {posixpath.basename(l.get("_data") or ""): l for l in consultar_mediastore(con, _padrao_pasta(remoto), cfg)}
        faltando = [it for it in itens if posixpath.basename(it["remoto"]) not in por_nome]
        if not faltando:
            return por_nome
        if agora() >= limite:
            nomes = [it["nome"] for it in faltando]
            raise ErroEnvio(
                f"Faltaram {len(faltando)} de {len(itens)} mídia(s) na galeria do BlueStacks: {', '.join(nomes)}. "
                "Não abri o Instagram.",
                faltando=nomes,
            )
        dormir(float(cfg.get("conferencia_intervalo_s", 0.5)))


def enviar_letra(con: Conexao, data: str, letra: str, midias: list[dict], cfg: dict | None = None) -> dict:
    """Manda as mídias da letra para ``<pasta_android>/<data>_<letra>/`` (vira o álbum da galeria).

    Ordem inversa (última mídia primeiro), ``mtime`` da 1ª = agora e das seguintes 1 min mais velhas,
    varredura arquivo a arquivo com ~1,1 s entre eles, conferência no MediaStore (todas + ordem).
    """
    cfg = cfg or _cfg()
    remoto = pasta_remota(data, letra, cfg)
    aceitas = {e.lower() for e in cfg.get("extensoes_galeria") or []}
    for m in midias:
        local = Path(str(m.get("caminho") or ""))
        if not local.is_file():
            raise ErroEnvio(f"Arquivo não encontrado no PC: {local}")
        if aceitas and local.suffix.lower() not in aceitas:
            raise ErroEnvio(f"{m.get('nome')}: formato {local.suffix} não aparece na galeria do emulador "
                            "(converter antes com stories-preparar).")
    log.info("Enviando %d mídia(s) da letra %s para a galeria do BlueStacks (%s)", len(midias), letra, remoto)
    avisos: list[str] = []
    sufixo = _preparar_pasta(con, remoto, cfg, avisos)
    base = _hora_android(con)
    passo = timedelta(minutes=float(cfg.get("mtime_passo_min", 1)))
    itens = []
    for i, m in enumerate(midias, 1):
        itens.append({
            "nome": m.get("nome"),
            "local": str(m["caminho"]),
            "remoto": f"{remoto}/{nome_remoto(data, letra, m, i, sufixo)}",
            "mtime": (base - passo * (i - 1)).strftime("%Y%m%d%H%M.%S"),
            "posicao": i,
        })
    preferido = None
    for it in reversed(itens):
        try:
            con.rodar("push", it["local"], it["remoto"], timeout=float(cfg.get("push_timeout_s", 300)))
        except (ferramentas.ErroComando, ferramentas.FerramentaAusente) as e:
            raise ErroEnvio(f"Não consegui copiar {it['nome']} para o emulador: {e}") from e
        con.shell_completo(f"touch -m -t {it['mtime']} '{it['remoto']}'")
        it["varredura"] = varrer_arquivo(con, it["remoto"], cfg, preferido)
        if it["varredura"]:
            preferido = it["varredura"]
        else:
            log.warning("%s não apareceu na galeria com nenhuma varredura", it["nome"])
        dormir(float(cfg.get("intervalo_envio_s", 1.1)))
    por_nome = conferir_galeria(con, remoto, itens, cfg)
    ordem_avisar = conferir_ordem(itens, por_nome, cfg, avisos)
    for aviso in avisos:
        log.warning(aviso)
    log.info("Letra %s na galeria: %d de %d mídia(s), na ordem", letra, len(itens), len(itens))
    return {
        "pasta": remoto,
        "album": f"{data}_{letra}",
        "arquivos": [{k: it.get(k) for k in ("nome", "remoto", "mtime", "varredura")} for it in itens],
        "varredura": sorted({it["varredura"] for it in itens if it.get("varredura")}),
        # False = a data da foto/vídeo não segue a ordem da letra: sem o álbum, "Recentes" pode vir fora de ordem
        "ordem_data_da_midia": ordem_avisar,
        "avisos": avisos,
    }


# ---------------------------------------------------------------- tela (uiautomator2)

@dataclass
class Elemento:
    """Elemento da tela já lido (texto, descrição, limites) e como tocá-lo."""

    texto: str = ""
    descricao: str = ""
    limites: tuple[int, int, int, int] = (0, 0, 0, 0)
    marcado: bool | None = None
    marcavel: bool | None = None
    classe: str = ""
    id_recurso: str = ""
    plano_b: bool = False
    acao: Callable[[], object] | None = field(default=None, repr=False)

    @property
    def centro(self) -> tuple[int, int]:
        l, t, r, b = self.limites
        return (l + r) // 2, (t + b) // 2

    @property
    def altura(self) -> int:
        return self.limites[3] - self.limites[1]

    def tocar(self) -> None:
        if self.acao is None:
            raise ErroSeletor("Elemento sem ação de toque")
        self.acao()


def ordenar_grade(elementos: list) -> list:
    """Linha a linha (de cima para baixo), cada linha da esquerda para a direita."""
    linhas: list[list] = []
    for e in sorted(elementos, key=lambda e: (e.centro[1], e.centro[0])):
        if linhas:
            ref = linhas[-1][0]
            tolerancia = max(8, min(e.altura or 16, ref.altura or 16) / 2)
            if abs(e.centro[1] - ref.centro[1]) <= tolerancia:
                linhas[-1].append(e)
                continue
        linhas.append([e])
    return [e for linha in linhas for e in sorted(linha, key=lambda e: e.centro[0])]


def validar_seletores(seletores: dict) -> list[str]:
    """Problemas de formato na seção ``seletores`` (lista vazia = tudo certo)."""
    problemas = []
    for chave, alternativas in seletores.items():
        if chave.startswith("_"):
            continue
        if not isinstance(alternativas, list):
            problemas.append(f"{chave}: tem que ser uma lista de alternativas")
            continue
        for i, alt in enumerate(alternativas, 1):
            if not isinstance(alt, dict) or not alt:
                problemas.append(f"{chave} #{i}: alternativa vazia ou que não é objeto")
                continue
            especiais = [k for k in alt if k in ESPECIAIS]
            desconhecidos = [k for k in alt if k not in CAMPOS_U2 and k not in ESPECIAIS]
            if desconhecidos:
                problemas.append(f"{chave} #{i}: campo(s) desconhecido(s) {', '.join(desconhecidos)}")
            if especiais and len(alt) > 1:
                problemas.append(f"{chave} #{i}: '{especiais[0]}' tem que vir sozinho na alternativa")
            coord = alt.get("coordenada_relativa")
            if "coordenada_relativa" in alt and not (
                isinstance(coord, list) and len(coord) == 2 and all(isinstance(v, (int, float)) and 0 <= v <= 1 for v in coord)
            ):
                problemas.append(f"{chave} #{i}: coordenada_relativa tem que ser [x, y] entre 0 e 1")
    return problemas


def _preencher(valor, valores: dict):
    if isinstance(valor, str):
        for k, v in valores.items():
            valor = valor.replace("{" + k + "}", str(v))
    return valor


class Tela:
    """Embrulha o device do uiautomator2. Cada chave tem uma lista de alternativas tentadas em ordem;
    ``coordenada_relativa`` só depois de todas as outras, e sempre registrada no log como plano B."""

    def __init__(self, dispositivo, seletores: dict | None = None, cfg: dict | None = None):
        cfg = cfg or _cfg()
        self.d = dispositivo
        self.seletores = seletores if seletores is not None else (cfg.get("seletores") or {})
        problemas = validar_seletores(self.seletores)
        if problemas:
            raise ErroSeletor("Seletores inválidos em config/bluestacks.json: " + "; ".join(problemas))
        self.espera_padrao = float(cfg.get("espera_padrao_s", 10))
        self.intervalo = float(cfg.get("intervalo_busca_s", 0.4))
        self._tamanho: tuple[int, int] | None = None

    # -- alternativas
    def _alternativas(self, chave: str, valores: dict) -> list[dict]:
        if chave not in self.seletores:
            raise ErroSeletor(f"O seletor '{chave}' não existe em config/bluestacks.json (seletores).")
        return [{k: _preencher(v, valores) for k, v in alt.items()} for alt in self.seletores[chave]]

    def _de_info(self, info: dict) -> Elemento:
        b = info.get("visibleBounds") or info.get("bounds") or {}
        limites = (int(b.get("left", 0)), int(b.get("top", 0)), int(b.get("right", 0)), int(b.get("bottom", 0)))
        x, y = (limites[0] + limites[2]) // 2, (limites[1] + limites[3]) // 2
        return Elemento(
            texto=info.get("text") or "",
            descricao=info.get("contentDescription") or "",
            limites=limites,
            marcado=info.get("checked"),
            marcavel=info.get("checkable"),
            classe=info.get("className") or "",
            id_recurso=info.get("resourceName") or "",
            acao=lambda: self.d.click(x, y),
        )

    def _todos(self, alt: dict) -> list[Elemento]:
        try:
            if "xpath" in alt:
                return [self._de_info(el.info) for el in self.d.xpath(alt["xpath"]).all()]
            obj = self.d(**alt)
            if not obj.exists:
                return []
            try:
                infos = obj.info_list()
            except Exception:  # noqa: BLE001 - servidor antigo do uiautomator
                infos = [obj[i].info for i in range(obj.count)]
            return [self._de_info(i) for i in infos]
        except Exception as e:  # noqa: BLE001 - tela mudou no meio da leitura
            log.debug("Leitura falhou para %s: %s", alt, e)
            return []

    def _primeiro(self, alt: dict) -> Elemento | None:
        try:
            if "xpath" in alt:
                els = self.d.xpath(alt["xpath"]).all()
                return self._de_info(els[0].info) if els else None
            obj = self.d(**alt)
            return self._de_info(obj.info) if obj.exists else None
        except Exception as e:  # noqa: BLE001 - sumiu entre o "existe" e a leitura
            log.debug("Leitura falhou para %s: %s", alt, e)
            return None

    def _especial(self, chave: str, alt: dict) -> Elemento:
        if "tecla" in alt:
            tecla = str(alt["tecla"])
            log.info("'%s': tecla %s", chave, tecla)
            return Elemento(texto=f"tecla {tecla}", acao=lambda: self.d.press(tecla))
        fx, fy = alt["coordenada_relativa"]
        w, h = self.tamanho()
        x, y = int(w * fx), int(h * fy)
        log.warning("PLANO B para '%s': nenhum seletor por texto/descrição achou; tocando na coordenada %s (%d, %d)",
                    chave, alt["coordenada_relativa"], x, y)
        return Elemento(texto=f"coordenada {fx},{fy}", limites=(x, y, x, y), plano_b=True,
                        acao=lambda: self.d.click(x, y))

    def _achar_alt(self, chave: str, espera_s: float | None, plano_b: bool, valores: dict):
        alts = self._alternativas(chave, valores)
        normais = [a for a in alts if "coordenada_relativa" not in a and "tecla" not in a]
        especiais = [a for a in alts if a not in normais]
        if normais:
            limite = agora() + (self.espera_padrao if espera_s is None else espera_s)
            while True:
                for alt in normais:
                    el = self._primeiro(alt)
                    if el is not None:
                        return alt, el
                if agora() >= limite:
                    break
                dormir(self.intervalo)
        if plano_b and especiais:
            return especiais[0], self._especial(chave, especiais[0])
        return None, None

    # -- interface usada pelo fluxo (o dublê dos testes tem a mesma)
    def achar(self, chave: str, espera_s: float | None = None, plano_b: bool = True, **valores) -> Elemento | None:
        return self._achar_alt(chave, espera_s, plano_b, valores)[1]

    def existe(self, chave: str, **valores) -> bool:
        return self._achar_alt(chave, 0, False, valores)[1] is not None

    def tocar(self, chave: str, espera_s: float | None = None, **valores) -> Elemento:
        el = self.achar(chave, espera_s, **valores)
        if el is None:
            raise ErroSeletor(f"Não achei '{chave}' na tela")
        el.tocar()
        return el

    def digitar(self, chave: str, texto: str, espera_s: float | None = None, **valores) -> None:
        alt, el = self._achar_alt(chave, espera_s, False, valores)
        if el is None:
            raise ErroSeletor(f"Não achei o campo '{chave}' para digitar")
        if "xpath" in alt:
            el.tocar()
            self.d.clear_text()
            self.d.send_keys(texto)
        else:
            self.d(**alt).set_text(texto)

    def ler_texto(self, chave: str, espera_s: float | None = 0, **valores) -> str | None:
        el = self.achar(chave, espera_s, plano_b=False, **valores)
        return None if el is None else el.texto

    def grade(self, chave: str, filtro: Callable[[Elemento], bool] | None = None, **valores) -> list[Elemento]:
        for alt in self._alternativas(chave, valores):
            if any(k in alt for k in ("coordenada_relativa", "tecla")):
                continue
            els = self._todos(alt)
            if filtro:
                els = [e for e in els if filtro(e)]
            if els:
                return ordenar_grade(els)
        return []

    def xml(self) -> str:
        return self.d.dump_hierarchy()

    def print(self, caminho: Path) -> None:
        self.d.screenshot(str(caminho))

    def voltar(self) -> None:
        self.d.press("back")

    def rolar(self, limites: tuple[int, int, int, int]) -> None:
        """Arrasta o dedo para cima DENTRO de ``limites`` (x0, y0, x1, y1) — ex.: os itens de um menu, para não tocar
        fora dele (tocar fora fecha o menu). A lista rola e mostra o que está abaixo."""
        x0, y0, x1, y1 = limites
        x = (x0 + x1) // 2
        self.d.swipe(x, int(y0 + 0.85 * (y1 - y0)), x, int(y0 + 0.15 * (y1 - y0)), 0.4)

    def tamanho(self) -> tuple[int, int]:
        if self._tamanho is None:
            w, h = self.d.window_size()
            self._tamanho = (int(w), int(h))
        return self._tamanho

    def abrir_app(self, pacote: str, parar: bool = False) -> None:
        self.d.app_start(pacote, stop=parar)


def abrir_tela(con: Conexao, cfg: dict | None = None) -> Tela:
    """Conecta o uiautomator2 no mesmo serial (e no mesmo adb) e devolve a ``Tela``."""
    try:
        import uiautomator2 as u2
    except ImportError as e:
        raise ErroConexao("O pacote Python uiautomator2 não está instalado. Rode o instalar.bat de novo.") from e
    os.environ["ADBUTILS_ADB_PATH"] = con.adb
    try:
        d = u2.connect(con.serial)
    except Exception as e:  # noqa: BLE001 - mensagem clara para o usuário
        raise ErroConexao(f"O uiautomator2 não conectou em {con.serial}: {e}") from e
    return Tela(d, cfg=cfg)
