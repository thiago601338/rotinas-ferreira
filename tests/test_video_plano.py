import copy
import json

import pytest

from rotinas.contexto import Contexto
from rotinas.video import plano, receitas

PROJETO = "vestido-verde"
QUADRO = 1 / 30


# ---------------------------------------------------------------- preço

@pytest.mark.parametrize("valor, texto", [
    (229.99, "R$229,99"), (149.99, "R$149,99"), (150, "R$150,00"), (1299.9, "R$1.299,90"),
    (12999.5, "R$12.999,50"), ("229,99", "R$229,99"), ("R$ 1.299,90", "R$1.299,90"), (0.5, "R$0,50"),
    (1234567.8, "R$1.234.567,80"),
    ("1.299", "R$1.299,00"), ("R$ 1.299", "R$1.299,00"),  # ponto de milhar sem centavos (não é R$1,30)
    ("229.99", "R$229,99"),
])
def test_formatar_preco(valor, texto):
    assert plano.formatar_preco(valor) == texto


@pytest.mark.parametrize("valor, texto", [
    (149.99, "2x de R$75,00 sem juros"),   # até R$149,99 → 2x (74,995 arredonda para 75,00)
    (150.00, "3x de R$50,00 sem juros"),   # R$150,00 já é 3x
    (229.99, "3x de R$76,66 sem juros"),   # 76,663… → 76,66
    (319.98, "3x de R$106,66 sem juros"),  # último valor em 3x
    (319.99, "5x de R$64,00 sem juros"),   # acima de R$319,98 → 5x (63,998 → 64,00)
    (1299.90, "5x de R$259,98 sem juros"),
    (6499.95, "5x de R$1.299,99 sem juros"),  # parcela com milhar
])
def test_parcelas_nas_bordas(valor, texto):
    assert plano.parcelas(valor, com_valor=True) == texto
    vezes = texto.split("x", 1)[0]
    assert plano.parcelas(valor) == f"{vezes}x sem juros"  # padrão: formato do guia, sem o valor da parcela


def test_parcela_com_valor_so_quando_configurado(cfg):
    assert plano.parcelas(229.99) == "3x sem juros"
    cfg.alterar("video", parcela_mostrar_valor=True)
    assert plano.parcelas(229.99) == "3x de R$76,66 sem juros"


def test_parcela_arredondada_para_baixo_quando_configurado(cfg):
    cfg.alterar("video", parcela_arredondamento="para_baixo")
    assert plano.parcelas(149.99, com_valor=True) == "2x de R$74,99 sem juros"


@pytest.mark.parametrize("ruim", [0, -10, "abc", None, True])
def test_preco_invalido(ruim):
    with pytest.raises(ValueError):
        plano.formatar_preco(ruim)


def test_precos_fora_do_formato():
    assert plano.precos_fora_do_formato("R$229,99 · 3x de R$76,66 sem juros") == []
    assert plano.precos_fora_do_formato("R$1.299,90") == []
    assert plano.precos_fora_do_formato("custa R$ 229,99") == ["R$ 229,99"]
    assert plano.precos_fora_do_formato("R$1299,90") == ["R$1299,90"]
    assert plano.precos_fora_do_formato("R$229.99") == ["R$229.99"]


def test_ajustar_texto_quebra_e_reduz():
    texto, tam = plano.ajustar_texto("4 looks com 1 saia", 96, 80, 540)
    assert texto == "4 looks\ncom 1 saia" and tam == 96
    x0, _, x1, _ = plano.caixa_texto({"texto": texto, "tamanho_px": tam, "x": 540, "y": 500})
    assert x0 >= 80 and x1 <= 920


# ---------------------------------------------------------------- bruto.json falso

def _info(fps):
    return {"tipo": "video", "fps": fps, "fps_variavel": False, "largura": 2160, "altura": 3840, "duracao_s": 30.0,
            "hdr": False, "tem_audio": True}


def _arquivo(nome, fps=30.0, fala=False, silencios=()):
    caminho = f"C:\\Users\\V15\\Documents\\Rotinas Ferreira\\videos\\bruto\\{PROJETO}\\{nome}"
    return {"arquivo": nome, "caminho": caminho, "caminho_edicao": caminho, "info": _info(fps), "avisos": [],
            "tomadas": [], "silencios": list(silencios), "fala": fala}


def _tomadas(*itens):
    return [{"id": f"T{n:02d}", "arquivo": arq, "ini_s": a, "fim_s": b, "dur_s": round(b - a, 3),
             "folha": "folhas/tomadas-01.jpg"} for n, (arq, a, b) in enumerate(itens, 1)]


def gravar(cfg, bruto, transcricao=None):
    trabalho = cfg.p.videos / "trabalho" / PROJETO
    trabalho.mkdir(parents=True, exist_ok=True)
    (cfg.p.videos / "bruto" / PROJETO).mkdir(parents=True, exist_ok=True)
    (trabalho / "bruto.json").write_text(json.dumps(bruto, ensure_ascii=False), encoding="utf-8")
    if transcricao is not None:
        (trabalho / "transcricao.json").write_text(json.dumps(transcricao, ensure_ascii=False), encoding="utf-8")
    return trabalho


BATIDAS = [round(0.5 * k, 3) for k in range(1, 80)]  # 120 BPM, uma batida a cada 15 quadros


@pytest.fixture
def bruto_r1(cfg):
    bruto = {
        "projeto": PROJETO, "gerado_em": "2026-09-25T10:00:00-03:00",
        "arquivos": [_arquivo("IMG_0001.MOV"), _arquivo("IMG_0002.MOV", fps=60.0)],
        "tomadas": _tomadas(("IMG_0001.MOV", 0.0, 3.0), ("IMG_0001.MOV", 3.0, 6.0), ("IMG_0001.MOV", 6.0, 9.0),
                            ("IMG_0001.MOV", 9.0, 12.0), ("IMG_0002.MOV", 0.0, 4.0), ("IMG_0001.MOV", 12.0, 18.0)),
        "transcricao": None,
        "musica": {"arquivo": "C:\\Users\\V15\\Documents\\Rotinas Ferreira\\videos\\musicas\\guia.mp3", "bpm": 120.0,
                   "batidas_s": BATIDAS, "compassos_s": BATIDAS[::4], "primeira_batida_s": 0.5, "confianca": 0.9},
        "folhas": ["folhas/tomadas-01.jpg"], "avisos": [],
    }
    gravar(cfg, bruto)
    return bruto


ESCOLHAS_R1 = {
    "destino": "reels", "sku": "FB-0123", "preco": 229.99, "cta": "Chama no WhatsApp",
    "musica": {"arquivo": "guia.mp3", "no_capcut": False},
    "blocos": [
        {"papel": "gancho", "tomada": "T01", "texto": "4 looks com 1 saia"},
        {"papel": "look", "tomada": "T02"},
        {"papel": "look", "tomada": "T03"},
        {"papel": "look", "tomada": "t4"},
        {"papel": "look_final", "tomada": "T05"},
        {"papel": "preco", "tomada": "T06"},
    ],
}


def _na_batida(t):
    return min(abs(t - b) for b in BATIDAS) <= QUADRO + 1e-6


def test_planejar_r1_corta_na_batida(cfg, bruto_r1):
    p = plano.planejar(PROJETO, "r01", copy.deepcopy(ESCOLHAS_R1))
    assert p["violacoes"] == []
    assert p["receita"] == "r01-troca-de-look-na-batida"
    assert p["canvas"] == {"largura": 1080, "altura": 1920, "fps": 30.0}
    assert 12 - QUADRO / 2 <= p["duracao_s"] <= 20
    principais = [v for v in p["video"] if v["faixa"] == 0]
    # linha do tempo contínua, cortes na batida (tolerância de 1 quadro)
    t = 0.0
    for v in principais:
        assert v["ini_s"] == pytest.approx(t, abs=1e-3)
        t = v["ini_s"] + v["dur_s"]
    assert t == pytest.approx(p["duracao_s"], abs=1e-3)
    for v in principais[1:]:
        assert _na_batida(v["ini_s"]), v
    # gancho no quadro 1 com o texto da IA
    gancho = next(x for x in p["textos"] if x["papel"] == "gancho")
    assert gancho["ini_s"] == 0.0 and gancho["entrada_s"] <= 0.5
    assert gancho["texto"].replace("\n", " ") == "4 looks com 1 saia"
    assert 300 <= gancho["y"] <= 700 and gancho["x"] == 540
    # contador, preço e parcelas
    textos = [x["texto"] for x in p["textos"]]
    assert ["LOOK 1/4", "LOOK 2/4", "LOOK 3/4", "LOOK 4/4"] == [x for x in textos if x.startswith("LOOK")]
    assert "R$229,99" in textos and "3x sem juros" in textos and "Chama no WhatsApp" in textos
    assert p["preco"] == {"valor": 229.99, "texto": "R$229,99", "parcelas": "3x sem juros", "sku": "FB-0123"}
    # câmera lenta no último look, punch-in nos looks, corte seco nas trocas
    final = next(v for v in principais if v["papel"] == "look_final")
    assert final["velocidade"] == 0.5
    assert final["fonte_fim_s"] - final["fonte_ini_s"] == pytest.approx(final["dur_s"] * 0.5, abs=1e-3)
    assert any(v["escala"] == 1.15 for v in principais if v["papel"] == "look")
    assert all(x["tipo"] == "corte_seco" for x in p["transicoes"])
    assert {e["tecnica"] for e in p["efeitos"]} >= {1, 9, 21}
    # faixa-guia só para editar (música pelo Instagram); clipes sem fala mudos
    assert p["audio"][0]["papel"] == "guia" and p["audio"][0]["exportar"] is False
    assert all(v["mudo"] for v in principais)
    assert p["legendas"] == []
    # plano.json gravado e igual ao devolvido
    gravado = json.loads((cfg.p.videos / "trabalho" / PROJETO / "plano.json").read_text(encoding="utf-8"))
    assert gravado == p


def test_aviso_de_efeito_sonoro_sem_arquivo_da_o_nome_de_cada_arquivo(cfg, bruto_r1):
    # Teste da skill (25/09/2026): saía "pôr pop, whoosh.mp3" (parecia um arquivo só).
    p = plano.planejar(PROJETO, "r01", copy.deepcopy(ESCOLHAS_R1))
    aviso = next(a for a in p["avisos"] if a.startswith("Efeitos sonoros sem arquivo"))
    assert "pôr pop.mp3, whoosh.mp3 com licença comercial" in aviso


def test_r1_tomada_curta_e_recorte_fora_da_tomada(cfg, bruto_r1):
    esc = copy.deepcopy(ESCOLHAS_R1)
    esc["blocos"][1].update(ini_s=0.4, fim_s=1.0)  # tempos relativos à tomada, não ao arquivo
    with pytest.raises(plano.ErroPlano, match="fora da tomada .*T02 vai de 3,00 a 6,00 s"):
        plano.planejar(PROJETO, "r01", esc)
    esc["blocos"][1].update(ini_s=3.2, fim_s=3.8)  # dentro, mas curto
    p = plano.planejar(PROJETO, "r01", esc)
    look = next(v for v in p["video"] if v["tomada"] == "T02")
    assert look["fonte_ini_s"] == pytest.approx(3.2)
    assert any("bloco 2 (look)" in a for a in p["avisos"])


def test_r1_sem_batidas_avisa(cfg, bruto_r1):
    bruto = copy.deepcopy(bruto_r1)
    bruto["musica"] = None
    gravar(cfg, bruto)
    esc = copy.deepcopy(ESCOLHAS_R1)
    esc.pop("musica")
    p = plano.planejar(PROJETO, "r01", esc)
    assert any("não há batidas marcadas" in a for a in p["avisos"])
    assert p["batidas_s"] == []


def test_erros_de_entrada(cfg, bruto_r1):
    with pytest.raises(plano.ErroPlano, match="papel 'refrão' não existe"):
        plano.planejar(PROJETO, "r01", {"blocos": [{"papel": "refrão", "tomada": "T01"}]})
    with pytest.raises(plano.ErroPlano, match="Tomada 'T99' não existe"):
        plano.planejar(PROJETO, "r01", {"blocos": [{"papel": "gancho", "tomada": "T99"}]})
    with pytest.raises(plano.ErroPlano, match="Destino 'feed' fora da receita"):
        plano.planejar(PROJETO, "r01", {"destino": "feed", "blocos": [{"papel": "gancho", "tomada": "T01"}]})
    with pytest.raises(plano.ErroPlano, match="video-preparar"):
        plano.planejar("outro-projeto", "r01", ESCOLHAS_R1)


# ---------------------------------------------------------------- R2: fala, legenda e preço

FALA = [
    {"ini_s": 13.5, "fim_s": 13.8, "texto": "Esse"}, {"ini_s": 13.8, "fim_s": 14.2, "texto": "vestido"},
    {"ini_s": 14.2, "fim_s": 14.5, "texto": "custa"}, {"ini_s": 14.5, "fim_s": 14.7, "texto": "R$"},
    {"ini_s": 14.7, "fim_s": 15.3, "texto": "229,99"}, {"ini_s": 15.4, "fim_s": 15.6, "texto": "em"},
    {"ini_s": 15.6, "fim_s": 15.8, "texto": "3x"}, {"ini_s": 15.8, "fim_s": 16.0, "texto": "sem"},
    {"ini_s": 16.0, "fim_s": 16.3, "texto": "juros."},
    {"ini_s": 18.6, "fim_s": 18.9, "texto": "tchau"},  # fora do trecho usado
]


@pytest.fixture
def bruto_r2(cfg):
    bruto = {
        "projeto": PROJETO, "gerado_em": "2026-09-25T10:00:00-03:00",
        "arquivos": [_arquivo("IMG_0003.MOV", fala=True, silencios=[{"ini_s": 0.0, "fim_s": 13.4}])],
        "tomadas": _tomadas(("IMG_0003.MOV", 0.0, 2.0), ("IMG_0003.MOV", 2.0, 5.0), ("IMG_0003.MOV", 5.0, 8.0),
                            ("IMG_0003.MOV", 8.0, 11.0), ("IMG_0003.MOV", 11.0, 13.0), ("IMG_0003.MOV", 13.0, 20.0)),
        "transcricao": {"arquivo_srt": "legendas.srt", "palavras": [{"arquivo": "IMG_0003.MOV", **w} for w in FALA]},
        "musica": None, "folhas": [], "avisos": [],
    }
    transc = {"arquivos": [{"arquivo": "IMG_0003.MOV", "caminho": "x", "srt": "legendas.srt", "palavras": FALA,
                            "blocos": []}]}
    gravar(cfg, bruto, transc)
    return bruto


ESCOLHAS_R2 = {
    "destino": "reels", "sku": "FB-0456", "preco": 229.99,
    "blocos": [
        {"papel": "gancho", "tomada": "T01", "texto": "Provei o vestido verde"},
        {"papel": "prova", "tomada": "T02"},
        {"papel": "prova", "tomada": "T03"},
        {"papel": "detalhe", "tomada": "T04"},
        {"papel": "bolso", "tomada": "T05", "texto": "bolso de verdade"},
        {"papel": "preco", "tomada": "T06"},
    ],
    "cta": "Chama no WhatsApp",
}


def test_planejar_r2_legenda_retimada_e_preco(cfg, bruto_r2):
    p = plano.planejar(PROJETO, "r02", copy.deepcopy(ESCOLHAS_R2))
    assert p["violacoes"] == []
    assert 15 <= p["duracao_s"] <= 25
    preco = next(v for v in p["video"] if v["papel"] == "preco")
    assert preco["fala"] is True and preco["mudo"] is False and preco["volume_db"] == 0.0
    # começa logo antes da 1ª palavra e termina logo depois da última usada ("tchau" fica de fora)
    assert preco["fonte_ini_s"] == pytest.approx(13.42, abs=0.01)
    assert preco["fonte_fim_s"] < 18.6
    legendas = p["legendas"]
    assert legendas, "tem legenda da fala"
    juntas = " ".join(x["texto"].replace("\n", " ") for x in legendas)
    assert "tchau" not in juntas
    assert "R$229,99" in juntas and "R$ 229" not in juntas  # cifrão colado
    # retimada: a 1ª palavra (13,5 s no arquivo) cai 0,08 s depois do início do bloco na linha do tempo
    assert legendas[0]["ini_s"] == pytest.approx(preco["ini_s"] + 0.08, abs=0.02)
    for lg in legendas:
        assert preco["ini_s"] - 1e-3 <= lg["ini_s"] and lg["ini_s"] + lg["dur_s"] <= p["duracao_s"] + 1e-3
        assert 950 <= lg["y"] <= 1250
    # preço no formato da loja e parcelas pela regra
    textos = {x["papel"]: x for x in p["textos"]}
    assert textos["preco"]["texto"] == "R$229,99"
    assert textos["parcelas"]["texto"] == "3x sem juros"
    assert textos["preco"]["ini_s"] == pytest.approx(preco["ini_s"])
    assert textos["rotulo"]["texto"] == "bolso de verdade"
    # clipes sem fala mudos; nada de música no plano (vai pelo Instagram)
    assert all(v["mudo"] for v in p["video"] if not v["fala"])
    assert not [a for a in p["audio"] if a["papel"] in ("musica", "guia")]
    assert {e["tecnica"] for e in p["efeitos"]} >= {55, 54, 53}


def test_r2_legenda_desligada_e_preco_pelo_sku(cfg, bruto_r2):
    esc = copy.deepcopy(ESCOLHAS_R2)
    esc["legendas"] = False
    esc.pop("preco")
    p = plano.planejar(PROJETO, "r02", esc)
    assert p["legendas"] == []
    assert p["preco"] is None
    assert any("SKU FB-0456" in a and "consulta o estoque" in a for a in p["avisos"])
    assert not [x for x in p["textos"] if x["papel"] in ("preco", "parcelas")]


def test_r2_legenda_avisa_preco_diferente_do_cadastro(cfg, bruto_r2):
    esc = copy.deepcopy(ESCOLHAS_R2)
    esc["preco"] = 199.9
    p = plano.planejar(PROJETO, "r02", esc)
    assert any("A legenda diz R$229,99" in a and "R$199,90" in a for a in p["avisos"])
    assert next(x for x in p["textos"] if x["papel"] == "parcelas")["texto"] == "3x sem juros"


# ---------------------------------------------------------------- validar_plano pega cada violação

@pytest.fixture
def plano_r2(cfg, bruto_r2):
    p = plano.planejar(PROJETO, "r02", copy.deepcopy(ESCOLHAS_R2))
    assert plano.validar_plano(p) == []
    return p


def _texto(p, papel):
    return next(x for x in p["textos"] if x["papel"] == papel)


def _tem(violacoes, trecho):
    return any(trecho in v for v in violacoes), violacoes


def test_viola_texto_fora_da_zona_segura(plano_r2):
    _texto(plano_r2, "rotulo")["y"] = 1500
    assert _tem(plano.validar_plano(plano_r2), "'bolso de verdade' fora da zona segura")[0]


def test_viola_texto_largo_demais(plano_r2):
    _texto(plano_r2, "rotulo")["texto"] = "bolso de verdade com zíper invisível"
    assert _tem(plano.validar_plano(plano_r2), "fora da zona segura")[0]


def test_viola_texto_curto_demais(plano_r2):
    _texto(plano_r2, "rotulo")["dur_s"] = 0.8
    v = plano.validar_plano(plano_r2)
    assert _tem(v, "'bolso de verdade' fica 0,8 s na tela; precisa de 1,9 s")[0], v


def test_viola_texto_pequeno(plano_r2):
    _texto(plano_r2, "rotulo")["tamanho_px"] = 36
    assert _tem(plano.validar_plano(plano_r2), "com 36 px (mínimo 42 px")[0]


def test_viola_gancho_sem_texto(plano_r2):
    plano_r2["textos"] = [x for x in plano_r2["textos"] if x["papel"] != "gancho"]
    assert _tem(plano.validar_plano(plano_r2), "Gancho sem texto no quadro 1")[0]


def test_viola_gancho_que_entra_tarde(plano_r2):
    _texto(plano_r2, "gancho")["ini_s"] = 0.6
    assert _tem(plano.validar_plano(plano_r2), "Gancho sem texto no quadro 1")[0]


def test_viola_gancho_sem_texto_no_planejar(cfg, bruto_r2):
    esc = copy.deepcopy(ESCOLHAS_R2)
    esc["blocos"][0].pop("texto")
    p = plano.planejar(PROJETO, "r02", esc)
    assert _tem(p["violacoes"], "Gancho sem texto")[0]


def test_viola_stories_acima_de_60_s(plano_r2):
    plano_r2["destino"] = "stories"
    ultimo = plano_r2["video"][-1]
    ultimo["dur_s"] += 65 - plano_r2["duracao_s"]
    plano_r2["duracao_s"] = 65.0
    v = plano.validar_plano(plano_r2)
    assert _tem(v, "acima do máximo de stories (60 s)")[0], v
    assert _tem(v, "fora da receita (15–25 s)")[0]


def test_viola_efeitos_acima_do_orcamento(plano_r2):
    base = {"dur_s": 0.2, "clipe": 1, "categoria": "apoio", "manual": False, "parametros": {}}
    plano_r2["efeitos"] += [{**base, "tecnica": 5, "nome": "Tremor", "ini_s": 3.0},
                            {**base, "tecnica": 2, "nome": "Zoom lento", "ini_s": 5.0},
                            {**base, "tecnica": 49, "nome": "Color pop", "ini_s": 6.0}]
    assert _tem(plano.validar_plano(plano_r2), "Efeitos acima do orçamento")[0]


def test_viola_mais_de_3_flashes_por_segundo(plano_r2):
    base = {"tecnica": 31, "nome": "Flash", "dur_s": 0.067, "clipe": 1, "categoria": "apoio", "manual": False,
            "parametros": {}}
    plano_r2["efeitos"] += [{**base, "ini_s": t} for t in (3.0, 3.2, 3.4, 3.6)]
    assert _tem(plano.validar_plano(plano_r2), "4 flashes em 1 s")[0]
    plano_r2["efeitos"] = [e for e in plano_r2["efeitos"] if not (e["tecnica"] == 31 and e["ini_s"] == 3.6)]
    assert not _tem(plano.validar_plano(plano_r2), "flashes em 1 s")[0]


def test_viola_preco_fora_do_formato(plano_r2):
    _texto(plano_r2, "preco")["texto"] = "R$ 229,99"
    v = plano.validar_plano(plano_r2)
    assert _tem(v, "preço 'R$ 229,99' fora do formato da loja")[0]
    _texto(plano_r2, "preco")["texto"] = "R$229,99"
    _texto(plano_r2, "parcelas")["texto"] = "2x de R$115,00 sem juros"
    assert _tem(plano.validar_plano(plano_r2), "diferentes da regra da loja")[0]


def test_viola_troca_visual(plano_r2):
    # junta dois clipes sem fala num só de 6 s
    sem_fala = [n for n, v in enumerate(plano_r2["video"]) if v["papel"] == "prova"]
    a, b = plano_r2["video"][sem_fala[0]], plano_r2["video"][sem_fala[1]]
    a["dur_s"] += b["dur_s"]
    plano_r2["video"].remove(b)
    assert _tem(plano.validar_plano(plano_r2), "s sem troca visual")[0]


def test_viola_transicoes_e_corte_fora_da_batida(cfg, bruto_r1):
    p = plano.planejar(PROJETO, "r01", copy.deepcopy(ESCOLHAS_R1))
    assert plano.validar_plano(p) == []
    p["transicoes"][0]["tipo"] = "fusao"
    assert _tem(plano.validar_plano(p), "transições além do corte seco")[0]
    p["transicoes"][0]["tipo"] = "corte_seco"
    principais = [v for v in p["video"] if v["faixa"] == 0]
    principais[0]["dur_s"] += 0.2
    principais[1]["ini_s"] += 0.2
    principais[1]["dur_s"] -= 0.2
    assert _tem(plano.validar_plano(p), "fora da batida")[0]


# ---------------------------------------------------------------- fila e terminal

def test_tarefa_grava_escolhas_e_bloqueia_violacao(cfg, bruto_r2, tmp_path):
    ctx = Contexto(tmp_path / "saida")
    r = plano.tarefa({"projeto": PROJETO, "receita": "r02", "escolhas": copy.deepcopy(ESCOLHAS_R2)}, ctx)
    assert r["violacoes"] == [] and r["plano_json"].endswith("plano.json")
    trabalho = cfg.p.videos / "trabalho" / PROJETO
    assert json.loads((trabalho / "escolhas.json").read_text(encoding="utf-8")) == ESCOLHAS_R2
    assert (tmp_path / "saida" / "plano.txt").exists()
    # sem 'escolhas' usa o escolhas.json do trabalho
    assert plano.tarefa({"projeto": PROJETO, "receita": "r02"}, ctx)["receita"] == "r02-provador-com-preco"
    ruim = copy.deepcopy(ESCOLHAS_R2)
    ruim["blocos"][0]["texto"] = "Olha"
    with pytest.raises(plano.ErroPlano) as e:
        plano.tarefa({"projeto": PROJETO, "receita": "r02", "escolhas": ruim}, ctx)
    assert "Texto do gancho com 1 palavra(s)" in str(e.value)
    assert e.value.resultado_parcial["violacoes"]
    # o plano com violação não apaga o último plano bom (é ele que o rascunho e a exportação usam)
    assert json.loads((trabalho / "plano.json").read_text(encoding="utf-8"))["violacoes"] == []
    assert json.loads((trabalho / "plano-com-violacoes.json").read_text(encoding="utf-8"))["violacoes"]


def test_sem_transcricao_avisa_fala_muda_e_legenda_vazia(cfg):
    bruto = {
        "projeto": PROJETO, "gerado_em": "2026-09-25T10:00:00-03:00",
        "arquivos": [_arquivo("IMG_0003.MOV", fala=True)],
        "tomadas": _tomadas(("IMG_0003.MOV", 0.0, 2.0), ("IMG_0003.MOV", 2.0, 5.0), ("IMG_0003.MOV", 5.0, 8.0),
                            ("IMG_0003.MOV", 8.0, 11.0), ("IMG_0003.MOV", 11.0, 13.0), ("IMG_0003.MOV", 13.0, 20.0)),
        "transcricao": None, "musica": None, "folhas": [], "avisos": [],
    }
    gravar(cfg, bruto)
    p = plano.planejar(PROJETO, "r02", dict(copy.deepcopy(ESCOLHAS_R2), legendas=True))
    assert any("não foi transcrito" in a for a in p["avisos"])
    assert any("não há transcrição" in a for a in p["avisos"]) and p["legendas"] == []


def test_cli(cfg, bruto_r2, capsys):
    trabalho = cfg.p.videos / "trabalho" / PROJETO
    (trabalho / "escolhas.json").write_text(json.dumps(ESCOLHAS_R2), encoding="utf-8")
    assert plano.cli(["--projeto", PROJETO, "--receita", "R2"]) == 0
    saida = capsys.readouterr().out
    assert "Plano r02-provador-com-preco (reels)" in saida and "R$229,99" in saida
    assert plano.cli(["--projeto", PROJETO, "--receita", "r77"]) == 2


@pytest.mark.parametrize("rid", [f"r{n:02d}" for n in range(1, 13)])
def test_todas_as_receitas_planejam(cfg, rid):
    """Um bruto genérico (tomadas longas, fala e batidas) passa por qualquer receita sem erro de montagem."""
    receita = receitas.carregar(rid)
    tomadas = _tomadas(*[("IMG_0009.MOV", 10.0 * k, 10.0 * k + 10.0) for k in range(40)])
    bruto = {"projeto": PROJETO, "arquivos": [_arquivo("IMG_0009.MOV", fps=60.0, fala=True)], "tomadas": tomadas,
             "transcricao": None, "musica": {"arquivo": "guia.mp3", "bpm": 120.0, "batidas_s": BATIDAS},
             "folhas": [], "avisos": []}
    gravar(cfg, bruto)
    blocos, n = [], 0
    for d in receita["estrutura"]:
        vezes = (d["repete"] or [1, 1])[0] or 1
        for _ in range(vezes):
            b = {"papel": d["papel"], "tomada": tomadas[n]["id"]}
            if d.get("composicao"):
                q = receitas.regra("composicoes")[d["composicao"]]["quadros"][0]
                b["tomadas"] = [t["id"] for t in tomadas[n:n + q]]
            if d["papel"] == "gancho":
                b["texto"] = "o look que esgotou"
            n += 1
            blocos.append(b)
    p = plano.planejar(PROJETO, rid, {"destino": "reels", "preco": 189.9, "blocos": blocos})
    assert p["textos"][0]["papel"] == "gancho" and p["textos"][0]["ini_s"] == 0.0
    assert receita["duracao_s"][0] - QUADRO <= p["duracao_s"] <= receita["duracao_s"][1] + QUADRO, p["avisos"]
    assert p["violacoes"] == [], p["violacoes"]


# ---------------------------------------------------------------- composição, jump cut, fotos e música

def test_r3_grade_2x2_e_jump_cut_com_escala_alternada(cfg):
    # IMG_0004: fala em 3 trechos com pausas de 0,8 s (silêncios) → jump cuts
    palavras, silencios = [], []
    for k in range(3):
        base = 10.0 * k
        palavras += [{"ini_s": base + 0.5 + 0.3 * j, "fim_s": base + 0.75 + 0.3 * j, "texto": f"palavra{j}"}
                     for j in range(6)]
        palavras += [{"ini_s": base + 3.3 + 0.3 * j, "fim_s": base + 3.55 + 0.3 * j, "texto": f"outra{j}"}
                     for j in range(10)]
        silencios += [{"ini_s": base + 2.3, "fim_s": base + 3.2}]
    bruto = {
        "projeto": PROJETO,
        "arquivos": [_arquivo("IMG_0001.MOV"), _arquivo("IMG_0004.MOV", fala=True, silencios=silencios)],
        "tomadas": _tomadas(*[("IMG_0001.MOV", 3.0 * k, 3.0 * k + 3.0) for k in range(4)],
                            *[("IMG_0004.MOV", 10.0 * k, 10.0 * k + 10.0) for k in range(3)]),
        "transcricao": {"palavras": [{"arquivo": "IMG_0004.MOV", **w} for w in palavras]},
        "musica": None, "folhas": [], "avisos": [],
    }
    gravar(cfg, bruto, {"arquivos": [{"arquivo": "IMG_0004.MOV", "palavras": palavras}]})
    grade = ["T01", "T02", "T03", "T04"]
    esc = {"destino": "reels", "blocos": [
        {"papel": "gancho", "tomadas": grade, "texto": "1 saia, 3 formas"},
        {"papel": "look", "tomada": "T05"}, {"papel": "look", "tomada": "T06"}, {"papel": "look", "tomada": "T07"},
        {"papel": "grade_final", "tomadas": grade}]}
    p = plano.planejar(PROJETO, "r03", esc)
    assert p["violacoes"] == [], p["violacoes"]
    abertura = [v for v in p["video"] if v["papel"] == "gancho"]
    assert [v["faixa"] for v in abertura] == [0, 1, 2, 3]
    assert {(v["x"], v["y"]) for v in abertura} == {(270, 480), (810, 480), (270, 1440), (810, 1440)}
    assert all(v["escala"] == 0.49 for v in abertura) and all(v["mudo"] for v in abertura[1:])
    look1 = [v for v in p["video"] if v["tomada"] == "T05"]
    assert len(look1) == 2, "a pausa de 0,9 s saiu (jump cut)"
    assert look1[0]["fonte_fim_s"] <= 2.3 + 0.1 and look1[1]["fonte_ini_s"] >= 3.2 - 0.1
    assert look1[0]["ini_s"] + look1[0]["dur_s"] == pytest.approx(look1[1]["ini_s"], abs=1e-3)
    escalas = [v["escala"] for v in p["video"] if v["papel"] == "look"]
    assert set(escalas) == {1.0, 1.1}, escalas  # 100%/110% alternados a cada 2 cortes
    assert p["legendas"] and all(lg["ini_s"] >= 2.9 for lg in p["legendas"])
    assert [x["texto"] for x in p["textos"] if x["papel"] == "contador"] == ["LOOK 1/3", "LOOK 2/3", "LOOK 3/3"]
    assert next(x for x in p["textos"] if x["papel"] == "cta")["texto"].replace("\n", " ") == "Salva para lembrar"


def test_r5_fotos_do_bruto(cfg, bruto_r1):
    pasta = cfg.p.videos / "bruto" / PROJETO
    fotos = []
    for n in range(16):
        f = pasta / f"FOTO {n:02d}.jpg"
        f.write_bytes(b"jpg")
        fotos.append(f.name)
    blocos = [{"papel": "gancho", "foto": fotos[0], "texto": "tudo que chegou hoje"}]
    blocos += [{"papel": "foto", "foto": f, "destaque": n in (3, 9)} for n, f in enumerate(fotos[1:], 1)]
    p = plano.planejar(PROJETO, "r05", {"destino": "stories", "blocos": blocos})
    assert p["violacoes"] == [], p["violacoes"]
    assert all(v["tipo"] == "foto" and v["mudo"] for v in p["video"])
    assert all(v["fonte_ini_s"] == 0.0 for v in p["video"] if v["escala"] == 1.0)
    assert p["loop"] is True
    zoom3d = [e["clipe"] for e in p["efeitos"] if e["tecnica"] == 3]
    assert len(zoom3d) == 3  # gancho + 2 fotos-chave (as destacadas pela IA)
    destacadas = {p["video"][c]["arquivo"] for c in zoom3d}
    assert str(pasta / fotos[3]) in destacadas and str(pasta / fotos[9]) in destacadas
    flashes = sorted(e["ini_s"] for e in p["efeitos"] if e["tecnica"] == 31)
    assert 1 <= len(flashes) <= 3
    with pytest.raises(plano.ErroPlano, match="Foto não encontrada"):
        plano.planejar(PROJETO, "r05", {"blocos": [{"papel": "gancho", "foto": "nao-existe.jpg"}]})


def test_musica_so_entra_quando_a_receita_pede(cfg, bruto_r1):
    esc = {"blocos": [{"papel": "gancho", "tomada": "T05", "texto": "o detalhe que ninguém vê"},
                      {"papel": "tecido", "tomada": "T02"}, {"papel": "textura", "tomada": "T03"},
                      {"papel": "peca", "tomada": "T06"}], "preco": 329.9}
    p = plano.planejar(PROJETO, "r04", esc)  # ASMR: sem música por padrão
    assert not [a for a in p["audio"] if a["papel"] in ("musica", "guia")]
    assert next(v for v in p["video"] if v["papel"] == "tecido")["volume_db"] == 4.0  # som do objeto +4 dB
    assert next(x for x in p["textos"] if x["papel"] == "parcelas")["texto"] == "5x sem juros"
    esc["musica"] = {"arquivo": "guia.mp3", "no_capcut": True}
    p = plano.planejar(PROJETO, "r04", esc)
    musica = next(a for a in p["audio"] if a["papel"] == "musica")
    assert musica["exportar"] is True and musica["volume_db"] == -20.0


def test_texto_obrigatorio_sem_conteudo_avisa(cfg, bruto_r1):
    esc = {"preco": 99.9, "blocos": [{"papel": "gancho", "tomada": "T01", "texto": "do básico ao completo"},
                                     {"papel": "depois", "tomada": "T02"}, {"papel": "lista", "tomada": "T06"}]}
    p = plano.planejar(PROJETO, "r07", esc)
    assert any("sem texto para 'lista'" in a for a in p["avisos"])
    esc["blocos"][2]["texto"] = "Blusa R$89,90\nSaia R$129,90"
    p = plano.planejar(PROJETO, "r07", esc)
    lista = next(x for x in p["textos"] if x["papel"] == "lista")
    assert lista["texto"] == "Blusa R$89,90\nSaia R$129,90"
    assert p["violacoes"] == [], p["violacoes"]
    esc["blocos"][2]["texto"] = "Blusa R$ 89,90"
    p = plano.planejar(PROJETO, "r07", esc)
    assert any("fora do formato da loja" in v for v in p["violacoes"])


# ---------------------------------------------------------------- revisão: casos fora do caminho feliz

def test_preco_da_fala_vai_para_o_formato_da_loja():
    assert plano._normalizar_precos("custa R$ 229,99 em 3x") == "custa R$229,99 em 3x"
    assert plano._normalizar_precos("custa R$ 230.") == "custa R$230,00."
    assert plano._normalizar_precos("R$229.99, viu") == "R$229,99, viu"
    assert plano._normalizar_precos("R$ 1.299,90") == "R$1.299,90"


def test_legenda_com_preco_falado_sem_centavos_nao_bloqueia(cfg, bruto_r2):
    # a transcrição devolve "R$ 230" (sem centavos): antes virava violação que a IA não tinha como corrigir
    fala = [dict(w) for w in FALA]
    fala[4]["texto"] = "230"
    transc = {"arquivos": [{"arquivo": "IMG_0003.MOV", "palavras": fala}]}
    gravar(cfg, bruto_r2, transc)
    p = plano.planejar(PROJETO, "r02", copy.deepcopy(ESCOLHAS_R2))
    assert p["violacoes"] == [], p["violacoes"]
    juntas = " ".join(x["texto"].replace("\n", " ") for x in p["legendas"])
    assert "R$230,00" in juntas
    assert any("A legenda diz R$230,00" in a and "R$229,99" in a for a in p["avisos"])


def _bruto_fala(cfg, palavras, silencios=(), fps=30.0):
    bruto = {"projeto": PROJETO, "arquivos": [_arquivo("IMG_0001.MOV"), _arquivo("IMG_0004.MOV", fps=fps, fala=True,
                                                                               silencios=list(silencios))],
             "tomadas": _tomadas(*[("IMG_0001.MOV", 3.0 * k, 3.0 * k + 3.0) for k in range(4)],
                                 *[("IMG_0004.MOV", 10.0 * k, 10.0 * k + 10.0) for k in range(3)]),
             "transcricao": {"palavras": [{"arquivo": "IMG_0004.MOV", **w} for w in palavras]},
             "musica": None, "folhas": [], "avisos": []}
    gravar(cfg, bruto, {"arquivos": [{"arquivo": "IMG_0004.MOV", "palavras": palavras}]})


def _r3(tomadas_look=("T05", "T06", "T07")):
    grade = ["T01", "T02", "T03", "T04"]
    return {"destino": "reels", "blocos": [{"papel": "gancho", "tomadas": grade, "texto": "1 saia, 3 formas"}]
            + [{"papel": "look", "tomada": t} for t in tomadas_look]
            + [{"papel": "grade_final", "tomadas": grade}]}


def _frase(ini, n, passo=0.3, dur=0.25, nome="p"):
    return [{"ini_s": round(ini + passo * j, 3), "fim_s": round(ini + passo * j + dur, 3), "texto": f"{nome}{j}"}
            for j in range(n)]


def test_jump_cut_pela_transcricao_quando_o_ruido_esconde_o_silencio(cfg):
    # loja com ruído de fundo: o silencedetect não achou nenhuma pausa, mas a transcrição mostra 0,9 s parado
    palavras = []
    for k in range(3):
        palavras += _frase(10.0 * k + 0.5, 6) + _frase(10.0 * k + 3.3, 10, nome="q")
    _bruto_fala(cfg, palavras, silencios=())
    p = plano.planejar(PROJETO, "r03", _r3())
    look1 = [v for v in p["video"] if v["tomada"] == "T05"]
    assert len(look1) == 2, "a pausa entre as frases saiu (jump cut)"
    assert look1[0]["fonte_fim_s"] <= 2.25 + 0.1 and look1[1]["fonte_ini_s"] >= 3.3 - 0.1


def test_jump_cut_nao_corta_palavra_baixa_dentro_do_silencio(cfg):
    # "né" dito baixinho em 2,6 s cai dentro do "silêncio" do ffmpeg (2,3–3,2): a palavra fica
    palavras = []
    for k in range(3):
        base = 10.0 * k
        palavras += _frase(base + 0.5, 6) + [{"ini_s": base + 2.6, "fim_s": base + 2.8, "texto": "né"}]
        palavras += _frase(base + 3.3, 10, nome="q")
    silencios = [{"ini_s": 10.0 * k + 2.3, "fim_s": 10.0 * k + 3.2} for k in range(3)]
    _bruto_fala(cfg, palavras, silencios)
    p = plano.planejar(PROJETO, "r03", _r3())
    look1 = [v for v in p["video"] if v["tomada"] == "T05"]
    assert any(v["fonte_ini_s"] <= 2.6 and v["fonte_fim_s"] >= 2.8 for v in look1), look1
    assert "né" in " ".join(lg["texto"] for lg in p["legendas"])


def test_fala_longa_demais_avisa_o_que_ficou_de_fora(cfg):
    # 30 palavras seguidas (9 s) num look que vai até 8 s: o fim da fala sai, com aviso
    palavras = []
    for k in range(3):
        palavras += _frase(10.0 * k + 0.5, 30)
    _bruto_fala(cfg, palavras)
    p = plano.planejar(PROJETO, "r03", _r3())
    assert any("bloco 2 (look): a fala passa de 8,0 s e foi cortada" in a and "p29" in a for a in p["avisos"]), p["avisos"]


def test_fala_de_passagem_nao_tira_o_corte_da_batida(cfg, bruto_r1):
    # alguém diz "vai" no meio da tomada de um look: o bloco continua cortando na batida (antes virava bloco de
    # fala com duração da fala e o corte seguinte saía fora da batida)
    bruto = copy.deepcopy(bruto_r1)
    bruto["arquivos"][0]["fala"] = True
    bruto["transcricao"] = {"palavras": [{"arquivo": "IMG_0001.MOV", "ini_s": 4.3, "fim_s": 4.5, "texto": "vai"}]}
    gravar(cfg, bruto)
    p = plano.planejar(PROJETO, "r01", copy.deepcopy(ESCOLHAS_R1))
    assert p["violacoes"] == [], p["violacoes"]
    principais = [v for v in p["video"] if v["faixa"] == 0]
    for v in principais[1:]:
        assert _na_batida(v["ini_s"]), v
    assert next(v for v in principais if v["tomada"] == "T02")["mudo"] is False  # o som da tomada fica


def test_voz_em_camera_lenta_nao_vira_bloco_de_fala(cfg, bruto_r1):
    bruto = copy.deepcopy(bruto_r1)
    bruto["musica"] = None
    bruto["arquivos"][1]["fala"] = True
    bruto["transcricao"] = {"palavras": [{"arquivo": "IMG_0002.MOV", "ini_s": 1.0, "fim_s": 1.3, "texto": "gira"}]}
    gravar(cfg, bruto)
    esc = copy.deepcopy(ESCOLHAS_R1)
    esc.pop("musica")
    p = plano.planejar(PROJETO, "r01", esc)
    final = next(b for b in p["blocos"] if b["papel"] == "look_final")
    assert final["fala"] is False and final["dur_s"] >= 1.5


def test_tomadas_seguidas_de_camera_na_mao_viram_um_trecho(cfg, bruto_r1):
    # o detector partiu um plano tremido em T02 (3–6 s) e T03 (6–9 s): "tomadas" junta de volta
    esc = copy.deepcopy(ESCOLHAS_R1)
    esc["blocos"][1] = {"papel": "look", "tomadas": ["T02", "T03"], "ini_s": 5.4, "fim_s": 6.6}
    p = plano.planejar(PROJETO, "r01", esc)
    look = [v for v in p["video"] if v["bloco"] == 1]
    assert look[0]["fonte_ini_s"] == pytest.approx(5.4) and look[-1]["fonte_fim_s"] > 6.0
    assert not any("só a primeira tomada" in a for a in p["avisos"])
    esc["blocos"][1] = {"papel": "look", "tomadas": ["T02", "T05"]}  # arquivos diferentes: não junta
    p = plano.planejar(PROJETO, "r01", esc)
    assert any("só a primeira tomada (T02)" in a for a in p["avisos"])


def test_legendas_de_varios_arquivos_nao_se_misturam(cfg):
    # dois arquivos com fala nos mesmos segundos: cada clipe só leva as palavras do próprio arquivo
    fala_a = [{"ini_s": 13.5, "fim_s": 13.9, "texto": "Esse"}, {"ini_s": 13.9, "fim_s": 14.4, "texto": "vestido"},
              {"ini_s": 14.4, "fim_s": 14.9, "texto": "verde"}]
    fala_b = [{"ini_s": 0.5, "fim_s": 0.9, "texto": "Tem"}, {"ini_s": 0.9, "fim_s": 1.3, "texto": "bolso"},
              {"ini_s": 13.6, "fim_s": 14.0, "texto": "ERRADO"}]
    bruto = {
        "projeto": PROJETO, "gerado_em": "2026-09-25T10:00:00-03:00",
        "arquivos": [_arquivo("IMG_0003.MOV", fala=True), _arquivo("IMG_0005.MOV", fala=True)],
        "tomadas": _tomadas(("IMG_0003.MOV", 0.0, 2.0), ("IMG_0003.MOV", 2.0, 5.0), ("IMG_0003.MOV", 5.0, 8.0),
                            ("IMG_0003.MOV", 8.0, 11.0), ("IMG_0005.MOV", 0.0, 2.0), ("IMG_0003.MOV", 13.0, 20.0)),
        "transcricao": {"palavras": [{"arquivo": "IMG_0003.MOV", **w} for w in fala_a]
                        + [{"arquivo": "IMG_0005.MOV", **w} for w in fala_b]},
        "musica": None, "folhas": [], "avisos": [],
    }
    gravar(cfg, bruto, {"arquivos": [{"arquivo": "IMG_0003.MOV", "palavras": fala_a},
                                     {"arquivo": "IMG_0005.MOV", "palavras": fala_b}]})
    p = plano.planejar(PROJETO, "r02", copy.deepcopy(ESCOLHAS_R2))
    juntas = " ".join(lg["texto"].replace("\n", " ") for lg in p["legendas"])
    assert "ERRADO" not in juntas and "Esse vestido verde" in juntas and "Tem bolso" in juntas
    bolso = next(v for v in p["video"] if v["papel"] == "bolso")
    tem = next(lg for lg in p["legendas"] if lg["texto"].startswith("Tem"))
    assert tem["ini_s"] == pytest.approx(bolso["ini_s"] + (0.5 - bolso["fonte_ini_s"]), abs=0.02)


def test_quebra_de_linha_nao_separa_artigo_do_substantivo():
    texto, _ = plano.ajustar_texto("Provei o vestido verde", 96, 80, 540)
    assert not any(linha.split()[-1] in ("o", "a", "de") for linha in texto.split("\n")[:-1]), texto


def test_maiusculas_ocupam_mais_largura():
    assert plano._largura("NOVA COLEÇÃO", 100) > plano._largura("nova coleção", 100)
    # caixa alta que só "cabia" pela conta de minúsculas agora quebra ou encolhe dentro da zona segura
    texto, tam = plano.ajustar_texto("CHAMA NO WHATSAPP", 72, 56, 540)
    x0, _, x1, _ = plano.caixa_texto({"texto": texto, "tamanho_px": tam, "x": 540, "y": 600})
    assert x0 >= 80 and x1 <= 920


def test_regancho_opcional_resolve_video_longo_sem_texto(cfg, bruto_r2):
    esc = copy.deepcopy(ESCOLHAS_R2)
    esc["blocos"].insert(3, {"papel": "prova", "tomada": "T03", "ini_s": 5.0, "fim_s": 8.0})
    p = plano.planejar(PROJETO, "r02", esc)
    assert any("sem texto novo" in a for a in p["avisos"])
    esc["blocos"][3]["texto"] = "mas o bolso é o melhor"
    p = plano.planejar(PROJETO, "r02", esc)
    assert not any("sem texto novo" in a for a in p["avisos"]), p["avisos"]
    reg = next(x for x in p["textos"] if x["papel"] == "regancho")
    assert 420 <= reg["y"] <= 580 and reg["ini_s"] > 0
    assert p["violacoes"] == [], p["violacoes"]


def test_avisa_faixa_guia_fora_do_bpm_da_receita(cfg, bruto_r1):
    p = plano.planejar(PROJETO, "r01", copy.deepcopy(ESCOLHAS_R1))  # 120 BPM numa receita de 100–128
    assert not any("BPM e a receita pede" in a for a in p["avisos"])
    bruto = copy.deepcopy(bruto_r1)
    bruto["musica"]["bpm"] = 150.0
    bruto["musica"]["batidas_s"] = [round(0.4 * k, 3) for k in range(1, 100)]
    gravar(cfg, bruto)
    p = plano.planejar(PROJETO, "r01", copy.deepcopy(ESCOLHAS_R1))
    assert any("150 BPM e a receita pede 100–128 BPM" in a for a in p["avisos"]), p["avisos"]
