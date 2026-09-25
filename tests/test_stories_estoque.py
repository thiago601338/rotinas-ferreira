import json

import pytest
import requests

from rotinas.contexto import Contexto
from rotinas.stories import estoque
from rotinas.stories.estoque import ClienteFalso, ClienteSupabase, ErroEstoque, Produto


# ------------------------------------------------------------ requests falso

class Resposta:
    def __init__(self, status=200, dados=None, texto=None):
        self.status_code = status
        self._dados = dados
        self.text = texto if texto is not None else json.dumps(dados)

    def json(self):
        if self._dados is None:
            raise ValueError("sem json")
        return self._dados


@pytest.fixture
def http(monkeypatch):
    """Troca ``requests.get``: cada chamada consome a próxima resposta e fica registrada."""

    class Http:
        chamadas = []
        respostas = []

        @staticmethod
        def get(url, params=None, headers=None, timeout=None):
            Http.chamadas.append({"url": url, "params": list(params or []), "headers": dict(headers or {}), "timeout": timeout})
            r = Http.respostas.pop(0)
            if isinstance(r, Exception):
                raise r
            return r

    monkeypatch.setattr(estoque.requests, "get", Http.get)
    return Http


LINHA = {
    "id": 7,
    "sku": "FB-0123",
    "name": "Vestido Midi Alça",
    "category": "Vestidos",
    "status": "Ativo",
    "sale_price": "189.9",
    "product_variations": [
        {"color": "Verde Musgo", "size": "M", "stock": 2},
        {"color": "Preto", "size": "P", "stock": 0},
        {"color": "Verde Musgo", "size": "G", "stock": 3},
        {"color": "Preto", "size": "M", "stock": 0},
    ],
}


def _params(chamada):
    return dict(chamada["params"])


def _texto_da_chamada(chamada):
    return chamada["url"] + " " + " ".join(f"{k}={v}" for k, v in chamada["params"])


def test_consulta_por_sku_url_params_e_cabecalhos(cfg, http):
    http.respostas = [Resposta(200, [LINHA])]
    produtos = ClienteSupabase().buscar(sku="FB-0123")
    c = http.chamadas[0]
    assert c["url"] == "https://exemplo.supabase.co/rest/v1/products"
    p = _params(c)
    assert p["select"] == "id,sku,name,category,status,sale_price,product_variations(color,size,stock)"
    assert p["status"] == "eq.Ativo"
    assert p["deleted_at"] == "is.null"
    assert p["sku"] == "eq.FB-0123"
    assert "name" not in p and "or" not in p
    assert "cost_price" not in _texto_da_chamada(c)
    assert "*" not in p["select"]
    assert c["headers"]["apikey"] == cfg.segredo
    assert c["headers"]["Authorization"] == f"Bearer {cfg.segredo}"
    assert c["timeout"] and c["timeout"] > 0
    assert len(produtos) == 1
    prod = produtos[0]
    assert prod.preco == 189.9
    # ordenado como o SQL: cor, depois tamanho
    assert [(v["cor"], v["tamanho"]) for v in prod.variacoes] == [
        ("Preto", "M"), ("Preto", "P"), ("Verde Musgo", "G"), ("Verde Musgo", "M"),
    ]
    assert prod.estoque_por_cor() == {"Preto": 0, "Verde Musgo": 5}
    assert prod.total == 5


def test_consulta_por_termo_usa_ilike_sem_aspas(cfg, http):
    http.respostas = [Resposta(200, [])]
    assert ClienteSupabase().buscar(termo="vestido, midi (alça)") == []
    p = _params(http.chamadas[0])
    # filtro simples: valor literal (aspas entrariam na busca)
    assert p["name"] == "ilike.*vestido,*midi*(alça)*"  # espaço vira curinga: palavras em sequência
    assert "sku" not in p


def test_termo_com_palavras_separadas_acha_nome_com_palavra_no_meio(cfg):
    cliente = ClienteFalso([Produto(1, "FB-0410", "Vestido Longo Festa Cetim", "Vestidos de Festa", 399.9,
                                    [{"cor": "Azul Marinho", "tamanho": "M", "estoque": 1}], status="Ativo")])
    assert [p.sku for p in cliente.buscar(termo="vestido festa")] == ["FB-0410"]
    assert cliente.buscar(termo="festa vestido") == []  # a ordem das palavras vale


def test_sku_e_termo_juntos_usam_or_com_citacao(cfg, http):
    http.respostas = [Resposta(200, [])]
    ClienteSupabase().buscar(sku="FB-0123", termo='Vestido, "midi" (alça)')
    p = _params(http.chamadas[0])
    assert p["or"] == '(sku.eq.FB-0123,name.ilike."*Vestido,*\\"midi\\"*(alça)*")'
    assert p["status"] == "eq.Ativo" and p["deleted_at"] == "is.null"


def test_citacao_do_postgrest():
    assert estoque._citar("FB-0123") == "FB-0123"
    assert estoque._citar("a,b") == '"a,b"'
    assert estoque._citar("x.y") == '"x.y"'
    assert estoque._citar('a"b') == '"a\\"b"'
    assert estoque._citar("a\\b") == '"a\\\\b"'


def test_url_com_rest_v1_e_barra_final(cfg, http, monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://exemplo.supabase.co/rest/v1/")
    http.respostas = [Resposta(200, [])]
    ClienteSupabase().buscar(sku="X")
    assert http.chamadas[0]["url"] == "https://exemplo.supabase.co/rest/v1/products"


def test_erro_401_nao_vaza_a_chave(cfg, http):
    http.respostas = [Resposta(401, {"message": f"Invalid API key {cfg.segredo}", "hint": "confira"})]
    with pytest.raises(ErroEstoque) as e:
        ClienteSupabase().buscar(sku="FB-0123")
    msg = str(e.value)
    assert "401" in msg and "SUPABASE_KEY" in msg
    assert cfg.segredo not in msg
    assert cfg.segredo not in repr(ClienteSupabase())


def test_erro_403_e_outros_status(cfg, http):
    http.respostas = [Resposta(403, {"message": "permission denied"}), Resposta(500, None, texto="falhou")]
    with pytest.raises(ErroEstoque, match="403"):
        ClienteSupabase().buscar(sku="A")
    with pytest.raises(ErroEstoque, match="HTTP 500"):
        ClienteSupabase().buscar(sku="A")


def test_erro_de_rede_e_tempo_limite(cfg, http):
    http.respostas = [
        requests.ConnectionError(f"falhou com apikey={cfg.segredo}"),
        requests.Timeout("demorou"),
    ]
    with pytest.raises(ErroEstoque) as e:
        ClienteSupabase().buscar(sku="A")
    assert "Sem conexão" in str(e.value) and cfg.segredo not in str(e.value)
    with pytest.raises(ErroEstoque, match="não respondeu"):
        ClienteSupabase().buscar(sku="A")


def test_sem_chave_no_env(cfg, tmp_path, monkeypatch):
    env = tmp_path / "vazio.env"
    env.write_text("SUPABASE_URL=https://exemplo.supabase.co\nSUPABASE_KEY=\n", encoding="utf-8")
    monkeypatch.setenv("ROTINAS_ENV", str(env))
    with pytest.raises(ErroEstoque, match="Falta SUPABASE_KEY no .env"):
        ClienteSupabase()


def test_resposta_que_nao_e_json(cfg, http):
    http.respostas = [Resposta(200, None, texto="<html>")]
    with pytest.raises(ErroEstoque, match="inesperada"):
        ClienteSupabase().buscar(sku="A")


def test_fallback_pgrst200_em_duas_etapas(cfg, http):
    erro = {"code": "PGRST200", "message": "Could not find a relationship between 'products' and 'product_variations'"}
    produtos = [
        {"id": 1, "sku": "FB-1", "name": "Conjunto Linho", "category": "Conjuntos", "status": "Ativo", "sale_price": 150},
        {"id": 2, "sku": "FB-2", "name": "Conjunto Seda", "category": "Conjuntos", "status": "Ativo", "sale_price": None},
    ]
    variacoes = [
        {"product_id": 2, "color": "Azul", "size": "M", "stock": 1},
        {"product_id": 1, "color": "Bege", "size": "P", "stock": 4},
    ]
    http.respostas = [Resposta(400, erro), Resposta(200, produtos), Resposta(200, variacoes)]
    achados = ClienteSupabase().buscar(termo="conjunto")
    assert [p.sku for p in achados] == ["FB-1", "FB-2"]
    assert achados[0].estoque_por_cor() == {"Bege": 4}
    assert achados[1].estoque_por_cor() == {"Azul": 1}
    assert achados[1].preco is None
    etapa1, etapa2 = _params(http.chamadas[1]), _params(http.chamadas[2])
    assert etapa1["select"] == "id,sku,name,category,status,sale_price"
    assert etapa1["name"] == "ilike.*conjunto*" and etapa1["status"] == "eq.Ativo" and etapa1["deleted_at"] == "is.null"
    assert http.chamadas[2]["url"].endswith("/rest/v1/product_variations")
    assert etapa2 == {"select": "product_id,color,size,stock", "product_id": "in.(1,2)"}
    assert all("cost_price" not in _texto_da_chamada(c) for c in http.chamadas)


def test_outro_erro_400_nao_cai_no_fallback(cfg, http):
    http.respostas = [Resposta(400, {"code": "PGRST100", "message": "parse error"})]
    with pytest.raises(ErroEstoque, match="PGRST100"):
        ClienteSupabase().buscar(sku="A")
    assert len(http.chamadas) == 1


def test_trava_contra_cost_price_e_asterisco():
    with pytest.raises(ErroEstoque, match="cost_price"):
        estoque._conferir_params([("select", "id,cost_price")])
    with pytest.raises(ErroEstoque, match="nunca"):
        estoque._conferir_params([("select", "*")])
    with pytest.raises(ErroEstoque, match="cost_price"):
        estoque._conferir_params([("cost_price", "gt.0")])


def test_buscar_sem_sku_nem_termo(cfg):
    with pytest.raises(ErroEstoque, match="SKU ou um termo"):
        ClienteFalso([]).buscar()


# ------------------------------------------------------------ cliente falso e resolução

PRODUTOS_FALSOS = [
    {"id": 1, "sku": "FB-0123", "name": "Vestido Midi Alça", "category": "Vestidos", "status": "Ativo", "sale_price": 189.9,
     "product_variations": [{"color": "Verde Musgo", "size": "M", "stock": 2}, {"color": "Preto", "size": "M", "stock": 0}]},
    {"id": 2, "sku": "FB-0124", "nome": "Vestido Longo Festa", "categoria": "Vestidos de Festa", "status": "Ativo",
     "variacoes": [{"cor": "Azul Marinho", "tamanho": "P", "estoque": 1}]},
    {"id": 3, "sku": "FB-0999", "name": "Vestido Antigo", "status": "Inativo", "product_variations": []},
    {"id": 4, "sku": "FB-0998", "name": "Vestido Excluído", "status": "Ativo", "deleted_at": "2026-01-01", "product_variations": []},
]


def test_cliente_padrao_com_estoque_falso(cfg, tmp_path, monkeypatch):
    arq = tmp_path / "estoque.json"
    arq.write_text(json.dumps({"produtos": PRODUTOS_FALSOS}), encoding="utf-8")
    monkeypatch.setenv("ROTINAS_ESTOQUE_FALSO", str(arq))
    cliente = estoque.cliente_padrao()
    assert isinstance(cliente, ClienteFalso)
    assert [p.sku for p in cliente.buscar(termo="vestido")] == ["FB-0124", "FB-0123"]  # sem inativo/excluído
    assert [p.nome for p in cliente.buscar(sku="FB-0123")] == ["Vestido Midi Alça"]
    assert cliente.buscar(termo="VESTIDO MIDI")[0].sku == "FB-0123"
    assert cliente.buscar(termo="midi*alça")[0].sku == "FB-0123"


def test_cliente_padrao_sem_falso_e_supabase(cfg, monkeypatch):
    monkeypatch.delenv("ROTINAS_ESTOQUE_FALSO", raising=False)
    assert isinstance(estoque.cliente_padrao(), ClienteSupabase)
    monkeypatch.setenv("ROTINAS_ESTOQUE_FALSO", "/nao/existe.json")
    with pytest.raises(ErroEstoque, match="não existe"):
        estoque.cliente_padrao()


def test_resolver_produto(cfg):
    cliente = ClienteFalso(PRODUTOS_FALSOS)
    assert estoque.resolver_produto(cliente, sku="FB-0123").nome == "Vestido Midi Alça"
    assert estoque.resolver_produto(cliente, termo="longo").sku == "FB-0124"
    # SKU e termo: o SKU exato vence mesmo com outros nomes casando
    assert estoque.resolver_produto(cliente, sku="FB-0124", termo="vestido").sku == "FB-0124"
    with pytest.raises(ErroEstoque) as e:
        estoque.resolver_produto(cliente, termo="vestido")
    assert "FB-0123" in str(e.value) and "FB-0124" in str(e.value) and "Informe o SKU" in str(e.value)
    assert {c["sku"] for c in e.value.candidatos} == {"FB-0123", "FB-0124"}
    with pytest.raises(ErroEstoque, match="Nenhum produto ativo"):
        estoque.resolver_produto(cliente, sku="FB-0999")  # inativo


def test_normalizar_cor():
    assert estoque.normalizar_cor("  Verde   Água ") == "verde agua"
    assert estoque.normalizar_cor("CORAÇÃO") == "coracao"
    assert estoque.normalizar_cor(None) == ""


def test_produto_junta_grafias_da_mesma_cor_e_ignora_negativo():
    p = Produto(id=1, sku="X", nome="Y", variacoes=[
        {"cor": "Verde", "tamanho": "P", "estoque": 2},
        {"cor": "verde ", "tamanho": "M", "estoque": 1},
        {"cor": "Rosa", "tamanho": "M", "estoque": -1},
        {"cor": "Rosa", "tamanho": "G", "estoque": None},
    ])
    assert p.estoque_por_cor() == {"Rosa": 0, "Verde": 3}
    assert p.total == 3
    d = p.como_dict(com_variacoes=False)
    assert set(d) == {"sku", "nome", "categoria", "preco", "estoque_por_cor", "total"}
    assert "variacoes" in p.como_dict()


# ------------------------------------------------------------ avaliar_letra

def produto(**cores_estoque):
    variacoes = []
    for cor, qtd in cores_estoque.items():
        variacoes.append({"cor": cor.replace("_", " "), "tamanho": "M", "estoque": qtd})
    return Produto(id=1, sku="FB-0123", nome="Vestido Midi Alça", categoria="Vestidos", preco=189.9, variacoes=variacoes)


def test_avaliar_tudo_aprovado_e_acento():
    p = produto(Verde_Água=2, Preto=1)
    r = estoque.avaliar_letra("A", {"midias": {"A - 1": ["verde agua"], "A - 2": ["Preto"], "A - 3": ["VERDE ÁGUA", "preto"]}}, p)
    assert r["status"] == "ok" and r["motivo"] is None
    assert r["aprovadas"] == ["A - 1", "A - 2", "A - 3"]
    assert r["cortadas"] == [] and r["cores_sem_estoque"] == []
    assert r["cores_aprovadas"] == ["Verde Água", "Preto"]
    assert r["cores_por_midia"]["A - 3"] == ["Verde Água", "Preto"]
    assert r["avisos"] == []
    assert r["produto"] == {"sku": "FB-0123", "nome": "Vestido Midi Alça", "categoria": "Vestidos", "preco": 189.9,
                            "estoque_por_cor": {"Preto": 1, "Verde Água": 2}, "total": 3}


def test_avaliar_cor_aproximada_gera_aviso():
    p = produto(Verde_Musgo=2, Preto=1)
    r = estoque.avaliar_letra("A", {"midias": {"A - 1": ["verde"], "A - 2": ["musgo"]}}, p)
    assert r["aprovadas"] == ["A - 1", "A - 2"]
    assert r["cores_aprovadas"] == ["Verde Musgo"]
    assert any("cor aproximada" in a and "Verde Musgo" in a for a in r["avisos"])


def test_avaliar_cor_ambigua_da_erro_e_nao_corta():
    p = produto(Azul_Marinho=2, Azul_Bebê=0)
    with pytest.raises(ErroEstoque) as e:
        estoque.avaliar_letra("A", {"midias": {"A - 1": ["azul"]}}, p)
    msg = str(e.value)
    assert "ambígua" in msg and "Azul Marinho" in msg and "Azul Bebê" in msg
    assert "nenhuma mídia foi cortada" in msg


def test_avaliar_cor_desconhecida_lista_cores_validas():
    p = produto(Verde=2, Preto=0)
    with pytest.raises(ErroEstoque) as e:
        estoque.avaliar_letra("A", {"midias": {"A - 1": ["verde"], "A - 2": ["roxo"], "A - 3": ["lilás"]}}, p)
    msg = str(e.value)
    assert "'roxo' não existe" in msg and "'lilás' não existe" in msg  # todos os problemas de uma vez
    assert "Verde (2)" in msg and "Preto (0)" in msg
    assert e.value.cores_validas == ["Preto", "Verde"]


def test_avaliar_midia_sem_cor_e_de_outra_letra():
    p = produto(Verde=2)
    with pytest.raises(ErroEstoque, match="pelo menos 1 cor"):
        estoque.avaliar_letra("A", {"midias": {"A - 1": []}}, p)
    with pytest.raises(ErroEstoque, match="não é da letra A"):
        estoque.avaliar_letra("A", {"midias": {"B - 1": ["verde"]}}, p)


def test_avaliar_midia_com_duas_cores_uma_sem_estoque_e_cortada():
    p = produto(Verde=2, Preto=0)
    ident = {"midias": {"A - 1": ["verde", "preto"], "A - 2": ["verde"], "A - 3": ["preto"]}}
    r = estoque.avaliar_letra("A", ident, p)
    assert r["status"] == "ok"
    assert r["aprovadas"] == ["A - 2"]
    assert r["cortadas"] == [
        {"nome": "A - 1", "motivo": "cor sem estoque", "detalhe": "Preto", "cores": ["Preto"]},
        {"nome": "A - 3", "motivo": "cor sem estoque", "detalhe": "Preto", "cores": ["Preto"]},
    ]
    assert r["cores_sem_estoque"] == ["Preto"]
    assert r["cores_aprovadas"] == ["Verde"]
    assert any("Preto" in a and "A - 1" in a for a in r["avisos"])


def test_avaliar_modelo_zerado_corta_a_letra_sem_erro_de_cor():
    p = produto(Verde=0, Preto=0)
    r = estoque.avaliar_letra("A", {"midias": {"A - 1": ["verde"], "A - 2": ["cor inventada"], "A - 3": []}}, p)
    assert r["status"] == "cortada" and r["motivo"] == "modelo sem nenhuma peça"
    assert r["aprovadas"] == []
    assert [c["nome"] for c in r["cortadas"]] == ["A - 1", "A - 2", "A - 3"]
    assert {c["motivo"] for c in r["cortadas"]} == {"modelo sem nenhuma peça"}
    assert r["cores_sem_estoque"] == ["Verde"]


def test_avaliar_produto_sem_variacoes_e_modelo_zerado():
    p = Produto(id=1, sku="FB-1", nome="Sem grade", variacoes=[])
    r = estoque.avaliar_letra("C", {"midias": {"C - 1": ["verde"]}}, p)
    assert r["status"] == "cortada" and r["motivo"] == "modelo sem nenhuma peça"
    assert any("nenhuma variação" in a for a in r["avisos"])


def test_avaliar_todas_cortadas_por_cor():
    p = produto(Verde=3, Preto=0, Rosa=0)
    r = estoque.avaliar_letra("B", {"midias": {"B - 1": ["preto"], "B - 2": ["rosa"]}}, p)
    assert r["status"] == "cortada" and r["motivo"] == "nenhuma mídia com estoque"
    assert r["aprovadas"] == [] and r["cores_aprovadas"] == []
    assert r["cores_sem_estoque"] == ["Preto", "Rosa"]


def test_avaliar_excluir():
    p = produto(Verde=3)
    ident = {"midias": {"A - 1": ["verde"], "A - 2": ["cor que nao existe"], "A - 3": ["verde"]},
             "excluir": {"A - 2": "tremido", "A - 4": "duplicada"}}
    r = estoque.avaliar_letra("A", ident, p)
    assert r["aprovadas"] == ["A - 1", "A - 3"]
    assert r["cortadas"] == [
        {"nome": "A - 2", "motivo": "excluída", "detalhe": "tremido", "cores": ["cor que nao existe"]},
        {"nome": "A - 4", "motivo": "excluída", "detalhe": "duplicada", "cores": []},
    ]
    assert r["status"] == "ok"
    r = estoque.avaliar_letra("A", {"midias": {"A - 1": ["verde"]}, "excluir": {"A - 1": "ruim"}}, p)
    assert r["status"] == "cortada" and r["motivo"] == "nenhuma mídia para postar"


def test_avaliar_ordem_numerica_e_nome_com_extensao():
    p = produto(Verde=3)
    r = estoque.avaliar_letra("a", {"midias": {"A - 10": ["verde"], "A - 2.jpg": ["verde"], "A - 1.mp4": "verde"}}, p)
    assert r["letra"] == "A"
    assert r["aprovadas"] == ["A - 1", "A - 2", "A - 10"]


# ------------------------------------------------------------ tarefa e terminal

@pytest.fixture
def falso(cfg, tmp_path, monkeypatch):
    arq = tmp_path / "estoque.json"
    arq.write_text(json.dumps(PRODUTOS_FALSOS), encoding="utf-8")
    monkeypatch.setenv("ROTINAS_ESTOQUE_FALSO", str(arq))
    return arq


def test_tarefa(falso, tmp_path):
    ctx = Contexto(pasta_saida=tmp_path / "saida")
    r = estoque.tarefa({"consultas": [{"sku": "FB-0123"}, {"termo": "inexistente"}]}, ctx)
    assert r["consultas"][0]["encontrados"] == 1
    prod = r["consultas"][0]["produtos"][0]
    assert prod["estoque_por_cor"] == {"Preto": 0, "Verde Musgo": 2}
    assert "cost_price" not in json.dumps(r)
    assert r["consultas"][1]["encontrados"] == 0
    assert "nenhum produto ativo" in (tmp_path / "saida" / "estoque.txt").read_text(encoding="utf-8")
    with pytest.raises(ErroEstoque):
        estoque.tarefa({}, ctx)


def test_cli_tabela(falso, capsys):
    assert estoque.cli(["--sku", "FB-0123"]) == 0
    saida = capsys.readouterr().out
    assert "FB-0123 · Vestido Midi Alça · Vestidos · R$ 189,90 · total 2" in saida
    linhas = saida.splitlines()
    assert any(l.split()[:2] == ["Cor", "M"] for l in linhas)
    assert any("Preto" in l and "sem estoque" in l for l in linhas)
    assert any(l.split() == ["Verde", "Musgo", "2", "2"] for l in linhas)


def test_cli_json_e_nao_encontrado(falso, capsys):
    assert estoque.cli(["--termo", "longo", "--json"]) == 0
    dados = json.loads(capsys.readouterr().out)
    assert dados[0]["sku"] == "FB-0124" and dados[0]["total"] == 1
    assert estoque.cli(["--termo", "nada disso"]) == 1
    assert "nenhum produto" in capsys.readouterr().out


def test_texto_ordem_dos_tamanhos(cfg):
    p = Produto(id=1, sku="X", nome="Y", variacoes=[
        {"cor": "Azul", "tamanho": "GG", "estoque": 1},
        {"cor": "Azul", "tamanho": "P", "estoque": 1},
        {"cor": "Azul", "tamanho": "G", "estoque": 1},
        {"cor": "Azul", "tamanho": "M", "estoque": 1},
    ])
    cabecalho = estoque.texto_produto(p).splitlines()[1].split()
    assert cabecalho == ["Cor", "P", "M", "G", "GG", "Total"]


# ------------------------------------------------------------ revisão

def test_avaliar_nome_fora_do_padrao_da_erro_e_letra_minuscula_normaliza():
    p = produto(Verde=3)
    with pytest.raises(ErroEstoque, match="fora do padrão"):
        estoque.avaliar_letra("A", {"midias": {"A - 1": ["verde"], "IMG_0001.jpg": ["verde"]}}, p)
    with pytest.raises(ErroEstoque, match="fora do padrão"):
        estoque.avaliar_letra("A", {"midias": {"A - 1": ["verde"]}, "excluir": {"A1": "ruim"}}, p)
    r = estoque.avaliar_letra("A", {"midias": {"a - 2.JPG": ["verde"]}}, p)
    assert r["aprovadas"] == ["A - 2"]
    with pytest.raises(ErroEstoque, match="não é da letra A"):
        estoque.avaliar_letra("A", {"midias": {"b - 1": ["verde"]}}, p)


def test_cliente_padrao_aceita_caminho_com_aspas_e_espaco(cfg, tmp_path, monkeypatch):
    pasta = tmp_path / "Área de Trabalho"
    pasta.mkdir()
    arq = pasta / "estoque falso.json"
    arq.write_text(json.dumps(PRODUTOS_FALSOS), encoding="utf-8")
    monkeypatch.setenv("ROTINAS_ESTOQUE_FALSO", f'"{arq}"')  # `set VAR="..."` no cmd guarda as aspas
    assert isinstance(estoque.cliente_padrao(), ClienteFalso)


def test_fallback_tambem_para_relacao_ambigua_pgrst201(cfg, http):
    erro = {"code": "PGRST201", "message": "Could not embed because more than one relationship was found"}
    http.respostas = [Resposta(300, erro), Resposta(200, [dict(LINHA, product_variations=None)]),
                      Resposta(200, [{"product_id": 7, "color": "Verde", "size": "M", "stock": 1}])]
    achados = ClienteSupabase().buscar(sku="FB-0123")
    assert achados[0].estoque_por_cor() == {"Verde": 1}
    assert len(http.chamadas) == 3
