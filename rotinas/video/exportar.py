"""B4: exportação do rascunho pelo CapCut.

Por enquanto a exportação é um clique do usuário (BRIEFING §5 B4): este módulo grava
``instrucoes_exportacao.txt`` com o preset do destino (``config/exportacao.json`` + o modal mapeado em
``conhecimento/capcut-rascunho-e-exportacao.md``) e vigia a pasta de saída até aparecer o ``.mp4``
novo, estável por alguns segundos; aí chama ``conferencia.conferir``. Nunca muda configuração do
CapCut: só lista o que conferir no modal. A automação por atalhos fica para o ciclo real
(``exportar_por_atalhos`` é um esboço documentado).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .. import config, registro
from ..contexto import Contexto, carimbo
from . import capcut

log = registro.obter("video.exportar")

dormir = time.sleep  # trocáveis nos testes
agora = time.time

AUDIO_KBPS_ESTIMADO = 192  # margem para o áudio no cálculo do tamanho (§8)


class ErroExportacao(RuntimeError):
    """Problema na exportação ou na espera do arquivo exportado."""


def _cfg() -> dict:
    return capcut.cfg().get("exportacao") or {}


def preset(destino: str) -> dict:
    presets = config.carregar("exportacao").get("presets") or {}
    if destino not in presets:
        raise ErroExportacao(f"Destino desconhecido: '{destino}'. Destinos: {', '.join(sorted(presets))}")
    return presets[destino]


def pasta_exportado() -> Path:
    return config.pastas().videos / _cfg().get("pasta", "exportado")


def pastas_vigiadas() -> list[Path]:
    pastas = [pasta_exportado()]
    for extra in _cfg().get("pastas_extra") or []:
        p = config.expandir(extra)
        if p not in pastas:
            pastas.append(p)
    return pastas


def nome_arquivo(rascunho: str, destino: str) -> str:
    """Nome (sem extensão) que o usuário digita no campo "Nome" do modal."""
    return capcut.sanitizar_nome(f"{rascunho}_{destino}")


def _resolucao(largura: int, altura: int) -> str:
    lado = min(int(largura), int(altura))
    return {480: "480P", 720: "720P", 1080: "1080P", 1440: "2K", 2160: "4K", 4320: "8K"}.get(lado, f"{lado}P")


def _n(valor: float, casas: int = 0) -> str:
    texto = f"{valor:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return texto


def estimar_mb(kbps: float, duracao_s: float) -> float:
    """Tamanho estimado em MB (1.000.000 bytes): (vídeo + áudio) × duração ÷ 8."""
    return (float(kbps) + AUDIO_KBPS_ESTIMADO) * float(duracao_s) / 8 / 1000


def instrucoes(destino: str, rascunho: str, nome: str | None = None, duracao_s: float | None = None,
               pasta: Path | None = None) -> str:
    """Texto com o passo a passo do modal "Exportar" para o preset do destino."""
    p = preset(destino)
    nome = nome or nome_arquivo(rascunho, destino)
    pasta = pasta or pasta_exportado()
    L = [f"Exportar o rascunho \"{rascunho}\" para {destino} (preset de config/exportacao.json)", "",
         f"1. Abra o CapCut e o projeto \"{rascunho}\". Faça o acabamento do relatorio_rascunho.txt e o checklist "
         "(edicao-video-capcut.md §9).",
         "2. Clique em Exportar (canto de cima, à direita) ou Ctrl+E. O modal \"Exportar-<nome>\" não fecha com Esc "
         "(para cancelar sem clicar: Alt+Espaço e depois f).",
         "3. Preencha o modal:",
         f"   - Nome: {nome}",
         f"   - Exportar para: {pasta}",
         "   - Vídeo (marcado):",
         f"     - Resolução: {_resolucao(p['largura'], p['altura'])} ({p['largura']}×{p['altura']})",
         f"     - Taxa de bits: Personalizado → {_n(p['kbps'])} kbps",
         f"     - Codec: {'H.264' if str(p.get('codec', 'h264')).lower() in ('h264', 'h.264', 'avc') else p['codec']}",
         f"     - Formato: {p.get('formato', 'mp4')}",
         f"     - Taxa de quadros: {p['fps']}",
         "     - Espaço de cores: Rec.709 SDR (fixo)",
         "   - Áudio (MP3), GIF e Legendas: desmarcados.",
         "   - \"Sincronize os vídeos exportados com o espaço\": deixe como está (só mudar se o dono pedir).",
         "   - Os menus às vezes pedem 2 cliques; feche cada lista clicando no próprio campo "
         "(a lista de fps cobre o botão Exportar).",
         "4. Clique em [Exportar]. [Cancelar] fica logo ao lado (≈75 px à direita): confira antes de clicar.",
         "5. Se aparecer \"Não foi possível exportar — ... direitos autorais\": a linha do tempo só tem material da "
         "Biblioteca sem edição; edite (ex.: o texto) e exporte de novo.",
         ""]
    if duracao_s:
        mb = estimar_mb(p["kbps"], duracao_s)
        linha = f"Tamanho estimado: ≈{_n(mb, 1)} MB para {_n(duracao_s, 1)} s"
        limite = p.get("tamanho_max_mb")
        if limite:
            linha += f" (limite do {destino}: {_n(limite)} MB)"
            if mb > limite:
                maximo = limite * 8000 / float(duracao_s) - AUDIO_KBPS_ESTIMADO
                linha += f". PASSA DO LIMITE: use no máximo {_n(maximo)} kbps."
        L.append(linha)
    L += ["Volume: o CapCut está em \"Padrão (−23 LUFS)\" e a mixagem mira −14 LUFS; "
          "não mudar essa configuração sem o dono pedir.",
          f"Depois de exportar: o arquivo {nome}.{p.get('formato', 'mp4')} é conferido sozinho quando aparecer na pasta "
          "(duração, resolução, fps, codec, taxa de bits, áudio, loudness e tamanho)."]
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- vigia de exportação

def _novos(pastas: list[Path], desde: float, extensao: str) -> list[Path]:
    achados = []
    for pasta in pastas:
        if not pasta.is_dir():
            continue
        for arq in pasta.iterdir():
            try:
                if arq.is_file() and arq.suffix.lower() == extensao and arq.stat().st_mtime >= desde - 1:
                    achados.append(arq)
            except OSError:
                continue
    return achados


def _mtime(arq: Path) -> float:
    """mtime, ou 0 se o arquivo sumiu entre a listagem e agora (o CapCut renomeia/apaga temporários)."""
    try:
        return arq.stat().st_mtime
    except OSError:
        return 0.0


def _pode_ler(arq: Path) -> bool:
    try:
        with open(arq, "rb") as f:
            f.read(1)
        return True
    except OSError:
        return False


def esperar_arquivo(esperado: str, desde: float, pastas: list[Path] | None = None, extensao: str = ".mp4",
                    timeout_s: float | None = None, estavel_s: float | None = None,
                    intervalo_s: float | None = None) -> Path:
    """Espera um arquivo novo (depois de ``desde``) com o nome esperado, estável por ``estavel_s`` segundos.

    Se ``aceitar_outro_nome`` (config) e nenhum arquivo tiver o nome esperado, aceita o mais novo.
    """
    c = _cfg()
    pastas = pastas or pastas_vigiadas()
    timeout_s = float(timeout_s if timeout_s is not None else float(c.get("espera_max_min", 30)) * 60)
    estavel_s = float(estavel_s if estavel_s is not None else c.get("estavel_s", 5))
    intervalo_s = float(intervalo_s if intervalo_s is not None else c.get("intervalo_s", 1))
    aceitar_outro = bool(c.get("aceitar_outro_nome", True))
    inicio = agora()
    vistos: dict[Path, tuple[int, float, float]] = {}  # arquivo → (tamanho, mtime, desde quando igual)
    log.info("Esperando o arquivo exportado '%s%s' em: %s", esperado, extensao, ", ".join(str(p) for p in pastas))
    while True:
        novos = _novos(pastas, desde, extensao)
        certos = [a for a in novos if a.stem.lower().startswith(esperado.lower())]
        candidatos = certos or (novos if aceitar_outro else [])
        for arq in sorted(candidatos, key=_mtime, reverse=True):
            try:
                st = arq.stat()
            except OSError:
                continue
            atual = (st.st_size, st.st_mtime)
            antes = vistos.get(arq)
            if antes is None or (antes[0], antes[1]) != atual:
                vistos[arq] = (st.st_size, st.st_mtime, agora())
                continue
            if st.st_size > 0 and agora() - antes[2] >= estavel_s and _pode_ler(arq):
                if not certos:
                    log.warning("Arquivo exportado com nome diferente do esperado: %s", arq.name)
                return arq
        if agora() - inicio >= timeout_s:
            raise ErroExportacao(
                f"Nenhum {extensao} novo '{esperado}' apareceu em {int(timeout_s // 60)} min "
                f"({', '.join(str(p) for p in pastas)}). Exporte pelo CapCut e rode de novo."
            )
        dormir(intervalo_s)


def vigiar_e_conferir(esperado: str, destino: str, desde: float, duracao_esperada_s: float | None = None,
                      **opcoes) -> dict:
    """Espera o arquivo exportado e confere com ``conferencia.conferir``."""
    from . import conferencia

    extensao = "." + str(preset(destino).get("formato", "mp4")).lstrip(".")
    arquivo = esperar_arquivo(esperado, desde, extensao=extensao, **opcoes)
    resultado = conferencia.conferir(arquivo, destino, duracao_esperada_s)
    return {"arquivo": str(arquivo), "conferencia": resultado, "texto": conferencia.texto(resultado)}


def exportar_por_atalhos(rascunho: str, destino: str) -> None:
    """ESBOÇO (ciclo real): exportar sem clique do usuário.

    Plano, a validar no PC com o diagnóstico: 1) garantir o foco na janela do CapCut antes de cada
    atalho (a janela do Claude Desktop pode vir para a frente por 3–15 s); 2) abrir o projeto;
    3) Ctrl+E e conferir o título "Exportar-<nome>"; 4) preencher Nome e os menus (coluna x≈954–1166
    com a janela em x=256 e largura 1200; −128 em x com a janela maximizada; menus pedem 2 cliques);
    5) print do modal antes de clicar em [Exportar] (a ≈75 px de [Cancelar]); 6) nunca Ctrl+Q (fecha o
    CapCut) nem os menus de conta; cancelar com Alt+Espaço → f. Até lá a exportação é um clique do usuário.
    """
    raise NotImplementedError(
        "Exportação por atalhos ainda não implementada: por enquanto a exportação é um clique do usuário "
        "(siga o instrucoes_exportacao.txt)."
    )


# ---------------------------------------------------------------- fila e terminal

def _rascunho_do_projeto(projeto: str | None) -> tuple[str | None, float | None]:
    """Nome e duração do último rascunho gerado para o projeto (``relatorio_rascunho.txt``).

    O ``plano.json`` pode ter sido trocado depois do rascunho (outro planejar, até com violação);
    o relatório é do rascunho que o usuário vai abrir."""
    if not projeto:
        return None, None
    arq = config.pastas().videos / "trabalho" / projeto / "relatorio_rascunho.txt"
    try:
        linhas = arq.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeDecodeError):
        return None, None
    nome = duracao = None
    for linha in linhas[:10]:
        if linha.startswith("Rascunho do CapCut:"):
            nome = linha.split(":", 1)[1].strip() or None
        elif linha.startswith("Duração:"):
            try:
                duracao = float(linha.split(":", 1)[1].split("s", 1)[0].strip().replace(",", "."))
            except ValueError:
                pass
    return nome, duracao


def _duracao_do_plano(projeto: str | None) -> float | None:
    if not projeto:
        return None
    arq = config.pastas().videos / "trabalho" / projeto / "plano.json"
    try:
        valor = json.loads(arq.read_text(encoding="utf-8-sig")).get("duracao_s")
    except (OSError, ValueError, AttributeError):
        return None
    return float(valor) if isinstance(valor, (int, float)) else None


def tarefa(args: dict, ctx: Contexto) -> dict:
    """Tipo ``video.exportar``: ``{"destino", "rascunho"?, "projeto"?, "nome_arquivo"?, "duracao_esperada_s"?,
    "esperar"?, "timeout_min"?}``. Grava as instruções e (salvo ``esperar: false`` ou ensaio) vigia e confere."""
    destino = args.get("destino") or "reels"
    projeto = args.get("projeto")
    if not (args.get("rascunho") or projeto):
        raise ErroExportacao("Informe 'rascunho' (nome do projeto no CapCut) ou 'projeto'.")
    nome = args.get("nome_arquivo") or nome_arquivo(args.get("rascunho") or projeto, destino)
    # o rascunho no CapCut se chama "<projeto> <data>" (ou o 'nome' do video.rascunho), não "<projeto>";
    # sem 'rascunho', nome e duração vêm do último relatorio_rascunho.txt do projeto
    nome_rel, dur_rel = (None, None) if args.get("rascunho") else _rascunho_do_projeto(projeto)
    rascunho = args.get("rascunho") or nome_rel or projeto
    duracao = args.get("duracao_esperada_s")
    duracao = float(duracao) if duracao is not None else (dur_rel or _duracao_do_plano(projeto))
    desde = agora()
    texto = instrucoes(destino, rascunho, nome, duracao)
    arquivos = [ctx.arquivo("instrucoes_exportacao.txt")]
    if projeto:
        arquivos.append(config.pastas().videos / "trabalho" / projeto / "instrucoes_exportacao.txt")
    for arq in arquivos:
        arq.parent.mkdir(parents=True, exist_ok=True)
        arq.write_text(texto, encoding="utf-8")
    pasta_exportado().mkdir(parents=True, exist_ok=True)
    resultado = {"destino": destino, "rascunho": rascunho, "nome_arquivo": nome, "instrucoes": str(arquivos[-1]),
                 "pastas_vigiadas": [str(p) for p in pastas_vigiadas()], "duracao_esperada_s": duracao}
    if ctx.ensaio or args.get("esperar") is False:
        return {**resultado, "esperou": False}
    timeout = float(args["timeout_min"]) * 60 if args.get("timeout_min") else None
    conferido = vigiar_e_conferir(nome, destino, desde, duracao, timeout_s=timeout)
    ctx.arquivo("conferencia.txt").write_text(conferido["texto"], encoding="utf-8")
    return {**resultado, "esperou": True, **conferido, "aprovado": conferido["conferencia"].get("aprovado")}


def cli(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="python -m rotinas video-exportar",
                                description="B4: instruções de exportação do CapCut + espera e conferência do arquivo.")
    p.add_argument("--destino", default="reels", help="reels, stories, tiktok ou feed (config/exportacao.json)")
    p.add_argument("--rascunho", help="nome do projeto no CapCut")
    p.add_argument("--projeto", help="projeto em videos/trabalho/<projeto>/ (lê a duração do plano)")
    p.add_argument("--nome-arquivo", help="nome do arquivo exportado, sem extensão")
    p.add_argument("--duracao", type=float, help="duração esperada em segundos")
    p.add_argument("--sem-esperar", action="store_true", help="só grava as instruções")
    p.add_argument("--timeout-min", type=float, help="quanto esperar o arquivo (padrão: config/capcut.json)")
    a = p.parse_args(argv)
    if not (a.rascunho or a.projeto):
        p.error("informe --rascunho ou --projeto")
    ctx = Contexto(config.pastas().logs / "exportar" / carimbo())
    args = {"destino": a.destino, "rascunho": a.rascunho, "projeto": a.projeto, "nome_arquivo": a.nome_arquivo,
            "duracao_esperada_s": a.duracao, "esperar": not a.sem_esperar, "timeout_min": a.timeout_min}
    try:
        if not a.sem_esperar:
            print(instrucoes(a.destino, a.rascunho or a.projeto, a.nome_arquivo,
                             a.duracao if a.duracao is not None else _duracao_do_plano(a.projeto)))
        r = tarefa(args, ctx)
    except ErroExportacao as e:
        print(str(e), file=sys.stderr)
        return 1
    if not r["esperou"]:
        print(f"Instruções gravadas em {r['instrucoes']}")
        return 0
    print(r["texto"])
    return 0 if r.get("aprovado") else 1
