import pytest

from rotinas.stories import link
from rotinas.stories.link import ErroRegra


def test_link_sem_https_com_acento_e_espaco_codificados(cfg):
    url = link.montar_link("Vestido Midi Alça")
    assert url == "wa.me/5582988748649?text=Quero+comprar+o+Vestido+Midi+Al%C3%A7a"
    assert not url.lower().startswith("http")
    assert "://" not in url and " " not in url


def test_numero_vem_da_config(cfg):
    cfg.alterar("stories", whatsapp="55 (82) 99999-0000")
    assert link.montar_link("Vestido").startswith("wa.me/5582999990000?text=")


@pytest.mark.parametrize("peca, artigo", [
    ("Saia Longa", "a"),
    ("Blusa Ciganinha", "a"),
    ("Calça Pantalona", "a"),
    ("calca jeans", "a"),
    ("Túnica Bordada", "a"),
    ("T-shirt Básica", "a"),
    ("Vestido Midi", "o"),
    ("Conjunto Linho", "o"),
    ("Macacão Pantalona", "o"),
])
def test_artigo_pela_primeira_palavra(cfg, peca, artigo):
    assert link.mensagem(peca).startswith(f"Quero comprar {artigo} ")
    assert f"text=Quero+comprar+{artigo}+" in link.montar_link(peca)


def test_caixa_alta_vira_titulo_com_preposicoes_minusculas(cfg):
    assert link.nome_peca("VESTIDO LONGO DE FESTA COM FENDA") == "Vestido Longo de Festa com Fenda"
    assert link.nome_peca("MACACÃO  ALÇA   DA SORTE") == "Macacão Alça da Sorte"
    assert link.nome_peca("T-SHIRT BÁSICA") == "T-Shirt Básica"
    assert link.nome_peca("DE LINHO") == "De Linho"  # a primeira palavra fica em maiúscula
    assert link.montar_link("SAIA MIDI DE LINHO").endswith("text=Quero+comprar+a+Saia+Midi+de+Linho")


def test_nome_misto_fica_como_veio(cfg):
    assert link.nome_peca("  Vestido Midi   Alça ") == "Vestido Midi Alça"
    assert link.nome_peca("vestido midi") == "vestido midi"


@pytest.mark.parametrize("peca", ["", "   ", None])
def test_mensagem_nunca_generica(cfg, peca):
    with pytest.raises(ErroRegra, match="nomear a peça"):
        link.montar_link(peca)


def test_link_modelo_com_https_e_recusado(cfg):
    cfg.alterar("stories", link_modelo="https://wa.me/{numero}?text={mensagem}")
    with pytest.raises(ErroRegra, match="sem https://"):
        link.montar_link("Vestido Midi")


@pytest.mark.parametrize("url", ["HTTPS://wa.me/55?text=x", "http://wa.me/55?text=x", "wa.me/55?text="])
def test_validar_link(url):
    with pytest.raises(ErroRegra):
        link.validar_link(url)


def test_rodizio_do_texto_da_figurinha(cfg):
    textos = [link.texto_figurinha(i) for i in range(4)]
    assert textos == ["Comprar", "Comprar agora", "Comprar pelo Whatsapp", "Comprar"]


def test_musica_do_video_sem_som_e_busca_fashion_ao_acaso(cfg):
    """Regra do usuário (25/09/2026): buscar "fashion" e escolher qualquer uma das faixas, ao acaso."""
    assert link.musica_sem_som() == {"busca": "fashion", "escolha": "aleatoria"}
    m = link.musica_sem_som()
    m["busca"] = "mexido"
    assert link.musica_sem_som()["busca"] == "fashion"  # devolve cópia


def test_lista_vazia_na_config(cfg):
    cfg.alterar("stories", textos_figurinha=[])
    with pytest.raises(ErroRegra, match="textos_figurinha"):
        link.texto_figurinha(0)


def test_vestido_de_festa_null_pergunta_ao_usuario(cfg):
    cfg.alterar("stories", link_em_vestido_de_festa=None)
    with pytest.raises(ErroRegra, match="Regra não confirmada: vestido de festa leva figurinha de link"):
        link.leva_link("Vestidos de Festa")
    with pytest.raises(ErroRegra, match="link_em_vestido_de_festa"):
        link.leva_link("VESTIDO DE FESTA")
    assert link.leva_link("Vestidos") is True  # só a festa depende da regra


@pytest.mark.parametrize("regra", [True, False])
def test_vestido_de_festa_segue_a_config(cfg, regra):
    cfg.alterar("stories", link_em_vestido_de_festa=regra)
    assert link.leva_link("Vestidos de Festa") is regra
    assert link.leva_link("vestido de festa") is regra  # sem diferenciar maiúsculas


def test_config_atual_festa_sem_link(cfg):
    assert link.leva_link("VESTIDO DE FESTA") is False


@pytest.mark.parametrize("categoria", ["Vestidos", "Vestidos Casuais", "Conjuntos", "Macacões", None, ""])
def test_demais_categorias_levam_link(cfg, categoria):
    cfg.alterar("stories", link_em_vestido_de_festa=None)
    assert link.leva_link(categoria) is True


def test_regra_com_valor_invalido(cfg):
    cfg.alterar("stories", link_em_vestido_de_festa="sim")
    with pytest.raises(ErroRegra, match="true, false ou null"):
        link.leva_link("Vestidos de Festa")


def test_figurinha(cfg):
    f = link.figurinha("Vestido Midi Alça", 1)
    assert f == {"url": "wa.me/5582988748649?text=Quero+comprar+o+Vestido+Midi+Al%C3%A7a", "texto": "Comprar agora"}
