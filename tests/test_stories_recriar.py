"""Foto de várias cores com alguma sem estoque: recriada sem essa cor pela API de imagens da OpenAI (regra do usuário
de 26/09/2026) antes de montar. API simulada; a original nunca muda."""

import base64
import io
import json
from pathlib import Path

import pytest
from PIL import Image

from conftest import RespostaFalsa
from rotinas import config, fila
from rotinas.stories import pedido, recriar
from test_stories_pedido import DATA, ambiente, cliente, manifesto  # noqa: F401 - fixture reaproveitada

CHAVE = "sk-teste-0123456789abcdef"


def _png(cor=(20, 120, 60)) -> bytes:
    b = io.BytesIO()
    Image.new("RGB", (1024, 1536), cor).save(b, "PNG")
    return b.getvalue()


class HttpFalso:
    def __init__(self, respostas=None):
        self.respostas = list(respostas or [])
        self.chamadas = []

    def post(self, url, headers=None, files=None, data=None, timeout=None):
        self.chamadas.append({"url": url, "headers": headers, "arquivo": files["image"][0], "data": data})
        if self.respostas:
            return self.respostas.pop(0)
        return RespostaFalsa(200, {"data": [{"b64_json": base64.b64encode(_png()).decode()}]})


@pytest.fixture
def com_chave(ambiente, monkeypatch):  # noqa: F811
    env = Path(config.caminho_env())
    env.write_text(env.read_text(encoding="utf-8") + f"OPENAI_API_KEY={CHAVE}\n", encoding="utf-8")
    config.limpar_cache()
    return ambiente


def _foto_real(man, nome):
    """O manifesto de teste grava bytes quaisquer; a recriação precisa de uma imagem de verdade."""
    letra = nome.split(" - ")[0]
    item = next(m for m in man["letras"][letra]["midias"] if m["nome"] == nome)
    Image.new("RGB", (1080, 1920), (200, 30, 30)).save(item["caminho"], "JPEG")
    return Path(item["caminho"])


def test_recriar_salva_arquivo_novo_e_nao_mexe_na_original(com_chave):
    man = manifesto(com_chave, {"A": ["foto", "foto"]})
    original = _foto_real(man, "A - 2")
    antes = original.read_bytes()
    http = HttpFalso()
    res = recriar.recriar(DATA, [{"nome": "A - 2", "tirar": ["Preto"], "ficam": ["Verde"]}], http=http)
    (feita,) = res["recriadas"]
    nova = Path(feita["recriada"])
    assert nova.is_file() and nova.parent == recriar.pasta_recriadas(DATA) and nova.name == "A - 2 sem Preto.jpg"
    with Image.open(nova) as img:
        assert img.format == "JPEG"
    assert original.read_bytes() == antes  # a original fica intacta
    assert Path(feita["folha"]).is_file()
    (chamada,) = http.chamadas
    assert chamada["url"].endswith("/v1/images/edits") and chamada["headers"]["Authorization"] == f"Bearer {CHAVE}"
    assert chamada["data"]["model"] and "Preto" in chamada["data"]["prompt"] and "Verde" in chamada["data"]["prompt"]
    reg = recriar.ler_registro(DATA)["A - 2"]
    assert reg["tirar"] == ["Preto"] and reg["ficam"] == ["Verde"] and reg["caminho"] == str(nova)


def test_recriar_de_novo_nao_sobrescreve_a_anterior(com_chave):
    man = manifesto(com_chave, {"A": ["foto", "foto"]})
    _foto_real(man, "A - 2")
    pedido_ = [{"nome": "A - 2", "tirar": ["Preto"], "ficam": ["Verde"]}]
    primeira = recriar.recriar(DATA, pedido_, http=HttpFalso())["recriadas"][0]["recriada"]
    segunda = recriar.recriar(DATA, pedido_, http=HttpFalso())["recriadas"][0]["recriada"]
    assert Path(primeira).is_file() and Path(segunda).is_file() and primeira != segunda
    assert recriar.ler_registro(DATA)["A - 2"]["caminho"] == segunda


def test_video_nao_e_recriado(com_chave):
    manifesto(com_chave, {"A": ["video", "foto"]})
    with pytest.raises(recriar.ErroRecriar, match="só foto"):
        recriar.recriar(DATA, [{"nome": "A - 1", "tirar": ["Preto"], "ficam": ["Verde"]}], http=HttpFalso())


def test_sem_chave_da_erro_claro_sem_chamar_a_api(ambiente):  # noqa: F811
    man = manifesto(ambiente, {"A": ["foto", "foto"]})
    _foto_real(man, "A - 2")
    http = HttpFalso()
    with pytest.raises(recriar.ErroRecriar, match="OPENAI_API_KEY"):
        recriar.recriar(DATA, [{"nome": "A - 2", "tirar": ["Preto"], "ficam": ["Verde"]}], http=http)
    assert http.chamadas == []


def test_erro_da_api_nao_mostra_a_chave(com_chave):
    man = manifesto(com_chave, {"A": ["foto", "foto"]})
    _foto_real(man, "A - 2")
    http = HttpFalso([RespostaFalsa(400, {"error": {"message": f"Bad request for key {CHAVE}"}})])
    with pytest.raises(recriar.ErroRecriar) as e:
        recriar.recriar(DATA, [{"nome": "A - 2", "tirar": ["Preto"], "ficam": ["Verde"]}], http=http)
    assert "HTTP 400" in str(e.value) and CHAVE not in str(e.value)


# ---------------------------------------------------------------- montar

IDENT = {"A": {"sku": "FB-0123", "midias": {"A - 1": ["verde"], "A - 2": ["verde", "preto"]}}}


def test_montar_para_e_pede_recriar_antes_de_tudo(com_chave):
    """Foto com Verde (tem) e Preto (sem estoque): não corta; para sem gravar nada e traz o stories.recriar pronto."""
    manifesto(com_chave, {"A": ["foto", "foto"]})
    with pytest.raises(pedido.ErroPedido) as e:
        pedido.montar(DATA, IDENT, cliente=cliente())
    msg = str(e.value)
    assert "Recriar antes de montar" in msg and "A - 2" in msg
    args = json.loads(msg.split("com estes args:\n")[1].split("\n")[0])
    assert args == {"data": DATA, "midias": [{"nome": "A - 2", "tirar": ["Preto"], "ficam": ["Verde"]}]}
    assert not list((fila.pasta_fila() / "pendente").glob("*.json"))


def test_montar_com_recriada_aprovada_usa_a_imagem_nova(com_chave):
    man = manifesto(com_chave, {"A": ["foto", "foto"]})
    original = _foto_real(man, "A - 2")
    recriar.recriar(DATA, [{"nome": "A - 2", "tirar": ["Preto"], "ficam": ["Verde"]}], http=HttpFalso())
    res = pedido.montar(DATA, IDENT, cliente=cliente(), recriadas=["A - 2"])
    (letra,) = res["plano"]["letras"]
    a2 = next(m for m in letra["midias"] if m["nome"] == "A - 2")
    assert a2["caminho"] == recriar.ler_registro(DATA)["A - 2"]["caminho"] and a2["cores"] == ["Verde"]
    assert a2["recriada_de"] == original.name and a2["figurinha"]  # continua sendo a última: leva o link
    assert any(c["motivo"] == pedido.MOTIVO_RECRIADA and c["detalhe"] == "Preto" for c in res["plano"]["cortes"])
    assert res["pedido_postagem"]


def test_recriada_que_nao_tira_a_cor_certa_ou_mudou_volta_a_pedir(com_chave):
    man = manifesto(com_chave, {"A": ["foto", "foto"]})
    _foto_real(man, "A - 2")
    recriar.recriar(DATA, [{"nome": "A - 2", "tirar": ["Rosa"], "ficam": ["Verde"]}], http=HttpFalso())
    with pytest.raises(pedido.ErroPedido, match="recriar de novo"):
        pedido.montar(DATA, IDENT, cliente=cliente(), recriadas=["A - 2"])
    recriar.recriar(DATA, [{"nome": "A - 2", "tirar": ["Preto"], "ficam": ["Verde"]}], http=HttpFalso())
    Path(recriar.ler_registro(DATA)["A - 2"]["caminho"]).write_bytes(b"mexida depois")
    with pytest.raises(pedido.ErroPedido, match="recriar de novo"):
        pedido.montar(DATA, IDENT, cliente=cliente(), recriadas=["A - 2"])


def test_video_de_varias_cores_com_uma_sem_estoque_continua_cortado(com_chave):
    manifesto(com_chave, {"A": ["foto", "video"]})
    res = pedido.montar(DATA, IDENT, cliente=cliente())
    assert [m["nome"] for m in res["plano"]["letras"][0]["midias"]] == ["A - 1"]
    assert any("vídeo não dá para recriar" in a for a in res["plano"]["avisos"])


def test_foto_so_com_a_cor_sem_estoque_e_cortada_como_antes(com_chave):
    manifesto(com_chave, {"A": ["foto", "foto"]})
    res = pedido.montar(DATA, {"A": {"sku": "FB-0123", "midias": {"A - 1": ["verde"], "A - 2": ["preto"]}}},
                        cliente=cliente())
    assert [m["nome"] for m in res["plano"]["letras"][0]["midias"]] == ["A - 1"]
