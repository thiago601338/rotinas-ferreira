"""Montagem do pedido de stories (A2 + A3 + A4): estoque, já postado, links e plano de postagem.

Entrada: o manifesto da pasta do dia (A1) e a identificação feita pela IA
(``{"A": {"sku": "FB-0123" | "termo": "...", "midias": {"A - 1": ["verde"]}, "excluir": {...}, "musica": ...}}``).
Saída: ``plano-<id>.json`` na pasta de trabalho e, se for postar, um pedido ``stories.postar`` na fila.
O padrão é ENSAIO: publicar de verdade exige ``ensaio=False`` (``--real`` no terminal).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from .. import config, fila, registro
from . import estoque, link, postados, relatorio

log = registro.obter("stories.pedido")

RE_NOME = re.compile(r"^(?P<letra>[A-Z]{1,2}) - (?P<n>\d+)(?:\.(?P<ext>[A-Za-z0-9]+))?$")
RE_DATA = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ORDENS = ("letras", "categorias")
MOTIVO_POSTADO = "já postado"
MOTIVO_MODELO = "modelo sem nenhuma peça"
MOTIVO_REPETIDO = "modelo repetido no pedido"


class ErroPedido(RuntimeError):
    """Identificação ou manifesto com problema: nada foi gravado na fila."""

    def __init__(self, mensagem: str, problemas: list[str] | None = None):
        super().__init__(mensagem)
        self.problemas = list(problemas or [])


# ---------------------------------------------------------------- utilidades

def _chave_letra(letra: str) -> tuple:
    return (len(letra), letra)


def _nome_midia(nome) -> str:
    """``"A - 1.mp4"`` → ``"A - 1"``."""
    texto = " ".join(str(nome).split())
    m = RE_NOME.match(texto) or RE_NOME.match(texto.upper())  # "a - 1" (IA em minúsculas) → "A - 1"
    return f"{m.group('letra')} - {int(m.group('n'))}" if m else texto


def _cores(valor) -> list[str]:
    if valor is None:
        return []
    if isinstance(valor, str):
        valor = [valor]
    return [str(c).strip() for c in valor if str(c or "").strip()]


def _gravar_json(caminho: Path, dados) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    tmp = caminho.with_name(caminho.name + ".tmp")
    tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(caminho)


def pasta_trabalho(data: str) -> Path:
    return config.pastas().trabalho_stories / data


def _validar_data(data) -> str:
    d = str(data or "").strip()
    try:
        if not RE_DATA.match(d):
            raise ValueError
        datetime.strptime(d, "%Y-%m-%d")
    except ValueError:
        raise ErroPedido(f"Data inválida: {data!r} (use AAAA-MM-DD, ex.: 2026-09-22)") from None
    return d


# ---------------------------------------------------------------- manifesto e identificação

def carregar_manifesto(data: str) -> tuple[dict, bool]:
    """Manifesto do dia; se ainda não existe, roda a preparação da pasta (A1). Devolve (manifesto, gerado_agora)."""
    caminho = pasta_trabalho(data) / "manifesto.json"
    if caminho.exists():
        try:
            return json.loads(caminho.read_text(encoding="utf-8-sig")), False
        except json.JSONDecodeError as e:
            raise ErroPedido(f"manifesto.json inválido em {caminho}: {e}. Rode stories-preparar de novo.") from e
    log.info("Sem manifesto de %s: preparando a pasta do dia primeiro", data)
    from . import pasta

    return pasta.preparar(data), True


def _musica_da_ident(valor, letra: str, problemas: list[str]):
    """Índice (começa em 0) na lista ``audios_sem_som`` ou objeto ``{"nome", "autor", "busca"}``."""
    if valor is None:
        return None
    audios = config.carregar("stories").get("audios_sem_som") or []
    if isinstance(valor, int) and not isinstance(valor, bool):
        if 0 <= valor < len(audios):
            return dict(audios[valor])
        opcoes = "; ".join(f"{i} = {a.get('nome')} ({a.get('autor')})" for i, a in enumerate(audios))
        problemas.append(f"Letra {letra}: música {valor} não existe. Opções: {opcoes}")
        return None
    if isinstance(valor, dict) and (valor.get("busca") or valor.get("nome")):
        m = {"nome": valor.get("nome") or valor.get("busca"), "autor": valor.get("autor") or "", "busca": valor.get("busca") or valor.get("nome")}
        return {k: str(v) for k, v in m.items()}
    problemas.append(f"Letra {letra}: música inválida {valor!r} (use o índice de audios_sem_som ou {{\"nome\", \"autor\", \"busca\"}})")
    return None


def validar_identificacao(manifesto: dict, identificacao: dict) -> dict:
    """Confere a identificação contra o manifesto e devolve a versão normalizada.

    Erros juntos numa só ``ErroPedido`` (a IA corrige tudo de uma vez): letra ou mídia que não existe,
    mídia sem cor, mídia da letra sem identificação, letra sem SKU/termo.
    """
    if not isinstance(identificacao, dict) or not identificacao:
        raise ErroPedido("Identificação vazia: informe {\"A\": {\"sku\": ..., \"midias\": {\"A - 1\": [\"cor\"]}}}.")
    letras_man = manifesto.get("letras") or {}
    problemas: list[str] = []
    saida: dict[str, dict] = {}
    for chave, info in identificacao.items():
        letra = str(chave).strip().upper()
        if letra.startswith("_"):
            continue  # comentários
        if letra not in letras_man:
            problemas.append(f"Letra {letra} não existe no manifesto de {manifesto.get('data')} (letras: {', '.join(sorted(letras_man, key=_chave_letra)) or 'nenhuma'})")
            continue
        if not isinstance(info, dict):
            problemas.append(f"Letra {letra}: identificação tem que ser um objeto")
            continue
        sku = str(info.get("sku") or "").strip() or None
        termo = str(info.get("termo") or "").strip() or None
        if not sku and not termo:
            problemas.append(f"Letra {letra}: falta o SKU ou o termo da peça")
        nomes_man = [m["nome"] for m in letras_man[letra].get("midias") or []]
        midias: dict[str, list[str]] = {}
        if not isinstance(info.get("midias") or {}, dict):
            problemas.append(f"Letra {letra}: \"midias\" tem que ser {{\"{letra} - 1\": [\"cor\"], ...}}")
            info = {**info, "midias": {}}
        for nome, cores in (info.get("midias") or {}).items():
            n = _nome_midia(nome)
            if n not in nomes_man:
                problemas.append(f"Letra {letra}: mídia {nome} não existe nessa letra ({', '.join(nomes_man)})")
                continue
            midias[n] = _cores(cores)
        excluir_bruto = info.get("excluir") or {}
        if isinstance(excluir_bruto, (list, tuple)):
            excluir_bruto = {n: "" for n in excluir_bruto}
        excluir: dict[str, str] = {}
        for nome, motivo in excluir_bruto.items():
            n = _nome_midia(nome)
            if n not in nomes_man:
                problemas.append(f"Letra {letra}: mídia {nome} (excluir) não existe nessa letra")
                continue
            excluir[n] = str(motivo or "").strip()
        for n, cores in midias.items():
            if not cores and n not in excluir:
                problemas.append(f"Letra {letra}: {n} sem cor (toda mídia precisa de pelo menos 1 cor)")
        faltando = [n for n in nomes_man if n not in midias and n not in excluir]
        if faltando:
            problemas.append(f"Letra {letra}: {', '.join(faltando)} sem identificação (informe as cores ou ponha em \"excluir\" com o motivo)")
        item = {"sku": sku, "termo": termo, "midias": midias, "excluir": excluir}
        if info.get("peca"):
            item["peca"] = " ".join(str(info["peca"]).split())
        if info.get("musica") is not None:
            item["musica"] = _musica_da_ident(info["musica"], letra, problemas)
        saida[letra] = item
    if problemas:
        raise ErroPedido("Identificação com problema (nada foi gravado na fila):\n- " + "\n- ".join(problemas), problemas)
    return dict(sorted(saida.items(), key=lambda kv: _chave_letra(kv[0])))


# ---------------------------------------------------------------- ordem

def _grupo_categoria(categoria: str | None) -> tuple[int, str | None]:
    grupos = config.carregar("stories").get("compilacao_ordem") or []
    alvo = link.normalizar(categoria)
    for i, g in enumerate(grupos):
        if alvo and alvo in {link.normalizar(c) for c in g.get("categorias") or []}:
            return i, g.get("grupo")
    return len(grupos), None


def ordenar(letras: list[dict], ordem: str, avisos: list[str]) -> list[dict]:
    """``letras``: A, B, C…; ``categorias``: conjuntos → vestidos casuais → macacões → festa (config)."""
    letras = sorted(letras, key=lambda l: _chave_letra(l["letra"]))
    if ordem == "letras":
        return letras
    chaves = {}
    for l in letras:
        i, grupo = _grupo_categoria(l.get("categoria"))
        if grupo is None:
            avisos.append(
                f"Letra {l['letra']}: categoria '{l.get('categoria') or 'sem categoria'}' fora da compilacao_ordem "
                "(config/stories.json); foi para o fim"
            )
        chaves[l["letra"]] = i
    return sorted(letras, key=lambda l: (chaves[l["letra"]], _chave_letra(l["letra"])))


# ---------------------------------------------------------------- montagem

def _novo_id(pasta: Path) -> str:
    base = datetime.now().strftime("%Y%m%d-%H%M%S") + "-stories-montar"
    candidato, n = base, 1
    while (pasta / f"plano-{candidato}.json").exists():
        n += 1
        candidato = f"{base}-{n}"
    return candidato


def _corte(letra: str, nome, motivo: str, detalhe, peca=None, sku=None, **extras) -> dict:
    return {"letra": letra, "nome": nome, "motivo": motivo, "detalhe": detalhe, "peca": peca, "sku": sku, **extras}


def _avisos_estoque(letra: str, avisos: list[str]) -> list[str]:
    # os cortes já viram linhas do relatório; aqui ficam só os avisos que não se repetem nos cortes
    saida = []
    for a in avisos or []:
        if a.startswith(("Cor sem estoque cortada", f"Letra {letra} fora")):
            continue
        saida.append(a if a.startswith("Letra ") else f"Letra {letra}: {a}")
    return saida


def _avaliar(letra: str, ident: dict, info_man: dict, cliente, data: str, postadas_hoje: set[str],
             permitir: set[str], cortes: list[dict], avisos: list[str]) -> dict | None:
    """Uma letra: já postada hoje → estoque → repetição. Devolve a letra do plano (sem música/figurinha) ou None."""
    if letra in postadas_hoje:
        if letra not in permitir:
            linhas = [l for l in postados.ler() if l.get("data") == data and l.get("letra") == letra]
            peca, sku = (linhas[0].get("peca") or None, linhas[0].get("sku") or None) if linhas else (None, None)
            cortes.append(_corte(letra, None, MOTIVO_POSTADO, f"já postado em {relatorio.data_br(data)}, letra {letra} (esta mesma pasta)", peca, sku))
            return None
        avisos.append(f"Letra {letra}: já postada hoje, repetição permitida pelo usuário")

    produto = estoque.resolver_produto(cliente, sku=ident.get("sku"), termo=ident.get("termo"))
    peca = link.nome_peca(ident.get("peca") or produto.nome)
    aval = estoque.avaliar_letra(letra, {"midias": ident["midias"], "excluir": ident["excluir"]}, produto)
    avisos += _avisos_estoque(letra, aval.get("avisos"))
    if produto.total <= 0:
        cortes.append(_corte(letra, None, MOTIVO_MODELO, produto.sku or None, peca, produto.sku))
        return None
    for c in aval.get("cortadas") or []:
        detalhe = c.get("detalhe") or ", ".join(c.get("cores") or [])
        cortes.append(_corte(letra, _nome_midia(c["nome"]), c.get("motivo") or "cortada", detalhe, peca, produto.sku, cores=list(c.get("cores") or [])))
    aprovadas = {_nome_midia(n) for n in aval.get("aprovadas") or []}
    midias_man = [m for m in info_man.get("midias") or [] if m["nome"] in aprovadas]
    if not midias_man:
        avisos.append(f"Letra {letra} ({peca}) fora: {aval.get('motivo') or 'nenhuma mídia com estoque'}")
        return None

    ocorrencias = postados.verificar(data, letra, produto.sku or None, [m.get("hash") for m in midias_man if m.get("hash")])
    if ocorrencias:
        textos = "; ".join(dict.fromkeys(o.get("texto") or "" for o in ocorrencias))
        if letra not in permitir:
            cortes.append(_corte(letra, None, MOTIVO_POSTADO, textos, peca, produto.sku, ocorrencias=ocorrencias))
            return None
        avisos.append(f"Letra {letra}: repetição permitida pelo usuário ({textos})")

    cores_por_midia = aval.get("cores_por_midia") or {}
    midias = []
    for m in midias_man:
        midias.append({
            "nome": m["nome"],
            "arquivo": m.get("arquivo"),
            "caminho": m.get("caminho"),
            "tipo": m.get("tipo"),
            "hash": m.get("hash"),
            "cores": list(cores_por_midia.get(m["nome"]) or ident["midias"].get(m["nome"]) or []),
            "precisa_musica": bool(m.get("tipo") == "video" and m.get("precisa_musica")),
            "musica": None,
            "figurinha": None,
        })
    return {"letra": letra, "sku": produto.sku, "peca": peca, "categoria": produto.categoria, "midias": midias}


def _sem_modelo_repetido(letras: list[dict], permitir: set[str], cortes: list[dict]) -> list[dict]:
    """Uma letra por modelo: o mesmo SKU em duas letras do pedido fica só na primeira."""
    primeira: dict[str, str] = {}
    saida = []
    for l in sorted(letras, key=lambda x: _chave_letra(x["letra"])):
        chave = (l.get("sku") or "").casefold()
        if chave and chave in primeira and l["letra"] not in permitir:
            cortes.append(_corte(l["letra"], None, MOTIVO_REPETIDO, f"mesmo modelo ({l['sku']}) da letra {primeira[chave]} deste pedido", l["peca"], l["sku"]))
            continue
        primeira.setdefault(chave, l["letra"])
        saida.append(l)
    return saida


def _conferir_arquivos(letras: list[dict]) -> None:
    faltando = [f"{m['nome']} ({m.get('caminho')})" for l in letras for m in l["midias"] if not m.get("caminho") or not Path(m["caminho"]).exists()]
    if faltando:
        raise ErroPedido(
            "Mídias do manifesto que não estão na pasta: " + "; ".join(faltando)
            + ". Rode stories-preparar de novo antes de montar o pedido.", faltando,
        )


def _conferir_limite(letras: list[dict]) -> None:
    """O A5 recusa o plano inteiro com letra acima de ``max_midias_por_letra``: melhor parar aqui, antes da fila."""
    maximo = int(config.carregar("stories").get("max_midias_por_letra", 10))
    grandes = [f"{l['letra']} ({len(l['midias'])} mídias)" for l in letras if len(l["midias"]) > maximo]
    if grandes:
        raise ErroPedido(
            f"Letra com mais de {maximo} mídias (max_midias_por_letra em config/stories.json): {', '.join(grandes)}. "
            "Ponha as sobras em \"excluir\" com o motivo e monte de novo.", grandes,
        )


def _postagens_reais_na_fila(data: str) -> dict[str, set[str]]:
    """Pedidos ``stories.postar`` REAIS ainda pendentes/em andamento para ``data`` → {id: letras}."""
    raiz = fila.pasta_fila()
    saida: dict[str, set[str]] = {}
    for estado in ("pendente", "andamento"):
        pasta = raiz / estado
        if not pasta.is_dir():
            continue
        for arq in pasta.glob("*.json"):
            try:
                p = json.loads(arq.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                continue
            if not isinstance(p, dict) or p.get("tipo") != "stories.postar":
                continue
            plano = (p.get("args") or {}).get("plano")
            if not isinstance(plano, dict) or plano.get("data") != data:
                continue
            if p.get("ensaio") or plano.get("ensaio", False):
                continue
            saida[p.get("id") or arq.stem] = {str(l.get("letra")) for l in plano.get("letras") or []}
    return saida


def _sem_postagem_duplicada(data: str, letras: list[dict]) -> None:
    """Rodar ``stories-montar --real`` duas vezes não pode deixar duas postagens reais das mesmas letras na fila."""
    nossas = {l["letra"] for l in letras}
    choques = {id_: sorted(ls & nossas, key=_chave_letra) for id_, ls in _postagens_reais_na_fila(data).items() if ls & nossas}
    if choques:
        detalhe = "; ".join(f"{id_} (letras {', '.join(ls)})" for id_, ls in sorted(choques.items()))
        raise ErroPedido(
            f"Já existe postagem REAL de {data} na fila com as mesmas letras: {detalhe}. "
            "Espere terminar (e rode stories-relatorio) ou tire o pedido de fila/pendente antes de montar de novo.",
            list(choques),
        )


def _musica_e_figurinha(letras: list[dict], ident: dict) -> None:
    """Música nos vídeos sem som e figurinha na última mídia de cada letra que leva link (na ordem final)."""
    i_musica = i_texto = 0
    for l in letras:
        escolhida = ident[l["letra"]].get("musica")
        for m in l["midias"]:
            if m["precisa_musica"]:
                if escolhida:
                    m["musica"] = dict(escolhida)
                else:
                    m["musica"] = link.musica_para(i_musica)
                    i_musica += 1
        if link.leva_link(l["categoria"]):  # ErroRegra (vestido de festa não confirmado) sobe com a mensagem
            l["midias"][-1]["figurinha"] = link.figurinha(l["peca"], i_texto)
            i_texto += 1


def montar(
    data: str,
    identificacao: dict,
    ensaio: bool = True,
    postar: bool = True,
    ordem: str = "letras",
    permitir_repeticao=(),
    cliente=None,
    id_plano: str | None = None,
) -> dict:
    """Monta o plano de postagem e (se ``postar``) grava o pedido ``stories.postar`` na fila.

    Devolve ``{"plano", "relatorio", "pedido_postagem", "arquivo_plano"}``.
    """
    data = _validar_data(data)
    if ordem not in ORDENS:
        raise ErroPedido(f"Ordem inválida: {ordem!r} (use {' ou '.join(ORDENS)})")
    manifesto, gerado_agora = carregar_manifesto(data)
    if manifesto.get("simulado"):
        raise ErroPedido(f"O manifesto de {data} é de simulação (stories-preparar --simular). Rode stories-preparar sem --simular antes.")
    ident = validar_identificacao(manifesto, identificacao)
    permitir = {str(l).strip().upper() for l in permitir_repeticao or []}
    cliente = cliente or estoque.cliente_padrao()
    letras_man = manifesto.get("letras") or {}

    avisos: list[str] = list(manifesto.get("avisos") or []) if gerado_agora else []
    cortes: list[dict] = []
    postadas_hoje = postados.letras_postadas(data)
    for letra in sorted(letras_man, key=_chave_letra):
        if letra not in ident and letra not in postadas_hoje:
            avisos.append(f"Letra {letra} sem identificação: ficou de fora")

    letras: list[dict] = []
    erros: list[str] = []
    for letra, item in ident.items():
        try:
            l = _avaliar(letra, item, letras_man[letra], cliente, data, postadas_hoje, permitir, cortes, avisos)
        except estoque.ErroEstoque as e:
            erros.append(f"Letra {letra}: {e}")
            continue
        if l:
            letras.append(l)
    if erros:
        raise ErroPedido("Estoque/identificação com problema (nada foi gravado na fila):\n\n" + "\n\n".join(erros), erros)

    letras = ordenar(_sem_modelo_repetido(letras, permitir, cortes), ordem, avisos)
    _musica_e_figurinha(letras, ident)
    _conferir_arquivos(letras)
    _conferir_limite(letras)
    if postar and letras and not ensaio:
        _sem_postagem_duplicada(data, letras)

    pasta = pasta_trabalho(data)
    pasta.mkdir(parents=True, exist_ok=True)
    id_plano = id_plano or _novo_id(pasta)
    plano = {"data": data, "id": id_plano, "ensaio": bool(ensaio), "ordem": ordem, "letras": letras, "cortes": cortes, "avisos": avisos}
    _gravar_json(pasta / "identificacao.json", ident)
    arquivo_plano = pasta / f"plano-{id_plano}.json"
    _gravar_json(arquivo_plano, plano)
    texto = relatorio.texto_plano(plano)

    pedido_postagem = None
    if postar and letras:
        args = {"plano": plano}
        # letra já publicada hoje que o usuário mandou repetir: sem "repostar" o A5 pula a letra (postados.csv)
        repostar = sorted((permitir & postadas_hoje) & {l["letra"] for l in letras}, key=_chave_letra)
        if repostar:
            args["repostar"] = repostar
        pedido_postagem = fila.criar_pedido("stories.postar", args, ensaio=plano["ensaio"], sufixo=data).stem
        texto += f"\n\nPedido de postagem na fila: {pedido_postagem}" + (" (ensaio)" if plano["ensaio"] else " (POSTAGEM REAL)")
    elif postar:
        texto += "\n\nNada para postar: nenhum pedido foi gravado na fila."
    (pasta / f"relatorio-{id_plano}.txt").write_text(texto + "\n", encoding="utf-8")
    log.info("Plano %s: %d letra(s), %d corte(s)%s", id_plano, len(letras), len(cortes),
             f", pedido {pedido_postagem}" if pedido_postagem else "")
    return {"plano": plano, "relatorio": texto, "pedido_postagem": pedido_postagem, "arquivo_plano": str(arquivo_plano)}


# ---------------------------------------------------------------- fila e terminal

def _ler_identificacao(valor) -> dict:
    if isinstance(valor, dict):
        return valor
    caminho = Path(str(valor))
    if not caminho.exists():
        raise ErroPedido(f"Arquivo de identificação não encontrado: {caminho}")
    try:
        return json.loads(caminho.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as e:
        raise ErroPedido(f"JSON inválido em {caminho}: {e}") from e


def tarefa(args: dict, ctx) -> dict:
    """Pedido ``stories.montar``: ``{"data", "identificacao": {...} | "arquivo.json", "ensaio"?, "postar"?, "ordem"?,
    "permitir_repeticao"?}``. Ensaio é o padrão: só publica com ``"ensaio": false`` e o pedido sem ``--ensaio``."""
    if not args.get("data") or args.get("identificacao") is None:
        raise ErroPedido('Informe "data" e "identificacao".')
    ensaio = bool(ctx.ensaio) or bool(args.get("ensaio", True))
    res = montar(
        args["data"],
        _ler_identificacao(args["identificacao"]),
        ensaio=ensaio,
        postar=bool(args.get("postar", True)),
        ordem=args.get("ordem") or "letras",
        permitir_repeticao=args.get("permitir_repeticao") or (),
        id_plano=ctx.id_pedido,
    )
    ctx.arquivo("plano.json").write_text(json.dumps(res["plano"], ensure_ascii=False, indent=2), encoding="utf-8")
    ctx.arquivo("relatorio.txt").write_text(res["relatorio"] + "\n", encoding="utf-8")
    return res


def cli(argv: list[str]) -> int:
    p = argparse.ArgumentParser(
        prog="python -m rotinas stories-montar",
        description="Corta sem estoque e já postados, monta os links e grava o pedido de postagem (padrão: ENSAIO).",
    )
    p.add_argument("--data", required=True, help="dia da pasta (AAAA-MM-DD)")
    p.add_argument("--identificacao", required=True, help="arquivo JSON com a identificação das letras")
    p.add_argument("--real", action="store_true", help="publicar de verdade (sem isto é ensaio)")
    p.add_argument("--sem-postar", action="store_true", help="só monta o plano, sem gravar o pedido na fila")
    p.add_argument("--ordem", choices=ORDENS, default="letras")
    p.add_argument("--permitir-repeticao", nargs="*", default=[], metavar="LETRA", help="letras que o usuário mandou repetir")
    p.add_argument("--json", action="store_true", help="saída em JSON")
    a = p.parse_args(argv)
    try:
        res = montar(a.data, _ler_identificacao(a.identificacao), ensaio=not a.real, postar=not a.sem_postar,
                     ordem=a.ordem, permitir_repeticao=a.permitir_repeticao)
    except (RuntimeError, config.ErroConfig, OSError) as e:  # ErroPedido/Regra/Estoque/Postados/Pasta e arquivo preso
        print(f"Erro: {registro.ocultar(str(e))}", file=sys.stderr)
        return 1
    print(json.dumps(res, ensure_ascii=False, indent=2) if a.json else res["relatorio"])
    return 0
