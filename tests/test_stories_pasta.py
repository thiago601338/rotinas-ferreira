"""A1 — preparar a pasta do dia (rotinas/stories/pasta.py)."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from PIL import Image, ImageOps

import sintetico
from rotinas import midia
from rotinas.contexto import Contexto
from rotinas.stories import pasta

DATA = "2026-09-22"
NOVOS_B = ["IMG_0001.MOV", "IMG_0002.JPG", "IMG_0003.JPG"]
NOVOS_C = ["IMG_0010.MOV", "IMG_0011.JPG", "IMG_0012.JPG"]


def hora(h, m, s=0):
    return datetime(2026, 9, 22, h, m, s)


def utc(local):
    """``creation_time`` do vídeo vai em UTC; a data de captura volta no fuso local."""
    return local.astimezone(timezone.utc).replace(tzinfo=None)


def retrato(pasta_):
    """rel → sha256 de tudo o que está na pasta do dia (inclui _originais)."""
    return {p.relative_to(pasta_).as_posix(): midia.hash_arquivo(p) for p in sorted(pasta_.rglob("*")) if p.is_file()}


def arquivos(m, letra):
    return [x["arquivo"] for x in m["letras"][letra]["midias"]]


def origens(m, letra):
    return [x["origem"] for x in m["letras"][letra]["midias"]]


@pytest.fixture
def dia(cfg):
    d = cfg.p.pasta_do_dia(DATA)
    d.mkdir(parents=True)
    return d


@pytest.fixture
def trabalho(cfg):
    return cfg.p.trabalho_stories / DATA


def cenario(dia):
    """Letra A já existente + dois modelos novos soltos na raiz (28 min de intervalo)."""
    sintetico.video(dia / "A - 1.mp4", audio="tom", criado_em=utc(hora(10, 0)))
    sintetico.foto(dia / "A - 2.jpg", cor=(10, 120, 10), tirada_em=hora(10, 1))
    # modelo 1: .MOV H.264 sem faixa de áudio + 2 fotos
    sintetico.video(dia / "IMG_0001.MOV", audio=None, criado_em=utc(hora(14, 0)))
    sintetico.foto(dia / "IMG_0002.JPG", cor=(30, 30, 200), tirada_em=hora(14, 1))
    sintetico.foto(dia / "IMG_0003.JPG", cor=(30, 30, 210), tirada_em=hora(14, 2))
    # modelo 2: .MOV com áudio em silêncio + 2 fotos
    sintetico.video(dia / "IMG_0010.MOV", audio="silencio", criado_em=utc(hora(14, 30)))
    sintetico.foto(dia / "IMG_0011.JPG", cor=(200, 30, 30), tirada_em=hora(14, 31))
    sintetico.foto(dia / "IMG_0012.JPG", cor=(210, 30, 30), tirada_em=hora(14, 32))


# ------------------------------------------------------------ letras

def test_sequencia_de_letras():
    assert [pasta.letra_do_indice(i) for i in (0, 1, 25, 26, 27, 51, 52, 701)] == ["A", "B", "Z", "AA", "AB", "AZ", "BA", "ZZ"]
    assert all(pasta.indice_letra(pasta.letra_do_indice(i)) == i for i in range(702))
    with pytest.raises(pasta.ErroPasta):
        pasta.letra_do_indice(702)


def test_depois_de_z_vem_aa(cfg, dia):
    sintetico.foto(dia / "Z - 1.jpg", tirada_em=hora(9, 0))
    sintetico.foto(dia / "foto nova.jpg", tirada_em=hora(9, 5))
    m = pasta.preparar(DATA)
    assert list(m["letras"]) == ["Z", "AA"]
    assert arquivos(m, "AA") == ["AA - 1.jpg"]


# ------------------------------------------------------------ fluxo principal

@pytest.mark.ffmpeg
def test_preparar_nomeia_converte_e_guarda_originais(cfg, dia, trabalho):
    cenario(dia)
    antes = retrato(dia)
    m = pasta.preparar(DATA)

    assert list(m["letras"]) == ["A", "B", "C"]
    assert [m["letras"][k]["nova"] for k in "ABC"] == [False, True, True]
    assert arquivos(m, "A") == ["A - 1.mp4", "A - 2.jpg"]
    assert arquivos(m, "B") == ["B - 1.mp4", "B - 2.jpg", "B - 3.jpg"]
    assert arquivos(m, "C") == ["C - 1.mp4", "C - 2.jpg", "C - 3.jpg"]
    assert origens(m, "B") == NOVOS_B and origens(m, "C") == NOVOS_C

    a1, b1, c1 = (m["letras"][k]["midias"][0] for k in "ABC")
    assert (a1["audio"], a1["precisa_musica"], a1["convertido"]) == ("com_audio", False, None)
    assert (b1["tipo"], b1["audio"], b1["precisa_musica"], b1["convertido"]) == ("video", "sem_audio", True, "remux")
    assert (c1["audio"], c1["precisa_musica"]) == ("silencioso", True)
    assert (b1["largura"], b1["altura"]) == (360, 640) and abs(b1["duracao_s"] - 2.0) < 0.2
    assert b1["capturado_em"] == "2026-09-22T14:00:00"
    b2 = m["letras"]["B"]["midias"][1]
    assert (b2["tipo"], b2["audio"], b2["precisa_musica"], b2["largura"], b2["altura"]) == ("foto", None, False, 600, 800)
    assert b2["capturado_em"] == "2026-09-22T14:01:00"

    # .MOV virou .mp4 H.264; foto é cópia idêntica
    assert midia.sondar(dia / "B - 1.mp4").codec_video == "h264"
    assert midia.hash_arquivo(dia / "B - 2.jpg") == antes["IMG_0002.JPG"]
    # originais guardados intactos; nada da letra A mudou
    for nome in NOVOS_B + NOVOS_C:
        assert not (dia / nome).exists()
        assert midia.hash_arquivo(dia / "_originais" / nome) == antes[nome]
    for nome in ("A - 1.mp4", "A - 2.jpg"):
        assert midia.hash_arquivo(dia / nome) == antes[nome]
    # hash e caminho do manifesto são os do arquivo final
    for info in m["letras"].values():
        for x in info["midias"]:
            assert x["hash"] == midia.hash_arquivo(Path(x["caminho"]))
            assert Path(x["caminho"]) == dia / x["arquivo"]

    assert "B - 1 é vídeo sem áudio: vai receber música do Instagram" in m["avisos"]
    assert any(a.startswith("C - 1 é vídeo com áudio em silêncio") for a in m["avisos"])
    assert not any(a.startswith("A - 1 ") for a in m["avisos"])

    # folhas de contato
    for k in "ABC":
        f = Path(m["letras"][k]["folha"])
        assert f == trabalho / "folhas" / f"{k}.jpg" and f.exists()
    with Image.open(trabalho / "folhas" / "B.jpg") as img:
        assert img.width > 600 and img.height > 500

    # manifesto gravado = devolvido
    assert m["simulado"] is False and m["data"] == DATA and m["pasta"] == str(dia)
    assert pasta.carregar_manifesto(DATA) == json.loads(json.dumps(m))


@pytest.mark.ffmpeg
def test_segunda_execucao_nao_muda_nada(cfg, dia):
    cenario(dia)
    m1 = pasta.preparar(DATA)
    depois = retrato(dia)
    m2 = pasta.preparar(DATA)
    assert retrato(dia) == depois
    assert list(m2["letras"]) == ["A", "B", "C"]
    assert not any(v["nova"] for v in m2["letras"].values())
    for k in "ABC":
        # nomes, origem e conversão ficam iguais (vêm do registro em _originais)
        campos = ("arquivo", "origem", "convertido", "hash", "audio", "capturado_em")
        assert [{c: x[c] for c in campos} for x in m2["letras"][k]["midias"]] == \
               [{c: x[c] for c in campos} for x in m1["letras"][k]["midias"]]


@pytest.mark.ffmpeg
def test_simular_nao_altera_a_pasta(cfg, dia, trabalho):
    cenario(dia)
    antes = retrato(dia)
    m = pasta.preparar(DATA, simular=True)
    assert retrato(dia) == antes
    assert m["simulado"] is True
    assert arquivos(m, "B") == ["B - 1.mp4", "B - 2.jpg", "B - 3.jpg"]
    assert arquivos(m, "C") == ["C - 1.mp4", "C - 2.jpg", "C - 3.jpg"]
    b1, b2 = m["letras"]["B"]["midias"][:2]
    assert not Path(b1["caminho"]).exists()
    assert (b1["convertido"], b1["audio"], b1["hash"]) == ("remux", "sem_audio", None)
    assert b2["hash"] == antes["IMG_0002.JPG"]  # cópia: o hash já é conhecido
    for k in "ABC":
        assert Path(m["letras"][k]["folha"]).exists()
    assert (trabalho / "manifesto-simulado.json").exists()
    assert not (trabalho / "manifesto.json").exists()
    with pytest.raises(pasta.ErroPasta, match="simulado"):
        pasta.carregar_manifesto(DATA)
    # a rodada real faz exatamente o que a simulação propôs
    real = pasta.preparar(DATA)
    for k in "ABC":
        assert arquivos(real, k) == arquivos(m, k) and origens(real, k) == origens(m, k)


# ------------------------------------------------------------ nunca sobrescrever

@pytest.mark.ffmpeg
def test_conflito_para_sem_alterar_nada(cfg, dia, monkeypatch):
    cenario(dia)
    antes = retrato(dia)
    planejar = pasta._planejar

    def aparece_arquivo(*a, **k):
        novas = planejar(*a, **k)
        (dia / "C - 2.jpg").write_bytes(b"arquivo do usuario")  # surgiu entre a leitura e a gravação
        return novas

    monkeypatch.setattr(pasta, "_planejar", aparece_arquivo)
    with pytest.raises(pasta.ErroPasta, match=r"C - 2\.jpg.*Nada foi alterado"):
        pasta.preparar(DATA)
    esperado = dict(antes, **{"C - 2.jpg": midia.hash_arquivo(dia / "C - 2.jpg")})
    assert retrato(dia) == esperado
    assert (dia / "C - 2.jpg").read_bytes() == b"arquivo do usuario"
    assert not (dia / "_originais").exists()


@pytest.mark.ffmpeg
def test_falha_no_meio_da_letra_desfaz_so_ela(cfg, dia, monkeypatch):
    cenario(dia)
    antes = retrato(dia)
    criar = pasta._criar_final

    def falha(origem, destino, operacao, c):
        if destino.name == "C - 3.jpg":
            raise OSError("disco cheio (simulado)")
        return criar(origem, destino, operacao, c)

    monkeypatch.setattr(pasta, "_criar_final", falha)
    with pytest.raises(pasta.ErroPasta, match="Nada foi alterado na letra C") as erro:
        pasta.preparar(DATA)
    assert erro.value.resultado_parcial == {"letras_prontas": ["B"], "falhou": "C"}
    assert [p.name for p in sorted(dia.glob("B - *"))] == ["B - 1.mp4", "B - 2.jpg", "B - 3.jpg"]
    assert not list(dia.glob("C - *"))
    for nome in NOVOS_C:
        assert midia.hash_arquivo(dia / nome) == antes[nome]

    monkeypatch.setattr(pasta, "_criar_final", criar)
    m = pasta.preparar(DATA)
    assert list(m["letras"]) == ["A", "B", "C"]
    assert (m["letras"]["B"]["nova"], m["letras"]["C"]["nova"]) == (False, True)
    assert origens(m, "C") == NOVOS_C


@pytest.mark.ffmpeg
def test_rodada_interrompida_e_retomada_sem_duplicar(cfg, dia, monkeypatch):
    cenario(dia)
    antes = retrato(dia)
    criar = pasta._criar_final

    def cai(origem, destino, operacao, c):
        if destino.name == "C - 2.jpg":
            raise KeyboardInterrupt  # processo morto no meio da letra
        return criar(origem, destino, operacao, c)

    monkeypatch.setattr(pasta, "_criar_final", cai)
    with pytest.raises(KeyboardInterrupt):
        pasta.preparar(DATA)
    assert (dia / "C - 1.mp4").exists() and (dia / "IMG_0010.MOV").exists()

    monkeypatch.setattr(pasta, "_criar_final", criar)
    m = pasta.preparar(DATA)
    assert list(m["letras"]) == ["A", "B", "C"]  # não virou letra D
    assert arquivos(m, "C") == ["C - 1.mp4", "C - 2.jpg", "C - 3.jpg"] and m["letras"]["C"]["nova"]
    assert origens(m, "C") == NOVOS_C
    for nome in NOVOS_C:
        assert midia.hash_arquivo(dia / "_originais" / nome) == antes[nome]


def test_original_aberto_no_windows_conclui_na_proxima(cfg, dia, monkeypatch):
    sintetico.foto(dia / "IMG_0002.JPG", tirada_em=hora(14, 1))
    sintetico.foto(dia / "IMG_0003.JPG", cor=(1, 2, 3), tirada_em=hora(14, 2))
    renomear = pasta._renomear_sem_sobrescrever

    def em_uso(origem, destino):
        if origem.name == "IMG_0002.JPG":
            raise PermissionError(13, "O arquivo já está sendo usado por outro processo")
        return renomear(origem, destino)

    monkeypatch.setattr(pasta, "_renomear_sem_sobrescrever", em_uso)
    m = pasta.preparar(DATA)
    assert arquivos(m, "A") == ["A - 1.jpg", "A - 2.jpg"]
    assert (dia / "IMG_0002.JPG").exists()
    assert any("IMG_0002.JPG" in a and "rode de novo" in a for a in m["avisos"])

    monkeypatch.setattr(pasta, "_renomear_sem_sobrescrever", renomear)
    m2 = pasta.preparar(DATA)
    assert list(m2["letras"]) == ["A"]  # não criou letra B com o mesmo arquivo
    assert not (dia / "IMG_0002.JPG").exists() and (dia / "_originais" / "IMG_0002.JPG").exists()


def test_original_com_mesmo_nome_em_originais_ganha_sufixo(cfg, dia):
    (dia / "_originais").mkdir()
    (dia / "_originais" / "IMG_0002.JPG").write_bytes(b"de outra rodada")
    sintetico.foto(dia / "IMG_0002.JPG", tirada_em=hora(14, 1))
    h = midia.hash_arquivo(dia / "IMG_0002.JPG")
    pasta.preparar(DATA)
    assert (dia / "_originais" / "IMG_0002.JPG").read_bytes() == b"de outra rodada"
    assert midia.hash_arquivo(dia / "_originais" / "IMG_0002 (2).JPG") == h
    assert midia.hash_arquivo(dia / "A - 1.jpg") == h


def test_original_devolvido_para_a_pasta_nao_vira_letra_nova(cfg, dia):
    sintetico.foto(dia / "IMG_0002.JPG", tirada_em=hora(14, 1))
    pasta.preparar(DATA)
    (dia / "_originais" / "IMG_0002.JPG").rename(dia / "IMG_0002.JPG")
    antes = retrato(dia)
    m = pasta.preparar(DATA)
    assert list(m["letras"]) == ["A"] and retrato(dia) == antes
    assert any("IMG_0002.JPG já tinha virado A - 1.jpg" in a for a in m["avisos"])


def test_desfazer_apaga_copia_somente_leitura(tmp_path, monkeypatch):
    """No Windows, unlink de arquivo somente leitura falha; copy2 herda esse atributo do original.
    Se a cópia ficasse para trás, a próxima rodada pararia para sempre em "já existe"."""
    import os
    import stat

    arq = tmp_path / "B - 2.jpg"
    arq.write_bytes(b"copia nossa")
    os.chmod(arq, stat.S_IREAD)
    unlink = Path.unlink

    def como_windows(self, missing_ok=False):
        if self.exists() and not os.stat(self).st_mode & stat.S_IWRITE:
            raise PermissionError(13, "Acesso negado", str(self))
        return unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", como_windows)
    pasta._remover_nosso(arq)
    assert not arq.exists()


# ------------------------------------------------------------ agrupamento

@pytest.mark.ffmpeg
def test_grupos_explicitos(cfg, dia):
    cenario(dia)
    grupos = [["IMG_0011.JPG", "IMG_0001.MOV"], ["img_0002.jpg", "IMG_0003.JPG", "IMG_0010.MOV", "IMG_0012.JPG"]]
    m = pasta.preparar(DATA, grupos=grupos)
    assert origens(m, "B") == ["IMG_0001.MOV", "IMG_0011.JPG"]  # vídeo primeiro
    assert origens(m, "C") == ["IMG_0010.MOV", "IMG_0002.JPG", "IMG_0003.JPG", "IMG_0012.JPG"]
    assert arquivos(m, "C") == ["C - 1.mp4", "C - 2.jpg", "C - 3.jpg", "C - 4.jpg"]
    assert (dia / "C - 4.jpg").exists() and (dia / "_originais" / "IMG_0012.JPG").exists()


def test_grupos_explicitos_rodando_de_novo_nao_da_erro(cfg, dia):
    """O mesmo pedido com grupos pode ser repetido (fila, retomada): o que já virou letra é pulado."""
    for i, nome in enumerate(["IMG_1.JPG", "IMG_2.JPG", "IMG_3.JPG"]):
        sintetico.foto(dia / nome, cor=(i * 40, 10, 10), tirada_em=hora(14, i))
    grupos = [["IMG_1.JPG", "IMG_3.JPG"], ["IMG_2.JPG"]]
    m1 = pasta.preparar(DATA, grupos=grupos)
    assert origens(m1, "A") == ["IMG_1.JPG", "IMG_3.JPG"] and origens(m1, "B") == ["IMG_2.JPG"]
    depois = retrato(dia)
    m2 = pasta.preparar(DATA, grupos=grupos)
    assert retrato(dia) == depois and list(m2["letras"]) == ["A", "B"]
    assert any("IMG_2.JPG já tinha virado B - 1.jpg" in a for a in m2["avisos"])
    # uma mídia nova no meio de grupos antigos entra numa letra nova, sem mexer nas prontas
    sintetico.foto(dia / "IMG_4.JPG", tirada_em=hora(15, 0))
    m3 = pasta.preparar(DATA, grupos=grupos + [["IMG_4.JPG"]])
    assert list(m3["letras"]) == ["A", "B", "C"] and origens(m3, "C") == ["IMG_4.JPG"]


def test_letra_em_minuscula_nao_vira_midia_nova_nem_e_reaproveitada(cfg, dia):
    # no Windows "b - 1.jpg" e "B - 1.jpg" são o mesmo arquivo: não pode renomear nem usar a letra B
    sintetico.foto(dia / "A - 1.jpg", tirada_em=hora(9, 0))
    sintetico.foto(dia / "b - 1.jpg", tirada_em=hora(9, 5))
    sintetico.foto(dia / "IMG_9.JPG", tirada_em=hora(10, 0))
    antes = midia.hash_arquivo(dia / "b - 1.jpg")
    m = pasta.preparar(DATA)
    assert list(m["letras"]) == ["A", "C"] and origens(m, "C") == ["IMG_9.JPG"]
    assert midia.hash_arquivo(dia / "b - 1.jpg") == antes
    assert not (dia / "_originais" / "b - 1.jpg").exists()
    assert any(a.startswith("b - 1.jpg ignorado: letra em minúscula") for a in m["avisos"])


def test_original_travado_ao_ler_para_sem_alterar_a_letra(cfg, dia, monkeypatch):
    sintetico.foto(dia / "IMG_1.JPG", tirada_em=hora(9, 0))
    sintetico.foto(dia / "IMG_2.JPG", cor=(1, 2, 3), tirada_em=hora(11, 0))  # outra letra (intervalo)
    antes = retrato(dia)
    ler = midia.hash_arquivo

    def travado(caminho, *a, **k):
        if Path(caminho).name == "IMG_2.JPG":
            raise PermissionError(13, "O arquivo já está sendo usado por outro processo", str(caminho))
        return ler(caminho, *a, **k)

    monkeypatch.setattr(midia, "hash_arquivo", travado)
    with pytest.raises(pasta.ErroPasta, match="não consegui ler IMG_2.JPG.*Nada foi alterado na letra B") as erro:
        pasta.preparar(DATA)
    assert erro.value.resultado_parcial == {"letras_prontas": ["A"], "falhou": "B"}
    monkeypatch.setattr(midia, "hash_arquivo", ler)
    assert (dia / "IMG_2.JPG").exists() and not (dia / "B - 1.jpg").exists()
    assert midia.hash_arquivo(dia / "IMG_2.JPG") == antes["IMG_2.JPG"]
    m = pasta.preparar(DATA)
    assert list(m["letras"]) == ["A", "B"] and origens(m, "B") == ["IMG_2.JPG"]


def test_grupos_explicitos_com_erro(cfg, dia):
    for i, nome in enumerate(["IMG_1.JPG", "IMG_2.JPG", "IMG_3.JPG"]):
        sintetico.foto(dia / nome, tirada_em=hora(14, i))
    antes = retrato(dia)
    casos = [
        ([["IMG_1.JPG", "IMG_2.JPG"]], "fora dos grupos: IMG_3.JPG"),
        ([["IMG_1.JPG"], ["IMG_2.JPG", "IMG_9.JPG", "IMG_3.JPG"]], "não encontrei 'IMG_9.JPG'"),
        ([["IMG_1.JPG", "IMG_2.JPG"], ["IMG_2.JPG", "IMG_3.JPG"]], "mais de um grupo"),
        ([["IMG_1.JPG"], "IMG_2.JPG"], "lista de listas"),
    ]
    for grupos, texto in casos:
        with pytest.raises(pasta.ErroPasta, match=texto):
            pasta.preparar(DATA, grupos=grupos)
    assert retrato(dia) == antes


@pytest.mark.ffmpeg
def test_subpastas_e_video_depois_de_foto(cfg, dia):
    # raiz, 1 minuto entre cada captura: o vídeo depois da foto abre uma letra nova
    sintetico.video(dia / "V1.mp4", audio="tom", criado_em=utc(hora(9, 0)))
    sintetico.foto(dia / "F1.jpg", tirada_em=hora(9, 1))
    sintetico.video(dia / "V2.mp4", audio="tom", criado_em=utc(hora(9, 2)))
    sintetico.foto(dia / "F2.jpg", tirada_em=hora(9, 3))
    # subpasta = uma letra; a foto foi tirada antes do vídeo, mas o vídeo vem primeiro
    sub = dia / "vestido azul"
    sintetico.foto(sub / "IMG_0100.JPG", tirada_em=hora(8, 0))
    sintetico.video(sub / "IMG_0101.MOV", audio="tom", criado_em=utc(hora(8, 5)))
    # subpasta com "_" é ignorada
    sintetico.foto(dia / "_rascunho" / "IMG_0900.JPG", tirada_em=hora(7, 0))

    m = pasta.preparar(DATA)
    assert list(m["letras"]) == ["A", "B", "C"]  # ordem: captura mais antiga de cada grupo
    assert origens(m, "A") == ["vestido azul/IMG_0101.MOV", "vestido azul/IMG_0100.JPG"]
    assert arquivos(m, "A") == ["A - 1.mp4", "A - 2.jpg"]
    assert origens(m, "B") == ["V1.mp4", "F1.jpg"]
    assert origens(m, "C") == ["V2.mp4", "F2.jpg"]
    assert (dia / "_originais" / "vestido azul" / "IMG_0100.JPG").exists()
    assert not sub.exists()  # ficou vazia
    assert (dia / "_rascunho" / "IMG_0900.JPG").exists()
    assert m["letras"]["A"]["midias"][0]["convertido"] == "remux"
    assert m["letras"]["B"]["midias"][0]["convertido"] is None  # .mp4 é só copiado


def test_intervalo_grande_abre_letra_nova(cfg, dia):
    sintetico.foto(dia / "a.jpg", tirada_em=hora(9, 0))
    sintetico.foto(dia / "b.jpg", tirada_em=hora(9, 10))  # 10 min: mesmo grupo
    sintetico.foto(dia / "c.jpg", tirada_em=hora(9, 21))  # 11 min: grupo novo
    m = pasta.preparar(DATA, simular=True)
    assert origens(m, "A") == ["a.jpg", "b.jpg"] and origens(m, "B") == ["c.jpg"]
    cfg.alterar("stories", agrupamento_intervalo_min=15)
    m = pasta.preparar(DATA, simular=True)
    assert origens(m, "A") == ["a.jpg", "b.jpg", "c.jpg"]


def test_aviso_de_letra_com_muitas_midias(cfg, dia):
    for i in range(3):
        sintetico.foto(dia / f"f{i}.jpg", tirada_em=hora(9, i))
    cfg.alterar("stories", max_midias_por_letra=2)
    m = pasta.preparar(DATA, simular=True)
    assert any(a.startswith("Letra A tem 3 mídias (máximo 2)") for a in m["avisos"])


# ------------------------------------------------------------ conversões

@pytest.mark.ffmpeg
def test_letra_existente_com_mov_vira_mp4(cfg, dia):
    sintetico.video(dia / "A - 1.mov", audio="tom", criado_em=utc(hora(10, 0)))
    sintetico.foto(dia / "A - 2.jpg", tirada_em=hora(10, 1))
    h = midia.hash_arquivo(dia / "A - 1.mov")
    m = pasta.preparar(DATA)
    assert arquivos(m, "A") == ["A - 1.mp4", "A - 2.jpg"] and m["letras"]["A"]["nova"] is False
    a1 = m["letras"]["A"]["midias"][0]
    assert (a1["origem"], a1["convertido"]) == ("A - 1.mov", "remux")
    assert not (dia / "A - 1.mov").exists()
    assert midia.hash_arquivo(dia / "_originais" / "A - 1.mov") == h
    depois = retrato(dia)
    m2 = pasta.preparar(DATA)
    assert retrato(dia) == depois and m2["letras"]["A"]["midias"][0]["origem"] == "A - 1.mov"


def test_heic_vira_jpg_com_exif(cfg, dia, monkeypatch):
    # sem pillow-heif na nuvem: um JPEG com extensão .HEIC e o leitor trocado
    def abrir(caminho):
        return ImageOps.exif_transpose(Image.open(caminho))

    monkeypatch.setattr(midia, "abrir_imagem", abrir)
    heic = sintetico.foto(dia / "tmp.jpg", tirada_em=hora(14, 0))
    heic = heic.rename(dia / "IMG_0300.HEIC")
    h = midia.hash_arquivo(heic)
    m = pasta.preparar(DATA)
    x = m["letras"]["A"]["midias"][0]
    assert (x["arquivo"], x["origem"], x["convertido"]) == ("A - 1.jpg", "IMG_0300.HEIC", "recodificado")
    assert midia.data_captura(dia / "A - 1.jpg") == hora(14, 0)
    with Image.open(dia / "A - 1.jpg") as img:
        assert img.format == "JPEG" and img.size == (600, 800)
        assert img.getexif().get_ifd(0x8769)[36867] == "2026:09:22 14:00:00"  # DateTimeOriginal preservado
    assert midia.hash_arquivo(dia / "_originais" / "IMG_0300.HEIC") == h


def test_heic_girado_sai_em_pe_sem_tag_de_orientacao(cfg, dia, monkeypatch):
    """Orientação aplicada nos pixels e tirada do EXIF: senão o JPEG gira duas vezes na galeria."""
    monkeypatch.setattr(midia, "abrir_imagem", lambda c: ImageOps.exif_transpose(Image.open(c)))
    img = Image.new("RGB", (800, 600), (200, 30, 30))
    exif = Image.Exif()
    exif[0x0112] = 6  # girar 90°
    exif.get_ifd(0x8769)[36867] = "2026:09:22 14:00:00"
    img.save(dia / "tmp.jpg", "JPEG", exif=exif.tobytes())
    (dia / "tmp.jpg").rename(dia / "IMG_0301.HEIC")
    pasta.preparar(DATA)
    with Image.open(dia / "A - 1.jpg") as saida:
        assert saida.size == (600, 800)
        assert saida.getexif().get(0x0112, 1) == 1
        assert saida.getexif().get_ifd(0x8769)[36867] == "2026:09:22 14:00:00"


# ------------------------------------------------------------ bordas, tarefa e linha de comando

def test_pasta_vazia_inexistente_e_data_invalida(cfg, dia):
    m = pasta.preparar(DATA)
    assert m["letras"] == {} and any("Nenhuma mídia" in a for a in m["avisos"])
    assert not (dia / "_originais").exists()
    with pytest.raises(pasta.ErroPasta, match="não encontrada"):
        pasta.preparar("2026-09-23")
    with pytest.raises(pasta.ErroPasta, match="Data inválida"):
        pasta.preparar("22/09/2026")


def test_ignora_temporarios_e_nao_midia(cfg, dia):
    sintetico.foto(dia / "IMG_1.jpg", tirada_em=hora(9, 0))
    (dia / "desktop.ini").write_text("x", encoding="utf-8")
    (dia / "B - 1.parcial.jpg").write_bytes(b"sobra")
    (dia / "~$lista.docx").write_bytes(b"x")
    m = pasta.preparar(DATA, simular=True)
    assert list(m["letras"]) == ["A"] and origens(m, "A") == ["IMG_1.jpg"]


def test_tarefa_e_cli(cfg, dia, tmp_path, capsys):
    sintetico.foto(dia / "IMG_1.jpg", tirada_em=hora(9, 0))
    sintetico.foto(dia / "IMG_2.jpg", tirada_em=hora(9, 1))
    r = pasta.tarefa({"data": DATA, "simular": True}, Contexto(tmp_path / "saida"))
    assert r["simulado"] and arquivos(r, "A") == ["A - 1.jpg", "A - 2.jpg"]
    with pytest.raises(pasta.ErroPasta):
        pasta.tarefa({}, Contexto(tmp_path / "saida"))

    assert pasta.cli(["--data", DATA, "--simular"]) == 0
    saida = capsys.readouterr().out
    assert "SIMULAÇÃO" in saida and "A - 1.jpg ← IMG_1.jpg" in saida

    grupos = tmp_path / "grupos.json"
    grupos.write_text(json.dumps([["IMG_2.jpg"], ["IMG_1.jpg"]]), encoding="utf-8")
    assert pasta.cli(["--data", DATA, "--grupos-arquivo", str(grupos), "--json"]) == 0
    m = json.loads(capsys.readouterr().out)
    assert origens(m, "A") == ["IMG_2.jpg"] and origens(m, "B") == ["IMG_1.jpg"]
    assert (dia / "B - 1.jpg").exists()

    assert pasta.cli(["--data", "2026-13-40"]) == 1
    assert "Data inválida" in capsys.readouterr().err
