"""A5 — ADB do BlueStacks: conexão, envio à galeria (MediaStore) e a Tela sobre o uiautomator2 (dublês)."""

import json
import logging
from pathlib import Path

import pytest

from dubles_android import AdbFalso, Relogio, U2Falso, elemento_u2
from rotinas import config, ferramentas
from rotinas.stories import android

PASTA = "/sdcard/Pictures/RotinasFerreira/2026-09-22_A"


@pytest.fixture
def relogio(monkeypatch):
    r = Relogio()
    monkeypatch.setattr(android, "dormir", r.dormir)
    monkeypatch.setattr(android, "agora", r.agora)
    return r


def _midias(pasta: Path, nomes: list[str]) -> list[dict]:
    pasta.mkdir(parents=True, exist_ok=True)
    itens = []
    for nome in nomes:
        caminho = pasta / nome
        caminho.write_bytes(nome.encode("utf-8"))
        itens.append({"nome": nome.rsplit(".", 1)[0], "arquivo": nome, "caminho": str(caminho)})
    return itens


def _enviar(cfg, tmp_path, monkeypatch, relogio, nomes=("A - 1.mp4", "A - 2.jpg", "A - 3.jpg"), **kw):
    adb = AdbFalso(relogio, **kw)
    monkeypatch.setattr(ferramentas, "rodar", adb)
    con = android.Conexao("adb", "127.0.0.1:5555")
    midias = _midias(tmp_path / "Stories da Loja" / "2026-09-22", list(nomes))
    return adb, android.enviar_letra(con, "2026-09-22", "A", midias)


# ---------------------------------------------------------------- envio à galeria

def test_envio_em_ordem_inversa_com_mtime_decrescente_e_varredura_por_arquivo(cfg, tmp_path, monkeypatch, relogio):
    adb, res = _enviar(cfg, tmp_path, monkeypatch, relogio)
    pushes = [e[1] for e in adb.eventos if e[0] == "push"]
    assert pushes == ["2026-09-22_A_3.jpg", "2026-09-22_A_2.jpg", "2026-09-22_A_1.mp4"]
    mtimes = {e[1]: e[2] for e in adb.eventos if e[0] == "touch"}
    assert mtimes == {"2026-09-22_A_1.mp4": "202609251830.00", "2026-09-22_A_2.jpg": "202609251829.00",
                      "2026-09-22_A_3.jpg": "202609251828.00"}
    # cada arquivo: push → touch → varredura, antes do próximo push
    sequencia = [(e[0], e[-1] if e[0] != "touch" else e[1]) for e in adb.eventos if e[0] in ("push", "touch", "varredura")]
    assert sequencia == [("push", "2026-09-22_A_3.jpg"), ("touch", "2026-09-22_A_3.jpg"), ("varredura", "2026-09-22_A_3.jpg"),
                         ("push", "2026-09-22_A_2.jpg"), ("touch", "2026-09-22_A_2.jpg"), ("varredura", "2026-09-22_A_2.jpg"),
                         ("push", "2026-09-22_A_1.mp4"), ("touch", "2026-09-22_A_1.mp4"), ("varredura", "2026-09-22_A_1.mp4")]
    media = {k.rsplit("/", 1)[-1]: v for k, v in adb.media.items()}
    adicionados = [media[f"2026-09-22_A_{n}{e}"]["date_added"] for n, e in ((1, ".mp4"), (2, ".jpg"), (3, ".jpg"))]
    assert adicionados[0] > adicionados[1] > adicionados[2]  # A-1 é a mais recente
    assert res["album"] == "2026-09-22_A" and res["pasta"] == PASTA
    assert res["varredura"] == ["broadcast"]
    assert [a["nome"] for a in res["arquivos"]] == ["A - 1", "A - 2", "A - 3"]


def test_varredura_tenta_o_proximo_metodo_e_guarda_o_que_funcionou(cfg, tmp_path, monkeypatch, relogio):
    adb, res = _enviar(cfg, tmp_path, monkeypatch, relogio, metodos_ok=("scan_file",))
    tentativas = [e[1] for e in adb.eventos if e[0] == "varredura"]
    assert tentativas == ["broadcast", "scan_file", "scan_file", "scan_file"]
    assert res["varredura"] == ["scan_file"]


def test_midia_que_nao_aparece_na_galeria_da_erro_dizendo_qual(cfg, tmp_path, monkeypatch, relogio):
    with pytest.raises(android.ErroEnvio, match="A - 2") as erro:
        _enviar(cfg, tmp_path, monkeypatch, relogio, perder={"2026-09-22_A_2.jpg"})
    assert erro.value.faltando == ["A - 2"]
    assert "Não abri o Instagram" in str(erro.value)


def test_ordem_na_galeria_que_nao_confere_da_erro(cfg, tmp_path, monkeypatch, relogio):
    with pytest.raises(android.ErroEnvio, match="ordem"):
        _enviar(cfg, tmp_path, monkeypatch, relogio, date_added_fixo=1_758_800_000)


def test_sem_coluna_datetaken_consulta_sem_ela(cfg, tmp_path, monkeypatch, relogio):
    _, res = _enviar(cfg, tmp_path, monkeypatch, relogio, sem_datetaken=True)
    assert len(res["arquivos"]) == 3
    assert res["ordem_data_da_midia"] == {"datetaken": None}


def test_data_da_midia_fora_da_ordem_vira_aviso_e_sinal(cfg, tmp_path, monkeypatch, relogio):
    _, res = _enviar(cfg, tmp_path, monkeypatch, relogio)
    assert res["ordem_data_da_midia"] == {"datetaken": True} and not res["avisos"]
    _, res = _enviar(cfg, tmp_path / "2", monkeypatch, relogio, datetaken_fixo=1_700_000_000_000)
    assert res["ordem_data_da_midia"] == {"datetaken": False}
    assert any("datetaken" in a for a in res["avisos"])


def test_limpa_so_a_pasta_da_letra_antes_de_enviar(cfg, tmp_path, monkeypatch, relogio):
    adb, _ = _enviar(cfg, tmp_path, monkeypatch, relogio)
    assert ("rm", PASTA) in adb.eventos
    assert [e for e in adb.eventos if e[0] == "rm"] == [("rm", PASTA)]
    assert ("delete", "%/Pictures/RotinasFerreira/2026-09-22_A/%") in adb.eventos


def test_registro_antigo_que_nao_sai_da_galeria_usa_nomes_novos(cfg, tmp_path, monkeypatch, relogio):
    adb = AdbFalso(relogio, delete_funciona=False)
    adb.media[adb.canonico(PASTA + "/2026-09-22_A_1.mp4")] = {"_id": 1, "date_added": 1, "date_modified": 1, "datetaken": 1}
    monkeypatch.setattr(ferramentas, "rodar", adb)
    midias = _midias(tmp_path / "m", ["A - 1.mp4"])
    res = android.enviar_letra(android.Conexao("adb", "x"), "2026-09-22", "A", midias)
    assert res["arquivos"][0]["remoto"] != PASTA + "/2026-09-22_A_1.mp4"
    assert res["avisos"]


@pytest.mark.parametrize("base", ["/sdcard", "/sdcard/Pictures", "/storage/emulated/0", "/storage/1234-ABCD/Fotos/X",
                                  "/sdcard/Pictures/../DCIM", "C:\\Users\\V15",
                                  # vão para o shell do Android (touch, rm, file://): espaço/aspas/acento quebram
                                  "/sdcard/Pictures/Rotinas Ferreira", "/sdcard/Pictures/X'; rm -rf '/sdcard",
                                  "/sdcard/Pictures/Rotinas_Ferreira_Ç"])
def test_pasta_android_perigosa_e_recusada(cfg, base):
    cfg.alterar("bluestacks", pasta_android=base)
    with pytest.raises(android.ErroEnvio, match="pasta_android"):
        android.pasta_remota("2026-09-22", "A")


def test_pasta_remota_valida(cfg):
    assert android.pasta_remota("2026-09-22", "AB") == "/sdcard/Pictures/RotinasFerreira/2026-09-22_AB"
    with pytest.raises(android.ErroEnvio):
        android.pasta_remota("2026-09-22; rm -rf /", "A")


def test_arquivo_ausente_ou_mov_nao_e_enviado(cfg, tmp_path, monkeypatch, relogio):
    adb = AdbFalso(relogio)
    monkeypatch.setattr(ferramentas, "rodar", adb)
    con = android.Conexao("adb", "x")
    with pytest.raises(android.ErroEnvio, match="não encontrado"):
        android.enviar_letra(con, "2026-09-22", "A", [{"nome": "A - 1", "caminho": str(tmp_path / "nada.mp4")}])
    mov = _midias(tmp_path / "m", ["A - 1.mov"])
    with pytest.raises(android.ErroEnvio, match=".mov"):
        android.enviar_letra(con, "2026-09-22", "A", mov)
    assert not [e for e in adb.eventos if e[0] == "push"]


def test_leitura_do_mediastore():
    saida = ("Row: 0 _id=31, _data=/storage/emulated/0/Pictures/R/2026-09-22_A/2026-09-22_A_1.mp4, "
             "date_added=1758800010, date_modified=1758800000, datetaken=NULL\n"
             "Row: 1 _id=32, _data=/storage/emulated/0/Pictures/R/2026-09-22_A/x, y.jpg, date_added=5, date_modified=6\n")
    linhas = android._linhas_mediastore(saida)
    assert linhas[0]["_id"] == "31" and linhas[0]["datetaken"] is None
    assert linhas[1]["_data"].endswith("x, y.jpg") and linhas[1]["date_modified"] == "6"


# ---------------------------------------------------------------- conexão

def _conf(tmp_path, cfg, linhas: list[str]) -> None:
    arq = tmp_path / "bluestacks.conf"
    arq.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    cfg.alterar("bluestacks", bluestacks_conf=str(arq))


def test_conecta_na_porta_do_bluestacks_conf(cfg, tmp_path, monkeypatch, relogio):
    _conf(tmp_path, cfg, ['bst.enable_adb_access="1"', 'bst.instance.Pie64.status.adb_port="5565"',
                          'bst.instance.Pie64.adb_port="5555"'])
    adb = AdbFalso(relogio, conectaveis={"127.0.0.1:5565"}, dispositivos=[("emulator-5564", "device"), ("127.0.0.1:5565", "device")])
    monkeypatch.setattr(ferramentas, "rodar", adb)
    monkeypatch.setattr(ferramentas, "localizar", lambda nome, cands=None: "C:/BlueStacks/HD-Adb.exe")
    monkeypatch.delenv("ADBUTILS_ADB_PATH", raising=False)
    con = android.conectar()
    assert con.serial == "127.0.0.1:5565" and con.adb == "C:/BlueStacks/HD-Adb.exe"
    import os
    assert os.environ["ADBUTILS_ADB_PATH"] == "C:/BlueStacks/HD-Adb.exe"  # uiautomator2 usa o mesmo adb
    monkeypatch.delenv("ADBUTILS_ADB_PATH", raising=False)


def test_adb_desligado_no_bluestacks_da_mensagem_com_o_caminho(cfg, tmp_path, monkeypatch, relogio):
    _conf(tmp_path, cfg, ['bst.enable_adb_access="0"', 'bst.instance.Pie64.status.adb_port="5555"'])
    monkeypatch.setattr(ferramentas, "rodar", AdbFalso(relogio, conectaveis=(), dispositivos=[]))
    monkeypatch.setattr(ferramentas, "localizar", lambda nome, cands=None: "adb")
    monkeypatch.setenv("ADBUTILS_ADB_PATH", "x")
    with pytest.raises(android.ErroConexao) as erro:
        android.conectar()
    texto = str(erro.value)
    assert "DESLIGADO" in texto and "Configurações" in texto and "Avançado" in texto and "Android Debug Bridge" in texto


def test_sem_adb_da_mensagem_clara(cfg, monkeypatch):
    monkeypatch.setattr(ferramentas, "localizar", lambda nome, cands=None: None)
    with pytest.raises(android.ErroConexao, match="instalar.bat"):
        android.conectar()


def test_nunca_escolhe_celular_ligado_por_usb(cfg, tmp_path, monkeypatch, relogio):
    _conf(tmp_path, cfg, ['bst.enable_adb_access="1"'])
    monkeypatch.setattr(ferramentas, "rodar", AdbFalso(relogio, conectaveis=(), dispositivos=[("R58M123ABC", "device")]))
    monkeypatch.setattr(ferramentas, "localizar", lambda nome, cands=None: "adb")
    monkeypatch.setenv("ADBUTILS_ADB_PATH", "x")
    with pytest.raises(android.ErroConexao, match="BlueStacks"):
        android.conectar()


def test_info_do_aparelho(cfg, monkeypatch, relogio):
    monkeypatch.setattr(ferramentas, "rodar", AdbFalso(relogio))
    info = android.Conexao("adb", "127.0.0.1:5555").info("com.instagram.android")
    assert info["android"] == "11" and info["instagram"] == "300.0.0.1" and "1080x1920" in info["tela"]


# ---------------------------------------------------------------- Tela (uiautomator2)

SELETORES = {
    "botao": [{"text": "Não existe"}, {"description": "Avançar"}, {"coordenada_relativa": [0.5, 0.25]}],
    "so_plano_b": [{"text": "Nada"}, {"coordenada_relativa": [0.1, 0.9]}],
    "album": [{"text": "{album}"}],
    "grade": [{"resourceId": "falso:vazio"}, {"className": "android.widget.ImageView"}],
    "campo": [{"className": "android.widget.EditText", "instance": 1}],
    "enter": [{"tecla": "enter"}],
    "xp": [{"xpath": "//x"}],
}


def _tela(elementos, seletores=SELETORES):
    d = U2Falso(elementos)
    return d, android.Tela(d, seletores=seletores)


def test_tela_tenta_alternativas_em_ordem(cfg, relogio):
    d, tela = _tela([elemento_u2(desc="Avançar", limites=(100, 200, 300, 260))])
    el = tela.achar("botao")
    assert el.descricao == "Avançar" and not el.plano_b
    el.tocar()
    assert d.cliques == [(200, 230)]


def test_coordenada_so_depois_de_esperar_e_registrada_como_plano_b(cfg, relogio, caplog):
    d, tela = _tela([])
    inicio = relogio.t
    with caplog.at_level(logging.WARNING, logger="rotinas"):
        tela.tocar("so_plano_b", espera_s=3)
    assert relogio.t - inicio >= 3  # esperou as alternativas por texto antes
    assert d.cliques == [(100, 1800)]
    assert "PLANO B" in caplog.text
    assert tela.existe("so_plano_b") is False  # existe() nunca conta o plano B
    assert tela.achar("so_plano_b", espera_s=0, plano_b=False) is None


def test_tela_preenche_o_album(cfg, relogio):
    _, tela = _tela([elemento_u2(text="2026-09-22_A")])
    assert tela.existe("album", album="2026-09-22_A")
    assert not tela.existe("album", album="2026-09-22_B")


def test_grade_linha_a_linha_da_esquerda_para_a_direita(cfg, relogio):
    ims = [elemento_u2(text=str(i), classe="android.widget.ImageView", limites=lim) for i, lim in enumerate([
        (500, 405, 700, 600), (0, 400, 200, 600), (250, 650, 450, 850), (250, 398, 450, 598), (0, 655, 200, 850)])]
    _, tela = _tela(ims)
    assert [e.texto for e in tela.grade("grade")] == ["1", "3", "0", "4", "2"]
    assert [e.texto for e in tela.grade("grade", filtro=lambda e: e.texto in ("2", "4"))] == ["4", "2"]


def test_digitar_e_ler_texto(cfg, relogio):
    campos = [elemento_u2(classe="android.widget.EditText", text="URL"), elemento_u2(classe="android.widget.EditText", text="")]
    d, tela = _tela(campos)
    tela.digitar("campo", "Comprar agora")
    assert tela.ler_texto("campo") == "Comprar agora"
    assert campos[0]["text"] == "URL"


def test_tecla_do_teclado(cfg, relogio):
    d, tela = _tela([])
    tela.tocar("enter")
    assert d.teclas == ["enter"]


def test_seletor_desconhecido_ou_invalido(cfg, relogio):
    _, tela = _tela([])
    with pytest.raises(android.ErroSeletor, match="nao_existe"):
        tela.achar("nao_existe")
    with pytest.raises(android.ErroSeletor, match="desconhecido"):
        android.Tela(U2Falso([]), seletores={"x": [{"texto": "errado"}]})
    with pytest.raises(android.ErroSeletor, match="sozinho"):
        android.Tela(U2Falso([]), seletores={"x": [{"coordenada_relativa": [0.1, 0.2], "text": "a"}]})
    with pytest.raises(android.ErroSeletor, match="entre 0 e 1"):
        android.Tela(U2Falso([]), seletores={"x": [{"coordenada_relativa": [10, 20]}]})


def test_seletores_da_config_sao_validos_e_publicar_nunca_tem_plano_b(cfg):
    config.limpar_cache()
    seletores = config.carregar("bluestacks")["seletores"]
    assert android.validar_seletores(seletores) == []
    for chave in ("seu_story", "concluir_publicacao", "descartar", "compartilhar_facebook_toggle"):
        assert not any("coordenada_relativa" in alt for alt in seletores[chave]), chave
    usados = {"feed", "dispensar_aviso", "criar", "abrir_story", "abrir_galeria", "album_menu", "album_item",
              "selecionar_varios", "miniaturas_galeria", "badge_selecao", "contador_selecao", "avancar", "editor",
              "miniaturas_editor", "musica", "figurinhas", "figurinha_musica", "buscar_musica",
              "concluir_musica", "buscar_figurinha", "figurinha_link", "campo_url", "personalizar_texto",
              "campo_texto_figurinha", "confirmar_teclado", "concluir_figurinha", "figurinha_na_tela", "seu_story",
              "enviar_busca_musica", "faixas_musica", "limpar_busca_musica", "popup_sugestao_teclado",
              "itens_lista_album",
              "compartilhar_facebook_toggle", "interruptores", "concluir_publicacao", "descartar"}
    assert usados <= set(seletores)
    d = json.loads((Path(config.RAIZ) / "config" / "bluestacks.json").read_text(encoding="utf-8"))
    assert d["pasta_android"].startswith("/sdcard/")


def test_interruptor_do_facebook_lido_pelo_u2(cfg, relogio):
    sw = elemento_u2(classe="android.widget.Switch", desc="Compartilhar no Facebook", checked=True, checkable=True)
    _, tela = _tela([sw], seletores={"fb": [{"className": "android.widget.Switch", "descriptionContains": "Facebook"}]})
    el = tela.achar("fb", 0)
    assert el.marcado is True and el.marcavel is True
