"""B2: plano da linha do tempo (receita + bruto + escolhas da IA) → ``plano.json`` para o gerador de rascunho (B3).

``planejar()`` lê ``videos/trabalho/<projeto>/bruto.json`` (B1), a receita (``receitas/*.json``) e as escolhas da IA
(tomadas, recortes e textos) e monta a linha do tempo: cortes em quadros inteiros do fps do destino (na batida quando a
receita pede), textos na zona segura, preço no formato da loja, legendas retimadas, música e volumes, transições e
efeitos dentro do orçamento (§4.1). No fim roda ``validar_plano()``: violação bloqueia (a tarefa da fila dá erro),
aviso não bloqueia. Regras em ``conhecimento/edicao-video-capcut.md`` §3–§10; parâmetros em ``config/video.json``.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import os
import re
import statistics
import sys
from collections import Counter
from datetime import datetime
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path, PureWindowsPath

from .. import config, registro
from ..contexto import Contexto
from . import receitas, transcricao

log = registro.obter("video.plano")

PRECO_LOJA = re.compile(r"R\$(?:\d{1,3}(?:\.\d{3})+|\d{1,3}),\d{2}(?![\d,])")
_PRECO_QUALQUER = re.compile(r"R\$\s*(?:[\d.,]*\d)?")
_SO_MILHAR = re.compile(r"^\d{1,3}(?:\.\d{3})+$")
_TOMADA = re.compile(r"^[Tt]0*(\d+)$")
_AUTOMATICOS = ("preco", "parcelas")
_EXT_FOTO = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}
_EPS = 1e-6


class ErroPlano(RuntimeError):
    """Escolhas, receita ou bruto que não dão um plano (ou plano com violações, na tarefa da fila)."""

    def __init__(self, mensagem: str, resultado_parcial: dict | None = None):
        super().__init__(mensagem)
        if resultado_parcial is not None:
            self.resultado_parcial = resultado_parcial


def _c() -> dict:
    return config.carregar("video")


def _nome(caminho) -> str:
    """Nome do arquivo de um caminho do Windows ou do Linux (o bruto.json vem do PC)."""
    return PureWindowsPath(str(caminho or "")).name


_r = receitas.regra


def _s(q: int, fps: float) -> float:
    """Quadros → segundos (4 casas)."""
    return round(q / fps, 4)


def _n(valor: float, casas: int = 1) -> str:
    return f"{valor:.{casas}f}".replace(".", ",")


# ---------------------------------------------------------------- preço (regra da loja, §5)

def _centavos(valor) -> int:
    if valor is None or isinstance(valor, bool):
        raise ValueError(f"Preço inválido: {valor!r}")
    if isinstance(valor, str):
        texto = valor.strip().replace("R$", "").replace(" ", "").replace(" ", "")
        if "," in texto or _SO_MILHAR.match(texto):
            # formato brasileiro: "1.299,90" e também "1.299" (ponto de milhar, sem centavos)
            texto = texto.replace(".", "").replace(",", ".")
        valor = texto
    try:
        d = Decimal(str(valor))
    except InvalidOperation as e:
        raise ValueError(f"Preço inválido: {valor!r}") from e
    if not d.is_finite() or d <= 0:
        raise ValueError(f"Preço inválido: {valor!r}")
    return int((d * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _reais(centavos: int) -> str:
    reais, cent = divmod(int(centavos), 100)
    return f"R${reais:,}".replace(",", ".") + f",{cent:02d}"


def formatar_preco(valor) -> str:
    """``229.99`` → ``"R$229,99"``; ``1299.9`` → ``"R$1.299,90"`` (cifrão colado, milhar com ponto)."""
    return _reais(_centavos(valor))


def vezes_sem_juros(valor) -> int:
    """Regra da Ferreira: até R$149,99 em 2x; até R$319,98 em 3x; acima em 5x (``parcelas_loja``)."""
    cent = _centavos(valor)
    faixas = _r("parcelas_loja")
    for faixa in faixas:
        if faixa.get("ate") is None or cent <= _centavos(faixa["ate"]):
            return int(faixa["vezes"])
    return int(faixas[-1]["vezes"])


def parcelas(preco, com_valor: bool | None = None) -> str:
    """``229.99`` → ``"3x sem juros"`` (formato do guia §4.4).

    Com ``com_valor`` (ou ``parcela_mostrar_valor`` na config): ``"3x de R$76,66 sem juros"``, parcela
    arredondada ao centavo conforme ``parcela_arredondamento`` — só usar depois de o dono confirmar a regra.
    """
    cent = _centavos(preco)
    vezes = vezes_sem_juros(preco)
    if com_valor is None:
        com_valor = bool(_c().get("parcela_mostrar_valor", False))
    if not com_valor:
        return f"{vezes}x sem juros"
    modo = ROUND_DOWN if _c().get("parcela_arredondamento") == "para_baixo" else ROUND_HALF_UP
    parcela = int((Decimal(cent) / vezes).quantize(Decimal(1), rounding=modo))
    return f"{vezes}x de {_reais(parcela)} sem juros"


def precos_fora_do_formato(texto: str) -> list[str]:
    """Trechos com ``R$`` fora do formato da loja (``R$229,99``, ``R$1.299,90``)."""
    ruins = []
    for m in _PRECO_QUALQUER.finditer(str(texto or "")):
        if not PRECO_LOJA.match(str(texto), m.start()):
            ruins.append(m.group(0).strip() or "R$")
    return ruins


def _normalizar_precos(texto: str) -> str:
    """Preço da fala no formato da loja: ``R$ 229,99`` → ``R$229,99``, ``R$ 230`` → ``R$230,00``,
    ``R$229.99`` → ``R$229,99`` (a transcrição separa o cifrão e nem sempre põe os centavos)."""

    def trocar(m: re.Match) -> str:
        try:
            return formatar_preco(m.group(1))
        except ValueError:
            return m.group(0)

    return re.sub(r"R\$\s*(\d(?:[\d.,]*\d)?)", trocar, texto)


# ---------------------------------------------------------------- texto: caixa, quebra e tamanho

def _largura(linha: str, tamanho: float) -> float:
    """Largura estimada: maiúscula é mais larga que minúscula (sans bold: ~0,70 × ~0,58 do tamanho)."""
    rt = _r("plano_texto")
    comum = float(rt["largura_caractere"])
    maiuscula = float(rt.get("largura_caractere_maiuscula", comum))
    return sum(maiuscula if c.isupper() else comum for c in linha) * float(tamanho)


def caixa_texto(item: dict) -> tuple[float, float, float, float]:
    """Caixa estimada ``(x0, y0, x1, y1)`` de um texto do plano (x/y = centro)."""
    rt = _r("plano_texto")
    linhas = str(item.get("texto") or "").split("\n")
    tam = float(item.get("tamanho_px") or 0)
    larg = max(_largura(linha, tam) for linha in linhas)
    alt = len(linhas) * tam * float(rt["entrelinha"])
    x = float(item.get("x", rt["x_padrao"]))
    y = float(item.get("y", 0))
    return x - larg / 2, y - alt / 2, x + larg / 2, y + alt / 2


def _quebrar(palavras_: list[str], n: int) -> list[str] | None:
    """Divide em ``n`` linhas equilibradas (menor linha mais longa possível), evitando terminar linha em artigo,
    preposição ou "R$" (§5: não separar artigo e substantivo)."""
    if n > len(palavras_):
        return None
    presas = {p.casefold() for p in _c().get("palavras_que_nao_fecham_bloco") or []}
    melhor = None
    for cortes in itertools.combinations(range(1, len(palavras_)), n - 1):
        pontos = (0, *cortes, len(palavras_))
        linhas = [" ".join(palavras_[a:b]) for a, b in zip(pontos, pontos[1:])]
        ruins = sum(1 for c in cortes if palavras_[c - 1].casefold() in presas)
        custo = (ruins, max(len(linha) for linha in linhas))
        if melhor is None or custo < melhor[0]:
            melhor = (custo, linhas)
    return melhor[1] if melhor else None


def ajustar_texto(texto: str, tamanho: float, tamanho_min: float, x: float, max_linhas: int | None = None) -> tuple[str, float]:
    """Quebra em até ``max_linhas`` e reduz o tamanho (até ``tamanho_min``) para caber na largura segura em torno de x."""
    rt = _r("plano_texto")
    zona = _r("zona_segura")
    max_linhas = int(max_linhas or rt["max_linhas"])
    largura_max = 2 * min(x - zona["x"][0], zona["x"][1] - x)
    tamanho_min = max(float(tamanho_min), float(rt["tamanho_min_px"]))
    fixas = "\n" in texto
    palavras_ = texto.split()
    tam = float(tamanho)
    ultimo = texto
    while True:
        opcoes = [texto.split("\n")] if fixas else [_quebrar(palavras_, n) for n in range(1, max_linhas + 1)]
        for linhas in opcoes:
            if linhas and max(_largura(linha, tam) for linha in linhas) <= largura_max + _EPS:
                return "\n".join(linhas), tam
        if opcoes and opcoes[-1]:
            ultimo = "\n".join(opcoes[-1])
        if tam - 2 < tamanho_min - _EPS:
            return ultimo, tam
        tam -= 2


def tempo_minimo(item: dict) -> float:
    """Tempo mínimo de um texto do plano (§5); papéis isentos (contador) usam o ``min_s`` da receita."""
    rt = _r("plano_texto")
    if item.get("papel") in rt["papeis_sem_tempo_minimo"]:
        return float(item.get("min_s") or 0)
    return max(receitas.tempo_minimo_texto(item.get("texto", "")), float(item.get("min_s") or 0))


# ---------------------------------------------------------------- entrada: bruto, palavras, fontes

def _pastas(projeto: str) -> dict[str, Path]:
    from .bruto import pastas_projeto

    return pastas_projeto(projeto)


def _ler_json(caminho: Path):
    return json.loads(Path(caminho).read_text(encoding="utf-8"))


def _gravar_json(caminho: Path, dados) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    tmp = caminho.with_name(caminho.name + ".tmp")
    tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, caminho)


def carregar_bruto(projeto: str) -> tuple[dict, dict[str, Path]]:
    p = _pastas(projeto)
    arq = p["trabalho"] / "bruto.json"
    if not arq.is_file():
        raise ErroPlano(f"Não achei {arq}. Rode antes: python -m rotinas video-preparar --projeto {projeto}")
    return _ler_json(arq), p


def _palavras(p: dict[str, Path], bruto: dict) -> dict[str, list[dict]]:
    """Palavras transcritas por arquivo (``transcricao.json``; senão, as do ``bruto.json``), em tempo do arquivo."""
    por: dict[str, list[dict]] = {}
    arq = p["trabalho"] / "transcricao.json"
    if arq.is_file():
        for a in _ler_json(arq).get("arquivos") or []:
            por.setdefault(a.get("arquivo"), []).extend(a.get("palavras") or [])
    elif bruto.get("transcricao"):
        for w in bruto["transcricao"].get("palavras") or []:
            por.setdefault(w.get("arquivo"), []).append(w)
    for lista in por.values():
        lista.sort(key=lambda w: float(w["ini_s"]))
    return por


def _no_trecho(palavras_: list[dict], a: float, b: float, eps: float = 0.02) -> list[dict]:
    return [w for w in palavras_ if float(w["ini_s"]) >= a - eps and float(w["fim_s"]) <= b + eps]


def _id_tomada(valor) -> str:
    m = _TOMADA.match(str(valor).strip())
    return f"T{int(m.group(1)):02d}" if m else str(valor).strip()


def _fonte(bruto: dict, valor, arquivos: dict[str, dict]) -> dict:
    tid = _id_tomada(valor)
    tomadas = bruto.get("tomadas") or []
    t = next((x for x in tomadas if x.get("id") == tid), None)
    if t is None:
        faixa = f"{tomadas[0]['id']}–{tomadas[-1]['id']}" if tomadas else "nenhuma"
        raise ErroPlano(f"Tomada {valor!r} não existe no bruto.json (tomadas: {faixa}).")
    a = arquivos.get(t["arquivo"]) or {}
    info = a.get("info") or {}
    return {"tomada": tid, "arquivo": t["arquivo"], "caminho": a.get("caminho_edicao") or a.get("caminho") or t["arquivo"],
            "ini": float(t["ini_s"]), "fim": float(t["fim_s"]), "fps": info.get("fps"), "tipo": "video",
            "silencios": a.get("silencios") or [], "fala_arquivo": bool(a.get("fala"))}


def _foto(valor, p: dict[str, Path]) -> dict:
    c = Path(str(valor).strip().strip('"'))
    candidatos = [c] if c.is_absolute() else [p["bruto"] / c]
    achado = next((x for x in candidatos if x.is_file()), None)
    if achado is None:
        raise ErroPlano(f"Foto não encontrada: {valor}. Procurei em: " + "; ".join(str(x) for x in candidatos))
    if achado.suffix.lower() not in _EXT_FOTO:
        raise ErroPlano(f"{achado.name} não é foto ({', '.join(sorted(_EXT_FOTO))}).")
    return {"tomada": None, "arquivo": achado.name, "caminho": str(achado), "ini": 0.0, "fim": math.inf, "fps": None,
            "tipo": "foto", "silencios": [], "fala_arquivo": False}


def _num(valor, nome: str) -> float | None:
    if valor is None:
        return None
    if isinstance(valor, str):
        valor = valor.replace(",", ".")
    try:
        x = float(valor)
    except (TypeError, ValueError) as e:
        raise ErroPlano(f"{nome} tem que ser um número (segundos): {valor!r}") from e
    if not math.isfinite(x):
        raise ErroPlano(f"{nome} inválido: {valor!r}")
    return x


def _efeitos_def(d: dict) -> list[int]:
    e = d.get("efeito")
    return [] if e is None else list(e) if isinstance(e, list) else [e]


def _sons_def(d: dict) -> list[str]:
    s = d.get("som")
    return [] if s is None else list(s) if isinstance(s, list) else [s]


def _papeis_texto(d: dict) -> list[str]:
    t = d.get("texto")
    return [] if t is None else [t] if isinstance(t, str) else list(t)


def _resolver_blocos(escolhas: dict, receita: dict, bruto: dict, p: dict[str, Path], avisos: list[str]) -> list[dict]:
    defs = {d["papel"]: d for d in receita["estrutura"]}
    escolhidos = escolhas.get("blocos")
    if not isinstance(escolhidos, list) or not escolhidos:
        raise ErroPlano("escolhas sem 'blocos' (lista com papel, tomada, ini_s/fim_s opcionais e texto).")
    arquivos = {a.get("arquivo"): a for a in bruto.get("arquivos") or []}
    comps = _c().get("composicoes") or {}
    tol = float(_r("plano_ritmo")["tolerancia_tomada_s"])
    blocos = []
    for i, e in enumerate(escolhidos):
        rotulo = f"bloco {i + 1}"
        if not isinstance(e, dict) or e.get("papel") not in defs:
            papel = e.get("papel") if isinstance(e, dict) else e
            raise ErroPlano(f"{rotulo}: papel {papel!r} não existe na receita {receita['id']} ({', '.join(defs)}).")
        d = defs[e["papel"]]
        rotulo += f" ({e['papel']})"
        if e.get("foto"):
            fontes = [_foto(e["foto"], p)]
        else:
            ids = e.get("tomadas") or ([e["tomada"]] if e.get("tomada") else [])
            if not ids:
                raise ErroPlano(f"{rotulo}: falta 'tomada' (ex.: \"T03\", do bruto.json) ou 'foto'.")
            fontes = [_fonte(bruto, x, arquivos) for x in ids]
        comp = d.get("composicao")
        if comp:
            q_min, q_max = (comps.get(comp) or {}).get("quadros") or [1, len(fontes)]
            if len(fontes) < q_min:
                avisos.append(f"{rotulo}: a composição {comp} pede {q_min} tomada(s) em 'tomadas'; veio {len(fontes)}.")
            fontes = fontes[:q_max]
        elif len(fontes) > 1:
            # câmera na mão/tremida: o detector de cenas parte um plano em várias tomadas seguidas do mesmo
            # arquivo; "tomadas": ["T03", "T04"] junta de volta num trecho só
            seguidas = all(f["tipo"] == "video" and f["arquivo"] == fontes[0]["arquivo"]
                           and abs(f["ini"] - g["fim"]) <= tol for g, f in zip(fontes, fontes[1:]))
            if seguidas:
                fontes = [{**fontes[0], "fim": fontes[-1]["fim"]}]
            else:
                avisos.append(f"{rotulo}: só a primeira tomada ({fontes[0]['tomada']}) entra; o bloco não é composição "
                              "e as tomadas não são seguidas no mesmo arquivo.")
                fontes = fontes[:1]
        f0 = fontes[0]
        ini, fim = _num(e.get("ini_s"), f"{rotulo}: ini_s"), _num(e.get("fim_s"), f"{rotulo}: fim_s")
        if f0["tipo"] == "video":
            onde = f"{f0['tomada']} vai de {_n(f0['ini'], 2)} a {_n(f0['fim'], 2)} s no arquivo {f0['arquivo']}"
            for nome, v in (("ini_s", ini), ("fim_s", fim)):
                if v is not None and not f0["ini"] - tol <= v <= f0["fim"] + tol:
                    raise ErroPlano(f"{rotulo}: {nome} {_n(v, 2)} fora da tomada ({onde}; os tempos são do arquivo).")
            ini = None if ini is None else min(max(ini, f0["ini"]), f0["fim"])
            fim = None if fim is None else min(max(fim, f0["ini"]), f0["fim"])
            if ini is not None and fim is not None and fim <= ini:
                raise ErroPlano(f"{rotulo}: fim_s tem que ser maior que ini_s.")
        vel = _num(e.get("velocidade", d.get("velocidade", 1.0)), f"{rotulo}: velocidade")
        if vel is None or vel <= 0:
            raise ErroPlano(f"{rotulo}: velocidade tem que ser > 0.")
        y = _num(e.get("y"), f"{rotulo}: y")
        congelar = bool(d.get("congelar") or e.get("congelar"))
        if congelar and ini is None and f0["tipo"] == "video":
            ini = (f0["ini"] + f0["fim"]) / 2
            avisos.append(f"{rotulo}: sem ini_s para o quadro congelado; usei o meio de {f0['tomada']} "
                          f"({_n(ini, 2)} s). Passe ini_s com o quadro mais nítido e no melhor ângulo.")
        blocos.append({
            "i": i, "papel": e["papel"], "def": d, "escolha": e, "fontes": fontes, "vel": vel, "y": y,
            "ini_fixo": ini is not None, "fim_fixo": fim is not None,
            "a": f0["ini"] if ini is None else ini, "b": f0["fim"] if fim is None else fim,
            "foto": f0["tipo"] == "foto", "congelar": congelar,
            "destaque": bool(e.get("destaque")),
        })
    return blocos


def _conferir_estrutura(blocos: list[dict], receita: dict, avisos: list[str]) -> None:
    ordem = [d["papel"] for d in receita["estrutura"]]
    contagem = Counter(b["papel"] for b in blocos)
    for d in receita["estrutura"]:
        n = contagem.get(d["papel"], 0)
        lo, hi = d.get("repete") or [1, 1]
        if n < lo:
            avisos.append(f"Faltou o bloco '{d['papel']}' da receita ({n} de {lo}): {d['tomada_sugerida']}.")
        elif n > hi:
            avisos.append(f"'{d['papel']}' aparece {n} vezes; a receita prevê até {hi}.")
    posicoes = [ordem.index(b["papel"]) for b in blocos]
    if posicoes != sorted(posicoes):
        avisos.append("A ordem dos blocos difere da receita (" + " → ".join(ordem) + ").")


# ---------------------------------------------------------------- conteúdo dos textos

def _conteudos(blocos: list[dict], receita: dict, escolhas: dict, avisos: list[str]) -> None:
    """Define ``b["textos"] = [(papel, texto)]`` de cada bloco (sem posição nem tempo)."""
    textos = receita["textos"]
    preco = escolhas.get("preco")
    texto_preco = texto_parcelas = None
    if preco not in (None, ""):
        try:
            texto_preco, texto_parcelas = formatar_preco(preco), parcelas(preco)
        except ValueError as e:
            avisos.append(f"{e}: o preço ficou fora do vídeo.")
    contadores = [b for b in blocos if "contador" in _papeis_texto(b["def"])]
    avisou_preco = False
    for b in blocos:
        papeis = _papeis_texto(b["def"])
        e = b["escolha"]
        dados = dict(e.get("textos") or {})
        if e.get("texto") not in (None, "") and papeis:
            alvo = papeis[0]
            if alvo in _AUTOMATICOS:
                avisos.append(f"bloco {b['i'] + 1} ({b['papel']}): o preço vem de escolhas.preco; o texto {e['texto']!r} "
                              "foi ignorado.")
            else:
                dados.setdefault(alvo, e["texto"])
        itens = []
        for papel in papeis:
            t = textos[papel]
            if papel == "preco":
                valor = texto_preco
            elif papel == "parcelas":
                valor = texto_parcelas
            elif papel == "contador":
                n = contadores.index(b) + 1
                valor = dados.get(papel) or str(t.get("formato") or "{n}/{total}").format(n=n, total=len(contadores))
            elif papel == "cta":
                valor = dados.get(papel) or escolhas.get("cta") or t.get("padrao")
            else:
                valor = dados.get(papel) or t.get("padrao")
            if papel in _AUTOMATICOS and valor is None and not avisou_preco:
                avisou_preco = True
                if escolhas.get("sku"):
                    avisos.append(f"Sem preço para o SKU {escolhas['sku']}: a IA consulta o estoque/cadastro "
                                  "(stories-estoque) e passa escolhas.preco; o bloco de preço ficou sem texto.")
                else:
                    avisos.append("Sem preço nas escolhas (escolhas.preco): o bloco de preço ficou sem texto.")
            if valor not in (None, ""):
                itens.append((papel, str(valor).strip()))
            elif papel not in _AUTOMATICOS and papel != "gancho" and not t.get("opcional"):
                avisos.append(f"bloco {b['i'] + 1} ({b['papel']}): sem texto para '{papel}' (passar em 'texto' ou "
                              f"'textos'); o bloco ficou sem esse texto.")
        b["textos"] = itens


def _min_texto_bloco(b: dict, receita: dict) -> float:
    """Tempo que os textos do bloco pedem a partir do início dele (para o último bloco caber)."""
    rt = _r("plano_texto")
    maior = 0.0
    for papel, texto in b.get("textos") or []:
        t = receita["textos"][papel]
        atraso = 0.0 if papel == "gancho" else float(t.get("atraso_s") or 0)
        if papel in rt["papeis_sem_tempo_minimo"]:
            precisa = float(t.get("min_s") or 0)
        else:
            precisa = max(float(t.get("min_s") or 0), receitas.tempo_minimo_texto(texto))
        maior = max(maior, atraso + precisa)
    return maior


# ---------------------------------------------------------------- fala, jump cut e durações

def _pecas_fala(b: dict, palavras_: list[dict], cfg_rec: dict) -> list[tuple[float, float]]:
    """Trechos (tempo do arquivo) sem os silêncios longos: jump cut (§3 Fala, #15)."""
    a, bb = b["a"], b["b"]
    margem = float(cfg_rec["jump_cut_margem_s"])
    minimo = float(cfg_rec["jump_cut_silencio_min_s"])
    ditas = _no_trecho(palavras_, a, bb)
    # pausas: silêncios do ffmpeg e, com transcrição, os buracos entre palavras (com ruído de fundo o
    # silencedetect não acha a pausa, mas a transcrição acha)
    pausas = [(float(s["ini_s"]), float(s["fim_s"])) for s in b["fontes"][0]["silencios"]]
    pausas += [(float(w0["fim_s"]), float(w1["ini_s"])) for w0, w1 in zip(ditas, ditas[1:])]
    # palavra dita nunca é cortada (palavra baixa no fim da frase cai abaixo do limiar do silencedetect)
    protegidas = [(float(w["ini_s"]) - margem, float(w["fim_s"]) + margem) for w in ditas]
    cortes = []
    for p0, p1 in pausas:
        if p1 - p0 < minimo:
            continue
        trechos = [(p0 + margem, p1 - margem)]
        for w0, w1 in protegidas:
            trechos = [x for t0, t1 in trechos
                       for x in ((t0, min(t1, w0)), (max(t0, w1), t1)) if x[1] > x[0]]
        for s0, s1 in trechos:
            if s1 - s0 >= minimo - 2 * margem and s1 > a and s0 < bb:
                cortes.append((max(s0, a), min(s1, bb)))
    pecas, cursor = [], a
    for s0, s1 in sorted(cortes):
        if s0 > cursor:
            pecas.append((cursor, s0))
        cursor = max(cursor, s1)
    if bb > cursor:
        pecas.append((cursor, bb))
    parte_min = float(cfg_rec["jump_cut_parte_min_s"])
    return [(x, y) for x, y in pecas if y - x >= parte_min or _no_trecho(palavras_, x, y)] or [(a, bb)]


def _limitar_pecas(pecas: list[tuple[float, float]], limite_fonte: float, palavras_: list[dict],
                   margem: float) -> list[tuple[float, float]]:
    """Corta as peças para somarem até ``limite_fonte`` s, terminando no fim de uma palavra quando der."""
    saida, total = [], 0.0
    for x, y in pecas:
        if total + (y - x) <= limite_fonte + _EPS:
            saida.append((x, y))
            total += y - x
            continue
        resta = limite_fonte - total
        corte = x + resta
        finais = [float(w["fim_s"]) + margem for w in _no_trecho(palavras_, x, y) if float(w["fim_s"]) + margem <= corte]
        if finais and max(finais) - x >= 0.2:
            corte = max(finais)
        if corte - x > 0.05:
            saida.append((x, corte))
        break
    return saida or [(pecas[0][0], pecas[0][0] + limite_fonte)]


def _batidas_timeline(bruto: dict, musica: dict | None, avisos: list[str], fps: float) -> tuple[list[float], float | None]:
    """Batidas no tempo da linha do tempo (a música começa em 0 s, a partir de ``fonte_ini_s``) e o período."""
    info = bruto.get("musica") or {}
    batidas = [float(x) for x in info.get("batidas_s") or []]
    if not batidas:
        return [], None
    if musica and musica.get("arquivo") and _nome(info.get("arquivo")) != _nome(musica["arquivo"]):
        avisos.append(f"As batidas do bruto.json são de {_nome(info.get('arquivo'))}, não de "
                      f"{_nome(musica['arquivo'])}: rode video-preparar --musica com a faixa escolhida.")
        return [], None
    desloc = float((musica or {}).get("ini_s") or 0.0)
    batidas = [x - desloc for x in batidas if x - desloc > 0.5 / fps]
    if len(batidas) < 2:
        return batidas, None
    periodo = 60.0 / float(info["bpm"]) if info.get("bpm") else statistics.median(
        y - x for x, y in zip(batidas, batidas[1:]))
    ultimo = batidas[-1]
    while ultimo < 600:
        ultimo += periodo
        batidas.append(ultimo)
    return batidas, periodo


def _escolher(indices: list[int], n: int | None, destaques: set[int]) -> set[int]:
    """Até ``n`` blocos de uma lista: primeiro os destacados pela IA, depois espalhados."""
    if n is None or n >= len(indices):
        return set(indices)
    escolhidos = [i for i in indices if i in destaques][:n]
    resto = [i for i in indices if i not in escolhidos]
    faltam = n - len(escolhidos)
    if faltam > 0 and resto:
        passo = len(resto) / faltam
        escolhidos += [resto[min(len(resto) - 1, int(k * passo + passo / 2))] for k in range(faltam)]
    return set(escolhidos)


def _duracoes(blocos: list[dict], receita: dict, bq: list[int], periodo_q: float | None, fps: float,
              limite_destino_q: int | None, avisos: list[str]) -> None:
    """Define ``ini_q``/``dur_q`` de cada bloco: dentro de ``dur_s``, na batida quando pede, somando a duração da receita."""
    ritmo = receita["ritmo"]
    rr = _r("plano_ritmo")
    usar_batida = bool(bq) and ritmo.get("corte_na_batida")
    for k, b in enumerate(blocos):
        d = b["def"]
        b["min_q"] = math.ceil(d["dur_s"][0] * fps - _EPS)
        b["max_q"] = math.floor(d["dur_s"][1] * fps + _EPS)
        if k == len(blocos) - 1:
            precisa = math.ceil(_min_texto_bloco(b, receita) * fps - _EPS)
            b["min_q"] = max(b["min_q"], precisa)
            b["max_q"] = max(b["max_q"], precisa)
        if b["foto"] or b["congelar"]:
            b["disp_q"] = 10 ** 9
        else:
            disp = min((f["fim"] - f["ini"]) for f in b["fontes"][1:]) if len(b["fontes"]) > 1 else math.inf
            disp = min(disp, b["b"] - b["a"])
            b["disp_q"] = max(1, math.floor(disp / b["vel"] * fps + _EPS))
        if b.get("pecas"):
            b["fixo_q"] = sum(max(1, round((y - x) / b["vel"] * fps)) for x, y in b["pecas"])
        elif b.get("fala") and not (usar_batida and not d.get("fala")):
            b["fixo_q"] = max(1, min(b["disp_q"], b["max_q"]))
        else:
            b["fixo_q"] = None
        hi = min(b["max_q"], b["disp_q"])
        if usar_batida and b["fixo_q"] is None:
            n = int(d.get("batidas") or ritmo.get("batidas_por_troca") or 1)
            alvo = round(n * periodo_q)
        else:
            alvo = hi
        b["alvo_q"] = max(1, min(max(alvo, min(b["min_q"], hi)), hi))

    def montar(alvos: list[int]) -> tuple[list[int], list[str]]:
        durs, notas, t = [], [], 0
        for b, alvo in zip(blocos, alvos):
            rot = f"bloco {b['i'] + 1} ({b['papel']})"
            if b["fixo_q"] is not None:
                dur = b["fixo_q"]
            elif usar_batida:
                lo, hi = b["min_q"], min(b["max_q"], b["disp_q"])
                cands = [x - t for x in bq if lo <= x - t <= hi]
                if not cands:
                    cands = [x - t for x in bq if 1 <= x - t <= b["disp_q"]]
                    if cands and hi >= lo:
                        notas.append(f"{rot}: nenhuma batida entre {_n(lo / fps, 2)} e {_n(hi / fps, 2)} s de bloco; "
                                     "cortei na batida mais perto, fora da faixa da receita.")
                if cands:
                    dur = min(cands, key=lambda x: (abs(x - alvo), x))
                else:
                    dur = max(1, min(alvo, b["disp_q"]))
                    notas.append(f"{rot}: a tomada é curta demais para chegar à próxima batida; corte fora da batida.")
            else:
                dur = max(1, min(alvo, b["disp_q"]))
            durs.append(dur)
            t += dur
        return durs, notas

    alvos = [b["alvo_q"] for b in blocos]
    dmin_total = math.ceil(receita["duracao_s"][0] * fps - _EPS)
    dmax_total = math.floor(receita["duracao_s"][1] * fps + _EPS)
    if limite_destino_q:
        dmax_total = min(dmax_total, limite_destino_q)
    passo = max(1, round(periodo_q)) if usar_batida else max(1, round(float(rr["passo_ajuste_s"]) * fps))
    ajustaveis = [k for k, b in enumerate(blocos) if b["fixo_q"] is None]
    contagem = Counter(blocos[k]["papel"] for k in ajustaveis)
    unicos = [[k] for k in reversed(ajustaveis) if contagem[blocos[k]["papel"]] == 1]
    papeis_rep = list(dict.fromkeys(blocos[k]["papel"] for k in reversed(ajustaveis) if contagem[blocos[k]["papel"]] > 1))
    repetidos = [[k for k in ajustaveis if blocos[k]["papel"] == p] for p in papeis_rep]
    ponteiros = {"unicos": 0, "repetidos": 0}

    def tem_folga(k: int, durs: list[int]) -> bool:
        b = blocos[k]
        hi = min(b["max_q"], b["disp_q"])
        return durs[k] + passo <= hi + (passo // 2 if usar_batida else 0)

    durs, notas = montar(alvos)
    for _ in range(2000):
        total = sum(durs)
        if total < dmin_total:
            feito = False
            for nome, grupos in (("unicos", unicos), ("repetidos", repetidos)):
                for s in range(len(grupos)):
                    g = grupos[(ponteiros[nome] + s) % len(grupos)]
                    if all(tem_folga(k, durs) for k in g):
                        for k in g:
                            alvos[k] = durs[k] + passo
                        ponteiros[nome] = (ponteiros[nome] + s + 1) % len(grupos)
                        feito = True
                        break
                if feito:
                    break
            if not feito:
                break
        elif total > dmax_total:
            folgas = [(durs[k] - blocos[k]["min_q"], k) for k in ajustaveis if durs[k] - passo >= blocos[k]["min_q"]]
            if not folgas:
                break
            k = max(folgas)[1]
            alvos[k] = durs[k] - passo
        else:
            break
        novos, notas = montar(alvos)
        if novos == durs:
            break
        durs = novos
    avisos.extend(notas)
    t = 0
    for b, dur in zip(blocos, durs):
        b["ini_q"], b["dur_q"] = t, dur
        if dur < math.ceil(b["def"]["dur_s"][0] * fps - _EPS):
            vel = f" na velocidade {_n(b['vel'], 2)}x" if b["vel"] != 1 else ""
            avisos.append(f"bloco {b['i'] + 1} ({b['papel']}) ficou com {_n(dur / fps, 2)} s{vel} e a receita pede ≥ "
                          f"{_n(b['def']['dur_s'][0], 1)} s: escolher um trecho mais longo.")
        t += dur


def _trechos_fonte(b: dict, fps: float) -> list[tuple[float, float, int]]:
    """``[(fonte_ini, fonte_fim, quadros)]`` da fonte principal do bloco depois das durações."""
    if b.get("pecas"):
        saida = []
        for x, y in b["pecas"]:
            q = max(1, round((y - x) / b["vel"] * fps))
            saida.append((x, x + q / fps * b["vel"], q))
        return saida
    comp = b["dur_q"] / fps * b["vel"]
    if b["foto"]:
        return [(0.0, b["dur_q"] / fps, b["dur_q"])]
    if b["congelar"]:
        q_fonte = 1.0 / float(b["fontes"][0].get("fps") or fps)
        return [(b["a"], b["a"] + q_fonte, b["dur_q"])]
    if b["ini_fixo"] or b.get("fala"):
        a = b["a"]
    else:
        a = b["a"] + max(0.0, (b["b"] - b["a"]) - comp) / 2
    return [(a, a + comp, b["dur_q"])]


# ---------------------------------------------------------------- montagem do plano

def _musica_escolhida(escolhas: dict, receita: dict, bruto: dict, p: dict[str, Path], avisos: list[str]) -> dict | None:
    m = escolhas.get("musica")
    info = bruto.get("musica") or {}
    if m is False:
        return None
    if m is None and not (receita["ritmo"].get("corte_na_batida") or receita["musica"]["origem"] == "faixa_guia"):
        return None
    m = dict(m) if isinstance(m, dict) else {}
    nome = m.get("arquivo") or info.get("arquivo")
    if not nome:
        return None
    caminho = None
    cand = Path(str(nome))
    if info.get("arquivo") and _nome(info["arquivo"]) == _nome(nome):
        caminho = str(info["arquivo"])
    elif cand.is_absolute() and cand.is_file():
        caminho = str(cand)
    else:
        from .bruto import pasta_musicas

        for x in (p["bruto"] / cand, pasta_musicas() / cand):
            if x.is_file():
                caminho = str(x)
                break
    if caminho is None:
        avisos.append(f"Música {nome} não encontrada (bruto do projeto ou videos\\musicas): ficou fora do plano.")
        return None
    m["arquivo"] = caminho
    m.setdefault("no_capcut", receita["musica"]["origem"] == "faixa_guia")
    return m


def _itens_video(blocos: list[dict], receita: dict, canvas: dict, bq: list[int], permitidas: set[int],
                 efeitos: list[dict], avisos: list[str]) -> list[dict]:
    """Clipes da linha do tempo (quadros inteiros). Composição ganha ``x``/``y`` absolutos (centro do clipe, px)."""
    fps = float(canvas["fps"])
    centro_x, centro_y = canvas["largura"] / 2, canvas["altura"] / 2
    m = receita["musica"]
    rm = _r("plano_musica")
    rec = _r("plano_recorte")
    comps = _c().get("composicoes") or {}
    cat = receitas.tecnicas()
    itens = []
    parte_min_q = math.ceil(float(rec["punch_in_parte_min_s"]) * fps - _EPS)
    for b in blocos:
        d = b["def"]
        efs = _efeitos_def(d)
        trechos = _trechos_fonte(b, fps)
        f0 = b["fontes"][0]
        if b["fala"]:
            vol, mudo = float(m["volume_voz_db"]), False
        elif m.get("volume_clipe_sem_fala_db") is None or b["foto"]:
            vol, mudo = float(rm["volume_mudo_db"]), True
        else:
            vol, mudo = float(m["volume_clipe_sem_fala_db"]), False
        base = {"arquivo": f0["caminho"], "arquivo_bruto": f0["arquivo"], "tomada": f0["tomada"],
                "velocidade": b["vel"], "papel": b["papel"],
                "volume_db": vol, "mudo": mudo, "faixa": 0, "bloco": b["i"], "fala": b["fala"], "tipo": f0["tipo"],
                "congelar": b["congelar"]}
        b["itens"] = []
        t = b["ini_q"]
        # jump cut (#15): escala 100%/110% alternada a cada 2–3 cortes; fala contínua mais longa que o limite
        # (§3: 4–6 s) ganha um punch-in no meio para ter troca visual sem cortar a frase
        alternar = max(1, int(rec["jump_cut_alternar_a_cada"]))
        limite_fala_q = max(1, math.floor(float(_r("plano_ritmo")["fala_troca_max_s"]) * fps + _EPS))
        escala_alt = float(rec["jump_cut_escala"])
        escala, saltos = 1.0, 0
        for k, (x, y, q) in enumerate(trechos):
            partes = math.ceil(q / limite_fala_q) if b["fala"] and 1 in permitidas and q > limite_fala_q else 1
            feito_q = 0
            for n in range(partes):
                q_n = q // partes + (1 if n < q % partes else 0)
                if n > 0:
                    escala = escala_alt if escala == 1.0 else 1.0
                elif k > 0:
                    saltos += 1
                    if b.get("pecas") and 1 in efs and 1 in permitidas and (saltos - 1) % alternar == 0:
                        escala = escala_alt if escala == 1.0 else 1.0
                x_n = x + feito_q / fps * b["vel"]
                y_n = y if n == partes - 1 else x_n + q_n / fps * b["vel"]
                item = {**base, "fonte_ini_s": round(x_n, 4), "fonte_fim_s": round(y_n, 4), "ini_q": t, "dur_q": q_n,
                        "escala": escala}
                b["itens"].append(item)
                if escala != 1.0:
                    efeitos.append({"tecnica": 1, "ini_q": t, "dur_q": q_n, "bloco": b["i"], "item": item,
                                    "parametros": {"escala": escala}})
                t += q_n
                feito_q += q_n
        # punch-in (#1): corta na batida (ou no meio) e o 2º trecho entra a 110–120%
        if (1 in efs and 1 in permitidas and not b.get("pecas") and b.get("punch_in")
                and len(b["itens"]) == 1 and not b["congelar"]):
            item = b["itens"][0]
            lo, hi = item["ini_q"] + parte_min_q, item["ini_q"] + item["dur_q"] - parte_min_q
            if hi >= lo:
                meio = item["ini_q"] + item["dur_q"] / 2
                cands = [x for x in bq if lo <= x <= hi] if bq else []
                corte = min(cands, key=lambda x: abs(x - meio)) if cands else round(meio)
                q1 = corte - item["ini_q"]
                corte_fonte = item["fonte_ini_s"] + q1 / fps * b["vel"]
                if f0["tipo"] == "foto":
                    corte_fonte = q1 / fps
                segundo = {**item, "fonte_ini_s": round(corte_fonte, 4), "ini_q": corte, "dur_q": item["dur_q"] - q1,
                           "escala": float((cat[1].get("parametros") or {}).get("escala", rec["punch_in_escala"]))}
                item["fonte_fim_s"], item["dur_q"] = round(corte_fonte, 4), q1
                b["itens"].append(segundo)
                efeitos.append({"tecnica": 1, "ini_q": corte, "dur_q": segundo["dur_q"], "bloco": b["i"],
                                "item": segundo, "parametros": {"escala": segundo["escala"]}})
        # composição (grade 2×2, clone, game): tomadas empilhadas em faixas acima
        comp = d.get("composicao")
        if comp:
            cfg = comps.get(comp) or {}
            posicoes = cfg.get("posicoes_px") or []
            principal = b["itens"][0]
            if posicoes:
                principal["x"], principal["y"] = centro_x + posicoes[0][0], centro_y + posicoes[0][1]
            principal["escala"] = float(cfg.get("escala", 1.0))
            dur_fonte = principal["dur_q"] / fps * b["vel"]
            for n, f in enumerate(b["fontes"][1:], start=1):
                sobra = max(0.0, (f["fim"] - f["ini"]) - dur_fonte)
                a = f["ini"] + sobra / 2
                pos = posicoes[n] if n < len(posicoes) else [0, 0]
                b["itens"].append({**principal, "arquivo": f["caminho"], "arquivo_bruto": f["arquivo"],
                                   "tomada": f["tomada"], "fonte_ini_s": round(a, 4),
                                   "fonte_fim_s": round(a + dur_fonte, 4), "faixa": n,
                                   "x": centro_x + pos[0], "y": centro_y + pos[1],
                                   "volume_db": float(rm["volume_mudo_db"]), "mudo": True, "fala": False})
        if 9 in efs or b["vel"] < 1:
            fps_min = float((cat[9].get("parametros") or {}).get("fps_min_bruto", 50))
            if f0.get("fps") and float(f0["fps"]) < fps_min:
                avisos.append(f"bloco {b['i'] + 1} ({b['papel']}): câmera lenta em {f0['tomada']} gravada a "
                              f"{_n(float(f0['fps']), 0)} fps; fica travada (gravar a 60 fps, §2/§4.2 #9).")
        itens.extend(b["itens"])
    itens.sort(key=lambda it: (it["ini_q"], it["faixa"]))
    return itens


def _textos(blocos: list[dict], receita: dict, total_q: int, fps: float) -> list[dict]:
    rt = _r("plano_texto")
    saida = []
    for b in blocos:
        if not b.get("textos"):
            continue
        fim_bloco = b["ini_q"] + b["dur_q"]
        delta = None
        for papel, texto in b["textos"]:
            t = receita["textos"][papel]
            meio = (t["y"][0] + t["y"][1]) / 2
            if delta is None:
                delta = (b["y"] - meio) if b.get("y") is not None else 0.0
            x = float(t.get("x", rt["x_padrao"]))
            conteudo, tam = ajustar_texto(texto, t["tamanho_px"], t.get("tamanho_min_px", t["tamanho_px"]), x)
            atraso = 0.0 if papel == "gancho" else float(t.get("atraso_s") or 0)
            ini_q = 0 if papel == "gancho" and b["ini_q"] == 0 else b["ini_q"] + round(atraso * fps)
            item = {"texto": conteudo, "papel": papel, "estilo": t.get("estilo", papel), "x": x, "y": round(meio + delta),
                    "tamanho_px": tam, "min_s": float(t.get("min_s") or 0)}
            precisa = math.ceil(tempo_minimo(item) * fps - _EPS)
            fim_q = fim_bloco if papel in rt["papeis_sem_tempo_minimo"] else max(fim_bloco, ini_q + precisa)
            animacao = t.get("animacao", "nenhuma")
            entrada = min(float(rt["animacoes_s"].get(animacao, 0.0)), float(t.get("entra_max_s", 0.5)))
            saida.append({**item, "ini_q": ini_q, "fim_q": min(fim_q, total_q), "animacao": animacao,
                          "entrada_s": entrada, "bloco": b["i"]})
    # o mesmo papel não fica em cima de si mesmo (contador que muda a cada look)
    for papel in {x["papel"] for x in saida}:
        mesmos = sorted((x for x in saida if x["papel"] == papel), key=lambda x: x["ini_q"])
        for a, b in zip(mesmos, mesmos[1:]):
            a["fim_q"] = min(a["fim_q"], b["ini_q"])
    return saida


def _legendas(video: list[dict], receita: dict, escolhas: dict, palavras: dict[str, list[dict]], total_q: int,
              fps: float, avisos: list[str]) -> tuple[list[dict], list[tuple[float, float]]]:
    """Legendas retimadas para a linha do tempo (só as palavras dos trechos usados) + trechos de fala (s)."""
    ligado = escolhas.get("legendas")
    ligado = receita["legendas"]["ligado"] if ligado is None else bool(ligado)
    retimadas = []
    for it in video:
        if it["faixa"] != 0 or it["mudo"] or it["tipo"] != "video":
            continue
        lista = palavras.get(it.get("arquivo_bruto")) or palavras.get(_nome(it["arquivo"])) or []
        ini_s = float(it["ini_s"])
        for w in _no_trecho(lista, it["fonte_ini_s"], it["fonte_fim_s"]):
            a = ini_s + (float(w["ini_s"]) - it["fonte_ini_s"]) / it["velocidade"]
            b = ini_s + (float(w["fim_s"]) - it["fonte_ini_s"]) / it["velocidade"]
            retimadas.append({"ini_s": round(a, 3), "fim_s": round(min(b, ini_s + float(it["dur_s"])), 3),
                              "texto": w["texto"]})
    retimadas.sort(key=lambda w: w["ini_s"])
    falas = []
    for w in retimadas:
        if falas and w["ini_s"] - falas[-1][1] <= float(_r("plano_musica")["ducking_juntar_s"]):
            falas[-1] = (falas[-1][0], max(falas[-1][1], w["fim_s"]))
        else:
            falas.append((w["ini_s"], w["fim_s"]))
    if not ligado:
        return [], falas
    tem_fala = any(it["fala"] for it in video)
    if not retimadas:
        if tem_fala:
            avisos.append("Blocos com fala sem transcrição: gerar as legendas no CapCut (Legendas > Legendas automáticas) "
                          "e revisar nome da peça, preço e tamanhos.")
        return [], falas
    lg = receita["legendas"]
    rl = _r("plano_legendas")
    y = round(sum(lg.get("y") or rl["y"]) / 2)
    x = float(_r("plano_texto")["x_padrao"])
    tam = float(lg.get("tamanho_px") or rl["tamanho_px"][0])
    saida = []
    total_s = total_q / fps
    for bloco in transcricao.blocos_legenda(retimadas):
        ini = float(bloco["ini_s"])
        fim = min(float(bloco["fim_s"]), total_s)
        if fim - ini <= 0.01:
            continue
        texto = _normalizar_precos(bloco["texto"].replace("\n", " "))
        texto, tam_bloco = ajustar_texto(texto, tam, rl["tamanho_px"][0], x, max_linhas=int(_c().get("legenda_max_linhas", 2)))
        saida.append({"texto": texto, "ini_s": round(ini, 3), "dur_s": round(fim - ini, 3), "x": x, "y": y,
                      "tamanho_px": tam_bloco, "estilo": lg.get("estilo", "legenda")})
    return saida, falas


def _chaves_volume(falas: list[tuple[float, float]], com: float, sem: float, total: float) -> list[dict]:
    """Ducking (§7): 4 pontos por fala, rampas de 0,3–0,5 s."""
    rampa = float(_r("plano_musica")["ducking_rampa_s"])
    chaves = [{"t_s": 0.0, "volume_db": sem}]
    for a, b in falas:
        pontos = [(max(0.0, a - rampa), sem), (a, com), (b, com), (min(total, b + rampa), sem)]
        for t, v in pontos:
            if chaves and t <= chaves[-1]["t_s"] + _EPS:
                if v < chaves[-1]["volume_db"]:
                    chaves[-1] = {"t_s": chaves[-1]["t_s"], "volume_db": v}
                continue
            chaves.append({"t_s": round(t, 3), "volume_db": v})
    return chaves if len(chaves) > 1 else []


def _arquivo_som(nome: str) -> str | None:
    c = _r("plano_efeitos_sonoros")
    pasta = config.pastas().videos / c["subpasta"]
    for ext in c["extensoes"]:
        x = pasta / f"{nome}{ext}"
        if x.is_file():
            return str(x)
    return None


def _efeitos_e_sons(blocos: list[dict], fps: float, bq: list[int], total_q: int, orc: dict,
                    permitidas: set[int], efeitos: list[dict], textos: list[dict], avisos: list[str]) -> list[dict]:
    """Efeitos por bloco, reforços nos cortes (§4.1 regra 2), flashes (≤ 3/s) e efeitos sonoros (orçamento e §7)."""
    cat = receitas.tecnicas()
    rec = _r("plano_recorte")
    rs = _r("plano_efeitos_sonoros")
    reforcos = _r("reforcos")
    flash_q = max(1, int(rec["flash_quadros"]))
    fora: set[int] = set()
    flashes, sons = [], []
    por_papel: dict[str, list[int]] = {}
    for b in blocos:
        por_papel.setdefault(b["papel"], []).append(b["i"])
    destaques = {b["i"] for b in blocos if b["destaque"]}
    alvo_ef, alvo_ref, alvo_som = {}, {}, {}
    for papel, idx in por_papel.items():
        d = blocos[idx[0]]["def"]
        alvo_ef[papel] = _escolher(idx, d.get("efeito_max"), destaques)
        alvo_ref[papel] = _escolher(idx, d.get("reforco_max"), destaques)
        alvo_som[papel] = _escolher(idx, d.get("som_max"), destaques)
    for b in blocos:
        d = b["def"]
        principal = b["itens"][0]
        fim_q = b["ini_q"] + b["dur_q"]
        tecnicas_bloco = list(_efeitos_def(d))
        if b["vel"] < 1 and 9 not in tecnicas_bloco:
            tecnicas_bloco.append(9)
        if b["vel"] >= 4 and 12 not in tecnicas_bloco:
            tecnicas_bloco.append(12)
        for n in tecnicas_bloco:
            info = cat.get(n) or {}
            if info.get("tipo") == "efeito" and n not in permitidas:
                fora.add(n)
                continue
            if info.get("tipo") == "efeito" and b["i"] not in alvo_ef[b["papel"]]:
                continue
            if n == 1:
                continue  # o punch-in já entrou no corte do clipe
            if n == 31:
                passo = max(1, round(float(rec["strobe_intervalo_s"]) * fps))
                tempos = [x for x in bq if b["ini_q"] <= x < fim_q - flash_q] if bq else list(range(b["ini_q"], fim_q - flash_q, passo))
                for x in tempos[: int(rec["strobe_max"])]:
                    flashes.append({"tecnica": 31, "ini_q": x, "dur_q": flash_q, "bloco": b["i"], "item": principal})
                continue
            parametros = dict(info.get("parametros") or {})
            if info.get("tipo") == "velocidade":
                parametros["velocidade"] = b["vel"]
            efeitos.append({"tecnica": n, "ini_q": b["ini_q"], "dur_q": b["dur_q"], "bloco": b["i"], "item": principal,
                            "parametros": parametros})
        # reforço no corte de entrada do bloco (um só: flash, tremor ou whoosh)
        reforco = d.get("reforco")
        if reforco and b["ini_q"] > 0 and b["i"] in alvo_ref[b["papel"]]:
            n = int(reforcos[reforco])
            if n == 57:
                sons.append({"som": reforco, "t_q": b["ini_q"], "prioridade": 1, "bloco": b["i"], "item": principal})
            elif n in permitidas:
                dur = flash_q if n == 31 else max(1, int(rec["tremor_quadros"]))
                alvo = flashes if n == 31 else efeitos
                alvo.append({"tecnica": n, "ini_q": b["ini_q"], "dur_q": dur, "bloco": b["i"], "item": principal,
                             "parametros": dict((cat.get(n) or {}).get("parametros") or {})})
            else:
                fora.add(n)
        if b["i"] in alvo_som[b["papel"]]:
            for som in _sons_def(d):
                t = b["ini_q"]
                if som == "pop":
                    tx = [x for x in textos if x["bloco"] == b["i"] and x["papel"] != "gancho"]
                    if tx:
                        t = min(x["ini_q"] for x in tx)
                sons.append({"som": som, "t_q": t, "prioridade": 0, "bloco": b["i"], "item": principal})
    for n in sorted(fora):
        avisos.append(f"#{n} {cat[n]['nome']} ficou de fora: passa do orçamento de efeitos de "
                      f"{_n(total_q / fps)} s (§4.1).")
    # flashes: no máximo N por segundo (fotossensibilidade)
    max_flash = int(_r("plano_ritmo")["flashes_max_por_s"])
    mantidos = []
    for f in sorted(flashes, key=lambda f: f["ini_q"]):
        if sum(1 for m in mantidos if f["ini_q"] - m["ini_q"] < fps) < max_flash:
            mantidos.append(f)
    if len(mantidos) < len(flashes):
        avisos.append(f"{len(flashes) - len(mantidos)} flash(es) tirado(s): no máximo {max_flash} por segundo (§4.1).")
    for f in mantidos:
        f["parametros"] = dict((cat[31].get("parametros") or {}))
        efeitos.append(f)
    # efeitos sonoros: um a cada 2–3 s (§7) e dentro do orçamento (§4.1)
    intervalo_q = float(rs["intervalo_min_s"]) * fps
    limite = int(orc["efeitos_sonoros"][1])
    escolhidos = []
    for s in sorted(sons, key=lambda s: (s["prioridade"], s["t_q"])):
        if len(escolhidos) < limite and all(abs(s["t_q"] - x["t_q"]) >= intervalo_q - _EPS for x in escolhidos):
            escolhidos.append(s)
    if len(escolhidos) < len(sons):
        avisos.append(f"{len(sons) - len(escolhidos)} efeito(s) sonoro(s) tirado(s): no máximo um a cada "
                      f"{_n(float(rs['intervalo_min_s']))} s e {limite} no vídeo (§4.1/§7).")
    audio_sons, faltando = [], set()
    for s in sorted(escolhidos, key=lambda s: s["t_q"]):
        adiantar = round(float((rs.get("adiantar_s") or {}).get(s["som"], 0.0)) * fps)
        ini_q = max(0, s["t_q"] - adiantar)
        dur_q = max(1, min(round(float((rs.get("duracao_s") or {}).get(s["som"], 0.5)) * fps), total_q - ini_q))
        arquivo = _arquivo_som(s["som"])
        efeitos.append({"tecnica": 57, "som": s["som"], "ini_q": ini_q, "dur_q": dur_q, "bloco": s["bloco"],
                        "item": s["item"], "parametros": {"arquivo": arquivo}})
        if arquivo:
            audio_sons.append({"arquivo": arquivo, "ini_s": _s(ini_q, fps), "dur_s": _s(dur_q, fps), "fonte_ini_s": 0.0,
                               "volume_db": float(rs["volume_db"]), "papel": "efeito_sonoro", "som": s["som"], "exportar": True})
        else:
            faltando.add(s["som"])
    if faltando:
        pasta = config.pastas().videos / rs["subpasta"]
        avisos.append(f"Efeitos sonoros sem arquivo ({', '.join(sorted(faltando))}): pôr {', '.join(sorted(faltando))}"
                      f".mp3 com licença comercial (Pixabay, Meta Sound Collection) em {pasta}, ou usar SFX com a marca "
                      "\"comercial\" no CapCut (§7). Ficaram marcados no plano.")
    return audio_sons


def _transicoes(video: list[dict], blocos: list[dict], receita: dict, orc: dict, avisos: list[str]) -> list[dict]:
    """Uma transição por corte da faixa principal: corte seco, salvo a que a receita pede dentro do orçamento (§4.1)."""
    tipos = _r("tipos_transicao")
    principais = [(n, it) for n, it in enumerate(video) if it["faixa"] == 0]
    primeiro_do_bloco = {id(b["itens"][0]): b for b in blocos}
    limite = min(int(receita["transicoes"].get("max", 0)), int(orc["transicoes"][1]))
    usadas, contagem, saida = 0, Counter(), []
    for (na, _a), (nb, b_it) in zip(principais, principais[1:]):
        bloco = primeiro_do_bloco.get(id(b_it))
        tipo = "corte_seco"
        tecnica = None
        if bloco is not None:
            tecnica = bloco["def"].get("troca")
            pedido = bloco["def"].get("transicao") or "corte_seco"
            if pedido != "corte_seco":
                maximo = tipos[pedido].get("max_por_video")
                if usadas < limite and (maximo is None or contagem[pedido] < maximo):
                    tipo = pedido
                    usadas += 1
                    contagem[pedido] += 1
                else:
                    avisos.append(f"Transição {pedido} antes do bloco {bloco['i'] + 1} virou corte seco "
                                  f"(orçamento: {limite} transição(ões), §4.1).")
        faixa = tipos[tipo]["dur_s"]
        dur = round((faixa[0] + faixa[1]) / 2, 3)
        item = {"entre": [na, nb], "tipo": tipo, "dur_s": dur}
        if tipos[tipo].get("tecnica"):
            item["tecnica"] = tipos[tipo]["tecnica"]
        elif tecnica:
            item["tecnica"] = tecnica
        saida.append(item)
    return saida


def _regras(receita: dict) -> dict:
    return {"duracao_s": receita["duracao_s"], "corte_na_batida": bool(receita["ritmo"].get("corte_na_batida")),
            "troca_s": receita["ritmo"].get("troca_s"), "transicoes_max": receita["transicoes"].get("max"),
            "assinatura": receita["efeitos"].get("assinatura"), "apoio": receita["efeitos"].get("apoio") or [],
            "estetica": receita["estetica"], "objetivo": receita["objetivo"]}


def _acabamento(plano: dict, receita: dict) -> list[str]:
    cat = receitas.tecnicas()
    comps = _c().get("composicoes") or {}
    linhas = []
    vistos = set()
    for ef in plano["efeitos"]:
        if ef.get("manual") and (ef["tecnica"], ef["ini_s"]) not in vistos:
            vistos.add((ef["tecnica"], ef["ini_s"]))
            nome = ef.get("som") or cat[ef["tecnica"]]["nome"]
            linhas.append(f"#{ef['tecnica']} {nome} em {_n(ef['ini_s'])}–{_n(ef['ini_s'] + ef['dur_s'])} s "
                          "(como fazer: guia §4.2).")
    for d in receita["estrutura"]:
        if d.get("composicao") and (comps.get(d["composicao"]) or {}).get("manual"):
            linhas.append(f"{d['papel']}: {comps[d['composicao']]['manual']}.")
    cor = receita["cor"]
    linhas.append(f"Cor: look {cor['look']} (§6), filtros até {int(float(cor.get('filtro_max', 0.4)) * 100)}%; "
                  "comparar a cor da peça com a peça real e manter um plano com a cor real.")
    if any(a.get("papel") == "guia" for a in plano["audio"]):
        linhas.append("Faixa-guia: desligar (V) antes de exportar; a música entra pelo Instagram (§7).")
    if receita.get("loop"):
        linhas.append("Loop (#13): conferir se o último quadro emenda no primeiro.")
    if plano["legendas"]:
        linhas.append("Revisar as legendas: acentos, nome da peça, preço, tamanhos e cor exata (§5).")
    return linhas


def planejar(projeto: str, receita_id: str, escolhas: dict) -> dict:
    """Monta e grava ``trabalho/<projeto>/plano.json`` (formato no contrato do Entregável B). Violações ficam em
    ``plano["violacoes"]`` (quem chama decide bloquear); erro de entrada levanta ``ErroPlano``."""
    if not isinstance(escolhas, dict):
        raise ErroPlano("escolhas tem que ser um objeto JSON.")
    receita = receitas.carregar(receita_id)
    erros = receitas.validar(receita)
    if erros:
        raise ErroPlano(f"Receita {receita['id']} inválida: " + "; ".join(erros))
    bruto, p = carregar_bruto(projeto)
    destino = escolhas.get("destino") or receita["destinos"][0]
    if destino not in receita["destinos"]:
        raise ErroPlano(f"Destino {destino!r} fora da receita {receita['id']} ({', '.join(receita['destinos'])}).")
    preset = (config.carregar("exportacao").get("presets") or {}).get(destino) or {}
    fps = float(preset.get("fps") or 30)
    canvas = {"largura": int(preset.get("largura") or 1080), "altura": int(preset.get("altura") or 1920), "fps": fps}
    avisos: list[str] = []
    blocos = _resolver_blocos(escolhas, receita, bruto, p, avisos)
    _conferir_estrutura(blocos, receita, avisos)
    _conteudos(blocos, receita, escolhas, avisos)
    palavras = _palavras(p, bruto)
    musica = _musica_escolhida(escolhas, receita, bruto, p, avisos)
    batidas, periodo = _batidas_timeline(bruto, musica, avisos, fps) if receita["ritmo"].get("corte_na_batida") else ([], None)
    if receita["ritmo"].get("corte_na_batida") and not batidas:
        avisos.append("A receita corta na batida, mas não há batidas marcadas: rode video-preparar --musica <faixa-guia> "
                      "ou marque no CapCut (M no ritmo).")
    bq = sorted({round(x * fps) for x in batidas}) if periodo else []
    faixa_bpm = receita["ritmo"].get("bpm")
    if periodo and faixa_bpm and not faixa_bpm[0] - 1 <= 60.0 / periodo <= faixa_bpm[1] + 1:
        avisos.append(f"A faixa-guia está a {_n(60.0 / periodo, 0)} BPM e a receita pede {faixa_bpm[0]}–{faixa_bpm[1]} BPM "
                      "(§3): os cortes na batida ficam mais rápidos/lentos que o previsto.")
    rec = _r("plano_recorte")
    margem = float(rec["jump_cut_margem_s"])
    for b in blocos:
        f0 = b["fontes"][0]
        lista = palavras.get(f0["arquivo"]) or []
        ditas = [] if b["foto"] or b["congelar"] else _no_trecho(lista, b["a"], b["b"])
        sem_transcricao = f0["arquivo"] not in palavras
        falado = bool(b["def"].get("fala"))
        b["fala"] = bool(ditas) or (falado and sem_transcricao and f0["fala_arquivo"])
        if b["fala"] and not falado and b["vel"] != 1:
            # voz em câmera lenta/timelapse não serve como fala: o bloco é visual (som tratado como sem fala)
            b["fala"] = False
        if not b["fala"]:
            continue
        if bq and not falado:
            # fala de passagem ("vai!", "pula") num bloco que corta na batida: o som fica, a batida manda no corte
            continue
        if ditas and not b["ini_fixo"]:
            b["a"] = max(b["a"], float(ditas[0]["ini_s"]) - margem)
        if ditas and not b["fim_fixo"]:
            b["b"] = min(b["b"], float(ditas[-1]["fim_s"]) + margem)
        pecas = _pecas_fala(b, lista, rec) if 15 in _efeitos_def(b["def"]) else [(b["a"], b["b"])]
        limite = b["def"]["dur_s"][1] * b["vel"]
        b["pecas"] = _limitar_pecas(pecas, limite, lista, margem)
        cortadas = [w["texto"] for w in ditas if not any(_no_trecho([w], x, y) for x, y in b["pecas"])]
        if cortadas:
            avisos.append(f"bloco {b['i'] + 1} ({b['papel']}): a fala passa de {_n(b['def']['dur_s'][1], 1)} s e foi "
                          f"cortada; ficou de fora: \"{' '.join(cortadas[:12])}{' …' if len(cortadas) > 12 else ''}\". "
                          "Escolher um trecho com fim_s numa pausa, ou uma fala mais curta.")
    limite_destino_q = math.floor(float(preset["duracao_max_s"]) * fps + _EPS) if preset.get("duracao_max_s") else None
    _duracoes(blocos, receita, bq, periodo * fps if periodo else None, fps, limite_destino_q, avisos)
    total_q = sum(b["dur_q"] for b in blocos)
    orc = receitas.orcamento(total_q / fps)
    apoio = list(dict.fromkeys(receita["efeitos"].get("apoio") or []))
    permitidas = set(apoio[: int(orc["apoio"][1])])
    if receita["efeitos"].get("assinatura") is not None:
        permitidas.add(receita["efeitos"]["assinatura"])
    efeitos_q: list[dict] = []
    # quais blocos recebem os efeitos (efeito_max) — o punch-in é aplicado na montagem dos clipes
    por_papel: dict[str, list[int]] = {}
    for b in blocos:
        por_papel.setdefault(b["papel"], []).append(b["i"])
    destaques = {b["i"] for b in blocos if b["destaque"]}
    for papel, idx in por_papel.items():
        alvo = _escolher(idx, blocos[idx[0]]["def"].get("efeito_max"), destaques)
        for i in idx:
            blocos[i]["punch_in"] = i in alvo
    itens = _itens_video(blocos, receita, canvas, bq, permitidas, efeitos_q, avisos)
    textos_q = _textos(blocos, receita, total_q, fps)
    audio_sons = _efeitos_e_sons(blocos, fps, bq, total_q, orc, permitidas, efeitos_q, textos_q, avisos)

    video = []
    for it in itens:
        v = {k: val for k, val in it.items() if k not in ("ini_q", "dur_q")}
        v["ini_s"], v["dur_s"] = _s(it["ini_q"], fps), _s(it["dur_q"], fps)
        video.append(v)
    ordem = {id(it): n for n, it in enumerate(itens)}
    cat = receitas.tecnicas()
    assinatura = receita["efeitos"].get("assinatura")
    efeitos = []
    for ef in sorted(efeitos_q, key=lambda e: (e["ini_q"], e["tecnica"])):
        info = cat.get(ef["tecnica"]) or {}
        tipo = info.get("tipo")
        categoria = ("assinatura" if ef["tecnica"] == assinatura else "apoio") if tipo == "efeito" else tipo
        item = {"tecnica": ef["tecnica"], "nome": info.get("nome"), "ini_s": _s(ef["ini_q"], fps),
                "dur_s": _s(ef["dur_q"], fps), "clipe": ordem.get(id(ef["item"])), "categoria": categoria,
                "manual": bool(info.get("manual")) or (ef["tecnica"] == 57 and not (ef.get("parametros") or {}).get("arquivo")),
                "parametros": ef.get("parametros") or {}}
        if ef.get("som"):
            item["som"] = ef["som"]
        efeitos.append(item)
    textos = [{"texto": t["texto"], "ini_s": _s(t["ini_q"], fps), "dur_s": _s(t["fim_q"] - t["ini_q"], fps), "x": t["x"],
               "y": t["y"], "tamanho_px": t["tamanho_px"], "estilo": t["estilo"], "papel": t["papel"],
               "animacao": t["animacao"], "entrada_s": t["entrada_s"], "min_s": t["min_s"], "bloco": t["bloco"]}
              for t in sorted(textos_q, key=lambda t: (t["ini_q"], t["y"]))]
    legendas, falas = _legendas(video, receita, escolhas, palavras, total_q, fps, avisos)
    preco = escolhas.get("preco")
    if preco not in (None, ""):
        try:
            texto_preco = formatar_preco(preco)
            for lg in legendas:
                for m in PRECO_LOJA.findall(lg["texto"]):
                    if m != texto_preco:
                        avisos.append(f"A legenda diz {m}, mas o preço do cadastro é {texto_preco}: corrigir a fala ou a legenda.")
        except ValueError:
            pass
    total_s = _s(total_q, fps)
    audio = []
    m = receita["musica"]
    if musica:
        exporta = bool(musica.get("no_capcut"))
        base = float(m["volume_musica_sem_fala_db"])
        audio.append({"arquivo": musica["arquivo"], "ini_s": 0.0, "dur_s": total_s,
                      "fonte_ini_s": float(musica.get("ini_s") or 0.0), "volume_db": base,
                      "papel": "musica" if exporta else "guia", "exportar": exporta,
                      "volume_chaves": _chaves_volume(falas, float(m["volume_musica_com_fala_db"]), base, total_s)})
        if exporta and m["origem"] == "instagram":
            avisos.append("Música dentro do CapCut: só com licença para o Instagram (Meta Sound Collection, Epidemic, "
                          "Pixabay); o padrão desta receita é pôr a música pelo Instagram (§7).")
        elif not exporta:
            avisos.append("Faixa-guia só para cortar na batida: desligar antes de exportar; a música entra pelo "
                          "Instagram (§7).")
    elif m["origem"] == "faixa_guia":
        avisos.append("A receita pede música no vídeo (faixa licenciada) e nenhuma foi escolhida.")
    audio.extend(audio_sons)
    transicoes = _transicoes(itens, blocos, receita, orc, avisos)
    plano = {
        "projeto": bruto.get("projeto") or projeto,
        "receita": receita["id"],
        "destino": destino,
        "gerado_em": datetime.now().astimezone().isoformat(timespec="seconds"),
        "canvas": canvas,
        "duracao_s": total_s,
        "blocos": [{"bloco": b["i"], "papel": b["papel"], "ini_s": _s(b["ini_q"], fps), "dur_s": _s(b["dur_q"], fps),
                    "tomada": b["fontes"][0]["tomada"], "arquivo": b["fontes"][0]["arquivo"], "fala": b["fala"],
                    "payoff": bool(b["def"].get("payoff"))} for b in blocos],
        "video": video,
        "textos": textos,
        "legendas": legendas,
        "audio": audio,
        "transicoes": transicoes,
        "efeitos": efeitos,
        "batidas_s": [round(x, 4) for x in batidas if x <= total_s + _EPS] if bq else [],
        "preco": ({"valor": float(_centavos(preco)) / 100, "texto": formatar_preco(preco), "parcelas": parcelas(preco),
                   "sku": escolhas.get("sku")} if preco not in (None, "") and _preco_ok(preco) else None),
        "cor": receita["cor"],
        "loop": bool(receita.get("loop")),
        "regras": _regras(receita),
        "acabamento": [],
        "avisos": avisos,
        "violacoes": [],
    }
    plano["acabamento"] = _acabamento(plano, receita)
    violacoes, avisos_plano = conferir_plano(plano)
    plano["violacoes"] = violacoes
    plano["avisos"] = list(dict.fromkeys(avisos + avisos_plano))
    _gravar_json(p["trabalho"] / "plano.json", plano)
    log.info("plano.json de %s (%s, %s): %s s, %d clipe(s), %d texto(s), %d legenda(s), %d aviso(s), %d violação(ões)",
             plano["projeto"], receita["id"], destino, _n(total_s), len(video), len(textos), len(legendas),
             len(plano["avisos"]), len(violacoes))
    return plano


def _preco_ok(preco) -> bool:
    try:
        _centavos(preco)
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------- conferência do plano

def _regras_do_plano(plano: dict) -> dict:
    if plano.get("regras"):
        return plano["regras"]
    try:
        return _regras(receitas.carregar(plano["receita"]))
    except (receitas.ErroReceita, KeyError):
        return {}


def conferir_plano(plano: dict) -> tuple[list[str], list[str]]:
    """``(violações, avisos)`` do plano pelas regras do guia (§3, §4.1, §5, §9, §10)."""
    v: list[str] = []
    a: list[str] = []
    cat = receitas.tecnicas()
    rt = _r("plano_texto")
    rg = _r("plano_gancho")
    rr = _r("plano_ritmo")
    zona = _r("zona_segura")
    regras = _regras_do_plano(plano)
    destino = plano.get("destino", "reels")
    fps = float((plano.get("canvas") or {}).get("fps") or 30)
    q = 1.0 / fps
    dur = float(plano.get("duracao_s") or 0)
    video = plano.get("video") or []
    principais = sorted((it for it in video if it.get("faixa", 0) == 0), key=lambda it: it["ini_s"])
    textos = plano.get("textos") or []
    legendas = plano.get("legendas") or []
    efeitos = plano.get("efeitos") or []

    # duração: receita, destino e linha do tempo sem buraco
    faixa = regras.get("duracao_s")
    if faixa and not faixa[0] - q / 2 <= dur <= faixa[1] + q / 2:
        v.append(f"Duração de {_n(dur)} s fora da receita ({_n(faixa[0], 0)}–{_n(faixa[1], 0)} s).")
    preset = (config.carregar("exportacao").get("presets") or {}).get(destino) or {}
    if preset.get("duracao_max_s") and dur > float(preset["duracao_max_s"]) + q / 2:
        v.append(f"Duração de {_n(dur)} s acima do máximo de {destino} ({_n(float(preset['duracao_max_s']), 0)} s).")
    if preset.get("duracao_min_s") and dur < float(preset["duracao_min_s"]) - q / 2:
        v.append(f"Duração de {_n(dur)} s abaixo do mínimo de {destino} ({_n(float(preset['duracao_min_s']), 0)} s).")
    t = 0.0
    for it in principais:
        if abs(it["ini_s"] - t) > q / 2:
            v.append(f"Buraco ou sobreposição na faixa principal em {_n(t, 2)} s.")
            break
        t = it["ini_s"] + it["dur_s"]
    if principais and abs(t - dur) > q / 2:
        v.append(f"A faixa principal termina em {_n(t, 2)} s e o plano diz {_n(dur, 2)} s.")

    # gancho no quadro 1
    if not principais or principais[0].get("papel") != "gancho":
        v.append("O vídeo não começa pelo gancho (quadro 1, §3).")
    ganchos = [x for x in textos if x.get("papel") == "gancho"]
    g = next((x for x in ganchos if x["ini_s"] <= q / 2 and float(x.get("entrada_s") or 0) <= rg["entra_max_s"]), None)
    if g is None:
        v.append(f"Gancho sem texto no quadro 1 (começa em 0 s e entra em ≤ {_n(rg['entra_max_s'])} s, §3/§5).")
    else:
        n = receitas.palavras(g["texto"])
        if not rg["palavras"][0] <= n <= rg["palavras"][1]:
            v.append(f"Texto do gancho com {n} palavra(s) (regra: {rg['palavras'][0]}–{rg['palavras'][1]}, §5).")
        if not rg["tamanho_px"][0] <= float(g["tamanho_px"]) <= rg["tamanho_px"][1]:
            v.append(f"Texto do gancho com {_n(float(g['tamanho_px']), 0)} px (regra: {rg['tamanho_px'][0]}–"
                     f"{rg['tamanho_px'][1]} px, §5).")
        if not rg["y"][0] <= float(g["y"]) <= rg["y"][1]:
            v.append(f"Texto do gancho em y {_n(float(g['y']), 0)} (regra: y {rg['y'][0]}–{rg['y'][1]}, §5).")

    # textos e legendas: zona segura, tamanho, tempo, preço
    y0, y1 = receitas.limites_y(destino)
    for x in textos + [{**lg, "papel": "legenda"} for lg in legendas]:
        rot = f"{'Legenda' if x['papel'] == 'legenda' else 'Texto'} {x['texto']!r}".replace("\\n", " ")
        cx0, cy0, cx1, cy1 = caixa_texto(x)
        if cx0 < zona["x"][0] - 0.5 or cx1 > zona["x"][1] + 0.5 or cy0 < y0 - 0.5 or cy1 > y1 + 0.5:
            v.append(f"{rot} fora da zona segura de {destino} (caixa x {cx0:.0f}–{cx1:.0f}, y {cy0:.0f}–{cy1:.0f}; "
                     f"seguro x {zona['x'][0]}–{zona['x'][1]}, y {y0:g}–{y1:g}, §10).")
        if float(x.get("tamanho_px") or 0) < rt["tamanho_min_px"]:
            v.append(f"{rot} com {_n(float(x.get('tamanho_px') or 0), 0)} px (mínimo {rt['tamanho_min_px']} px, §5).")
        for ruim in precos_fora_do_formato(x["texto"]):
            v.append(f"{rot}: preço {ruim!r} fora do formato da loja (R$229,99, §5).")
        if x["papel"] != "legenda":
            precisa = tempo_minimo(x)
            if float(x["dur_s"]) < precisa - q / 2:
                v.append(f"{rot} fica {_n(float(x['dur_s']))} s na tela; precisa de {_n(precisa)} s "
                         "(1 s + 0,3 s por palavra, mínimo 1,5 s, §5).")
        elif float(x["dur_s"]) > 0:
            cps = len(x["texto"].replace("\n", " ")) / float(x["dur_s"])
            if cps > _r("plano_legendas")["cps_max"] + 0.5:
                a.append(f"{rot}: {_n(cps)} caracteres/s (máx. {_r('plano_legendas')['cps_max']}, §5).")
    preco = plano.get("preco")
    if preco:
        esperado = parcelas(preco["valor"])
        for x in textos:
            if x.get("papel") == "parcelas" and x["texto"].replace("\n", " ") != esperado:
                v.append(f"Parcelas {x['texto']!r} diferentes da regra da loja para {preco['texto']} ({esperado}).")
            if x.get("papel") == "preco" and x["texto"].replace("\n", " ") != preco["texto"]:
                v.append(f"Preço {x['texto']!r} diferente do cadastro ({preco['texto']}).")

    # troca visual a cada 1–3 s (fala até 6 s)
    troca_max = float((regras.get("troca_s") or [0, rr["troca_max_s"]])[1] or rr["troca_max_s"])
    eventos = {round(it["ini_s"], 3) for it in principais}
    eventos |= {round(x["ini_s"], 3) for x in textos}
    eventos |= {round(e["ini_s"], 3) for e in efeitos if e.get("categoria") in ("assinatura", "apoio")}
    eventos = sorted(e for e in eventos if e < dur - q / 2) + [dur]
    for e0, e1 in zip(eventos, eventos[1:]):
        meio = (e0 + e1) / 2
        clipe = next((it for it in principais if it["ini_s"] <= meio < it["ini_s"] + it["dur_s"]), None)
        limite = float(rr["fala_troca_max_s"]) if clipe and clipe.get("fala") else troca_max
        if e1 - e0 > limite + q / 2:
            v.append(f"{_n(e1 - e0)} s sem troca visual entre {_n(e0)} e {_n(e1)} s (máx. {_n(limite)} s, §3).")

    # orçamento de efeitos e transições (§4.1), flashes (≤ 3/s)
    orc = receitas.orcamento(dur)
    visuais = sorted({e["tecnica"] for e in efeitos if (cat.get(e["tecnica"]) or {}).get("tipo") == "efeito"})
    maximo = int(orc["assinatura"]) + int(orc["apoio"][1])
    if len(visuais) > maximo:
        v.append(f"Efeitos acima do orçamento de {_n(dur)} s: {len(visuais)} técnicas ({', '.join(f'#{n}' for n in visuais)}); "
                 f"máximo {maximo} (1 assinatura + {orc['apoio'][1]} de apoio, §4.1).")
    assinaturas = {e["tecnica"] for e in efeitos if e.get("categoria") == "assinatura"}
    if len(assinaturas) > 1:
        v.append(f"Mais de um efeito-assinatura ({', '.join(f'#{n}' for n in sorted(assinaturas))}, §4.1).")
    trans = [x for x in plano.get("transicoes") or [] if x.get("tipo") != "corte_seco"]
    lim_trans = int(orc["transicoes"][1])
    if regras.get("transicoes_max") is not None:
        lim_trans = min(lim_trans, int(regras["transicoes_max"]))
    if len(trans) > lim_trans:
        v.append(f"{len(trans)} transições além do corte seco; o orçamento permite {lim_trans} (§4.1).")
    sons = [e for e in efeitos if e["tecnica"] == 57]
    if len(sons) > int(orc["efeitos_sonoros"][1]):
        v.append(f"{len(sons)} efeitos sonoros; o orçamento de {_n(dur)} s permite {orc['efeitos_sonoros'][1]} (§4.1).")
    estetica = regras.get("estetica")
    for n in sorted({e["tecnica"] for e in efeitos}):
        if estetica in ((cat.get(n) or {}).get("proibida_em") or []):
            v.append(f"#{n} {cat[n]['nome']} não combina com a estética {estetica} (§4.2).")
    tempos_flash = sorted([e["ini_s"] for e in efeitos if (cat.get(e["tecnica"]) or {}).get("flash")]
                          + [video[x["entre"][1]]["ini_s"] for x in plano.get("transicoes") or []
                             if x.get("tipo") == "flash" and x["entre"][1] < len(video)])
    max_flash = int(rr["flashes_max_por_s"])
    for i, t0 in enumerate(tempos_flash):
        n = sum(1 for t1 in tempos_flash[i:] if t1 - t0 < 1.0 - _EPS)
        if n > max_flash:
            v.append(f"{n} flashes em 1 s a partir de {_n(t0, 2)} s (máx. {max_flash} por segundo, §4.1).")
            break

    # cortes na batida (tolerância de 1 quadro)
    batidas = plano.get("batidas_s") or []
    if regras.get("corte_na_batida"):
        if not batidas:
            a.append("A receita corta na batida e o plano não tem batidas: conferir o ritmo no CapCut.")
        else:
            tol = int(rr["tolerancia_batida_quadros"]) * q + _EPS
            for anterior, it in zip(principais, principais[1:]):
                if anterior.get("fala") and it.get("fala"):
                    continue
                perto = min(batidas, key=lambda b: abs(b - it["ini_s"]))
                if abs(perto - it["ini_s"]) > tol:
                    v.append(f"Corte em {_n(it['ini_s'], 2)} s fora da batida (a mais perto: {_n(perto, 2)} s; "
                             "tolerância de 1 quadro).")

    # avisos: CTA, re-gancho, payoff, texto sobre texto
    payoffs = [b for b in plano.get("blocos") or [] if b.get("payoff")]
    for x in textos:
        if x.get("papel") == "cta" and float(x["dur_s"]) > rr["cta_max_s"] + q / 2:
            sobre = any(b["ini_s"] - q <= x["ini_s"] < b["ini_s"] + b["dur_s"] for b in payoffs)
            if not sobre:
                a.append(f"CTA com {_n(float(x['dur_s']))} s fora do payoff (até {_n(rr['cta_max_s'])} s ou sobre o payoff, §3).")
    if dur > rr["regancho_acima_de_s"]:
        inicios = sorted({0.0} | {float(x["ini_s"]) for x in textos}) + [dur]
        maior = max(b - a_ for a_, b in zip(inicios, inicios[1:]))
        if maior > rr["regancho_max_s"] + q:
            a.append(f"{_n(maior)} s sem texto novo: vídeo acima de {rr['regancho_acima_de_s']} s pede re-gancho a cada "
                     f"5–8 s (§3); passar 'texto' num bloco do meio que tenha o texto 'regancho' na receita.")
    for b in payoffs:
        if dur and b["ini_s"] > rr["payoff_max_fracao"] * dur + q:
            a.append(f"Payoff ({b['papel']}) começa em {_n(b['ini_s'])} s, depois de {int(rr['payoff_max_fracao'] * 100)}% "
                     "do vídeo (§3).")
    todos = textos + [{**lg, "papel": "legenda"} for lg in legendas]
    for i, x in enumerate(todos):
        for w in todos[i + 1:]:
            if x["ini_s"] < w["ini_s"] + w["dur_s"] - q and w["ini_s"] < x["ini_s"] + x["dur_s"] - q:
                ax0, ay0, ax1, ay1 = caixa_texto(x)
                bx0, by0, bx1, by1 = caixa_texto(w)
                if ax0 < bx1 and bx0 < ax1 and ay0 < by1 and by0 < ay1:
                    a.append(f"Texto {x['texto']!r} e {w['texto']!r} se sobrepõem na tela.".replace("\\n", " "))
    return v, list(dict.fromkeys(a))


def validar_plano(plano: dict) -> list[str]:
    """Violações do plano (lista vazia = pode ir para o rascunho)."""
    return conferir_plano(plano)[0]


# ---------------------------------------------------------------- fila e terminal

def resumo(plano: dict, caminho: Path | None = None) -> dict:
    return {
        "projeto": plano["projeto"], "receita": plano["receita"], "destino": plano["destino"],
        "plano_json": str(caminho) if caminho else None, "duracao_s": plano["duracao_s"],
        "blocos": [f"{_n(b['ini_s'], 2)} s {b['papel']} {b['tomada'] or b['arquivo']}" for b in plano["blocos"]],
        "clipes": len(plano["video"]), "textos": [t["texto"].replace("\n", " ") for t in plano["textos"]],
        "legendas": len(plano["legendas"]), "acabamento": plano["acabamento"],
        "avisos": plano["avisos"], "violacoes": plano["violacoes"],
    }


def texto(plano: dict, caminho: Path | None = None) -> str:
    linhas = [f"Plano {plano['receita']} ({plano['destino']}): {_n(plano['duracao_s'])} s, {len(plano['blocos'])} bloco(s), "
              f"{len(plano['video'])} clipe(s), {len(plano['textos'])} texto(s), {len(plano['legendas'])} legenda(s)."]
    for b in plano["blocos"]:
        linhas.append(f"  {_n(b['ini_s'], 2)}–{_n(b['ini_s'] + b['dur_s'], 2)} s  {b['papel']}  "
                      f"{b['tomada'] or b['arquivo']}{'  (fala)' if b['fala'] else ''}")
    for t in plano["textos"]:
        linhas.append(f"  texto {_n(t['ini_s'], 2)} s: {t['texto']!r}".replace("\\n", " / "))
    if plano["acabamento"]:
        linhas.append("Acabamento no CapCut:")
        linhas += [f"  - {x}" for x in plano["acabamento"]]
    if plano["avisos"]:
        linhas.append("Avisos:")
        linhas += [f"  - {x}" for x in plano["avisos"]]
    if plano["violacoes"]:
        linhas.append("VIOLAÇÕES (corrigir as escolhas antes do rascunho):")
        linhas += [f"  - {x}" for x in plano["violacoes"]]
    if caminho:
        linhas.append(f"plano.json: {caminho}")
    return "\n".join(linhas)


def _escolhas_de(args_escolhas, p: dict[str, Path]) -> dict:
    if args_escolhas is None:
        arq = p["trabalho"] / "escolhas.json"
        if not arq.is_file():
            raise ErroPlano(f"Sem escolhas: passe 'escolhas' no pedido ou grave {arq}.")
        return _ler_json(arq)
    if isinstance(args_escolhas, (str, Path)):
        arq = Path(args_escolhas)
        if not arq.is_absolute() and not arq.is_file():
            arq = p["trabalho"] / arq
        if not arq.is_file():
            raise ErroPlano(f"Arquivo de escolhas não encontrado: {arq}")
        return _ler_json(arq)
    if not isinstance(args_escolhas, dict):
        raise ErroPlano("'escolhas' tem que ser um objeto JSON ou o caminho de um arquivo.")
    _gravar_json(p["trabalho"] / "escolhas.json", args_escolhas)
    return args_escolhas


def tarefa(args: dict, ctx: Contexto) -> dict:
    """Pedido ``video.planejar``: args ``{"projeto", "receita", "escolhas"?}`` (objeto, caminho ou nada = escolhas.json).
    Violação vira erro (com o resumo em ``resultado_parcial``); avisos não bloqueiam."""
    projeto, receita = args.get("projeto"), args.get("receita")
    if not projeto or not receita:
        raise ValueError("Faltam 'projeto' (pasta em videos\\bruto) e/ou 'receita' (ex.: r02).")
    p = _pastas(projeto)
    escolhas = _escolhas_de(args.get("escolhas"), p)
    plano = planejar(projeto, receita, escolhas)
    caminho = p["trabalho"] / "plano.json"
    ctx.arquivo("plano.json").write_text(json.dumps(plano, ensure_ascii=False, indent=2), encoding="utf-8")
    ctx.arquivo("plano.txt").write_text(texto(plano, caminho) + "\n", encoding="utf-8")
    res = resumo(plano, caminho)
    if plano["violacoes"]:
        raise ErroPlano(f"Plano com {len(plano['violacoes'])} violação(ões): " + " | ".join(plano["violacoes"]),
                        resultado_parcial=res)
    return res


def cli(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="python -m rotinas video-planejar",
                                 description="B2: monta o plano da linha do tempo (receita + bruto.json + escolhas da IA).")
    ap.add_argument("--projeto", required=True, help="nome da pasta em videos\\bruto")
    ap.add_argument("--receita", required=True, help="id da receita (ex.: r02 ou r02-provador-com-preco)")
    ap.add_argument("--escolhas", help="arquivo JSON das escolhas (padrão: trabalho\\<projeto>\\escolhas.json)")
    ap.add_argument("--json", action="store_true", help="imprime o plano em JSON")
    a = ap.parse_args(argv)
    try:
        p = _pastas(a.projeto)
        plano = planejar(a.projeto, a.receita, _escolhas_de(a.escolhas, p))
    except (ErroPlano, receitas.ErroReceita, config.ErroConfig, ValueError, OSError) as e:
        print(f"Erro: {e}", file=sys.stderr)
        return 2
    caminho = p["trabalho"] / "plano.json"
    print(json.dumps(plano, ensure_ascii=False, indent=2) if a.json else texto(plano, caminho))
    return 1 if plano["violacoes"] else 0
