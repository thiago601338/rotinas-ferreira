"""Privacidade das telas salvas antes do git (repositório público): Direct fora, notificação apagada e coberta."""

from PIL import Image

from rotinas import execucao, privacidade

CFG = {
    "marcadores_tela_privada": ["direct_thread", "row_thread_composer"],
    "pacote_notificacoes": "com.android.systemui",
    "ids_mantidos": ["com.android.systemui:id/clock"],
    "margem_print_px": [56, 24],
}


def no(rid="", texto="", desc="", pacote="com.instagram.android", limites="[0,0][900,1600]"):
    return (f'<node index="0" text="{texto}" resource-id="{rid}" class="android.widget.TextView" package="{pacote}" '
            f'content-desc="{desc}" bounds="{limites}" />')


def tela(*nos):
    raiz = '<node index="0" text="" resource-id="" class="android.widget.FrameLayout" package="com.instagram.android" ' \
           'content-desc="" bounds="[0,0][900,1600]">'
    return "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?><hierarchy rotation=\"0\">" + raiz + "".join(nos) \
        + "</node></hierarchy>"


# como no ensaio de 25/09 19:42: notificação flutuante de mensagem de cliente sobre a galeria
NOTIFICACAO = [
    no("com.android.systemui:id/clock", "19:43", "19:43", "com.android.systemui", "[12,0][108,96]"),
    no("android:id/message_name", "cliente_x", "", "com.android.systemui", "[136,104][307,142]"),
    no("android:id/message_text", "Quero o vestido", "", "com.android.systemui", "[136,143][190,181]"),
    no("android:id/action0", "RESPONDER", "Responder", "com.android.systemui", "[166,193][372,289]"),
    no("", "", "Notificação do Instagram: cliente_x", "com.android.systemui", "[97,0][141,48]"),
    no("com.instagram.android:id/gallery_title_text", "Adicionar ao story"),
]


def png(caminho, cor=(200, 200, 200)):
    Image.new("RGB", (900, 1600), cor).save(caminho)
    return caminho


def test_notificacao_do_android_e_apagada_do_xml_e_coberta_no_print(tmp_path):
    x = tmp_path / "passo_006.xml"
    x.write_text(tela(*NOTIFICACAO), encoding="utf-8")
    p = png(tmp_path / "passo_006.png")
    r = privacidade.conferir_par(x, CFG)
    assert r == {"privada": None, "apagados": 4, "coberto": True}
    xml = x.read_text(encoding="utf-8")
    assert "cliente_x" not in xml and "Quero o vestido" not in xml and "[oculto]" in xml
    assert 'text="19:43"' in xml and "Adicionar ao story" in xml  # relógio e tela do Instagram ficam
    with Image.open(p) as img:
        assert img.getpixel((450, 120)) == (0, 0, 0) and img.getpixel((20, 60)) == (0, 0, 0)  # faixa inteira
        assert img.getpixel((450, 800)) == (200, 200, 200)  # o resto do print fica


def test_so_icones_da_barra_de_status_apaga_nomes_sem_cobrir_print(tmp_path):
    x = tmp_path / "feed.xml"
    x.write_text(tela(NOTIFICACAO[0], NOTIFICACAO[4]), encoding="utf-8")
    p = png(tmp_path / "feed.png")
    antes = p.read_bytes()
    assert privacidade.conferir_par(x, CFG) == {"privada": None, "apagados": 1, "coberto": False}
    assert "cliente_x" not in x.read_text(encoding="utf-8") and p.read_bytes() == antes


def test_print_em_escala_diferente_da_tela_e_coberto_na_mesma_proporcao(tmp_path):
    x = tmp_path / "t.xml"
    x.write_text(tela(*NOTIFICACAO), encoding="utf-8")
    p = tmp_path / "t.png"
    Image.new("RGB", (450, 800), (200, 200, 200)).save(p)
    privacidade.conferir_par(x, CFG)
    with Image.open(p) as img:
        assert img.getpixel((225, 60)) == (0, 0, 0) and img.getpixel((225, 400)) == (200, 200, 200)


def test_tela_sem_notificacao_fica_igual(tmp_path):
    x = tmp_path / "t.xml"
    conteudo = tela(no("com.instagram.android:id/feed_tab", "", "Página inicial"))
    x.write_text(conteudo, encoding="utf-8")
    assert privacidade.conferir_par(x, CFG) == {"privada": None, "apagados": 0, "coberto": False}
    assert x.read_text(encoding="utf-8") == conteudo


def test_tela_do_direct_e_marcada_como_privada(tmp_path):
    x = tmp_path / "falha.xml"
    x.write_text(tela(no("com.instagram.android:id/direct_thread_header"), no("", "Mensagem da cliente")),
                 encoding="utf-8")
    assert privacidade.conferir_par(x, CFG)["privada"] == "direct_thread"
    y = tmp_path / "compose.xml"  # telas novas do Instagram (Compose) têm resource-id sem o prefixo do pacote
    y.write_text(tela(no("row_thread_composer_edittext", "Mensagem...")), encoding="utf-8")
    assert privacidade.conferir_par(y, CFG)["privada"] == "row_thread_composer"


def test_sanear_deixa_o_direct_so_no_pc_e_limpa_a_notificacao(cfg, tmp_path):
    """Ensaio de 25/09 19:42: a tela foi para uma conversa do Direct e o print foi para o GitHub."""
    raiz = tmp_path / "r"
    pasta = raiz / "execucoes" / "2026-09-25_1942_stories-ensaio"
    pasta.mkdir(parents=True)
    (pasta / "falha_T_musica_1.xml").write_text(
        tela(no("com.instagram.android:id/row_thread_composer_edittext", "Mensagem..."), no("", "Quero o vestido")),
        encoding="utf-8")
    png(pasta / "falha_T_musica_1.png")
    (pasta / "passo_006.xml").write_text(tela(*NOTIFICACAO), encoding="utf-8")
    png(pasta / "passo_006.png")
    res = execucao.sanear(pasta, raiz)
    assert not (pasta / "falha_T_musica_1.xml").exists() and not (pasta / "falha_T_musica_1.png").exists()
    guardado = raiz / "saida_local" / "execucoes" / pasta.name
    assert (guardado / "falha_T_musica_1.xml").exists() and (guardado / "falha_T_musica_1.png").exists()
    omitidos = (pasta / "omitidos.txt").read_text(encoding="utf-8")
    assert "falha_T_musica_1.png" in omitidos and "tela privada" in omitidos and "Quero o vestido" not in omitidos
    assert "cliente_x" not in (pasta / "passo_006.xml").read_text(encoding="utf-8")
    assert any(o.startswith("passo_006.xml (notificação do Android, print coberto") for o in res["ocultados"])


def test_sanear_na_duvida_tira_a_tela_do_git(cfg, tmp_path, monkeypatch):
    raiz = tmp_path / "r"
    pasta = raiz / "execucoes" / "2026-09-25_1000_x"
    pasta.mkdir(parents=True)
    (pasta / "t.xml").write_text(tela(), encoding="utf-8")
    png(pasta / "t.png")

    def quebra(*a, **k):
        raise OSError("arquivo aberto")

    monkeypatch.setattr(privacidade, "conferir_par", quebra)
    execucao.sanear(pasta, raiz)
    assert not (pasta / "t.xml").exists() and not (pasta / "t.png").exists()
