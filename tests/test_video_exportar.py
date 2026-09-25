"""B4: instruções de exportação e vigia do arquivo exportado (conferencia.conferir vem por dublê)."""

import os
import sys
import types
from pathlib import Path

import pytest

import rotinas.video
from rotinas.contexto import Contexto
from rotinas.video import exportar


class Relogio:
    """Relógio falso: ``dormir`` avança o tempo e roda o que o teste agendou."""

    def __init__(self, monkeypatch, inicio=1_000_000.0):
        self.t = inicio
        self.agendado: dict[int, list] = {}
        self.voltas = 0
        monkeypatch.setattr(exportar, "agora", lambda: self.t)
        monkeypatch.setattr(exportar, "dormir", self.dormir)

    def em(self, volta, funcao):
        self.agendado.setdefault(volta, []).append(funcao)

    def dormir(self, s):
        self.t += s
        self.voltas += 1
        for f in self.agendado.pop(self.voltas, []):
            f()


def _escrever(arq: Path, dados: bytes, t: float):
    arq.parent.mkdir(parents=True, exist_ok=True)
    arq.write_bytes(dados)
    os.utime(arq, (t, t))


@pytest.fixture
def conferencia_falsa(monkeypatch):
    chamadas = []
    modulo = types.ModuleType("rotinas.video.conferencia")

    def conferir(arquivo, destino="reels", duracao_esperada_s=None):
        chamadas.append((Path(arquivo), destino, duracao_esperada_s))
        return {"arquivo": str(arquivo), "destino": destino, "aprovado": True,
                "itens": [{"item": "resolução", "esperado": "1080×1920", "obtido": "1080×1920", "ok": True}]}

    modulo.conferir = conferir
    modulo.texto = lambda r: f"Aprovado: {Path(r['arquivo']).name}"
    monkeypatch.setitem(sys.modules, "rotinas.video.conferencia", modulo)
    monkeypatch.setattr(rotinas.video, "conferencia", modulo, raising=False)
    return chamadas


def test_instrucoes_reels(cfg):
    texto = exportar.instrucoes("reels", "Vestido verde", duracao_s=20)
    for trecho in ("Nome: Vestido verde_reels", "Resolução: 1080P (1080×1920)", "Personalizado → 16.000 kbps",
                   "Codec: H.264", "Formato: mp4", "Taxa de quadros: 30", "Rec.709 SDR",
                   "Sincronize os vídeos exportados com o espaço", "só mudar se o dono pedir",
                   str(cfg.p.videos / "exportado"), "Ctrl+E", "Alt+Espaço", "−23 LUFS", "−14 LUFS"):
        assert trecho in texto
    assert "PASSA DO LIMITE" not in texto


def test_instrucoes_stories_avisa_limite_de_tamanho(cfg):
    ok = exportar.instrucoes("stories", "Saia", duracao_s=30)
    assert "limite do stories: 100 MB" in ok and "PASSA DO LIMITE" not in ok
    grande = exportar.instrucoes("stories", "Saia", duracao_s=80)
    assert "PASSA DO LIMITE" in grande
    assert exportar.estimar_mb(11000, 80) == pytest.approx((11000 + 192) * 80 / 8 / 1000)


def test_destino_desconhecido(cfg):
    with pytest.raises(exportar.ErroExportacao):
        exportar.instrucoes("youtube", "x")


def test_espera_arquivo_estavel(cfg, tmp_path, monkeypatch):
    relogio = Relogio(monkeypatch)
    pasta = tmp_path / "exportado"
    arq = pasta / "Vestido verde_reels.mp4"
    desde = relogio.t
    _escrever(pasta / "antigo.mp4", b"x" * 10, desde - 3600)  # anterior ao pedido: ignorado
    relogio.em(2, lambda: _escrever(arq, b"x" * 100, relogio.t))
    relogio.em(4, lambda: _escrever(arq, b"x" * 500, relogio.t))  # ainda crescendo
    achado = exportar.esperar_arquivo("Vestido verde_reels", desde, [pasta], timeout_s=60, estavel_s=5, intervalo_s=1)
    assert achado == arq
    assert relogio.voltas >= 4 + 5  # esperou ficar estável depois da última mudança


def test_arquivo_que_some_durante_a_espera_nao_derruba_o_vigia(cfg, tmp_path, monkeypatch):
    # O CapCut grava um temporário e renomeia: o arquivo listado pode sumir antes do stat da ordenação.
    relogio = Relogio(monkeypatch)
    pasta = tmp_path / "exportado"
    temporario, final = pasta / "Saia_reels_tmp.mp4", pasta / "Saia_reels.mp4"
    relogio.em(1, lambda: _escrever(temporario, b"x" * 100, relogio.t))
    relogio.em(2, lambda: _escrever(final, b"x" * 100, relogio.t))
    original = exportar._novos

    def novos_com_sumico(pastas, desde, extensao):
        achados = original(pastas, desde, extensao)
        if temporario.exists() and relogio.voltas >= 3:
            temporario.unlink()  # some entre a listagem e a ordenação
        return achados

    monkeypatch.setattr(exportar, "_novos", novos_com_sumico)
    achado = exportar.esperar_arquivo("Saia_reels", relogio.t, [pasta], timeout_s=60, estavel_s=2, intervalo_s=1)
    assert achado == final


def test_espera_esgota_o_tempo(cfg, tmp_path, monkeypatch):
    relogio = Relogio(monkeypatch)
    with pytest.raises(exportar.ErroExportacao, match="Nenhum .mp4"):
        exportar.esperar_arquivo("x", relogio.t, [tmp_path / "vazia"], timeout_s=10, estavel_s=2, intervalo_s=1)


def test_nome_diferente_conforme_config(cfg, tmp_path, monkeypatch):
    relogio = Relogio(monkeypatch)
    pasta = tmp_path / "exportado"
    _escrever(pasta / "0925.mp4", b"x" * 100, relogio.t)
    achado = exportar.esperar_arquivo("Vestido_reels", relogio.t, [pasta], timeout_s=30, estavel_s=2, intervalo_s=1)
    assert achado.name == "0925.mp4"
    cfg.alterar("capcut", exportacao={**exportar._cfg(), "aceitar_outro_nome": False})
    with pytest.raises(exportar.ErroExportacao):
        exportar.esperar_arquivo("Vestido_reels", relogio.t - 5, [pasta], timeout_s=10, estavel_s=2, intervalo_s=1)


def test_vigiar_chama_a_conferencia(cfg, tmp_path, monkeypatch, conferencia_falsa):
    relogio = Relogio(monkeypatch)
    pasta = tmp_path / "exportado"
    relogio.em(1, lambda: _escrever(pasta / "Saia_stories.mp4", b"x" * 100, relogio.t))
    r = exportar.vigiar_e_conferir("Saia_stories", "stories", relogio.t, 12.5, pastas=[pasta], timeout_s=60,
                                   estavel_s=2, intervalo_s=1)
    assert conferencia_falsa == [(pasta / "Saia_stories.mp4", "stories", 12.5)]
    assert r["conferencia"]["aprovado"] and r["texto"] == "Aprovado: Saia_stories.mp4"


def test_tarefa_sem_esperar_grava_instrucoes(cfg, tmp_path):
    trabalho = cfg.p.videos / "trabalho" / "vestido-verde"
    trabalho.mkdir(parents=True)
    (trabalho / "plano.json").write_text('{"duracao_s": 18.5}', encoding="utf-8")
    ctx = Contexto(tmp_path / "exec")
    r = exportar.tarefa({"destino": "reels", "projeto": "vestido-verde", "rascunho": "Vestido verde",
                         "esperar": False}, ctx)
    assert not r["esperou"] and r["duracao_esperada_s"] == 18.5
    assert (ctx.pasta_saida / "instrucoes_exportacao.txt").exists()
    assert "Nome: Vestido verde_reels" in (trabalho / "instrucoes_exportacao.txt").read_text(encoding="utf-8")
    assert (cfg.p.videos / "exportado").is_dir()
    ensaio = exportar.tarefa({"destino": "reels", "rascunho": "X"}, Contexto(tmp_path / "exec2", ensaio=True))
    assert not ensaio["esperou"]


def test_tarefa_espera_e_confere(cfg, tmp_path, monkeypatch, conferencia_falsa):
    relogio = Relogio(monkeypatch)
    cfg.alterar("capcut", exportacao={**exportar._cfg(), "pastas_extra": [], "estavel_s": 2})
    destino = cfg.p.videos / "exportado" / "Vestido verde_reels.mp4"
    relogio.em(3, lambda: _escrever(destino, b"x" * 1000, relogio.t))
    ctx = Contexto(tmp_path / "exec")
    r = exportar.tarefa({"destino": "reels", "rascunho": "Vestido verde", "duracao_esperada_s": 20}, ctx)
    assert r["esperou"] and r["aprovado"] and r["arquivo"] == str(destino)
    assert (ctx.pasta_saida / "conferencia.txt").read_text(encoding="utf-8") == "Aprovado: Vestido verde_reels.mp4"
    assert conferencia_falsa[0][1:] == ("reels", 20.0)


def test_tarefa_sem_nome(cfg, tmp_path):
    with pytest.raises(exportar.ErroExportacao):
        exportar.tarefa({"destino": "reels"}, Contexto(tmp_path / "exec"))


def test_atalhos_ainda_nao(cfg):
    with pytest.raises(NotImplementedError, match="clique do usuário"):
        exportar.exportar_por_atalhos("x", "reels")


def test_cli_sem_esperar(cfg, capsys):
    assert exportar.cli(["--destino", "stories", "--rascunho", "Saia", "--sem-esperar"]) == 0
    assert "Instruções gravadas" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        exportar.cli(["--destino", "reels"])
