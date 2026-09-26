"""Seletores de ``config/bluestacks.json`` conferidos contra telas REAIS do Instagram 448 capturadas no PC.

Os XMLs em ``tests/dados/telas_448/`` vieram de ``execucoes/`` (já sem nome/mensagem de notificação). Motivo: em
26/09 00:17 o seletor das faixas exigia o prefixo ``com.instagram.android:id/``, mas as telas novas do Instagram
(Compose) têm ``resource-id`` sem prefixo (``audio_browser_track_0_…``, ``music_button``, ``audio_bar_select_tap_target``):
a lista apareceu e o script disse "não trouxe nenhuma faixa". Todo seletor novo entra aqui com a tela real.
"""

from pathlib import Path

import pytest

from dubles_android import Relogio, u2_do_xml
from rotinas import config
from rotinas.stories import android

TELAS = Path(__file__).parent / "dados" / "telas_448"


@pytest.fixture
def relogio(monkeypatch):
    r = Relogio()
    monkeypatch.setattr(android, "dormir", r.dormir)
    monkeypatch.setattr(android, "agora", r.agora)
    return r


@pytest.fixture
def telas(cfg):
    seletores = config.carregar("bluestacks")["seletores"]

    def abrir(nome):
        return android.Tela(u2_do_xml(TELAS / f"{nome}.xml"), seletores=seletores)

    return abrir


def test_busca_de_musica_acha_as_faixas_sem_prefixo_no_id(telas, relogio):
    tela = telas("busca_musica")
    faixas = tela.grade("faixas_musica")
    assert len(faixas) == 10
    assert faixas[0].descricao.startswith("Selecionar faixa Fool Me Once de Jazmine Robinson")
    assert tela.existe("buscar_musica") and not tela.existe("usar_musica")


def test_barra_da_musica_tem_a_seta_e_ela_nao_conta_como_faixa(telas, relogio):
    tela = telas("barra_da_musica")
    seta = tela.achar("usar_musica", 0, plano_b=False)
    assert seta is not None and seta.limites == (776, 1448, 884, 1552)
    assert len(tela.grade("faixas_musica")) == 10  # a barra também diz "Selecionar faixa …", mas não é linha


def test_editor_acha_musica_e_figurinhas_pelo_id(telas, relogio):
    tela = telas("editor")
    assert tela.achar("musica", 0, plano_b=False).limites == (784, 228, 880, 324)  # o botão, não o ícone
    assert tela.achar("figurinhas", 0, plano_b=False).limites == (784, 124, 880, 220)
    assert tela.existe("editor") and not tela.existe("seu_story")
    miniaturas = tela.grade("miniaturas_editor")  # para trocar de mídia (figurinha na última)
    assert [m.descricao for m in miniaturas] == ["Vídeo selecionado", "Foto selecionada", "Foto selecionada"]


def test_galeria_com_selecao_e_feed(telas, relogio):
    g = telas("galeria_selecionada")
    assert g.existe("selecao_ativa") and g.existe("album_menu") and len(g.grade("miniaturas_galeria")) == 3
    f = telas("feed")
    assert f.existe("feed") and f.existe("criar")
    assert not f.existe("tela_privada") and f.faixa_notificacao() is None


def test_menu_de_albuns_tem_todos_os_albuns_e_itens_para_rolar(telas, relogio):
    tela = telas("menu_albuns")
    assert tela.existe("album_todos")
    assert len(tela.grade("itens_lista_album")) >= 4


def test_notificacao_flutuante_e_achada(telas, relogio):
    tela = telas("notificacao_flutuante")
    assert tela.faixa_notificacao() == (104, 289)


def test_editor_da_musica_tem_o_concluir(telas, relogio):
    """Ensaio de 26/09 00:26: depois da seta, a tela de ajuste da música ("Somente música", trecho, ✓ no canto)."""
    tela = telas("editor_da_musica")
    ok = tela.achar("concluir_musica", 0, plano_b=False)
    assert ok is not None and ok.limites == (796, 8, 892, 104) and ok.descricao == "Concluir"
    assert not tela.existe("editor")  # ainda não voltou ao editor do story


def test_figurinhas_buscando_link(telas, relogio):
    """Ensaio de 26/09 00:34: a busca "link" mostrou "Figurinha de link" (l minúsculo), que o seletor não pegava."""
    tela = telas("figurinhas_busca_link")
    link = tela.achar("figurinha_link", 0, plano_b=False)
    assert link is not None and link.limites == (30, 245, 205, 420)
    assert tela.achar("buscar_figurinha", 0, plano_b=False).texto == "link"


def test_adicionar_link(telas, relogio):
    """Ensaio de 26/09 00:45: tela "Adicionar link" com o link já digitado; "Personalizar o texto da figurinha" (com
    "o") não batia com o seletor."""
    tela = telas("adicionar_link")
    assert tela.ler_texto("campo_url").startswith("wa.me/5582988748649?text=")
    assert tela.achar("personalizar_texto", 0, plano_b=False).limites == (32, 378, 868, 419)
    assert tela.achar("concluir_figurinha", 0, plano_b=False).limites == (704, 41, 900, 156)
    assert tela.achar("campo_texto_figurinha", 0, plano_b=False) is None  # só aparece depois de personalizar
