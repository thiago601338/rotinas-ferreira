"""B2: receitas de edição (``receitas/*.json``): listar, carregar, validar e orçamento de efeitos.

Cada receita traduz uma receita de moda do guia (``conhecimento/edicao-video-capcut.md`` §4.4) com as regras de
montagem e ritmo (§3), orçamento (§4.1), texto (§5), cor (§6), áudio (§7), checklist (§9) e zonas seguras (§10).
O catálogo de técnicas (§4.2), a tabela do orçamento e os limites ficam em ``config/video.json``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from .. import config, registro

log = registro.obter("video.receitas")

CAMPOS = {
    "id": str, "nome": str, "objetivo": str, "estetica": str, "destinos": list, "duracao_s": list,
    "estrutura": list, "ritmo": dict, "textos": dict, "legendas": dict, "transicoes": dict, "efeitos": dict,
    "musica": dict, "cor": dict, "loop": bool, "notas": list,
}
_NOMES_TIPO = {str: "texto", list: "lista", dict: "objeto", bool: "true/false"}
_ID = re.compile(r"^r(\d{2})-[a-z0-9]+(?:-[a-z0-9]+)*$")
_ATALHO = re.compile(r"^[rR]0*(\d{1,2})$")
_SEPARADORES = {"·", "•", "|", "-", "–", "—", "/", "+", "&"}


class ErroReceita(RuntimeError):
    """Receita inexistente ou ilegível."""


def _cfg() -> dict:
    return config.carregar("video")


def regra(chave: str):
    valor = _cfg().get(chave)
    if valor is None:
        raise config.ErroConfig(f"config/video.json sem a chave '{chave}' (regras das receitas).")
    return valor


# ---------------------------------------------------------------- arquivos

def pasta() -> Path:
    """Pasta das receitas (``receitas/`` na raiz do repositório, ou a de ``receitas_pasta``)."""
    p = config.expandir(_cfg().get("receitas_pasta") or "receitas")
    return p if p.is_absolute() else config.RAIZ / p


def _arquivos() -> list[Path]:
    return sorted(a for a in pasta().glob("r*.json") if _ID.match(a.stem))


def _ler(caminho: Path) -> dict:
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ErroReceita(f"JSON inválido em {caminho.name}: {e}") from e


def listar() -> list[dict]:
    """``[{"id", "nome", "objetivo", "duracao_s"}]`` na ordem R1…R12."""
    itens = []
    for arq in _arquivos():
        r = _ler(arq)
        itens.append({"id": r.get("id", arq.stem), "nome": r.get("nome"), "objetivo": r.get("objetivo"),
                      "duracao_s": r.get("duracao_s")})
    return itens


def normalizar_id(id_: str) -> str:
    """Aceita o id completo, o prefixo (``r02``) ou o atalho do guia (``R2``). Devolve o id completo."""
    texto = str(id_ or "").strip()
    if texto.lower().endswith(".json"):
        texto = texto[:-5]
    atalho = _ATALHO.match(texto)
    prefixo = f"r{int(atalho.group(1)):02d}" if atalho else texto.lower()
    ids = [a.stem for a in _arquivos()]
    if prefixo in ids:
        return prefixo
    achados = [i for i in ids if i.startswith(prefixo + "-")]
    if len(achados) == 1:
        return achados[0]
    raise ErroReceita(f"Receita não encontrada: {id_!r}. Receitas: {', '.join(ids) or '(nenhuma)'}.")


def carregar(id_: str) -> dict:
    """Receita pelo id (ou ``r02``/``R2``)."""
    rid = normalizar_id(id_)
    receita = _ler(pasta() / f"{rid}.json")
    if receita.get("id") != rid:
        raise ErroReceita(f"{rid}.json tem id {receita.get('id')!r}: o id tem que ser igual ao nome do arquivo.")
    return receita


# ---------------------------------------------------------------- catálogo e regras

def tecnicas() -> dict[int, dict]:
    """Catálogo da §4.2: número → ``{"nome", "tipo", ...}``."""
    return {int(n): d for n, d in regra("tecnicas").items()}


def tecnica(n) -> dict | None:
    try:
        return tecnicas().get(int(n))
    except (TypeError, ValueError):
        return None


def orcamento(duracao_s: float) -> dict:
    """Linha da tabela §4.1 para a duração: ``{"faixa_s", "assinatura", "apoio", "transicoes", "efeitos_sonoros",
    "apoio_repetidos"}``. Faixas ``[mín, máx]`` (o máximo é o limite; o mínimo é referência). Até 15 s usa a 1ª
    linha (também abaixo de 7 s); até 30 s a 2ª; acima, a 3ª."""
    linhas = regra("orcamento_efeitos")
    for linha in linhas:
        if linha.get("ate_s") is None or float(duracao_s) <= float(linha["ate_s"]) + 1e-9:
            return {k: v for k, v in linha.items() if k != "ate_s"}
    return {k: v for k, v in linhas[-1].items() if k != "ate_s"}


def palavras(texto: str) -> int:
    """Palavras de um texto na tela (separadores como ``·`` não contam)."""
    return sum(1 for t in str(texto or "").split() if t not in _SEPARADORES and re.search(r"\w", t))


def tempo_minimo_texto(texto: str) -> float:
    """§5: tempo na tela ≈ 1 s + 0,3 s por palavra, mínimo 1,5 s."""
    r = regra("plano_texto")
    return max(float(r["tempo_min_s"]), float(r["tempo_base_s"]) + float(r["tempo_por_palavra_s"]) * palavras(texto))


def limites_y(destino: str) -> tuple[float, float]:
    """Faixa vertical segura para texto no destino: retângulo universal ∩ margens do destino (§10)."""
    zona = regra("zona_segura")
    y0, y1 = float(zona["y"][0]), float(zona["y"][1])
    extra = (_cfg().get("zona_segura_destino") or {}).get(destino) or {}
    if extra.get("topo_px") is not None:
        y0 = max(y0, float(extra["topo_px"]))
    if extra.get("base_px") is not None:
        y1 = min(y1, 1920.0 - float(extra["base_px"]))
    return y0, y1


# ---------------------------------------------------------------- validação

def _faixa(valor, nome: str, e: list[str], minimo: float | None = None, maximo: float | None = None,
           inteiro: bool = False) -> bool:
    tipos = (int,) if inteiro else (int, float)
    if (not isinstance(valor, list) or len(valor) != 2
            or not all(isinstance(v, tipos) and not isinstance(v, bool) for v in valor)):
        e.append(f"{nome} deveria ser [mín, máx] com {'inteiros' if inteiro else 'números'}")
        return False
    a, b = valor
    if a > b:
        e.append(f"{nome}: mínimo {a} maior que o máximo {b}")
        return False
    if minimo is not None and a < minimo:
        e.append(f"{nome}: {a} abaixo de {minimo}")
        return False
    if maximo is not None and b > maximo:
        e.append(f"{nome}: {b} acima de {maximo}")
        return False
    return True


def _lista_int(valor) -> list:
    if valor is None:
        return []
    return list(valor) if isinstance(valor, list) else [valor]


def _papeis_texto(bloco: dict) -> list[str]:
    t = bloco.get("texto")
    if t is None:
        return []
    return [t] if isinstance(t, str) else list(t) if isinstance(t, list) else [t]


def _validar_textos(receita: dict, e: list[str]) -> None:
    rt = regra("plano_texto")
    rg = regra("plano_gancho")
    zona = regra("zona_segura")
    textos = receita["textos"]
    if "gancho" not in textos:
        e.append("textos: falta o papel 'gancho' (texto do gancho no quadro 1, §3/§5)")
    for papel, t in textos.items():
        nome = f"textos.{papel}"
        if not isinstance(t, dict):
            e.append(f"{nome} deveria ser um objeto")
            continue
        for campo in ("y", "tamanho_px", "min_s", "entra_max_s", "estilo"):
            if campo not in t:
                e.append(f"{nome}: falta '{campo}'")
        if not all(c in t for c in ("y", "tamanho_px", "min_s", "entra_max_s")):
            continue
        if _faixa(t["y"], f"{nome}.y", e):
            for destino in receita.get("destinos") or []:
                y0, y1 = limites_y(destino)
                if t["y"][0] < y0 or t["y"][1] > y1:
                    e.append(f"{nome}.y {t['y']} fora da zona segura de {destino} (y {y0:g}–{y1:g}, §10)")
        x = t.get("x", rt["x_padrao"])
        if not zona["x"][0] < x < zona["x"][1]:
            e.append(f"{nome}.x {x} fora da zona segura (x {zona['x'][0]}–{zona['x'][1]})")
        if t["tamanho_px"] < rt["tamanho_min_px"]:
            e.append(f"{nome}: {t['tamanho_px']} px abaixo do mínimo de {rt['tamanho_min_px']} px (§5)")
        if t.get("tamanho_min_px") is not None and not rt["tamanho_min_px"] <= t["tamanho_min_px"] <= t["tamanho_px"]:
            e.append(f"{nome}.tamanho_min_px tem que ficar entre {rt['tamanho_min_px']} e tamanho_px")
        if papel not in rt["papeis_sem_tempo_minimo"] and t["min_s"] < rt["tempo_min_s"]:
            e.append(f"{nome}: min_s {t['min_s']} abaixo de {rt['tempo_min_s']} s (§5)")
        animacao = t.get("animacao", "nenhuma")
        if animacao not in rt["animacoes_s"]:
            e.append(f"{nome}: animação desconhecida {animacao!r} (use {', '.join(rt['animacoes_s'])})")
        if t.get("atraso_s") is not None and not (isinstance(t["atraso_s"], (int, float)) and t["atraso_s"] >= 0):
            e.append(f"{nome}.atraso_s tem que ser um número ≥ 0")
        if papel == "gancho":
            if not (rg["y"][0] <= t["y"][0] and t["y"][1] <= rg["y"][1]):
                e.append(f"{nome}.y {t['y']} fora de y {rg['y'][0]}–{rg['y'][1]} (§5)")
            if not rg["tamanho_px"][0] <= t["tamanho_px"] <= rg["tamanho_px"][1]:
                e.append(f"{nome}: {t['tamanho_px']} px fora de {rg['tamanho_px'][0]}–{rg['tamanho_px'][1]} px (§5)")
            if t["min_s"] < rg["min_s"]:
                e.append(f"{nome}: fica {t['min_s']} s; o gancho fica ≥ {rg['min_s']} s (§5)")
            if t["entra_max_s"] > rg["entra_max_s"] or rt["animacoes_s"].get(animacao, 0) > rg["entra_max_s"]:
                e.append(f"{nome}: entrada acima de {rg['entra_max_s']} s (§3/§5)")
            if "palavras" in t and _faixa(t["palavras"], f"{nome}.palavras", e, inteiro=True):
                if t["palavras"][0] < rg["palavras"][0] or t["palavras"][1] > rg["palavras"][1]:
                    e.append(f"{nome}.palavras {t['palavras']} fora de {rg['palavras'][0]}–{rg['palavras'][1]} (§5)")
            if t.get("padrao"):
                e.append(f"{nome}: o texto do gancho é escolhido pela IA para cada vídeo (sem 'padrao')")


def _validar_estrutura(receita: dict, e: list[str], usadas: dict[int, str]) -> None:
    cat = tecnicas()
    ritmo = receita["ritmo"]
    rr = regra("plano_ritmo")
    textos = receita["textos"]
    transicoes = receita["transicoes"]
    tipos_transicao = regra("tipos_transicao")
    reforcos = regra("reforcos")
    composicoes = _cfg().get("composicoes") or {}
    sonoros = set((receita["efeitos"] or {}).get("sonoros") or [])
    estrutura = receita["estrutura"]
    if not estrutura:
        e.append("estrutura vazia")
        return
    papeis = [b.get("papel") if isinstance(b, dict) else None for b in estrutura]
    if len(set(papeis)) != len(papeis):
        e.append("estrutura: papéis repetidos (use 'repete' para listas de looks)")
    primeiro = estrutura[0] if isinstance(estrutura[0], dict) else {}
    if primeiro.get("papel") != "gancho" or "gancho" not in _papeis_texto(primeiro):
        e.append("estrutura: o 1º bloco tem que ser 'gancho' com texto 'gancho' (gancho no quadro 1, §3)")
    troca_s = ritmo.get("troca_s")
    troca_max = float(troca_s[1]) if isinstance(troca_s, list) and len(troca_s) == 2 else float(rr["troca_max_s"])
    soma_min = soma_max = 0.0
    for i, b in enumerate(estrutura):
        nome = f"estrutura[{i}]" + (f" ({b.get('papel')})" if isinstance(b, dict) and b.get("papel") else "")
        if not isinstance(b, dict):
            e.append(f"{nome} deveria ser um objeto")
            continue
        for campo in ("papel", "dur_s", "tomada_sugerida", "texto", "efeito", "repete"):
            if campo not in b:
                e.append(f"{nome}: falta '{campo}'")
        if not isinstance(b.get("tomada_sugerida"), str) or not b.get("tomada_sugerida", "").strip():
            e.append(f"{nome}: 'tomada_sugerida' tem que descrever a tomada (§2)")
        ok_dur = _faixa(b.get("dur_s"), f"{nome}.dur_s", e, minimo=0.1)
        repete = b.get("repete")
        n_min = 1
        if repete is not None and _faixa(repete, f"{nome}.repete", e, minimo=0, inteiro=True):
            n_min = repete[0]
        if ok_dur:
            soma_min += b["dur_s"][0] * n_min
            soma_max += b["dur_s"][1] * n_min
        for papel in _papeis_texto(b):
            if papel not in textos:
                e.append(f"{nome}: texto {papel!r} sem definição em 'textos'")
        for n in _lista_int(b.get("efeito")):
            if not isinstance(n, int) or n not in cat:
                e.append(f"{nome}: efeito {n!r} não existe no catálogo §4.2 (1–{max(cat)})")
            elif cat[n]["tipo"] == "transicao":
                e.append(f"{nome}: técnica {n} ({cat[n]['nome']}) é transição: usar o campo 'transicao'")
            else:
                usadas.setdefault(n, nome)
        if b.get("troca") is not None:
            n = b["troca"]
            if not isinstance(n, int) or n not in cat or cat[n]["tipo"] not in ("corte", "transicao"):
                e.append(f"{nome}: troca {n!r} não é uma técnica de troca/corte do catálogo §4.2")
            else:
                usadas.setdefault(n, nome)
        if b.get("reforco") is not None:
            if b["reforco"] not in reforcos:
                e.append(f"{nome}: reforço {b['reforco']!r} inválido (um só por corte: {', '.join(reforcos)}, §4.1)")
            else:
                n = int(reforcos[b["reforco"]])
                usadas.setdefault(n, nome)
                if cat.get(n, {}).get("tipo") == "som" and b["reforco"] not in sonoros:
                    e.append(f"{nome}: reforço {b['reforco']!r} fora de efeitos.sonoros")
        for som in _lista_int(b.get("som")):
            if som not in sonoros:
                e.append(f"{nome}: som {som!r} fora de efeitos.sonoros")
            else:
                usadas.setdefault(57, nome)
        if b.get("transicao") is not None:
            t = b["transicao"]
            if t not in tipos_transicao:
                e.append(f"{nome}: transição {t!r} desconhecida ({', '.join(tipos_transicao)})")
            elif t not in (transicoes.get("permitidas") or []):
                e.append(f"{nome}: transição {t!r} fora de transicoes.permitidas")
            elif i == 0:
                e.append(f"{nome}: o gancho começa no quadro 1, sem transição de entrada")
            elif tipos_transicao[t].get("tecnica"):
                usadas.setdefault(int(tipos_transicao[t]["tecnica"]), nome)
        vel = b.get("velocidade")
        if vel is not None:
            if not isinstance(vel, (int, float)) or vel <= 0:
                e.append(f"{nome}: velocidade tem que ser > 0")
            elif vel < 1:
                usadas.setdefault(9, nome)
            elif vel >= 4:
                usadas.setdefault(12, nome)
        if b.get("composicao") is not None and b["composicao"] not in composicoes:
            e.append(f"{nome}: composição {b['composicao']!r} desconhecida ({', '.join(composicoes)})")
        for campo in ("efeito_max", "reforco_max", "som_max", "batidas"):
            v = b.get(campo)
            if v is not None and (not isinstance(v, int) or isinstance(v, bool) or v < 1):
                e.append(f"{nome}: {campo} tem que ser um inteiro ≥ 1")
        # troca visual a cada 1–3 s (§3): bloco sem fala mais longo que isso precisa de mudança no meio
        # (texto que entra depois do início ou punch-in no meio do bloco)
        if ok_dur and not b.get("fala"):
            dmax_b = float(b["dur_s"][1])
            pontos = {0.0} | {float((textos.get(p) or {}).get("atraso_s") or 0) for p in _papeis_texto(b)}
            if 1 in _lista_int(b.get("efeito")):
                pontos.add(dmax_b / 2)
            marcas = sorted(x for x in pontos if x < dmax_b) + [dmax_b]
            maior = max(y - x for x, y in zip(marcas, marcas[1:]))
            if maior > troca_max + 1e-9:
                e.append(f"{nome}: pode ficar {maior:g} s sem troca visual (máx. {troca_max} s, §3)")
        if ok_dur and b.get("fala") and b["dur_s"][1] > rr["fala_troca_max_s"] and 15 not in _lista_int(b.get("efeito")):
            e.append(f"{nome}: fala de até {b['dur_s'][1]} s sem jump cut (máx. {rr['fala_troca_max_s']} s por plano, §3)")
    n_trans = {}
    for b in estrutura:
        if isinstance(b, dict) and b.get("transicao") not in (None, "corte_seco"):
            vezes = b["repete"][1] if isinstance(b.get("repete"), list) and len(b["repete"]) == 2 else 1
            n_trans[b["transicao"]] = n_trans.get(b["transicao"], 0) + vezes
    if isinstance(transicoes.get("max"), int) and sum(n_trans.values()) > transicoes["max"]:
        e.append(f"estrutura: até {sum(n_trans.values())} transições, acima de transicoes.max ({transicoes['max']})")
    for tipo, n in n_trans.items():
        limite = (tipos_transicao.get(tipo) or {}).get("max_por_video")
        if limite is not None and n > limite:
            e.append(f"estrutura: transição {tipo!r} até {n} vezes (máx. {limite} por vídeo, §4.2)")
    if isinstance(receita.get("duracao_s"), list) and len(receita["duracao_s"]) == 2:
        dmin, dmax = receita["duracao_s"]
        if soma_min > dmax + 1e-9:
            e.append(f"estrutura: o mínimo dos blocos ({soma_min:g} s) passa da duração máxima ({dmax} s)")
        if soma_max < dmin - 1e-9:
            e.append(f"estrutura: com o mínimo de repetições, os blocos ({soma_max:g} s) não chegam à duração "
                     f"mínima ({dmin} s)")


def _validar_efeitos(receita: dict, e: list[str], usadas: dict[int, str]) -> None:
    cat = tecnicas()
    ef = receita["efeitos"]
    dmax = receita["duracao_s"][1] if isinstance(receita.get("duracao_s"), list) and len(receita["duracao_s"]) == 2 else 60
    orc = orcamento(dmax)
    assinatura = ef.get("assinatura")
    apoio = ef.get("apoio") or []
    if assinatura is not None and assinatura not in cat:
        e.append(f"efeitos.assinatura {assinatura!r} não existe no catálogo §4.2")
    if not isinstance(apoio, list) or any(a not in cat for a in apoio):
        e.append("efeitos.apoio tem que ser uma lista de técnicas do catálogo §4.2")
        apoio = [a for a in apoio if a in cat] if isinstance(apoio, list) else []
    if len(set(apoio)) > orc["apoio"][1]:
        e.append(f"efeitos.apoio com {len(set(apoio))} técnicas; o orçamento de {dmax} s permite {orc['apoio'][1]} (§4.1)")
    if assinatura in apoio:
        e.append("efeitos: a assinatura não entra também no apoio")
    tr = receita["transicoes"]
    if not isinstance(tr.get("permitidas"), list) or "corte_seco" not in tr.get("permitidas", []):
        e.append("transicoes.permitidas tem que incluir 'corte_seco' (o resto é corte seco, §4.1)")
    tipos = regra("tipos_transicao")
    for t in tr.get("permitidas") or []:
        if t not in tipos:
            e.append(f"transicoes.permitidas: {t!r} desconhecida")
    mx = tr.get("max")
    if not isinstance(mx, int) or mx < 0:
        e.append("transicoes.max tem que ser um inteiro ≥ 0")
    elif mx > orc["transicoes"][1]:
        e.append(f"transicoes.max {mx} acima do orçamento de {dmax} s ({orc['transicoes'][1]}, §4.1)")
    if not isinstance(ef.get("sonoros", []), list):
        e.append("efeitos.sonoros tem que ser uma lista de nomes de som")
    permitidas = set(apoio) | ({assinatura} if assinatura is not None else set())
    biblioteca = {int(i.get("tecnica")) for i in receita.get("itens_biblioteca") or [] if isinstance(i, dict)
                  and isinstance(i.get("tecnica"), int)}
    todas = dict(usadas)
    for n in permitidas:
        todas.setdefault(n, "efeitos")
    for n, onde in sorted(todas.items()):
        d = cat.get(n)
        if not d:
            continue
        if d["tipo"] == "efeito" and n not in permitidas:
            e.append(f"{onde}: técnica {n} ({d['nome']}) não está na assinatura nem no apoio (§4.1)")
        if receita.get("estetica") in (d.get("proibida_em") or []):
            e.append(f"{onde}: técnica {n} ({d['nome']}) não combina com a estética {receita['estetica']} (§4.2)")
        if receita.get("objetivo") in (d.get("evitar_objetivo") or []):
            e.append(f"{onde}: técnica {n} ({d['nome']}) evitada em vídeo para {receita['objetivo']} (§4.2)")
        if d.get("so_biblioteca") and n not in biblioteca:
            e.append(f"{onde}: técnica {n} ({d['nome']}) só existe na biblioteca do CapCut ({d['so_biblioteca']}): "
                     "declarar em itens_biblioteca (marca comercial, §7) ou trocar por efeito feito à mão")


def _validar_musica_cor(receita: dict, e: list[str]) -> None:
    c = _cfg()
    m = receita["musica"]
    if m.get("origem") not in c["receitas_musica_origens"]:
        e.append(f"musica.origem {m.get('origem')!r} inválida ({', '.join(c['receitas_musica_origens'])})")
    for campo in ("volume_musica_com_fala_db", "volume_musica_sem_fala_db", "volume_voz_db"):
        if not isinstance(m.get(campo), (int, float)):
            e.append(f"musica.{campo} tem que ser um número (dB)")
    if "volume_clipe_sem_fala_db" not in m or not (m["volume_clipe_sem_fala_db"] is None
                                                   or isinstance(m["volume_clipe_sem_fala_db"], (int, float))):
        e.append("musica.volume_clipe_sem_fala_db tem que ser um número (dB) ou null (mudo)")
    if all(isinstance(m.get(k), (int, float)) for k in ("volume_musica_com_fala_db", "volume_voz_db")):
        a, b = regra("plano_musica")["abaixo_da_voz_db"]
        dif = m["volume_voz_db"] - m["volume_musica_com_fala_db"]
        if not a <= dif <= b:
            e.append(f"musica: durante a fala a música fica {dif:g} dB abaixo da voz (regra: {a}–{b} dB, §7)")
    if isinstance(m.get("volume_musica_sem_fala_db"), (int, float)) and m["volume_musica_sem_fala_db"] > 0:
        e.append("musica.volume_musica_sem_fala_db acima de 0 dB")
    ritmo = receita["ritmo"]
    _faixa(ritmo.get("troca_s"), "ritmo.troca_s", e, minimo=0.2, maximo=regra("plano_ritmo")["troca_max_s"])
    if not isinstance(ritmo.get("corte_na_batida"), bool):
        e.append("ritmo.corte_na_batida tem que ser true/false")
    elif ritmo["corte_na_batida"]:
        if not isinstance(ritmo.get("batidas_por_troca"), int) or ritmo["batidas_por_troca"] < 1:
            e.append("ritmo.batidas_por_troca tem que ser inteiro ≥ 1 quando corta na batida")
        if m.get("origem") == "sem":
            e.append("ritmo: corte na batida pede faixa-guia (musica.origem 'instagram' ou 'faixa_guia')")
    if ritmo.get("bpm") is not None:
        _faixa(ritmo["bpm"], "ritmo.bpm", e, minimo=40, maximo=220)
    cor = receita["cor"]
    if cor.get("look") not in c["receitas_looks_cor"]:
        e.append(f"cor.look {cor.get('look')!r} inválido ({', '.join(c['receitas_looks_cor'])}, §6)")
    if cor.get("filtro_max") is not None and not 0 <= cor["filtro_max"] <= 0.4:
        e.append("cor.filtro_max acima de 0,4 (filtros a 20–40%, §6)")
    if cor.get("tomada_cor_fiel") is not True:
        e.append("cor.tomada_cor_fiel tem que ser true (pelo menos um plano com a cor real, §4.1/§6)")
    lg = receita["legendas"]
    if not isinstance(lg.get("ligado"), bool):
        e.append("legendas.ligado tem que ser true/false")
    if lg.get("ligado"):
        rl = regra("plano_legendas")
        if "y" in lg and _faixa(lg["y"], "legendas.y", e):
            if lg["y"][0] < rl["y"][0] or lg["y"][1] > rl["y"][1]:
                e.append(f"legendas.y {lg['y']} fora de y {rl['y'][0]}–{rl['y'][1]} (§5)")
        tam = lg.get("tamanho_px")
        if not isinstance(tam, (int, float)) or not rl["tamanho_px"][0] <= tam <= rl["tamanho_px"][1]:
            e.append(f"legendas.tamanho_px tem que ficar entre {rl['tamanho_px'][0]} e {rl['tamanho_px'][1]} px (§5)")


def validar(receita: dict) -> list[str]:
    """Erros da receita (lista vazia = válida): estrutura do modelo e regras do guia §3–§10."""
    if not isinstance(receita, dict):
        return ["a receita não é um objeto JSON"]
    e: list[str] = []
    for campo, tipo in CAMPOS.items():
        if campo not in receita:
            e.append(f"falta o campo '{campo}'")
        elif not isinstance(receita[campo], tipo):
            e.append(f"'{campo}' deveria ser {_NOMES_TIPO[tipo]}")
    if e:
        return e
    c = _cfg()
    if not _ID.match(receita["id"]):
        e.append(f"id {receita['id']!r} fora do padrão rNN-nome-com-hifens")
    if receita["objetivo"] not in c["receitas_objetivos"]:
        e.append(f"objetivo {receita['objetivo']!r} inválido ({', '.join(c['receitas_objetivos'])}, §4.3)")
    if receita["estetica"] not in c["receitas_esteticas"]:
        e.append(f"estética {receita['estetica']!r} inválida ({', '.join(c['receitas_esteticas'])}, §4.3)")
    if not receita["destinos"] or any(d not in c["receitas_destinos"] for d in receita["destinos"]):
        e.append(f"destinos {receita['destinos']} inválidos (use {', '.join(c['receitas_destinos'])})")
    presets = config.carregar("exportacao").get("presets") or {}
    if _faixa(receita["duracao_s"], "duracao_s", e, minimo=1):
        for d in receita["destinos"]:
            p = presets.get(d) or {}
            if p.get("duracao_max_s") and receita["duracao_s"][1] > p["duracao_max_s"]:
                e.append(f"duracao_s até {receita['duracao_s'][1]} s passa do máximo de {d} ({p['duracao_max_s']} s)")
            if p.get("duracao_min_s") and receita["duracao_s"][0] < p["duracao_min_s"]:
                e.append(f"duracao_s a partir de {receita['duracao_s'][0]} s abaixo do mínimo de {d} ({p['duracao_min_s']} s)")
    if not receita["notas"] or not all(isinstance(n, str) and n.strip() for n in receita["notas"]):
        e.append("notas: listar o que a receita exige da captação (§2)")
    usadas: dict[int, str] = {}
    try:
        _validar_textos(receita, e)
        _validar_estrutura(receita, e, usadas)
        _validar_efeitos(receita, e, usadas)
        _validar_musica_cor(receita, e)
    except (TypeError, KeyError, ValueError, AttributeError, IndexError) as ex:
        e.append(f"campo com formato inesperado ({ex.__class__.__name__}: {ex}); conferir com as outras receitas")
        return e
    if receita["loop"] is False and not any("cta" in _papeis_texto(b) for b in receita["estrutura"] if isinstance(b, dict)):
        e.append("sem loop e sem CTA: o final tem que emendar no início ou ter CTA de até 2 s (§3/§9)")
    return e


# ---------------------------------------------------------------- terminal

def _intervalo(v) -> str:
    try:
        return f"{v[0]:g}–{v[1]:g} s"
    except (TypeError, IndexError, ValueError):
        return "?"


def cli(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="python -m rotinas video-receitas",
                                 description="B2: lista as receitas de edição (receitas/*.json) e confere as regras.")
    ap.add_argument("--validar", action="store_true", help="confere todas as receitas (sai com 1 se alguma tiver erro)")
    ap.add_argument("--id", help="mostra uma receita (ex.: r02 ou R2)")
    ap.add_argument("--json", action="store_true", help="saída em JSON")
    a = ap.parse_args(argv)
    try:
        if a.id:
            receita = carregar(a.id)
            erros = validar(receita)
            if a.json:
                print(json.dumps({"receita": receita, "erros": erros}, ensure_ascii=False, indent=2))
            else:
                print(f"{receita['id']}: {receita['nome']} ({receita['objetivo']}, {_intervalo(receita['duracao_s'])})")
                for b in receita["estrutura"]:
                    print(f"  - {b['papel']}: {_intervalo(b['dur_s'])} · {b['tomada_sugerida']}")
                print("Captação:")
                for n in receita["notas"]:
                    print(f"  - {n}")
                for x in erros:
                    print(f"  ERRO: {x}")
            return 1 if erros else 0
        itens = listar()
        falhas = {}
        if a.validar:
            for item in itens:
                try:
                    erros = validar(carregar(item["id"]))
                except ErroReceita as ex:
                    erros = [str(ex)]
                if erros:
                    falhas[item["id"]] = erros
        if a.json:
            print(json.dumps({"receitas": itens, "erros": falhas}, ensure_ascii=False, indent=2))
        else:
            for item in itens:
                marca = " ERRO" if item["id"] in falhas else (" ok" if a.validar else "")
                print(f"{item['id']}: {item['nome']} ({item['objetivo']}, {_intervalo(item['duracao_s'])}){marca}")
                for x in falhas.get(item["id"], []):
                    print(f"    - {x}")
            if a.validar:
                print(f"{len(itens) - len(falhas)} de {len(itens)} receita(s) válida(s).")
        return 1 if falhas else 0
    except (ErroReceita, config.ErroConfig) as ex:
        print(f"Erro: {ex}", file=sys.stderr)
        return 2
