import json
import logging
import os
import time
from pathlib import Path

import pytest

import sintetico
from rotinas import config, fila, midia, registro, tarefas


def test_config_pastas(cfg):
    p = config.pastas()
    assert p.fila == p.rotinas / "fila"
    assert p.pasta_do_dia("2026-09-22") == p.stories_fonte / "2026-09-22"
    assert config.carregar("stories")["whatsapp"] == "5582988748649"


def test_expandir_variavel_estilo_windows(monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", "/tmp/local")
    assert str(config.expandir("%LOCALAPPDATA%/x")) == "/tmp/local/x"


def test_env_e_segredo(cfg):
    assert config.segredo("SUPABASE_URL") == "https://exemplo.supabase.co"
    assert cfg.segredo in config.valores_secretos()


def test_ocultar_nunca_mostra_segredo(cfg):
    texto = f"chave {cfg.segredo} e apikey=abcdef123456 e Bearer xyz987654321"
    limpo = registro.ocultar(texto)
    assert cfg.segredo not in limpo
    assert "abcdef123456" not in limpo
    assert "xyz987654321" not in limpo
    assert "monkey business" == registro.ocultar("monkey business")


def test_log_em_arquivo_sem_segredo(cfg, tmp_path):
    arq = tmp_path / "log.txt"
    registro.configurar(arq, console=False)
    registro.obter("teste").info("usando %s", cfg.segredo)
    for h in logging.getLogger("rotinas").handlers:
        h.flush()
    assert cfg.segredo not in arq.read_text(encoding="utf-8")
    assert "usando ***" in arq.read_text(encoding="utf-8")


# ------------------------------------------------------------ fila

def eco(args, ctx):
    ctx.arquivo("saida.txt").write_text("ok", encoding="utf-8")
    if args.get("falhar"):
        raise RuntimeError("falhou de propósito")
    return {"eco": args, "ensaio": ctx.ensaio}


@pytest.fixture
def fila_teste(cfg, monkeypatch):
    monkeypatch.setitem(tarefas.TAREFAS, "teste.eco", "test_nucleo:eco")
    return fila.preparar_pastas()


def test_fila_fluxo_feito(fila_teste):
    caminho = fila.criar_pedido("teste.eco", {"x": 1}, ensaio=True)
    assert caminho.parent.name == "pendente"
    assert fila.Vigia(intervalo_s=0.01).rodar(uma_vez=True) == 0
    res = json.loads((fila_teste / "feito" / caminho.name).read_text(encoding="utf-8"))
    assert res["estado"] == "feito"
    assert res["resultado"] == {"eco": {"x": 1}, "ensaio": True}
    assert "saida.txt" in res["arquivos"] and "log.txt" in res["arquivos"]
    assert not list((fila_teste / "pendente").glob("*.json"))
    assert not list((fila_teste / "andamento").iterdir())


def test_fila_erro_e_sem_segredo(fila_teste, cfg):
    caminho = fila.criar_pedido("teste.eco", {"falhar": True, "k": cfg.segredo})
    fila.Vigia(intervalo_s=0.01).rodar(uma_vez=True)
    texto = (fila_teste / "erro" / caminho.name).read_text(encoding="utf-8")
    res = json.loads(texto)
    assert res["estado"] == "erro" and "falhou de propósito" in res["erro"]
    assert cfg.segredo not in texto


def test_fila_nunca_executa_duas_vezes(fila_teste):
    caminho = fila.criar_pedido("teste.eco", {"n": 1}, id_="pedido-unico")
    conteudo = caminho.read_text(encoding="utf-8")
    fila.Vigia(intervalo_s=0.01).rodar(uma_vez=True)
    # alguém grava o mesmo pedido de novo
    (fila_teste / "pendente" / "pedido-unico.json").write_text(conteudo, encoding="utf-8")
    fila.Vigia(intervalo_s=0.01).rodar(uma_vez=True)
    erros = list((fila_teste / "erro").glob("pedido-unico__duplicado*.json"))
    assert len(erros) == 1
    assert "já foi executado" in json.loads(erros[0].read_text(encoding="utf-8"))["erro"]
    with pytest.raises(ValueError):
        fila.criar_pedido("teste.eco", {}, id_="pedido-unico")


def test_fila_interrompido_nao_reexecuta(fila_teste):
    (fila_teste / "andamento" / "caiu.json").write_text(json.dumps({"id": "caiu", "tipo": "teste.eco", "args": {}}), encoding="utf-8")
    fila.Vigia(intervalo_s=0.01).rodar(uma_vez=True)
    res = json.loads((fila_teste / "erro" / "caiu.json").read_text(encoding="utf-8"))
    assert "Interrompido" in res["erro"]
    assert not (fila_teste / "feito" / "caiu.json").exists()


def test_fila_json_invalido_e_id_divergente(fila_teste):
    ruim = fila_teste / "pendente" / "ruim.json"
    ruim.write_text("{nao é json", encoding="utf-8")
    os.utime(ruim, (time.time() - 60, time.time() - 60))
    (fila_teste / "pendente" / "nome.json").write_text(json.dumps({"id": "outro", "tipo": "teste.eco"}), encoding="utf-8")
    fila.Vigia(intervalo_s=0.01).rodar(uma_vez=True)
    assert "JSON inválido" in json.loads((fila_teste / "erro" / "ruim.json").read_text(encoding="utf-8"))["erro"]
    assert "igual ao nome" in json.loads((fila_teste / "erro" / "nome.json").read_text(encoding="utf-8"))["erro"]


def test_fila_tipo_desconhecido(fila_teste):
    with pytest.raises(tarefas.TipoDesconhecido):
        fila.criar_pedido("nao.existe", {})
    (fila_teste / "pendente" / "x.json").write_text(json.dumps({"id": "x", "tipo": "nao.existe"}), encoding="utf-8")
    fila.Vigia(intervalo_s=0.01).rodar(uma_vez=True)
    assert "desconhecido" in json.loads((fila_teste / "erro" / "x.json").read_text(encoding="utf-8"))["erro"]


def test_trava_um_vigia_por_vez(fila_teste):
    t1 = fila.Trava(fila_teste / "vigia.lock")
    t2 = fila.Trava(fila_teste / "vigia.lock")
    assert t1.adquirir()
    assert not t2.adquirir()
    t1.liberar()
    assert t2.adquirir()
    t2.liberar()


def test_todas_as_tarefas_e_comandos_apontam_para_algo():
    from rotinas import cli

    for alvo in list(tarefas.TAREFAS.values()) + [a for a, _ in cli.COMANDOS.values()]:
        modulo, funcao = alvo.split(":")
        assert modulo.startswith("rotinas.") and funcao


# ------------------------------------------------------------ mídia

@pytest.mark.ffmpeg
def test_sondar_e_audio(cfg, tmp_path):
    com = sintetico.video(tmp_path / "com.mp4", audio="tom")
    sem = sintetico.video(tmp_path / "sem.mp4", audio=None)
    mudo = sintetico.video(tmp_path / "mudo.mp4", audio="silencio")
    info = midia.sondar(com)
    assert (info.largura, info.altura, info.tipo) == (360, 640, "video")
    assert abs(info.fps - 30) < 0.1 and info.tem_audio and info.vertical
    assert midia.situacao_audio(com) == "com_audio"
    assert midia.situacao_audio(sem) == "sem_audio"
    assert midia.situacao_audio(mudo) == "silencioso"


@pytest.mark.ffmpeg
def test_converter_mov_para_mp4_sem_sobrescrever(cfg, tmp_path):
    mov = sintetico.video(tmp_path / "IMG_0001.mov", audio="tom")
    antes = midia.hash_arquivo(mov)
    destino = tmp_path / "A - 1.mp4"
    r = midia.converter_para_mp4(mov, destino)
    assert r["modo"] == "remux"
    assert midia.sondar(destino).codec_video == "h264"
    assert midia.hash_arquivo(mov) == antes
    with pytest.raises(midia.ErroMidia):
        midia.converter_para_mp4(mov, destino)


@pytest.mark.ffmpeg
def test_converter_hevc_recodifica(cfg, tmp_path):
    try:
        mov = sintetico.video(tmp_path / "hevc.mov", audio="tom", codec="libx265")
    except Exception:
        pytest.skip("ffmpeg sem libx265")
    r = midia.converter_para_mp4(mov, tmp_path / "saida.mp4")
    assert r["modo"].startswith("recodificado")
    info = midia.sondar(tmp_path / "saida.mp4")
    assert info.codec_video == "h264" and info.codec_audio == "aac"


def test_data_captura_exif(cfg, tmp_path):
    from datetime import datetime

    f = sintetico.foto(tmp_path / "f.jpg", tirada_em=datetime(2026, 9, 22, 14, 30, 5))
    assert midia.data_captura(f) == datetime(2026, 9, 22, 14, 30, 5)


def test_folha_de_contato(tmp_path):
    from PIL import Image

    from rotinas import folha

    itens = [(Image.new("RGB", (300, 500), (i * 40, 100, 100)), f"A-{i + 1}") for i in range(5)]
    saida = folha.montar(itens, tmp_path / "A.jpg", titulo="Letra A")
    img = Image.open(saida)
    assert img.width > 300 and img.height > 480


# ------------------------------------------------------------ fila: robustez (Windows)

def devolve_path(args, ctx):
    return {"arquivo": ctx.pasta_saida / "x.png", "texto": 'Authorization: Bearer abcdef123456" e "Conjunto Secret: Elegance"'}


def test_fila_resultado_com_path_e_texto_de_token(fila_teste, monkeypatch):
    monkeypatch.setitem(tarefas.TAREFAS, "teste.path", "test_nucleo:devolve_path")
    caminho = fila.criar_pedido("teste.path", {})
    fila.Vigia(intervalo_s=0.01).rodar(uma_vez=True)
    res = json.loads((fila_teste / "feito" / caminho.name).read_text(encoding="utf-8"))
    assert res["estado"] == "feito"
    assert res["resultado"]["arquivo"].endswith("x.png")
    assert "abcdef123456" not in res["resultado"]["texto"]
    assert "Secret: Elegance" in res["resultado"]["texto"]


@pytest.mark.parametrize("nome", ["nul", "CON", "com1", "aux.json-x", "termina.", "-comeca", "a" * 130])
def test_id_invalido(nome):
    assert not fila.ID_VALIDO.match(nome)


@pytest.mark.parametrize("nome", ["a", "20260925-183000-stories-montar", "pedido_1.2", "console", "nulo"])
def test_id_valido(nome):
    assert fila.ID_VALIDO.match(nome)


def test_fila_nome_de_arquivo_reservado_vai_para_erro(fila_teste):
    (fila_teste / "pendente" / "nul.json").write_text(json.dumps({"id": "nul", "tipo": "teste.eco"}), encoding="utf-8")
    fila.Vigia(intervalo_s=0.01).rodar(uma_vez=True)
    erros = list((fila_teste / "erro").glob("invalido-*.json"))
    assert len(erros) == 1 and "inválido" in json.loads(erros[0].read_text(encoding="utf-8"))["erro"]


def test_recuperar_json_que_nao_e_objeto_e_resultado_ja_gravado(fila_teste):
    (fila_teste / "andamento" / "lista.json").write_text("[1, 2]", encoding="utf-8")
    (fila_teste / "feito" / "pronto.json").write_text("{}", encoding="utf-8")
    (fila_teste / "andamento" / "pronto.json").write_text(json.dumps({"id": "pronto"}), encoding="utf-8")
    ids = fila.Vigia(intervalo_s=0.01).recuperar_interrompidos()
    assert ids == ["lista"]
    assert not (fila_teste / "erro" / "pronto.json").exists()
    assert not (fila_teste / "andamento" / "pronto.json").exists()


def test_pasta_presa_nao_vira_interrompido(fila_teste, monkeypatch):
    real = os.replace

    def replace_que_falha_em_pasta(a, b):
        if Path(a).is_dir():
            raise PermissionError("em uso")
        return real(a, b)

    monkeypatch.setattr(fila.os, "replace", replace_que_falha_em_pasta)
    monkeypatch.setattr(fila.time, "sleep", lambda s: None)
    caminho = fila.criar_pedido("teste.eco", {"x": 2})
    fila.Vigia(intervalo_s=0.01).rodar(uma_vez=True)
    res = json.loads((fila_teste / "feito" / caminho.name).read_text(encoding="utf-8"))
    assert res["estado"] == "feito"
    assert Path(res["pasta"]).parent.name == "andamento"
    assert not list((fila_teste / "erro").glob("*.json"))


def test_sinal_de_vida_nao_derruba(fila_teste, monkeypatch):
    vigia = fila.Vigia(intervalo_s=0.01)

    def falha(*a, **k):
        raise PermissionError("em uso")

    monkeypatch.setattr(fila, "_gravar_json", falha)
    vigia.sinal_de_vida()  # não levanta
