"""Montagem do pedido de stories (A2 + A3 + A4).

O manifesto é montado à mão no formato do contrato (não depende de pasta.py). Estoque com
``estoque.ClienteFalso``; já postados com o ``postados.py`` real (CSV em tmp_path).
"""

import hashlib
import json
import sys
import types

import pytest

from rotinas import config, tarefas
from rotinas.contexto import Contexto
from rotinas.stories import link, pedido, postados
from rotinas.stories.estoque import ClienteFalso, Produto
from rotinas.stories.pedido import ErroPedido

DATA = "2026-09-22"


def _postar_falso(args, ctx):  # dublê de stories.postar enquanto bluestacks.py (A5) não existe
    return {}


@pytest.fixture
def ambiente(cfg, monkeypatch):
    try:
        tarefas.funcao_da_tarefa("stories.postar")
    except Exception:
        monkeypatch.setitem(tarefas.TAREFAS, "stories.postar", "test_stories_pedido:_postar_falso")
    return cfg


def var(cor, estoque, tamanho="M"):
    return {"cor": cor, "tamanho": tamanho, "estoque": estoque}


def produtos():
    return [
        Produto(id=1, sku="FB-0123", nome="Vestido Midi Alça", categoria="Vestidos", preco=189.9,
                variacoes=[var("Verde", 2), var("Verde", 1, "G"), var("Preto", 0), var("Preto", 0, "G")]),
        Produto(id=2, sku="FB-0200", nome="VESTIDO LONGO DE FESTA", categoria="VESTIDO DE FESTA", preco=399.0,
                variacoes=[var("Azul", 3)]),
        Produto(id=3, sku="FB-0300", nome="Conjunto Linho", categoria="Conjuntos", preco=159.0, variacoes=[var("Bege", 1)]),
        Produto(id=4, sku="FB-0400", nome="Macacão Pantalona", categoria="Macacões", preco=209.0,
                variacoes=[var("Preto", 0), var("Vinho", 0)]),
        Produto(id=5, sku="FB-0500", nome="Blusa Ciganinha", categoria="Blusas", preco=89.0, variacoes=[var("Branca", 2)]),
    ]


def cliente():
    return ClienteFalso(produtos())


def item(cfg, data, nome, tipo, precisa_musica=False):
    ext = "mp4" if tipo == "video" else "jpg"
    caminho = cfg.p.pasta_do_dia(data) / f"{nome}.{ext}"
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_bytes(f"{data}/{nome}".encode())
    return {
        "nome": nome, "arquivo": caminho.name, "caminho": str(caminho), "tipo": tipo, "origem": f"IMG_{nome[-1]}.MOV",
        "convertido": None, "audio": ("sem_audio" if precisa_musica else "com_audio") if tipo == "video" else None,
        "precisa_musica": precisa_musica, "duracao_s": 12.3 if tipo == "video" else None, "largura": 1080,
        "altura": 1920, "hash": hashlib.sha256(caminho.read_bytes()).hexdigest(), "capturado_em": f"{data}T14:30:05",
    }


def manifesto(cfg, letras: dict, data=DATA, **extras) -> dict:
    """``letras = {"A": ["video_mudo", "foto", "foto"]}`` → grava ``manifesto.json`` e as mídias na pasta do dia."""
    man = {"data": data, "pasta": str(cfg.p.pasta_do_dia(data)), "gerado_em": f"{data}T18:30:00-03:00",
           "simulado": False, "letras": {}, "avisos": []}
    for letra, tipos in letras.items():
        midias = []
        for n, t in enumerate(tipos, 1):
            midias.append(item(cfg, data, f"{letra} - {n}", "video" if t.startswith("video") else "foto", t == "video_mudo"))
        man["letras"][letra] = {"nova": True, "folha": str(cfg.p.trabalho_stories / data / "folhas" / f"{letra}.jpg"), "midias": midias}
    man.update(extras)
    destino = cfg.p.trabalho_stories / data / "manifesto.json"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(man, ensure_ascii=False), encoding="utf-8")
    return man


def ident_a(**extras):
    return {"A": {"sku": "FB-0123", "midias": {"A - 1": ["verde"], "A - 2": ["verde"], "A - 3": ["preto"]}, **extras}}


def pendentes(cfg):
    return sorted((cfg.p.fila / "pendente").glob("*.json")) if (cfg.p.fila / "pendente").exists() else []


# ------------------------------------------------------------ estoque e figurinha

def test_cor_sem_estoque_corta_e_figurinha_vai_para_a_nova_ultima(ambiente):
    manifesto(ambiente, {"A": ["video_mudo", "foto", "foto"]})
    res = pedido.montar(DATA, ident_a(), cliente=cliente())
    plano = res["plano"]
    assert [l["letra"] for l in plano["letras"]] == ["A"]
    a = plano["letras"][0]
    assert (a["sku"], a["peca"], a["categoria"]) == ("FB-0123", "Vestido Midi Alça", "Vestidos")
    assert [m["nome"] for m in a["midias"]] == ["A - 1", "A - 2"]
    assert a["midias"][0]["figurinha"] is None
    assert a["midias"][1]["figurinha"] == {"url": "wa.me/5582988748649?text=Quero+comprar+o+Vestido+Midi+Al%C3%A7a", "texto": "Comprar"}
    assert not a["midias"][1]["figurinha"]["url"].startswith("http")
    assert a["midias"][0]["cores"] == ["Verde"]  # grafia do cadastro
    assert a["midias"][0]["precisa_musica"] is True
    assert a["midias"][0]["musica"] == config.carregar("stories")["audios_sem_som"][0]
    assert a["midias"][1]["musica"] is None
    corte = [c for c in plano["cortes"] if c["nome"] == "A - 3"][0]
    assert (corte["letra"], corte["motivo"], corte["detalhe"]) == ("A", "cor sem estoque", "Preto")
    assert "avisar se repor" in res["relatorio"]


def test_arquivos_gravados_na_pasta_de_trabalho(ambiente):
    manifesto(ambiente, {"A": ["video_mudo", "foto", "foto"]})
    res = pedido.montar(DATA, ident_a(), cliente=cliente(), id_plano="20260925-183000-stories-montar")
    trab = ambiente.p.trabalho_stories / DATA
    assert json.loads((trab / "plano-20260925-183000-stories-montar.json").read_text(encoding="utf-8")) == res["plano"]
    ident = json.loads((trab / "identificacao.json").read_text(encoding="utf-8"))
    assert ident["A"]["midias"]["A - 3"] == ["preto"]
    assert (trab / "relatorio-20260925-183000-stories-montar.txt").read_text(encoding="utf-8").startswith("Stories de 22/09/2026")
    assert res["plano"]["id"] == "20260925-183000-stories-montar"


def test_modelo_zerado_fica_de_fora(ambiente):
    manifesto(ambiente, {"A": ["video_mudo", "foto", "foto"], "B": ["foto", "foto"]})
    ident = {**ident_a(), "B": {"termo": "Macacão Pantalona", "midias": {"B - 1": ["preto"], "B - 2": ["vinho"]}}}
    plano = pedido.montar(DATA, ident, cliente=cliente())["plano"]
    assert [l["letra"] for l in plano["letras"]] == ["A"]
    cb = [c for c in plano["cortes"] if c["letra"] == "B"]
    assert len(cb) == 1 and cb[0]["nome"] is None and cb[0]["motivo"] == "modelo sem nenhuma peça"


def test_todas_as_cores_sem_estoque_tira_a_letra(ambiente):
    manifesto(ambiente, {"A": ["foto", "foto"]})
    ident = {"A": {"sku": "FB-0123", "midias": {"A - 1": ["preto"], "A - 2": ["preto"]}}}
    res = pedido.montar(DATA, ident, cliente=cliente())
    assert res["plano"]["letras"] == [] and res["pedido_postagem"] is None
    assert {c["nome"] for c in res["plano"]["cortes"]} == {"A - 1", "A - 2"}
    assert pendentes(ambiente) == []
    assert "Nada vai subir" in res["relatorio"]


def test_excluir_midia(ambiente):
    manifesto(ambiente, {"A": ["video_mudo", "foto", "foto"]})
    ident = {"A": {"sku": "FB-0123", "midias": {"A - 1": ["verde"], "A - 2": ["verde"]}, "excluir": {"A - 3": "tremida"}}}
    plano = pedido.montar(DATA, ident, cliente=cliente())["plano"]
    assert [m["nome"] for m in plano["letras"][0]["midias"]] == ["A - 1", "A - 2"]
    assert plano["cortes"][0]["nome"] == "A - 3" and plano["cortes"][0]["detalhe"] == "tremida"


def test_musica_escolhida_na_identificacao(ambiente):
    manifesto(ambiente, {"A": ["video_mudo", "foto", "foto"]})
    plano = pedido.montar(DATA, ident_a(musica=3), cliente=cliente())["plano"]
    assert plano["letras"][0]["midias"][0]["musica"] == config.carregar("stories")["audios_sem_som"][3]
    obj = {"nome": "Áudio original", "autor": "fulana", "busca": "fulana"}
    plano = pedido.montar(DATA, ident_a(musica=obj), cliente=cliente())["plano"]
    assert plano["letras"][0]["midias"][0]["musica"] == obj


def test_video_com_audio_nao_recebe_musica(ambiente):
    manifesto(ambiente, {"A": ["video", "foto", "foto"]})
    plano = pedido.montar(DATA, ident_a(), cliente=cliente())["plano"]
    v = plano["letras"][0]["midias"][0]
    assert (v["tipo"], v["precisa_musica"], v["musica"]) == ("video", False, None)


# ------------------------------------------------------------ já postado

def registrar(data, letra, sku, hash_="0" * 64):
    postados.registrar(data, letra, sku, "Vestido Midi Alça",
                       [{"nome": f"{letra} - 2", "arquivo": f"{letra} - 2.jpg", "cores": ["Verde"], "hash": hash_}], "p1")


def test_ja_postado_bloqueia_a_letra_inteira(ambiente):
    manifesto(ambiente, {"A": ["video_mudo", "foto", "foto"]})
    registrar("2026-09-20", "B", "FB-0123")
    res = pedido.montar(DATA, ident_a(), cliente=cliente())
    plano = res["plano"]
    assert plano["letras"] == [] and res["pedido_postagem"] is None
    c = [c for c in plano["cortes"] if c["motivo"] == "já postado"][0]
    assert c["letra"] == "A" and c["nome"] is None
    assert "20/09/2026" in c["detalhe"] and "letra B" in c["detalhe"]
    assert "20/09/2026" in res["relatorio"]


def test_permitir_repeticao(ambiente):
    manifesto(ambiente, {"A": ["video_mudo", "foto", "foto"]})
    registrar("2026-09-20", "B", "FB-0123")
    plano = pedido.montar(DATA, ident_a(), cliente=cliente(), permitir_repeticao=["a"])["plano"]
    assert [l["letra"] for l in plano["letras"]] == ["A"]
    assert not [c for c in plano["cortes"] if c["motivo"] == "já postado"]
    assert any("repetição permitida" in a for a in plano["avisos"])


def test_mesma_midia_em_outra_pasta_bloqueia(ambiente):
    man = manifesto(ambiente, {"A": ["video_mudo", "foto", "foto"]})
    outra = ambiente.p.pasta_do_dia("2026-09-15")
    outra.mkdir(parents=True)
    (outra / "C - 2.jpg").write_bytes(open(man["letras"]["A"]["midias"][1]["caminho"], "rb").read())
    plano = pedido.montar(DATA, ident_a(), cliente=cliente())["plano"]
    assert plano["letras"] == []
    assert "15/09/2026" in plano["cortes"][-1]["detalhe"]


def test_letra_ja_postada_neste_dia_fica_de_fora(ambiente):
    manifesto(ambiente, {"A": ["video_mudo", "foto", "foto"], "B": ["foto"]})
    registrar(DATA, "A", "FB-0123")
    ident = {**ident_a(), "B": {"sku": "FB-0300", "midias": {"B - 1": ["bege"]}}}
    plano = pedido.montar(DATA, ident, cliente=cliente())["plano"]
    assert [l["letra"] for l in plano["letras"]] == ["B"]
    c = [c for c in plano["cortes"] if c["letra"] == "A"][0]
    assert c["motivo"] == "já postado" and "22/09/2026" in c["detalhe"]


def test_mesmo_modelo_em_duas_letras_fica_so_na_primeira(ambiente):
    manifesto(ambiente, {"A": ["foto"], "B": ["foto"]})
    ident = {"A": {"sku": "FB-0300", "midias": {"A - 1": ["bege"]}}, "B": {"termo": "Conjunto Linho", "midias": {"B - 1": ["bege"]}}}
    plano = pedido.montar(DATA, ident, cliente=cliente())["plano"]
    assert [l["letra"] for l in plano["letras"]] == ["A"]
    c = plano["cortes"][0]
    assert (c["letra"], c["motivo"]) == ("B", "modelo repetido no pedido") and "letra A" in c["detalhe"]
    plano = pedido.montar(DATA, ident, cliente=cliente(), permitir_repeticao=["B"])["plano"]
    assert [l["letra"] for l in plano["letras"]] == ["A", "B"]


def test_repeticao_permitida_de_letra_ja_postada_hoje_vai_com_repostar(ambiente):
    # sem "repostar" o stories.postar (A5) pula a letra que já está em postados.csv e nada sobe
    manifesto(ambiente, {"A": ["video_mudo", "foto", "foto"], "B": ["foto"]})
    registrar(DATA, "A", "FB-0123")
    ident = {**ident_a(), "B": {"sku": "FB-0300", "midias": {"B - 1": ["bege"]}}}
    res = pedido.montar(DATA, ident, cliente=cliente(), permitir_repeticao=["A"], ensaio=False)
    assert [l["letra"] for l in res["plano"]["letras"]] == ["A", "B"]
    p = json.loads(pendentes(ambiente)[0].read_text(encoding="utf-8"))
    assert p["args"]["repostar"] == ["A"]
    ja = postados.letras_postadas(DATA) - set(p["args"]["repostar"])
    assert not ({"A", "B"} & ja)  # mesma conta que bluestacks.executar faz para pular


def test_montar_real_duas_vezes_nao_duplica_a_postagem(ambiente):
    manifesto(ambiente, {"A": ["video_mudo", "foto", "foto"]})
    pedido.montar(DATA, ident_a(), cliente=cliente(), ensaio=False)
    with pytest.raises(ErroPedido, match="Já existe postagem REAL"):
        pedido.montar(DATA, ident_a(), cliente=cliente(), ensaio=False)
    assert len(pendentes(ambiente)) == 1
    pedido.montar(DATA, ident_a(), cliente=cliente())  # ensaio não publica: pode
    assert len(pendentes(ambiente)) == 2


def test_letra_acima_do_maximo_para_antes_da_fila(ambiente):
    ambiente.alterar("stories", max_midias_por_letra=2)
    manifesto(ambiente, {"A": ["foto", "foto", "foto"]})
    ident = {"A": {"sku": "FB-0123", "midias": {"A - 1": ["verde"], "A - 2": ["verde"], "A - 3": ["verde"]}}}
    with pytest.raises(ErroPedido, match="max_midias_por_letra"):
        pedido.montar(DATA, ident, cliente=cliente())
    assert pendentes(ambiente) == []


def test_nome_de_midia_em_minusculas_na_identificacao(ambiente):
    manifesto(ambiente, {"A": ["video_mudo", "foto", "foto"]})
    ident = {"a": {"sku": "FB-0123", "midias": {"a - 1": ["verde"], "A - 2.JPG": ["verde"], "a - 3": ["preto"]}}}
    plano = pedido.montar(DATA, ident, cliente=cliente())["plano"]
    assert [m["nome"] for m in plano["letras"][0]["midias"]] == ["A - 1", "A - 2"]


# ------------------------------------------------------------ ordem

def test_ordem_por_categorias_e_rodizio(ambiente):
    manifesto(ambiente, {"A": ["video_mudo", "foto", "foto"], "B": ["video_mudo", "foto"], "C": ["video_mudo", "foto"], "D": ["foto"]})
    ident = {
        **ident_a(),
        "B": {"sku": "FB-0200", "midias": {"B - 1": ["azul"], "B - 2": ["azul"]}},
        "C": {"sku": "FB-0300", "midias": {"C - 1": ["bege"], "C - 2": ["bege"]}},
        "D": {"sku": "FB-0500", "midias": {"D - 1": ["branca"]}},
    }
    plano = pedido.montar(DATA, ident, cliente=cliente(), ordem="categorias")["plano"]
    assert plano["ordem"] == "categorias"
    assert [l["letra"] for l in plano["letras"]] == ["C", "A", "B", "D"]  # conjuntos → vestidos → festa → fora da lista
    assert any("Letra D" in a and "Blusas" in a and "fim" in a for a in plano["avisos"])
    fig = {l["letra"]: l["midias"][-1]["figurinha"] for l in plano["letras"]}
    assert fig["B"] is None  # vestido de festa: sem link (config false)
    assert all(m["figurinha"] is None for l in plano["letras"] for m in l["midias"][:-1])
    assert [fig[x]["texto"] for x in ("C", "A", "D")] == ["Comprar", "Comprar agora", "Comprar pelo Whatsapp"]
    audios = config.carregar("stories")["audios_sem_som"]
    assert [l["midias"][0]["musica"] for l in plano["letras"][:3]] == audios[:3]


def test_ordem_por_letras(ambiente):
    manifesto(ambiente, {"A": ["foto"], "B": ["foto"]})
    ident = {"B": {"sku": "FB-0300", "midias": {"B - 1": ["bege"]}}, "A": {"sku": "FB-0500", "midias": {"A - 1": ["branca"]}}}
    plano = pedido.montar(DATA, ident, cliente=cliente())["plano"]
    assert [l["letra"] for l in plano["letras"]] == ["A", "B"]


def test_vestido_de_festa_nao_confirmado_propaga(ambiente):
    ambiente.alterar("stories", link_em_vestido_de_festa=None)
    manifesto(ambiente, {"B": ["foto"]})
    with pytest.raises(link.ErroRegra, match="Regra não confirmada"):
        pedido.montar(DATA, {"B": {"sku": "FB-0200", "midias": {"B - 1": ["azul"]}}}, cliente=cliente())
    assert pendentes(ambiente) == []


def test_vestido_de_festa_com_link_se_confirmado(ambiente):
    ambiente.alterar("stories", link_em_vestido_de_festa=True)
    manifesto(ambiente, {"B": ["foto"]})
    plano = pedido.montar(DATA, {"B": {"sku": "FB-0200", "midias": {"B - 1": ["azul"]}}}, cliente=cliente())["plano"]
    assert plano["letras"][0]["peca"] == "Vestido Longo de Festa"  # cadastro em CAIXA ALTA
    assert plano["letras"][0]["midias"][0]["figurinha"]["url"].endswith("Quero+comprar+o+Vestido+Longo+de+Festa")


# ------------------------------------------------------------ fila

def test_pedido_na_fila_em_ensaio_por_padrao(ambiente):
    manifesto(ambiente, {"A": ["video_mudo", "foto", "foto"]})
    res = pedido.montar(DATA, ident_a(), cliente=cliente())
    assert res["plano"]["ensaio"] is True
    [arq] = pendentes(ambiente)
    assert arq.stem == res["pedido_postagem"] and DATA in arq.stem
    p = json.loads(arq.read_text(encoding="utf-8"))
    assert (p["tipo"], p["ensaio"]) == ("stories.postar", True)
    assert p["args"] == {"plano": res["plano"]}
    assert res["pedido_postagem"] in res["relatorio"]


def test_pedido_real_e_sem_postar(ambiente):
    manifesto(ambiente, {"A": ["video_mudo", "foto", "foto"]})
    res = pedido.montar(DATA, ident_a(), cliente=cliente(), ensaio=False)
    p = json.loads(pendentes(ambiente)[0].read_text(encoding="utf-8"))
    assert p["ensaio"] is False and res["plano"]["ensaio"] is False
    res = pedido.montar(DATA, ident_a(), cliente=cliente(), postar=False)
    assert res["pedido_postagem"] is None and len(pendentes(ambiente)) == 1


# ------------------------------------------------------------ erros de identificação

def test_erro_de_identificacao_junta_os_problemas(ambiente):
    manifesto(ambiente, {"A": ["video_mudo", "foto", "foto"], "B": ["foto"]})
    ident = {
        "A": {"sku": "FB-0123", "midias": {"A - 1": ["verde"], "A - 2": [], "A - 9": ["verde"]}},
        "B": {"midias": {"B - 1": ["bege"]}},
        "Z": {"sku": "FB-0300", "midias": {}},
    }
    with pytest.raises(ErroPedido) as e:
        pedido.montar(DATA, ident, cliente=cliente())
    texto = str(e.value)
    assert "A - 2 sem cor" in texto
    assert "A - 9 não existe" in texto
    assert "A - 3 sem identificação" in texto
    assert "Letra B: falta o SKU ou o termo" in texto
    assert "Letra Z não existe" in texto
    assert len(e.value.problemas) == 5
    assert pendentes(ambiente) == []
    assert not list((ambiente.p.trabalho_stories / DATA).glob("plano-*.json"))


def test_cor_inexistente_vira_erro_sem_cortar(ambiente):
    manifesto(ambiente, {"A": ["video_mudo", "foto", "foto"]})
    ident = ident_a()
    ident["A"]["midias"]["A - 2"] = ["roxo"]
    with pytest.raises(ErroPedido, match="Letra A"):
        pedido.montar(DATA, ident, cliente=cliente())
    assert pendentes(ambiente) == []


def test_musica_invalida(ambiente):
    manifesto(ambiente, {"A": ["video_mudo", "foto", "foto"]})
    with pytest.raises(ErroPedido, match="música 99 não existe"):
        pedido.montar(DATA, ident_a(musica=99), cliente=cliente())


def _foto_da_pasta_do_dia(cfg, data=DATA):
    """Estado da pasta do dia do usuário: {nome: bytes} (para provar que nada mudou)."""
    dia = cfg.p.pasta_do_dia(data)
    return {q.relative_to(dia).as_posix(): q.read_bytes() for q in sorted(dia.rglob("*")) if q.is_file()}


def test_so_manifesto_simulado_e_recusado_sem_mexer_na_pasta(ambiente, monkeypatch):
    """Achado #1: só com manifesto-simulado.json, o montar (mesmo em ensaio) não roda o preparar real."""
    man = manifesto(ambiente, {"A": ["video_mudo", "foto", "foto"]}, simulado=True)
    trabalho = ambiente.p.trabalho_stories / DATA
    (trabalho / "manifesto.json").rename(trabalho / "manifesto-simulado.json")
    dia = ambiente.p.pasta_do_dia(DATA)
    (dia / "IMG_0001.MOV").write_bytes(b"bruto do usuario")  # mídia ainda sem nome, como antes do preparar
    antes = _foto_da_pasta_do_dia(ambiente)
    chamadas = []

    def preparar(data, simular=False, grupos=None):  # como o real: renomeia as mídias soltas da pasta do dia
        chamadas.append((data, simular, grupos))
        (dia / "IMG_0001.MOV").rename(dia / "B - 1.mov")
        return man

    falso = types.ModuleType("rotinas.stories.pasta")
    falso.preparar = preparar
    import rotinas.stories as pacote

    monkeypatch.setitem(sys.modules, "rotinas.stories.pasta", falso)
    monkeypatch.setattr(pacote, "pasta", falso, raising=False)
    with pytest.raises(ErroPedido, match="manifesto-simulado.json") as e:
        pedido.montar(DATA, ident_a(), ensaio=True, cliente=cliente())
    assert "stories-preparar --data 2026-09-22" in str(e.value) and "SEM simular" in str(e.value)
    assert chamadas == []
    assert _foto_da_pasta_do_dia(ambiente) == antes
    assert not (trabalho / "manifesto.json").exists()
    assert pendentes(ambiente) == []


def test_midia_sumida_da_pasta(ambiente):
    man = manifesto(ambiente, {"A": ["video_mudo", "foto", "foto"]})
    import os

    os.remove(man["letras"]["A"]["midias"][1]["caminho"])
    with pytest.raises(ErroPedido, match="stories-preparar"):
        pedido.montar(DATA, ident_a(), cliente=cliente())


def test_letra_sem_identificacao_vira_aviso(ambiente):
    manifesto(ambiente, {"A": ["video_mudo", "foto", "foto"], "B": ["foto"]})
    plano = pedido.montar(DATA, ident_a(), cliente=cliente())["plano"]
    assert "Letra B sem identificação: ficou de fora" in plano["avisos"]


def test_sem_manifesto_nao_prepara_a_pasta(ambiente, monkeypatch):
    """Achado #1: o montar nunca prepara a pasta; sem manifesto.json pede o stories.preparar real."""
    chamadas = []

    def preparar(data, simular=False, grupos=None):
        chamadas.append(data)
        return manifesto(ambiente, {"A": ["video_mudo", "foto", "foto"]})

    falso = types.ModuleType("rotinas.stories.pasta")
    falso.preparar = preparar
    import rotinas.stories as pacote

    monkeypatch.setitem(sys.modules, "rotinas.stories.pasta", falso)
    monkeypatch.setattr(pacote, "pasta", falso, raising=False)
    with pytest.raises(ErroPedido, match="Sem manifesto.json") as e:
        pedido.montar(DATA, ident_a(), cliente=cliente())
    assert "manifesto-simulado" not in str(e.value)
    assert chamadas == []


# ------------------------------------------------------------ tarefa e terminal

def test_tarefa_usa_id_do_pedido_e_ensaio(ambiente, monkeypatch, tmp_path):
    manifesto(ambiente, {"A": ["video_mudo", "foto", "foto"]})
    monkeypatch.setattr(pedido.estoque, "cliente_padrao", cliente)
    ctx = Contexto(tmp_path / "saida", ensaio=False, id_pedido="20260925-183000-stories-montar")
    res = pedido.tarefa({"data": DATA, "identificacao": ident_a()}, ctx)
    assert res["plano"]["id"] == "20260925-183000-stories-montar"
    assert res["plano"]["ensaio"] is True  # sem "ensaio": false explícito, é ensaio
    assert (tmp_path / "saida" / "plano.json").exists() and (tmp_path / "saida" / "relatorio.txt").exists()
    ctx2 = Contexto(tmp_path / "saida2", ensaio=True, id_pedido="20260925-183100-stories-montar")
    assert pedido.tarefa({"data": DATA, "identificacao": ident_a(), "ensaio": False}, ctx2)["plano"]["ensaio"] is True
    ctx3 = Contexto(tmp_path / "saida3", ensaio=False, id_pedido="20260925-183200-stories-montar")
    assert pedido.tarefa({"data": DATA, "identificacao": ident_a(), "ensaio": False}, ctx3)["plano"]["ensaio"] is False



def test_diagnostico_do_montar_vai_para_o_postar(ambiente, monkeypatch, tmp_path):
    """Achado #4: ``diagnostico`` do stories.montar (no pedido ou nos args) vale para o stories.postar gerado."""
    manifesto(ambiente, {"A": ["video_mudo", "foto", "foto"]})
    monkeypatch.setattr(pedido.estoque, "cliente_padrao", cliente)

    def postar_gerado(res):
        return json.loads((ambiente.p.fila / "pendente" / f"{res['pedido_postagem']}.json").read_text(encoding="utf-8"))

    ctx = Contexto(tmp_path / "s1", ensaio=False, diagnostico=True, id_pedido="20260925-184000-stories-montar")
    res = pedido.tarefa({"data": DATA, "identificacao": ident_a()}, ctx)
    assert postar_gerado(res)["diagnostico"] is True
    assert "com diagnóstico" in res["relatorio"]
    ctx = Contexto(tmp_path / "s2", ensaio=False, id_pedido="20260925-184100-stories-montar")
    assert postar_gerado(pedido.tarefa({"data": DATA, "identificacao": ident_a(), "diagnostico": True}, ctx))["diagnostico"] is True
    ctx = Contexto(tmp_path / "s3", ensaio=False, id_pedido="20260925-184200-stories-montar")
    assert postar_gerado(pedido.tarefa({"data": DATA, "identificacao": ident_a()}, ctx))["diagnostico"] is False

def test_cli_com_estoque_falso(ambiente, monkeypatch, tmp_path, capsys):
    manifesto(ambiente, {"A": ["video_mudo", "foto", "foto"]})
    falso = tmp_path / "estoque.json"
    falso.write_text(json.dumps({"produtos": [p.como_dict() for p in produtos()]}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("ROTINAS_ESTOQUE_FALSO", str(falso))
    arq = tmp_path / "identificação.json"
    arq.write_text(json.dumps(ident_a(), ensure_ascii=False), encoding="utf-8")
    assert pedido.cli(["--data", DATA, "--identificacao", str(arq)]) == 0
    saida = capsys.readouterr().out
    assert "ENSAIO" in saida and "A · Vestido Midi Alça" in saida
    p = json.loads(pendentes(ambiente)[0].read_text(encoding="utf-8"))
    assert p["ensaio"] is True
    assert pedido.cli(["--data", DATA, "--identificacao", str(arq), "--real", "--sem-postar"]) == 0
    assert "POSTAGEM REAL" in capsys.readouterr().out
    assert len(pendentes(ambiente)) == 1


def test_cli_erro_curto(ambiente, tmp_path, capsys):
    manifesto(ambiente, {"A": ["video_mudo", "foto", "foto"]})
    arq = tmp_path / "ident.json"
    arq.write_text(json.dumps({"A": {"sku": "FB-0123", "midias": {}}}), encoding="utf-8")
    assert pedido.cli(["--data", DATA, "--identificacao", str(arq)]) == 1
    assert "sem identificação" in capsys.readouterr().err


def test_cli_erro_do_registro_sai_curto(ambiente, tmp_path, capsys, monkeypatch):
    manifesto(ambiente, {"A": ["video_mudo", "foto", "foto"]})
    arq = tmp_path / "ident.json"
    arq.write_text(json.dumps(ident_a()), encoding="utf-8")

    def preso(data):
        raise postados.ErroPostados("postados.csv está aberto no Excel")

    monkeypatch.setattr(pedido.postados, "letras_postadas", preso)
    assert pedido.cli(["--data", DATA, "--identificacao", str(arq)]) == 1
    assert "aberto no Excel" in capsys.readouterr().err
