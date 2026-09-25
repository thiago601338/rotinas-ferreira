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
    env.write_text(f"SUPABASE_URL=https://exemplo.supabase.co\nSUPABASE_KEY={SEGREDO_FALSO}\n", encoding="utf-8")
    monkeypatch.setenv("ROTINAS_CONFIG_DIR", str(pasta_cfg))
    monkeypatch.setenv("ROTINAS_ENV", str(env))
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_KEY", raising=False)
    config.limpar_cache()
    for p in pastas.values():
        Path(p).mkdir(parents=True, exist_ok=True)

    class C:
        dir = pasta_cfg
        raiz = base
        p = config.pastas()
        segredo = SEGREDO_FALSO

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
