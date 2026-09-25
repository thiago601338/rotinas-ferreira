"""B4: conferência automática do vídeo exportado pelo CapCut contra o preset do destino.

Confere duração, resolução, fps, codec, formato, taxa de bits, áudio, volume (≈ −14 LUFS), pico real,
tamanho e HDR. Cada item traz esperado, obtido, ok e, quando falha, o que fazer no CapCut
(``conhecimento/edicao-video-capcut.md`` §7 e §8). Presets e tolerâncias: ``config/exportacao.json``.

``som_esperado`` diz o que o plano manda no som do arquivo: ``"com_som"`` (padrão: fala e/ou música no vídeo),
``"mudo"`` (música pelo Instagram e nenhuma fala: o arquivo sai mudo de propósito, então áudio, volume e pico não
reprovam) ou ``"so_efeitos"`` (só efeitos sonoros: o alvo de −14 LUFS não vale). O ``video.exportar`` deduz isso
do ``plano.json``.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

from .. import config, ferramentas, midia, registro
from ..contexto import Contexto
from .exportar import SONS, normalizar_som  # o exportar também valida (antes de esperar o arquivo)

log = registro.obter("video.conferencia")

MB = 1_000_000  # bytes (limite conservador: o do Instagram é "~100 MB")
MUDO_LUFS = -69.0  # o ebur128 devolve −70 LUFS para silêncio
# Acima disto o arquivo "tem som" num plano mudo (clipe a −60 dB fica bem abaixo; música esquecida, bem acima).
MUDO_AUDIVEL_LUFS = -50.0
NA_MUDO = "n/a (sai mudo: música pelo Instagram)"
EXT_VIDEO = (".mp4", ".mov", ".m4v")
NOME_CODEC = {"h264": "H.264", "hevc": "HEVC", "av1": "AV1", "prores": "ProRes", "qtrle": "RLE"}


# ---------------------------------------------------------------- formatação

def _n(valor: float, casas: int | None = 1) -> str:
    """Número no jeito brasileiro (vírgula decimal, sinal de menos tipográfico).

    ``casas=None``: sem casas se for inteiro, senão uma.
    """
    if casas is None:
        casas = 0 if float(valor).is_integer() else 1
    texto = f"{valor:.{casas}f}"
    if float(texto) == 0:
        texto = texto.lstrip("-")  # nada de "−0,0"
    texto = texto.replace(".", ",")
    return "−" + texto[1:] if texto.startswith("-") else texto


def _mil(valor: float) -> str:
    return f"{int(round(valor)):,}".replace(",", ".")


def _fps_txt(fps: float | None) -> str:
    if fps is None:
        return "?"
    return f"{_n(fps, 0) if abs(fps - round(fps)) < 0.005 else _n(fps, 2)} fps"


def _item(nome: str, esperado: str, obtido: str, ok: bool, fazer: str | None = None) -> dict:
    item = {"item": nome, "esperado": esperado, "obtido": obtido, "ok": bool(ok)}
    if not ok and fazer:
        item["fazer"] = fazer
    return item


def _finito(valor: float | None) -> float | None:
    return valor if valor is not None and math.isfinite(valor) else None


# ---------------------------------------------------------------- itens

def _duracao(info: midia.InfoMidia, preset: dict, exp: dict, destino: str, esperada: float | None) -> dict:
    dur = info.duracao_s
    folga = 1.0 / float(preset.get("fps") or 30)
    maximo, minimo = preset.get("duracao_max_s"), preset.get("duracao_min_s")
    tol = float(exp.get("duracao_tolerancia_s", 0.5))
    partes = []
    if esperada is not None:
        partes.append(f"{_n(esperada)} s ± {_n(tol)} s")
    if minimo is not None:
        partes.append(f"≥ {_n(minimo, None)} s")
    if maximo is not None:
        partes.append(f"≤ {_n(maximo, None)} s")
    esperado = ", ".join(partes) or "qualquer"
    if dur is None:
        return _item("duração", esperado, "sem duração", False, "O arquivo parece incompleto: exportar de novo.")
    problemas = []
    if maximo is not None and dur > maximo + folga:
        extra = " por story" if destino == "stories" else ""
        problemas.append(f"Cortar para até {_n(maximo, None)} s ({destino}: até {_n(maximo, None)} s{extra}).")
    if minimo is not None and dur < minimo - folga:
        problemas.append(f"O {destino} pede pelo menos {_n(minimo, None)} s.")
    if esperada is not None and abs(dur - esperada) > tol:
        dif = dur - esperada
        if dif > 0:
            problemas.append(f"Saiu {_n(dif)} s a mais que o plano: conferir se sobrou clipe, áudio ou texto depois "
                             "do último corte na linha do tempo.")
        else:
            problemas.append(f"Saiu {_n(-dif)} s a menos que o plano: conferir se faltou trecho na linha do tempo "
                             "ou se a exportação parou no meio.")
    return _item("duração", esperado, f"{_n(dur)} s", not problemas, " ".join(problemas))


def _resolucao(info: midia.InfoMidia, preset: dict) -> dict:
    larg, alt = int(preset["largura"]), int(preset["altura"])
    esperado = f"{larg}×{alt}"
    w, h = info.largura, info.altura
    if not w or not h:
        return _item("resolução", esperado, "sem vídeo", False,
                     "O arquivo não tem imagem: exportar de novo com Vídeo marcado.")
    obtido = f"{w}×{h}"
    ok = (w, h) == (larg, alt)
    if abs(w / h - larg / alt) > 0.01:
        fazer = (f"A proporção do projeto não é a do destino ({esperado}): ajustar em Proporção (sob o player) "
                 "e exportar de novo em 1080P.")
    elif w < larg:
        fazer = "No Exportar, Resolução 1080P."
    else:
        fazer = "No Exportar, Resolução 1080P (saiu maior que o destino: 2K/4K)."
    return _item("resolução", esperado, obtido, ok, fazer)


def _fps(info: midia.InfoMidia, preset: dict, exp: dict) -> dict:
    alvo = float(preset["fps"])
    tol = float(exp.get("fps_tolerancia", 0.05))
    obtido = _fps_txt(info.fps) + (" (variável)" if info.fps_variavel else "")
    ok = info.fps is not None and abs(info.fps - alvo) <= tol
    fazer = f"No Exportar, Taxa de quadros {_n(alvo, None)}."
    if info.fps is not None and round(info.fps) in (25, 50):
        fazer += " 25/50 fps cintilam sob lâmpadas de 60 Hz."
    elif info.fps is not None and info.fps > alvo:
        fazer += f" Se o vídeo tem câmera lenta gravada a {_n(info.fps, 0)} fps, pode ignorar este item."
    return _item("taxa de quadros", _fps_txt(alvo), obtido, ok, fazer)


def _codec(info: midia.InfoMidia, preset: dict) -> dict:
    alvo = str(preset.get("codec") or "h264").lower()
    obtido = NOME_CODEC.get(info.codec_video or "", info.codec_video or "sem vídeo")
    return _item("codec", NOME_CODEC.get(alvo, alvo), obtido, (info.codec_video or "").lower() == alvo,
                 f"No Exportar, Codec {NOME_CODEC.get(alvo, alvo)}.")


def _formato(arquivo: Path, preset: dict) -> dict:
    alvo = "." + str(preset.get("formato") or "mp4").lower().lstrip(".")
    obtido = arquivo.suffix.lower() or "sem extensão"
    return _item("formato", alvo, obtido, obtido == alvo,
                 f"No Exportar, Formato {alvo.lstrip('.')} "
                 "(o .mov não aparece na galeria do Instagram no BlueStacks).")


def _kbps_pelo_tamanho(limite_mb: float, dur: float) -> tuple[float, int]:
    """(Mbps máximo, kbps sugerido com margem para o áudio) pela fórmula Mbps ≤ (MB × 8) ÷ s (guia §8)."""
    mbps = limite_mb * 8 / dur
    return mbps, int(mbps * 1000 * 0.9 // 100 * 100)


def _taxa_bits(info: midia.InfoMidia, preset: dict, exp: dict) -> dict:
    kmin, kmax, kalvo = float(preset["kbps_min"]), float(preset["kbps_max"]), float(preset["kbps"])
    tol = float(exp.get("kbps_tolerancia_pct", 25)) / 100
    lo, hi = kmin * (1 - tol), kmax * (1 + tol)
    esperado = f"{_mil(kmin)}–{_mil(kmax)} kbps (aceito {_mil(lo)}–{_mil(hi)})"
    kbps = info.bitrate_kbps
    if kbps is None:
        return _item("taxa de bits", esperado, "não medida", False, "O arquivo parece incompleto: exportar de novo.")
    sugerido = int(kalvo)
    limite = preset.get("tamanho_max_mb")
    if limite and info.duracao_s:
        sugerido = min(sugerido, _kbps_pelo_tamanho(float(limite), info.duracao_s)[1])
    fazer = f"No Exportar, Taxa de bits → Personalizado {_mil(sugerido)} Kbps."
    if kbps < lo:
        fazer += (f" Se já estava em Personalizado {_mil(sugerido)}, o vídeo é muito parado e o codificador gastou "
                  "menos: pode ignorar este item.")
    return _item("taxa de bits", esperado, f"{_mil(kbps)} kbps", lo <= kbps <= hi, fazer)


def _audivel(info: midia.InfoMidia, som: dict, exp: dict) -> bool:
    """Som de verdade (não só o resto de um clipe a −60 dB)."""
    lufs = som.get("lufs")
    limite = float(exp.get("mudo_audivel_lufs", MUDO_AUDIVEL_LUFS))
    return info.tem_audio and lufs is not None and math.isfinite(lufs) and lufs > limite


def _audio_mudo(info: midia.InfoMidia, som: dict, exp: dict) -> dict:
    esperado = "mudo (música pelo Instagram)"
    if not _audivel(info, som, exp):
        obtido = "sem faixa de áudio" if not info.tem_audio else "sem som"
        return _item("áudio", esperado, obtido, True)
    return _item("áudio", esperado, f"com som ({_n(som['lufs'])} LUFS)", False,
                 "O plano exporta o vídeo mudo (a música entra pelo Instagram), mas o arquivo tem som: conferir se a "
                 "faixa-guia foi desligada (V) e se nenhuma música ficou na linha do tempo. Se o som é de propósito, "
                 "pode ignorar este item.")


def _audio(info: midia.InfoMidia, som: dict, exp: dict | None = None, som_esperado: str = "com_som") -> dict:
    if som_esperado == "mudo":
        return _audio_mudo(info, som, exp or {})
    esperado = "presente, com som" if som_esperado == "com_som" else "presente, com os efeitos sonoros"
    fazer = ("O vídeo saiu sem som: conferir se as faixas de áudio não estão silenciadas ou desativadas no CapCut. "
             "Se a música vai ser posta pelo Instagram e o vídeo não tem fala, o arquivo sai mudo mesmo: conferir de "
             "novo com som_esperado \"mudo\" (o video.exportar deduz isso do plano.json).")
    if not info.tem_audio:
        return _item("áudio", esperado, "sem faixa de áudio", False, fazer)
    detalhe = NOME_CODEC.get(info.codec_audio or "", (info.codec_audio or "?").upper())
    if info.taxa_amostragem:
        detalhe += f" {_n(info.taxa_amostragem / 1000, 0 if info.taxa_amostragem % 1000 == 0 else 1)} kHz"
    if info.canais:
        detalhe += " estéreo" if info.canais == 2 else f" {info.canais} canal(is)"
    lufs = som.get("lufs")
    if lufs is not None and (not math.isfinite(lufs) or lufs <= MUDO_LUFS):
        return _item("áudio", esperado, f"{detalhe}, mas mudo", False, fazer)
    return _item("áudio", esperado, detalhe, True)


def _volume(info: midia.InfoMidia, som: dict, exp: dict, som_esperado: str = "com_som") -> dict:
    alvo = float(exp.get("loudness_alvo_lufs", -14.0))
    tol = float(exp.get("loudness_tolerancia_lu", 2.0))
    pico_max = float(exp.get("pico_real_max_dbtp", -1.0))
    esperado = f"{_n(alvo, None)} LUFS ± {_n(tol, None)}"
    lufs, pico = som.get("lufs"), _finito(som.get("pico_real_dbtp"))
    if som_esperado == "mudo" and not _audivel(info, som, exp):
        return _item("volume", "n/a", NA_MUDO, True)
    if som_esperado == "so_efeitos":
        obtido = f"{_n(lufs)} LUFS" if _finito(lufs) is not None else "não medido"
        return _item("volume", "n/a (só efeitos sonoros)", obtido, True)
    if not info.tem_audio or (lufs is not None and (not math.isfinite(lufs) or lufs <= MUDO_LUFS)):
        return _item("volume", esperado, "sem som", False, "Ver o item áudio.")
    if lufs is None:
        return _item("volume", esperado, "não medido", False,
                     "O ffmpeg não devolveu a medição (ebur128): rodar de novo ou medir no Youlean Loudness Meter.")
    obtido = f"{_n(lufs)} LUFS"
    if abs(lufs - alvo) <= tol:
        return _item("volume", esperado, obtido, True)
    if lufs < alvo:
        ganho = alvo - lufs
        fazer = (f"Subir o ganho do clipe ~{_n(ganho, 0)} dB e exportar de novo: o CapCut está com alvo −23 LUFS "
                 "(Configurações > Editar > Nível de volume desejado), que deixa o áudio ~9 dB abaixo de −14.")
        if pico is not None and pico + ganho > pico_max:
            fazer += (f" Com +{_n(ganho, 0)} dB o pico real iria a {_n(pico + ganho)} dBTP: subir só até o pico "
                      f"chegar a {_n(pico_max, None)} dBTP (~{_n(max(pico_max - pico, 0), 0)} dB) e baixar os picos "
                      "da voz/música (voz com picos de −6 a −3 dB).")
    else:
        fazer = f"Baixar o volume ~{_n(lufs - alvo, 0)} dB (clipes de voz e música) e exportar de novo."
    return _item("volume", esperado, obtido, False, fazer)


def _pico(info: midia.InfoMidia, som: dict, exp: dict, som_esperado: str = "com_som") -> dict:
    pico_max = float(exp.get("pico_real_max_dbtp", -1.0))
    esperado = f"≤ {_n(pico_max)} dBTP"
    lufs, pico = som.get("lufs"), som.get("pico_real_dbtp")
    if som_esperado == "mudo" and not _audivel(info, som, exp):
        return _item("pico real", "n/a", NA_MUDO, True)
    if not info.tem_audio or (lufs is not None and (not math.isfinite(lufs) or lufs <= MUDO_LUFS)):
        return _item("pico real", esperado, "sem som", False, "Ver o item áudio.")
    if pico is None:
        return _item("pico real", esperado, "não medido", False,
                     "O ffmpeg não devolveu o pico real: rodar de novo ou medir no Youlean Loudness Meter.")
    return _item("pico real", esperado, f"{_n(pico)} dBTP", pico <= pico_max + 1e-9,
                 f"Baixar ~{_n(pico - pico_max)} dB no volume geral ou nos picos (voz com picos de −6 a −3 dB; "
                 "música 12–18 dB abaixo da voz) e exportar de novo.")


def _tamanho(info: midia.InfoMidia, preset: dict, destino: str) -> dict:
    limite = preset.get("tamanho_max_mb")
    mb = info.tamanho_bytes / MB
    obtido = f"{_n(mb)} MB"
    if not limite:
        return _item("tamanho", "sem limite", obtido, True)
    ok = mb <= float(limite)
    fazer = None
    if not ok:
        dur = info.duracao_s or 0
        if dur > 0:
            mbps, kbps = _kbps_pelo_tamanho(float(limite), dur)
            fazer = (f"Baixar a taxa de bits: Mbps ≤ (MB × 8) ÷ s = ({_n(limite, None)} × 8) ÷ {_n(dur)} "
                     f"= {_n(mbps)} Mbps. No Exportar, Taxa de bits → Personalizado até {_mil(kbps)} Kbps "
                     "(margem para o áudio).")
        else:
            fazer = f"Baixar a taxa de bits no Exportar até o arquivo ficar abaixo de {_n(limite, None)} MB."
    return _item("tamanho", f"≤ {_n(limite, None)} MB ({destino})", obtido, ok, fazer)


def _hdr(info: midia.InfoMidia) -> dict:
    obtido = f"HDR ({info.transferencia})" if info.hdr else "SDR"
    return _item("HDR", "SDR (Rec. 709)", obtido, not info.hdr,
                 "O vídeo saiu em HDR: exportar em Rec. 709 SDR; se o bruto é HDR, converter antes (clipe HDR em "
                 "projeto SDR fica lavado, guia §2 e §6).")


# ---------------------------------------------------------------- conferência

def presets() -> dict:
    return config.carregar("exportacao").get("presets") or {}


def conferir(arquivo: str | Path, destino: str = "reels", duracao_esperada_s: float | None = None,
             som_esperado: str | None = None) -> dict:
    """Confere o arquivo exportado contra o preset do destino. ``aprovado`` só se todos os itens passarem.

    ``som_esperado``: ``"com_som"`` (padrão), ``"mudo"`` ou ``"so_efeitos"`` (ver o topo do módulo)."""
    som_esperado = normalizar_som(som_esperado)
    arquivo = Path(arquivo)
    exp = config.carregar("exportacao")
    todos = exp.get("presets") or {}
    if destino not in todos:
        raise ValueError(f"Destino desconhecido: '{destino}'. Destinos: {', '.join(sorted(todos))}")
    preset = todos[destino]
    info = midia.sondar(arquivo)
    som = midia.loudness(arquivo) if info.tem_audio else {"lufs": None, "lra": None, "pico_real_dbtp": None}
    esperada = float(duracao_esperada_s) if duracao_esperada_s is not None else None
    itens = [
        _duracao(info, preset, exp, destino, esperada),
        _resolucao(info, preset),
        _fps(info, preset, exp),
        _codec(info, preset),
        _formato(arquivo, preset),
        _taxa_bits(info, preset, exp),
        _audio(info, som, exp, som_esperado),
        _volume(info, som, exp, som_esperado),
        _pico(info, som, exp, som_esperado),
        _tamanho(info, preset, destino),
        _hdr(info),
    ]
    resultado = {
        "arquivo": str(arquivo),
        "destino": destino,
        "som_esperado": som_esperado,
        "aprovado": all(i["ok"] for i in itens),
        "itens": itens,
        "medidas": {
            "duracao_s": info.duracao_s, "largura": info.largura, "altura": info.altura, "fps": info.fps,
            "fps_variavel": info.fps_variavel, "codec_video": info.codec_video, "bitrate_kbps": info.bitrate_kbps,
            "tem_audio": info.tem_audio, "codec_audio": info.codec_audio, "taxa_amostragem": info.taxa_amostragem,
            "lufs": _finito(som.get("lufs")), "lra": _finito(som.get("lra")),
            "pico_real_dbtp": _finito(som.get("pico_real_dbtp")), "tamanho_mb": round(info.tamanho_bytes / MB, 2),
            "hdr": info.hdr,
        },
    }
    falhas = [i["item"] for i in itens if not i["ok"]]
    log.info("Conferência de %s (%s): %s%s", arquivo.name, destino, "aprovado" if not falhas else "reprovado",
             f" ({', '.join(falhas)})" if falhas else "")
    return resultado


def texto(resultado: dict) -> str:
    """Relatório curto: o que passou, o que não passou e o que fazer."""
    itens = resultado.get("itens") or []
    falhas = [i for i in itens if not i["ok"]]
    nome = Path(resultado.get("arquivo") or "").name
    if not falhas:
        total = len(itens)
        linhas = [f"Conferência de {nome} ({resultado.get('destino')}): APROVADO ({total} de {total} itens)."]
    else:
        linhas = [f"Conferência de {nome} ({resultado.get('destino')}): REPROVADO, "
                  f"{len(falhas)} de {len(itens)} itens com problema.", "Não passou:"]
        for i in falhas:
            linha = f"- {i['item']}: {i['obtido']} (esperado {i['esperado']})."
            if i.get("fazer"):
                linha += f" Fazer: {i['fazer']}"
            linhas.append(linha)
    passou = [f"{i['item']} {i['obtido']}" for i in itens if i["ok"]]
    if passou:
        linhas.append("Passou: " + "; ".join(passou) + ".")
    return "\n".join(linhas)


# ---------------------------------------------------------------- arquivos, fila e terminal

def pasta_exportado() -> Path:
    sub = (config.carregar("video").get("subpastas_video") or {}).get("exportado", "exportado")
    return config.pastas().videos / sub


def resolver_arquivo(arquivo: str | Path) -> Path:
    """Caminho do vídeo: como veio ou, se for só o nome, dentro de ``videos\\exportado``."""
    caminho = Path(arquivo)
    if caminho.exists():
        return caminho
    if not caminho.is_absolute():
        candidato = pasta_exportado() / caminho
        if candidato.exists():
            return candidato
    raise midia.ErroMidia(f"Não achei o vídeo '{arquivo}' (procurei também em {pasta_exportado()}).")


def mais_recente(pasta: Path | None = None) -> Path:
    pasta = pasta or pasta_exportado()
    videos = [p for p in pasta.glob("*") if p.is_file() and p.suffix.lower() in EXT_VIDEO] if pasta.exists() else []
    if not videos:
        raise midia.ErroMidia(f"Nenhum vídeo em {pasta}. Exporte do CapCut para essa pasta ou passe --arquivo.")
    return max(videos, key=lambda p: p.stat().st_mtime)


def _gravar(ctx: Contexto, resultado: dict, relatorio: str) -> None:
    dados = json.loads(registro.ocultar(json.dumps(resultado, ensure_ascii=False)))
    ctx.arquivo("conferencia.json").write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    ctx.arquivo("conferencia.txt").write_text(registro.ocultar(relatorio) + "\n", encoding="utf-8")


def tarefa(args: dict, ctx: Contexto) -> dict:
    """Pedido ``video.conferir``: args ``{"arquivo", "destino"?, "duracao_esperada_s"?, "som_esperado"?,
    "projeto"?}``. Sem ``som_esperado``, com ``projeto``: deduz do ``plano.json`` do projeto (como o exportar)."""
    if not args.get("arquivo"):
        raise ValueError("Falta o argumento 'arquivo' (caminho ou nome do vídeo em videos\\exportado).")
    caminho = resolver_arquivo(args["arquivo"])
    esperada = args.get("duracao_esperada_s")
    if isinstance(esperada, str):
        try:
            esperada = _segundos(esperada)
        except argparse.ArgumentTypeError as e:
            raise ValueError(str(e)) from None
    som = args.get("som_esperado")
    if not som and args.get("projeto"):
        from .exportar import som_do_projeto

        som = som_do_projeto(args["projeto"])
    resultado = conferir(caminho, args.get("destino") or "reels", esperada, som)
    relatorio = texto(resultado)
    _gravar(ctx, resultado, relatorio)
    return {**resultado, "texto": relatorio}


def _segundos(texto: str) -> float:
    """Duração digitada no terminal: aceita vírgula decimal (``18,5``)."""
    try:
        return float(str(texto).strip().replace(",", "."))
    except ValueError:
        raise argparse.ArgumentTypeError(f"duração inválida: '{texto}' (use segundos, ex.: 18,5)") from None


def _parser(prog: str) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=prog, description="B4: confere o vídeo exportado (duração, resolução, fps, "
                                                       "codec, taxa de bits, áudio, volume, pico, tamanho, HDR).")
    p.add_argument("--arquivo", help="vídeo exportado: caminho, ou só o nome se estiver em videos\\exportado "
                                     "(sem --arquivo: o mais recente de lá)")
    p.add_argument("--destino", default="reels", choices=sorted(presets()))
    p.add_argument("--duracao", type=_segundos, help="duração esperada em segundos (a do plano)")
    p.add_argument("--som", choices=SONS, default=None,
                   help="som esperado: com_som (padrão), mudo (música pelo Instagram, sem fala) ou so_efeitos")
    return p


def cli(argv: list[str]) -> int:
    p = _parser("python -m rotinas video-conferir")
    p.add_argument("--json", action="store_true", help="imprime o resultado em JSON")
    a = p.parse_args(argv)
    try:
        caminho = resolver_arquivo(a.arquivo) if a.arquivo else mais_recente()
        resultado = conferir(caminho, a.destino, a.duracao, a.som)
    except (midia.ErroMidia, ferramentas.FerramentaAusente, ValueError) as e:
        print(f"Erro: {e}", file=sys.stderr)
        return 2
    print(json.dumps(resultado, ensure_ascii=False, indent=2) if a.json else texto(resultado))
    return 0 if resultado["aprovado"] else 1


def teste_real(ctx: Contexto, argv: list[str]) -> dict:
    """``testar.bat conferir [--arquivo X] [--destino D] [--duracao S]``: sem ``--arquivo``, pega o vídeo mais
    recente de ``videos\\exportado``. Grava ``conferencia.json``, ``conferencia.txt`` e ``ffprobe.json``."""
    a = _parser("testar conferir").parse_args(argv)
    caminho = resolver_arquivo(a.arquivo) if a.arquivo else mais_recente()
    sonda = midia.sondar_json(caminho)
    ctx.arquivo("ffprobe.json").write_text(registro.ocultar(json.dumps(sonda, ensure_ascii=False, indent=2)),
                                           encoding="utf-8")
    resultado = conferir(caminho, a.destino, a.duracao, a.som)
    relatorio = texto(resultado)
    _gravar(ctx, resultado, relatorio)
    log.info("%s", relatorio)
    return {
        "arquivo": str(caminho),
        "destino": a.destino,
        "aprovado": resultado["aprovado"],
        "texto": relatorio,
        "versoes": {"ffmpeg": ferramentas.versao("ffmpeg"), "ffprobe": ferramentas.versao("ffprobe")},
        "arquivos": ["conferencia.json", "conferencia.txt", "ffprobe.json"],
    }
