import csv
import hashlib
import json
import os

import pytest

from rotinas import midia
from rotinas.stories import postados
from rotinas.stories.postados import ErroPostados


def h(texto: str) -> str:
    return hashlib.sha256(texto.encode()).hexdigest()


def registrar_a(data="2026-09-22", letra="A", sku="FB-0123", pedido="20260922-183000-stories-montar"):
    return postados.registrar(data, letra, sku, "Vestido Midi Alça", [
        {"nome": "A - 1", "arquivo": "A - 1.mp4", "cores": ["Verde"], "hash": h("video")},
        {"nome": "A - 2", "arquivo": "A - 2.jpg", "cores": ["Verde", "Preto"], "hash": h("foto")},
    ], pedido)


def midia_em(cfg, data, nome, conteudo, sub=None):
    pasta = cfg.p.pasta_do_dia(data)
    if sub:
        pasta = pasta / sub
    pasta.mkdir(parents=True, exist_ok=True)
    arq = pasta / nome
    arq.write_bytes(conteudo.encode())
    return arq


# ------------------------------------------------------------ CSV

def test_registrar_cria_csv_com_bom_e_ponto_e_virgula(cfg):
    assert registrar_a() == 2
    arq = cfg.p.registros / "postados.csv"
    bruto = arq.read_bytes()
    assert bruto.startswith(b"\xef\xbb\xbf")
    primeira = bruto[3:].split(b"\r\n")[0].decode()
    assert primeira == "data;letra;sku;cor;arquivo;hash;peca;pedido;registrado_em"
    linhas = list(csv.reader(bruto.decode("utf-8-sig").splitlines(), delimiter=";"))
    assert linhas[1][:6] == ["2026-09-22", "A", "FB-0123", "Verde", "A - 1.mp4", h("video")]
    assert linhas[2][3] == "Verde, Preto" and linhas[2][6] == "Vestido Midi Alça"


def test_registrar_so_acrescenta_sem_segundo_bom(cfg):
    registrar_a()
    arq = cfg.p.registros / "postados.csv"
    antes = arq.read_bytes()
    assert postados.registrar("2026-09-23", "b", "FB-0200", "Macacão Pantalona",
                              [{"arquivo": "B - 1.jpg", "cores": "Preto", "hash": h("outra")}], "p2") == 1
    depois = arq.read_bytes()
    assert depois.startswith(antes)  # nada do que existia mudou
    assert depois.count(b"\xef\xbb\xbf") == 1
    lidas = postados.ler()
    assert [(l["data"], l["letra"], l["arquivo"]) for l in lidas] == [
        ("2026-09-22", "A", "A - 1.mp4"), ("2026-09-22", "A", "A - 2.jpg"), ("2026-09-23", "B", "B - 1.jpg"),
    ]
    assert lidas[2]["peca"] == "Macacão Pantalona" and lidas[2]["pedido"] == "p2" and lidas[2]["registrado_em"]


def test_registrar_valida_data_e_letra(cfg):
    with pytest.raises(ErroPostados, match="Data inválida"):
        postados.registrar("22/09/2026", "A", "X", "Y", [{"arquivo": "A - 1.jpg"}], "p")
    with pytest.raises(ErroPostados, match="Letra inválida"):
        postados.registrar("2026-09-22", "A1", "X", "Y", [{"arquivo": "A - 1.jpg"}], "p")
    assert postados.registrar("2026-09-22", "A", "X", "Y", [], "p") == 0
    assert not (cfg.p.registros / "postados.csv").exists()


def test_registrar_com_arquivo_aberto_no_excel(cfg, monkeypatch):
    registrar_a()
    chamadas = []

    def preso(caminho, linhas):
        chamadas.append(1)
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(postados, "_acrescentar", preso)
    with pytest.raises(ErroPostados) as e:
        postados.registrar("2026-09-23", "B", "FB-1", "Peça", [{"arquivo": "B - 1.jpg"}], "p", tentativas=2, espera_s=0)
    assert "Excel" in str(e.value) and "letra B de 23/09/2026" in str(e.value)
    assert len(chamadas) == 2
    assert e.value.linhas[0]["arquivo"] == "B - 1.jpg"


def test_ler_com_arquivo_aberto(cfg, monkeypatch):
    registrar_a()

    def preso(self):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(type(cfg.p.registros), "read_bytes", preso)
    with pytest.raises(ErroPostados, match="Excel"):
        postados.ler()


def test_csv_salvo_pelo_excel(cfg):
    """Excel regrava em cp1252, sem BOM, com data dd/mm/aaaa e sem quebra de linha no fim."""
    arq = cfg.p.registros / "postados.csv"
    arq.parent.mkdir(parents=True, exist_ok=True)
    texto = "data;letra;sku;cor;arquivo;hash;peca;pedido;registrado_em\r\n22/09/2026;A;FB-1;Verde;A - 1.mp4;ABC;Macacão;p1;x"
    arq.write_bytes(texto.encode("cp1252"))
    assert postados.ler()[0]["data"] == "2026-09-22"
    assert postados.ler()[0]["peca"] == "Macacão"
    assert postados.ler()[0]["hash"] == "abc"
    postados.registrar("2026-09-23", "B", "FB-2", "Calça", [{"arquivo": "B - 1.jpg", "hash": "d"}], "p2")
    lidas = postados.ler()
    assert len(lidas) == 2 and lidas[1]["letra"] == "B" and lidas[1]["peca"] == "Calça"
    assert arq.read_bytes().decode("cp1252").count("\r\n") == 3


def test_cabecalho_inesperado_nao_mexe_no_arquivo(cfg):
    arq = cfg.p.registros / "postados.csv"
    arq.parent.mkdir(parents=True, exist_ok=True)
    arq.write_text("outra;coisa\n1;2\n", encoding="utf-8")
    with pytest.raises(ErroPostados, match="cabeçalho inesperado"):
        registrar_a()
    assert arq.read_text(encoding="utf-8") == "outra;coisa\n1;2\n"


def test_ler_sem_arquivo_e_letras_postadas(cfg):
    assert postados.ler() == []
    assert postados.letras_postadas("2026-09-22") == set()
    registrar_a()
    registrar_a(letra="C", sku="FB-0300")
    registrar_a(data="2026-09-23", letra="A", sku="FB-0400")
    assert postados.letras_postadas("2026-09-22") == {"A", "C"}
    assert postados.letras_postadas("2026-09-23") == {"A"}


# ------------------------------------------------------------ verificar pelo registro

def test_verificar_sku_em_outra_data(cfg):
    registrar_a()
    oc = postados.verificar("2026-09-25", "B", "fb-0123", [])
    assert oc == [{
        "motivo": "sku", "data": "2026-09-22", "letra": "A", "arquivo": "A - 1.mp4",
        "texto": "modelo FB-0123 já postado em 22/09/2026, letra A (A - 1.mp4)",
    }]


def test_verificar_mesma_letra_no_mesmo_dia_nao_bloqueia_a_si_mesma(cfg):
    registrar_a()
    assert postados.verificar("2026-09-22", "A", "FB-0123", [h("video"), h("foto")]) == []


def test_verificar_mesmo_dia_outra_letra(cfg):
    registrar_a()
    oc = postados.verificar("2026-09-22", "D", "FB-0123", [])
    assert [(o["motivo"], o["data"], o["letra"]) for o in oc] == [("sku", "2026-09-22", "A")]


def test_verificar_hash_no_registro(cfg):
    registrar_a()
    oc = postados.verificar("2026-09-25", "B", "FB-9999", [h("foto").upper(), h("nada")])
    assert len(oc) == 1
    assert oc[0]["motivo"] == "hash_registro" and oc[0]["arquivo"] == "A - 2.jpg" and oc[0]["hash"] == h("foto")
    assert oc[0]["texto"] == "mesma mídia já postada em 22/09/2026, letra A (A - 2.jpg)"


def test_verificar_sku_e_hash_na_mesma_postagem_da_uma_ocorrencia(cfg):
    registrar_a()
    oc = postados.verificar("2026-09-25", "B", "FB-0123", [h("video"), h("foto")])
    assert [o["motivo"] for o in oc] == ["sku"]


def test_verificar_sem_nada(cfg):
    registrar_a()
    assert postados.verificar("2026-09-25", "B", None, []) == []
    assert postados.verificar("2026-09-25", "B", "FB-7777", [h("inedito")]) == []
    with pytest.raises(ErroPostados):
        postados.verificar("25/09/2026", "B", None, [])


# ------------------------------------------------------------ varredura das pastas de data

def test_varredura_acha_mesma_midia_em_outro_dia(cfg):
    midia_em(cfg, "2026-09-20", "A - 1.jpg", "foto repetida")
    midia_em(cfg, "2026-09-20", "IMG_0001.JPG", "foto repetida", sub="_originais")  # mesma mídia: 1 ocorrência só
    midia_em(cfg, "2026-09-20", "A - 2.jpg", "outra foto")
    midia_em(cfg, "2026-09-21", "IMG_0009.MOV", "video antigo", sub="_originais")
    midia_em(cfg, "2026-09-21", "notas.txt", "foto repetida")  # não é mídia
    atual = midia_em(cfg, "2026-09-25", "B - 1.jpg", "foto repetida")  # pasta do próprio dia fica de fora
    midia_em(cfg, "2026-09-25", "B - 2.mp4", "video antigo")
    midia_em(cfg, "Outros", "x.jpg", "foto repetida")  # pasta que não é de data

    oc = postados.verificar("2026-09-25", "B", None, [midia.hash_arquivo(atual), h("video antigo")])
    assert [(o["motivo"], o["data"], o["letra"], o["arquivo"]) for o in oc] == [
        ("hash_pasta", "2026-09-20", "A", "A - 1.jpg"),
        ("hash_pasta", "2026-09-21", None, os.path.join("_originais", "IMG_0009.MOV")),
    ]
    assert oc[0]["texto"] == "mesma mídia já está na pasta de 20/09/2026, letra A (A - 1.jpg)"
    assert "21/09/2026" in oc[1]["texto"]


def test_varredura_usa_manifesto_para_originais(cfg):
    midia_em(cfg, "2026-09-21", "IMG_0009.MOV", "video antigo", sub="_originais")
    trabalho = cfg.p.trabalho_stories / "2026-09-21"
    trabalho.mkdir(parents=True)
    (trabalho / "manifesto.json").write_text(json.dumps({"letras": {"C": {"midias": [
        {"nome": "C - 1", "arquivo": "C - 1.mp4", "origem": "IMG_0009.MOV"}]}}}), encoding="utf-8")
    oc = postados.verificar("2026-09-25", "B", None, [h("video antigo")])
    assert [(o["letra"], o["arquivo"]) for o in oc] == [("C", "C - 1.mp4")]


def test_varredura_nao_repete_o_que_o_registro_ja_mostrou(cfg):
    registrar_a()
    arq = midia_em(cfg, "2026-09-22", "A - 2.jpg", "foto")
    assert midia.hash_arquivo(arq) == h("foto")
    oc = postados.verificar("2026-09-25", "B", "FB-0123", [h("foto")])
    assert [o["motivo"] for o in oc] == ["sku"]
    oc = postados.verificar("2026-09-25", "B", "FB-9999", [h("foto")])
    assert [o["motivo"] for o in oc] == ["hash_registro"]


def test_cache_de_hashes(cfg, monkeypatch):
    antigo = midia_em(cfg, "2026-09-20", "A - 1.jpg", "foto repetida")
    midia_em(cfg, "2026-09-20", "A - 2.jpg", "outra")
    alvo = [h("foto repetida")]
    assert len(postados.verificar("2026-09-25", "B", None, alvo)) == 1
    cache = json.loads((cfg.p.registros / "cache_hashes.json").read_text(encoding="utf-8"))
    entrada = cache["arquivos"][str(antigo)]
    assert entrada["hash"] == h("foto repetida") and entrada["tamanho"] == len("foto repetida")
    assert len(cache["arquivos"]) == 2

    calculados = []
    original = midia.hash_arquivo

    def contar(caminho, *a, **k):
        calculados.append(caminho.name)
        return original(caminho, *a, **k)

    monkeypatch.setattr(midia, "hash_arquivo", contar)
    assert len(postados.verificar("2026-09-25", "B", None, alvo)) == 1
    assert calculados == []  # tudo veio do cache

    antigo.write_bytes(b"conteudo novo, maior que o anterior")  # muda tamanho e data
    assert postados.verificar("2026-09-25", "B", None, alvo) == []
    assert calculados == ["A - 1.jpg"]

    (cfg.p.pasta_do_dia("2026-09-20") / "A - 2.jpg").unlink()
    postados.verificar("2026-09-25", "B", None, alvo)
    cache = json.loads((cfg.p.registros / "cache_hashes.json").read_text(encoding="utf-8"))
    assert list(cache["arquivos"]) == [str(antigo)]  # entrada de arquivo apagado sai do cache


def test_cache_ilegivel_e_recalculado(cfg):
    midia_em(cfg, "2026-09-20", "A - 1.jpg", "foto repetida")
    (cfg.p.registros).mkdir(parents=True, exist_ok=True)
    (cfg.p.registros / "cache_hashes.json").write_text("{quebrado", encoding="utf-8")
    assert len(postados.verificar("2026-09-25", "B", None, [h("foto repetida")])) == 1
    assert json.loads((cfg.p.registros / "cache_hashes.json").read_text(encoding="utf-8"))["versao"] == 1


# ------------------------------------------------------------ terminal

def test_cli(cfg, capsys):
    assert postados.cli([]) == 0
    assert "Nenhuma postagem" in capsys.readouterr().out
    registrar_a()
    registrar_a(data="2026-09-23", letra="B", sku="FB-0400")
    assert postados.cli(["--sku", "fb-0123"]) == 0
    saida = capsys.readouterr().out
    assert "22/09/2026  letra A  FB-0123  Vestido Midi Alça" in saida
    assert "A - 1.mp4 (Verde), A - 2.jpg (Verde, Preto)" in saida
    assert "FB-0400" not in saida
    assert postados.cli(["--data", "2026-09-23", "--json"]) == 0
    dados = json.loads(capsys.readouterr().out)
    assert [(d["letra"], d["sku"]) for d in dados] == [("B", "FB-0400")]
    assert postados.cli(["--sku", "FB-NADA"]) == 0
    assert "Nenhuma postagem registrada do SKU FB-NADA" in capsys.readouterr().out


# ------------------------------------------------------------ revisão

def test_registrar_de_novo_nao_duplica_linhas(cfg):
    assert registrar_a() == 2
    arq = cfg.p.registros / "postados.csv"
    antes = arq.read_bytes()
    assert registrar_a() == 0  # retomada da mesma postagem
    assert arq.read_bytes() == antes
    # uma mídia nova da mesma letra entra; a já registrada não
    n = postados.registrar("2026-09-22", "A", "FB-0123", "Vestido Midi Alça", [
        {"arquivo": "A - 2.jpg", "cores": ["Verde"], "hash": h("foto")},
        {"arquivo": "A - 3.jpg", "cores": ["Verde"], "hash": h("foto3")},
    ], "outro-pedido")
    assert n == 1 and len(postados.ler()) == 3


def test_csv_regravado_pelo_excel_so_ascii_recebe_cp1252(cfg):
    """Excel PT-BR salva "CSV (separado por ponto e vírgula)" em cp1252 e sem BOM."""
    arq = cfg.p.registros / "postados.csv"
    arq.parent.mkdir(parents=True, exist_ok=True)
    arq.write_bytes(b"data;letra;sku;cor;arquivo;hash;peca;pedido;registrado_em\r\n22/09/2026;A;FB-1;Verde;A - 1.mp4;abc;Vestido;p1;x\r\n")
    postados.registrar("2026-09-23", "B", "FB-2", "Macacão Alça", [{"arquivo": "B - 1.jpg", "cores": ["Marrom"], "hash": "d"}], "p2")
    bruto = arq.read_bytes()
    assert "Macacão Alça".encode("cp1252") in bruto and "Macacão".encode("utf-8") not in bruto
    assert postados.ler()[1]["peca"] == "Macacão Alça"


def test_varredura_originais_em_subpasta_com_nome_repetido(cfg):
    """A preparação guarda em _originais/<subpasta>/ e põe "(2)" no nome quando ele já existe."""
    midia_em(cfg, "2026-09-20", "IMG_0001.JPG", "foto velha", sub="_originais/celular")
    midia_em(cfg, "2026-09-20", "IMG_0001 (2).JPG", "foto repetida", sub="_originais/celular")
    midia_em(cfg, "2026-09-20", "IMG_0005.JPG", "ainda na subpasta", sub="celular")
    reg = cfg.p.pasta_do_dia("2026-09-20") / "_originais" / "renomeados.json"
    reg.write_text(json.dumps({"entradas": [
        {"letra": "D", "arquivo": "D - 2.jpg", "origem": "celular/IMG_0001.JPG", "estado": "feito",
         "movido_para": "_originais/celular/IMG_0001 (2).JPG"},
    ]}), encoding="utf-8")
    oc = postados.verificar("2026-09-25", "B", None, [h("foto repetida"), h("ainda na subpasta")])
    assert [(o["data"], o["letra"], o["arquivo"]) for o in oc] == [
        ("2026-09-20", None, os.path.join("celular", "IMG_0005.JPG")),
        ("2026-09-20", "D", "D - 2.jpg"),
    ]


def test_verificar_procura_tambem_o_original_da_letra(cfg):
    """.MOV convertido em dias diferentes pode gerar .mp4 diferente; o original é o mesmo."""
    midia_em(cfg, "2026-09-20", "IMG_0009.MOV", "mov original", sub="_originais")
    midia_em(cfg, "2026-09-25", "IMG_0009.MOV", "mov original", sub="_originais")
    reg = cfg.p.pasta_do_dia("2026-09-25") / "_originais" / "renomeados.json"
    reg.write_text(json.dumps({"entradas": [
        {"letra": "B", "arquivo": "B - 1.mp4", "origem": "IMG_0009.MOV", "hash_origem": h("mov original").upper()},
        {"letra": "C", "arquivo": "C - 1.mp4", "origem": "IMG_0010.MOV", "hash_origem": h("outra letra")},
    ]}), encoding="utf-8")
    oc = postados.verificar("2026-09-25", "B", None, [h("mp4 convertido hoje")])
    assert [(o["motivo"], o["data"]) for o in oc] == [("hash_pasta", "2026-09-20")]
    assert postados.verificar("2026-09-25", "C", None, [h("mp4 convertido hoje")]) == []


# ------------------------------------------------------------ pendentes (letra publicada sem registro no CSV)

def _pendente_a(data="2026-09-22", letra="A", sku="FB-0123"):
    linhas = postados.linhas_do_registro(data, letra, sku, "Vestido Midi Alça", [
        {"arquivo": "A - 1.mp4", "cores": ["Verde"], "hash": h("video pendente")},
    ], "p-pendente")
    return postados.gravar_pendente(data, letra, linhas)


def test_pendente_conta_como_publicado_em_ler_letras_e_verificar(cfg):
    registrar_a(letra="C", sku="FB-0300")
    arq = _pendente_a()
    assert arq.parent == cfg.p.registros / "postados_pendentes"
    assert postados.letras_postadas("2026-09-22") == {"A", "C"}
    assert [(l["letra"], l["arquivo"]) for l in postados.ler()][-1] == ("A", "A - 1.mp4")
    oc = postados.verificar("2026-09-25", "B", "FB-0123", [])
    assert [(o["motivo"], o["letra"]) for o in oc] == [("sku", "A")]
    oc = postados.verificar("2026-09-25", "B", None, [h("video pendente")])
    assert [(o["motivo"], o["letra"]) for o in oc] == [("hash_registro", "A")]


def test_pendente_sem_csv_ainda(cfg):
    _pendente_a()
    assert not (cfg.p.registros / "postados.csv").exists()
    assert postados.letras_postadas("2026-09-22") == {"A"}


def test_proximo_registro_passa_o_pendente_para_o_csv_sem_duplicar(cfg):
    arq = _pendente_a()
    registrar_a(letra="B", sku="FB-0200")
    assert not arq.exists() and postados.ler_pendentes() == []
    no_csv = list(csv.reader(postados.caminho_csv().read_text(encoding="utf-8-sig").splitlines(), delimiter=";"))
    assert [(l[1], l[5]) for l in no_csv[1:]] == [("A", h("video pendente")), ("B", h("video")), ("B", h("foto"))]
    assert postados.letras_postadas("2026-09-22") == {"A", "B"}
    registrar_a(letra="C", sku="FB-0300")
    assert len(postados.ler()) == 5  # nada duplicado


def test_pendente_ilegivel_nao_deixa_postar_sem_saber(cfg):
    pasta = cfg.p.registros / "postados_pendentes"
    pasta.mkdir(parents=True)
    (pasta / "2026-09-22_A_x.json").write_text("{quebrado", encoding="utf-8")
    with pytest.raises(ErroPostados, match="pendente ilegível"):
        postados.letras_postadas("2026-09-22")


def test_testar_gravacao(cfg, monkeypatch):
    postados.testar_gravacao()  # sem CSV: só garante as pastas, não cria o arquivo
    assert not postados.caminho_csv().exists() and postados.pasta_pendentes().is_dir()
    registrar_a()
    antes = postados.caminho_csv().read_bytes()
    postados.testar_gravacao()
    assert postados.caminho_csv().read_bytes() == antes

    def aberto_no_excel(*args, **kw):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(postados, "open", aberto_no_excel, raising=False)
    with pytest.raises(ErroPostados, match="aberto em outro programa"):
        postados.testar_gravacao(tentativas=2, espera_s=0)
