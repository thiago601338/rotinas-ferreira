import subprocess

import numpy as np
import pytest

import sintetico
from rotinas import midia
from rotinas.video import batidas


def _cliques(inicio: float, duracao: float, bpm: float) -> np.ndarray:
    return np.arange(inicio, duracao, 60.0 / bpm)


def _conferir(r: dict, bpm: float, inicio: float, duracao: float) -> None:
    cliques = _cliques(inicio, duracao, bpm)
    achadas = np.array(r["batidas_s"])
    assert abs(r["bpm"] - bpm) / bpm <= 0.02, r["bpm"]
    assert len(achadas) >= 0.9 * len(cliques), (len(achadas), len(cliques))
    distancias = np.array([np.min(np.abs(cliques - b)) for b in achadas])
    assert np.mean(distancias <= 0.030) >= 0.9, distancias
    assert r["primeira_batida_s"] == r["batidas_s"][0]
    assert 0.3 <= r["confianca"] <= 1.0
    # compassos: a cada 4 batidas, todos em cima de batidas
    assert set(r["compassos_s"]) <= set(r["batidas_s"])
    assert np.allclose(np.diff(r["compassos_s"]), 4 * 60.0 / bpm, atol=0.03)


@pytest.mark.ffmpeg
@pytest.mark.parametrize("bpm", [90, 120, 128])
def test_bpm_e_batidas_nos_cliques(cfg, tmp_path, bpm):
    arq = sintetico.musica_cliques(tmp_path / f"cliques_{bpm}.wav", bpm=bpm, duracao=10.0)
    r = batidas.detectar_batidas(arq)
    _conferir(r, bpm, 0.0, 10.0)


@pytest.mark.ffmpeg
def test_comeco_em_silencio(cfg, tmp_path):
    arq = sintetico.musica_cliques(tmp_path / "atrasada.wav", bpm=120, duracao=10.0, inicio=2.0)
    r = batidas.detectar_batidas(arq)
    _conferir(r, 120, 2.0, 10.0)
    assert r["primeira_batida_s"] > 0
    assert abs(r["primeira_batida_s"] - 2.0) <= 0.03
    assert all(b >= 2.0 - 0.03 for b in r["batidas_s"])


@pytest.mark.ffmpeg
def test_introducao_baixa_nao_perde_batidas(cfg, tmp_path):
    """Música que começa baixa (−18 dB nos 10 primeiros segundos): as batidas da introdução continuam lá.

    Antes, o corte das batidas fracas das pontas usava só a média da música inteira e jogava fora a
    introdução: a primeira batida saía em 10 s e o vídeo não tinha onde cortar no ritmo no começo.
    """
    alto = sintetico.musica_cliques(tmp_path / "alto.wav", bpm=120, duracao=30.0)
    arq = tmp_path / "intro baixa.wav"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(alto), "-af",
                    f"volume='if(lt(t,10),{10 ** (-18 / 20):.4f},1)':eval=frame", str(arq)], check=True)
    r = batidas.detectar_batidas(arq)
    _conferir(r, 120, 0.0, 30.0)
    assert r["primeira_batida_s"] <= 0.03
    assert sum(b < 10 for b in r["batidas_s"]) >= 19


def test_bpm_final_em_musica_longa_com_variacao_humana():
    """3 min a 110 BPM com ±12 ms de variação por batida: a mediana dos intervalos erra um pouco e,
    numerando as batidas por ela, as últimas trocavam de número (110,4 BPM). Numerar intervalo a
    intervalo mantém o BPM certo e aguenta batida pulada."""
    rng = np.random.default_rng(2)
    tempos = np.arange(330) * 60 / 110 + rng.normal(0, 0.012, 330)
    assert abs(60 / batidas._periodo_final(tempos) - 110) <= 0.05
    pulada = np.delete(np.arange(200) * 0.5, [50, 51, 120])
    assert abs(60 / batidas._periodo_final(pulada) - 120) <= 0.01


@pytest.mark.ffmpeg
def test_audio_de_video_e_mp3(cfg, tmp_path):
    """Decodifica qualquer coisa que o ffmpeg abre (aqui: a faixa de cliques dentro de um .mp3)."""
    wav = sintetico.musica_cliques(tmp_path / "c.wav", bpm=100, duracao=8.0)
    mp3 = tmp_path / "c.mp3"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(wav), str(mp3)], check=True)
    r = batidas.detectar_batidas(mp3)
    assert abs(r["bpm"] - 100) / 100 <= 0.02


@pytest.mark.ffmpeg
def test_silencio_nao_inventa_batida(cfg, tmp_path):
    arq = tmp_path / "silencio.wav"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "anullsrc=r=44100:cl=mono:d=4", str(arq)], check=True)
    r = batidas.detectar_batidas(arq)
    assert r == {"bpm": 0.0, "batidas_s": [], "compassos_s": [], "primeira_batida_s": None, "confianca": 0.0}


@pytest.mark.ffmpeg
def test_ruido_tem_confianca_baixa(cfg, tmp_path):
    ruido = tmp_path / "ruido.wav"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "anoisesrc=d=8:c=white:r=44100:a=0.3:seed=7", str(ruido)], check=True)
    cliques = sintetico.musica_cliques(tmp_path / "c.wav", bpm=120, duracao=8.0)
    r = batidas.detectar_batidas(ruido)
    assert r["confianca"] < batidas.detectar_batidas(cliques)["confianca"] / 2
    # ruído de fundo sozinho (chiado, ar-condicionado) não vira grade de batidas inventada
    assert r["batidas_s"] == [] and r["bpm"] == 0.0


@pytest.mark.ffmpeg
def test_video_sem_audio_da_erro_claro(cfg, tmp_path):
    arq = sintetico.video(tmp_path / "mudo.mp4", duracao=1.0, audio=None)
    with pytest.raises(midia.ErroMidia, match="áudio"):
        batidas.detectar_batidas(arq)
    with pytest.raises(midia.ErroMidia, match="não existe"):
        batidas.detectar_batidas(tmp_path / "nao-tem.wav")


def test_encaixar():
    grade = [0.5, 1.0, 1.5, 2.0]
    assert batidas.encaixar(1.03, grade) == 1.0
    assert batidas.encaixar(1.47, grade) == 1.5
    assert batidas.encaixar(1.25, grade) == 1.25  # longe de todas (0,25 s > 0,12 s)
    assert batidas.encaixar(1.25, grade, tolerancia_s=0.3) == 1.0  # empate: fica a primeira
    assert batidas.encaixar(0.9, [], 0.12) == 0.9
    assert batidas.encaixar(2.1, grade, tolerancia_s=0.1) == 2.0
    assert batidas.encaixar(2.1, grade, tolerancia_s=0.05) == 2.1


def test_estimar_tempo_prefere_faixa_central():
    """Pulso a 128 BPM também repete a 64 BPM: o peso log-normal (centro ~110) escolhe 128."""
    qps = 22050 / 512
    env = np.zeros(2000)
    periodo = 60 * qps / 128
    env[np.round(np.arange(0, 2000 - 1, periodo)).astype(int)] = 1.0
    atraso, confianca = batidas.estimar_tempo(env, qps, dict(batidas.PADRAO))
    assert abs(60 * qps / atraso - 128) / 128 <= 0.02
    assert confianca > 0.3


def test_estimar_tempo_rapido_demais_vira_metade():
    """170 BPM (fora de 70–140) com a autocorrelação forte no dobro do período vira 85 BPM."""
    qps = 22050 / 512
    env = np.zeros(3000)
    periodo = 60 * qps / 170
    env[np.round(np.arange(0, 3000 - 1, periodo)).astype(int)] = 1.0
    atraso, _ = batidas.estimar_tempo(env, qps, dict(batidas.PADRAO))
    assert abs(60 * qps / atraso - 85) / 85 <= 0.02
