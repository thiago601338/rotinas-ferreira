"""A5 — fluxo de postagem no Instagram (BlueStacks) com a tela roteirizada e dublês do adb/postados."""

import hashlib
import json
import re
from pathlib import Path

import pytest

from dubles_android import Relogio, TelaFalsa
from rotinas.contexto import Contexto
from rotinas.stories import android, bluestacks, postados

LETRAS_POSTADAS = postados.letras_postadas  # a de verdade (o ``ambiente`` troca por um dublê)
URL = "wa.me/5582988748649?text=Quero+comprar+o+Vestido+Midi+Al%C3%A7a"
MUSICA = {"nome": "Áudio original", "autor": "petermarkoski", "busca": "petermarkoski"}


# ---------------------------------------------------------------- montagem

def _arquivo(pasta: Path, nome: str) -> tuple[Path, str]:
    caminho = pasta / nome
    caminho.write_bytes(f"conteudo {nome}".encode("utf-8"))
    return caminho, hashlib.sha256(caminho.read_bytes()).hexdigest()


def montar_plano(pasta: Path, letras: dict, data="2026-09-22", ensaio=True, figurinha=True) -> dict:
    """``letras = {"A": ["video_mudo", "foto", "foto"], ...}`` → plano no formato de pedido.py."""
    pasta.mkdir(parents=True, exist_ok=True)
    plano = {"data": data, "id": "20260925-183000-stories-montar", "ensaio": ensaio, "ordem": "letras",
             "letras": [], "cortes": [], "avisos": []}
    for letra, tipos in letras.items():
        midias = []
        for n, tipo in enumerate(tipos, 1):
            ext = ".mp4" if tipo.startswith("video") else ".jpg"
            caminho, h = _arquivo(pasta, f"{letra} - {n}{ext}")
            mudo = tipo == "video_mudo"
            midias.append({"nome": f"{letra} - {n}", "arquivo": caminho.name, "caminho": str(caminho),
                           "tipo": "video" if tipo.startswith("video") else "foto", "hash": h, "cores": ["Verde"],
                           "precisa_musica": mudo, "musica": dict(MUSICA) if mudo else None, "figurinha": None})
        if figurinha:
            midias[-1]["figurinha"] = {"url": URL, "texto": "Comprar agora"}
        plano["letras"].append({"letra": letra, "sku": f"FB-{letra}", "peca": "Vestido Midi Alça",
                                "categoria": "Vestidos", "midias": midias})
    return plano


@pytest.fixture
def ambiente(cfg, tmp_path, monkeypatch):
    relogio = Relogio()
    monkeypatch.setattr(bluestacks, "dormir", relogio.dormir)
    monkeypatch.setattr(bluestacks, "agora", relogio.agora)
    monkeypatch.setattr(android, "dormir", relogio.dormir)
    monkeypatch.setattr(android, "agora", relogio.agora)
    eventos: list = []
    tela = TelaFalsa(eventos)
    registros: list = []

    def registrar(data, letra, sku, peca, midias, pedido):
        registros.append({"data": data, "letra": letra, "sku": sku, "peca": peca, "midias": midias, "pedido": pedido})
        eventos.append(("registrou", letra))
        return len(midias)

    monkeypatch.setattr(postados, "registrar", registrar)
    monkeypatch.setattr(postados, "letras_postadas", lambda data: set())
    enviados: list = []

    def enviar(L):
        enviados.append(L["letra"])
        tela.albuns[f"2026-09-22_{L['letra']}"] = len(L["midias"])
        return {"pasta": f"/sdcard/Pictures/RotinasFerreira/2026-09-22_{L['letra']}", "avisos": []}

    class Amb:
        pass

    a = Amb()
    a.tela, a.eventos, a.registros, a.enviados, a.enviar, a.relogio = tela, eventos, registros, enviados, enviar, relogio
    a.ctx = Contexto(tmp_path / "saida", id_pedido="20260925-190000-stories-postar")
    a.midias = tmp_path / "Stories da Loja" / "2026-09-22"
    return a


def rodar(a, plano, ensaio=True, diagnostico=False):
    return bluestacks.executar(plano, a.ctx, ensaio=ensaio, diagnostico=diagnostico, tela=a.tela, enviar=a.enviar)


PADRAO = {"A": ["video_mudo", "foto", "foto"], "B": ["video_som", "foto"], "C": ["foto"]}


# ---------------------------------------------------------------- ensaio

def test_instagram_448_adicionar_ao_story_abre_a_camera_direto(ambiente):
    """No Instagram 448 não há aba "Criar": "Adicionar ao story" já abre a câmera; a aba "Story" não é tocada."""
    a = ambiente
    a.tela.criar_abre_camera = True
    res = rodar(a, montar_plano(a.midias, {"A": ["foto", "foto"]}), ensaio=True)
    assert [x["estado"] for x in res["letras"]] == ["ensaio_ok"]
    assert "abrir_story" not in a.tela.toques and a.tela.toques.count("criar") == 1


def test_instagram_448_como_no_pc(ambiente):
    """Como no testar.bat bluestacks de 25/09: "Adicionar ao story" abre a galeria; o álbum fica em "Todos os
    álbuns"; a seleção não mostra número (só a descrição da miniatura muda). Real publica certo."""
    a = ambiente
    a.tela.criar_abre_galeria = True
    a.tela.album_via_todos = True
    a.tela.numeros_na_selecao = False
    res = rodar(a, montar_plano(a.midias, {"A": ["foto", "foto", "foto"]}, ensaio=False), ensaio=False)
    assert res["publicadas"] == ["A"]
    assert "abrir_story" not in a.tela.toques and "abrir_galeria" not in a.tela.toques
    assert a.tela.toques.index("album_todos") < a.tela.toques.index("album_item")
    assert a.tela.publicacoes[0]["album"] == "2026-09-22_A" and len(a.tela.publicacoes[0]["midias"]) == 3


def test_selecao_ja_ligada_nao_e_desligada(ambiente):
    a = ambiente
    a.tela.criar_abre_galeria = True
    a.tela.selecao_ja_ativa = True
    res = rodar(a, montar_plano(a.midias, {"A": ["foto", "foto"]}), ensaio=True)
    assert [x["estado"] for x in res["letras"]] == ["ensaio_ok"]
    assert "selecionar_varios" not in a.tela.toques


def test_sem_numero_e_com_uma_miniatura_ignorada_nao_publica(ambiente):
    a = ambiente
    a.tela.criar_abre_galeria = True
    a.tela.numeros_na_selecao = False
    a.tela.ignorar_miniatura = {1}  # o toque na 2ª não pegou
    with pytest.raises(bluestacks.ErroPostagem):
        rodar(a, montar_plano(a.midias, {"A": ["foto", "foto", "foto"]}, ensaio=False), ensaio=False)
    assert a.tela.publicacoes == []


def test_versao_com_aba_criar_ainda_escolhe_story(ambiente):
    a = ambiente
    res = rodar(a, montar_plano(a.midias, {"A": ["foto"]}), ensaio=True)
    assert [x["estado"] for x in res["letras"]] == ["ensaio_ok"]
    assert a.tela.toques.index("criar") < a.tela.toques.index("abrir_story")


def test_ensaio_nao_toca_em_publicar_e_gera_um_print_por_midia(ambiente):
    a = ambiente
    res = rodar(a, montar_plano(a.midias, PADRAO), ensaio=True)
    assert res["ensaio"] is True
    assert not set(a.tela.toques) & bluestacks.CHAVES_PUBLICAR
    assert a.tela.publicacoes == []
    assert a.registros == []
    assert [x["estado"] for x in res["letras"]] == ["ensaio_ok"] * 3
    assert res["publicadas"] == []
    for x, n in zip(res["letras"], (3, 2, 1)):
        esperados = [f"ensaio_{x['letra']}_{i}.png" for i in range(1, n + 1)]
        assert x["prints"] == esperados
        assert all((a.ctx.pasta_saida / p).is_file() for p in esperados)
    assert a.tela.estado == "feed"  # saiu descartando
    assert a.tela.toques.count("descartar") == 3
    assert a.tela.apps[0] == ("com.instagram.android", True)  # 1ª letra abre o Instagram do zero
    assert all(parar is False for _, parar in a.tela.apps[1:])


def test_publicar_bloqueado_fora_da_publicacao_real(ambiente):
    a = ambiente
    post = bluestacks.Postador(a.tela, a.ctx, ensaio=True)
    a.tela.estado = "editor"
    with pytest.raises(bluestacks.ErroPasso, match="bloqueado"):
        post._tocar("seu_story")
    assert "seu_story" not in a.tela.toques


# ---------------------------------------------------------------- real

def test_real_publica_cada_letra_uma_vez_e_registra_depois(ambiente):
    a = ambiente
    plano = montar_plano(a.midias, PADRAO, ensaio=False)
    res = rodar(a, plano, ensaio=False)
    assert res["publicadas"] == ["A", "B", "C"]
    assert [x["estado"] for x in res["letras"]] == ["publicada"] * 3
    assert [p["album"] for p in a.tela.publicacoes] == ["2026-09-22_A", "2026-09-22_B", "2026-09-22_C"]
    assert [len(p["midias"]) for p in a.tela.publicacoes] == [3, 2, 1]
    assert a.eventos == [("publicou", "2026-09-22_A"), ("registrou", "A"), ("publicou", "2026-09-22_B"),
                         ("registrou", "B"), ("publicou", "2026-09-22_C"), ("registrou", "C")]
    reg = a.registros[0]
    assert (reg["data"], reg["letra"], reg["sku"], reg["peca"]) == ("2026-09-22", "A", "FB-A", "Vestido Midi Alça")
    assert [m["arquivo"] for m in reg["midias"]] == ["A - 1.mp4", "A - 2.jpg", "A - 3.jpg"]
    assert all(m["hash"] and m["cores"] == ["Verde"] for m in reg["midias"])
    assert reg["pedido"] == "20260925-190000-stories-postar"
    # cada letra: seleção na ordem da grade e um único "Seu story" + "Compartilhar"
    assert a.tela.toques.count("seu_story") == 3 and a.tela.toques.count("concluir_publicacao") == 3
    assert [m["indice"] for m in a.tela.publicacoes[0]["midias"]] == [0, 1, 2]
    assert "publicada_A.png" in res["letras"][0]["prints"]


def test_publicacao_direta_no_seu_story_tambem_funciona(ambiente):
    a = ambiente
    a.tela.modo_publicacao = "direto"
    res = rodar(a, montar_plano(a.midias, {"A": ["foto", "foto"]}, ensaio=False), ensaio=False)
    assert res["publicadas"] == ["A"]
    assert "concluir_publicacao" not in a.tela.toques
    assert len(a.tela.publicacoes) == 1


def test_falha_no_meio_da_segunda_letra_para_tudo(ambiente):
    a = ambiente
    a.tela.quebrar = {"abertura": 2, "chave": "figurinhas"}  # letra B: a figurinha some
    with pytest.raises(bluestacks.ErroPostagem) as erro:
        rodar(a, montar_plano(a.midias, PADRAO, ensaio=False), ensaio=False)
    parcial = erro.value.resultado_parcial
    assert [x["estado"] for x in parcial["letras"]] == ["publicada", "falhou", "nao_iniciada"]
    assert parcial["publicadas"] == ["A"]
    assert parcial["parou_em"] == "letra B: figurinha_2"
    assert "figurinhas" in parcial["letras"][1]["erro"]
    assert [r["letra"] for r in a.registros] == ["A"]
    assert len(a.tela.publicacoes) == 1
    assert a.enviados == ["A", "B"]  # C nem começou
    depois_de_a = a.tela.toques[a.tela.toques.index("concluir_publicacao") + 1:]
    assert not set(depois_de_a) & bluestacks.CHAVES_PUBLICAR
    assert a.tela.estado == "feed"  # descartou a edição da B
    falha = parcial["letras"][1]
    assert "falha_B_figurinha_2.png" in falha["prints"] and falha["xml_falha"] == "falha_B_figurinha_2.xml"
    assert (a.ctx.pasta_saida / "falha_B_figurinha_2.xml").is_file()
    assert "Publicadas antes: A" in str(erro.value) and "Não iniciadas: C" in str(erro.value)


def test_selecao_com_n_menos_1_itens_nao_publica(ambiente):
    a = ambiente
    a.tela.ignorar_miniatura = {1}  # o toque na 2ª miniatura não pega
    with pytest.raises(bluestacks.ErroPostagem, match="seleção tem 2 de 3") as erro:
        rodar(a, montar_plano(a.midias, {"A": ["video_mudo", "foto", "foto"]}, ensaio=False), ensaio=False)
    assert a.tela.publicacoes == []
    assert "avancar" not in a.tela.toques
    assert erro.value.resultado_parcial["letras"][0]["estado"] == "falhou"
    assert erro.value.resultado_parcial["parou_em"] == "letra A: conferir_selecao"
    assert a.registros == []


def test_selecao_com_midia_escondida_ja_selecionada_nao_publica(ambiente):
    """Números 2, 3, 4 nas miniaturas = já havia uma mídia selecionada fora da tela (4 no total)."""
    a = ambiente
    a.tela.pre_selecionados = 1
    with pytest.raises(bluestacks.ErroPostagem, match="não conferem"):
        rodar(a, montar_plano(a.midias, {"A": ["foto", "foto", "foto"]}, ensaio=False), ensaio=False)
    assert a.tela.publicacoes == [] and "avancar" not in a.tela.toques and a.registros == []


def test_faixa_do_editor_com_miniatura_a_mais_nao_poe_figurinha_na_midia_errada(ambiente):
    a = ambiente
    a.tela.miniaturas_editor_extra = 1  # ex.: botão "+" antes das miniaturas
    with pytest.raises(bluestacks.ErroPostagem, match="4 miniatura"):
        rodar(a, montar_plano(a.midias, {"A": ["foto", "foto", "foto"]}, ensaio=False), ensaio=False)
    assert a.tela.publicacoes == [] and "editor_extra" not in a.tela.toques


def test_coordenada_plano_b_nunca_e_tocada_com_botao_de_publicar_na_tela(ambiente):
    """"Story" reabriu um rascunho no editor; a galeria só seria achada pela coordenada, que ali é o "Seu story"."""
    a = ambiente
    a.tela.story_abre_rascunho = True
    a.tela.plano_b_chaves = {"abrir_galeria"}
    with pytest.raises(bluestacks.ErroPostagem, match="plano B") as erro:
        rodar(a, montar_plano(a.midias, {"A": ["foto"]}), ensaio=True)
    assert a.tela.publicacoes == []
    assert not [t for t in a.tela.toques if t.startswith("coordenada:")]
    assert erro.value.resultado_parcial["parou_em"] == "letra A: abrir_galeria"


def test_publicar_fora_do_editor_nao_toca_no_seu_story_do_feed(ambiente):
    """No feed, "Seu story" é o próprio story no topo: tocar ali e voltar ao feed NÃO é publicar."""
    a = ambiente
    post = bluestacks.Postador(a.tela, a.ctx, ensaio=False)
    a.tela.estado = "feed"
    r = {"prints": []}
    with pytest.raises(bluestacks.ErroPasso, match="editor"):
        post._publicar(r)
    assert "seu_story" not in a.tela.toques and a.tela.estado == "feed"
    assert post.tocou_publicar is False


def test_album_indisponivel_com_data_da_midia_fora_da_ordem_nao_usa_recentes(ambiente):
    a = ambiente
    a.tela.quebrar = {"abertura": 1, "chave": "album_menu"}

    def enviar(L):
        a.enviados.append(L["letra"])
        return {"pasta": "x", "avisos": [], "ordem_data_da_midia": {"datetaken": False}}

    with pytest.raises(bluestacks.ErroPostagem, match="Recentes"):
        bluestacks.executar(montar_plano(a.midias, {"A": ["foto", "foto"]}, ensaio=False), a.ctx, ensaio=False,
                            tela=a.tela, enviar=enviar)
    assert a.tela.publicacoes == [] and "selecionar_varios" not in a.tela.toques


def test_real_sem_menu_de_albuns_nao_publica_pela_grade_recentes(ambiente):
    """Mesmo com a ordem por data "certa", 'Recentes' tem as outras letras e o resto do emulador: no real, PARA."""
    a = ambiente
    a.tela.quebrar = {"abertura": 1, "chave": "album_menu"}

    def enviar(L):
        return {"pasta": "x", "avisos": [], "ordem_data_da_midia": {"datetaken": True}}

    with pytest.raises(bluestacks.ErroPostagem, match="não publico pela grade 'Recentes'") as erro:
        bluestacks.executar(montar_plano(a.midias, {"A": ["foto", "foto"]}, ensaio=False), a.ctx, ensaio=False,
                            tela=a.tela, enviar=enviar)
    assert a.tela.publicacoes == [] and "selecionar_varios" not in a.tela.toques
    assert erro.value.resultado_parcial["parou_em"] == "letra A: escolher_album"
    assert a.registros == []


def test_real_com_album_fora_da_lista_volta_e_nao_publica(ambiente):
    a = ambiente

    def enviar(L):  # a pasta não virou álbum na galeria: album_item não aparece
        return {"pasta": "x", "avisos": [], "ordem_data_da_midia": {"datetaken": True}}

    with pytest.raises(bluestacks.ErroPostagem, match="não apareceu na lista.*Recentes"):
        bluestacks.executar(montar_plano(a.midias, {"A": ["foto"]}, ensaio=False), a.ctx, ensaio=False,
                            tela=a.tela, enviar=enviar)
    assert a.tela.publicacoes == [] and "selecionar_varios" not in a.tela.toques
    assert "album_menu" in a.tela.toques and a.tela.estado == "feed"


def test_ensaio_sem_menu_de_albuns_usa_recentes_e_avisa_que_o_real_para(ambiente):
    a = ambiente
    a.tela.quebrar = {"abertura": 1, "chave": "album_menu"}

    def enviar(L):
        return {"pasta": "x", "avisos": [], "ordem_data_da_midia": {"datetaken": True}}

    res = bluestacks.executar(montar_plano(a.midias, {"A": ["foto", "foto"]}), a.ctx, ensaio=True,
                              tela=a.tela, enviar=enviar)
    assert res["letras"][0]["estado"] == "ensaio_ok" and res["letras"][0]["recuo_recentes"] is True
    assert any("Recentes" in x and "real PARA" in x for x in res["avisos"])
    assert a.tela.publicacoes == []


def test_url_da_figurinha_sem_https_e_conferida(ambiente):
    a = ambiente
    rodar(a, montar_plano(a.midias, {"A": ["foto", "foto"]}, ensaio=False), ensaio=False)
    urls = [t for c, t in a.tela.digitados if c == "campo_url"]
    assert urls == [URL]
    assert not urls[0].startswith("http")
    fig = a.tela.publicacoes[0]["midias"][-1]["figurinha"]
    assert fig == {"url": URL, "texto": "Comprar agora", "teclado_confirmado": True}


def test_campo_com_https_e_corrigido(ambiente):
    a = ambiente
    a.tela.url_https = 1  # o campo mostra https:// na 1ª vez
    rodar(a, montar_plano(a.midias, {"A": ["foto"]}, ensaio=False), ensaio=False)
    urls = [t for c, t in a.tela.digitados if c == "campo_url"]
    assert urls == [URL, "", URL]  # digitou, apagou, redigitou
    assert a.tela.publicacoes[0]["midias"][0]["figurinha"]["url"] == URL


def test_campo_que_insiste_em_https_nao_publica(ambiente):
    a = ambiente
    a.tela.url_https = 99
    with pytest.raises(bluestacks.ErroPostagem, match="campo_url"):
        rodar(a, montar_plano(a.midias, {"A": ["foto"]}, ensaio=False), ensaio=False)
    assert a.tela.publicacoes == []


def test_enter_que_quebra_linha_no_texto_da_figurinha_nao_publica(ambiente):
    a = ambiente
    a.tela.enter_quebra_linha = True
    with pytest.raises(bluestacks.ErroPostagem, match="quebra de linha"):
        rodar(a, montar_plano(a.midias, {"A": ["foto"]}, ensaio=False), ensaio=False)
    assert a.tela.publicacoes == []


def test_figurinha_so_na_ultima_e_musica_so_nos_videos_mudos(ambiente):
    a = ambiente
    rodar(a, montar_plano(a.midias, PADRAO, ensaio=False), ensaio=False)
    pa, pb, pc = a.tela.publicacoes
    assert [m["musica"] for m in pa["midias"]] == ["Áudio original | petermarkoski", None, None]
    assert [bool(m["figurinha"]) for m in pa["midias"]] == [False, False, True]
    assert [m["musica"] for m in pb["midias"]] == [None, None]  # vídeo com som não recebe música
    assert [bool(m["figurinha"]) for m in pb["midias"]] == [False, True]
    assert pc["midias"][0]["figurinha"]["url"] == URL
    assert a.tela.toques.count("figurinhas") == 3


def test_letra_sem_figurinha_no_plano_nao_recebe(ambiente):
    a = ambiente
    rodar(a, montar_plano(a.midias, {"A": ["foto", "foto"]}, ensaio=False, figurinha=False), ensaio=False)
    assert "figurinhas" not in a.tela.toques
    assert all(m["figurinha"] is None for m in a.tela.publicacoes[0]["midias"])


def test_facebook_ligado_e_desligado_antes_de_concluir(ambiente):
    a = ambiente
    a.tela.facebook_ligado = True
    res = rodar(a, montar_plano(a.midias, {"A": ["foto"]}, ensaio=False), ensaio=False)
    assert a.tela.publicacoes[0]["facebook"] is False
    t = a.tela.toques
    assert t.index("compartilhar_facebook_toggle") < t.index("concluir_publicacao")
    assert res["publicadas"] == ["A"]


def test_facebook_pelo_interruptor_ao_lado_do_texto(ambiente):
    a = ambiente
    a.tela.facebook_ligado = True
    a.tela.facebook_rotulo = True
    rodar(a, montar_plano(a.midias, {"A": ["foto"]}, ensaio=False), ensaio=False)
    assert a.tela.publicacoes[0]["facebook"] is False
    assert a.tela.toques.index("interruptores") < a.tela.toques.index("concluir_publicacao")


def test_facebook_nao_confunde_com_a_caixa_do_seu_story_logo_acima(ambiente):
    a = ambiente
    a.tela.facebook_ligado = True
    a.tela.facebook_rotulo = True
    a.tela.caixa_seu_story = True  # caixa marcada de "Seu story" 100 px acima do texto do Facebook
    rodar(a, montar_plano(a.midias, {"A": ["foto"]}, ensaio=False), ensaio=False)
    pub = a.tela.publicacoes[0]
    assert pub["facebook"] is False and pub["seu_story"] is True
    assert "caixa_seu_story" not in a.tela.toques


@pytest.mark.parametrize("modo", ["compartilhar", "direto"])
def test_aviso_de_compartilhar_no_facebook_e_recusado(ambiente, modo):
    a = ambiente
    a.tela.aviso_facebook = True
    a.tela.modo_publicacao = modo
    res = rodar(a, montar_plano(a.midias, {"A": ["foto"]}, ensaio=False), ensaio=False)
    assert res["publicadas"] == ["A"]
    assert a.tela.publicacoes[0]["facebook"] is False
    assert "dispensar_aviso" in a.tela.toques


def test_instagram_que_volta_para_a_camera_depois_de_publicar(ambiente):
    a = ambiente
    a.tela.volta_para_camera = True
    res = rodar(a, montar_plano(a.midias, {"A": ["foto"], "B": ["foto"]}, ensaio=False), ensaio=False)
    assert res["publicadas"] == ["A", "B"] and len(a.tela.publicacoes) == 2
    assert a.tela.estado == "feed"


def test_postados_ilegivel_nao_publica(ambiente, monkeypatch):
    a = ambiente

    def quebrado(data):
        raise postados.ErroPostados("postados.csv corrompido")

    monkeypatch.setattr(postados, "letras_postadas", quebrado)
    with pytest.raises(bluestacks.ErroPostagem, match="já postados"):
        rodar(a, montar_plano(a.midias, {"A": ["foto"]}, ensaio=False), ensaio=False)
    assert a.tela.toques == []


def test_letra_ja_postada_e_pulada_no_real(ambiente, monkeypatch):
    a = ambiente
    monkeypatch.setattr(postados, "letras_postadas", lambda data: {"A"})
    res = rodar(a, montar_plano(a.midias, {"A": ["foto"], "B": ["foto"]}, ensaio=False), ensaio=False)
    assert res["publicadas"] == ["B"]
    assert res["letras"][0]["estado"] == "nao_iniciada" and "postados" in res["letras"][0]["pulada"]
    assert a.enviados == ["B"]


def test_registro_que_falha_depois_de_publicar_para_e_fica_pendente(ambiente, monkeypatch, cfg):
    """A subiu e o CSV travou: para antes da B, A continua "publicada" e o pendente central faz o próximo
    postar/montar pular A (antes: seguia publicando B, C… e a próxima rodada publicava A de novo)."""
    a = ambiente
    registra_bem = postados.registrar

    def registrar(*args, **kw):
        raise postados.ErroPostados("postados.csv está aberto no Excel")

    monkeypatch.setattr(postados, "registrar", registrar)
    plano = montar_plano(a.midias, {"A": ["foto"], "B": ["foto"]}, ensaio=False)
    with pytest.raises(bluestacks.ErroPostagem, match="FOI PUBLICADA.*Parei antes da próxima letra") as erro:
        rodar(a, plano, ensaio=False)
    parcial = erro.value.resultado_parcial
    assert parcial["publicadas"] == ["A"]
    assert [x["estado"] for x in parcial["letras"]] == ["publicada", "nao_iniciada"]
    assert not parcial["letras"][0].get("incerta")
    assert parcial["parou_em"] == "letra A: registro em postados.csv"
    assert a.enviados == ["A"] and len(a.tela.publicacoes) == 1
    assert "Não iniciadas: B" in str(erro.value)
    # cópia na pasta do pedido e o pendente central, que é o que vale
    pendente = json.loads((a.ctx.pasta_saida / "postados_pendentes_A.json").read_text(encoding="utf-8"))
    assert pendente["letra"] == "A" and pendente["midias"][0]["arquivo"] == "A - 1.jpg"
    centrais = list((cfg.p.registros / "postados_pendentes").glob("*.json"))
    assert len(centrais) == 1 and parcial["letras"][0]["registro_pendente"] == str(centrais[0])
    assert LETRAS_POSTADAS("2026-09-22") == {"A"}
    # próxima rodada real (o mesmo plano, com o registro de verdade): A é pulada, só B sobe
    monkeypatch.setattr(postados, "letras_postadas", LETRAS_POSTADAS)
    monkeypatch.setattr(postados, "registrar", registra_bem)  # Excel fechado
    res = rodar(a, plano, ensaio=False)
    assert res["publicadas"] == ["B"] and res["letras"][0]["pulada"]
    assert a.enviados == ["A", "B"] and len(a.tela.publicacoes) == 2


def test_csv_que_nao_grava_para_antes_de_publicar(ambiente, monkeypatch):
    a = ambiente

    def preso():
        raise postados.ErroPostados("postados.csv está aberto no Excel")

    monkeypatch.setattr(postados, "testar_gravacao", preso)
    with pytest.raises(bluestacks.ErroPostagem, match="nada foi publicado") as erro:
        rodar(a, montar_plano(a.midias, {"A": ["foto"]}, ensaio=False), ensaio=False)
    assert erro.value.resultado_parcial["parou_em"] == "gravação de postados.csv"
    assert a.tela.toques == [] and a.enviados == []
    rodar(a, montar_plano(a.midias, {"A": ["foto"]}), ensaio=True)  # o ensaio não grava nada: não testa
    assert a.tela.publicacoes == []


def test_js_de_conferencia_inclui_letra_incerta(ambiente):
    """Falhou depois de "Seu story" (estado "falhou" + incerta): o JS não pode dizer "Nada publicado"."""
    a = ambiente
    plano = montar_plano(a.midias, {"A": ["foto"], "B": ["foto"]}, ensaio=False)
    res = bluestacks.novo_resultado(plano, ensaio=False)
    res["letras"][0].update(estado="falhou", incerta=True, erro="o Instagram não voltou ao feed")
    res["parou_em"] = "letra A: concluir_publicacao"
    bluestacks._anexar_relatorio(plano, res, a.ctx)
    assert not res["js_conferencia"].startswith("// Nada publicado")
    assert res["js_conferencia"] in res["relatorio"]


# ---------------------------------------------------------------- envio, diagnóstico e validação

def test_midia_faltando_na_galeria_para_antes_do_instagram(ambiente):
    a = ambiente

    def enviar(L):
        raise android.ErroEnvio("Faltaram 1 de 2 mídia(s) na galeria do BlueStacks: A - 2.", faltando=["A - 2"])

    with pytest.raises(bluestacks.ErroPostagem, match="A - 2") as erro:
        bluestacks.executar(montar_plano(a.midias, {"A": ["foto", "foto"]}, ensaio=False), a.ctx, ensaio=False,
                            tela=a.tela, enviar=enviar)
    assert a.tela.apps == [] and a.tela.toques.count("criar") == 0
    assert erro.value.resultado_parcial["parou_em"] == "letra A: enviar_midias"


def test_diagnostico_grava_xml_e_print_por_passo(ambiente):
    a = ambiente
    rodar(a, montar_plano(a.midias, {"A": ["video_mudo", "foto"]}), ensaio=True, diagnostico=True)
    xmls = sorted(p.name for p in a.ctx.pasta_saida.glob("passo_*.xml"))
    pngs = sorted(p.name for p in a.ctx.pasta_saida.glob("passo_*.png"))
    assert xmls and [x[:-4] for x in xmls] == [p[:-4] for p in pngs]
    assert xmls[0] == "passo_001_A_enviar_midias.xml"
    numeros = [int(re.match(r"passo_(\d+)_", x).group(1)) for x in xmls]
    assert numeros == list(range(1, len(xmls) + 1))
    nomes = {x.split("_A_", 1)[1][:-4] for x in xmls}
    assert {"abrir_story", "selecionar_varios", "conferir_selecao", "musica_1", "figurinha_2", "sair_sem_publicar"} <= nomes


def test_sem_diagnostico_nao_grava_passos(ambiente):
    a = ambiente
    rodar(a, montar_plano(a.midias, {"A": ["foto"]}), ensaio=True)
    assert not list(a.ctx.pasta_saida.glob("passo_*"))


@pytest.mark.parametrize("mexer, trecho", [
    (lambda p: p["letras"][0]["midias"][0].update(figurinha={"url": URL, "texto": "x"}), "última mídia"),
    (lambda p: p["letras"][0]["midias"][-1]["figurinha"].update(url="https://" + URL), "sem https://"),
    (lambda p: p["letras"][0]["midias"][0].update(musica=None), "qual música"),
    (lambda p: p["letras"][0]["midias"][1].update(caminho="/nao/existe.jpg"), "não encontrado"),
    (lambda p: p["letras"][0]["midias"][1].update(hash="0" * 64), "hash diferente"),
])
def test_plano_invalido_nao_comeca(ambiente, mexer, trecho):
    a = ambiente
    plano = montar_plano(a.midias, {"A": ["video_mudo", "foto"]}, ensaio=False)
    mexer(plano)
    with pytest.raises(bluestacks.ErroPostagem, match=trecho) as erro:
        rodar(a, plano, ensaio=False)
    assert erro.value.resultado_parcial["parou_em"] == "validação do plano"
    assert a.tela.toques == [] and a.enviados == []


def test_erro_ao_conferir_o_plano_sobe_com_resultado_parcial(ambiente, monkeypatch):
    a = ambiente

    def preso(caminho):
        raise PermissionError(f"arquivo aberto em outro programa: {caminho}")

    monkeypatch.setattr(bluestacks.midia, "hash_arquivo", preso)
    with pytest.raises(bluestacks.ErroPostagem, match="aberto em outro programa") as erro:
        rodar(a, montar_plano(a.midias, {"A": ["foto"]}, ensaio=False), ensaio=False)
    assert erro.value.resultado_parcial["parou_em"] == "validação do plano"
    assert [x["estado"] for x in erro.value.resultado_parcial["letras"]] == ["nao_iniciada"]
    assert a.tela.toques == []


def test_mov_nao_vai_para_a_galeria(ambiente):
    a = ambiente
    plano = montar_plano(a.midias, {"A": ["foto"]})
    caminho, h = _arquivo(a.midias, "A - 9.mov")
    plano["letras"][0]["midias"][0].update(caminho=str(caminho), arquivo=caminho.name, hash=h)
    with pytest.raises(bluestacks.ErroPostagem, match="formato .mov"):
        rodar(a, plano)


def test_escolher_musica_pelo_autor_na_mesma_linha():
    textos = TelaFalsa().resultados_musica
    tela = TelaFalsa()
    tela.estado, tela.busca = "musica", "x"
    grade = tela.grade("escolher_musica")
    assert len(grade) == 2 * len(textos)
    el = bluestacks.escolher_resultado_musica(grade, "Áudio original", "petermarkoski")
    assert el.texto == "Áudio original" and el.limites[1] == 300 + 160
    el = bluestacks.escolher_resultado_musica(grade, "I know what you want", "Madison Beer/Calley")
    assert el.texto == "I Know What You Want"
    assert bluestacks.escolher_resultado_musica(grade, "Áudio original", "enfermeira_vitoria0") is None


# ---------------------------------------------------------------- entradas (tarefa, cli, testes do PC)

class ConexaoFalsa:
    serial, adb = "127.0.0.1:5555", "adb"

    def info(self, pacote):
        return {"serial": self.serial, "android": "11", "tela": "Physical size: 1080x1920", "instagram": "300.0"}


@pytest.fixture
def sem_emulador(ambiente, monkeypatch):
    a = ambiente
    monkeypatch.setattr(android, "conectar", lambda cfg=None: ConexaoFalsa())
    monkeypatch.setattr(android, "abrir_tela", lambda con, cfg=None: a.tela)
    monkeypatch.setattr(android, "enviar_letra", lambda con, data, letra, midias, cfg=None: a.enviar({"letra": letra, "midias": midias}))
    return a


def test_tarefa_com_plano_em_ensaio_nao_publica_mesmo_com_pedido_real(sem_emulador):
    a = sem_emulador
    ctx = Contexto(a.ctx.pasta_saida / "pedido", ensaio=False, id_pedido="p1")
    res = bluestacks.tarefa({"plano": montar_plano(a.midias, {"A": ["foto"]}, ensaio=True)}, ctx)
    assert res["ensaio"] is True and a.tela.publicacoes == []
    assert res["dispositivo"]["serial"] == "127.0.0.1:5555"


def test_tarefa_real_publica(sem_emulador):
    a = sem_emulador
    ctx = Contexto(a.ctx.pasta_saida / "pedido", ensaio=False, id_pedido="p2")
    res = bluestacks.tarefa({"plano": montar_plano(a.midias, {"A": ["foto"]}, ensaio=False)}, ctx)
    assert res["publicadas"] == ["A"] and a.registros[0]["pedido"] == "p2"
    # a IA do Cowork não roda comandos: o aviso e o JS de conferência vêm prontos no resultado
    assert "CONFERE" in res["js_conferencia"] and "slice(-" in res["js_conferencia"]
    assert res["relatorio"] and (ctx.pasta_saida / "relatorio.txt").exists()


def test_cli_padrao_e_ensaio_e_real_precisa_de_flag(sem_emulador, cfg, capsys):
    a = sem_emulador
    arq = a.midias / "plano-teste.json"
    arq.write_text(json.dumps(montar_plano(a.midias, {"A": ["foto"]}, ensaio=True), ensure_ascii=False), encoding="utf-8")
    assert bluestacks.cli(["--plano", str(arq)]) == 0
    assert a.tela.publicacoes == []
    assert "ENSAIO" in capsys.readouterr().out
    saidas = list((cfg.p.trabalho_stories / "2026-09-22").glob("postar-*/resultado.json"))
    assert saidas and json.loads(saidas[0].read_text(encoding="utf-8"))["ensaio"] is True
    assert bluestacks.cli(["--plano", str(arq), "--ensaio"]) == 0  # --ensaio explícito (como no cli.py) é aceito
    assert a.tela.publicacoes == []
    with pytest.raises(SystemExit):
        bluestacks.cli(["--plano", str(arq), "--real", "--ensaio"])
    assert a.tela.publicacoes == []
    assert bluestacks.cli(["--plano", str(arq), "--real"]) == 0
    assert len(a.tela.publicacoes) == 1


def test_cli_devolve_1_quando_para(sem_emulador, capsys):
    a = sem_emulador
    a.tela.quebrar = {"abertura": 1, "chave": "abrir_galeria"}
    arq = a.midias / "plano-teste.json"
    arq.write_text(json.dumps(montar_plano(a.midias, {"A": ["foto"]})), encoding="utf-8")
    assert bluestacks.cli(["--plano", str(arq)]) == 1
    assert "ERRO" in capsys.readouterr().err


def test_trava_do_emulador_impede_dois_ao_mesmo_tempo(sem_emulador, monkeypatch):
    from rotinas import fila

    a = sem_emulador
    conexoes = []
    monkeypatch.setattr(android, "conectar", lambda cfg=None: conexoes.append(1) or ConexaoFalsa())
    plano = montar_plano(a.midias, {"A": ["foto"]}, ensaio=False)
    outro = fila.Trava(fila.pasta_fila() / "bluestacks.lock")  # ex.: o vigia postando
    assert outro.adquirir()
    try:
        with pytest.raises(bluestacks.ErroPostagem, match="em uso") as erro:
            bluestacks.executar(plano, a.ctx, ensaio=False)
        assert erro.value.resultado_parcial["parou_em"] == "trava do BlueStacks"
        with pytest.raises(RuntimeError, match="em uso"):
            bluestacks.teste_real(Contexto(a.ctx.pasta_saida / "teste-real"), [])
        assert conexoes == [] and a.tela.toques == [] and a.enviados == []
    finally:
        outro.liberar()
    res = bluestacks.executar(plano, a.ctx, ensaio=False)
    assert res["publicadas"] == ["A"]
    depois = fila.Trava(fila.pasta_fila() / "bluestacks.lock")
    assert depois.adquirir()  # liberada no fim da postagem
    depois.liberar()


def test_teste_real_percorre_ate_a_galeria_sem_publicar(sem_emulador):
    a = sem_emulador
    ctx = Contexto(a.ctx.pasta_saida / "teste-real", diagnostico=True)
    res = bluestacks.teste_real(ctx, [])
    assert res["ok"] is True, res
    assert [p["passo"] for p in res["passos"]] == ["abrir_instagram", "entrar_no_story", "abrir_galeria",
                                                   "selecionar_varios", "album_menu"]
    assert res["miniaturas_galeria"] == a.tela.recentes
    assert not set(a.tela.toques) & bluestacks.CHAVES_PUBLICAR
    assert not {"avancar"} & set(a.tela.toques)
    xmls = sorted(p.name for p in ctx.pasta_saida.glob("passo_*.xml"))
    assert any("criar" in x for x in xmls) and any("abrir_story" in x for x in xmls) and len(xmls) >= 7
    assert res["saiu_com_seguranca"] and a.tela.estado == "feed"
    assert "Instagram 300.0" in res["resumo"]
    from rotinas import fila

    trava = fila.Trava(fila.pasta_fila() / "bluestacks.lock")
    assert trava.adquirir()  # o teste liberou a trava do emulador
    trava.liberar()


def test_teste_ensaio_usa_o_plano_mais_recente_da_data(sem_emulador, cfg):
    a = sem_emulador
    pasta = cfg.p.trabalho_stories / "2026-09-22"
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / "plano-1.json").write_text(json.dumps(montar_plano(a.midias, {"A": ["foto"]}, ensaio=False)), encoding="utf-8")
    ctx = Contexto(a.ctx.pasta_saida / "teste-ensaio", ensaio=True, diagnostico=True)
    res = bluestacks.teste_ensaio(ctx, ["--data", "2026-09-22"])
    assert res["ok"] is True and res["ensaio"] is True
    assert a.tela.publicacoes == []
    assert (ctx.pasta_saida / "ensaio_A_1.png").is_file()
    assert list(ctx.pasta_saida.glob("passo_*.xml"))


@pytest.mark.ffmpeg
def test_ensaio_sintetico_monta_letra_de_teste_sem_publicar(sem_emulador, cfg):
    a = sem_emulador
    a.tela.criar_abre_galeria = True
    a.tela.albuns["2000-01-01_T"] = 3
    ctx = Contexto(a.ctx.pasta_saida / "ensaio-sintetico", diagnostico=True)
    res = bluestacks.teste_ensaio(ctx, ["--sintetico"])
    assert res["ok"] is True, res
    assert a.tela.publicacoes == [] and not set(a.tela.toques) & bluestacks.CHAVES_PUBLICAR
    (letra,) = res["letras"]
    assert letra["estado"] == "ensaio_ok" and len(letra["prints"]) == 3
    # mídia de teste fica na pasta de trabalho das rotinas, nunca em Stories da Loja
    assert Path(res["plano"]).is_relative_to(cfg.p.trabalho_stories)
    assert not any(cfg.p.stories_fonte.rglob("T - *"))
    plano = bluestacks.plano_sintetico(Path(res["plano"]))
    midias = plano["letras"][0]["midias"]
    assert midias[0]["precisa_musica"] and midias[0]["musica"]
    assert midias[-1]["figurinha"]["url"].startswith("wa.me/") and all(m["figurinha"] is None for m in midias[:-1])
