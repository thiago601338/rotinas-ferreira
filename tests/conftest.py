import json
import shutil
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from rotinas import config  # noqa: E402

SEGREDO_FALSO = "eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoiYW5vbiJ9.segredoFalsoDeTeste123"
SENHA_FALSA = "SenhaFalsa-das-rotinas-123"
TOKEN_FALSO = "eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoiYXV0aGVudGljYXRlZCJ9.tokenFalsoDeTeste456"


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    """Config isolada: pastas em tmp_path, .env falso. Devolve um objeto com os caminhos."""
    pasta_cfg = tmp_path / "config"
    shutil.copytree(RAIZ / "config", pasta_cfg)
    base = tmp_path / "pc"
    pastas = {
        "stories_fonte": str(base / "Stories da Loja"),
        "rotinas": str(base / "Rotinas Ferreira"),
        "sistema": str(RAIZ),
        "capcut_rascunhos": str(base / "CapCut" / "com.lveditor.draft"),
        "capcut_apps": str(base / "CapCut" / "Apps"),
        "videos": str(base / "Rotinas Ferreira" / "videos"),
    }
    (pasta_cfg / "pastas.json").write_text(json.dumps(pastas), encoding="utf-8")
    env = tmp_path / ".env"
    env.write_text(f"SUPABASE_URL=https://exemplo.supabase.co\nSUPABASE_KEY={SEGREDO_FALSO}\n"
                   f"SUPABASE_EMAIL=rotinas@exemplo.com\nSUPABASE_SENHA={SENHA_FALSA}\n", encoding="utf-8")
    monkeypatch.setenv("ROTINAS_CONFIG_DIR", str(pasta_cfg))
    monkeypatch.setenv("ROTINAS_ENV", str(env))
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_EMAIL", raising=False)
    monkeypatch.delenv("SUPABASE_SENHA", raising=False)
    config.limpar_cache()
    for p in pastas.values():
        Path(p).mkdir(parents=True, exist_ok=True)

    class C:
        dir = pasta_cfg
        raiz = base
        p = config.pastas()
        segredo = SEGREDO_FALSO
        senha = SENHA_FALSA
        token = TOKEN_FALSO

        @staticmethod
        def alterar(nome, **valores):
            arq = pasta_cfg / f"{nome}.json"
            d = json.loads(arq.read_text(encoding="utf-8"))
            d.update(valores)
            arq.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
            config.limpar_cache()

    yield C
    config.limpar_cache()


def pytest_collection_modifyitems(config, items):
    if shutil.which("ffmpeg") and shutil.which("ffprobe"):
        return
    pular = pytest.mark.skip(reason="ffmpeg não instalado")
    for item in items:
        if "ffmpeg" in item.keywords:
            item.add_marker(pular)


@pytest.fixture(autouse=True)
def _sem_token_guardado():
    """O token de login do Supabase fica em memória: cada teste começa sem ele."""
    from rotinas import banco

    banco.limpar_cache()
    yield
    banco.limpar_cache()


class RespostaFalsa:
    def __init__(self, status=200, dados=None, texto=None):
        self.status_code = status
        self._dados = dados
        self.text = texto if texto is not None else json.dumps(dados)

    def json(self):
        if self._dados is None:
            raise ValueError("sem json")
        return self._dados


@pytest.fixture
def supabase_falso(monkeypatch):
    """Troca ``requests.post`` (login) e ``requests.get`` (leitura). ``login``/``leituras`` = próximas respostas
    (padrão: login ok e 1 produto); ``posts``/``gets`` registram as chamadas."""
    import requests

    class Falso:
        posts, gets = [], []
        login = None
        leituras = []

        @staticmethod
        def post(url, params=None, headers=None, json=None, timeout=None):
            Falso.posts.append({"url": url, "params": params, "headers": dict(headers or {}), "json": json})
            r = Falso.login if Falso.login is not None else RespostaFalsa(200, {"access_token": TOKEN_FALSO, "expires_in": 3600})
            if isinstance(r, Exception):
                raise r
            return r

        @staticmethod
        def get(url, params=None, headers=None, timeout=None):
            Falso.gets.append({"url": url, "params": list(params or []), "headers": dict(headers or {}), "timeout": timeout})
            r = Falso.leituras.pop(0) if Falso.leituras else RespostaFalsa(200, [{"id": 1}])
            if isinstance(r, Exception):
                raise r
            return r

    monkeypatch.setattr(requests, "post", Falso.post)
    monkeypatch.setattr(requests, "get", Falso.get)
    return Falso
