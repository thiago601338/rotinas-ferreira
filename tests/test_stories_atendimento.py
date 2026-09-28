"""Contrato do registro remoto e isolamento do fluxo de publicação, sem rede real."""
import json
from datetime import datetime

import pytest

from rotinas.stories import atendimento, bluestacks
from test_stories_bluestacks import ambiente, montar_plano, rodar  # noqa: F401

INICIO, FIM = "2026-09-27T12:00:00+00:00", "2026-09-27T12:05:00+00:00"
SEGREDO = "a" * 64


def letra(cores=("preto", "preto")):
    return {"letra": "A", "sku": "FB-0001", "midias": [
        {"nome": f"A - {i+1}", "cores": [cor]} for i, cor in enumerate(cores)]}


@pytest.fixture
def rede(monkeypatch, cfg):
    cfg.alterar("atendimento", registrar_stories=True)
    monkeypatch.setenv("ROTINAS_SEGREDO_ATENDIMENTO", SEGREDO)
    chamadas = []

    def post(url, **kwargs):
        chamadas.append({"url": url, **kwargs})
        return type("Resposta", (), {"status_code": 200, "json": lambda self: {"ok": True, "registrados": 2}})()

    monkeypatch.setattr(atendimento.requests, "post", post)
    return chamadas


def test_mesma_peca_cor_usa_corpo_simples():
    assert atendimento.montar_corpo(letra(), INICIO, FIM) == {
        "letra": "A", "sku": "FB-0001", "cor": "preto", "n_midias": 2,
        "publicado_de": INICIO, "publicado_ate": FIM}


def test_cores_diferentes_usam_manifesto_na_ordem_original():
    corpo = atendimento.montar_corpo(letra(("verde", "preto")), INICIO, FIM)
    assert corpo["varios_modelos"] is True
    assert corpo["midias"] == [{"sku": "FB-0001", "cor": "verde"}, {"sku": "FB-0001", "cor": "preto"}]


def test_foto_com_varias_cores_nao_inventa_cor_unica():
    dados = letra()
    dados["midias"][0]["cores"] = ["preto", "rosa"]
    assert atendimento.montar_corpo(dados, INICIO, FIM)["midias"][0]["cor"] is None


def test_varios_modelos_exige_sku_por_arquivo():
    dados = {**letra(), "varios_modelos": True}
    with pytest.raises(atendimento.RegistroPendente, match="sku_por_midia_ausente"):
        atendimento.montar_corpo(dados, INICIO, FIM)
    dados["midias"][0]["sku"], dados["midias"][1]["sku"] = "FB-0001", "FB-0002"
    assert [m["sku"] for m in atendimento.montar_corpo(dados, INICIO, FIM)["midias"]] == ["FB-0001", "FB-0002"]


def test_ids_por_midia_preservam_correspondencia_sem_herdar_produto_de_outro_sku():
    dados = {**letra(), "product_id": "00000000-0000-4000-8000-000000000001"}
    dados["midias"][0].update(sku="FB-0002", story_id="180000000001")
    dados["midias"][1].update(story_id="180000000002")
    corpo = atendimento.montar_corpo(dados, INICIO, FIM)
    assert "product_id" not in corpo["midias"][0]
    assert corpo["midias"][1]["product_id"] == dados["product_id"]


@pytest.mark.parametrize("inicio,fim", [("2026-09-27T12:00:00", FIM), (FIM, INICIO), (INICIO, "2026-09-29T12:00:00Z")])
def test_janelas_invalidas_nao_geram_pedido(inicio, fim):
    with pytest.raises(atendimento.RegistroPendente, match="janela_invalida"):
        atendimento.montar_corpo(letra(), inicio, fim)


def test_envio_confirmado_salva_corpo_sem_segredo_e_sem_redirecionamento(rede, tmp_path):
    resultado = atendimento.registrar_letra(letra(), INICIO, FIM, tmp_path)
    assert resultado["status"] == "registrado"
    assert rede[0]["headers"] == {"x-ai-followup-token": SEGREDO}
    assert rede[0]["allow_redirects"] is False
    assert rede[0]["timeout"] == (3, 10)
    texto = (tmp_path / "atendimento_stories_A.json").read_text(encoding="utf-8")
    assert SEGREDO not in texto
    assert json.loads(texto)["corpo"] == rede[0]["json"]


def test_sem_segredo_nao_acessa_rede_mas_guarda_pendente(rede, tmp_path, monkeypatch):
    monkeypatch.setenv("ROTINAS_SEGREDO_ATENDIMENTO", "invalido")
    resultado = atendimento.registrar_letra(letra(), INICIO, FIM, tmp_path)
    assert resultado["motivo"] == "segredo_nao_configurado"
    assert not rede
    assert (tmp_path / "atendimento_stories_A.json").exists()


def test_ensaio_nao_grava_arquivo_nem_chama_edge(rede, tmp_path):
    saida = tmp_path / "saida-ensaio"
    assert atendimento.registrar_letra(letra(), INICIO, FIM, saida, ensaio=True)["status"] == "ignorado"
    assert not rede
    assert not saida.exists()


def test_timeout_guarda_corpo_exato_para_repetir_sem_publicar(rede, tmp_path, monkeypatch):
    def falhou(*args, **kwargs):
        raise TimeoutError("erro incluindo " + SEGREDO)
    monkeypatch.setattr(atendimento.requests, "post", falhou)
    resultado = atendimento.registrar_letra(letra(), INICIO, FIM, tmp_path)
    assert resultado["status"] == "pendente"
    arquivo = tmp_path / "atendimento_stories_A.json"
    original = json.loads(arquivo.read_text(encoding="utf-8"))["corpo"]
    assert SEGREDO not in arquivo.read_text(encoding="utf-8")
    def repetiu(url, **kwargs):
        assert kwargs["json"] == original
        return type("Resposta", (), {"status_code": 200, "json": lambda self: {"ok": True, "registrados": 2, "ja_registrado": True}})()
    monkeypatch.setattr(atendimento.requests, "post", repetiu)
    assert atendimento.repetir_registro(arquivo)["ja_registrado"] is True


@pytest.mark.parametrize("status,dados", [(409, {"motivo": "contagem_divergente"}), (200, {"ok": True, "registrados": 1}), (503, {"error": SEGREDO})])
def test_resposta_incompleta_ou_erro_nao_afirma_registrado(rede, tmp_path, monkeypatch, status, dados):
    monkeypatch.setattr(atendimento.requests, "post", lambda *a, **kw: type("Resposta", (), {"status_code": status, "json": lambda self: dados})())
    resultado = atendimento.registrar_letra(letra(), INICIO, FIM, tmp_path)
    assert resultado["status"] == "pendente"
    assert SEGREDO not in str(resultado)


def test_hook_so_chama_depois_do_registro_local_e_nao_interrompe_proxima_letra(ambiente, monkeypatch):
    a = ambiente
    plano = montar_plano(a.midias, {"A": ["foto"], "B": ["foto"]}, ensaio=False)
    chamadas = []
    def associar(L, inicio, fim, pasta, **kwargs):
        assert L["letra"] in [r["letra"] for r in a.registros]
        assert datetime.fromisoformat(inicio).tzinfo is not None
        assert datetime.fromisoformat(fim) >= datetime.fromisoformat(inicio)
        chamadas.append(L["letra"])
        raise RuntimeError("falha isolada")
    monkeypatch.setattr(atendimento, "registrar_letra", associar)
    resultado = rodar(a, plano, ensaio=False)
    assert resultado["publicadas"] == ["A", "B"]
    assert chamadas == ["A", "B"]
    assert all(r["estado"] == "publicada" for r in resultado["letras"])
    assert all(r["atendimento_stories"]["status"] == "pendente" for r in resultado["letras"])


def test_hook_nao_chama_no_ensaio(ambiente, monkeypatch):
    a = ambiente
    plano = montar_plano(a.midias, {"A": ["foto"]})
    def proibido(*args, **kwargs):
        pytest.fail("ensaio chamou registro externo")
    monkeypatch.setattr(atendimento, "registrar_letra", proibido)
    resultado = rodar(a, plano)
    assert not resultado["publicadas"]
    assert "atendimento_stories" not in resultado["letras"][0]


def test_hook_nao_chama_quando_publicacao_falha(ambiente, monkeypatch):
    a = ambiente
    plano = montar_plano(a.midias, {"A": ["foto"]}, ensaio=False)
    def falhar(self, resultado):
        self.tocou_publicar = True
        raise bluestacks.ErroPasso("publicação incerta")
    def proibido(*args, **kwargs):
        pytest.fail("publicação incerta chamou associação")
    monkeypatch.setattr(bluestacks.Postador, "_publicar", falhar)
    monkeypatch.setattr(atendimento, "registrar_letra", proibido)
    with pytest.raises(bluestacks.ErroPostagem) as erro:
        rodar(a, plano, ensaio=False)
    assert erro.value.resultado_parcial["letras"][0]["incerta"] is True


def test_hook_nao_chama_para_letra_ja_publicada(ambiente, monkeypatch):
    a = ambiente
    plano = montar_plano(a.midias, {"A": ["foto"]}, ensaio=False)
    monkeypatch.setattr(bluestacks.postados, "letras_postadas", lambda data: {"A"})
    def proibido(*args, **kwargs):
        pytest.fail("letra pulada chamou associação")
    monkeypatch.setattr(atendimento, "registrar_letra", proibido)
    resultado = rodar(a, plano, ensaio=False)
    assert not resultado["publicadas"]
    assert resultado["letras"][0]["pulada"]
