"""B3: gerador de rascunho do CapCut sobre gabarito.

O gabarito usado aqui é o PROVISÓRIO (tests/dados/gabarito_provisorio/), montado a partir de um
rascunho gerado pelo pyCapCut 0.0.3 (formato do CapCut 6.7) com caminhos de Windows falsos, os 3
arquivos de linha do tempo (draft_info.json, draft_content.json, template-2.tmp), meta com
draft_materials ligado por local_material_id e 2 auxiliares sintéticos. Quando o gabarito real "0925"
chegar, trocar só esses arquivos.
"""

import copy
import hashlib
import json
import re
import shutil
from pathlib import Path

import pytest

import sintetico
from rotinas import midia
from rotinas.contexto import Contexto
from rotinas.video import capcut, rascunho

DADOS = Path(__file__).resolve().parent / "dados" / "gabarito_provisorio"
GABARITO = DADOS / "0925"
UUID_MAIUSCULO = re.compile(r"^[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}$")
DURACOES = {"video": 5.0, "audio": 8.0}


def _hash_pasta(pasta: Path) -> dict:
    return {p.relative_to(pasta).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(pasta.rglob("*")) if p.is_file()}


class Ambiente:
    def __init__(self, cfg, tmp_path):
        self.cfg = cfg
        self.rasc = cfg.p.capcut_rascunhos
        shutil.copy(DADOS / "root_meta_info.json", self.rasc / "root_meta_info.json")
        self.midia = tmp_path / "midia"
        self.midia.mkdir()
        self.video = self.midia / "IMG_0001.MOV"
        self.video2 = self.midia / "IMG 0002.mp4"
        self.musica = self.midia / "guia.mp3"
        for arq in (self.video, self.video2, self.musica):
            arq.write_bytes(b"falso" * 10)

    def plano(self, **mudancas) -> dict:
        p = {
            "projeto": "vestido-verde", "receita": "r02-provador-com-preco", "destino": "reels",
            "canvas": {"largura": 1080, "altura": 1920, "fps": 30}, "duracao_s": 4.3,
            "video": [
                {"arquivo": str(self.video), "tomada": "T03", "fonte_ini_s": 0.4, "fonte_fim_s": 1.4, "ini_s": 0.0,
                 "dur_s": 1.0, "velocidade": 1.0, "escala": 1.0, "papel": "gancho", "volume_db": 0.0},
                {"arquivo": str(self.video2), "tomada": "T05", "fonte_ini_s": 1 / 3, "ini_s": 1.0, "dur_s": 0.1 + 0.2,
                 "velocidade": 2.0, "escala": 1.2, "papel": "look", "volume_db": -6.0},
                {"arquivo": str(self.video), "tomada": "T04", "fonte_ini_s": 2.0, "ini_s": 1.3, "dur_s": 3.0,
                 "velocidade": 1.0, "papel": "preco", "volume_db": -120.0},
            ],
            "textos": [
                {"texto": "4 looks com 1 saia", "ini_s": 0.0, "dur_s": 2.0, "x": 540, "y": 520, "tamanho_px": 96,
                 "estilo": "gancho", "papel": "gancho"},
                {"texto": "R$229,99 · 3x de R$76,66 sem juros", "ini_s": 1.3, "dur_s": 3.0, "x": 500, "y": 1300,
                 "tamanho_px": 60, "estilo": "preco", "papel": "preco"},
            ],
            "legendas": [{"texto": "olha só esse vestido", "ini_s": 0.5, "dur_s": 1.2},
                         {"texto": "tem do P ao GG", "ini_s": 1.7, "dur_s": 1.4}],
            "audio": [{"arquivo": str(self.musica), "ini_s": 0.0, "dur_s": 4.3, "fonte_ini_s": 0.0, "volume_db": -18.0,
                       "papel": "musica"}],
            "transicoes": [{"entre": [0, 1], "tipo": "corte_seco", "dur_s": 0.0},
                           {"entre": [1, 2], "tipo": "zoom", "dur_s": 0.3}],
            "efeitos": [{"tecnica": 1, "nome": "Punch-in", "ini_s": 1.3, "dur_s": 0.2}],
            "avisos": [], "violacoes": [],
        }
        p.update(mudancas)
        return p

    def gerar(self, plano=None, nome="Vestido verde", gabarito=GABARITO, **kw):
        return rascunho.gerar_completo(plano or self.plano(), self.rasc, gabarito, nome, **kw)


def _info_falsa(caminho):
    caminho = Path(caminho)
    audio = caminho.suffix.lower() == ".mp3"
    return midia.InfoMidia(caminho=str(caminho), tipo="audio" if audio else "video",
                           largura=None if audio else 1080, altura=None if audio else 1920,
                           duracao_s=DURACOES["audio" if audio else "video"], fps=None if audio else 30.0,
                           tem_audio=True, tamanho_bytes=caminho.stat().st_size)


@pytest.fixture
def amb(cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(rascunho, "sondar_midia", _info_falsa)
    monkeypatch.setattr(capcut, "capcut_aberto", lambda: False)
    return Ambiente(cfg, tmp_path)


def _doc(pasta: Path, nome="draft_info.json") -> dict:
    return json.loads((pasta / nome).read_text(encoding="utf-8"))


def _segs(doc, tipo):
    return [s for f in doc["tracks"] if f["type"] == tipo for s in f["segments"]]


def _mat(doc, mid):
    return next(m for lista in doc["materials"].values() if isinstance(lista, list) for m in lista if m.get("id") == mid)


# ---------------------------------------------------------------- estrutura

def test_gera_estrutura_valida(amb):
    antes = _hash_pasta(GABARITO)
    r = amb.gerar()
    assert r.pasta == amb.rasc / "Vestido verde" and r.nome == "Vestido verde"
    arquivos = {p.relative_to(r.pasta).as_posix() for p in r.pasta.rglob("*") if p.is_file()}
    assert {"draft_info.json", "draft_content.json", "template-2.tmp", "draft_meta_info.json",
            "draft_agency_config.json", "common_attachment/attachment_script_video.json"} == arquivos
    doc = _doc(r.pasta)
    assert _doc(r.pasta, "draft_content.json") == doc == _doc(r.pasta, "template-2.tmp")
    gab = rascunho.carregar_gabarito(GABARITO)
    assert rascunho.validar(doc, gab, rascunho.prototipos(gab.doc)) == []
    assert set(gab.doc) <= set(doc) and set(gab.doc["materials"]) <= set(doc["materials"])
    assert doc["name"] == "Vestido verde"
    assert doc["canvas_config"]["width"] == 1080 and doc["canvas_config"]["height"] == 1920
    assert doc["canvas_config"]["ratio"] == "9:16"
    assert doc["fps"] == 30
    assert len(_segs(doc, "video")) == 3 and len(_segs(doc, "audio")) == 1 and len(_segs(doc, "text")) == 4
    assert [f["type"] for f in doc["tracks"]] == ["video", "audio", "text", "text", "text"]  # ordem do gabarito
    assert len(doc["materials"]["videos"]) == 2  # um material por arquivo
    assert _hash_pasta(GABARITO) == antes  # o gabarito nunca é alterado
    assert not list(amb.rasc.glob(".rotinas-tmp-*"))


def test_ids_unicos_e_novos(amb):
    r = amb.gerar()
    doc = _doc(r.pasta)
    ids = [m["id"] for lista in doc["materials"].values() for m in lista]
    ids += [f["id"] for f in doc["tracks"]] + [s["id"] for f in doc["tracks"] for s in f["segments"]]
    ids.append(doc["id"])
    assert len(ids) == len(set(ids))
    assert all(UUID_MAIUSCULO.match(i) for i in ids)
    antigos = set(re.findall(r'"id":"([^"]+)"', (GABARITO / "draft_info.json").read_text(encoding="utf-8")))
    assert not antigos & set(ids)
    for m in doc["materials"]["videos"]:
        assert m["material_id"] == m["id"]  # campo que repete o id (pyCapCut) acompanha o id novo


def test_tempos_em_microssegundos(amb):
    plano = amb.plano()
    r = amb.gerar(plano)
    doc = _doc(r.pasta)
    videos = sorted(_segs(doc, "video"), key=lambda s: s["target_timerange"]["start"])
    for item, s in zip(plano["video"], videos, strict=True):
        alvo, fonte = s["target_timerange"], s["source_timerange"]
        assert alvo["start"] == round(item["ini_s"] * 1_000_000)
        assert alvo["start"] + alvo["duration"] == round((item["ini_s"] + item["dur_s"]) * 1_000_000)
        assert fonte["start"] == round(item["fonte_ini_s"] * 1_000_000)
        assert fonte["duration"] == round(alvo["duration"] * item["velocidade"])
        assert s["speed"] == item["velocidade"]
        velocidade = _mat(doc, s["extra_material_refs"][0])
        assert velocidade["type"] == "speed" and velocidade["speed"] == item["velocidade"]
        for v in (*alvo.values(), *fonte.values()):
            assert isinstance(v, int)
    assert videos[1]["source_timerange"] == {"start": 333_333, "duration": 600_000}
    assert doc["duration"] == 4_300_000
    assert _mat(doc, videos[0]["material_id"])["duration"] == 5_000_000  # duração do arquivo, não do trecho
    musica = _segs(doc, "audio")[0]
    assert _mat(doc, musica["material_id"])["duration"] == 8_000_000


def test_texto_na_zona_segura_convertida(amb):
    # Retângulo seguro (x 80–920, y 280–1400) nos quatro cantos, no centro e no meio de cada borda.
    pontos = [(80, 280), (920, 280), (80, 1400), (920, 1400), (540, 960), (540, 280), (540, 1400)]
    textos = [{"texto": f"T{i}", "ini_s": float(i), "dur_s": 1.0, "x": x, "y": y, "tamanho_px": 60}
              for i, (x, y) in enumerate(pontos)]
    r = amb.gerar(amb.plano(textos=textos, legendas=[], video=amb.plano()["video"][:1]))
    doc = _doc(r.pasta)
    por_texto = {json.loads(_mat(doc, s["material_id"])["content"])["text"]: s for s in _segs(doc, "text")}
    x_min, x_max = (80 - 540) / 540, (920 - 540) / 540
    y_min, y_max = (960 - 1400) / 960, (960 - 280) / 960
    for i, (x, y) in enumerate(pontos):
        t = por_texto[f"T{i}"]["clip"]["transform"]
        assert x_min - 1e-6 <= t["x"] <= x_max + 1e-6 and y_min - 1e-6 <= t["y"] <= y_max + 1e-6
        assert t["x"] * 540 + 540 == pytest.approx(x, abs=0.01)  # volta aos pixels
        assert 960 - t["y"] * 960 == pytest.approx(y, abs=0.01)
    assert por_texto["T5"]["clip"]["transform"]["y"] > 0  # y do CapCut cresce para cima
    assert por_texto["T6"]["clip"]["transform"]["y"] < 0


def test_conteudo_e_estilo_do_texto(amb):
    r = amb.gerar(amb.plano(textos=[{"texto": "Vestido 👗 verde", "ini_s": 0, "dur_s": 2, "x": 540, "y": 520,
                                      "tamanho_px": 96, "estilo": "gancho"}]))
    doc = _doc(r.pasta)
    gancho = next(m for m in doc["materials"]["texts"] if "Vestido" in m["content"])
    conteudo = json.loads(gancho["content"])
    assert conteudo["text"] == "Vestido 👗 verde"
    estilo = conteudo["styles"][0]
    assert len(conteudo["styles"]) == 1 and estilo["range"] == [0, 16]
    assert estilo["size"] == pytest.approx(96 / 3.0)
    assert estilo["bold"] is True
    assert estilo["fill"]["content"]["solid"]["color"] == [1.0, 1.0, 1.0]
    assert estilo["strokes"][0]["content"]["solid"]["color"] == [0.0, 0.0, 0.0]
    assert gancho["check_flag"] & 8
    legendas = [f for f in doc["tracks"] if f["type"] == "text" and f["name"].startswith("legendas")]
    assert legendas and len(legendas[0]["segments"]) == 2
    assert legendas[0]["segments"][0]["clip"]["transform"]["y"] == pytest.approx((960 - 1100) / 960, abs=1e-6)


def test_canvas_do_feed_converte_posicao_pela_altura_dele(amb):
    r = amb.gerar(amb.plano(canvas={"largura": 1080, "altura": 1350, "fps": 30}, legendas=[],
                            textos=[{"texto": "Feed", "ini_s": 0, "dur_s": 2, "x": 540, "y": 400, "tamanho_px": 96}]))
    doc = _doc(r.pasta)
    assert (doc["canvas_config"]["width"], doc["canvas_config"]["height"], doc["canvas_config"]["ratio"]) == \
        (1080, 1350, "4:5")
    t = _segs(doc, "text")[0]["clip"]["transform"]
    assert t["y"] == pytest.approx((675 - 400) / 675, abs=1e-6)


def test_textos_sobrepostos_vao_para_faixas_diferentes(amb):
    textos = [{"texto": "A", "ini_s": 0, "dur_s": 2, "x": 540, "y": 500, "tamanho_px": 80},
              {"texto": "B", "ini_s": 1, "dur_s": 2, "x": 540, "y": 700, "tamanho_px": 80},
              {"texto": "C", "ini_s": 2, "dur_s": 1, "x": 540, "y": 900, "tamanho_px": 80}]
    r = amb.gerar(amb.plano(textos=textos, legendas=[]))
    doc = _doc(r.pasta)
    faixas = [f for f in doc["tracks"] if f["type"] == "text"]
    assert [len(f["segments"]) for f in faixas] == [2, 1]
    assert faixas[1]["segments"][0]["render_index"] == faixas[0]["segments"][0]["render_index"] + 1


def test_volume_db_para_linear(amb):
    r = amb.gerar()
    doc = _doc(r.pasta)
    videos = sorted(_segs(doc, "video"), key=lambda s: s["target_timerange"]["start"])
    assert videos[0]["volume"] == 1.0
    assert videos[1]["volume"] == pytest.approx(0.501187, abs=1e-6)
    assert videos[2]["volume"] == pytest.approx(1e-6, abs=1e-7)
    assert _segs(doc, "audio")[0]["volume"] == pytest.approx(0.125893, abs=1e-6)
    assert videos[1]["clip"]["scale"] == {"x": 1.2, "y": 1.2}


def test_materiais_de_midia_locais_e_ligados_ao_meta(amb):
    r = amb.gerar()
    doc, meta = _doc(r.pasta), _doc(r.pasta, "draft_meta_info.json")
    video = next(m for m in doc["materials"]["videos"] if m["material_name"] == "IMG_0001.MOV")
    assert video["path"] == str(amb.video).replace("\\", "/")
    assert (video["width"], video["height"], video["type"], video["category_name"]) == (1080, 1920, "video", "local")
    audio = doc["materials"]["audios"][0]
    assert audio["type"] == "extract_music" and audio["name"] == "guia.mp3"
    registrados = {e["id"]: e for g in meta["draft_materials"] for e in g["value"]}
    assert len(registrados) == 3
    for m in doc["materials"]["videos"] + doc["materials"]["audios"]:
        e = registrados[m["local_material_id"]]
        assert e["file_Path"] == m["path"] and e["duration"] == m["duration"]
    assert registrados[audio["local_material_id"]]["metetype"] == "music"
    assert meta["draft_name"] == "Vestido verde"
    assert meta["draft_fold_path"] == str(r.pasta).replace("\\", "/")
    assert meta["tm_duration"] == doc["duration"]
    assert meta["tm_draft_create"] > 1e15 and meta["draft_cover"] == ""
    assert meta["draft_id"] != "5A1F0C2E-7B3D-4E9A-8C6B-1D2E3F4A5B6C"


def test_auxiliares_clonados_sem_midia_e_com_ids_trocados(amb, tmp_path):
    gab = tmp_path / "gab" / "0925"
    shutil.copytree(GABARITO, gab)
    (gab / "Resources").mkdir()
    (gab / "Resources" / "clipe_biblioteca.mp4").write_bytes(b"video")
    (gab / "draft_cover.jpg").write_bytes(b"jpg")
    (gab / ".locked").write_text("", encoding="utf-8")
    (gab / "draft_info.json.bak").write_text("{}", encoding="utf-8")
    r = amb.gerar(gabarito=gab)
    arquivos = {p.relative_to(r.pasta).as_posix() for p in r.pasta.rglob("*") if p.is_file()}
    assert not {"Resources/clipe_biblioteca.mp4", "draft_cover.jpg", ".locked", "draft_info.json.bak"} & arquivos
    anexo = json.loads((r.pasta / "common_attachment" / "attachment_script_video.json").read_text(encoding="utf-8"))
    meta = _doc(r.pasta, "draft_meta_info.json")
    assert anexo["draft_id"] == meta["draft_id"]
    assert anexo["timeline_id"] == _doc(r.pasta)["id"]
    assert anexo["draft_fold_path"] == meta["draft_fold_path"]
    assert any("Mídia do gabarito não copiada" in a for a in r.avisos)


def test_caminho_novo_que_comeca_com_o_do_gabarito(amb, tmp_path):
    # No PC o gabarito fica na mesma pasta de rascunhos: ".../0925" é prefixo de ".../0925 teste".
    gab = tmp_path / "gab" / "Vestido"
    shutil.copytree(GABARITO, gab)
    antigo = str(amb.rasc / "Vestido").replace("\\", "/")
    meta = json.loads((gab / "draft_meta_info.json").read_text(encoding="utf-8"))
    meta["draft_fold_path"] = antigo
    (gab / "draft_meta_info.json").write_text(json.dumps(meta), encoding="utf-8")
    anexo = gab / "common_attachment" / "attachment_script_video.json"
    anexo.write_text(json.dumps({"draft_fold_path": antigo, "arquivo": antigo + "/x.json"}), encoding="utf-8")
    r = amb.gerar(gabarito=gab, nome="Vestido verde")
    novo = str(r.pasta).replace("\\", "/")
    assert _doc(r.pasta, "draft_meta_info.json")["draft_fold_path"] == novo
    copiado = json.loads((r.pasta / "common_attachment" / "attachment_script_video.json").read_text(encoding="utf-8"))
    assert copiado == {"draft_fold_path": novo, "arquivo": novo + "/x.json"}


# ---------------------------------------------------------------- segurança

def test_backup_feito_antes_de_gravar(amb, monkeypatch):
    indice_antes = (amb.rasc / "root_meta_info.json").read_text(encoding="utf-8")
    original = capcut.backup
    chamadas = []

    def espiao(pasta, projetos=None, base=None):
        chamadas.append((pasta / "Vestido verde").exists())
        return original(pasta, projetos, base)

    monkeypatch.setattr(capcut, "backup", espiao)
    r = amb.gerar()
    assert chamadas == [False]  # o projeto ainda não existia quando o backup rodou
    assert r.backup and (r.backup / "root_meta_info.json").read_text(encoding="utf-8") == indice_antes
    assert (amb.rasc / "root_meta_info.json").read_text(encoding="utf-8") != indice_antes


def test_recusa_com_capcut_aberto(amb, monkeypatch):
    monkeypatch.setattr(capcut, "capcut_aberto", lambda: True)
    antes = _hash_pasta(amb.rasc)
    with pytest.raises(capcut.CapCutAberto):
        amb.gerar()
    assert _hash_pasta(amb.rasc) == antes
    assert not (amb.cfg.p.backups / "capcut").exists()


def test_recusa_gabarito_criptografado(amb, tmp_path):
    gab = tmp_path / "gab" / "0925"
    shutil.copytree(GABARITO, gab)
    (gab / "draft_info.json").write_bytes(b"\x02\x9f\x11\x8a" + bytes(range(200)))
    antes = _hash_pasta(amb.rasc)
    with pytest.raises(capcut.GabaritoCriptografado):
        amb.gerar(gabarito=gab)
    assert _hash_pasta(amb.rasc) == antes


def test_nome_repetido_vira_2(amb):
    r1 = amb.gerar()
    antes = _hash_pasta(r1.pasta)
    r2 = amb.gerar()
    r3 = amb.gerar()
    assert (r2.nome, r3.nome) == ("Vestido verde (2)", "Vestido verde (3)")
    assert _hash_pasta(r1.pasta) == antes  # o primeiro não foi tocado
    assert r2.backup and (r2.backup / "projetos" / "Vestido verde" / "draft_info.json").exists()
    indice = json.loads((amb.rasc / "root_meta_info.json").read_text(encoding="utf-8"))
    nomes = [e["draft_name"] for e in indice["all_draft_store"]]
    assert nomes == ["0925", "Vestido verde", "Vestido verde (2)", "Vestido verde (3)"]


def test_capcut_aberto_depois_da_validacao_nao_grava_projeto(amb, monkeypatch):
    # O usuário abre o CapCut enquanto o rascunho é montado: a 2ª conferência (logo antes de gravar) recusa.
    respostas = iter([False, True])
    monkeypatch.setattr(capcut, "capcut_aberto", lambda: next(respostas))
    indice_antes = (amb.rasc / "root_meta_info.json").read_bytes()
    with pytest.raises(capcut.CapCutAberto):
        amb.gerar()
    assert not (amb.rasc / "Vestido verde").exists() and not list(amb.rasc.glob(".rotinas-tmp-*"))
    assert (amb.rasc / "root_meta_info.json").read_bytes() == indice_antes


def test_recusa_pasta_de_rascunhos_inexistente(amb, tmp_path):
    # Config errada: gravar numa pasta que o CapCut não lê seria "sumir" com o rascunho.
    errada = tmp_path / "CapCut" / "outra" / "com.lveditor.draft"
    with pytest.raises(rascunho.ErroRascunho, match="não existe"):
        rascunho.gerar_completo(amb.plano(), errada, GABARITO, "X")
    assert not errada.exists() and not (tmp_path / "CapCut" / "outra").exists()


def test_nada_gravado_se_a_validacao_falhar(amb, monkeypatch):
    antes = _hash_pasta(amb.rasc)
    monkeypatch.setattr(rascunho, "validar", lambda *a, **k: ["erro de propósito"])
    with pytest.raises(rascunho.ErroValidacao) as e:
        amb.gerar()
    assert e.value.erros == ["erro de propósito"] and e.value.resultado_parcial["erros_validacao"]
    assert _hash_pasta(amb.rasc) == antes
    assert not (amb.cfg.p.backups / "capcut").exists()
    assert not (amb.cfg.p.videos / "trabalho" / "vestido-verde" / "relatorio_rascunho.txt").exists()


def test_validacao_pega_trecho_depois_do_fim_do_arquivo(amb):
    plano = amb.plano()
    plano["video"][2]["fonte_ini_s"] = 4.0  # 4 s + 3 s num arquivo de 5 s
    antes = _hash_pasta(amb.rasc)
    with pytest.raises(rascunho.ErroValidacao) as e:
        amb.gerar(plano)
    assert any("passa do fim do arquivo" in x for x in e.value.erros)
    assert _hash_pasta(amb.rasc) == antes


def test_validacao_pega_midia_ausente_e_campo_faltando(amb):
    with pytest.raises(rascunho.ErroValidacao) as e:
        amb.gerar(amb.plano(audio=[{"arquivo": str(amb.midia / "sumiu.mp3"), "ini_s": 0, "dur_s": 1}]))
    assert "não existe" in e.value.erros[0]
    with pytest.raises(rascunho.ErroValidacao):
        amb.gerar(amb.plano(textos=[{"texto": "sem tempo"}]))


def test_validar_detecta_problemas_no_documento(amb):
    r = amb.gerar()
    gab = rascunho.carregar_gabarito(GABARITO)
    protos = rascunho.prototipos(gab.doc)
    doc = _doc(r.pasta)
    ruim = copy.deepcopy(doc)
    video = next(f for f in ruim["tracks"] if f["type"] == "video")
    video["segments"][1]["target_timerange"]["start"] = 500_000  # sobrepõe o primeiro
    video["segments"][0]["extra_material_refs"].append("NAO-EXISTE")
    video["segments"][2]["target_timerange"]["duration"] = 1.5
    del ruim["materials"]["videos"][0]["crop"]
    ruim["tracks"][-1]["segments"][0]["id"] = ruim["tracks"][0]["segments"][0]["id"]
    erros = " | ".join(rascunho.validar(ruim, gab, protos))
    for trecho in ("sobrepostos", "material inexistente", "inteiros em µs", "falta a chave 'crop'", "id repetido"):
        assert trecho in erros
    # Segmento de texto apontando para o material de um vídeo (existe, mas é do tipo errado).
    trocado = copy.deepcopy(doc)
    texto = next(f for f in trocado["tracks"] if f["type"] == "text")
    texto["segments"][0]["material_id"] = trocado["materials"]["videos"][0]["id"]
    assert any("aponta para material de 'videos'" in e for e in rascunho.validar(trocado, gab, protos))
    assert rascunho.validar(doc, gab, protos) == []


def test_registra_no_indice_clonando_entrada(amb):
    r = amb.gerar()
    indice = json.loads((amb.rasc / "root_meta_info.json").read_text(encoding="utf-8"))
    original, nova = indice["all_draft_store"]
    assert original["draft_name"] == "0925"
    assert set(original) <= set(nova)
    meta = _doc(r.pasta, "draft_meta_info.json")
    assert nova["draft_id"] == meta["draft_id"] and nova["draft_name"] == "Vestido verde"
    assert nova["draft_fold_path"] == meta["draft_fold_path"]
    assert nova["draft_json_file"].endswith("/draft_info.json")
    assert nova["tm_duration"] == 4_300_000
    assert indice["draft_ids"] == 2
    assert r.indice.startswith("registrado")
    assert nova["tm_draft_create"] > 1e15  # µs, como a entrada que foi clonada


def test_draft_ids_nunca_diminui(amb):
    # Se draft_ids for um contador que só cresce (projetos apagados continuam contados), não pode voltar.
    arq = amb.rasc / "root_meta_info.json"
    indice = json.loads(arq.read_text(encoding="utf-8"))
    indice["draft_ids"] = 57
    arq.write_text(json.dumps(indice), encoding="utf-8")
    amb.gerar()
    assert json.loads(arq.read_text(encoding="utf-8"))["draft_ids"] == 58


def test_carimbos_na_unidade_do_gabarito(amb, tmp_path):
    gab = tmp_path / "gab" / "0925"
    shutil.copytree(GABARITO, gab)
    meta = json.loads((gab / "draft_meta_info.json").read_text(encoding="utf-8"))
    meta["tm_draft_create"] = meta["tm_draft_modified"] = 1_790_000_000  # segundos
    (gab / "draft_meta_info.json").write_text(json.dumps(meta), encoding="utf-8")
    r = amb.gerar(gabarito=gab)
    gerado = _doc(r.pasta, "draft_meta_info.json")
    assert 1e9 < gerado["tm_draft_create"] < 1e10 and gerado["tm_draft_modified"] == gerado["tm_draft_create"]


def test_sem_indice_no_modo_auto_nao_cria(amb):
    (amb.rasc / "root_meta_info.json").unlink()
    r = amb.gerar()
    assert not (amb.rasc / "root_meta_info.json").exists()
    assert r.indice.startswith("não registrado")


def test_relatorio_lista_o_que_fica_manual(amb):
    r = amb.gerar()
    texto = (amb.cfg.p.videos / "trabalho" / "vestido-verde" / "relatorio_rascunho.txt").read_text(encoding="utf-8")
    assert r.relatorio_texto == texto
    assert "Transição 'zoom' entre os blocos 2 e 3" in texto
    assert "corte_seco" not in texto
    assert "Punch-in" not in texto  # o rascunho já aplica pela escala do clipe (achado #12)
    assert "mídia perdida" in texto and "Vestido verde" in texto


def test_manual_e_o_acabamento_completo(amb):
    # Achado #12: 'manual' tem que ser a lista completa do acabamento (composição, cor, faixa-guia, loop,
    # legendas) + transições + protótipos omitidos, sem os efeitos que o rascunho já aplicou (punch-in).
    acabamento = [
        "#39 Clone em 1,30–4,30 s (como fazer: guia §4.2).",
        "look: máscara Linear ou Retângulo com a borda numa área calma, pena 10–20 (#39).",
        "Cor: look quente (§6), filtros até 40%; comparar a cor da peça com a peça real e manter um plano com a cor real.",
        "Faixa-guia: desligar (V) antes de exportar; a música entra pelo Instagram (§7).",
        "Loop (#13): conferir se o último quadro emenda no primeiro.",
        "Revisar as legendas: acentos, nome da peça, preço, tamanhos e cor exata (§5).",
    ]
    efeitos = [
        {"tecnica": 1, "nome": "Punch-in (zoom seco)", "ini_s": 1.0, "dur_s": 0.3, "manual": False, "categoria": "apoio"},
        {"tecnica": 1, "nome": "Punch-in (zoom seco)", "ini_s": 2.0, "dur_s": 0.3, "manual": False, "categoria": "apoio"},
        {"tecnica": 14, "nome": "Corte na batida", "ini_s": 0.0, "dur_s": 1.0, "manual": False, "categoria": "corte"},
        {"tecnica": 31, "nome": "Flash / strobe", "ini_s": 1.3, "dur_s": 0.07, "manual": False, "categoria": "apoio"},
        {"tecnica": 31, "nome": "Flash / strobe", "ini_s": 1.3, "dur_s": 0.07, "manual": False, "categoria": "apoio"},
        {"tecnica": 39, "nome": "Clone", "ini_s": 1.3, "dur_s": 3.0, "manual": True, "categoria": "assinatura"},
        {"tecnica": 57, "nome": "Efeitos sonoros", "som": "whoosh", "ini_s": 1.0, "dur_s": 0.5, "manual": False,
         "categoria": "som", "parametros": {"arquivo": str(amb.musica)}},
        {"tecnica": 57, "nome": "Efeitos sonoros", "som": "pop", "ini_s": 2.0, "dur_s": 0.5, "manual": True,
         "categoria": "som", "parametros": {"arquivo": None}},
    ]
    r = amb.gerar(amb.plano(efeitos=efeitos, acabamento=acabamento))
    manual = r.manual
    for linha in acabamento:
        assert manual.count(linha) == 1, linha
    assert not [x for x in manual if "Punch-in" in x or "Corte na batida" in x or "whoosh" in x]
    assert [x for x in manual if "Flash / strobe" in x] == [
        "Efeito 31 'Flash / strobe' em 1,30–1,37 s: fazer à mão (edicao-video-capcut.md §4.2)."]
    assert sum("Clone" in x for x in manual) == 1  # vem do acabamento, sem repetir
    assert any("Transição 'zoom'" in x for x in manual)
    assert "Faixa-guia: desligar (V)" in r.relatorio_texto and "Cor: look quente" in r.relatorio_texto


# ---------------------------------------------------------------- variações de gabarito

def test_gabarito_sem_audio_usa_reserva(amb, tmp_path):
    gab = tmp_path / "gab" / "0925"
    shutil.copytree(GABARITO, gab)
    for nome in ("draft_info.json", "draft_content.json", "template-2.tmp"):
        doc = json.loads((gab / nome).read_text(encoding="utf-8"))
        doc["tracks"] = [f for f in doc["tracks"] if f["type"] != "audio"]
        doc["materials"]["audios"] = []
        (gab / nome).write_text(json.dumps(doc), encoding="utf-8")
    r = amb.gerar(gabarito=gab)
    doc = _doc(r.pasta)
    assert len(_segs(doc, "audio")) == 1 and doc["materials"]["audios"][0]["type"] == "extract_music"
    assert any("protótipo de reserva" in a for a in r.avisos)
    assert "protótipo de reserva" in r.relatorio_texto


def test_envelope_no_template_2(amb, tmp_path):
    gab = tmp_path / "gab" / "0925"
    shutil.copytree(GABARITO, gab)
    interno = (gab / "template-2.tmp").read_text(encoding="utf-8")
    (gab / "template-2.tmp").write_text(json.dumps({"versao": 7, "draft": interno}), encoding="utf-8")
    r = amb.gerar(gabarito=gab)
    envelope = json.loads((r.pasta / "template-2.tmp").read_text(encoding="utf-8"))
    assert envelope["versao"] == 7
    assert json.loads(envelope["draft"]) == _doc(r.pasta)


def test_timelines_espelhar(amb, tmp_path):
    amb.cfg.alterar("capcut", timelines="espelhar")
    gab = tmp_path / "gab" / "0925"
    shutil.copytree(GABARITO, gab)
    antigo = json.loads((gab / "draft_info.json").read_text(encoding="utf-8"))["id"]
    (gab / "Timelines" / antigo).mkdir(parents=True)
    shutil.copy(gab / "draft_info.json", gab / "Timelines" / antigo / "draft_info.json")
    (gab / "Timelines" / "project.json").write_text(json.dumps({"id": antigo, "main_timeline_id": antigo,
                                                                "timelines": [{"id": antigo}]}), encoding="utf-8")
    r = amb.gerar(gabarito=gab)
    novo = _doc(r.pasta)["id"]
    projeto = json.loads((r.pasta / "Timelines" / "project.json").read_text(encoding="utf-8"))
    assert projeto["main_timeline_id"] == novo and projeto["timelines"][0]["id"] == novo
    assert _doc(r.pasta / "Timelines" / novo) == _doc(r.pasta)
    assert not (r.pasta / "Timelines" / antigo).exists()


def test_timelines_omitidas_quando_configurado(amb, tmp_path, cfg):
    cfg.alterar("capcut", timelines="omitir")  # padrão agora é espelhar (como no 0925 real da 9.5)
    gab = tmp_path / "gab" / "0925"
    shutil.copytree(GABARITO, gab)
    (gab / "Timelines" / "X").mkdir(parents=True)
    (gab / "Timelines" / "project.json").write_text("{}", encoding="utf-8")
    r = amb.gerar(gabarito=gab)
    assert not (r.pasta / "Timelines").exists()


def test_prototipo_da_biblioteca_tem_origem_limpa(amb, tmp_path):
    gab = tmp_path / "gab" / "0925"
    shutil.copytree(GABARITO, gab)
    for nome in ("draft_info.json", "draft_content.json", "template-2.tmp"):
        doc = json.loads((gab / nome).read_text(encoding="utf-8"))
        v = doc["materials"]["videos"][0]
        v.update({"category_name": "stock", "category_id": "123", "resource_id": "7000", "material_url": "https://x"})
        (gab / nome).write_text(json.dumps(doc), encoding="utf-8")
    r = amb.gerar(gabarito=gab)
    for m in _doc(r.pasta)["materials"]["videos"]:
        assert (m["category_name"], m["category_id"], m["resource_id"], m["material_url"]) == ("local", "", "", "")


def test_prototipo_local_nao_carrega_arquivos_derivados_nem_reverso(amb, tmp_path):
    # Gabarito com o clipe invertido e estabilizado: os arquivos derivados são do vídeo do GABARITO.
    gab = tmp_path / "gab" / "0925"
    shutil.copytree(GABARITO, gab)
    for nome in ("draft_info.json", "draft_content.json", "template-2.tmp"):
        doc = json.loads((gab / nome).read_text(encoding="utf-8"))
        v = doc["materials"]["videos"][0]
        v.update({"reverse_path": "C:/gab/rev.mp4", "intensifies_path": "C:/gab/int.mp4",
                  "stable": {"matrix_path": "C:/gab/m.dat", "stable_level": 1}})
        for f in doc["tracks"]:
            if f["type"] == "video":
                f["segments"][0]["reverse"] = True
        (gab / nome).write_text(json.dumps(doc), encoding="utf-8")
    r = amb.gerar(gabarito=gab)
    doc = _doc(r.pasta)
    assert all(s["reverse"] is False for s in _segs(doc, "video"))
    for m in doc["materials"]["videos"]:
        assert (m["reverse_path"], m["intensifies_path"], m["stable"]["matrix_path"]) == ("", "", "")
        assert m["path"].endswith((".MOV", ".mp4"))  # o caminho do próprio material fica


def test_auxiliar_com_caminho_de_barra_invertida(amb, tmp_path):
    # No texto cru do JSON, "C:\Users\..." aparece escapado ("C:\\Users\\..."): a troca tem que pegar.
    gab = tmp_path / "gab" / "0925"
    shutil.copytree(GABARITO, gab)
    antigo = json.loads((gab / "draft_meta_info.json").read_text(encoding="utf-8"))["draft_fold_path"]
    anexo = gab / "common_attachment" / "attachment_script_video.json"
    anexo.write_text(json.dumps({"p": antigo.replace("/", "\\"), "q": antigo}), encoding="utf-8")
    r = amb.gerar(gabarito=gab)
    copiado = json.loads((r.pasta / "common_attachment" / "attachment_script_video.json").read_text(encoding="utf-8"))
    novo = str(r.pasta).replace("\\", "/")
    assert copiado == {"p": novo.replace("/", "\\"), "q": novo}


def test_video_sobreposto_vai_para_outra_faixa_com_aviso(amb):
    plano = amb.plano()
    plano["video"][1]["ini_s"] = 0.5  # começa antes do fim do primeiro (1,0 s)
    r = amb.gerar(plano)
    faixas = [f for f in _doc(r.pasta)["tracks"] if f["type"] == "video"]
    assert len(faixas) == 2
    assert any("se sobrepõem" in a for a in r.avisos)


def test_inspecionar_gabarito(amb):
    d = rascunho.inspecionar(GABARITO)
    assert d["principal"] == "draft_info.json" and d["versao"] == "6.7.0"
    assert set(d["prototipos"]) == {"video", "audio", "text"} and d["faltam"] == []
    assert d["arquivos"]["template-2.tmp"] == "json"
    assert d["draft_materials"]["0"] == 2


def test_localizar_gabarito(amb, tmp_path):
    raiz = tmp_path / "repo"
    with pytest.raises(rascunho.ErroRascunho, match="não está nos rascunhos do CapCut") as erro:
        rascunho.localizar_gabarito(raiz=raiz)
    # achado #13: não mandar copiar pasta (as cópias do diagnóstico já são procuradas); sugerir args.gabarito
    assert "args.gabarito" in str(erro.value) and "--gabarito" in str(erro.value)
    assert "copie" not in str(erro.value) and "diagnostico.bat" not in str(erro.value)
    no_pc = amb.rasc / "Projeto qualquer"
    shutil.copytree(GABARITO, no_pc)  # o CapCut às vezes usa pasta com outro nome; acha pelo draft_name
    assert rascunho.localizar_gabarito(raiz=raiz) == no_pc
    velho = raiz / "execucoes" / "2026-09-25_1000_diagnostico" / "capcut_0925"
    novo = raiz / "execucoes" / "2026-09-26_0900_diagnostico" / "capcut_0925"
    for pasta in (velho, novo):
        shutil.copytree(GABARITO, pasta)
    assert rascunho.localizar_gabarito(raiz=raiz) == novo  # a cópia mais nova do diagnóstico
    repo = raiz / "gabaritos" / "capcut-9.5" / "0925"
    shutil.copytree(GABARITO, repo)
    assert rascunho.localizar_gabarito(raiz=raiz) == repo  # o gabarito guardado no repositório vem primeiro


# ---------------------------------------------------------------- fila, terminal e teste real

def test_tarefa_em_ensaio_nao_toca_no_capcut(amb, tmp_path):
    trabalho = amb.cfg.p.videos / "trabalho" / "vestido-verde"
    trabalho.mkdir(parents=True)
    (trabalho / "plano.json").write_text(json.dumps(amb.plano()), encoding="utf-8")
    antes = _hash_pasta(amb.rasc)
    ctx = Contexto(tmp_path / "execucao", ensaio=True)
    # achados #6/#11: o ensaio não toca no relatório do projeto (o video.exportar lê o nome do rascunho de lá)
    r = rascunho.tarefa({"projeto": "vestido-verde", "nome": "Ensaio", "gabarito": str(GABARITO)}, ctx)
    assert r["ensaio"] and Path(r["pasta"]) == ctx.pasta_saida / "rascunhos_ensaio" / "Ensaio"
    assert r["backup"] is None
    assert _hash_pasta(amb.rasc) == antes
    assert (ctx.pasta_saida / "relatorio_rascunho.txt").exists()
    assert r["relatorio"] == str(ctx.pasta_saida / "relatorio_rascunho.txt")
    assert not (trabalho / "relatorio_rascunho.txt").exists()
    real = "Rascunho do CapCut: vestido-verde 2026-09-25 (2)\nDuração: 18,00 s\n"
    (trabalho / "relatorio_rascunho.txt").write_text(real, encoding="utf-8")
    rascunho.tarefa({"projeto": "vestido-verde", "nome": "Ensaio", "gabarito": str(GABARITO)},
                    Contexto(tmp_path / "execucao2", ensaio=True))
    assert (trabalho / "relatorio_rascunho.txt").read_text(encoding="utf-8") == real


def test_tarefa_real_grava_no_capcut(amb, tmp_path):
    trabalho = amb.cfg.p.videos / "trabalho" / "vestido-verde"
    trabalho.mkdir(parents=True)
    (trabalho / "plano.json").write_text(json.dumps(amb.plano()), encoding="utf-8")
    amb.cfg.alterar("capcut", gabarito_pasta=str(DADOS))
    r = rascunho.tarefa({"projeto": "vestido-verde"}, Contexto(tmp_path / "execucao"))
    assert Path(r["pasta"]).parent == amb.rasc and r["rascunho"].startswith("vestido-verde ")
    assert r["manual"] and r["backup"]


def test_cli_inspecionar_e_erro_sem_plano(amb, capsys):
    assert rascunho.cli(["--inspecionar", str(GABARITO)]) == 0
    assert '"principal": "draft_info.json"' in capsys.readouterr().out
    assert rascunho.cli(["--projeto", "nao-existe", "--gabarito", str(GABARITO)]) == 1
    assert "Plano não encontrado" in capsys.readouterr().err


@pytest.mark.ffmpeg
def test_midia_real_sintetica(cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(capcut, "capcut_aberto", lambda: False)
    shutil.copy(DADOS / "root_meta_info.json", cfg.p.capcut_rascunhos / "root_meta_info.json")
    video = sintetico.video(tmp_path / "bruto" / "clipe.mp4", duracao=3.0, largura=360, altura=640)
    plano = {"projeto": "sintetico", "canvas": {"largura": 1080, "altura": 1920, "fps": 30},
             "video": [{"arquivo": str(video), "fonte_ini_s": 0.5, "ini_s": 0, "dur_s": 2.0}],
             "textos": [{"texto": "Oi", "ini_s": 0, "dur_s": 2, "x": 540, "y": 520, "tamanho_px": 90}]}
    r = rascunho.gerar_completo(plano, cfg.p.capcut_rascunhos, GABARITO, "Sintético")
    doc = _doc(r.pasta)
    m = doc["materials"]["videos"][0]
    assert (m["width"], m["height"]) == (360, 640)
    assert abs(m["duration"] - 3_000_000) <= 50_000


@pytest.mark.ffmpeg
def test_teste_real_gera_e_copia_para_comparar(cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(capcut, "capcut_aberto", lambda: False)
    shutil.copy(DADOS / "root_meta_info.json", cfg.p.capcut_rascunhos / "root_meta_info.json")
    cfg.alterar("capcut", gabarito_pasta=str(DADOS), teste_real={
        "pasta_trabalho": "teste-rascunho", "duracao_s": 3, "largura": 360, "altura": 640, "fps": 30,
        "nome": "Teste Rotinas {carimbo}"})
    ctx = Contexto(tmp_path / "execucao")
    r = rascunho.teste_real(ctx, [])
    assert r["rascunho"].startswith("Teste Rotinas ") and Path(r["pasta"]).is_dir()
    assert (ctx.pasta_saida / "rascunho_gerado" / r["rascunho"] / "draft_info.json").exists()
    assert (ctx.pasta_saida / "gabarito_usado" / "0925" / "draft_info.json").exists()
    assert (ctx.pasta_saida / "relatorio_rascunho.txt").exists()
    assert (ctx.pasta_saida / "indice_depois" / "root_meta_info.json").exists()
    assert "mídia perdida" in r["pedido_ao_usuario"]
    assert not list((ctx.pasta_saida).rglob("*.mp4"))
    doc = _doc(Path(r["pasta"]))
    assert len(_segs(doc, "video")) == 2 and len(_segs(doc, "audio")) == 1 and len(_segs(doc, "text")) == 2


def test_capcut_copiar_copia_o_projeto_como_esta_sem_midia(cfg, tmp_path, monkeypatch):
    """``testar.bat capcut-copiar "<projeto>"``: ver o que o CapCut manteve depois de abrir o rascunho gerado."""
    monkeypatch.setattr(capcut, "capcut_aberto", lambda: False)
    proj = cfg.p.capcut_rascunhos / "Meu Teste"
    shutil.copytree(GABARITO, proj)
    (proj / "clipe.mp4").write_bytes(b"video")
    antes = _hash_pasta(proj)
    ctx = Contexto(tmp_path / "execucao")
    r = rascunho.teste_copiar(ctx, ["Meu Teste"])
    assert r["ok"] and (ctx.pasta_saida / "projeto" / "Meu Teste" / "draft_content.json").exists()
    assert (ctx.pasta_saida / "inspecao.json").exists() and not list(ctx.pasta_saida.rglob("*.mp4"))
    assert _hash_pasta(proj) == antes  # não muda nada no projeto


def test_capcut_copiar_projeto_que_nao_existe_lista_os_recentes(cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(capcut, "capcut_aberto", lambda: False)
    shutil.copytree(GABARITO, cfg.p.capcut_rascunhos / "Outro")
    with pytest.raises(FileNotFoundError, match="Outro"):
        rascunho.teste_copiar(Contexto(tmp_path / "execucao"), ["Nao Existe"])


# ---------------------------------------------------------------- plano com violação e faixa-guia

def test_plano_com_violacao_nao_vira_rascunho(amb):
    antes = _hash_pasta(amb.rasc)
    with pytest.raises(rascunho.ErroValidacao) as e:
        amb.gerar(amb.plano(violacoes=["texto fora da zona segura"]))
    assert "zona segura" in str(e.value)
    assert _hash_pasta(amb.rasc) == antes


def test_faixa_guia_sai_muda(amb):
    audio = [{"arquivo": str(amb.musica), "ini_s": 0.0, "dur_s": 4.3, "fonte_ini_s": 0.0, "volume_db": -6.0,
              "papel": "guia"}]
    pasta = amb.gerar(amb.plano(audio=audio)).pasta
    segs = _segs(_doc(pasta), "audio")
    assert segs and all(s["volume"] == 0.0 for s in segs)


# ---------------------------------------------------------------- gabarito real do CapCut 9.5 (projeto "0925" do PC)

GABARITO_REAL = Path(__file__).resolve().parent.parent / "gabaritos" / "capcut-9.5" / "0925"


def test_gabarito_real_9_5_gera_raiz_e_timelines_iguais(amb):
    r = amb.gerar(gabarito=GABARITO_REAL)
    pasta = r.pasta
    raiz = _doc(pasta, "draft_content.json")
    assert not (pasta / "draft_info.json").exists()  # a 9.5 não usa draft_info.json
    assert _doc(pasta, "template-2.tmp") == raiz
    projeto = json.loads((pasta / "Timelines" / "project.json").read_text(encoding="utf-8"))
    assert projeto["main_timeline_id"] == raiz["id"] and projeto["timelines"][0]["id"] == raiz["id"]
    linha = pasta / "Timelines" / raiz["id"]
    assert json.loads((linha / "draft_content.json").read_text(encoding="utf-8")) == raiz
    # nada do gabarito que não deve ir: .bak, capa, a pasta da linha do tempo antiga
    assert not list(pasta.rglob("*.bak")) and not list(pasta.rglob("draft_cover.jpg"))
    assert not (pasta / "Timelines" / "4011713C-6C6B-48de-BAE0-BA6D68984DBD").exists()
    assert "4011713C-6C6B-48de-BAE0-BA6D68984DBD" not in (pasta / "Timelines" / "project.json").read_text(encoding="utf-8")
    assert [t["type"] for t in raiz["tracks"]].count("video") >= 1 and raiz["canvas_config"]["height"] == 1920
    assert raiz["platform"]["app_version"] == "9.5.0"
