import json
import os
import subprocess
from pathlib import Path

import pytest

from rotinas import midia
from rotinas.contexto import Contexto
from rotinas.video import conferencia

ITENS = ["duração", "resolução", "taxa de quadros", "codec", "formato", "taxa de bits", "áudio", "volume",
         "pico real", "tamanho", "HDR"]


def _video(caminho: Path, largura=1080, altura=1920, fps=30, kbps=16000, lufs=-14.0, duracao=3.5, hdr=False) -> Path:
    """Vídeo H.264 com taxa de bits constante (preenchimento CBR) e tom estéreo de 440 Hz no volume pedido.

    3,5 s por padrão: o Reels pede pelo menos 3 s.
    """
    entradas = ["-f", "lavfi", "-i", f"testsrc2=s={largura}x{altura}:r={fps}:d={duracao}"]
    mapa = ["-map", "0:v"]
    if lufs is not None:
        amp = 10 ** ((lufs + 0.7) / 20)  # tom de 440 Hz estéreo: LUFS ≈ 20·log10(amplitude) − 0,7
        onda = f"{amp:.5f}*sin(2*PI*440*t)"
        entradas += ["-f", "lavfi", "-i", f"aevalsrc={onda}|{onda}:s=48000:d={duracao}"]
        mapa += ["-map", "1:a", "-c:a", "aac", "-b:a", "192k"]
    taxa = f"{kbps}k"
    cor = ["-color_primaries", "bt2020", "-color_trc", "smpte2084", "-colorspace", "bt2020nc"] if hdr else []
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *entradas, *mapa, "-c:v", "libx264", "-preset",
         "ultrafast", "-pix_fmt", "yuv420p", "-b:v", taxa, "-minrate", taxa, "-maxrate", taxa, "-bufsize",
         f"{kbps // 2}k", "-x264-params", "nal-hrd=cbr", *cor, "-t", str(duracao), "-movflags", "+faststart",
         str(caminho)],
        check=True,
    )
    return caminho


@pytest.fixture(scope="module")
def pasta_videos(tmp_path_factory):
    return tmp_path_factory.mktemp("videos")


@pytest.fixture(scope="module")
def video_ok(pasta_videos):
    return _video(pasta_videos / "reels ok.mp4")


def _itens(resultado: dict) -> dict:
    return {i["item"]: i for i in resultado["itens"]}


def _so_falha(resultado: dict, *nomes: str) -> None:
    falhas = {i["item"] for i in resultado["itens"] if not i["ok"]}
    assert falhas == set(nomes), resultado["itens"]
    for nome in nomes:
        assert _itens(resultado)[nome].get("fazer"), nome


@pytest.mark.ffmpeg
def test_passa_no_reels(cfg, video_ok):
    r = conferencia.conferir(video_ok, "reels")
    assert [i["item"] for i in r["itens"]] == ITENS
    assert all({"item", "esperado", "obtido", "ok"} <= set(i) for i in r["itens"])
    assert r["aprovado"], r["itens"]
    assert r["destino"] == "reels" and r["arquivo"] == str(video_ok)
    assert abs(r["medidas"]["lufs"] - (-14.0)) <= 0.7
    assert r["medidas"]["pico_real_dbtp"] <= -1.0
    itens = _itens(r)
    assert itens["resolução"]["obtido"] == "1080×1920"
    assert itens["taxa de quadros"]["obtido"] == "30 fps"
    assert itens["codec"]["obtido"] == "H.264"
    assert not any("fazer" in i for i in r["itens"])
    rel = conferencia.texto(r)
    assert "APROVADO" in rel and "Não passou" not in rel
    json.dumps(r)  # vira JSON (resultado da fila)


@pytest.mark.ffmpeg
def test_duracao_esperada(cfg, video_ok):
    assert _itens(conferencia.conferir(video_ok, "reels", duracao_esperada_s=3.8))["duração"]["ok"]
    r = conferencia.conferir(video_ok, "reels", duracao_esperada_s=6.0)
    _so_falha(r, "duração")
    assert "a menos que o plano" in _itens(r)["duração"]["fazer"]


@pytest.mark.ffmpeg
@pytest.mark.parametrize("nome, opcoes, item, dica", [
    ("720p", {"largura": 720, "altura": 1280}, "resolução", "Resolução 1080P"),
    ("25fps", {"fps": 25}, "taxa de quadros", "Taxa de quadros 30"),
    ("horizontal", {"largura": 1920, "altura": 1080}, "resolução", "Proporção"),
])
def test_falha_de_imagem(cfg, pasta_videos, nome, opcoes, item, dica):
    r = conferencia.conferir(_video(pasta_videos / f"{nome}.mp4", **opcoes), "reels")
    assert not r["aprovado"]
    _so_falha(r, item)
    assert dica in _itens(r)[item]["fazer"]
    rel = conferencia.texto(r)
    assert "REPROVADO" in rel and dica in rel


@pytest.mark.ffmpeg
def test_sem_audio(cfg, pasta_videos):
    r = conferencia.conferir(_video(pasta_videos / "mudo.mp4", lufs=None), "reels")
    _so_falha(r, "áudio", "volume", "pico real")
    itens = _itens(r)
    assert itens["áudio"]["obtido"] == "sem faixa de áudio"
    assert "sem som" in itens["áudio"]["fazer"]
    assert itens["volume"]["fazer"] == "Ver o item áudio."


@pytest.mark.ffmpeg
def test_audio_baixo_do_alvo_padrao_do_capcut(cfg, pasta_videos):
    r = conferencia.conferir(_video(pasta_videos / "baixo.mp4", lufs=-23.0), "reels")
    _so_falha(r, "volume")
    volume = _itens(r)["volume"]
    assert abs(r["medidas"]["lufs"] - (-23.0)) <= 0.7
    assert "−23 LUFS" in volume["fazer"] and "Subir o volume dos clipes com som (voz e música) ~9 dB" in volume["fazer"]


@pytest.mark.ffmpeg
def test_acima_do_limite_do_stories(cfg, pasta_videos):
    arq = _video(pasta_videos / "stories.mp4", kbps=11000, duracao=4.0)
    assert conferencia.conferir(arq, "stories")["aprovado"]
    presets = json.loads((cfg.dir / "exportacao.json").read_text(encoding="utf-8"))["presets"]
    presets["stories"]["tamanho_max_mb"] = 1
    cfg.alterar("exportacao", presets=presets)
    r = conferencia.conferir(arq, "stories")
    _so_falha(r, "tamanho")
    fazer = _itens(r)["tamanho"]["fazer"]
    assert "(MB × 8) ÷ s" in fazer and "(1 × 8) ÷ 4,0 = 2,0 Mbps" in fazer
    assert "Personalizado até 1.800 Kbps" in fazer


@pytest.mark.ffmpeg
def test_mov_e_hdr(cfg, pasta_videos, video_ok):
    mov = pasta_videos / "reels.mov"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(video_ok), "-c", "copy", str(mov)],
                   check=True)
    r = conferencia.conferir(mov, "reels")
    _so_falha(r, "formato")
    assert "BlueStacks" in _itens(r)["formato"]["fazer"]
    r = conferencia.conferir(_video(pasta_videos / "hdr.mp4", hdr=True), "reels")
    _so_falha(r, "HDR")


@pytest.mark.ffmpeg
def test_taxa_de_bits_fora_da_faixa(cfg, pasta_videos):
    r = conferencia.conferir(_video(pasta_videos / "pesado.mp4", kbps=40000), "reels")
    _so_falha(r, "taxa de bits")
    assert "Personalizado 16.000 Kbps" in _itens(r)["taxa de bits"]["fazer"]


@pytest.mark.ffmpeg
def test_pico_alto_e_ganho_que_estouraria(cfg, video_ok, monkeypatch):
    monkeypatch.setattr(midia, "loudness", lambda c: {"lufs": -14.2, "lra": 1.0, "pico_real_dbtp": -0.3})
    r = conferencia.conferir(video_ok, "reels")
    _so_falha(r, "pico real")
    assert "Baixar ~0,7 dB" in _itens(r)["pico real"]["fazer"]

    monkeypatch.setattr(midia, "loudness", lambda c: {"lufs": -23.0, "lra": 1.0, "pico_real_dbtp": -4.0})
    volume = _itens(conferencia.conferir(video_ok, "reels"))["volume"]
    assert "iria a 5,0 dBTP" in volume["fazer"] and "(~3 dB)" in volume["fazer"]

    monkeypatch.setattr(midia, "loudness", lambda c: {"lufs": -70.0, "lra": 0.0, "pico_real_dbtp": float("-inf")})
    r = conferencia.conferir(video_ok, "reels")
    _so_falha(r, "áudio", "volume", "pico real")
    assert _itens(r)["áudio"]["obtido"].endswith("mas mudo")
    assert r["medidas"]["pico_real_dbtp"] is None
    json.dumps(r, allow_nan=False)


@pytest.mark.ffmpeg
def test_destino_desconhecido(cfg, video_ok):
    with pytest.raises(ValueError, match="Destinos"):
        conferencia.conferir(video_ok, "youtube")


@pytest.mark.ffmpeg
def test_tarefa_pelo_nome_em_exportado(cfg, video_ok, tmp_path):
    exportado = cfg.p.videos / "exportado"
    exportado.mkdir(parents=True, exist_ok=True)
    (exportado / "vestido verde.mp4").write_bytes(video_ok.read_bytes())
    ctx = Contexto(tmp_path / "pedido")
    r = conferencia.tarefa({"arquivo": "vestido verde.mp4", "destino": "reels", "duracao_esperada_s": 3.5}, ctx)
    assert r["aprovado"] and "APROVADO" in r["texto"]
    salvo = json.loads(ctx.arquivo("conferencia.json").read_text(encoding="utf-8"))
    assert salvo["aprovado"] and len(salvo["itens"]) == len(ITENS)
    assert "APROVADO" in ctx.arquivo("conferencia.txt").read_text(encoding="utf-8")
    with pytest.raises(midia.ErroMidia, match="Não achei"):
        conferencia.tarefa({"arquivo": "nao-existe.mp4"}, ctx)
    with pytest.raises(ValueError, match="arquivo"):
        conferencia.tarefa({}, ctx)


@pytest.mark.ffmpeg
def test_cli_e_teste_real(cfg, pasta_videos, video_ok, tmp_path, capsys):
    assert conferencia.cli(["--arquivo", str(video_ok)]) == 0
    assert "APROVADO" in capsys.readouterr().out
    # duração digitada com vírgula (teclado PT-BR) no terminal e na fila
    assert conferencia.cli(["--arquivo", str(video_ok), "--duracao", "3,5", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["itens"][0]["esperado"].startswith("3,5 s ± 0,5 s")
    assert conferencia.cli(["--arquivo", str(video_ok), "--duracao", "9,0"]) == 1
    capsys.readouterr()
    with pytest.raises(ValueError, match="duração inválida"):
        conferencia.tarefa({"arquivo": str(video_ok), "duracao_esperada_s": "3,5 s"}, Contexto(tmp_path / "x"))
    baixo = _video(pasta_videos / "baixo-cli.mp4", lufs=-23.0, duracao=1.0)
    assert conferencia.cli(["--arquivo", str(baixo), "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["aprovado"] is False
    assert conferencia.cli(["--arquivo", str(tmp_path / "nao-tem.mp4")]) == 2
    assert "Não achei" in capsys.readouterr().err
    assert conferencia.cli([]) == 2  # videos\exportado vazio

    exportado = cfg.p.videos / "exportado"
    exportado.mkdir(parents=True, exist_ok=True)
    (exportado / "antigo.mp4").write_bytes(baixo.read_bytes())
    novo = exportado / "novo.mp4"
    novo.write_bytes(video_ok.read_bytes())
    os.utime(exportado / "antigo.mp4", (1, 1))
    ctx = Contexto(tmp_path / "execucao")
    r = conferencia.teste_real(ctx, ["--destino", "reels"])
    assert r["arquivo"] == str(novo) and r["aprovado"]
    for nome in ("conferencia.json", "conferencia.txt", "ffprobe.json"):
        assert (ctx.pasta_saida / nome).exists()
    assert not list(ctx.pasta_saida.glob("*.mp4"))  # vídeo não vai para execucoes/


# ---------------------------------------------------------------- som esperado (achado #3)

@pytest.mark.ffmpeg
def test_plano_mudo_nao_reprova_audio_volume_e_pico(cfg, pasta_videos):
    # R1 "troca de look na batida" sem fala: música pelo Instagram, o .mp4 sai mudo de propósito.
    sem_faixa = _video(pasta_videos / "mudo-plano.mp4", lufs=None)
    _so_falha(conferencia.conferir(sem_faixa, "reels"), "áudio", "volume", "pico real")  # sem o plano: reprova
    r = conferencia.conferir(sem_faixa, "reels", som_esperado="mudo")
    assert r["aprovado"], r["itens"]
    assert r["som_esperado"] == "mudo"
    itens = _itens(r)
    assert itens["áudio"]["esperado"].startswith("mudo") and "n/a" in itens["volume"]["obtido"]
    assert "APROVADO" in conferencia.texto(r)


@pytest.mark.ffmpeg
def test_plano_mudo_com_faixa_silenciosa_e_com_som_esquecido(cfg, video_ok, monkeypatch):
    monkeypatch.setattr(midia, "loudness", lambda c: {"lufs": -70.0, "lra": 0.0, "pico_real_dbtp": float("-inf")})
    assert conferencia.conferir(video_ok, "reels", som_esperado="mudo")["aprovado"]
    # resto de clipe a −60 dB: ainda conta como mudo
    monkeypatch.setattr(midia, "loudness", lambda c: {"lufs": -66.0, "lra": 0.0, "pico_real_dbtp": -55.0})
    assert conferencia.conferir(video_ok, "reels", som_esperado="mudo")["aprovado"]
    # faixa-guia esquecida ligada: o plano diz mudo, o arquivo tem música
    monkeypatch.setattr(midia, "loudness", lambda c: {"lufs": -14.0, "lra": 1.0, "pico_real_dbtp": -2.0})
    r = conferencia.conferir(video_ok, "reels", som_esperado="mudo")
    _so_falha(r, "áudio")
    assert "faixa-guia" in _itens(r)["áudio"]["fazer"]


@pytest.mark.ffmpeg
def test_so_efeitos_nao_cobra_o_volume(cfg, video_ok, monkeypatch):
    monkeypatch.setattr(midia, "loudness", lambda c: {"lufs": -27.0, "lra": 1.0, "pico_real_dbtp": -0.2})
    _so_falha(conferencia.conferir(video_ok, "reels"), "volume", "pico real")
    r = conferencia.conferir(video_ok, "reels", som_esperado="so_efeitos")
    _so_falha(r, "pico real")  # o pico continua valendo
    assert _itens(r)["volume"]["ok"]


@pytest.mark.ffmpeg
def test_tarefa_e_cli_aceitam_som_esperado(cfg, pasta_videos, tmp_path, capsys):
    mudo = _video(pasta_videos / "mudo-tarefa.mp4", lufs=None)
    ctx = Contexto(tmp_path / "pedido")
    assert conferencia.tarefa({"arquivo": str(mudo), "som_esperado": "mudo"}, ctx)["aprovado"]
    assert not conferencia.tarefa({"arquivo": str(mudo)}, ctx)["aprovado"]
    with pytest.raises(ValueError, match="som_esperado"):
        conferencia.tarefa({"arquivo": str(mudo), "som_esperado": "alto"}, ctx)
    # pelo projeto: deduz do plano.json (como o video.exportar)
    trabalho = cfg.p.videos / "trabalho" / "vestido-verde"
    trabalho.mkdir(parents=True)
    (trabalho / "plano.json").write_text(json.dumps({
        "duracao_s": 3.5, "audio": [{"arquivo": "guia.mp3", "papel": "guia", "exportar": False}],
        "video": [{"arquivo": "a.mp4", "mudo": True}]}), encoding="utf-8")
    assert conferencia.tarefa({"arquivo": str(mudo), "projeto": "vestido-verde"}, ctx)["aprovado"]
    assert conferencia.cli(["--arquivo", str(mudo), "--som", "mudo"]) == 0
    assert "APROVADO" in capsys.readouterr().out
