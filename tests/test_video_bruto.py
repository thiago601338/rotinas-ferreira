import json
import os
import sys
import types
from pathlib import Path

import pytest

import sintetico
from rotinas import midia
from rotinas.contexto import Contexto
from rotinas.video import bruto, transcricao

QUADRO = 1 / 30
PROJETO = "vestido-verde"

PALAVRAS = [
    {"ini_s": 0.05, "fim_s": 0.3, "texto": "Esse"},
    {"ini_s": 0.3, "fim_s": 0.45, "texto": "vestido"},
    {"ini_s": 1.05, "fim_s": 1.3, "texto": "custa"},
    {"ini_s": 1.3, "fim_s": 1.45, "texto": "R$"},
    {"ini_s": 2.05, "fim_s": 2.45, "texto": "229,99."},
]


def pasta_bruto(cfg, projeto=PROJETO):
    pasta = cfg.p.videos / "bruto" / projeto
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def hashes(pasta):
    return {p.name: midia.hash_arquivo(p) for p in sorted(pasta.iterdir())}


@pytest.fixture
def batidas_falsas(monkeypatch):
    """O módulo de batidas é de outro agente: aqui entra um falso, determinístico."""
    mod = types.ModuleType("rotinas.video.batidas")
    mod.chamadas = []

    def detectar_batidas(caminho):
        mod.chamadas.append(Path(caminho))
        return {"bpm": 120.0, "batidas_s": [0.0, 0.5, 1.0, 1.5], "compassos_s": [0.0],
                "primeira_batida_s": 0.0, "confianca": 0.9}

    mod.detectar_batidas = detectar_batidas
    monkeypatch.setitem(sys.modules, "rotinas.video.batidas", mod)
    return mod


@pytest.fixture
def fala_falsa(monkeypatch):
    chamadas = []

    def transcrever(caminho, modelo=None):
        chamadas.append(Path(caminho).name)
        return [dict(p) for p in PALAVRAS]

    monkeypatch.setattr(transcricao, "transcrever", transcrever)
    return chamadas


# ------------------------------------------------------------ pastas e regras puras

def test_pastas_projeto(cfg):
    p = bruto.pastas_projeto(PROJETO)
    assert p["bruto"] == cfg.p.videos / "bruto" / PROJETO
    assert p["trabalho"] == cfg.p.videos / "trabalho" / PROJETO
    assert p["folhas"] == p["trabalho"] / "folhas"
    assert p["exportado"] == cfg.p.videos / "exportado"
    for ruim in ("", " ", "..", "a/b", "a\\b", "x:y"):
        with pytest.raises(bruto.ErroBruto):
            bruto.pastas_projeto(ruim)


def test_trechos_juntam_os_curtos():
    assert bruto._trechos([1.0, 2.0], 3.0, 0.6) == [(0.0, 1.0), (1.0, 2.0), (2.0, 3.0)]
    assert bruto._trechos([0.3, 2.0], 3.0, 0.6) == [(0.0, 2.0), (2.0, 3.0)]  # começo curto
    assert bruto._trechos([1.0, 1.2, 2.0], 3.0, 0.6) == [(0.0, 1.0), (1.0, 2.0), (2.0, 3.0)]  # flash no meio
    assert bruto._trechos([1.0, 2.8], 3.0, 0.6) == [(0.0, 1.0), (1.0, 3.0)]  # fim curto
    assert bruto._trechos([], 0.4, 0.6) == [(0.0, 0.4)]
    assert bruto._trechos([], 0.0, 0.6) == []


def test_tempo_curto_e_quadros_da_tomada():
    assert bruto.tempo_curto(4.2) == "0:04,2"
    assert bruto.tempo_curto(64.25) == "1:04,2" or bruto.tempo_curto(64.25) == "1:04,3"
    assert bruto.tempo_curto(3725.0) == "1:02:05,0"
    assert bruto._tempos_quadros(4.2, 6.0, 3, 0.2) == pytest.approx([4.4, 5.1, 5.8])
    curta = bruto._tempos_quadros(1.0, 1.4, 3, 0.2)
    assert curta[0] > 1.0 and curta[-1] < 1.4


def test_avisos_hdr_e_fps_variavel(cfg):
    info = midia.InfoMidia(caminho="IMG_0001.mp4", tipo="video", largura=1080, altura=1920, fps=29.4,
                           fps_variavel=True, hdr=True, transferencia="arib-std-b67", tem_audio=True)
    av = bruto.avisos_midia(info, "com_audio")
    assert len(av) == 2
    assert any("desligar HDR na câmera" in x and "SDR" in x for x in av)
    assert any("30 fps constante" in x and "HandBrake" in x for x in av)
    ok = midia.InfoMidia(caminho="IMG_0002.mp4", tipo="video", largura=2160, altura=3840, fps=30.0, tem_audio=True)
    assert bruto.avisos_midia(ok, "com_audio") == []


# ------------------------------------------------------------ ffmpeg

@pytest.mark.ffmpeg
def test_detectar_tomadas_nos_cortes_secos(cfg, tmp_path):
    v = sintetico.video(tmp_path / "cenas.mp4", duracao=4.0, cenas=["black", "white", "navy", "yellow"], audio=None)
    tomadas = bruto.detectar_tomadas(v)
    assert len(tomadas) == 4
    for t, (a, b) in zip(tomadas, [(0, 1), (1, 2), (2, 3), (3, 4)]):
        assert abs(t["ini_s"] - a) <= QUADRO + 1e-3 and abs(t["fim_s"] - b) <= QUADRO + 1e-3
    assert bruto.detectar_tomadas(v, min_s=5) == [{"ini_s": 0.0, "fim_s": 4.0}]
    assert len(bruto.detectar_tomadas(v, limiar=1.1)) == 1  # limiar impossível: arquivo inteiro


@pytest.mark.ffmpeg
def test_detectar_silencios(cfg, tmp_path):
    fala = sintetico.video(tmp_path / "fala.mp4", duracao=3.0, audio="fala")
    s = bruto.detectar_silencios(fala)
    assert len(s) == 3
    for item, (a, b) in zip(s, [(0.5, 1.0), (1.5, 2.0), (2.5, 3.0)]):
        assert abs(item["ini_s"] - a) < 0.05 and abs(item["fim_s"] - b) < 0.05
    assert bruto.detectar_silencios(sintetico.video(tmp_path / "tom.mp4", duracao=2.0, audio="tom")) == []
    assert bruto.detectar_silencios(sintetico.video(tmp_path / "sem.mp4", duracao=2.0, audio=None)) == [
        {"ini_s": 0.0, "fim_s": 2.0}]


@pytest.mark.ffmpeg
def test_inventario_com_avisos(cfg):
    pasta = pasta_bruto(cfg)
    sintetico.video(pasta / "IMG_10.mp4", duracao=1.0, fps=25, largura=1080, altura=1920, audio="tom")
    sintetico.video(pasta / "IMG_9.MOV", duracao=1.0, largura=640, altura=360, audio=None)
    sintetico.video(pasta / "IMG_11.mp4", duracao=1.0, audio="silencio")
    sintetico.foto(pasta / "foto.jpg")
    (pasta / "desktop.ini").write_text("x", encoding="utf-8")
    inv = bruto.inventario(PROJETO)
    assert [i["arquivo"] for i in inv] == ["IMG_9.MOV", "IMG_10.mp4", "IMG_11.mp4"]  # ordem natural
    horizontal, a25, mudo = inv
    assert abs(a25["fps"] - 25) < 0.1 and a25["audio"] == "com_audio"
    assert any("60 Hz" in x for x in a25["avisos"])
    assert not any("horizontal" in x or "resolução" in x for x in a25["avisos"])
    assert any("horizontal" in x for x in horizontal["avisos"])
    assert any("lado menor de 360 px, abaixo de 1080" in x for x in horizontal["avisos"])
    assert any("sem faixa de áudio" in x for x in horizontal["avisos"])
    assert any(".mov do iPhone abre" in x for x in horizontal["avisos"])
    assert horizontal["audio"] == "sem_audio" and mudo["audio"] == "silencioso"
    assert any("áudio em silêncio" in x for x in mudo["avisos"])


@pytest.mark.ffmpeg
def test_preparar_grava_tudo_sem_tocar_no_bruto(cfg, fala_falsa, batidas_falsas):
    pasta = pasta_bruto(cfg)
    sintetico.video(pasta / "IMG_0001.MOV", duracao=3.0, cenas=["black", "white", "navy"], audio="fala")
    sintetico.video(pasta / "IMG_0002.mp4", duracao=2.0, cenas=["yellow", "black"], audio=None)
    guia = sintetico.musica_cliques(cfg.p.videos / "musicas" / "guia.wav", bpm=120, duracao=3.0)
    antes = hashes(pasta)

    r = bruto.preparar(PROJETO, musica="guia.wav")

    assert hashes(pasta) == antes  # nada alterado nem criado no bruto
    trabalho = cfg.p.videos / "trabalho" / PROJETO
    assert json.loads((trabalho / "bruto.json").read_text(encoding="utf-8")) == json.loads(json.dumps(r))
    assert r["projeto"] == PROJETO and r["gerado_em"]
    assert [t["id"] for t in r["tomadas"]] == ["T01", "T02", "T03", "T04", "T05"]
    assert [t["arquivo"] for t in r["tomadas"]] == ["IMG_0001.MOV"] * 3 + ["IMG_0002.mp4"] * 2
    assert abs(r["tomadas"][1]["ini_s"] - 1.0) <= QUADRO + 1e-3 and abs(r["tomadas"][3]["fim_s"] - 1.0) <= QUADRO + 1e-3
    assert r["tomadas"][0]["dur_s"] == pytest.approx(r["tomadas"][0]["fim_s"] - r["tomadas"][0]["ini_s"])
    assert [t["id"] for t in r["arquivos"][1]["tomadas"]] == ["T04", "T05"]
    assert set(r["arquivos"][0]) >= {"arquivo", "caminho", "info", "avisos", "tomadas", "silencios", "fala"}
    assert r["arquivos"][0]["info"]["largura"] == 360

    assert r["folhas"] == ["folhas/tomadas-01.jpg"]
    assert all(t["folha"] == "folhas/tomadas-01.jpg" for t in r["tomadas"])
    from PIL import Image

    with Image.open(trabalho / "folhas" / "tomadas-01.jpg") as img:
        assert img.format == "JPEG" and img.width > 1000

    assert fala_falsa == ["IMG_0001.MOV"]  # só o arquivo com fala
    assert r["arquivos"][0]["fala"] is True and r["arquivos"][1]["fala"] is False
    # volume medido para o plano levar a voz a −14 LUFS (o CapCut exporta a mistura como está)
    vol = r["arquivos"][0]["volume"]
    assert -60 < vol["lufs"] < -5 and -60 < vol["pico_real_dbtp"] <= 0 and r["arquivos"][1]["volume"] is None
    assert len(r["arquivos"][0]["silencios"]) >= 2
    assert r["transcricao"]["arquivo_srt"] == "legendas.srt"
    assert all(p["arquivo"] == "IMG_0001.MOV" for p in r["transcricao"]["palavras"])
    lido = transcricao.ler_srt((trabalho / "legendas.srt").read_text(encoding="utf-8"))
    assert lido and lido[0]["ini_s"] == 0.05
    assert all(b["texto"].split()[-1] != "R$" for b in lido)
    tj = json.loads((trabalho / "transcricao.json").read_text(encoding="utf-8"))
    assert tj["arquivos"][0]["srt"] == "legendas.srt" and len(tj["arquivos"][0]["palavras"]) == len(PALAVRAS)

    assert batidas_falsas.chamadas == [guia]
    assert r["musica"]["bpm"] == 120.0 and r["musica"]["arquivo"] == str(guia)
    assert json.loads((trabalho / "batidas.json").read_text(encoding="utf-8"))["batidas_s"] == [0.0, 0.5, 1.0, 1.5]


@pytest.mark.ffmpeg
def test_preparar_varios_com_fala_paginas_e_musica_no_bruto(cfg, fala_falsa, batidas_falsas):
    cfg.alterar("video", folha_tomadas_por_folha=2)
    pasta = pasta_bruto(cfg)
    sintetico.video(pasta / "A.mp4", duracao=2.0, cenas=["black", "white"], audio="fala")
    sintetico.video(pasta / "B.mp4", duracao=2.0, cenas=["navy", "yellow"], audio="tom")
    sintetico.musica_cliques(pasta / "guia.wav", bpm=100, duracao=2.0)
    trabalho = cfg.p.videos / "trabalho" / PROJETO
    (trabalho / "folhas").mkdir(parents=True)
    (trabalho / "folhas" / "tomadas-09.jpg").write_bytes(b"velha")

    r = bruto.preparar(PROJETO, musica="guia.wav")

    assert [a["arquivo"] for a in r["arquivos"]] == ["A.mp4", "B.mp4"]  # a música não vira tomada
    assert r["folhas"] == ["folhas/tomadas-01.jpg", "folhas/tomadas-02.jpg"]
    assert not (trabalho / "folhas" / "tomadas-09.jpg").exists()
    assert r["transcricao"]["arquivo_srt"] is None
    assert r["transcricao"]["arquivos_srt"] == {"A.mp4": "legendas-A.srt", "B.mp4": "legendas-B.srt"}
    assert (trabalho / "legendas-A.srt").exists() and (trabalho / "legendas-B.srt").exists()
    assert r["musica"]["arquivo"] == str(pasta / "guia.wav")


@pytest.mark.ffmpeg
def test_preparar_sem_whisper_e_sem_batidas_segue_com_aviso(cfg, monkeypatch):
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    monkeypatch.setattr(transcricao, "_modelos", {})
    quebrado = types.ModuleType("rotinas.video.batidas")

    def detectar_batidas(caminho):
        raise RuntimeError("faixa estranha")

    quebrado.detectar_batidas = detectar_batidas
    monkeypatch.setitem(sys.modules, "rotinas.video.batidas", quebrado)
    pasta = pasta_bruto(cfg)
    sintetico.video(pasta / "IMG_0001.mp4", duracao=1.5, audio="fala")
    musica = sintetico.musica_cliques(cfg.raiz / "outra pasta" / "faixa guia.wav", duracao=2.0)

    r = bruto.preparar(PROJETO, musica=str(musica))

    assert r["transcricao"] is None and r["musica"] is None
    assert any("faster-whisper" in a for a in r["avisos"])
    assert any("batidas" in a and "faixa estranha" in a for a in r["avisos"])
    assert r["arquivos"][0]["fala"] is True  # sem Whisper fica o palpite pelo áudio
    assert len(r["tomadas"]) == 1


@pytest.mark.ffmpeg
def test_modelo_indisponivel_para_na_primeira_tentativa(cfg, monkeypatch):
    chamadas = []

    def transcrever(caminho, modelo=None):
        chamadas.append(caminho)
        raise transcricao.ModeloIndisponivel("Não consegui carregar o modelo Whisper 'small' (sem internet).")

    monkeypatch.setattr(transcricao, "transcrever", transcrever)
    pasta = pasta_bruto(cfg)
    sintetico.video(pasta / "A.mp4", duracao=1.0, audio="fala")
    sintetico.video(pasta / "B.mp4", duracao=1.0, audio="fala")
    r = bruto.preparar(PROJETO)
    assert len(chamadas) == 1 and r["transcricao"] is None
    assert sum("modelo Whisper" in a for a in r["avisos"]) == 1


@pytest.mark.ffmpeg
def test_quadro_que_falha_vira_marcador(cfg, tmp_path):
    v = sintetico.video(tmp_path / "curto.mp4", duracao=1.0, audio=None)
    assert bruto._quadro(v, 0.5, tmp_path, 90, 160).size == (90, 160)
    img = bruto._quadro(v, 99.0, tmp_path, 90, 160)  # depois do fim: marcador cinza "sem quadro"
    assert img.size == (90, 160) and img.getpixel((80, 150)) == (70, 70, 70)


@pytest.mark.ffmpeg
def test_preparar_sem_transcricao_nao_chama_whisper(cfg, fala_falsa):
    pasta = pasta_bruto(cfg)
    sintetico.video(pasta / "IMG_0001.mp4", duracao=1.0, audio="fala")
    r = bruto.preparar(PROJETO, transcrever=False)
    assert fala_falsa == [] and r["transcricao"] is None and r["musica"] is None


@pytest.mark.ffmpeg
def test_normalizar_vfr_gera_copia_em_trabalho(cfg, monkeypatch):
    pasta = pasta_bruto(cfg)
    original = sintetico.video(pasta / "IMG_0001.MOV", duracao=1.0, audio="tom")
    antes = hashes(pasta)
    sondar = midia.sondar

    def sondar_vfr(caminho):
        info = sondar(caminho)
        if Path(caminho) == original:
            info.fps_variavel = True
        return info

    monkeypatch.setattr(midia, "sondar", sondar_vfr)
    r = bruto.preparar(PROJETO, transcrever=False, normalizar_vfr=True)
    copia = cfg.p.videos / "trabalho" / PROJETO / "cfr" / "IMG_0001-mov-cfr30.mp4"
    assert copia.exists() and r["arquivos"][0]["caminho_edicao"] == str(copia)
    assert r["arquivos"][0]["caminho"] == str(original)
    assert any("HandBrake" in a for a in r["arquivos"][0]["avisos"])
    assert any("cópia em fps constante gerada" in a for a in r["arquivos"][0]["avisos"])
    info = sondar(copia)
    assert info.codec_video == "h264" and abs(info.fps - 30) < 0.1
    assert hashes(pasta) == antes


@pytest.mark.ffmpeg
def test_copia_cfr_nao_reaproveita_copia_de_outro_arquivo(cfg, tmp_path):
    # Achado #2: IMG_0001.MOV e IMG_0001.mp4 no mesmo bruto dividiam IMG_0001-cfr30.mp4, e um original trocado
    # por outro com o mesmo nome reaproveitava a cópia velha.
    pasta = pasta_bruto(cfg)
    trabalho = tmp_path / "trabalho"
    mov = sintetico.video(pasta / "IMG_0001.MOV", duracao=1.0, audio="tom")
    mp4 = sintetico.video(pasta / "IMG_0001.mp4", duracao=2.0, audio="tom")
    antes = hashes(pasta)
    copia_mov = bruto._copia_cfr(mov, trabalho)
    copia_mp4 = bruto._copia_cfr(mp4, trabalho)
    assert copia_mov != copia_mp4
    assert abs(midia.sondar(copia_mov).duracao_s - 1.0) < 0.15
    assert abs(midia.sondar(copia_mp4).duracao_s - 2.0) < 0.15
    assert bruto._copia_cfr(mov, trabalho) == copia_mov  # mesmo original: reaproveita
    assert hashes(pasta) == antes

    # o usuário troca o .MOV por outro vídeo com o mesmo nome (e data de modificação mais antiga)
    mov.unlink()
    sintetico.video(mov, duracao=3.0, audio="tom")
    os.utime(mov, (1_000_000_000, 1_000_000_000))
    assert bruto._copia_cfr(mov, trabalho) == copia_mov
    assert abs(midia.sondar(copia_mov).duracao_s - 3.0) < 0.15
    assert not list((trabalho / "cfr").glob("*.parcial.*"))


def test_preparar_erros_claros(cfg):
    with pytest.raises(bruto.ErroBruto, match="Não achei a pasta do bruto"):
        bruto.preparar("nao-existe")
    pasta_bruto(cfg)
    with pytest.raises(bruto.ErroBruto, match="Nenhum vídeo"):
        bruto.preparar(PROJETO)
    with pytest.raises(bruto.ErroBruto, match="Música não encontrada"):
        bruto.preparar(PROJETO, musica="nao-tem.mp3")


# ------------------------------------------------------------ fila e terminal

@pytest.mark.ffmpeg
def test_tarefa_e_cli(cfg, tmp_path, capsys):
    pasta = pasta_bruto(cfg)
    sintetico.video(pasta / "IMG_0001.mp4", duracao=2.0, cenas=["black", "white"], fps=25, audio=None)
    res = bruto.tarefa({"projeto": PROJETO, "transcrever": False}, Contexto(tmp_path / "ctx"))
    assert res["tomadas"] == 2 and res["projeto"] == PROJETO
    assert Path(res["bruto_json"]).exists() and all(Path(f).exists() for f in res["folhas"])
    assert any("60 Hz" in a for a in res["arquivos"][0]["avisos"])
    json.dumps(res)
    with pytest.raises(ValueError):
        bruto.tarefa({}, Contexto(tmp_path / "ctx2"))

    assert bruto.cli(["--projeto", PROJETO, "--sem-transcricao"]) == 0
    saida = capsys.readouterr().out
    assert "2 tomada(s)" in saida and "tomadas-01.jpg" in saida and "60 Hz" in saida
    assert bruto.cli(["--projeto", "nao-existe"]) == 1


# ------------------------------------------------------------ revisão: casos fora do sintético

def test_vfr_nao_acusa_25_fps_pela_media(cfg):
    # celular a 30 fps no escuro: média de ~25 fps com taxa variável não é "gravado a 25 fps"
    info = midia.InfoMidia(caminho="IMG_0003.mp4", tipo="video", largura=1080, altura=1920, fps=24.9,
                           fps_variavel=True, tem_audio=True)
    av = bruto.avisos_midia(info, "com_audio")
    assert any("constante" in x for x in av) and not any("60 Hz" in x for x in av)


def test_tempos_do_ffmpeg_em_notacao_cientifica(cfg, monkeypatch, tmp_path):
    """O ffmpeg escreve "%.6g": áudio que começa 0,02 ms depois do vídeo sai "silence_start: 2.08333e-05"."""
    stderr = {
        "silencedetect": ("[silencedetect @ 0x1] silence_start: 2.08333e-05\n"
                          "[silencedetect @ 0x1] silence_end: 1.00269 | silence_duration: 1.00267\n"
                          "[silencedetect @ 0x1] silence_start: 2.5\n"),
        "showinfo": ("[Parsed_showinfo_2 @ 0x1] n:   0 pts:      1 pts_time:3.33333e-05 duration: 1\n"
                     "[Parsed_showinfo_2 @ 0x1] n:   1 pts:  30720 pts_time:1.5     duration:512\n"),
    }

    def rodar(cmd, timeout=None, verificar=True):
        filtro = next(x for x in cmd if "silencedetect" in x or "showinfo" in x)
        return types.SimpleNamespace(stdout="", stderr=stderr["silencedetect" if "silencedetect" in filtro else "showinfo"])

    monkeypatch.setattr(bruto.ferramentas, "rodar", rodar)
    monkeypatch.setattr(midia, "sondar", lambda c: midia.InfoMidia(caminho=str(c), tipo="video", duracao_s=3.0,
                                                                   tem_audio=True))
    monkeypatch.setattr(midia, "ffmpeg", lambda: "ffmpeg")
    assert bruto.detectar_silencios(tmp_path / "x.mp4") == [{"ini_s": 0.0, "fim_s": 1.003}, {"ini_s": 2.5, "fim_s": 3.0}]
    assert bruto.detectar_tomadas(tmp_path / "x.mp4") == [{"ini_s": 0.0, "fim_s": 1.5}, {"ini_s": 1.5, "fim_s": 3.0}]


@pytest.mark.ffmpeg
def test_mesmo_nome_com_extensoes_diferentes_nao_apaga_legenda(cfg, fala_falsa):
    pasta = pasta_bruto(cfg)
    sintetico.video(pasta / "IMG_0001.MOV", duracao=1.0, audio="fala")
    sintetico.video(pasta / "IMG_0001.mp4", duracao=1.0, audio="fala")
    r = bruto.preparar(PROJETO)
    srts = r["transcricao"]["arquivos_srt"]
    assert len(set(s.casefold() for s in srts.values())) == 2
    trabalho = cfg.p.videos / "trabalho" / PROJETO
    assert all((trabalho / s).exists() for s in srts.values())


@pytest.mark.ffmpeg
def test_musica_sem_batidas_avisa(cfg, monkeypatch):
    mod = types.ModuleType("rotinas.video.batidas")
    mod.detectar_batidas = lambda caminho: {"bpm": 0.0, "batidas_s": [], "compassos_s": [],
                                            "primeira_batida_s": None, "confianca": 0.0}
    monkeypatch.setitem(sys.modules, "rotinas.video.batidas", mod)
    pasta = pasta_bruto(cfg)
    sintetico.video(pasta / "IMG_0001.mp4", duracao=1.0, audio=None)
    sintetico.musica_cliques(pasta / "guia.wav", duracao=2.0)
    r = bruto.preparar(PROJETO, musica="guia.wav")
    assert any("Não achei batidas regulares em guia.wav" in a for a in r["avisos"])
    assert not any("confiança baixa" in a for a in r["avisos"])
