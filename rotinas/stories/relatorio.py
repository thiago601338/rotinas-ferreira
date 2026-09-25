"""A6: relatório do pedido de stories e JS de conferência no Instagram.

Textos curtos, em português, prontos para a IA avisar o usuário: o que sobe/subiu (letra, peça,
mídias, onde está o link), o que ficou de fora e por quê, e o que ele precisa fazer.
A conferência parte do trecho de ``conhecimento/stories.md`` (``/api/v1/feed/reels_media/``).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from .. import config, fila, registro
from . import link

MOTIVO_COR = "cor sem estoque"
MOTIVO_POSTADO = "já postado"
ESTADOS_LETRA = {
    "publicada": "publicada",
    "ensaio_ok": "montada até antes de publicar",
    "falhou": "falhou",
    "nao_iniciada": "não chegou a ser postada",
}


def data_br(data: str) -> str:
    """``"2026-09-22"`` → ``"22/09/2026"``."""
    try:
        return datetime.strptime(str(data), "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        return str(data)


def _plural(n: int, singular: str, plural: str) -> str:
    return f"{n} {singular if n == 1 else plural}"


# ---------------------------------------------------------------- conferência (JS)

def sequencia_esperada(plano: dict, letras_publicadas: list[str] | None = None) -> list[dict]:
    """Mídias publicadas na ordem do plano: ``[{"letra", "nome", "esperado": "LINK"|"sem link", "url"}]``."""
    filtro = None if letras_publicadas is None else {str(l).upper() for l in letras_publicadas}
    seq = []
    for l in plano.get("letras") or []:
        if filtro is not None and l["letra"] not in filtro:
            continue
        for m in l.get("midias") or []:
            fig = m.get("figurinha")
            seq.append({"letra": l["letra"], "nome": m["nome"], "esperado": "LINK" if fig else "sem link",
                        "url": fig.get("url") if fig else None})
    return seq


def js_conferencia(plano: dict, letras_publicadas: list[str] | None = None) -> str:
    """JS para o console do navegador logado no Instagram. Última linha: ``CONFERE`` ou ``NÃO CONFERE``."""
    seq = sequencia_esperada(plano, letras_publicadas)
    if not seq:
        return "// Nada publicado neste pedido: nada a conferir no Instagram."
    c = config.carregar("stories").get("conferencia_instagram") or {}
    uid, app_id = str(c.get("uid") or ""), str(c.get("app_id") or "")
    if not uid.isdigit() or not app_id.isdigit():
        raise config.ErroConfig("config/stories.json → conferencia_instagram precisa de uid e app_id (números).")
    n = len(seq)
    esperado = json.dumps([s["esperado"] for s in seq], ensure_ascii=False)
    midias = json.dumps([s["nome"] for s in seq], ensure_ascii=False)
    return "\n".join([
        f"const uid='{uid}', appId='{app_id}';",
        "const j=await fetch('/api/v1/feed/reels_media/?reel_ids='+uid,{headers:{'X-IG-App-ID':appId}}).then(r=>r.json());",
        f"const esperado={esperado}, midias={midias};",
        f"const itens=((j.reels_media||[])[0]?.items||[]).slice(-{n});",
        "const obtido=itens.map(it=>(it.story_link_stickers||[]).length?'LINK':'sem link');",
        "const erros=esperado.map((e,i)=>obtido[i]===e?'':midias[i]+': esperado '+e+', veio '+(obtido[i]||'nada')).filter(Boolean);",
        "[...itens.map((it,i)=>new Date(it.taken_at*1000).toLocaleTimeString('pt-BR')",
        "  + ((it.story_link_stickers||[]).length?' LINK':' sem link')",
        "  + (it.story_link_stickers?.[0]?.story_link?.url?' '+it.story_link_stickers[0].story_link.url:'')",
        "  + ' (esperado '+midias[i]+': '+esperado[i]+')'),",
        f" (itens.length==={n}&&!erros.length)?'CONFERE':'NÃO CONFERE: '+(itens.length<{n}?'subiram '+itens.length+' de {n}; ':'')+erros.join('; ')];",
    ])


# ---------------------------------------------------------------- partes do texto

def _linha_letra(l: dict, com_musica: bool = False) -> str:
    midias = l.get("midias") or []
    partes = [_plural(len(midias), "mídia", "mídias")]
    com_link = [m for m in midias if m.get("figurinha")]
    if com_link:
        m = com_link[-1]
        partes.append(f"link na {m['nome']} (\"{m['figurinha'].get('texto')}\")")
    else:
        partes.append("sem link" + (" (vestido de festa)" if link.eh_vestido_de_festa(l.get("categoria")) else ""))
    if com_musica:
        for m in midias:
            mu = m.get("musica")
            if mu:
                autor = f" ({mu.get('autor')})" if mu.get("autor") else ""
                partes.append(f"música na {m['nome']}: {mu.get('nome')}{autor}")
    sku = f" ({l['sku']})" if l.get("sku") else ""
    return f"- {l['letra']} · {l.get('peca')}{sku}: " + "; ".join(partes)


def _cortes_por_letra(plano: dict) -> list[tuple[str, list[dict]]]:
    grupos: dict[str, list[dict]] = {}
    for c in plano.get("cortes") or []:
        grupos.setdefault(c.get("letra") or "?", []).append(c)
    return list(grupos.items())


def _peca_da_letra(plano: dict, letra: str, cortes: list[dict]) -> str | None:
    for c in cortes:
        if c.get("peca"):
            return c["peca"]
    for l in plano.get("letras") or []:
        if l["letra"] == letra:
            return l.get("peca")
    return None


def _cores_do_corte(c: dict) -> list[str]:
    cores = [str(x) for x in c.get("cores") or [] if str(x).strip()]
    if not cores and c.get("detalhe"):
        cores = [x.strip() for x in str(c["detalhe"]).split(",") if x.strip()]
    return cores


def linhas_cortes(plano: dict) -> list[str]:
    """Uma linha por letra com o que ficou de fora e por quê."""
    no_plano = {l["letra"] for l in plano.get("letras") or []}
    linhas = []
    for letra, cortes in _cortes_por_letra(plano):
        peca = _peca_da_letra(plano, letra, cortes)
        rotulo = f"{letra} · {peca}" if peca else f"Letra {letra}"
        inteiras = [c for c in cortes if not c.get("nome")]
        for c in inteiras:
            detalhe = str(c.get("detalhe") or "").strip()
            if c.get("motivo") == MOTIVO_POSTADO and detalhe:
                linhas.append(f"- {rotulo}: {detalhe}")
            else:
                linhas.append(f"- {rotulo}: {c.get('motivo')}" + (f" ({detalhe})" if detalhe else ""))
        midias = [c for c in cortes if c.get("nome")]
        if not midias:
            continue
        partes = []
        sem_estoque = [c for c in midias if c.get("motivo") == MOTIVO_COR]
        if sem_estoque:
            cores = list(dict.fromkeys(cor for c in sem_estoque for cor in _cores_do_corte(c)))
            partes.append(f"{', '.join(c['nome'] for c in sem_estoque)} com cor sem estoque ({', '.join(cores)}), avisar se repor")
        for c in midias:
            if c.get("motivo") == MOTIVO_COR:
                continue
            detalhe = str(c.get("detalhe") or "").strip()
            partes.append(f"{c['nome']} {c.get('motivo')}" + (f" ({detalhe})" if detalhe else ""))
        inteira = " (letra inteira fora)" if letra not in no_plano and not inteiras else ""
        linhas.append(f"- {rotulo}{inteira}: " + "; ".join(partes))
    return linhas


def _cores_para_repor(plano: dict) -> list[str]:
    saida = []
    for letra, cortes in _cortes_por_letra(plano):
        cores = list(dict.fromkeys(cor for c in cortes if c.get("motivo") == MOTIVO_COR for cor in _cores_do_corte(c)))
        if cores:
            peca = _peca_da_letra(plano, letra, cortes) or f"letra {letra}"
            saida.append(f"{', '.join(cores)} ({peca})")
    return saida


def _secao(titulo: str, linhas: list[str]) -> list[str]:
    return [titulo, *linhas] if linhas else []


def _total_midias(letras: list[dict]) -> int:
    return sum(len(l.get("midias") or []) for l in letras)


# ---------------------------------------------------------------- textos

def texto_plano(plano: dict) -> str:
    """Antes de postar: o que vai subir, o que foi cortado e por quê, o que fazer."""
    letras = plano.get("letras") or []
    modo = "ENSAIO (vai até antes de publicar)" if plano.get("ensaio", True) else "POSTAGEM REAL"
    saida = [f"Stories de {data_br(plano.get('data'))} — {modo}"]
    if letras:
        ordem = " (ordem por categorias)" if plano.get("ordem") == "categorias" else ""
        saida.append(f"Vai subir: {_plural(len(letras), 'letra', 'letras')}, {_plural(_total_midias(letras), 'mídia', 'mídias')}{ordem}")
        saida += [_linha_letra(l, com_musica=True) for l in letras]
    else:
        saida.append("Nada vai subir.")
    saida += _secao("Ficou de fora:", linhas_cortes(plano))
    saida += _secao("Avisos:", [f"- {a}" for a in plano.get("avisos") or []])
    fazer = []
    if letras and plano.get("ensaio", True):
        fazer.append("- Conferir os prints do ensaio e, se estiver tudo certo, liberar a postagem real.")
    elif letras:
        fazer.append("- Deixar o BlueStacks aberto com o Instagram da loja; o vigia posta sozinho.")
    repor = _cores_para_repor(plano)
    if repor:
        fazer.append(f"- Avisar se repor: {'; '.join(repor)}.")
    saida += _secao("O que fazer:", fazer)
    return "\n".join(saida)


def texto_resultado(plano: dict, resultado: dict) -> str:
    """Depois de postar: o que subiu, o que ficou de fora e por quê, o que fazer e o JS de conferência."""
    resultado = resultado or {}
    ensaio = bool(resultado.get("ensaio", plano.get("ensaio", True)))
    por_letra = {r.get("letra"): r for r in resultado.get("letras") or []}
    publicadas = [str(x) for x in resultado.get("publicadas") or []]
    letras = plano.get("letras") or []
    saida = [f"Stories de {data_br(plano.get('data'))} — " + ("ENSAIO (nada foi publicado)" if ensaio else "postagem")]

    subiu = [l for l in letras if l["letra"] in publicadas]
    montadas = [l for l in letras if (por_letra.get(l["letra"]) or {}).get("estado") == "ensaio_ok"]
    if ensaio:
        linhas = []
        for l in montadas:
            prints = len((por_letra.get(l["letra"]) or {}).get("prints") or [])
            linhas.append(_linha_letra(l) + (f"; {_plural(prints, 'print', 'prints')}" if prints else ""))
        saida += _secao(f"Montado até antes de publicar: {_plural(len(montadas), 'letra', 'letras')}, "
                        f"{_plural(_total_midias(montadas), 'mídia', 'mídias')}", linhas)
    else:
        saida.append(f"Subiu: {_plural(len(subiu), 'letra', 'letras')}, {_plural(_total_midias(subiu), 'mídia', 'mídias')}")
        saida += [_linha_letra(l) for l in subiu]

    nao, puladas = [], []
    for l in letras:
        r = por_letra.get(l["letra"]) or {}
        estado = r.get("estado") or "nao_iniciada"
        if l["letra"] in publicadas or (ensaio and estado == "ensaio_ok"):
            continue
        if r.get("pulada"):
            puladas.append(f"- {l['letra']} · {l.get('peca')}: pulada ({r['pulada']})")
            continue
        if estado == "nao_iniciada" and ensaio:
            texto = "não chegou a ser montada"
        else:
            texto = ESTADOS_LETRA.get(estado, estado)
        if r.get("erro"):
            texto += f": {r['erro']}"
        if estado == "falhou" and not ensaio and not r.get("incerta"):
            texto += " (nada dessa letra foi publicado)"
        nao.append(f"- {l['letra']} · {l.get('peca')}: {texto}")
    saida += _secao("Não subiu:" if not ensaio else "Não montou:", nao + puladas)
    if resultado.get("parou_em"):
        saida.append(f"Parou em: {resultado['parou_em']}")
    saida += _secao("Ficou de fora antes de postar:", linhas_cortes(plano))
    # A5: "Recentes" no lugar do álbum, ordem por data diferente, registro em postados.csv que falhou…
    saida += _secao("Avisos da postagem:", [f"- {a}" for a in resultado.get("avisos") or []])

    # falhou depois de tocar em "Seu story" (A5 marca "incerta"): pode ter subido; repetir sem conferir duplica
    incertas = [l["letra"] for l in letras if not ensaio and l["letra"] not in publicadas
                and (por_letra.get(l["letra"]) or {}).get("incerta")]
    fazer = []
    if ensaio and montadas:
        fazer.append("- Conferir os prints do ensaio e, se estiver tudo certo, liberar a postagem real.")
    if incertas:
        fazer.append(f"- Letra {', '.join(incertas)} pode ter subido: rodar o JS abaixo ANTES de repetir "
                     "(CONFERE = subiu; não mandar de novo).")
    if nao:
        fazer.append("- Ver o erro acima e " + ("repetir o ensaio." if ensaio else "mandar as letras que não subiram num novo pedido"
                                                + (" (as incertas só depois do JS)." if incertas else ".")))
    repor = _cores_para_repor(plano)
    if repor:
        fazer.append(f"- Avisar se repor: {'; '.join(repor)}.")
    saida += _secao("O que fazer:", fazer)

    if not ensaio and (subiu or incertas):
        conferir = publicadas + incertas
        saida += ["", "Conferência (rodar no console do navegador logado no Instagram; a última linha tem que ser CONFERE):",
                  js_conferencia(plano, conferir)]
    return "\n".join(saida)


def texto_interrompido(plano: dict) -> str:
    """Postagem real que terminou sem resultado (vigia caiu, PC suspendeu): não dá para saber o que subiu."""
    letras = plano.get("letras") or []
    saida = [f"Stories de {data_br(plano.get('data'))} — postagem INTERROMPIDA: não sei o que subiu.",
             f"O pedido tinha {_plural(len(letras), 'letra', 'letras')}, {_plural(_total_midias(letras), 'mídia', 'mídias')}:"]
    saida += [_linha_letra(l) for l in letras]
    saida += ["O que fazer:",
              "- NÃO mandar de novo antes de conferir: rodar o JS abaixo (todas as letras do plano, na ordem).",
              "- CONFERE = tudo subiu. 'subiram k de n' = só as k primeiras mídias da lista subiram "
              "(conferir pelos horários); mandar num novo pedido só as letras que faltam.",
              "", "Conferência (rodar no console do navegador logado no Instagram):", js_conferencia(plano)]
    return "\n".join(saida)


def _interrompido(dados: dict, pedido: dict, plano: dict) -> bool:
    """Erro sem ``resultado`` nem ``resultado_parcial`` numa postagem real: o A5 não chegou a dizer o que fez."""
    if not dados.get("erro") or dados.get("resultado") or dados.get("resultado_parcial"):
        return False
    return not (bool(pedido.get("ensaio")) or bool(plano.get("ensaio", False)))


# ---------------------------------------------------------------- terminal

def ler_pedido(id_: str, base: Path | None = None) -> tuple[str, dict]:
    """(estado, resultado da fila) de um pedido. Pendente/andamento devolvem o próprio pedido."""
    if not fila.ID_VALIDO.match(str(id_)):  # vira nome de arquivo (relatorio-<id>.txt): nada de "..\"
        raise ValueError(f"id de pedido inválido: {id_!r}")
    raiz = fila.pasta_fila(base)
    for estado in ("feito", "erro", "andamento", "pendente"):
        q = raiz / estado / f"{id_}.json"
        if q.exists():
            return estado, json.loads(q.read_text(encoding="utf-8-sig"))
    raise FileNotFoundError(f"Pedido {id_} não encontrado em {raiz}")


def texto_do_pedido(estado: str, dados: dict, so_js: bool = False) -> tuple[dict | None, str]:
    """(plano, texto) de um resultado da fila de ``stories.montar`` ou ``stories.postar``."""
    if estado in ("pendente", "andamento"):
        return None, f"Pedido {dados.get('id')} ainda está em {estado} na fila."
    pedido = dados.get("pedido") or {}
    tipo = dados.get("tipo") or pedido.get("tipo")
    erro = f"Erro no pedido: {dados['erro']}" if dados.get("erro") else ""
    if tipo == "stories.montar":
        res = dados.get("resultado") or {}
        plano = res.get("plano")
        if not plano:
            return None, erro or "Pedido sem plano."
        texto = js_conferencia(plano) if so_js else (res.get("relatorio") or texto_plano(plano))
        return plano, "\n\n".join(x for x in (erro, texto) if x)
    if tipo != "stories.postar":
        raise ValueError(f"O pedido {dados.get('id')} é do tipo {tipo}, não de stories.")
    plano = (pedido.get("args") or {}).get("plano") or {}
    if isinstance(plano, str):  # stories.postar também aceita o caminho do plano-<id>.json
        try:
            plano = json.loads(Path(plano).read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as e:
            raise ValueError(f"Não consegui ler o plano {plano}: {e}") from e
    if isinstance(plano, dict) and _interrompido(dados, pedido, plano):
        if so_js:
            return plano, js_conferencia(plano)  # todas as letras: qualquer uma pode ter subido
        return plano, "\n\n".join(x for x in (erro, texto_interrompido(plano)) if x)
    res = dict(dados.get("resultado") or dados.get("resultado_parcial") or {})
    res.setdefault("ensaio", bool(pedido.get("ensaio")))
    if so_js:
        # incerta = falhou depois de tocar em "Seu story": pode ter subido, entra no JS (igual ao relatório)
        pub = list(res.get("publicadas") or [])
        inc = [] if res.get("ensaio") else [x.get("letra") for x in res.get("letras") or []
                                            if x.get("incerta") and x.get("letra") not in pub]
        return plano, js_conferencia(plano, pub + inc)
    return plano, "\n\n".join(x for x in (erro, texto_resultado(plano, res)) if x)


def cli(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="python -m rotinas stories-relatorio", description="Relatório de um pedido de stories e JS de conferência.")
    p.add_argument("--pedido", required=True, help="id do pedido (stories.postar ou stories.montar)")
    p.add_argument("--js", action="store_true", help="só o JS de conferência")
    p.add_argument("--fila", help="pasta da fila (padrão: config/pastas.json)")
    a = p.parse_args(argv)
    try:
        estado, dados = ler_pedido(a.pedido, Path(a.fila) if a.fila else None)
        plano, texto = texto_do_pedido(estado, dados, so_js=a.js)
    except (FileNotFoundError, ValueError, config.ErroConfig) as e:
        print(f"Erro: {e}", file=sys.stderr)
        return 1
    texto = registro.ocultar(texto)
    print(texto)
    if plano and plano.get("data") and not a.js:
        try:
            destino = config.pastas().trabalho_stories / plano["data"] / f"relatorio-{a.pedido}.txt"
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_text(texto + "\n", encoding="utf-8")
        except OSError:
            pass  # o relatório já saiu na tela
    return 0 if estado in ("feito", "erro") else 1
