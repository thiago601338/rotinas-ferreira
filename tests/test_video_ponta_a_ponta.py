"""Integração B1 → B2 → B4: bruto sintético → bruto.json → plano (R1 e R2) → exportado sintético → conferência.

Só a transcrição é falsa (o faster-whisper não roda na nuvem); tomadas, silêncios, batidas, folhas, plano e conferência
são os módulos de verdade sobre mídia gerada pelo ffmpeg.
"""

from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path

import pytest

import sintetico
from rotinas import midia
from rotinas.video import bruto, conferencia, plano, transcricao

PROJETO = "vestido verde"  # com espaço, como no Windows
QUADRO = 1 / 30
BPM = 120.0
PERIODO = 60.0 / BPM

# vídeo 1: cortes secos de cor a cada 4 s (6 tomadas, sem áudio); vídeo 2: vendedora falando (tom intermitente)
CENAS = ["black", "white", "navy", "yellow", "black", "white"]
CENA_S = 4.0
FALA_S = 4.0
# palavras falsas nos trechos com som do vídeo 2 (0–0,5 s, 1–1,5 s, 2–2,5 s); o Whisper às vezes separa o cifrão e
# escreve o preço com ponto: legendas.srt e plano têm que sair no formato da loja (R$229,99)
PALAVRAS = [
    {"ini_s": 0.05, "fim_s": 0.3, "texto": "Esse"},
    {"ini_s": 0.3, "fim_s": 0.45, "texto": "vestido"},
    {"ini_s": 1.05, "fim_s": 1.3, "texto": "custa"},
    {"ini_s": 1.3, "fim_s": 1.45, "texto": "R$"},
    {"ini_s": 2.05, "fim_s": 2.45, "texto": "229.99."},
]

ESCOLHAS_R1 = {
    "destino": "reels", "sku": "FB-0123", "preco": 229.99, "cta": "Chama no WhatsApp",
    "musica": {"arquivo": "guia.wav", "no_capcut": False},
    "blocos": [
        {"papel": "gancho", "tomada": "T01", "texto": "4 looks com 1 saia"},
        {"papel": "look", "tomada": "T02"},
        {"papel": "look", "tomada": "T03"},
        {"papel": "look", "tomada": "T04"},
        {"papel": "look_final", "tomada": "T05"},
        {"papel": "preco", "tomada": "T06"},
    ],
}

ESCOLHAS_R2 = {
    "destino": "reels", "sku": "FB-0456", "preco": 229.99, "cta": "Chama no WhatsApp", "legendas": True,
    "blocos": [
        {"papel": "gancho", "tomada": "T01", "texto": "Vestido verde no provador"},
        {"papel": "prova", "tomada": "T02"},
        {"papel": "prova", "tomada": "T07"},  # a fala da vendedora
        {"papel": "detalhe", "tomada": "T03"},
        {"papel": "bolso", "tomada": "T04", "texto": "bolso embutido"},
        {"papel": "preco", "tomada": "T05"},
    ],
}


def _hashes(pasta: Path) -> dict[str, str]:
    return {p.name: midia.hash_arquivo(p) for p in sorted(pasta.iterdir())}


@pytest.fixture
def fala_falsa(monkeypatch):
    chamadas = []

    def transcrever(caminho, modelo=None):
        chamadas.append(Path(caminho).name)
        return [dict(p) for p in PALAVRAS]

    monkeypatch.setattr(transcricao, "transcrever", transcrever)
    return chamadas


def _principais(p: dict) -> list[dict]:
    return sorted((v for v in p["video"] if v.get("faixa", 0) == 0), key=lambda v: v["ini_s"])


def _conferir_comum(p: dict, receita_id: str) -> None:
    """Regras que valem para qualquer plano: sem violações, linha contínua, gancho no quadro 1, duração, preço."""
    assert plano.validar_plano(p) == [], p["violacoes"]
    assert p["violacoes"] == []
    assert p["receita"] == receita_id and p["destino"] == "reels"
    assert p["canvas"] == {"largura": 1080, "altura": 1920, "fps": 30.0}
    lo, hi = p["regras"]["duracao_s"]
    assert lo - QUADRO / 2 <= p["duracao_s"] <= hi + QUADRO / 2
    t = 0.0
    for v in _principais(p):
        assert v["ini_s"] == pytest.approx(t, abs=1e-3)
        assert v["fonte_fim_s"] > v["fonte_ini_s"]
        t = v["ini_s"] + v["dur_s"]
    assert t == pytest.approx(p["duracao_s"], abs=1e-3)
    assert _principais(p)[0]["papel"] == "gancho"
    gancho = next(x for x in p["textos"] if x["papel"] == "gancho")
    assert gancho["ini_s"] == 0.0 and gancho["entrada_s"] <= 0.5
    # preço pela regra da loja: R$229,99 → até R$319,98 em 3x, parcela arredondada ao centavo
    assert plano.formatar_preco(229.99) == "R$229,99"
    assert plano.parcelas(229.99) == "3x sem juros"
    textos = {x["papel"]: x["texto"].replace("\n", " ") for x in p["textos"]}
    assert textos["preco"] == "R$229,99" and textos["parcelas"] == "3x sem juros"
    assert textos["cta"] == "Chama no WhatsApp"
    assert p["preco"]["texto"] == "R$229,99" and p["preco"]["parcelas"] == "3x sem juros"
    for x in p["textos"] + p["legendas"]:
        assert plano.precos_fora_do_formato(x["texto"]) == [], x
        assert x["ini_s"] >= 0 and x["ini_s"] + x["dur_s"] <= p["duracao_s"] + 1e-3


def _exportado_sintetico(destino: Path, duracao: float, lufs: float = -14.0, kbps: int = 16000) -> Path:
    """Faz de conta que é o CapCut: 1080×1920, 30 fps, H.264 CBR e tom estéreo perto de −14 LUFS."""
    amp = 10 ** ((lufs + 0.7) / 20)  # tom de 440 Hz estéreo: LUFS ≈ 20·log10(amplitude) − 0,7
    onda = f"{amp:.5f}*sin(2*PI*440*t)"
    taxa = f"{kbps}k"
    destino.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", f"testsrc2=s=1080x1920:r=30:d={duracao:.4f}",
         "-f", "lavfi", "-i", f"aevalsrc={onda}|{onda}:s=48000:d={duracao:.4f}",
         "-map", "0:v", "-map", "1:a", "-c:a", "aac", "-b:a", "192k",
         "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-b:v", taxa, "-minrate", taxa,
         "-maxrate", taxa, "-bufsize", f"{kbps // 2}k", "-x264-params", "nal-hrd=cbr",
         "-t", f"{duracao:.4f}", "-movflags", "+faststart", str(destino)],
        check=True,
    )
    return destino


@pytest.mark.ffmpeg
def test_bruto_ao_plano_e_a_conferencia(cfg, fala_falsa):
    pasta = cfg.p.videos / "bruto" / PROJETO
    sintetico.video(pasta / "IMG_0001.MOV", duracao=CENA_S * len(CENAS), cenas=CENAS, audio=None)
    sintetico.video(pasta / "IMG_0002.MOV", duracao=FALA_S, audio="fala")
    guia = sintetico.musica_cliques(cfg.p.videos / "musicas" / "guia.wav", bpm=BPM, duracao=30.0)
    antes = _hashes(pasta)
    hash_guia = midia.hash_arquivo(guia)

    # ---------------------------------------------------------------- B1: preparar
    r = bruto.preparar(PROJETO, musica="guia.wav")
    trabalho = cfg.p.videos / "trabalho" / PROJETO
    assert _hashes(pasta) == antes and midia.hash_arquivo(guia) == hash_guia  # bruto e música intactos
    assert json.loads((trabalho / "bruto.json").read_text(encoding="utf-8")) == json.loads(json.dumps(r))

    # tomadas: 6 cortes secos + o vídeo da fala inteiro, IDs globais em ordem
    assert [t["id"] for t in r["tomadas"]] == [f"T{n:02d}" for n in range(1, 8)]
    assert [t["arquivo"] for t in r["tomadas"]] == ["IMG_0001.MOV"] * 6 + ["IMG_0002.MOV"]
    for k, t in enumerate(r["tomadas"][:6]):
        assert t["ini_s"] == pytest.approx(k * CENA_S, abs=QUADRO + 1e-3)
        assert t["fim_s"] == pytest.approx((k + 1) * CENA_S, abs=QUADRO + 1e-3)
    assert r["tomadas"][6]["ini_s"] == 0.0 and r["tomadas"][6]["fim_s"] == pytest.approx(FALA_S, abs=QUADRO + 1e-3)

    # silêncios: sem faixa de áudio = tudo silêncio; na fala, as pausas de 0,5 s
    a1, a2 = r["arquivos"]
    assert a1["silencios"] == [{"ini_s": 0.0, "fim_s": pytest.approx(CENA_S * len(CENAS), abs=QUADRO)}]
    assert a1["fala"] is False
    assert len(a2["silencios"]) >= 2 and a2["fala"] is True
    for s in a2["silencios"]:
        assert 0.3 <= s["fim_s"] - s["ini_s"] <= 0.6 + QUADRO

    # batidas da faixa de cliques (detector de verdade): 120 BPM, na grade de 0,5 s
    m = r["musica"]
    assert m["arquivo"] == str(guia)
    assert m["bpm"] == pytest.approx(BPM, abs=1.0)
    assert len(m["batidas_s"]) >= 50
    for b in m["batidas_s"]:
        assert abs(b - round(b / PERIODO) * PERIODO) <= 0.02, b
    assert (trabalho / "batidas.json").is_file()

    # folhas de contato
    assert r["folhas"] == ["folhas/tomadas-01.jpg"]
    assert (trabalho / "folhas" / "tomadas-01.jpg").is_file()
    assert all(t["folha"] == "folhas/tomadas-01.jpg" for t in r["tomadas"])

    # transcrição (falsa) só do arquivo com fala; SRT sem bloco terminando em "R$"
    assert fala_falsa == ["IMG_0002.MOV"]
    assert r["transcricao"]["arquivo_srt"] == "legendas.srt"
    assert {w["arquivo"] for w in r["transcricao"]["palavras"]} == {"IMG_0002.MOV"}
    blocos_srt = transcricao.ler_srt((trabalho / "legendas.srt").read_text(encoding="utf-8"))
    assert blocos_srt and all(b["texto"].split()[-1] != "R$" for b in blocos_srt)
    assert [b["texto"].replace("\n", " ") for b in blocos_srt] == ["Esse vestido", "custa R$229,99."]
    assert all(plano.precos_fora_do_formato(b["texto"]) == [] for b in blocos_srt)

    # ---------------------------------------------------------------- B2: R1 troca de look na batida
    p1 = plano.planejar(PROJETO, "r01", copy.deepcopy(ESCOLHAS_R1))
    _conferir_comum(p1, "r01-troca-de-look-na-batida")
    principais = _principais(p1)
    batidas = m["batidas_s"]
    for v in principais[1:]:
        perto = min(batidas, key=lambda b: abs(b - v["ini_s"]))
        assert abs(perto - v["ini_s"]) <= QUADRO + 1e-6, (v["ini_s"], perto)
    assert all(abs(b - round(b / PERIODO) * PERIODO) <= 0.02 for b in p1["batidas_s"])
    assert [x["texto"] for x in p1["textos"] if x["papel"] == "contador"] == [f"LOOK {n}/4" for n in range(1, 5)]
    assert next(x for x in p1["textos"] if x["papel"] == "gancho")["texto"].replace("\n", " ") == "4 looks com 1 saia"
    assert p1["audio"][0]["papel"] == "guia" and p1["audio"][0]["arquivo"] == str(guia)
    assert p1["legendas"] == []
    # os clipes apontam para o bruto (o CapCut importa o original; nada foi copiado)
    assert {Path(v["arquivo"]) for v in principais} == {pasta / "IMG_0001.MOV"}
    for v in principais:
        t = next(t for t in r["tomadas"] if t["id"] == v["tomada"])
        assert t["ini_s"] - 1e-3 <= v["fonte_ini_s"] < v["fonte_fim_s"] <= t["fim_s"] + 1e-3
    gravado = json.loads((trabalho / "plano.json").read_text(encoding="utf-8"))
    assert gravado == p1

    # ---------------------------------------------------------------- B2: R2 provador com preço (com fala)
    p2 = plano.planejar(PROJETO, "r02", copy.deepcopy(ESCOLHAS_R2))
    _conferir_comum(p2, "r02-provador-com-preco")
    principais2 = _principais(p2)
    fala = [v for v in principais2 if v["fala"]]
    assert [v["tomada"] for v in fala] == ["T07"] and fala[0]["mudo"] is False
    assert p2["legendas"], p2["avisos"]
    for lg in p2["legendas"]:
        fim = lg["ini_s"] + lg["dur_s"]
        assert any(v["ini_s"] - 1e-3 <= lg["ini_s"] < fim <= v["ini_s"] + v["dur_s"] + 1e-3 for v in fala), lg
    juntas = " ".join(lg["texto"].replace("\n", " ") for lg in p2["legendas"])
    assert "R$229,99" in juntas and "R$ 229" not in juntas  # preço da fala no formato da loja
    assert next(x for x in p2["textos"] if x["papel"] == "rotulo")["texto"].replace("\n", " ") == "bolso embutido"
    assert _hashes(pasta) == antes

    # ---------------------------------------------------------------- B4: exportado sintético → conferência
    exportado = _exportado_sintetico(bruto.pastas_projeto(PROJETO)["exportado"] / f"{PROJETO} r01.mp4",
                                     p1["duracao_s"])
    assert conferencia.mais_recente() == exportado
    res = conferencia.conferir(conferencia.resolver_arquivo(exportado.name), destino="reels",
                               duracao_esperada_s=p1["duracao_s"])
    assert res["aprovado"], [i for i in res["itens"] if not i["ok"]]
    assert abs(res["medidas"]["duracao_s"] - p1["duracao_s"]) <= 0.1
    assert res["medidas"]["lufs"] == pytest.approx(-14.0, abs=1.0)
    assert "APROVADO" in conferencia.texto(res)
    # o mesmo arquivo contra a duração do plano R2 (outra duração) reprova só a duração
    if abs(p2["duracao_s"] - p1["duracao_s"]) > 0.6:
        outro = conferencia.conferir(exportado, destino="reels", duracao_esperada_s=p2["duracao_s"])
        assert {i["item"] for i in outro["itens"] if not i["ok"]} == {"duração"}
