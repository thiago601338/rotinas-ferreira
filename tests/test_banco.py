import json

import pytest

from conftest import RespostaFalsa
from rotinas import banco


def test_login_uma_vez_e_token_guardado(cfg, supabase_falso):
    s = banco.Sessao()
    s.get("products", [("select", "id")])
    banco.Sessao().get("product_variations", [("select", "color")])
    assert len(supabase_falso.posts) == 1  # o segundo pedido reaproveita o token
    login = supabase_falso.posts[0]
    assert login["url"] == "https://exemplo.supabase.co/auth/v1/token"
    assert login["params"] == {"grant_type": "password"} and login["headers"]["apikey"] == cfg.segredo
    assert all(g["headers"]["Authorization"] == f"Bearer {cfg.token}" for g in supabase_falso.gets)


def test_token_expirado_faz_novo_login_uma_vez(cfg, supabase_falso):
    supabase_falso.leituras = [RespostaFalsa(401, {"message": "JWT expired"}), RespostaFalsa(200, [{"id": 1}])]
    r = banco.Sessao().get("products", [("select", "id")])
    assert r.status_code == 200 and len(supabase_falso.posts) == 2 and len(supabase_falso.gets) == 2


def test_so_le_as_tabelas_das_rotinas(cfg, supabase_falso):
    with pytest.raises(banco.ErroBanco, match="não é das rotinas"):
        banco.Sessao().get("customers", [("select", "id")])
    assert supabase_falso.gets == []
    assert not hasattr(banco.Sessao, "post") and not hasattr(banco.Sessao, "patch")


def test_falta_usuario_no_env(cfg, tmp_path, monkeypatch):
    env = tmp_path / "x.env"
    env.write_text("SUPABASE_URL=https://exemplo.supabase.co\nSUPABASE_KEY=chave-publica-123\n", encoding="utf-8")
    monkeypatch.setenv("ROTINAS_ENV", str(env))
    assert banco.faltando() == ["SUPABASE_EMAIL", "SUPABASE_SENHA"]
    with pytest.raises(banco.ErroBanco, match="SUPABASE_EMAIL, SUPABASE_SENHA"):
        banco.Sessao()


@pytest.mark.parametrize("resposta, trecho", [
    (RespostaFalsa(400, {"error_code": "invalid_credentials", "msg": "Invalid login credentials"}), "SUPABASE_SENHA"),
    (RespostaFalsa(400, {"error_code": "email_not_confirmed"}), "Auto Confirm"),
    (RespostaFalsa(401, {"message": "Invalid API key"}), "SUPABASE_KEY"),
])
def test_erros_de_login_claros_e_sem_segredo(cfg, supabase_falso, resposta, trecho):
    supabase_falso.login = resposta
    with pytest.raises(banco.ErroBanco) as e:
        banco.Sessao().token()
    assert trecho in str(e.value)
    for segredo in (cfg.senha, cfg.segredo):
        assert segredo not in str(e.value)
    assert cfg.senha not in repr(banco.Sessao())


def test_testar_leitura_vazia_nao_e_ok(cfg, supabase_falso):
    supabase_falso.leituras = [RespostaFalsa(200, [])]
    r = banco.testar_leitura()
    assert r["ok"] is False and "RLS" in r["mensagem"]
    assert cfg.senha not in json.dumps(r)
