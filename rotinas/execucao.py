"""Ciclo de teste no PC (BRIEFING §6): ``testar.bat <alvo> [argumentos do alvo]``.

Cria ``execucoes/<aaaa-mm-dd_hhmm>_<alvo>/`` na raiz do repositório com ``log.txt``,
``versoes.json``, ``resultado.json`` e o que o alvo gravar (prints, XML). Antes de enviar,
saneia a pasta (sem segredos, sem ``.env``, sem vídeo nem arquivo grande) e faz commit só dessa
pasta + ``git pull --rebase --autostash`` + ``git push``. Na nuvem é só dar ``git pull``.

Alvos: tabela ``ALVOS`` (alvo → ``"modulo:funcao"``, assinatura ``funcao(ctx, argv_extra) -> dict``).
Importação preguiçosa: alvo de módulo que ainda não existe dá erro claro, sem derrubar os outros.
``testar enviar`` tenta de novo o envio do que ficou só no PC.
"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import os
import re
import shutil
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

from . import config, diagnostico, ferramentas, privacidade, registro
from .contexto import Contexto, carimbo

log = registro.obter("execucao")

ENVIAR = "enviar"

ALVOS: dict[str, str] = {
    "diagnostico": "rotinas.execucao:alvo_diagnostico",
    "verificar": "rotinas.execucao:alvo_verificar",
    "pytest": "rotinas.execucao:alvo_pytest",
    "bluestacks": "rotinas.stories.bluestacks:teste_real",
    "stories-ensaio": "rotinas.stories.bluestacks:teste_ensaio",
    "capcut-rascunho": "rotinas.video.rascunho:teste_real",
    "conferir": "rotinas.video.conferencia:teste_real",
}

DESCRICOES: dict[str, str] = {
    "diagnostico": "versões, pastas, .env (só nomes), ADB do BlueStacks, tela do Instagram, gabarito 0925 do CapCut, Supabase",
    "verificar": "confere a instalação (python -m rotinas verificar --json)",
    "pytest": "roda os testes automáticos aqui no PC",
    "bluestacks": "teste real no BlueStacks (stories, A5)",
    "stories-ensaio": "stories em modo ensaio (--data D, --plano arquivo ou --sintetico): monta tudo e para antes de publicar",
    "capcut-rascunho": "gera um rascunho de teste no CapCut (B3)",
    "conferir": "confere um vídeo exportado (B4)",
    ENVIAR: "tenta de novo enviar pelo git as execuções que ficaram só no PC",
}

BINARIOS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".heic", ".heif", ".ico", ".mp3", ".wav", ".m4a",
            ".aac", ".ogg", ".flac", ".zip", ".7z", ".gz", ".db", ".sqlite", ".pdf", ".ttf", ".otf", ".exe", ".dll"}


class AlvoIndisponivel(RuntimeError):
    """O alvo ainda não existe nesta versão do repositório (ou falta um pacote)."""


def _cfg() -> dict:
    return config.carregar("diagnostico")["execucao"]


def _gravar_json(caminho: Path, dados: dict) -> None:
    diagnostico.gravar_json(caminho, dados)


def _agora() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def lista_alvos() -> str:
    largura = max(len(n) for n in DESCRICOES)
    linhas = ["Alvos:"]
    linhas += [f"  {n.ljust(largura)}  {d}" for n, d in DESCRICOES.items()]
    linhas += ["", "Exemplos: testar.bat diagnostico", "          testar.bat stories-ensaio --data 2026-09-22",
               "          testar.bat enviar", "Opção --sem-git: grava a pasta mas não envia pelo git."]
    return "\n".join(linhas)


# ---------------------------------------------------------------- alvos internos

def alvo_diagnostico(ctx: Contexto, argv_extra: list[str]) -> dict:
    a = diagnostico.parser().parse_args(argv_extra)
    dados = diagnostico.executar(ctx.pasta_saida, **diagnostico.opcoes(a))
    return {"arquivo": "diagnostico.json", "problemas": dados.get("problemas"), "resumo": diagnostico.resumo(dados)}


def _utf8_nos_filhos() -> None:
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    os.environ.setdefault("PYTHONUTF8", "1")


def alvo_verificar(ctx: Contexto, argv_extra: list[str]) -> dict:
    if importlib.util.find_spec("rotinas.instalacao") is None:
        raise AlvoIndisponivel("O 'verificar' ainda não existe nesta versão (falta rotinas/instalacao.py). "
                               "Rode o atualizar.bat e tente de novo.")
    _utf8_nos_filhos()
    r = ferramentas.rodar(
        [sys.executable, "-m", "rotinas", "verificar", "--json", *argv_extra],
        timeout=float(config.carregar("diagnostico")["verificar_timeout_s"]), verificar=False, cwd=config.RAIZ,
    )
    try:
        dados = json.loads(r.stdout or "")
        _gravar_json(ctx.arquivo("verificar.json"), dados if isinstance(dados, dict) else {"resultado": dados})
    except ValueError:
        dados = None
        ctx.arquivo("verificar.txt").write_text(registro.ocultar(r.stdout or ""), encoding="utf-8")
    if (r.stderr or "").strip():
        ctx.arquivo("verificar_erros.txt").write_text(registro.ocultar(r.stderr), encoding="utf-8")
    return {"codigo": r.returncode, "ok": r.returncode == 0, "resultado": dados}


def alvo_pytest(ctx: Contexto, argv_extra: list[str]) -> dict:
    _utf8_nos_filhos()
    r = ferramentas.rodar(
        [sys.executable, "-m", "pytest", "-q", *argv_extra],
        timeout=float(_cfg()["timeout_pytest_s"]), verificar=False, cwd=config.RAIZ,
    )
    texto = r.stdout or ""
    if (r.stderr or "").strip():
        texto += "\n--- stderr ---\n" + r.stderr
    ctx.arquivo("pytest.txt").write_text(registro.ocultar(texto), encoding="utf-8")
    linhas = [x.strip() for x in (r.stdout or "").splitlines() if x.strip()]
    return {"codigo": r.returncode, "ok": r.returncode == 0, "resumo_pytest": linhas[-1] if linhas else None, "arquivo": "pytest.txt"}


def resolver_alvo(alvo: str):
    """Importa o alvo só agora. Módulo/função que ainda não existe vira ``AlvoIndisponivel``."""
    modulo, funcao = ALVOS[alvo].split(":", 1)
    try:
        mod = importlib.import_module(modulo)
    except ModuleNotFoundError as e:
        faltando = e.name or ""
        if faltando and (modulo == faltando or modulo.startswith(faltando + ".")):
            raise AlvoIndisponivel(
                f"O alvo '{alvo}' ainda não existe nesta versão do repositório (falta o módulo {modulo}). "
                "Rode o atualizar.bat e tente de novo."
            ) from e
        raise AlvoIndisponivel(
            f"O alvo '{alvo}' precisa do pacote Python '{faltando}', que não está instalado. Rode o instalar.bat de novo."
        ) from e
    f = getattr(mod, funcao, None)
    if not callable(f):
        raise AlvoIndisponivel(
            f"O alvo '{alvo}' ainda não está pronto: {modulo} não tem a função {funcao}. Rode o atualizar.bat e tente de novo."
        )
    return f


# ---------------------------------------------------------------- pasta da execução

def pasta_execucoes(raiz: Path | None = None) -> Path:
    return Path(raiz or config.RAIZ) / _cfg()["pasta"]


def nova_pasta(alvo: str, raiz: Path | None = None) -> Path:
    base = pasta_execucoes(raiz)
    nome = f"{carimbo()}_{re.sub(r'[^A-Za-z0-9_.-]+', '-', alvo)}"
    pasta, n = base / nome, 2
    while pasta.exists():
        pasta, n = base / f"{nome}-{n}", n + 1
    pasta.mkdir(parents=True)
    return pasta


def _dentro_de_execucoes(pasta: Path, raiz: Path | None) -> bool:
    base = pasta_execucoes(raiz).resolve()
    return base in Path(pasta).resolve().parents


def _eh_env(nome: str) -> bool:
    nome = nome.lower()
    return nome == ".env" or nome.startswith(".env.") or nome.endswith(".env")


def _eh_texto(arq: Path, extensoes_texto: set[str]) -> bool:
    sufixo = arq.suffix.lower()
    if sufixo in extensoes_texto:
        return True
    if sufixo in BINARIOS:
        return False
    with open(arq, "rb") as f:
        return b"\x00" not in f.read(8192)


def sanear(pasta: Path, raiz: Path | None = None) -> dict:
    """Deixa a pasta pronta para o git: sem segredos, sem ``.env``, sem vídeo nem arquivo grande.

    Só age dentro de ``execucoes/``. Vídeo e arquivo grande saem da pasta de execução e ficam
    em ``saida_local/`` (fora do git); ``.env`` é apagado. Tudo o que saiu vai para ``omitidos.txt``.
    Telas salvas (``.xml`` + ``.png``): conversa do Direct fica fora do git; notificação do Android (nome e mensagem
    de cliente) é apagada do XML e coberta no print (``privacidade``).
    """
    pasta = Path(pasta)
    raiz = Path(raiz or config.RAIZ)
    if not _dentro_de_execucoes(pasta, raiz):
        raise ValueError(f"Só saneio pastas dentro de {pasta_execucoes(raiz)}: {pasta}")
    c = _cfg()
    limite = int(float(c["max_mb_por_arquivo"]) * 1024 * 1024)
    textos = {e.lower() for e in c["extensoes_texto"]}
    videos = {e.lower() for e in c["extensoes_video"]}
    guardar = raiz / c.get("pasta_local_omitidos", "saida_local/execucoes") / pasta.name
    ocultados: list[str] = []
    omitidos: list[dict] = []

    def tirar(arq: Path, rel: str, tamanho: int | None, motivo: str, apagar: bool = False) -> None:
        destino = None
        if apagar or arq.is_symlink():
            arq.unlink()
        else:
            destino = guardar / Path(rel)
            destino.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(arq), str(destino))
        omitidos.append({"arquivo": rel, "tamanho_mb": None if tamanho is None else round(tamanho / (1024 * 1024), 2),
                         "motivo": motivo, "guardado_em": str(destino) if destino else None})

    def conferir(arq: Path, rel: str) -> None:
        if arq.is_symlink():
            tirar(arq, rel, None, "atalho (link) não vai para o git", apagar=True)
            return
        if not arq.is_file() or rel == "omitidos.txt":
            return
        if _eh_env(arq.name):
            tirar(arq, rel, None, "arquivo .env nunca vai para o git", apagar=True)
            return
        tamanho = arq.stat().st_size
        if arq.suffix.lower() in videos:
            tirar(arq, rel, tamanho, "vídeo não vai para o git")
        elif tamanho > limite:
            tirar(arq, rel, tamanho, f"maior que {c['max_mb_por_arquivo']} MB")
        elif _eh_texto(arq, textos):
            texto = arq.read_bytes().decode("utf-8", "surrogateescape")
            limpo = registro.ocultar(texto)
            if limpo != texto:
                arq.write_bytes(limpo.encode("utf-8", "surrogateescape"))
                ocultados.append(rel)

    priv = c.get("privacidade") or {}
    for xml in sorted(pasta.rglob("*.xml")):
        rel = xml.relative_to(pasta).as_posix()
        png = xml.with_suffix(".png")
        try:
            r = privacidade.conferir_par(xml, priv)
        except Exception as e:  # noqa: BLE001 - na dúvida, a tela não vai para o git
            log.warning("Não consegui conferir a privacidade de %s: %s", rel, e)
            r = {"privada": f"não consegui conferir ({e.__class__.__name__})", "apagados": 0, "coberto": False}
        if r["privada"]:
            for arq in (xml, png):
                if arq.exists():
                    tirar(arq, arq.relative_to(pasta).as_posix(), arq.stat().st_size,
                          f"tela privada ({r['privada']}): conversa de cliente não vai para o git")
        elif r["apagados"] or r["coberto"]:
            ocultados.append(f"{rel} (notificação do Android{', print coberto' if r['coberto'] else ''})")

    for arq in sorted(pasta.rglob("*")):
        rel = arq.relative_to(pasta).as_posix()
        try:
            conferir(arq, rel)
        except OSError as e:
            # não deu para conferir (arquivo aberto por outro programa?): fica fora do git
            log.warning("Não consegui conferir %s: %s", rel, e)
            tirar(arq, rel, None, f"não consegui conferir se tem segredo ({e.__class__.__name__})")

    if omitidos:
        linhas = ["Arquivos que ficaram fora do git (ficam só no PC):", ""]
        for o in omitidos:
            tam = f"{o['tamanho_mb']} MB" if o["tamanho_mb"] is not None else "-"
            onde = f" -> {o['guardado_em']}" if o["guardado_em"] else ""
            linhas.append(f"{o['arquivo']}  ({tam})  {o['motivo']}{onde}")
        arq_omitidos = pasta / "omitidos.txt"
        anterior = arq_omitidos.read_text(encoding="utf-8") + "\n" if arq_omitidos.exists() else ""
        arq_omitidos.write_text(registro.ocultar(anterior + "\n".join(linhas) + "\n"), encoding="utf-8")
    if ocultados:
        log.info("Segredos ocultados em: %s", ", ".join(ocultados))
    return {"ocultados": ocultados, "omitidos": omitidos}


# ---------------------------------------------------------------- git

def _git(raiz: Path, *args: str, verificar: bool = False, timeout: float | None = None):
    os.environ.setdefault("GIT_TERMINAL_PROMPT", "0")  # nunca travar esperando senha no terminal
    return ferramentas.rodar(
        [ferramentas.exigir("git"), *args],
        timeout=timeout or float(_cfg()["timeout_git_s"]), verificar=verificar, cwd=raiz,
    )


def _identidade(raiz: Path) -> list[str]:
    """Se o Git do PC não tiver nome/e-mail configurado, usa o autor padrão da config só neste commit."""
    autor = _cfg()["git_autor_padrao"]
    opcoes: list[str] = []
    for chave, valor in (("user.name", autor["nome"]), ("user.email", autor["email"])):
        r = _git(raiz, "config", chave)
        if r.returncode != 0 or not (r.stdout or "").strip():
            opcoes += ["-c", f"{chave}={valor}"]
    return opcoes


def commitar(caminhos: list[Path], raiz: Path, mensagem: str) -> str | None:
    """``git add`` + ``git commit`` só dos caminhos dados. Devolve o commit, ou ``None`` se não havia nada."""
    raiz = Path(raiz)
    rels = [Path(p).resolve().relative_to(raiz.resolve()).as_posix() for p in caminhos]
    _git(raiz, "add", "--", *rels, verificar=True)
    if _git(raiz, "diff", "--cached", "--quiet", "--", *rels).returncode == 0:
        return None
    _git(raiz, *_identidade(raiz), "commit", "-q", "-m", mensagem, "--", *rels, verificar=True)
    return (_git(raiz, "rev-parse", "HEAD", verificar=True).stdout or "").strip()


def _explicar_falha(texto: str) -> tuple[str, str]:
    t = texto.lower()
    acao = "O resultado ficou salvo no PC com commit local."
    if any(s in t for s in ("authentication failed", "could not read username", "terminal prompts disabled",
                            "permission denied", "error: 403", "error: 401", "invalid username", "repository not found")):
        return "login", (f"O Git deste PC não está logado no GitHub. {acao} Abra o Prompt de Comando nesta pasta e rode: "
                         "git push (vai abrir a janela de login do GitHub). Depois rode: testar.bat enviar")
    if any(s in t for s in ("could not resolve host", "failed to connect", "timed out", "tempo esgotado",
                            "network is unreachable", "connection was reset", "couldn't connect", "unable to access")):
        return "sem_internet", f"Sem conexão com o GitHub. {acao} Quando a internet voltar, rode: testar.bat enviar"
    if "conflict" in t or "conflito" in t:
        return "conflito", (f"Conflito ao juntar com o que está no GitHub; desfiz a tentativa. {acao} "
                            "Me avise e mande o print desta janela.")
    if any(s in t for s in ("rejected", "non-fast-forward", "fetch first")):
        return "rejeitado", f"O GitHub tem mudanças mais novas. {acao} Rode: testar.bat enviar"
    return "falha", f"O envio pelo git falhou. {acao} Tente de novo com: testar.bat enviar. Se continuar, mande o print desta janela."


def _falha(texto: str) -> dict:
    motivo, mensagem = _explicar_falha(texto)
    return {"enviado": False, "motivo": motivo, "mensagem": mensagem, "detalhe": registro.ocultar(texto.strip()[-800:])}


def _abortar_rebase(raiz: Path) -> None:
    r = _git(raiz, "rev-parse", "--git-dir")
    pasta_git = Path(raiz) / (r.stdout or ".git").strip()
    if (pasta_git / "rebase-merge").exists() or (pasta_git / "rebase-apply").exists():
        _git(raiz, "rebase", "--abort")


def enviar(raiz: Path | None = None) -> dict:
    """``git pull --rebase --autostash`` + ``git push``. Nunca levanta exceção: devolve o que aconteceu."""
    raiz = Path(raiz or config.RAIZ)
    try:
        if _git(raiz, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}").returncode != 0:
            remotos = (_git(raiz, "remote").stdout or "").split()
            if not remotos:
                return {"enviado": False, "motivo": "sem_remoto",
                        "mensagem": "Este repositório não tem remoto (GitHub) configurado. O commit ficou só no PC."}
            remoto = "origin" if "origin" in remotos else remotos[0]
            r = _git(raiz, "push", "-u", remoto, "HEAD")
        else:
            p = _git(raiz, "pull", "--rebase", "--autostash")
            if p.returncode != 0:
                _abortar_rebase(raiz)
                return _falha((p.stderr or "") + "\n" + (p.stdout or ""))
            r = _git(raiz, "push")
    except ferramentas.FerramentaAusente as e:
        return {"enviado": False, "motivo": "sem_git", "mensagem": f"{e} A pasta ficou salva no PC."}
    except ferramentas.ErroComando as e:
        _abortar_rebase_seguro(raiz)
        return _falha(str(e))
    if r.returncode != 0:
        return _falha((r.stderr or "") + "\n" + (r.stdout or ""))
    return {"enviado": True, "motivo": "ok", "mensagem": "Enviado para o GitHub."}


def _abortar_rebase_seguro(raiz: Path) -> None:
    try:
        _abortar_rebase(raiz)
    except Exception:  # noqa: BLE001 - melhor esforço
        pass


def enviar_execucao(pasta: Path, raiz: Path, mensagem: str) -> dict:
    try:
        commit = commitar([pasta], raiz, mensagem)
    except (ferramentas.FerramentaAusente, ferramentas.ErroComando) as e:
        return {"enviado": False, "commit": None, "motivo": "commit",
                "mensagem": f"Não consegui fazer o commit da execução ({registro.ocultar(str(e))}). A pasta ficou salva no PC."}
    envio = enviar(raiz)
    envio["commit"] = commit
    return envio


def _pastas_pendentes(raiz: Path) -> list[Path]:
    """Pastas de ``execucoes/`` com arquivos novos ou alterados (ex.: rodadas com --sem-git)."""
    base = pasta_execucoes(raiz)
    rel_base = base.resolve().relative_to(Path(raiz).resolve()).as_posix()
    r = _git(raiz, "status", "--porcelain", "-z", "--untracked-files=all", "--", rel_base, verificar=True)
    nomes = set()
    for entrada in (r.stdout or "").split("\0"):
        if len(entrada) > 3 and entrada[2] == " ":
            caminho = entrada[3:]
            if caminho.startswith(rel_base + "/"):
                partes = caminho[len(rel_base) + 1:].split("/")
                if len(partes) > 1:
                    nomes.add(partes[0])
    return [base / n for n in sorted(nomes) if (base / n).is_dir()]


def enviar_pendentes(raiz: Path | None = None) -> dict:
    """Alvo ``enviar``: commita execuções que ficaram fora do git e tenta o push de novo."""
    raiz = Path(raiz or config.RAIZ)
    commit = None
    try:
        pendentes = _pastas_pendentes(raiz)
        for pasta in pendentes:
            sanear(pasta, raiz)
        if pendentes:
            commit = commitar(pendentes, raiz, "Execuções pendentes: " + ", ".join(p.name for p in pendentes))
    except Exception as e:  # noqa: BLE001 - sem saneamento ou commit, não envia nada
        return {"enviado": False, "commit": None, "motivo": "commit", "pastas": None,
                "mensagem": f"Não consegui preparar o envio: {registro.ocultar(str(e))}"}
    envio = enviar(raiz)
    envio["commit"] = commit
    envio["pastas"] = [p.name for p in pendentes]
    return envio


# ---------------------------------------------------------------- testar

def testar(alvo: str, extra: list[str] | None = None, enviar_git: bool = True, raiz: Path | None = None) -> dict:
    """Roda um alvo, grava a pasta de execução, saneia e (se ``enviar_git``) envia pelo git."""
    raiz = Path(raiz or config.RAIZ)
    extra = list(extra or [])
    if alvo == ENVIAR:
        envio = enviar_pendentes(raiz)
        return {"codigo": 0 if envio["enviado"] else 4, "pasta": None, "resultado": None, "saneamento": None, "envio": envio}
    if alvo not in ALVOS:
        raise KeyError(alvo)

    pasta = nova_pasta(alvo, raiz)
    handler = registro.anexar_arquivo(pasta / "log.txt")
    inicio = time.time()
    resultado: dict = {"alvo": alvo, "argv": extra, "pasta": pasta.resolve().relative_to(raiz.resolve()).as_posix(), "inicio": _agora()}
    try:
        log.info("Teste '%s' começou. Pasta: %s", alvo, pasta)
        try:
            _gravar_json(pasta / "versoes.json", diagnostico.versoes_principais())
        except Exception as e:  # noqa: BLE001 - versões não podem impedir o teste
            log.warning("Não consegui gravar versoes.json: %s", e)
        ctx = Contexto(pasta_saida=pasta, ensaio="ensaio" in alvo, diagnostico=True, id_pedido=pasta.name,
                       extras={"alvo": alvo, "argv": extra})
        try:
            retorno = resolver_alvo(alvo)(ctx, extra)
            resultado["resultado"] = retorno
            resultado["ok"] = not (isinstance(retorno, dict) and retorno.get("ok") is False)
        except SystemExit as e:
            resultado.update(ok=False, erro=f"Argumentos inválidos para o alvo '{alvo}': {extra} (código {e.code})")
        except KeyboardInterrupt:
            resultado.update(ok=False, erro="Interrompido pelo usuário (Ctrl+C).")
        except Exception as e:  # noqa: BLE001 - erro do alvo vira resultado
            resultado.update(ok=False, erro=str(e) or e.__class__.__name__, tipo_erro=e.__class__.__name__,
                             detalhe=traceback.format_exc()[-4000:])
            parcial = getattr(e, "resultado_parcial", None)
            if parcial is not None:
                resultado["resultado_parcial"] = parcial
        resultado["fim"] = _agora()
        resultado["duracao_s"] = round(time.time() - inicio, 1)
        if resultado["ok"]:
            log.info("Teste '%s' terminou bem em %.1f s", alvo, resultado["duracao_s"])
        else:
            log.error("Teste '%s' terminou com erro: %s", alvo, resultado.get("erro") or "o alvo devolveu ok=false")
        _gravar_json(pasta / "resultado.json", resultado)
    finally:
        registro.remover(handler)  # fecha o log.txt antes de sanear

    envio = None
    try:
        saneamento = sanear(pasta, raiz)
    except Exception as e:  # noqa: BLE001 - sem saneamento, nada vai para o git
        log.error("Não consegui sanear %s: %s", pasta, e)
        saneamento = {"erro": registro.ocultar(str(e)), "ocultados": [], "omitidos": []}
        enviar_git = False
        envio = {"enviado": False, "motivo": "saneamento", "commit": None,
                 "mensagem": f"Não consegui limpar a pasta antes de enviar ({registro.ocultar(str(e))}). "
                             "Não enviei nada pelo git; a pasta ficou só no PC."}
    if enviar_git:
        mensagem = f"Execução {pasta.name}: {alvo} {'ok' if resultado['ok'] else 'com erro'}"
        envio = enviar_execucao(pasta, raiz, mensagem)
    codigo = 0 if resultado["ok"] else 1
    if codigo == 0 and envio is not None and not envio.get("enviado"):
        codigo = 4
    return {"codigo": codigo, "pasta": pasta, "resultado": resultado, "saneamento": saneamento, "envio": envio}


def _mostrar(r: dict, enviar_git: bool) -> None:
    resultado, envio = r.get("resultado"), r.get("envio")
    if resultado is not None:
        retorno = resultado.get("resultado")
        if isinstance(retorno, dict) and isinstance(retorno.get("resumo"), str):
            print(retorno["resumo"])
            print()
        print(f"Pasta: {r['pasta']}")
        if resultado.get("ok"):
            print("Resultado: OK")
        else:
            print(f"Resultado: ERRO - {resultado.get('erro') or 'o teste devolveu ok=false (ver resultado.json)'}")
        omitidos = (r.get("saneamento") or {}).get("omitidos") or []
        if omitidos:
            print(f"{len(omitidos)} arquivo(s) ficaram fora do git (lista em omitidos.txt).")
    if envio is not None:
        if envio.get("pastas") is not None and not envio.get("pastas") and envio.get("enviado"):
            print("Nenhuma execução pendente; enviei o que havia de commit local.")
        print(envio["mensagem"])
    elif not enviar_git:
        print("Envio pelo git desligado (--sem-git). Para enviar depois: testar.bat enviar")


def cli(argv: list[str]) -> int:
    p = argparse.ArgumentParser(
        prog="python -m rotinas testar",
        description="Roda um teste real no PC, grava execucoes/<data_hora>_<alvo>/ (sem segredos) e envia pelo git.",
        epilog=lista_alvos(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--sem-git", action="store_true", help="grava a pasta, mas não envia pelo git")
    p.add_argument("alvo", nargs="?", help="o que testar (lista abaixo)")
    p.add_argument("extra", nargs=argparse.REMAINDER, help="argumentos repassados ao alvo")
    argv = list(argv)
    sem_git = "--sem-git" in argv
    argv = [x for x in argv if x != "--sem-git"]
    a = p.parse_args(argv)
    if not a.alvo:
        print(lista_alvos())
        return 0
    if a.alvo != ENVIAR and a.alvo not in ALVOS:
        print(f"Alvo desconhecido: {a.alvo}\n", file=sys.stderr)
        print(lista_alvos(), file=sys.stderr)
        return 2
    r = testar(a.alvo, a.extra, enviar_git=not sem_git)
    _mostrar(r, enviar_git=not sem_git)
    return int(r["codigo"])
