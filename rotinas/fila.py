"""Ponte por fila de arquivos entre a IA (que só lê e grava arquivos) e o Windows.

Estados: ``fila/pendente → fila/andamento → fila/feito | fila/erro``.

- A IA grava ``fila/pendente/<id>.json``. O vigia pega o mais antigo, executa e grava
  ``fila/feito/<id>.json`` (ou ``fila/erro/<id>.json``) + a pasta ``<id>/`` com log e prints.
- O arquivo de resultado só aparece quando tudo terminou: é o sinal para a IA ler.
- Nunca executa o mesmo pedido duas vezes: id repetido vai para ``erro`` sem rodar; pedido
  que ficou em ``andamento`` (vigia caiu no meio) vai para ``erro`` sem ser reexecutado.
- ``fila/vigia.vivo`` mostra quando o vigia deu sinal de vida pela última vez.
- ``fila/parar.flag`` faz o vigia sair quando estiver ocioso (usado pelo atualizar.bat).

Formato completo e exemplos em ``fila/README.md``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

from . import config, registro, tarefas
from .contexto import Contexto

log = registro.obter("fila")

ESTADOS = ("pendente", "andamento", "feito", "erro")
ID_VALIDO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,120}$")
ESPERA_ARQUIVO_S = 5.0  # arquivo inválido mais novo que isso pode estar sendo gravado


def pasta_fila(base: Path | None = None) -> Path:
    return Path(base) if base else config.pastas().fila


def preparar_pastas(base: Path | None = None) -> Path:
    raiz = pasta_fila(base)
    for e in ESTADOS:
        (raiz / e).mkdir(parents=True, exist_ok=True)
    return raiz


def agora_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _gravar_json(caminho: Path, dados: dict) -> None:
    """Grava JSON de forma atômica (arquivo temporário + troca)."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    tmp = caminho.with_name(caminho.name + ".tmp")
    tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, caminho)


def _ler_json(caminho: Path) -> dict:
    return json.loads(caminho.read_text(encoding="utf-8-sig"))


# ---------------------------------------------------------------- criar pedidos

def novo_id(tipo: str, sufixo: str | None = None, base: Path | None = None) -> str:
    raiz = pasta_fila(base)
    corpo = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + tipo.replace(".", "-")
    if sufixo:
        corpo += "-" + re.sub(r"[^A-Za-z0-9_.\-]+", "-", sufixo).strip("-")
    candidato, n = corpo, 1
    while id_existe(candidato, raiz):
        n += 1
        candidato = f"{corpo}-{n}"
    return candidato


def id_existe(id_: str, base: Path | None = None) -> bool:
    raiz = pasta_fila(base)
    if any((raiz / e / f"{id_}.json").exists() for e in ESTADOS):
        return True
    return id_ in ids_do_historico(raiz)


def ids_do_historico(raiz: Path) -> set[str]:
    hist = raiz / "historico.jsonl"
    ids: set[str] = set()
    if hist.exists():
        for linha in hist.read_text(encoding="utf-8").splitlines():
            try:
                ids.add(json.loads(linha)["id"])
            except (ValueError, KeyError):
                continue
    return ids


def criar_pedido(
    tipo: str,
    args: dict | None = None,
    id_: str | None = None,
    ensaio: bool = False,
    diagnostico: bool = False,
    origem: str = "script",
    base: Path | None = None,
    sufixo: str | None = None,
) -> Path:
    """Grava um pedido em ``fila/pendente`` e devolve o caminho."""
    tarefas.funcao_da_tarefa(tipo)  # valida o tipo antes de gravar
    raiz = preparar_pastas(base)
    id_ = id_ or novo_id(tipo, sufixo, raiz)
    if not ID_VALIDO.match(id_):
        raise ValueError(f"id inválido: {id_!r} (use letras, números, ponto, hífen e sublinhado)")
    if id_existe(id_, raiz):
        raise ValueError(f"Já existe um pedido com o id {id_}")
    pedido = {
        "id": id_,
        "tipo": tipo,
        "args": args or {},
        "ensaio": bool(ensaio),
        "diagnostico": bool(diagnostico),
        "criado_em": agora_iso(),
        "origem": origem,
    }
    destino = raiz / "pendente" / f"{id_}.json"
    _gravar_json(destino, pedido)
    log.info("Pedido gravado na fila: %s (%s)", id_, tipo)
    return destino


# ---------------------------------------------------------------- vigia

class Trava:
    """Garante um vigia só por vez (trava de arquivo do sistema operacional)."""

    def __init__(self, caminho: Path):
        self.caminho = caminho
        self._f = None

    def adquirir(self) -> bool:
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        f = open(self.caminho, "a+")
        try:
            if os.name == "nt":
                import msvcrt

                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            f.close()
            return False
        self._f = f
        return True

    def liberar(self) -> None:
        if not self._f:
            return
        try:
            if os.name == "nt":
                import msvcrt

                self._f.seek(0)
                msvcrt.locking(self._f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._f.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        self._f.close()
        self._f = None


class Vigia:
    def __init__(self, base: Path | None = None, intervalo_s: float = 2.0):
        self.raiz = preparar_pastas(base)
        self.intervalo_s = intervalo_s
        self.trava = Trava(self.raiz / "vigia.lock")

    # -- utilidades
    def _historico(self, registro_: dict) -> None:
        with open(self.raiz / "historico.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(registro_, ensure_ascii=False) + "\n")

    def sinal_de_vida(self, estado: str = "ocioso", id_: str | None = None) -> None:
        _gravar_json(self.raiz / "vigia.vivo", {"pid": os.getpid(), "em": agora_iso(), "estado": estado, "pedido": id_})

    def _mover_pasta(self, id_: str, de: str, para: str) -> Path:
        origem = self.raiz / de / id_
        destino = self.raiz / para / id_
        if destino.exists():
            destino = self.raiz / para / f"{id_}__{datetime.now().strftime('%H%M%S')}"
        if origem.exists():
            shutil.move(str(origem), str(destino))
        else:
            destino.mkdir(parents=True, exist_ok=True)
        return destino

    def _finalizar(self, pedido: dict, estado: str, corpo: dict, pasta_de: str = "andamento") -> Path:
        id_ = pedido["id"]
        pasta = self._mover_pasta(id_, pasta_de, estado)
        arquivos = sorted(str(p.relative_to(pasta)).replace("\\", "/") for p in pasta.rglob("*") if p.is_file())
        dados = {"id": id_, "tipo": pedido.get("tipo"), "estado": estado, "pedido": pedido, "pasta": str(pasta), "arquivos": arquivos, **corpo}
        dados = json.loads(registro.ocultar(json.dumps(dados, ensure_ascii=False)))
        destino = self.raiz / estado / f"{id_}.json"
        if destino.exists():
            destino = self.raiz / estado / f"{id_}__{datetime.now().strftime('%H%M%S')}.json"
        _gravar_json(destino, dados)
        resto = self.raiz / pasta_de / f"{id_}.json"
        if resto.exists():
            resto.unlink()
        self._historico({"id": id_, "tipo": pedido.get("tipo"), "estado": estado, "fim": agora_iso()})
        return destino

    # -- recuperação
    def recuperar_interrompidos(self) -> list[str]:
        """Pedidos que ficaram em ``andamento`` (vigia caiu) vão para ``erro`` sem reexecutar."""
        ids = []
        for arq in sorted((self.raiz / "andamento").glob("*.json")):
            try:
                pedido = _ler_json(arq)
            except Exception:
                pedido = {"id": arq.stem, "tipo": None}
            pedido.setdefault("id", arq.stem)
            self._finalizar(
                pedido,
                "erro",
                {"erro": "Interrompido: o vigia parou no meio deste pedido. Não reexecutei para não repetir nada. "
                         "Confira o que já foi feito (log e prints na pasta) antes de pedir de novo, com outro id."},
            )
            log.warning("Pedido interrompido movido para erro: %s", pedido["id"])
            ids.append(pedido["id"])
        return ids

    # -- ciclo
    def proximo(self) -> Path | None:
        candidatos = sorted((self.raiz / "pendente").glob("*.json"), key=lambda p: (p.stat().st_mtime, p.name))
        return candidatos[0] if candidatos else None

    def processar(self, arq: Path) -> tuple[str, Path | None]:
        """Executa um pedido. Devolve (estado, caminho do resultado)."""
        try:
            pedido = _ler_json(arq)
            if not isinstance(pedido, dict):
                raise ValueError("o pedido precisa ser um objeto JSON")
        except Exception as e:
            if time.time() - arq.stat().st_mtime < ESPERA_ARQUIVO_S:
                return "aguardando", None  # talvez ainda esteja sendo gravado
            pedido = {"id": arq.stem, "tipo": None}
            destino_ped = self.raiz / "andamento" / arq.name
            os.replace(arq, destino_ped)
            return "erro", self._finalizar(pedido, "erro", {"erro": f"JSON inválido: {e}"})

        id_ = str(pedido.get("id") or arq.stem)
        pedido["id"] = id_
        if id_ != arq.stem:
            os.replace(arq, self.raiz / "andamento" / arq.name)
            pedido["id"] = arq.stem
            return "erro", self._finalizar(pedido, "erro", {"erro": f"O campo id ({id_}) tem que ser igual ao nome do arquivo ({arq.stem})."})
        if not ID_VALIDO.match(id_):
            os.replace(arq, self.raiz / "andamento" / arq.name)
            return "erro", self._finalizar(pedido, "erro", {"erro": f"id inválido: {id_!r}"})
        ja_feito = any((self.raiz / e / f"{id_}.json").exists() for e in ("feito", "erro")) or id_ in ids_do_historico(self.raiz)
        if ja_feito:
            novo = f"{id_}__duplicado-{datetime.now():%H%M%S}"
            os.replace(arq, self.raiz / "andamento" / f"{novo}.json")
            return "erro", self._finalizar(
                dict(pedido, id=novo, id_original=id_), "erro",
                {"erro": f"Pedido {id_} já foi executado antes. Não executo de novo. Use outro id."},
            )

        # reserva: pendente → andamento (atômico)
        andamento = self.raiz / "andamento" / arq.name
        try:
            os.replace(arq, andamento)
        except OSError as e:
            log.warning("Não consegui reservar %s: %s", arq.name, e)
            return "aguardando", None
        pasta = self.raiz / "andamento" / id_
        pasta.mkdir(parents=True, exist_ok=True)
        handler = registro.anexar_arquivo(pasta / "log.txt")
        inicio = time.time()
        self.sinal_de_vida("executando", id_)
        log.info("Executando %s (%s)%s", id_, pedido.get("tipo"), " [ensaio]" if pedido.get("ensaio") else "")
        estado, corpo = "feito", {}
        try:
            funcao = tarefas.funcao_da_tarefa(str(pedido.get("tipo")))
            ctx = Contexto(pasta_saida=pasta, ensaio=bool(pedido.get("ensaio")), diagnostico=bool(pedido.get("diagnostico")), id_pedido=id_)
            resultado = funcao(dict(pedido.get("args") or {}), ctx)
            corpo = {"resultado": resultado}
            log.info("Pedido %s terminou bem", id_)
        except Exception as e:  # noqa: BLE001 - qualquer erro vira resultado de erro
            estado = "erro"
            corpo = {"erro": str(e) or e.__class__.__name__, "tipo_erro": e.__class__.__name__, "detalhe": traceback.format_exc()[-4000:]}
            resultado_parcial = getattr(e, "resultado_parcial", None)
            if resultado_parcial is not None:
                corpo["resultado_parcial"] = resultado_parcial
            log.error("Pedido %s falhou: %s", id_, e)
        finally:
            registro.remover(handler)
        corpo.update({"inicio": datetime.fromtimestamp(inicio).astimezone().isoformat(timespec="seconds"), "fim": agora_iso(), "duracao_s": round(time.time() - inicio, 1)})
        return estado, self._finalizar(pedido, estado, corpo)

    def rodar(self, uma_vez: bool = False) -> int:
        if not self.trava.adquirir():
            log.info("Já existe um vigia rodando (%s). Saindo.", self.raiz / "vigia.lock")
            return 0
        try:
            self.recuperar_interrompidos()
            log.info("Vigia rodando em %s", self.raiz)
            while True:
                arq = self.proximo()
                if arq is not None:
                    estado, _ = self.processar(arq)
                    if estado != "aguardando":
                        continue
                self.sinal_de_vida()
                flag = self.raiz / "parar.flag"
                if flag.exists():
                    flag.unlink()
                    log.info("Pedido de parada recebido (parar.flag). Saindo.")
                    return 0
                if uma_vez:
                    if arq is None or not any((self.raiz / "pendente").glob("*.json")):
                        return 0
                    # sobrou só arquivo "aguardando": espera um pouco e tenta de novo
                time.sleep(self.intervalo_s)
        finally:
            self.trava.liberar()


# ---------------------------------------------------------------- linha de comando

def cli_vigia(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="python -m rotinas vigia", description="Executa os pedidos da fila.")
    p.add_argument("--uma-vez", action="store_true", help="processa o que está pendente e sai")
    p.add_argument("--fila", help="pasta da fila (padrão: config/pastas.json)")
    p.add_argument("--intervalo", type=float, default=2.0)
    a = p.parse_args(argv)
    base = Path(a.fila) if a.fila else None
    raiz = preparar_pastas(base)
    logs = config.pastas().logs if base is None else raiz.parent / "logs"
    registro.configurar(logs / f"vigia-{datetime.now():%Y-%m-%d}.log", console=sys.stderr is not None)
    return Vigia(base, a.intervalo).rodar(uma_vez=a.uma_vez)


def cli(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="python -m rotinas fila", description="Pedidos da fila.")
    sub = p.add_subparsers(dest="acao", required=True)
    c = sub.add_parser("criar", help="grava um pedido em fila/pendente")
    c.add_argument("tipo", choices=sorted(tarefas.TAREFAS))
    c.add_argument("--args", default="{}", help="argumentos em JSON")
    c.add_argument("--args-arquivo", help="arquivo JSON com os argumentos")
    c.add_argument("--id")
    c.add_argument("--ensaio", action="store_true")
    c.add_argument("--diagnostico", action="store_true")
    ls = sub.add_parser("listar", help="mostra os pedidos por estado")
    ls.add_argument("--ultimos", type=int, default=10)
    m = sub.add_parser("mostrar", help="mostra o resultado de um pedido")
    m.add_argument("id")
    for s in (c, ls, m):
        s.add_argument("--fila", help="pasta da fila (padrão: config/pastas.json)")
    a = p.parse_args(argv)
    base = Path(a.fila) if a.fila else None
    if a.acao == "criar":
        args = json.loads(Path(a.args_arquivo).read_text(encoding="utf-8")) if a.args_arquivo else json.loads(a.args)
        caminho = criar_pedido(a.tipo, args, a.id, a.ensaio, a.diagnostico, origem="terminal", base=base)
        print(caminho.stem)
        return 0
    raiz = preparar_pastas(base)
    if a.acao == "listar":
        for e in ESTADOS:
            itens = sorted((raiz / e).glob("*.json"), key=lambda q: q.stat().st_mtime)[-a.ultimos:]
            print(f"{e} ({len(itens)}):")
            for q in itens:
                print(f"  {q.stem}")
        vivo = raiz / "vigia.vivo"
        print("vigia:", _ler_json(vivo) if vivo.exists() else "nunca rodou")
        return 0
    for e in ESTADOS:
        q = raiz / e / f"{a.id}.json"
        if q.exists():
            print(f"[{e}]")
            print(q.read_text(encoding="utf-8"))
            return 0
    print(f"Pedido {a.id} não encontrado", file=sys.stderr)
    return 1
