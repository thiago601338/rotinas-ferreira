"""A2: estoque das peças no sistema da loja (Supabase, só leitura).

Regra fixa 1 (``conhecimento/stories.md``): só entra no story o que tem estoque.
- Mídia com qualquer cor de estoque 0 é cortada.
- Modelo sem nenhuma peça corta a letra inteira.
- Nome de cor que não existe no cadastro NUNCA corta nada: vira ``ErroEstoque`` listando as
  cores válidas, para a IA corrigir a identificação.

Nunca ler nem gravar ``products.cost_price``: as colunas são sempre explícitas (nada de ``*``).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
from dataclasses import dataclass, field

import requests

from .. import config, registro

log = registro.obter("stories.estoque")

COLUNAS_PRODUTO = "id,sku,name,category,status,sale_price"
COLUNAS_VARIACAO = "color,size,stock"
SELECT_EMBUTIDO = f"{COLUNAS_PRODUTO},product_variations({COLUNAS_VARIACAO})"
SELECT_VARIACOES = f"product_id,{COLUNAS_VARIACAO}"
PROIBIDAS = ("cost_price",)
LOTE_IDS = 100  # ids por consulta no modo de duas etapas (URL não fica gigante)
MAX_CANDIDATOS = 15  # quantos candidatos listar numa mensagem de erro

RE_NOME = re.compile(r"^(?P<letra>[A-Z]{1,2}) - (?P<n>\d+)(?:\.(?P<ext>[A-Za-z0-9]+))?$")

MOTIVO_COR = "cor sem estoque"
MOTIVO_MODELO = "modelo sem nenhuma peça"
MOTIVO_EXCLUIDA = "excluída"


class ErroEstoque(RuntimeError):
    """Problema na consulta de estoque ou na identificação (peça, cor)."""

    def __init__(self, mensagem: str, **extras):
        super().__init__(mensagem)
        for chave, valor in extras.items():
            setattr(self, chave, valor)


class ErroConsulta(ErroEstoque):
    """Resposta de erro do PostgREST (com o código ``PGRSTxxx`` quando vier)."""

    def __init__(self, mensagem: str, status: int, codigo: str | None):
        super().__init__(mensagem)
        self.status = status
        self.codigo = codigo


def _cfg() -> dict:
    try:
        return config.carregar("stories").get("estoque") or {}
    except config.ErroConfig:
        return {}


def _status_ativo() -> str:
    return str(_cfg().get("status_ativo") or "Ativo")


# ---------------------------------------------------------------- texto e números

def normalizar_cor(texto) -> str:
    """Minúsculas, sem acento, espaços simples: ``"  Verde   Água "`` → ``"verde agua"``."""
    if texto is None:
        return ""
    t = unicodedata.normalize("NFKD", str(texto))
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(t.lower().split())


def _palavras(texto) -> list[str]:
    return re.findall(r"[a-z0-9]+", normalizar_cor(texto))


def _int(valor) -> int:
    if valor is None or valor == "":
        return 0
    try:
        return int(float(valor))
    except (TypeError, ValueError):
        return 0


def _float(valor) -> float | None:
    if valor is None or valor == "":
        return None
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def _reais(valor: float | None) -> str:
    if valor is None:
        return "sem preço"
    return "R$ " + f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _chave_texto(valor) -> tuple:
    # igual ao "order by v.color, v.size" do SQL: nulos por último, sem diferenciar maiúsculas
    return (valor is None, normalizar_cor(valor), "" if valor is None else str(valor))


def ordenar_variacoes(variacoes: list[dict]) -> list[dict]:
    return sorted(variacoes, key=lambda v: (_chave_texto(v.get("cor")), _chave_texto(v.get("tamanho"))))


def _chave_tamanho(tamanho: str) -> tuple:
    """Ordem de exibição dos tamanhos (só para a tabela): lista da config, depois números, depois o resto."""
    ordem = [normalizar_cor(t) for t in _cfg().get("ordem_tamanhos") or []]
    n = normalizar_cor(tamanho)
    if n in ordem:
        return (0, ordem.index(n), "")
    try:
        return (1, float(n.replace(",", ".")), "")
    except ValueError:
        return (2, 0, n)


# ---------------------------------------------------------------- produto

def _variacao(v: dict) -> dict:
    cor = v.get("cor", v.get("color"))
    tamanho = v.get("tamanho", v.get("size"))
    return {
        "cor": None if cor is None else str(cor).strip(),
        "tamanho": None if tamanho is None else str(tamanho).strip(),
        "estoque": _int(v.get("estoque", v.get("stock"))),
    }


@dataclass
class Produto:
    """Um modelo do cadastro com as variações (cor, tamanho, estoque) já ordenadas como no SQL."""

    id: object
    sku: str
    nome: str
    categoria: str | None = None
    preco: float | None = None  # sale_price
    variacoes: list[dict] = field(default_factory=list)
    status: str | None = None

    def __post_init__(self) -> None:
        self.sku = str(self.sku or "").strip()
        self.nome = str(self.nome or "").strip()
        self.categoria = None if self.categoria is None else str(self.categoria).strip()
        self.preco = _float(self.preco)
        self.variacoes = ordenar_variacoes([_variacao(v) for v in self.variacoes or []])

    @classmethod
    def de_dict(cls, d: dict) -> "Produto":
        """Aceita o formato do banco (name, category, product_variations…) ou o deste módulo (nome, variacoes…)."""
        return cls(
            id=d.get("id"),
            sku=d.get("sku", ""),
            nome=d.get("nome", d.get("name", "")),
            categoria=d.get("categoria", d.get("category")),
            preco=d.get("preco", d.get("sale_price")),
            variacoes=d.get("variacoes", d.get("product_variations")) or [],
            status=d.get("status"),
        )

    def _agrupar(self) -> tuple[dict[str, str], dict[str, dict[str, int]]]:
        # cores que só diferem em maiúscula/acento/espaço são a mesma cor; a chave é a 1ª grafia do cadastro
        nomes: dict[str, str] = {}
        grade: dict[str, dict[str, int]] = {}
        for v in self.variacoes:
            cor = v["cor"] or ""
            chave = nomes.setdefault(normalizar_cor(cor), cor)
            tamanho = v["tamanho"] or ""
            por_tamanho = grade.setdefault(chave, {})
            por_tamanho[tamanho] = por_tamanho.get(tamanho, 0) + v["estoque"]
        return nomes, grade

    def tamanhos_por_cor(self) -> dict[str, dict[str, int]]:
        return self._agrupar()[1]

    def estoque_por_cor(self) -> dict[str, int]:
        """Soma dos tamanhos de cada cor (estoque negativo conta como 0)."""
        return {cor: sum(max(n, 0) for n in tams.values()) for cor, tams in self.tamanhos_por_cor().items()}

    @property
    def total(self) -> int:
        return sum(self.estoque_por_cor().values())

    def como_dict(self, com_variacoes: bool = True) -> dict:
        d = {
            "sku": self.sku,
            "nome": self.nome,
            "categoria": self.categoria,
            "preco": self.preco,
            "estoque_por_cor": self.estoque_por_cor(),
            "total": self.total,
        }
        if com_variacoes:
            d = {"id": self.id, **d, "variacoes": [dict(v) for v in self.variacoes]}
        return d


# ---------------------------------------------------------------- clientes

class ClienteEstoque:
    """Interface: produtos ativos e não excluídos com ``sku = X`` ou ``name ilike %termo%``."""

    def buscar(self, sku: str | None = None, termo: str | None = None) -> list[Produto]:
        raise NotImplementedError


def _validar_busca(sku: str | None, termo: str | None) -> tuple[str, str]:
    sku = (sku or "").strip()
    termo = (termo or "").strip()
    if not sku and not termo:
        raise ErroEstoque("Informe o SKU ou um termo do nome da peça.")
    return sku, termo


def _citar(valor: str) -> str:
    """Cita um valor dentro de ``or=(...)``/``in.(...)`` do PostgREST quando tem caractere reservado."""
    if any(c in valor for c in ',.:()"\\{}') or valor != valor.strip():
        return '"' + valor.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return valor


def filtros_busca(sku: str | None, termo: str | None) -> list[tuple[str, str]]:
    """Filtro do PostgREST para ``sku = X`` / ``name ilike %termo%``.

    Filtro simples (``name=ilike.*a,b*``) leva o valor literal, sem aspas. Só dentro de ``or=(...)``
    vírgula, ponto, dois-pontos, parênteses e aspas precisam de aspas duplas.
    """
    sku, termo = _validar_busca(sku, termo)
    if sku and termo:
        return [("or", f"(sku.eq.{_citar(sku)},name.ilike.{_citar('*' + termo + '*')})")]
    if sku:
        return [("sku", f"eq.{sku}")]
    return [("name", f"ilike.*{termo}*")]


def _conferir_params(params: list[tuple[str, str]]) -> None:
    """Trava de segurança: nunca pedir ``cost_price`` nem ``select=*``."""
    for chave, valor in params:
        texto = f"{chave}={valor}" if chave in ("select", "order") else chave
        if any(p in texto.lower() for p in PROIBIDAS):
            raise ErroEstoque("Consulta recusada: a coluna cost_price nunca pode ser lida.")
        if chave == "select" and "*" in valor:
            raise ErroEstoque("Consulta recusada: selecione colunas explícitas, nunca '*'.")


class ClienteSupabase(ClienteEstoque):
    """Consulta de leitura pelo PostgREST do Supabase (``SUPABASE_URL``/``SUPABASE_KEY`` do ``.env``)."""

    def __init__(self, url: str | None = None, chave: str | None = None, timeout_s: float | None = None):
        url = url or config.segredo("SUPABASE_URL")
        chave = chave or config.segredo("SUPABASE_KEY")
        faltando = [n for n, v in (("SUPABASE_URL", url), ("SUPABASE_KEY", chave)) if not (v or "").strip()]
        if faltando:
            raise ErroEstoque(
                f"Falta {' e '.join(faltando)} no .env ({config.caminho_env()}). "
                "Abra o .env no Bloco de Notas e preencha (chave só de leitura do Supabase)."
            )
        url = url.strip().rstrip("/")
        if url.endswith("/rest/v1"):
            url = url[: -len("/rest/v1")]
        if not url.startswith(("https://", "http://")):
            raise ErroEstoque("SUPABASE_URL no .env precisa começar com https:// (ex.: https://<projeto>.supabase.co).")
        self._base = url + "/rest/v1"
        self._chave = chave.strip()
        self.timeout_s = float(timeout_s or _cfg().get("timeout_s") or 20)

    def __repr__(self) -> str:  # nunca mostrar a chave
        return "ClienteSupabase()"

    def _cabecalhos(self) -> dict[str, str]:
        return {"apikey": self._chave, "Authorization": f"Bearer {self._chave}", "Accept": "application/json"}

    def _get(self, tabela: str, params: list[tuple[str, str]]) -> list[dict]:
        _conferir_params(params)
        try:
            r = requests.get(f"{self._base}/{tabela}", params=params, headers=self._cabecalhos(), timeout=self.timeout_s)
        except requests.Timeout as e:
            raise ErroEstoque(f"O Supabase não respondeu em {self.timeout_s:g} s. Confira a internet e tente de novo.") from e
        except requests.RequestException as e:
            raise ErroEstoque(f"Sem conexão com o Supabase: {registro.ocultar(str(e))[:300]}") from e
        if not 200 <= r.status_code < 300:  # PGRST201 (relação ambígua) vem com HTTP 300
            corpo = _json_ou_nada(r)
            codigo = corpo.get("code") if isinstance(corpo, dict) else None
            detalhe = corpo.get("message") if isinstance(corpo, dict) else None
            detalhe = registro.ocultar(str(detalhe or r.text or ""))[:300]
            if r.status_code in (401, 403):
                raise ErroConsulta(
                    f"O Supabase recusou o acesso (HTTP {r.status_code}). Confira SUPABASE_KEY no .env "
                    f"(tem que ser a chave de leitura do projeto). Detalhe: {detalhe}",
                    r.status_code, codigo,
                )
            raise ErroConsulta(f"Erro do Supabase (HTTP {r.status_code}, {codigo or 'sem código'}): {detalhe}", r.status_code, codigo)
        dados = _json_ou_nada(r)
        if not isinstance(dados, list):
            raise ErroEstoque("Resposta inesperada do Supabase (esperava uma lista em JSON).")
        return dados

    def buscar(self, sku: str | None = None, termo: str | None = None) -> list[Produto]:
        filtros = [("status", f"eq.{_status_ativo()}"), ("deleted_at", "is.null")] + filtros_busca(sku, termo)
        try:
            linhas = self._get("products", [("select", SELECT_EMBUTIDO), *filtros, ("order", "name.asc")])
        except ErroConsulta as e:
            if e.codigo not in ("PGRST200", "PGRST201"):  # relação ausente ou ambígua
                raise
            log.warning("Relação products → product_variations não veio embutida (%s); consultando em duas etapas", e.codigo)
            linhas = self._buscar_em_duas_etapas(filtros)
        produtos = [Produto.de_dict(l) for l in linhas]
        log.info("Estoque: %d produto(s) para %s", len(produtos), f"SKU {sku}" if sku else f"termo '{termo}'")
        return produtos

    def _buscar_em_duas_etapas(self, filtros: list[tuple[str, str]]) -> list[dict]:
        linhas = self._get("products", [("select", COLUNAS_PRODUTO), *filtros, ("order", "name.asc")])
        ids = [l.get("id") for l in linhas if l.get("id") is not None]
        variacoes: dict[str, list[dict]] = {}
        for i in range(0, len(ids), LOTE_IDS):
            lote = ",".join(_citar(str(x)) for x in ids[i : i + LOTE_IDS])
            for v in self._get("product_variations", [("select", SELECT_VARIACOES), ("product_id", f"in.({lote})")]):
                variacoes.setdefault(str(v.get("product_id")), []).append(v)
        for l in linhas:
            l["product_variations"] = variacoes.get(str(l.get("id")), [])
        return linhas


def _json_ou_nada(r):
    try:
        return r.json()
    except ValueError:
        return None


def _padrao_ilike(termo: str) -> re.Pattern:
    partes = []
    for c in termo:
        partes.append(".*" if c in "*%" else "." if c == "_" else re.escape(c))
    return re.compile("".join(partes), re.IGNORECASE | re.DOTALL)


class ClienteFalso(ClienteEstoque):
    """Estoque em memória (testes e ensaio sem banco). Aplica os mesmos filtros da consulta real."""

    def __init__(self, produtos: list):
        self.produtos: list[Produto] = []
        for p in produtos:
            if isinstance(p, dict):
                if p.get("deleted_at"):
                    continue
                p = Produto.de_dict(p)
            self.produtos.append(p)
        self.consultas: list[dict] = []

    def buscar(self, sku: str | None = None, termo: str | None = None) -> list[Produto]:
        sku, termo = _validar_busca(sku, termo)
        self.consultas.append({"sku": sku or None, "termo": termo or None})
        padrao = _padrao_ilike(termo) if termo else None
        status = _status_ativo()
        achados = [
            p for p in self.produtos
            if p.status in (None, status) and ((sku and p.sku == sku) or (padrao and padrao.search(p.nome)))
        ]
        return sorted(achados, key=lambda p: p.nome)


def cliente_padrao() -> ClienteEstoque:
    """Supabase; com ``ROTINAS_ESTOQUE_FALSO=<arquivo.json>`` usa o estoque desse arquivo (ensaio sem banco)."""
    # no cmd do Windows, `set VAR="C:\...\x.json"` guarda as aspas junto com o valor
    falso = (os.environ.get("ROTINAS_ESTOQUE_FALSO") or "").strip().strip('"').strip()
    if falso:
        caminho = config.expandir(falso)
        if not caminho.exists():
            raise ErroEstoque(f"ROTINAS_ESTOQUE_FALSO aponta para um arquivo que não existe: {caminho}")
        try:
            dados = json.loads(caminho.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as e:
            raise ErroEstoque(f"JSON inválido em {caminho}: {e}") from e
        if isinstance(dados, dict):
            dados = dados.get("produtos") or []
        log.warning("Usando estoque FALSO de %s (ensaio sem banco)", caminho)
        return ClienteFalso(dados)
    return ClienteSupabase()


def _resumo(p: Produto) -> str:
    return f"{p.sku or '(sem SKU)'} {p.nome}"


def resolver_produto(cliente: ClienteEstoque, sku: str | None = None, termo: str | None = None) -> Produto:
    """O único produto ativo do SKU (ou do termo). Nenhum ou mais de um → ``ErroEstoque`` com os candidatos."""
    sku, termo = _validar_busca(sku, termo)
    produtos = cliente.buscar(sku=sku or None, termo=termo or None)
    if sku:
        exatos = [p for p in produtos if p.sku == sku]
        if len(exatos) == 1:
            return exatos[0]
    if len(produtos) == 1:
        if sku and produtos[0].sku != sku:
            log.warning("SKU %s não existe; usando o produto do termo '%s': %s", sku, termo, _resumo(produtos[0]))
        return produtos[0]
    busca = " ou ".join(x for x in (f"SKU '{sku}'" if sku else "", f"termo '{termo}'" if termo else "") if x)
    candidatos = [{"sku": p.sku, "nome": p.nome} for p in produtos]
    if not produtos:
        raise ErroEstoque(
            f"Nenhum produto ativo encontrado para {busca}. Confira o SKU ou tente outro trecho do nome "
            "(se nada aparece para nenhuma busca, confira se a chave do .env pode ler products).",
            candidatos=candidatos,
        )
    lista = "; ".join(_resumo(p) for p in produtos[:MAX_CANDIDATOS])
    if len(produtos) > MAX_CANDIDATOS:
        lista += f"; e mais {len(produtos) - MAX_CANDIDATOS}"
    raise ErroEstoque(f"Mais de um produto para {busca} ({len(produtos)}): {lista}. Informe o SKU.", candidatos=candidatos)


# ---------------------------------------------------------------- avaliação da letra

class _CorInvalida(ValueError):
    pass


def _casar_cor(texto: str, estoque: dict[str, int]) -> tuple[str, str | None]:
    """Cor do cadastro para o nome identificado → (cor, aviso ou None)."""
    alvo = normalizar_cor(texto)
    if not alvo:
        raise _CorInvalida("cor vazia")
    for cor in estoque:
        if normalizar_cor(cor) == alvo:
            return cor, None
    palavras = _palavras(texto)
    candidatas = [cor for cor in estoque if palavras and all(p in _palavras(cor) for p in palavras)]
    if len(candidatas) == 1:
        return candidatas[0], f"cor aproximada: '{texto}' → '{candidatas[0]}'"
    if candidatas:
        raise _CorInvalida(f"cor '{texto}' é ambígua ({', '.join(candidatas)})")
    raise _CorInvalida(f"cor '{texto}' não existe no cadastro")


def _nome_midia(nome) -> str:
    """``"A - 1.mp4"`` → ``"A - 1"``; outros formatos ficam como vieram."""
    texto = str(nome).strip()
    m = RE_NOME.match(texto) or RE_NOME.match(texto.upper())
    return f"{m.group('letra').upper()} - {int(m.group('n'))}" if m else texto


def _ordem_midia(nome: str) -> tuple:
    m = RE_NOME.match(nome)
    return (0, int(m.group("n"))) if m else (1, 0)


def _cores_lista(cores) -> list[str]:
    if cores is None:
        return []
    if isinstance(cores, str):
        cores = [cores]
    return [str(c).strip() for c in cores if str(c or "").strip()]


def _unicos(itens) -> list:
    vistos: list = []
    for i in itens:
        if i not in vistos:
            vistos.append(i)
    return vistos


def avaliar_letra(letra: str, ident: dict, produto: Produto) -> dict:
    """Aprova ou corta cada mídia da letra pelo estoque do produto.

    ``ident = {"midias": {"A - 1": ["verde"], ...}, "excluir": {"A - 3": "motivo"}}``.
    Nome de cor desconhecido, ambíguo ou ausente → ``ErroEstoque`` (nada é cortado por isso).
    """
    letra = str(letra).strip().upper()
    midias_ident = {_nome_midia(n): _cores_lista(c) for n, c in (ident.get("midias") or {}).items()}
    excluir_bruto = ident.get("excluir") or {}
    if isinstance(excluir_bruto, (list, tuple, set)):
        excluir_bruto = {n: "" for n in excluir_bruto}
    excluir = {_nome_midia(n): str(m or "").strip() for n, m in excluir_bruto.items()}

    problemas: list[str] = []
    for nome in _unicos([*midias_ident, *excluir]):
        m = RE_NOME.match(nome)
        if not m:
            # nome fora do padrão seria "aprovado" sem existir na pasta (o plano não acharia o arquivo)
            problemas.append(f"{nome}: nome fora do padrão '<LETRA> - <n>' (ex.: '{letra} - 1')")
        elif m.group("letra") != letra:
            problemas.append(f"{nome}: não é da letra {letra}")

    estoque = produto.estoque_por_cor()
    total = produto.total
    avisos: list[str] = []
    if not produto.variacoes:
        avisos.append(f"{_resumo(produto)}: nenhuma variação (cor/tamanho) cadastrada no sistema")

    avaliar = sorted((n for n in midias_ident if n not in excluir), key=_ordem_midia)
    cores_por_midia: dict[str, list[str]] = {}
    for nome in avaliar:
        cores = midias_ident[nome]
        if not cores:
            if total > 0:
                problemas.append(f"{nome}: sem cor na identificação (toda mídia precisa de pelo menos 1 cor)")
            cores_por_midia[nome] = []
            continue
        casadas = []
        for texto in cores:
            try:
                cor, aviso = _casar_cor(texto, estoque)
            except _CorInvalida as e:
                if total > 0:  # modelo zerado sai inteiro: nome de cor não importa
                    problemas.append(f"{nome}: {e}")
                continue
            if aviso:
                avisos.append(f"{nome}: {aviso}")
            casadas.append(cor)
        cores_por_midia[nome] = _unicos(casadas)

    cores_validas = [f"{c or '(sem cor)'} ({n})" for c, n in estoque.items()]
    if problemas:
        raise ErroEstoque(
            f"Letra {letra} ({_resumo(produto)}): identificação com problema. Corrija e rode de novo "
            "(nenhuma mídia foi cortada por isso).\n- " + "\n- ".join(problemas)
            + f"\nCores válidas do cadastro: {', '.join(cores_validas) or 'nenhuma'}.",
            problemas=problemas, cores_validas=list(estoque),
        )

    aprovadas: list[str] = []
    cortadas: list[dict] = []
    sem_estoque: list[str] = []
    for nome in sorted([*avaliar, *(n for n in excluir)], key=_ordem_midia):
        if nome in excluir:
            cores = cores_por_midia.get(nome) or midias_ident.get(nome) or []
            cortadas.append({"nome": nome, "motivo": MOTIVO_EXCLUIDA, "detalhe": excluir[nome], "cores": list(cores)})
            continue
        cores = cores_por_midia[nome]
        if total <= 0:
            cortadas.append({"nome": nome, "motivo": MOTIVO_MODELO, "detalhe": _resumo(produto), "cores": cores})
            sem_estoque += cores
            continue
        zeradas = [c for c in cores if estoque.get(c, 0) <= 0]
        if zeradas:
            cortadas.append({"nome": nome, "motivo": MOTIVO_COR, "detalhe": ", ".join(zeradas), "cores": zeradas})
            sem_estoque += zeradas
        else:
            aprovadas.append(nome)

    sem_estoque = _unicos(sem_estoque)
    aprovadas_cores = _unicos(c for n in aprovadas for c in cores_por_midia[n])
    if total <= 0:
        motivo = MOTIVO_MODELO
        avisos.append(f"Letra {letra} fora: {_resumo(produto)} sem nenhuma peça em estoque")
    elif not aprovadas:
        motivo = "nenhuma mídia com estoque" if avaliar else "nenhuma mídia para postar"
        avisos.append(f"Letra {letra} fora: {motivo}")
    else:
        motivo = None
    if total > 0 and sem_estoque:
        cortes = [c["nome"] for c in cortadas if c["motivo"] == MOTIVO_COR]
        avisos.append(f"Cor sem estoque cortada: {', '.join(sem_estoque)} ({', '.join(cortes)})")
    return {
        "letra": letra,
        "produto": produto.como_dict(com_variacoes=False),
        "aprovadas": aprovadas,
        "cortadas": cortadas,
        "cores_sem_estoque": sem_estoque,
        "cores_aprovadas": aprovadas_cores,
        "cores_por_midia": cores_por_midia,
        "avisos": avisos,
        "status": "cortada" if motivo else "ok",
        "motivo": motivo,
    }


# ---------------------------------------------------------------- texto, tarefa e terminal

def texto_produto(p: Produto) -> str:
    """Tabela legível: cor → estoque por tamanho → total."""
    grade = p.tamanhos_por_cor()
    tamanhos = sorted({t for tams in grade.values() for t in tams}, key=_chave_tamanho)
    cab = ["Cor", *[t or "—" for t in tamanhos], "Total"]
    linhas = [cab]
    for cor, tams in grade.items():
        soma = sum(max(n, 0) for n in tams.values())
        linhas.append([cor or "(sem cor)", *[str(tams[t]) if t in tams else "-" for t in tamanhos], str(soma)])
    larguras = [max(len(l[i]) for l in linhas) for i in range(len(cab))]
    saida = [f"{p.sku or '(sem SKU)'} · {p.nome} · {p.categoria or 'sem categoria'} · {_reais(p.preco)} · total {p.total} peça(s)"]
    for i, l in enumerate(linhas):
        partes = [l[0].ljust(larguras[0])] + [c.rjust(larguras[j + 1]) for j, c in enumerate(l[1:])]
        extra = "  sem estoque" if i and l[-1] == "0" else ""
        saida.append("  " + "  ".join(partes) + extra)
    if not grade:
        saida.append("  (nenhuma variação cadastrada)")
    return "\n".join(saida)


def texto_consulta(consulta: dict, produtos: list[Produto]) -> str:
    busca = f"SKU {consulta.get('sku')}" if consulta.get("sku") else f"termo '{consulta.get('termo')}'"
    if not produtos:
        return f"{busca}: nenhum produto ativo encontrado."
    return f"{busca}: {len(produtos)} produto(s)\n\n" + "\n\n".join(texto_produto(p) for p in produtos)


def tarefa(args: dict, ctx) -> dict:
    """Pedido ``stories.estoque``: ``{"consultas": [{"sku": ...} | {"termo": ...}]}``."""
    consultas = args.get("consultas")
    if consultas is None and (args.get("sku") or args.get("termo")):
        consultas = [{"sku": args.get("sku"), "termo": args.get("termo")}]
    if not consultas or not isinstance(consultas, list):
        raise ErroEstoque('Informe "consultas": [{"sku": "..."} ou {"termo": "..."}].')
    cliente = cliente_padrao()
    saida, textos = [], []
    for c in consultas:
        if not isinstance(c, dict):
            raise ErroEstoque(f"Consulta inválida: {c!r} (use {{\"sku\": ...}} ou {{\"termo\": ...}}).")
        produtos = cliente.buscar(sku=c.get("sku"), termo=c.get("termo"))
        saida.append({
            "sku": c.get("sku"),
            "termo": c.get("termo"),
            "encontrados": len(produtos),
            "produtos": [p.como_dict() for p in produtos],
        })
        textos.append(texto_consulta(c, produtos))
    texto = "\n\n".join(textos)
    ctx.arquivo("estoque.txt").write_text(texto + "\n", encoding="utf-8")
    return {"consultas": saida, "texto": texto}


def cli(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="python -m rotinas stories-estoque", description="Consulta o estoque no sistema da loja (só leitura).")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--sku", help="SKU exato (ex.: FB-0123)")
    g.add_argument("--termo", help="trecho do nome da peça (ex.: \"vestido midi\")")
    p.add_argument("--json", action="store_true", help="saída em JSON")
    a = p.parse_args(argv)
    try:
        produtos = cliente_padrao().buscar(sku=a.sku, termo=a.termo)
    except ErroEstoque as e:
        print(f"Erro: {registro.ocultar(str(e))}", file=sys.stderr)
        return 1
    if a.json:
        print(json.dumps([x.como_dict() for x in produtos], ensure_ascii=False, indent=2))
    else:
        print(texto_consulta({"sku": a.sku, "termo": a.termo}, produtos))
    return 0 if produtos else 1
