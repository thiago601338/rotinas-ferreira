import json
import re
import sys

import pytest

from rotinas.video import capcut

UUID_MAIUSCULO = re.compile(r"^[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}$")


def test_us_e_segundos():
    assert capcut.us(1.4) == 1_400_000
    assert capcut.us(0.1 + 0.2) == 300_000
    assert capcut.us(1 / 3) == 333_333
    assert capcut.us("2.5") == 2_500_000
    assert capcut.segundos(2_500_000) == 2.5
    assert isinstance(capcut.us(1.0), int)


def test_novo_id_maiusculo_e_unico(cfg):
    ids = {capcut.novo_id() for _ in range(200)}
    assert len(ids) == 200
    assert all(UUID_MAIUSCULO.match(i) for i in ids)
    cfg.alterar("capcut", ids_maiusculos=False)
    minusculo = capcut.novo_id()
    assert minusculo == minusculo.lower()


def test_db_para_linear():
    assert capcut.db_para_linear(0) == 1.0
    assert capcut.db_para_linear(-6) == pytest.approx(0.501187, abs=1e-6)
    assert capcut.db_para_linear(-18) == pytest.approx(0.125893, abs=1e-6)
    assert capcut.db_para_linear(6) == pytest.approx(1.995262, abs=1e-6)
    assert capcut.linear_para_db(capcut.db_para_linear(-12.5)) == pytest.approx(-12.5, abs=1e-4)


def test_utf16_e_cor():
    assert capcut.tamanho_utf16("Olá") == 3
    assert capcut.tamanho_utf16("Vestido 👗") == 10  # o emoji ocupa 2 unidades UTF-16
    assert capcut.cor_rgb("#FFFFFF") == [1.0, 1.0, 1.0]
    assert capcut.cor_rgb("#000") == [0.0, 0.0, 0.0]
    with pytest.raises(ValueError):
        capcut.cor_rgb("verde")


def test_carimbo_na_unidade_do_gabarito():
    assert capcut.carimbo_como(1_790_000_000_000_000) > 1e15  # µs
    assert 1e12 < capcut.carimbo_como(1_790_000_000_000) < 1e13  # ms
    assert 1e9 < capcut.carimbo_como(1_790_000_000) < 1e10  # s
    assert capcut.carimbo_como(0) == 0
    assert capcut.carimbo_como(-1) == -1
    assert capcut.carimbo_como("") == ""


def test_formato_e_criptografia(tmp_path):
    aberto = tmp_path / "a.json"
    aberto.write_text('{"tracks": []}', encoding="utf-8")
    com_bom = tmp_path / "b.json"
    com_bom.write_bytes(b"\xef\xbb\xbf  {\"x\": 1}")
    cripto = tmp_path / "c.json"
    cripto.write_bytes(b"\x8a\x13\x99binario")
    vazio = tmp_path / "d.json"
    vazio.write_bytes(b"")
    quebrado = tmp_path / "e.json"
    quebrado.write_text("{nao e json", encoding="utf-8")
    assert capcut.formato(aberto) == "json"
    assert capcut.formato(com_bom) == "json"
    assert capcut.formato(cripto) == "criptografado"
    assert capcut.criptografado(cripto)
    assert not capcut.criptografado(aberto)
    assert capcut.formato(vazio) == "vazio"
    assert capcut.formato(quebrado) == "json_invalido"
    assert capcut.formato(tmp_path / "nao-existe.json") == "ausente"


def test_linha_do_tempo_direta_e_em_envelope():
    doc = {"id": "X", "tracks": [], "materials": {}}
    assert capcut.achar_linha_do_tempo(doc) == (doc, ())
    envelope = {"meta": 1, "draft": {"content": doc}}
    achado, caminho = capcut.achar_linha_do_tempo(envelope)
    assert achado is envelope["draft"]["content"] and caminho == ("draft", "content")
    texto = {"versao": 2, "draft_info": json.dumps(doc)}
    achado, caminho = capcut.achar_linha_do_tempo(texto)
    assert achado == doc and caminho == ("draft_info:json",)
    novo = {"id": "Y", "tracks": [{"type": "video"}], "materials": {}}
    capcut.recolocar(texto, caminho, novo)
    assert json.loads(texto["draft_info"]) == novo and texto["versao"] == 2
    capcut.recolocar(envelope, ("draft", "content"), novo)
    assert envelope["draft"]["content"] == novo
    assert capcut.achar_linha_do_tempo({"duration": 0}) is None


def test_capcut_aberto_por_nome_exato(cfg, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(capcut, "_processos_windows",
                        lambda: '"explorer.exe","1","Console","1","90.000 K"\n"CapCut.exe","4242","Console","1","500.000 K"\n')
    assert capcut.capcut_aberto()
    with pytest.raises(capcut.CapCutAberto):
        capcut.exigir_capcut_fechado()
    monkeypatch.setattr(capcut, "_processos_windows",
                        lambda: '"CapCutHelper.exe","7","Console","1","1 K"\n"python.exe","8","Console","1","1 K"\n')
    assert not capcut.capcut_aberto()
    capcut.exigir_capcut_fechado()


def test_tasklist_falhou_recusa(cfg, monkeypatch):
    class R:
        returncode, stdout = 1, ""

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(capcut.ferramentas, "rodar", lambda *a, **k: R())
    with pytest.raises(capcut.ErroCapCut, match="tasklist"):
        capcut.capcut_aberto()


def test_capcut_aberto_fora_do_windows(cfg, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert capcut.capcut_aberto() is False


def test_backup_copia_raiz_e_projeto_sem_apagar(cfg, tmp_path):
    rasc = cfg.p.capcut_rascunhos
    (rasc / "root_meta_info.json").write_text('{"all_draft_store": []}', encoding="utf-8")
    (rasc / "outro.db").write_bytes(b"x")
    proj = rasc / "Meu projeto"
    (proj / "sub").mkdir(parents=True)
    (proj / "draft_info.json").write_text("{}", encoding="utf-8")
    (proj / "sub" / "a.json").write_text("[]", encoding="utf-8")
    d1 = capcut.backup(rasc, [proj])
    d2 = capcut.backup(rasc, [])
    assert d1 != d2 and d1.parent == cfg.p.backups / "capcut"
    assert (d1 / "root_meta_info.json").read_text(encoding="utf-8") == '{"all_draft_store": []}'
    assert (d1 / "outro.db").exists()
    assert (d1 / "projetos" / "Meu projeto" / "sub" / "a.json").exists()
    manifesto = json.loads((d1 / "manifesto.json").read_text(encoding="utf-8"))
    assert manifesto["raiz"] == ["outro.db", "root_meta_info.json"]
    assert (proj / "draft_info.json").exists()  # nada apagado


def test_nome_livre_e_sanitizar(cfg):
    rasc = cfg.p.capcut_rascunhos
    assert capcut.nome_livre(rasc, "Vestido verde") == "Vestido verde"
    (rasc / "Vestido verde").mkdir()
    assert capcut.nome_livre(rasc, "Vestido verde") == "Vestido verde (2)"
    (rasc / "Vestido verde (2)").mkdir()
    assert capcut.nome_livre(rasc, "Vestido verde") == "Vestido verde (3)"
    indice = {"all_draft_store": [{"draft_name": "Saia", "draft_fold_path": "x"}]}
    assert capcut.nome_livre(rasc, "saia", indice) == "saia (2)"
    assert capcut.sanitizar_nome('a<b>c:d"e/f\\g|h?i*j. ') == "a-b-c-d-e-f-g-h-i-j"
    assert capcut.sanitizar_nome("   ") == "Rascunho"


def test_caminhos_no_estilo_do_capcut(cfg):
    assert capcut.caminho_capcut(r"C:\Users\V15\Videos\a b.mp4") == "C:/Users/V15/Videos/a b.mp4"
    assert capcut.caminho_capcut("C:/x/y.mp4", "\\") == "C:\\x\\y.mp4"
    assert capcut.estilo_separador("C:/Users/V15/x") == "/"
    assert capcut.estilo_separador(None, r"C:\Users\V15\x") == "\\"
    assert capcut.estilo_separador(None) == "/"
    cfg.alterar("capcut", separador_caminho="\\")
    assert capcut.estilo_separador("C:/Users/V15/x") == "\\"


def test_gravar_json_atomico_e_recuo(tmp_path):
    arq = tmp_path / "x" / "a.json"
    capcut.gravar_json(arq, {"b": "ção", "n": [1, 2]})
    assert arq.read_text(encoding="utf-8") == '{"b":"ção","n":[1,2]}'
    assert not list(arq.parent.glob("*.tmp-rotinas"))
    capcut.gravar_json(arq, {"a": 1}, recuo=2)
    assert capcut.recuo_de(arq.read_text(encoding="utf-8")) == 2
    assert capcut.recuo_de('{"a":1}') is None


def test_chave_do_indice():
    assert capcut.chave_do_indice({"all_draft_store": [{"draft_id": "1"}], "x": []}) == "all_draft_store"
    assert capcut.chave_do_indice({"all_draft_store": []}) == "all_draft_store"
    assert capcut.chave_do_indice({"outra": 1}) is None
