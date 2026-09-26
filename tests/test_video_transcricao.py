import re
import sys
import types

import pytest

from rotinas.video import transcricao

TEMPO_SRT = re.compile(r"^\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3}$")


def palavras(texto, ini=0.0, passo=0.4, dur=0.3):
    """Palavras falsas com tempo, uma a cada ``passo`` segundos."""
    saida, t = [], ini
    for w in texto.split():
        saida.append({"ini_s": round(t, 3), "fim_s": round(t + dur, 3), "texto": w})
        t += passo
    return saida


def textos(blocos):
    return " ".join(b["texto"].replace("\n", " ") for b in blocos).split()


def sem_sobreposicao(blocos):
    for a, b in zip(blocos, blocos[1:]):
        assert a["fim_s"] <= b["ini_s"] + 1e-9, (a, b)
    for b in blocos:
        assert b["fim_s"] > b["ini_s"]


def ultima(bloco):
    return bloco["texto"].split()[-1]


# ------------------------------------------------------------ transcrever (faster-whisper falso)

class _Palavra:
    def __init__(self, word, start, end, probability=0.9):
        self.word, self.start, self.end, self.probability = word, start, end, probability


class _Segmento:
    def __init__(self, words):
        self.words = words


@pytest.fixture
def whisper_falso(monkeypatch):
    mod = types.ModuleType("faster_whisper")
    registro = {"modelos": [], "chamadas": []}

    class WhisperModel:
        def __init__(self, nome, device=None, compute_type=None, download_root=None):
            registro["modelos"].append((nome, device, compute_type))

        def transcribe(self, caminho, **opcoes):
            registro["chamadas"].append((caminho, opcoes))
            segs = [
                _Segmento([_Palavra(" Esse", 0.5, 0.8), _Palavra(" vestido", 0.8, 1.2), _Palavra(" ", 1.2, 1.2)]),
                _Segmento([_Palavra(" custa", 1.3, 1.6, 0.42), _Palavra(" R$229,99.", 1.6, 2.4)]),
            ]
            return iter(segs), types.SimpleNamespace(language="pt")

    mod.WhisperModel = WhisperModel
    monkeypatch.setitem(sys.modules, "faster_whisper", mod)
    monkeypatch.setattr(transcricao, "_modelos", {})
    return registro


def test_transcrever_com_whisper_falso(cfg, tmp_path, whisper_falso):
    arq = tmp_path / "fala.mp4"
    arq.write_bytes(b"x")
    p = transcricao.transcrever(arq)
    assert [w["texto"] for w in p] == ["Esse", "vestido", "custa", "R$229,99."]
    assert p[0] == {"ini_s": 0.5, "fim_s": 0.8, "texto": "Esse", "prob": 0.9}
    assert p[2]["prob"] == 0.42
    _, opcoes = whisper_falso["chamadas"][0]
    assert opcoes["word_timestamps"] is True and opcoes["vad_filter"] is True and opcoes["language"] == "pt"
    assert "Maceió" in opcoes.get("initial_prompt", "")
    assert whisper_falso["modelos"] == [("small", "cpu", "int8")]
    transcricao.transcrever(arq)
    assert len(whisper_falso["modelos"]) == 1  # modelo em cache no processo
    assert len(whisper_falso["chamadas"]) == 2


def test_transcrever_sem_faster_whisper(cfg, tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    monkeypatch.setattr(transcricao, "_modelos", {})
    arq = tmp_path / "fala.mp4"
    arq.write_bytes(b"x")
    with pytest.raises(transcricao.WhisperAusente, match="faster-whisper"):
        transcricao.transcrever(arq)


def test_transcricao_mockada_gera_srt_valido(cfg, tmp_path, whisper_falso):
    arq = tmp_path / "fala.mp4"
    arq.write_bytes(b"x")
    srt = transcricao.gerar_srt(transcricao.blocos_legenda(transcricao.transcrever(arq)))
    partes = srt.strip().split("\n\n")
    for n, parte in enumerate(partes, 1):
        linhas = parte.split("\n")
        assert linhas[0] == str(n)
        assert TEMPO_SRT.match(linhas[1])
        assert 1 <= len(linhas[2:]) <= 2
    lido = transcricao.ler_srt(srt)
    assert textos(lido) == ["Esse", "vestido", "custa", "R$229,99."]
    assert lido[0]["ini_s"] == 0.5


def test_modelo_que_nao_carrega_da_erro_claro(cfg, tmp_path, monkeypatch):
    mod = types.ModuleType("faster_whisper")

    class WhisperModel:
        def __init__(self, *a, **k):
            raise OSError("sem internet")

    mod.WhisperModel = WhisperModel
    monkeypatch.setitem(sys.modules, "faster_whisper", mod)
    monkeypatch.setattr(transcricao, "_modelos", {})
    arq = tmp_path / "fala.mp4"
    arq.write_bytes(b"x")
    with pytest.raises(transcricao.ModeloIndisponivel, match="internet"):
        transcricao.transcrever(arq)
    with pytest.raises(transcricao.ErroTranscricao, match="não existe"):
        transcricao.transcrever(tmp_path / "nao-tem.mp4")


# ------------------------------------------------------------ blocos de legenda

def test_blocos_basico_2_a_4_palavras_e_pontuacao_final(cfg):
    b = transcricao.blocos_legenda(palavras("Oi gente. Hoje eu trouxe três vestidos novos para vocês"))
    assert b[0]["texto"] == "Oi gente."
    assert all(1 <= len(x["texto"].split()) <= 4 for x in b)
    assert textos(b) == "Oi gente. Hoje eu trouxe três vestidos novos para vocês".split()
    sem_sobreposicao(b)


def test_blocos_palavra_longa(cfg):
    longa = "wa.me/5582988748649?text=Quero-comprar-o-vestido"
    assert len(longa) > 42
    b = transcricao.blocos_legenda(palavras(f"Olha esse link: {longa} agora"))
    assert any(x["texto"] == longa for x in b)  # sozinha no bloco, numa linha só
    for x in b:
        for linha in x["texto"].split("\n"):
            assert len(linha) <= 42 or " " not in linha
    # quatro palavras compridas: duas linhas de até 42 caracteres
    b = transcricao.blocos_legenda(palavras("Superconfortável maravilhosamente elegantíssimo extraordinário", passo=0.6))
    for x in b:
        linhas = x["texto"].split("\n")
        assert len(linhas) <= 2 and all(len(l) <= 42 for l in linhas)
    assert any(len(x["texto"].split("\n")) == 2 for x in b)
    assert transcricao.conferir_blocos(b) == []


def test_blocos_nunca_terminam_em_R_ou_artigo(cfg):
    b = transcricao.blocos_legenda(palavras("O vestido custa R$ 229,99"))
    assert any("R$229,99" in x["texto"].replace("\n", " ") for x in b)  # formato da loja: cifrão colado (§5)
    assert all(ultima(x) != "R$" for x in b)
    # "R$" no fim da fala (sem número depois) continua como palavra; pausa longa depois do "R$" não separa o preço
    p = palavras("custa R$") + palavras("99,99.", ini=2.0)
    b = transcricao.blocos_legenda(p)
    assert [x["texto"] for x in b] == ["custa R$99,99."]
    assert b[0]["ini_s"] == 0.0 and b[0]["fim_s"] >= 2.3
    assert textos(transcricao.blocos_legenda(palavras("em R$ reais"))) == ["em", "R$", "reais"]
    frase = "Hoje eu trouxe o vestido longo de festa com a saia de tule para a formatura da sua filha"
    b = transcricao.blocos_legenda(palavras(frase, passo=0.35))
    nao_fecham = {"o", "a", "de", "da", "com", "para", "R$"}
    assert all(ultima(x) not in nao_fecham for x in b[:-1])
    assert textos(b) == frase.split()


def test_blocos_quebra_na_pausa_mas_nao_depois_de_preposicao(cfg):
    p = palavras("Esse vestido") + palavras("é lindo", ini=1.8)
    b = transcricao.blocos_legenda(p)
    assert [x["texto"] for x in b] == ["Esse vestido", "é lindo"]
    # pausa depois de "de" não separa "de" de "festa"
    p = palavras("vestido de") + palavras("festa", ini=2.0)
    b = transcricao.blocos_legenda(p)
    assert all(ultima(x) != "de" for x in b)
    assert "de festa" in " ".join(x["texto"] for x in b)


def test_blocos_nome_e_sobrenome_juntos(cfg):
    b = transcricao.blocos_legenda(palavras("Olha só a Maria Ferreira usando o conjunto de linho"))
    assert any("Maria Ferreira" in x["texto"].replace("\n", " ") for x in b)


def test_blocos_cps_alto_estende_sem_invadir(cfg):
    # 28 caracteres falados em 0,5 s e uma pausa longa depois: o bloco fica ≥ 28/17 s na tela
    p = [{"ini_s": 0.0, "fim_s": 0.2, "texto": "Superconfortável"}, {"ini_s": 0.2, "fim_s": 0.5, "texto": "maravilhosa"},
         {"ini_s": 3.0, "fim_s": 3.3, "texto": "Sim."}]
    b = transcricao.blocos_legenda(p)
    assert b[0]["texto"] == "Superconfortável maravilhosa"
    assert b[0]["fim_s"] >= round(len(b[0]["texto"]) / 17, 3)
    assert b[0]["fim_s"] <= b[1]["ini_s"]
    assert b[1]["fim_s"] - b[1]["ini_s"] >= 1.0  # tempo mínimo
    assert transcricao.conferir_blocos(b) == []
    # próximo bloco perto: estende só até o início dele
    p = [{"ini_s": 0.0, "fim_s": 0.3, "texto": "Superconfortável"}, {"ini_s": 0.3, "fim_s": 0.4, "texto": "demais."},
         {"ini_s": 0.9, "fim_s": 1.2, "texto": "Leva"}, {"ini_s": 1.2, "fim_s": 1.5, "texto": "hoje"}]
    b = transcricao.blocos_legenda(p)
    assert b[0]["fim_s"] == b[1]["ini_s"] == 0.9
    sem_sobreposicao(b)


def test_blocos_muitas_palavras_rapidas(cfg):
    frase = ("olha que lindo esse conjunto de linho verde oliva com calça pantalona e blusa cropped " * 4).split()
    p = [{"ini_s": round(i * 0.12, 3), "fim_s": round(i * 0.12 + 0.11, 3), "texto": w} for i, w in enumerate(frase)]
    b = transcricao.blocos_legenda(p)
    sem_sobreposicao(b)
    assert textos(b) == frase
    assert all(len(x["texto"].split()) <= 4 for x in b)
    assert all(b[i]["fim_s"] == b[i + 1]["ini_s"] for i in range(len(b) - 1))  # emendados, sem piscar
    assert any("caracteres/s" in x for x in transcricao.conferir_blocos(b))  # fala rápida demais fica apontada


def test_blocos_tempos_desordenados_e_vazios(cfg):
    p = [{"ini_s": 1.0, "fim_s": 1.2, "texto": "vestido"}, {"ini_s": 0.5, "fim_s": 0.9, "texto": "Esse"},
         {"ini_s": 1.3, "fim_s": 1.3, "texto": "  "}, {"ini_s": 1.0, "fim_s": 0.8, "texto": "lindo"}]
    b = transcricao.blocos_legenda(p)
    assert textos(b) == ["Esse", "vestido", "lindo"]
    sem_sobreposicao(b)
    assert transcricao.blocos_legenda([]) == []


# ------------------------------------------------------------ SRT

def test_gerar_e_ler_srt():
    blocos = [{"ini_s": 0.5, "fim_s": 1.75, "texto": "Esse vestido"},
              {"ini_s": 3661.004, "fim_s": 3662.5, "texto": "custa R$229,99\nem 3x sem juros"},
              {"ini_s": 4000, "fim_s": 4001, "texto": "   "}]
    srt = transcricao.gerar_srt(blocos)
    assert srt.startswith("1\n00:00:00,500 --> 00:00:01,750\nEsse vestido\n\n2\n01:01:01,004 --> 01:01:02,500\n")
    assert srt.count("-->") == 2 and srt.endswith("\n")
    lido = transcricao.ler_srt(srt)
    assert lido == blocos[:2]
    crlf = "﻿" + srt.replace("\n", "\r\n")
    assert transcricao.ler_srt(crlf) == blocos[:2]
    assert transcricao.ler_srt("lixo\n\n") == []
