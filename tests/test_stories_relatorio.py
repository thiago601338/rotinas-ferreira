import json
import shutil
import subprocess

import pytest

from rotinas.stories import relatorio

URL_A = "wa.me/5582988748649?text=Quero+comprar+o+Vestido+Midi+Al%C3%A7a"


def m(nome, tipo="foto", figurinha=None, musica=None):
    return {"nome": nome, "arquivo": f"{nome}.jpg", "caminho": f"C:\\x\\{nome}.jpg", "tipo": tipo, "hash": "h",
            "cores": ["Verde"], "precisa_musica": bool(musica), "musica": musica, "figurinha": figurinha}


def plano(ensaio=True):
    return {
        "data": "2026-09-22",
        "id": "20260925-183000-stories-montar",
        "ensaio": ensaio,
        "ordem": "letras",
        "letras": [
            {"letra": "A", "sku": "FB-0123", "peca": "Vestido Midi Alça", "categoria": "Vestidos", "midias": [
                m("A - 1", "video", musica={"nome": "Áudio original", "autor": "petermarkoski", "busca": "petermarkoski"}),
                m("A - 2"),
                m("A - 4", figurinha={"url": URL_A, "texto": "Comprar agora"}),
            ]},
            {"letra": "B", "sku": "FB-0200", "peca": "Vestido Longo de Festa", "categoria": "VESTIDO DE FESTA",
             "midias": [m("B - 1"), m("B - 2")]},
        ],
        "cortes": [
            {"letra": "A", "nome": "A - 3", "motivo": "cor sem estoque", "detalhe": "Preto"},
            {"letra": "C", "nome": None, "motivo": "já postado", "detalhe": "modelo FB-0300 já postado em 20/09/2026, letra B (B - 2.jpg)",
             "peca": "Conjunto Linho"},
            {"letra": "D", "nome": None, "motivo": "modelo sem nenhuma peça", "detalhe": "FB-0400",
             "peca": "Macacão Pantalona"},
        ],
        "avisos": ["Letra E sem identificação: ficou de fora"],
    }


# ------------------------------------------------------------ JS

def test_js_com_n_e_sequencia_esperada(cfg):
    js = relatorio.js_conferencia(plano())
    assert js.startswith("const uid='54614123599', appId='936619743392459';")
    assert "fetch('/api/v1/feed/reels_media/?reel_ids='+uid,{headers:{'X-IG-App-ID':appId}})" in js
    assert ".slice(-5)" in js
    assert 'const esperado=["sem link", "sem link", "LINK", "sem link", "sem link"]' in js
    assert "story_link_stickers?.[0]?.story_link?.url" in js
    assert "'CONFERE'" in js and "'NÃO CONFERE: '" in js


def test_js_so_das_letras_publicadas(cfg):
    js = relatorio.js_conferencia(plano(), ["A"])
    assert ".slice(-3)" in js and '["sem link", "sem link", "LINK"]' in js
    assert relatorio.js_conferencia(plano(), []).startswith("//")


def test_js_usa_uid_da_config(cfg):
    cfg.alterar("stories", conferencia_instagram={"uid": "111", "app_id": "222"})
    assert relatorio.js_conferencia(plano()).startswith("const uid='111', appId='222';")


def _rodar_js(js, itens):
    corpo = js.replace("\n[...itens", "\nreturn [...itens")
    programa = (
        "globalThis.fetch=async()=>({json:async()=>(" + json.dumps({"reels_media": [{"items": itens}]}) + ")});\n"
        "(async()=>{" + corpo + "})().then(r=>console.log(JSON.stringify(r)));"
    )
    saida = subprocess.run(["node", "-e", programa], capture_output=True, text=True, timeout=30, check=True).stdout
    return json.loads(saida)


def item(t, url=None):
    return {"taken_at": t, "story_link_stickers": [{"story_link": {"url": url}}] if url else []}


@pytest.mark.skipif(not shutil.which("node"), reason="node não instalado")
def test_js_roda_e_confere(cfg):
    js = relatorio.js_conferencia(plano())
    antigo = item(1000)
    certos = [item(2000), item(2001), item(2002, "https://" + URL_A), item(2003), item(2004)]
    r = _rodar_js(js, [antigo, *certos])
    assert r[-1] == "CONFERE"
    assert len(r) == 6 and URL_A in r[2] and " LINK" in r[2]
    # a última mídia de A subiu sem link (armadilha do https://) e B perdeu uma mídia
    r = _rodar_js(js, [antigo, item(2000), item(2001), item(2002), item(2003)])
    assert r[-1].startswith("NÃO CONFERE") and "A - 4: esperado LINK, veio sem link" in r[-1]
    r = _rodar_js(js, [item(2000), item(2001)])
    assert r[-1].startswith("NÃO CONFERE: subiram 2 de 5")


# ------------------------------------------------------------ textos

def test_texto_plano(cfg):
    t = relatorio.texto_plano(plano())
    assert t.startswith("Stories de 22/09/2026 — ENSAIO")
    assert "Vai subir: 2 letras, 5 mídias" in t
    assert '- A · Vestido Midi Alça (FB-0123): 3 mídias; link na A - 4 ("Comprar agora")' in t
    assert "música na A - 1: Áudio original (petermarkoski)" in t
    assert "- B · Vestido Longo de Festa (FB-0200): 2 mídias; sem link (vestido de festa)" in t
    assert "A - 3 com cor sem estoque (Preto), avisar se repor" in t
    assert "- C · Conjunto Linho: modelo FB-0300 já postado em 20/09/2026, letra B (B - 2.jpg)" in t
    assert "- D · Macacão Pantalona: modelo sem nenhuma peça (FB-0400)" in t
    assert "Letra E sem identificação" in t
    assert "Conferir os prints do ensaio" in t
    assert "Avisar se repor: Preto (Vestido Midi Alça)." in t


def test_texto_plano_real_e_vazio(cfg):
    p = plano(ensaio=False)
    assert "POSTAGEM REAL" in relatorio.texto_plano(p)
    assert "BlueStacks aberto" in relatorio.texto_plano(p)
    p["letras"] = []
    assert "Nada vai subir." in relatorio.texto_plano(p)


def test_letra_inteira_cortada_por_estoque(cfg):
    p = plano()
    p["cortes"] = [{"letra": "F", "nome": "F - 1", "motivo": "cor sem estoque", "detalhe": "Azul", "cores": ["Azul"], "peca": "Saia"},
                   {"letra": "F", "nome": "F - 2", "motivo": "excluída", "detalhe": "tremida", "peca": "Saia"}]
    t = relatorio.texto_plano(p)
    assert "- F · Saia (letra inteira fora): F - 1 com cor sem estoque (Azul), avisar se repor; F - 2 excluída (tremida)" in t


def test_texto_resultado_publicado_com_falha(cfg):
    res = {"ensaio": False, "publicadas": ["A"], "parou_em": "B: figurinha de link",
           "letras": [{"letra": "A", "estado": "publicada", "midias": ["A - 1", "A - 2", "A - 4"], "prints": [], "erro": None},
                      {"letra": "B", "estado": "falhou", "midias": [], "prints": [], "erro": "botão Avançar não apareceu"}]}
    t = relatorio.texto_resultado(plano(ensaio=False), res)
    assert "Subiu: 1 letra, 3 mídias" in t
    assert "- A · Vestido Midi Alça (FB-0123): 3 mídias; link na A - 4" in t
    assert "- B · Vestido Longo de Festa: falhou: botão Avançar não apareceu (nada dessa letra foi publicado)" in t
    assert "Parou em: B: figurinha de link" in t
    assert "A - 3 com cor sem estoque (Preto), avisar se repor" in t
    assert "já postado em 20/09/2026" in t
    assert ".slice(-3)" in t and "CONFERE" in t


def test_texto_resultado_letra_pulada_e_nao_iniciada(cfg):
    res = {"ensaio": True, "publicadas": [], "parou_em": "conexão com o BlueStacks",
           "letras": [{"letra": "A", "estado": "nao_iniciada", "pulada": "já publicada antes (postados.csv)"},
                      {"letra": "B", "estado": "nao_iniciada"}]}
    t = relatorio.texto_resultado(plano(), res)
    assert "- B · Vestido Longo de Festa: não chegou a ser montada" in t
    assert "- A · Vestido Midi Alça: pulada (já publicada antes (postados.csv))" in t
    assert "Parou em: conexão com o BlueStacks" in t


def test_texto_resultado_ensaio(cfg):
    res = {"ensaio": True, "publicadas": [],
           "letras": [{"letra": "A", "estado": "ensaio_ok", "prints": ["a1.png", "a2.png", "a3.png"]},
                      {"letra": "B", "estado": "ensaio_ok", "prints": ["b1.png", "b2.png"]}]}
    t = relatorio.texto_resultado(plano(), res)
    assert "ENSAIO (nada foi publicado)" in t
    assert "Montado até antes de publicar: 2 letras, 5 mídias" in t
    assert "3 prints" in t and "Conferir os prints" in t
    assert "const uid" not in t


# ------------------------------------------------------------ terminal

def _gravar_resultado(cfg, estado, dados):
    pasta = cfg.p.fila / estado
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / f"{dados['id']}.json").write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")


def test_cli_relatorio_de_postagem(cfg, capsys):
    id_ = "20260925-190000-stories-postar-2026-09-22"
    res = {"ensaio": False, "publicadas": ["A", "B"],
           "letras": [{"letra": "A", "estado": "publicada"}, {"letra": "B", "estado": "publicada"}]}
    _gravar_resultado(cfg, "feito", {"id": id_, "tipo": "stories.postar", "estado": "feito",
                                     "pedido": {"id": id_, "tipo": "stories.postar", "args": {"plano": plano(False)}, "ensaio": False},
                                     "resultado": res})
    assert relatorio.cli(["--pedido", id_]) == 0
    saida = capsys.readouterr().out
    assert "Subiu: 2 letras, 5 mídias" in saida and ".slice(-5)" in saida
    assert (cfg.p.trabalho_stories / "2026-09-22" / f"relatorio-{id_}.txt").exists()
    assert relatorio.cli(["--pedido", id_, "--js"]) == 0
    assert capsys.readouterr().out.startswith("const uid=")


def test_cli_pedido_com_erro_usa_resultado_parcial(cfg, capsys):
    id_ = "20260925-190500-stories-postar-2026-09-22"
    parcial = {"ensaio": False, "publicadas": ["A"], "letras": [{"letra": "A", "estado": "publicada"},
                                                                 {"letra": "B", "estado": "falhou", "erro": "sem conexão ADB"}]}
    _gravar_resultado(cfg, "erro", {"id": id_, "tipo": "stories.postar", "estado": "erro", "erro": "ADB caiu",
                                    "pedido": {"args": {"plano": plano(False)}, "ensaio": False}, "resultado_parcial": parcial})
    assert relatorio.cli(["--pedido", id_]) == 0
    saida = capsys.readouterr().out
    assert saida.startswith("Erro no pedido: ADB caiu")
    assert "Subiu: 1 letra, 3 mídias" in saida and "sem conexão ADB" in saida


def test_cli_pedido_de_montagem_e_pendente(cfg, capsys):
    id_ = "20260925-183000-stories-montar"
    _gravar_resultado(cfg, "feito", {"id": id_, "tipo": "stories.montar", "pedido": {"tipo": "stories.montar"},
                                     "resultado": {"plano": plano(), "relatorio": "texto pronto", "pedido_postagem": None}})
    assert relatorio.cli(["--pedido", id_]) == 0
    assert capsys.readouterr().out.strip() == "texto pronto"
    _gravar_resultado(cfg, "pendente", {"id": "x-1", "tipo": "stories.postar"})
    assert relatorio.cli(["--pedido", "x-1"]) == 1
    assert "pendente" in capsys.readouterr().out
    assert relatorio.cli(["--pedido", "nao-existe"]) == 1


def test_letra_incerta_nao_diz_que_nada_subiu_e_entra_no_js(cfg):
    # A5: falhou depois de tocar em "Seu story" → "incerta"; repetir sem conferir duplicaria o story
    res = {"ensaio": False, "publicadas": [], "parou_em": "letra A: concluir_publicacao",
           "letras": [{"letra": "A", "estado": "falhou", "incerta": True,
                       "erro": "tela travou ATENÇÃO: já tinha tocado em 'Seu story'; a letra pode ter subido."},
                      {"letra": "B", "estado": "nao_iniciada"}]}
    t = relatorio.texto_resultado(plano(ensaio=False), res)
    assert "nada dessa letra foi publicado" not in t
    assert "Letra A pode ter subido: rodar o JS" in t
    assert ".slice(-3)" in t and '["sem link", "sem link", "LINK"]' in t


def test_cli_plano_por_caminho(cfg, capsys, tmp_path):
    arq = tmp_path / "pasta com espaço" / "plano-x.json"
    arq.parent.mkdir()
    arq.write_text(json.dumps(plano(False), ensure_ascii=False), encoding="utf-8")
    id_ = "20260925-191000-stories-postar-2026-09-22"
    _gravar_resultado(cfg, "feito", {"id": id_, "tipo": "stories.postar",
                                     "pedido": {"args": {"plano": str(arq)}, "ensaio": False},
                                     "resultado": {"ensaio": False, "publicadas": ["A"], "letras": [{"letra": "A", "estado": "publicada"}]}})
    assert relatorio.cli(["--pedido", id_]) == 0
    assert "Subiu: 1 letra, 3 mídias" in capsys.readouterr().out


def test_cli_id_invalido(cfg, capsys):
    assert relatorio.cli(["--pedido", "..\\..\\x"]) == 1
    assert "inválido" in capsys.readouterr().err


# ------------------------------------------------------------ achados #16 e #19

def test_texto_resultado_mostra_os_avisos_da_postagem(cfg):
    aviso = "Letra A: não achei o menu de álbuns; usei 'Recentes' (a ordem por data garante as N primeiras)."
    res = {"ensaio": True, "publicadas": [], "avisos": [aviso],
           "letras": [{"letra": "A", "estado": "ensaio_ok", "prints": ["a1.png"]},
                      {"letra": "B", "estado": "ensaio_ok", "prints": ["b1.png"]}]}
    t = relatorio.texto_resultado(plano(), res)
    assert f"Avisos da postagem:\n- {aviso}" in t
    assert t.index("Avisos da postagem:") < t.index("O que fazer:")
    sem = relatorio.texto_resultado(plano(), dict(res, avisos=[]))
    assert "Avisos da postagem" not in sem


def _interrompido(cfg, ensaio=False):
    id_ = "20260925-192000-stories-postar-2026-09-22"
    motivo = ("Interrompido: o vigia parou no meio deste pedido. Não reexecutei para não repetir nada. "
              "Confira o que já foi feito (log e prints na pasta) antes de pedir de novo, com outro id.")
    _gravar_resultado(cfg, "erro", {"id": id_, "tipo": "stories.postar", "estado": "erro", "erro": motivo,
                                    "pedido": {"id": id_, "tipo": "stories.postar", "args": {"plano": plano(ensaio)},
                                               "ensaio": ensaio}})
    return id_


def test_postagem_interrompida_nao_diz_que_nada_subiu(cfg, capsys):
    id_ = _interrompido(cfg)
    assert relatorio.cli(["--pedido", id_]) == 0
    saida = capsys.readouterr().out
    assert saida.startswith("Erro no pedido: Interrompido")
    assert "não sei o que subiu" in saida
    assert "Subiu: 0 letras" not in saida and "não chegou a ser postada" not in saida
    assert "mandar as letras que não subiram" not in saida
    # JS de TODAS as letras do plano (A: 3 mídias, B: 2)
    assert ".slice(-5)" in saida and '["sem link", "sem link", "LINK", "sem link", "sem link"]' in saida
    assert relatorio.cli(["--pedido", id_, "--js"]) == 0
    js = capsys.readouterr().out
    assert js.startswith("const uid=") and ".slice(-5)" in js


def test_ensaio_interrompido_continua_com_o_relatorio_de_ensaio(cfg, capsys):
    id_ = _interrompido(cfg, ensaio=True)
    assert relatorio.cli(["--pedido", id_]) == 0
    saida = capsys.readouterr().out
    assert "não sei o que subiu" not in saida and "ENSAIO (nada foi publicado)" in saida


def test_cli_js_inclui_letra_incerta_do_resultado_parcial(cfg, capsys):
    # achado #0: `stories-relatorio --js` usava só "publicadas" e dizia "Nada publicado" com a letra A incerta
    id_ = "20260925-191000-stories-postar-2026-09-22"
    parcial = {"ensaio": False, "publicadas": [], "parou_em": "letra A: concluir_publicacao",
               "letras": [{"letra": "A", "estado": "falhou", "incerta": True, "erro": "não voltou ao feed"},
                          {"letra": "B", "estado": "nao_iniciada"}]}
    _gravar_resultado(cfg, "erro", {"id": id_, "tipo": "stories.postar", "estado": "erro", "erro": "Parei na letra A",
                                    "pedido": {"args": {"plano": plano(False)}, "ensaio": False},
                                    "resultado_parcial": parcial})
    assert relatorio.cli(["--pedido", id_, "--js"]) == 0
    js = capsys.readouterr().out.strip()
    assert js == relatorio.js_conferencia(plano(False), ["A"])
    assert ".slice(-3)" in js and not js.startswith("//")
    # com A publicada e B incerta, o JS cobre as duas
    parcial2 = dict(parcial, publicadas=["A"], letras=[{"letra": "A", "estado": "publicada"},
                                                       {"letra": "B", "estado": "falhou", "incerta": True}])
    _gravar_resultado(cfg, "erro", {"id": id_, "tipo": "stories.postar", "estado": "erro", "erro": "x",
                                    "pedido": {"args": {"plano": plano(False)}, "ensaio": False},
                                    "resultado_parcial": parcial2})
    assert relatorio.cli(["--pedido", id_, "--js"]) == 0
    assert ".slice(-5)" in capsys.readouterr().out
