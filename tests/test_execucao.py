"""Ciclo de teste do PC: saneamento da pasta de execução e envio só dela pelo git (repositório local + remoto bare)."""

import json
import subprocess
from pathlib import Path

import pytest

from rotinas import diagnostico, execucao, ferramentas


def git(pasta, *args, verificar=True):
    r = subprocess.run(["git", *args], cwd=pasta, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if verificar and r.returncode != 0:
        raise AssertionError(f"git {' '.join(args)}: {r.stderr}")
    return r.stdout


def alterar_execucao(cfg, **valores):
    d = json.loads((cfg.dir / "diagnostico.json").read_text(encoding="utf-8"))["execucao"]
    d.update(valores)
    cfg.alterar("diagnostico", execucao=d)


def alvo_eco(ctx, argv):
    """Alvo falso: grava de tudo um pouco, inclusive o que não pode ir para o git."""
    from rotinas import config

    segredo = config.segredo("SUPABASE_KEY")
    ctx.arquivo("saida.txt").write_text(f"chave usada: {segredo}\n", encoding="utf-8")
    ctx.arquivo("dados.json").write_text(json.dumps({"chave": segredo, "argv": argv}), encoding="utf-8")
    ctx.arquivo("tela.xml").write_text(f'<hierarchy><node text="{segredo}"/></hierarchy>', encoding="utf-8")
    ctx.arquivo("sub/extra.log").write_text("apikey=abcdef123456\n", encoding="utf-8")
    ctx.arquivo("sem_extensao").write_text(f"token {segredo}\n", encoding="utf-8")
    ctx.arquivo(".env").write_text(f"SUPABASE_KEY={segredo}\n", encoding="utf-8")
    ctx.arquivo("video.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42")
    ctx.arquivo("grande.bin").write_bytes(b"\x00" * 3000)
    ctx.arquivo("print.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    return {"ok": True, "argv": argv, "ensaio": ctx.ensaio}


def alvo_falha(ctx, argv):
    erro = RuntimeError("parou no passo 3")
    erro.resultado_parcial = {"passo": 3}
    raise erro


class Repo(type(Path())):
    """Caminho do clone local, com o remoto bare em ``.remoto``."""


@pytest.fixture
def git_isolado(tmp_path, monkeypatch):
    casa = tmp_path / "casa"
    casa.mkdir()
    (casa / ".gitconfig").write_text("", encoding="utf-8")
    monkeypatch.setenv("HOME", str(casa))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(casa / ".gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_TERMINAL_PROMPT", "0")
    for var in ("GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS", "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL",
                "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL", "EMAIL"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def repo(cfg, tmp_path, git_isolado, monkeypatch):
    """Clone local com remoto bare; git do PC sem nome/e-mail (usa o autor padrão da config)."""
    remoto = tmp_path / "remoto.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remoto))
    local = Repo(tmp_path / "repo")
    git(tmp_path, "clone", "-q", str(remoto), str(local))
    (local / "README.md").write_text("inicial\n", encoding="utf-8")
    (local / ".gitignore").write_text(".env\nsaida_local/\nexecucoes/**/*.mp4\n", encoding="utf-8")
    git(local, "add", ".")
    git(local, "-c", "user.name=Teste", "-c", "user.email=t@t", "commit", "-q", "-m", "inicial")
    git(local, "push", "-q", "-u", "origin", "HEAD")
    alterar_execucao(cfg, max_mb_por_arquivo=0.001)
    monkeypatch.setitem(execucao.ALVOS, "eco", "test_execucao:alvo_eco")
    monkeypatch.setitem(execucao.ALVOS, "falha", "test_execucao:alvo_falha")
    monkeypatch.setattr(diagnostico, "versoes_principais", lambda: {"rotinas": "teste", "python": "3.x"})
    local.remoto = remoto  # type: ignore[attr-defined]
    return local


def _arquivos_do_ultimo_commit(pasta_git, ref="HEAD"):
    return [x for x in git(pasta_git, "show", "--name-only", "--format=", ref).splitlines() if x]


# ------------------------------------------------------------ saneamento

def test_sanear_remove_segredo_grande_video_e_env(cfg, tmp_path):
    alterar_execucao(cfg, max_mb_por_arquivo=0.001)
    raiz = tmp_path / "r"
    pasta = raiz / "execucoes" / "2026-09-25_1000_eco"
    pasta.mkdir(parents=True)

    class Ctx:
        ensaio = False

        @staticmethod
        def arquivo(nome):
            p = pasta / nome
            p.parent.mkdir(parents=True, exist_ok=True)
            return p

    alvo_eco(Ctx, [])
    res = execucao.sanear(pasta, raiz)

    for nome in ("saida.txt", "dados.json", "tela.xml", "sub/extra.log", "sem_extensao"):
        texto = (pasta / nome).read_text(encoding="utf-8")
        assert cfg.segredo not in texto, nome
        assert "abcdef123456" not in texto, nome
    assert json.loads((pasta / "dados.json").read_text(encoding="utf-8"))["chave"] == "***"
    assert not (pasta / ".env").exists()
    assert not (pasta / "video.mp4").exists() and not (pasta / "grande.bin").exists()
    guardado = raiz / "saida_local" / "execucoes" / pasta.name
    assert (guardado / "video.mp4").exists() and (guardado / "grande.bin").exists()
    assert (pasta / "print.png").read_bytes() == b"\x89PNG\r\n\x1a\n"
    omitidos = (pasta / "omitidos.txt").read_text(encoding="utf-8")
    assert "video.mp4" in omitidos and "grande.bin" in omitidos and ".env" in omitidos
    assert {o["arquivo"] for o in res["omitidos"]} == {".env", "video.mp4", "grande.bin"}
    assert set(res["ocultados"]) == {"saida.txt", "dados.json", "tela.xml", "sub/extra.log", "sem_extensao"}


def test_sanear_tira_do_git_o_que_nao_conseguiu_conferir(cfg, tmp_path, monkeypatch):
    raiz = tmp_path / "r"
    pasta = raiz / "execucoes" / "x"
    pasta.mkdir(parents=True)
    (pasta / "travado.txt").write_text("aberto por outro programa", encoding="utf-8")
    (pasta / "ok.txt").write_text("normal", encoding="utf-8")
    original = execucao._eh_texto

    def eh_texto(arq, extensoes):
        if arq.name == "travado.txt":
            raise PermissionError("arquivo em uso")
        return original(arq, extensoes)

    monkeypatch.setattr(execucao, "_eh_texto", eh_texto)
    res = execucao.sanear(pasta, raiz)
    assert not (pasta / "travado.txt").exists() and (pasta / "ok.txt").exists()
    assert (raiz / "saida_local" / "execucoes" / "x" / "travado.txt").exists()
    assert res["omitidos"][0]["arquivo"] == "travado.txt"


def test_sanear_recusa_pasta_fora_de_execucoes(cfg, tmp_path):
    pasta = tmp_path / "r" / "fotos"
    pasta.mkdir(parents=True)
    (pasta / "video.mp4").write_bytes(b"x")
    with pytest.raises(ValueError):
        execucao.sanear(pasta, tmp_path / "r")
    assert (pasta / "video.mp4").exists()


# ------------------------------------------------------------ git

def test_testar_commita_so_a_pasta_da_execucao_e_envia(repo, cfg):
    (repo / "README.md").write_text("mexido pelo usuário\n", encoding="utf-8")
    (repo / "solto.txt").write_text("não é da execução\n", encoding="utf-8")
    (repo / "preparado.txt").write_text("já no índice\n", encoding="utf-8")
    git(repo, "add", "preparado.txt")

    r = execucao.testar("eco", ["--data", "2026-09-22"], raiz=repo)

    assert r["codigo"] == 0, r
    assert r["envio"]["enviado"] is True and r["envio"]["commit"]
    rel = r["pasta"].relative_to(repo).as_posix()
    assert rel.startswith("execucoes/") and rel.endswith("_eco")
    enviados = _arquivos_do_ultimo_commit(repo.remoto)
    assert enviados and all(x.startswith(rel + "/") for x in enviados)
    nomes = {x[len(rel) + 1:] for x in enviados}
    assert {"log.txt", "versoes.json", "resultado.json", "saida.txt", "dados.json", "tela.xml", "omitidos.txt"} <= nomes
    assert not nomes & {".env", "video.mp4", "grande.bin"}
    for x in enviados:
        conteudo = git(repo.remoto, "show", f"HEAD:{x}")
        assert cfg.segredo not in conteudo, x
    resultado = json.loads(git(repo.remoto, "show", f"HEAD:{rel}/resultado.json"))
    assert resultado["ok"] is True and resultado["argv"] == ["--data", "2026-09-22"]
    assert "Teste 'eco' começou" in git(repo.remoto, "show", f"HEAD:{rel}/log.txt")
    assert git(repo.remoto, "log", "-1", "--format=%an").strip() == "PC Ferreira Boutique"
    assert git(repo.remoto, "log", "-1", "--format=%s").startswith("Execução ")

    status = git(repo, "status", "--porcelain")
    assert " M README.md" in status and "?? solto.txt" in status and "A  preparado.txt" in status
    assert (repo / "README.md").read_text(encoding="utf-8") == "mexido pelo usuário\n"


def test_push_falha_mantem_commit_local_e_enviar_tenta_de_novo(repo, tmp_path):
    (repo / "README.md").write_text("mexido\n", encoding="utf-8")
    git(repo, "remote", "set-url", "origin", str(tmp_path / "nao_existe.git"))

    r = execucao.testar("eco", raiz=repo)
    assert r["codigo"] == 4
    assert r["envio"]["enviado"] is False and "testar.bat enviar" in r["envio"]["mensagem"]
    assert r["envio"]["commit"] == git(repo, "rev-parse", "HEAD").strip()
    assert "?? execucoes" not in git(repo, "status", "--porcelain")

    git(repo, "remote", "set-url", "origin", str(repo.remoto))
    r2 = execucao.testar("enviar", raiz=repo)
    assert r2["codigo"] == 0 and r2["envio"]["enviado"] is True
    assert git(repo.remoto, "rev-parse", "HEAD").strip() == r["envio"]["commit"]
    assert (repo / "README.md").read_text(encoding="utf-8") == "mexido\n"


def test_sem_git_e_depois_enviar(repo, cfg):
    r = execucao.testar("eco", enviar_git=False, raiz=repo)
    assert r["envio"] is None and r["codigo"] == 0
    rel = r["pasta"].relative_to(repo).as_posix()
    assert f"?? {rel}/log.txt" in git(repo, "status", "--porcelain", "--untracked-files=all")

    r2 = execucao.testar("enviar", raiz=repo)
    assert r2["envio"]["enviado"] is True and r2["envio"]["pastas"] == [r["pasta"].name]
    enviados = _arquivos_do_ultimo_commit(repo.remoto)
    assert enviados and all(x.startswith(rel + "/") for x in enviados)
    assert not any(x.endswith((".env", ".mp4")) for x in enviados)


def test_alvo_com_erro_tambem_vai_para_o_git(repo):
    r = execucao.testar("falha", raiz=repo)
    assert r["codigo"] == 1 and r["envio"]["enviado"] is True
    res = r["resultado"]
    assert res["ok"] is False and res["erro"] == "parou no passo 3" and res["resultado_parcial"] == {"passo": 3}
    assert "com erro" in git(repo.remoto, "log", "-1", "--format=%s")


def test_sem_saneamento_nada_vai_para_o_git(repo, monkeypatch):
    antes = git(repo.remoto, "rev-parse", "HEAD").strip()

    def quebrado(pasta, raiz=None):
        raise RuntimeError("disco cheio")

    monkeypatch.setattr(execucao, "sanear", quebrado)
    r = execucao.testar("eco", raiz=repo)
    assert r["envio"]["enviado"] is False and "Não enviei nada" in r["envio"]["mensagem"]
    assert r["codigo"] == 4
    assert git(repo.remoto, "rev-parse", "HEAD").strip() == antes
    assert git(repo, "rev-parse", "HEAD").strip() == antes


# ------------------------------------------------------------ alvos

def test_alvo_que_ainda_nao_existe_da_erro_claro(cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(diagnostico, "versoes_principais", lambda: {})
    monkeypatch.setitem(execucao.ALVOS, "fantasma", "rotinas.nao_existe_ainda:teste_real")
    monkeypatch.setitem(execucao.ALVOS, "sem-funcao", "rotinas.contexto:teste_real")
    r = execucao.testar("fantasma", enviar_git=False, raiz=tmp_path)
    assert r["codigo"] == 1 and "ainda não existe" in r["resultado"]["erro"]
    assert r["resultado"]["tipo_erro"] == "AlvoIndisponivel"
    assert json.loads((r["pasta"] / "resultado.json").read_text(encoding="utf-8"))["ok"] is False
    r = execucao.testar("sem-funcao", enviar_git=False, raiz=tmp_path)
    assert "não tem a função teste_real" in r["resultado"]["erro"]


def test_alvos_futuros_estao_na_tabela():
    assert execucao.ALVOS["bluestacks"] == "rotinas.stories.bluestacks:teste_real"
    assert execucao.ALVOS["stories-ensaio"] == "rotinas.stories.bluestacks:teste_ensaio"
    assert execucao.ALVOS["capcut-rascunho"] == "rotinas.video.rascunho:teste_real"
    assert execucao.ALVOS["conferir"] == "rotinas.video.conferencia:teste_real"


def test_alvo_pytest_guarda_a_saida(cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(diagnostico, "versoes_principais", lambda: {})
    chamadas = []

    def rodar(cmd, timeout=None, verificar=True, entrada=None, binario=False, cwd=None):
        chamadas.append([str(c) for c in cmd])
        return subprocess.CompletedProcess(cmd, 1, "F.\n1 failed, 1 passed in 0.12s\n", "")

    monkeypatch.setattr(ferramentas, "rodar", rodar)
    r = execucao.testar("pytest", ["-k", "nucleo"], enviar_git=False, raiz=tmp_path)
    assert chamadas[0][1:] == ["-m", "pytest", "-q", "-k", "nucleo"]
    assert r["codigo"] == 1 and r["resultado"]["resultado"]["resumo_pytest"] == "1 failed, 1 passed in 0.12s"
    assert "1 failed" in (r["pasta"] / "pytest.txt").read_text(encoding="utf-8")


def test_alvo_diagnostico_repassa_opcoes(cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(diagnostico, "versoes_principais", lambda: {})
    visto = {}

    def executar(pasta, **opcoes):
        visto.update(opcoes, pasta=pasta)
        return {"problemas": ["nada"], "versoes": {}}

    monkeypatch.setattr(diagnostico, "executar", executar)
    r = execucao.testar("diagnostico", ["--sem-u2", "--projeto", "0926"], enviar_git=False, raiz=tmp_path)
    assert r["codigo"] == 0
    assert visto["u2"] is False and visto["instagram"] is True and visto["projeto"] == "0926"
    assert visto["pasta"] == r["pasta"]
    assert r["resultado"]["resultado"]["problemas"] == ["nada"]


# ------------------------------------------------------------ linha de comando

def test_cli_sem_alvo_mostra_a_lista(capsys):
    assert execucao.cli([]) == 0
    saida = capsys.readouterr().out
    assert "diagnostico" in saida and "stories-ensaio" in saida and "enviar" in saida


def test_cli_alvo_desconhecido(capsys):
    assert execucao.cli(["nao-existe"]) == 2
    assert "Alvo desconhecido" in capsys.readouterr().err


def test_cli_repassa_argumentos_e_sem_git(monkeypatch, capsys):
    visto = {}

    def testar(alvo, extra=None, enviar_git=True, raiz=None):
        visto.update(alvo=alvo, extra=extra, enviar_git=enviar_git)
        return {"codigo": 0, "pasta": Path("x"), "resultado": {"ok": True}, "saneamento": {}, "envio": None}

    monkeypatch.setattr(execucao, "testar", testar)
    assert execucao.cli(["stories-ensaio", "--data", "2026-09-22", "--sem-git"]) == 0
    assert visto == {"alvo": "stories-ensaio", "extra": ["--data", "2026-09-22"], "enviar_git": False}
    assert "--sem-git" in capsys.readouterr().out


def test_todo_alvo_aponta_para_funcao_que_existe():
    """Cada alvo do testar.bat resolve para uma função importável (pega texto trocado por engano na tabela)."""
    import importlib

    from rotinas import execucao

    for alvo, destino in execucao.ALVOS.items():
        if not isinstance(destino, str):
            assert callable(destino), alvo
            continue
        assert ":" in destino, f"{alvo}: {destino!r}"
        modulo, funcao = destino.split(":", 1)
        assert callable(getattr(importlib.import_module(modulo), funcao)), alvo
    assert set(execucao.DESCRICOES) >= set(execucao.ALVOS) - {"enviar"}
