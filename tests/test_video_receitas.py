import copy

import pytest

from rotinas.video import receitas

IDS = [f"r{n:02d}" for n in range(1, 13)]


@pytest.fixture
def r02():
    return copy.deepcopy(receitas.carregar("r02"))


def test_lista_as_12_receitas_na_ordem():
    itens = receitas.listar()
    assert [i["id"][:3] for i in itens] == IDS
    for i in itens:
        assert set(i) == {"id", "nome", "objetivo", "duracao_s"}
        assert len(i["duracao_s"]) == 2


@pytest.mark.parametrize("rid", IDS)
def test_cada_receita_passa_na_validacao(rid):
    receita = receitas.carregar(rid)
    assert receitas.validar(receita) == []
    assert receita["id"].startswith(rid)
    assert receita["estrutura"][0]["papel"] == "gancho"
    assert receita["notas"], "a receita lista o que exige da captação"
    for bloco in receita["estrutura"]:
        for campo in ("papel", "dur_s", "tomada_sugerida", "texto", "efeito", "repete"):
            assert campo in bloco


def test_carregar_aceita_atalhos():
    assert receitas.carregar("R2")["id"] == "r02-provador-com-preco"
    assert receitas.carregar("r12")["id"] == "r12-escolha-o-look"
    assert receitas.carregar("r05-photo-dump-da-colecao.json")["id"] == "r05-photo-dump-da-colecao"
    with pytest.raises(receitas.ErroReceita):
        receitas.carregar("r99")


def test_receitas_respeitam_regras_fixas():
    for rid in IDS:
        r = receitas.carregar(rid)
        gancho = r["textos"]["gancho"]
        assert 300 <= gancho["y"][0] and gancho["y"][1] <= 700
        assert 80 <= gancho["tamanho_px"] <= 110
        assert gancho["entra_max_s"] <= 0.5
        if r["estetica"] in ("luxo", "festa"):
            usadas = {r["efeitos"].get("assinatura"), *r["efeitos"]["apoio"]}
            assert 32 not in usadas  # nada de glitch em festa/luxo
        assert r["musica"]["origem"] in ("instagram", "sem")  # música pelo Instagram por padrão (§7)
        assert r["itens_biblioteca"] == []  # tudo feito à mão, sem item da biblioteca


@pytest.mark.parametrize("duracao, esperado", [
    (6, {"faixa_s": [7, 15], "assinatura": 1, "apoio": [1, 1], "transicoes": [0, 1], "efeitos_sonoros": [2, 4]}),
    (12, {"faixa_s": [7, 15], "assinatura": 1, "apoio": [1, 1], "transicoes": [0, 1], "efeitos_sonoros": [2, 4]}),
    (15, {"faixa_s": [7, 15], "assinatura": 1, "apoio": [1, 1], "transicoes": [0, 1], "efeitos_sonoros": [2, 4]}),
    (15.5, {"faixa_s": [15, 30], "assinatura": 1, "apoio": [2, 2], "transicoes": [1, 2], "efeitos_sonoros": [3, 6]}),
    (30, {"faixa_s": [15, 30], "assinatura": 1, "apoio": [2, 2], "transicoes": [1, 2], "efeitos_sonoros": [3, 6]}),
    (45, {"faixa_s": [30, 60], "assinatura": 1, "apoio": [2, 3], "transicoes": [2, 3], "efeitos_sonoros": [4, 8]}),
    (90, {"faixa_s": [30, 60], "assinatura": 1, "apoio": [2, 3], "transicoes": [2, 3], "efeitos_sonoros": [4, 8]}),
])
def test_orcamento_bate_com_a_tabela(duracao, esperado):
    o = receitas.orcamento(duracao)
    assert {k: o[k] for k in esperado} == esperado
    assert o["apoio_repetidos"] is (duracao > 30)


def test_catalogo_tem_as_58_tecnicas():
    cat = receitas.tecnicas()
    assert sorted(cat) == list(range(1, 59))
    assert cat[32]["proibida_em"] == ["luxo", "festa"]
    assert cat[31]["flash"] is True


def test_palavras_e_tempo_minimo():
    assert receitas.palavras("forrado · não amassa · P ao GG") == 6
    assert receitas.tempo_minimo_texto("LOOK") == 1.5
    assert receitas.tempo_minimo_texto("4 looks com 1 saia") == pytest.approx(2.5)


def _erros(receita):
    return "\n".join(receitas.validar(receita))


def test_receita_sem_campo(r02):
    del r02["musica"]
    assert receitas.validar(r02) == ["falta o campo 'musica'"]


def test_gancho_tem_que_ser_o_primeiro_bloco(r02):
    r02["estrutura"] = r02["estrutura"][1:] + r02["estrutura"][:1]
    assert "o 1º bloco tem que ser 'gancho'" in _erros(r02)


def test_texto_do_gancho_fora_das_regras(r02):
    r02["textos"]["gancho"].update(y=[250, 800], tamanho_px=60, entra_max_s=1.0)
    e = _erros(r02)
    assert "textos.gancho.y [250, 800] fora da zona segura" in e
    assert "fora de y 300–700" in e
    assert "60 px fora de 80–110 px" in e
    assert "entrada acima de 0.5 s" in e


def test_texto_pequeno_ou_rapido_demais(r02):
    r02["textos"]["rotulo"].update(tamanho_px=30, tamanho_min_px=30, min_s=0.8)
    e = _erros(r02)
    assert "textos.rotulo: 30 px abaixo do mínimo de 42 px" in e
    assert "textos.rotulo: min_s 0.8 abaixo de 1.5 s" in e


def test_stories_ate_60_s(r02):
    r02["duracao_s"] = [15, 75]
    assert "duracao_s até 75 s passa do máximo de stories (60 s)" in _erros(r02)


def test_apoio_acima_do_orcamento(r02):
    r02["efeitos"]["apoio"] = [1, 2, 5]
    assert "efeitos.apoio com 3 técnicas; o orçamento de 25 s permite 2" in _erros(r02)


def test_efeito_fora_da_assinatura_e_do_apoio(r02):
    r02["estrutura"][1]["efeito"] = 5
    assert "técnica 5 (Tremor de câmera) não está na assinatura nem no apoio" in _erros(r02)


def test_glitch_nao_entra_em_festa_nem_luxo():
    r = copy.deepcopy(receitas.carregar("r10"))
    r["efeitos"]["apoio"] = [32]
    r["itens_biblioteca"] = [{"tecnica": 32, "item": "Efeitos > Falha"}]
    assert "técnica 32 (Glitch / RGB) não combina com a estética festa" in _erros(r)


def test_item_so_da_biblioteca_precisa_ser_declarado():
    r = copy.deepcopy(receitas.carregar("r05"))
    r["efeitos"]["apoio"] = [45]
    assert "só existe na biblioteca do CapCut" in _erros(r)


def test_tecnica_inexistente_e_transicao_fora_da_lista(r02):
    r02["estrutura"][2]["efeito"] = 99
    r02["estrutura"][3]["transicao"] = "giro_3d"
    e = _erros(r02)
    assert "efeito 99 não existe no catálogo" in e
    assert "transição 'giro_3d' fora de transicoes.permitidas" in e


def test_transicoes_acima_do_orcamento(r02):
    r02["transicoes"] = {"permitidas": ["corte_seco", "fusao"], "max": 3}
    assert "transicoes.max 3 acima do orçamento de 25 s (2" in _erros(r02)


def test_bloco_longo_sem_troca_visual(r02):
    r02["estrutura"][1]["dur_s"] = [1.5, 5.0]
    assert "(prova): pode ficar 5 s sem troca visual (máx. 3.0 s" in _erros(r02)


def test_musica_alta_demais_na_fala(r02):
    r02["musica"]["volume_musica_com_fala_db"] = -6
    assert "a música fica 6 dB abaixo da voz" in _erros(r02)


def test_sem_loop_nem_cta(r02):
    r02["estrutura"][-1]["texto"] = ["preco", "parcelas"]
    assert "sem loop e sem CTA" in _erros(r02)


def test_estrutura_que_nao_cabe_na_duracao(r02):
    r02["duracao_s"] = [30, 40]
    assert "não chegam à duração mínima (30 s)" in _erros(r02)


def test_cli_valida_todas(capsys):
    assert receitas.cli(["--validar"]) == 0
    saida = capsys.readouterr().out
    assert "12 de 12 receita(s) válida(s)." in saida
    assert receitas.cli(["--id", "R1"]) == 0
    assert "Captação:" in capsys.readouterr().out


def test_campo_com_tipo_errado_vira_erro_e_nao_excecao(r02):
    r02["textos"]["rotulo"]["tamanho_px"] = "grande"
    assert "formato inesperado" in _erros(r02)


def test_abertura_pelo_climax_dura_o_do_guia():
    """#21: o melhor 0,7–1 s do final no início (nas receitas que cortam na batida, até 1,2 s = 2 batidas a 100 BPM)."""
    for rid in IDS:
        r = receitas.carregar(rid)
        if not r["ritmo"]["corte_na_batida"]:
            continue
        for b in r["estrutura"]:
            if 21 in receitas._lista_int(b["efeito"]):
                assert 0.7 <= b["dur_s"][0] and b["dur_s"][1] <= 1.2, (rid, b["dur_s"])


def test_video_acima_de_15_s_tem_onde_por_o_regancho():
    """§3: re-gancho a cada 5–8 s acima de 15 s; algum bloco do meio precisa aceitar texto."""
    for rid in IDS:
        r = receitas.carregar(rid)
        if r["duracao_s"][1] <= 15:
            continue
        meio = r["estrutura"][1:-1]
        assert any(receitas._papeis_texto(b) for b in meio), rid
