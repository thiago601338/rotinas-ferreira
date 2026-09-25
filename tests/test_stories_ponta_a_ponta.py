"""Stories de ponta a ponta: pasta do dia com mídias soltas → pedido ``stories.postar`` na fila, sem clique.

Critério de aceite (BRIEFING): "uma pasta de data vai de mídias soltas a pedido na fila sem clique, com
cortes de estoque e bloqueio de repetição corretos". Usa os módulos reais (pasta, estoque, postados,
link, pedido, relatorio); só o banco é falso (``estoque.ClienteFalso``) e a "IA" é um dicionário.
O vigia e o BlueStacks NÃO rodam: o critério termina no pedido gravado em ``fila/pendente``.
"""

import json
import shutil
from datetime import datetime, timezone

import pytest

import sintetico
from rotinas import fila, midia, tarefas
from rotinas.stories import bluestacks, pasta, pedido, postados, relatorio
from rotinas.stories.estoque import ClienteFalso, Produto

pytestmark = pytest.mark.ffmpeg

DATA = "2026-09-22"
OUTRA_DATA = "2026-09-15"  # pasta antiga que já tem uma das fotos de hoje
NOVA_DATA = "2026-09-23"  # o mesmo lote copiado para outro dia
LINK_A = "wa.me/5582988748649?text=Quero+comprar+o+Vestido+Midi+Al%C3%A7a"
LINK_E = "wa.me/5582988748649?text=Quero+comprar+a+Saia+Midi+Plissada"

# arquivo solto → (letra esperada, arquivo final)
RENOMEACAO = {
    "IMG_0001.MOV": ("A", "A - 1.mp4"),  # vestido: vídeo sem áudio
    "IMG_0002.JPG": ("A", "A - 2.jpg"),
    "IMG_0003.JPG": ("A", "A - 3.jpg"),
    "IMG_0004.JPG": ("A", "A - 4.jpg"),  # cor preta, zerada
    "IMG_0010.JPG": ("B", "B - 1.jpg"),  # macacão sem nenhuma peça
    "IMG_0011.JPG": ("B", "B - 2.jpg"),
    "IMG_0020.JPG": ("C", "C - 1.jpg"),  # conjunto já postado em 18/09 (postados.csv)
    "IMG_0021.JPG": ("C", "C - 2.jpg"),
    "IMG_0030.JPG": ("D", "D - 1.jpg"),
    "IMG_0031.JPG": ("D", "D - 2.jpg"),  # mesma foto da pasta de 15/09
    "IMG_0040.MOV": ("E", "E - 1.mp4"),  # saia limpa: vídeo com áudio
    "IMG_0041.JPG": ("E", "E - 2.jpg"),
    "IMG_0050.JPG": ("F", "F - 1.jpg"),  # vestido de festa: sem figurinha
}

# o que a IA "identifica" olhando as folhas de contato
IDENTIFICACAO = {
    "A": {"sku": "FB-0123", "midias": {"A - 1": ["verde"], "A - 2": ["verde"], "A - 3": ["verde"], "A - 4": ["preto"]}},
    "B": {"termo": "Macacão Pantalona", "midias": {"B - 1": ["preto"], "B - 2": ["vinho"]}},
    "C": {"sku": "FB-0300", "midias": {"C - 1": ["bege"], "C - 2": ["bege"]}},
    "D": {"sku": "FB-0500", "midias": {"D - 1": ["branca"], "D - 2": ["branca"]}},
    "E": {"sku": "FB-0600", "midias": {"E - 1": ["preta"], "E - 2": ["preta"]}},
    "F": {"sku": "FB-0200", "midias": {"F - 1": ["azul"]}},
}


def var(cor, estoque, tamanho="M"):
    return {"cor": cor, "tamanho": tamanho, "estoque": estoque}


def cliente():
    return ClienteFalso([
        Produto(id=1, sku="FB-0123", nome="Vestido Midi Alça", categoria="Vestidos", preco=189.9,
                variacoes=[var("Verde", 2), var("Verde", 1, "G"), var("Preto", 0), var("Preto", 0, "G")]),
        Produto(id=2, sku="FB-0400", nome="Macacão Pantalona", categoria="Macacões", preco=209.0,
                variacoes=[var("Preto", 0), var("Vinho", 0)]),
        Produto(id=3, sku="FB-0300", nome="Conjunto Linho", categoria="Conjuntos", preco=159.0, variacoes=[var("Bege", 1)]),
        Produto(id=4, sku="FB-0500", nome="Blusa Ciganinha", categoria="Blusas", preco=89.0, variacoes=[var("Branca", 2)]),
        Produto(id=5, sku="FB-0600", nome="SAIA MIDI PLISSADA", categoria="Saias", preco=129.0, variacoes=[var("Preta", 3)]),
        Produto(id=6, sku="FB-0200", nome="Vestido Longo de Festa", categoria="VESTIDO DE FESTA", preco=399.0,
                variacoes=[var("Azul", 1)]),
    ])


def hora(h, m):
    return datetime(2026, 9, 22, h, m)


def utc(local):
    """``creation_time`` do vídeo vai em UTC; a data de captura volta no fuso local."""
    return local.astimezone(timezone.utc).replace(tzinfo=None)


def retrato(dir_):
    """nome → sha256 de cada arquivo solto (antes de preparar)."""
    return {p.name: midia.hash_arquivo(p) for p in sorted(dir_.iterdir()) if p.is_file()}


def montar_cenario(cfg):
    """Pasta do dia só com arquivos soltos do celular (peças separadas por mais de 10 min) + histórico."""
    dia = cfg.p.pasta_do_dia(DATA)
    dia.mkdir(parents=True)
    sintetico.video(dia / "IMG_0001.MOV", audio=None, criado_em=utc(hora(14, 0)))
    sintetico.foto(dia / "IMG_0002.JPG", cor=(20, 140, 20), tirada_em=hora(14, 1))
    sintetico.foto(dia / "IMG_0003.JPG", cor=(20, 150, 20), tirada_em=hora(14, 2))
    sintetico.foto(dia / "IMG_0004.JPG", cor=(10, 10, 10), tirada_em=hora(14, 3))
    sintetico.foto(dia / "IMG_0010.JPG", cor=(15, 15, 15), tirada_em=hora(14, 30))
    sintetico.foto(dia / "IMG_0011.JPG", cor=(110, 10, 30), tirada_em=hora(14, 31))
    sintetico.foto(dia / "IMG_0020.JPG", cor=(220, 200, 160), tirada_em=hora(15, 0))
    sintetico.foto(dia / "IMG_0021.JPG", cor=(225, 205, 165), tirada_em=hora(15, 1))
    sintetico.foto(dia / "IMG_0030.JPG", cor=(250, 250, 250), tirada_em=hora(15, 30))
    sintetico.foto(dia / "IMG_0031.JPG", cor=(245, 245, 245), tirada_em=hora(15, 31))
    sintetico.video(dia / "IMG_0040.MOV", audio="tom", cor="black", criado_em=utc(hora(16, 0)))
    sintetico.foto(dia / "IMG_0041.JPG", cor=(5, 5, 5), tirada_em=hora(16, 1))
    sintetico.foto(dia / "IMG_0050.JPG", cor=(20, 40, 200), tirada_em=hora(16, 30))

    # a foto IMG_0031 já foi usada na pasta de 15/09 (letra C de lá)
    antiga = cfg.p.pasta_do_dia(OUTRA_DATA)
    antiga.mkdir(parents=True)
    sintetico.foto(antiga / "C - 1.jpg", cor=(1, 2, 3), tirada_em=datetime(2026, 9, 15, 10, 0))
    shutil.copy2(dia / "IMG_0031.JPG", antiga / "C - 2.jpg")

    # o conjunto (FB-0300) já foi postado em 18/09
    postados.registrar("2026-09-18", "B", "FB-0300", "Conjunto Linho",
                       [{"arquivo": "B - 1.jpg", "cores": ["Bege"], "hash": "f" * 64}], "pedido-antigo")
    return dia


def pendentes(cfg):
    return sorted((cfg.p.fila / "pendente").glob("*.json"))


@pytest.fixture
def sem_vigia(monkeypatch):
    """Prova de que o critério não depende do vigia nem do BlueStacks: qualquer chamada falha o teste."""
    def proibido(*a, **k):
        raise AssertionError("o vigia/BlueStacks não pode rodar para montar o pedido")

    monkeypatch.setattr(bluestacks, "tarefa", proibido)
    monkeypatch.setattr(fila.Vigia, "processar", proibido)
    monkeypatch.setattr(fila.Vigia, "rodar", proibido)


def preparar_e_montar(cfg):
    """Passos sem clique: preparar a pasta → IA identifica → montar (ensaio padrão)."""
    dia = montar_cenario(cfg)
    antes = retrato(dia)
    manifesto = pasta.preparar(DATA)
    res = pedido.montar(DATA, IDENTIFICACAO, cliente=cliente())
    return dia, antes, manifesto, res


def publicar_de_verdade(plano, id_pedido):
    """O que o A5 faz depois de publicar cada letra (``bluestacks._registrar``)."""
    for L in plano["letras"]:
        midias = [{"nome": m["nome"], "arquivo": m["arquivo"], "cores": m["cores"], "hash": m["hash"]} for m in L["midias"]]
        assert postados.registrar(plano["data"], L["letra"], L["sku"], L["peca"], midias, id_pedido) == len(midias)


# ------------------------------------------------------------------ o critério de aceite

def test_pasta_solta_vira_pedido_na_fila_sem_clique(cfg, sem_vigia):
    dia, antes, manifesto, res = preparar_e_montar(cfg)

    # 1) arquivos renomeados/convertidos; originais intactos em _originais
    assert sorted(manifesto["letras"]) == ["A", "B", "C", "D", "E", "F"]
    por_origem = {m["origem"]: (letra, m) for letra, info in manifesto["letras"].items() for m in info["midias"]}
    assert {o: (l, m["arquivo"]) for o, (l, m) in por_origem.items()} == RENOMEACAO
    for origem, (letra, arquivo) in RENOMEACAO.items():
        assert (dia / arquivo).is_file(), arquivo
        assert not (dia / origem).exists(), f"{origem} ficou solto na pasta"
        guardado = dia / "_originais" / origem
        assert midia.hash_arquivo(guardado) == antes[origem], f"original {origem} mudou"
        assert por_origem[origem][1]["hash"] == midia.hash_arquivo(dia / arquivo)
    assert por_origem["IMG_0001.MOV"][1]["convertido"] in ("remux", "recodificado")
    assert midia.sondar(dia / "A - 1.mp4").codec_video == "h264"
    assert midia.hash_arquivo(dia / "D - 2.jpg") == midia.hash_arquivo(cfg.p.pasta_do_dia(OUTRA_DATA) / "C - 2.jpg")
    a1, e1 = por_origem["IMG_0001.MOV"][1], por_origem["IMG_0040.MOV"][1]
    assert (a1["audio"], a1["precisa_musica"]) == ("sem_audio", True)
    assert (e1["audio"], e1["precisa_musica"]) == ("com_audio", False)
    trabalho = cfg.p.trabalho_stories / DATA
    assert all((trabalho / "folhas" / f"{l}.jpg").is_file() for l in manifesto["letras"])

    # 2) plano: só as mídias certas, na ordem
    plano = res["plano"]
    assert plano["ensaio"] is True and plano["data"] == DATA
    assert [l["letra"] for l in plano["letras"]] == ["A", "E", "F"]
    L = {l["letra"]: l for l in plano["letras"]}
    assert [m["nome"] for m in L["A"]["midias"]] == ["A - 1", "A - 2", "A - 3"]
    assert [m["nome"] for m in L["E"]["midias"]] == ["E - 1", "E - 2"]
    assert [m["nome"] for m in L["F"]["midias"]] == ["F - 1"]
    assert (L["A"]["sku"], L["A"]["peca"], L["A"]["categoria"]) == ("FB-0123", "Vestido Midi Alça", "Vestidos")
    assert L["E"]["peca"] == "Saia Midi Plissada"  # CAIXA ALTA do cadastro vira Título
    for l in plano["letras"]:
        for m in l["midias"]:
            assert m["caminho"] == str(dia / m["arquivo"]) and m["hash"] == midia.hash_arquivo(dia / m["arquivo"])
    assert L["A"]["midias"][0]["cores"] == ["Verde"]  # grafia do cadastro

    # 3) cortes com os motivos certos
    cortes = {(c["letra"], c["nome"]): c for c in plano["cortes"]}
    assert set(cortes) == {("A", "A - 4"), ("B", None), ("C", None), ("D", None)}
    assert (cortes[("A", "A - 4")]["motivo"], cortes[("A", "A - 4")]["detalhe"]) == ("cor sem estoque", "Preto")
    assert cortes[("B", None)]["motivo"] == "modelo sem nenhuma peça"
    c_c, c_d = cortes[("C", None)], cortes[("D", None)]
    assert c_c["motivo"] == "já postado" and "18/09/2026" in c_c["detalhe"]
    assert [o["motivo"] for o in c_c["ocorrencias"]] == ["sku"]
    assert c_d["motivo"] == "já postado" and "15/09/2026" in c_d["detalhe"] and "C - 2.jpg" in c_d["detalhe"]
    assert [o["motivo"] for o in c_d["ocorrencias"]] == ["hash_pasta"]

    # 4) música só no vídeo sem áudio; figurinha só na última mídia de cada letra, sem https://
    musica = [(m["nome"], m["musica"]) for l in plano["letras"] for m in l["midias"] if m["musica"]]
    assert musica == [("A - 1", {"busca": "fashion", "escolha": "aleatoria"})]
    assert L["E"]["midias"][0]["tipo"] == "video" and L["E"]["midias"][0]["musica"] is None
    com_fig = {m["nome"]: m["figurinha"] for l in plano["letras"] for m in l["midias"] if m["figurinha"]}
    assert com_fig == {"A - 3": {"url": LINK_A, "texto": "Comprar"}, "E - 2": {"url": LINK_E, "texto": "Comprar agora"}}
    assert "http" not in json.dumps(plano, ensure_ascii=False)  # vestido de festa (F) fica sem link

    # 5) pedido stories.postar na fila, pendente, em ensaio; nada executado
    assert res["pedido_postagem"]
    arquivos = pendentes(cfg)
    assert [p.stem for p in arquivos] == [res["pedido_postagem"]]
    p = json.loads(arquivos[0].read_text(encoding="utf-8"))
    assert (p["tipo"], p["ensaio"]) == ("stories.postar", True)
    assert p["args"]["plano"] == plano
    assert tarefas.TAREFAS["stories.postar"] == "rotinas.stories.bluestacks:tarefa"
    for estado in ("andamento", "feito", "erro"):
        assert not list((cfg.p.fila / estado).glob("*.json")), f"fila/{estado} não devia ter nada"

    # 6) arquivos de trabalho e relatório
    assert json.loads((trabalho / f"plano-{plano['id']}.json").read_text(encoding="utf-8")) == plano
    assert json.loads((trabalho / "identificacao.json").read_text(encoding="utf-8"))["A"]["midias"]["A - 4"] == ["preto"]
    texto = (trabalho / f"relatorio-{plano['id']}.txt").read_text(encoding="utf-8")
    assert texto.strip() == res["relatorio"].strip()
    assert "ENSAIO" in texto and "Vai subir: 3 letras, 6 mídias" in texto
    assert "link na A - 3" in texto and "sem link (vestido de festa)" in texto
    assert "18/09/2026" in texto and "15/09/2026" in texto and "modelo sem nenhuma peça" in texto
    assert "Avisar se repor: Preto (Vestido Midi Alça)" in texto
    assert f"Pedido de postagem na fila: {res['pedido_postagem']} (ensaio)" in texto
    js = relatorio.js_conferencia(plano)
    assert ".slice(-6)" in js
    assert 'const esperado=["sem link", "sem link", "LINK", "sem link", "LINK", "sem link"]' in js
    assert 'midias=["A - 1", "A - 2", "A - 3", "E - 1", "E - 2", "F - 1"]' in js
    assert "CONFERE" in js and "https://" not in js

    # 7) a postagem real acontece (o A5 registra) e o mesmo lote é montado de novo: tudo bloqueado
    publicar_de_verdade(plano, "pedido-real-1")
    assert postados.letras_postadas(DATA) == {"A", "E", "F"}
    fim = relatorio.texto_resultado(
        {**plano, "ensaio": False},
        {"ensaio": False, "publicadas": ["A", "E", "F"],
         "letras": [{"letra": l, "estado": "publicada"} for l in ("A", "E", "F")]},
    )
    assert "Subiu: 3 letras, 6 mídias" in fim and ".slice(-6)" in fim

    assert pasta.preparar(DATA)["letras"].keys() == manifesto["letras"].keys()  # rodar de novo não duplica
    de_novo = pedido.montar(DATA, IDENTIFICACAO, cliente=cliente())
    plano2 = de_novo["plano"]
    assert plano2["letras"] == [] and de_novo["pedido_postagem"] is None
    motivos = {c["letra"]: c["motivo"] for c in plano2["cortes"] if c["nome"] is None}
    assert motivos == {"A": "já postado", "B": "modelo sem nenhuma peça", "C": "já postado",
                       "D": "já postado", "E": "já postado", "F": "já postado"}
    assert [p.stem for p in pendentes(cfg)] == [res["pedido_postagem"]]  # nenhum pedido novo
    assert "Nada vai subir" in de_novo["relatorio"]


def test_mesmo_lote_em_outra_data_fica_bloqueado(cfg, sem_vigia):
    """Os mesmos arquivos do celular copiados para a pasta de outro dia, depois de postados: nada sobe."""
    dia, _, _, res = preparar_e_montar(cfg)
    publicar_de_verdade(res["plano"], "pedido-real-1")

    nova = cfg.p.pasta_do_dia(NOVA_DATA)
    nova.mkdir(parents=True)
    for origem in RENOMEACAO:
        shutil.copy2(dia / "_originais" / origem, nova / origem)
    manifesto = pasta.preparar(NOVA_DATA)
    assert sorted(manifesto["letras"]) == ["A", "B", "C", "D", "E", "F"]

    novo = pedido.montar(NOVA_DATA, IDENTIFICACAO, cliente=cliente())
    plano = novo["plano"]
    assert plano["letras"] == [] and novo["pedido_postagem"] is None
    cortes = {c["letra"]: c for c in plano["cortes"] if c["nome"] is None}
    assert {l: c["motivo"] for l, c in cortes.items()} == {
        "A": "já postado", "B": "modelo sem nenhuma peça", "C": "já postado",
        "D": "já postado", "E": "já postado", "F": "já postado",
    }
    for letra in ("A", "E", "F"):  # postadas em 22/09: bloqueio pelo modelo (SKU) no registro
        assert "22/09/2026" in cortes[letra]["detalhe"], cortes[letra]
        assert "sku" in {o["motivo"] for o in cortes[letra]["ocorrencias"]}
    # D nunca foi postada, mas a mesma foto está nas pastas de 15/09 e 22/09
    assert {o["data"] for o in cortes["D"]["ocorrencias"]} == {OUTRA_DATA, DATA}
    assert [p.stem for p in pendentes(cfg)] == [res["pedido_postagem"]]
