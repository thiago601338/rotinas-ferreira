"""B1: batidas da música (BPM, batidas e compassos), só com numpy (sem librosa/scipy).

Caminho: ffmpeg decodifica para PCM mono → fluxo espectral log-comprimido (envelope de ataques)
→ tempo por autocorrelação com peso log-normal → batidas por programação dinâmica (Ellis 2007)
→ refinamento fino da fase num envelope de alta resolução. Parâmetros em ``config/video.json``
(chaves ``batidas_*``).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .. import config, ferramentas, midia, registro

log = registro.obter("video.batidas")

PADRAO = {
    "taxa_hz": 22050,
    "janela": 2048,
    "salto": 512,
    "bpm_min": 60.0,
    "bpm_max": 180.0,
    "bpm_centro": 110.0,
    "bpm_desvio_oitavas": 1.0,
    "bpm_preferido": [70.0, 140.0],
    "rigidez": 100.0,
    "por_compasso": 4,
    "confianca_descartar": 0.1,
}

_GAMA = 1000.0  # compressão log(1 + γ·|X|) do espectro
_MEDIA_MOVEL_S = 0.25  # média móvel subtraída do fluxo
_JANELA_FINA = 256  # envelope fino (≈ 2,9 ms por quadro a 22050 Hz) para acertar a fase
_SALTO_FINO = 64
_BUSCA_FASE_S = (-0.05, 0.09)  # o envelope grosso adianta o ataque; a fase é procurada nesta faixa
_AJUSTE_LOCAL_S = 0.02  # depois, cada batida ainda pode andar até isto para cair no ataque
_FORCA_S = 0.05  # trecho depois da batida usado para medir a força (escolha do 1º tempo do compasso)
_BLOCO = 512  # quadros por FFT de cada vez (limita a memória em músicas longas)
_PRESENCA = 0.1  # batida fraca nas pontas ainda vale se o ataque tiver ≥ 10% do pico mediano (intro baixa)


def parametros() -> dict:
    try:
        cfg = config.carregar("video")
    except config.ErroConfig:
        cfg = {}
    return {k: cfg.get(f"batidas_{k}", v) for k, v in PADRAO.items()}


# ---------------------------------------------------------------- áudio e envelopes

def decodificar(caminho: Path, taxa_hz: int) -> np.ndarray:
    """Áudio do arquivo (música ou vídeo) em PCM float mono na taxa pedida."""
    caminho = Path(caminho)
    if not caminho.exists():
        raise midia.ErroMidia(f"Arquivo não existe: {caminho}")
    cmd = [midia.ffmpeg(), "-hide_banner", "-nostdin", "-v", "error", "-i", str(caminho), "-map", "0:a:0", "-vn",
           "-ac", "1", "-ar", str(int(taxa_hz)), "-f", "f32le", "-acodec", "pcm_f32le", "-"]
    try:
        r = ferramentas.rodar(cmd, timeout=900, binario=True)
    except ferramentas.ErroComando as e:
        raise midia.ErroMidia(f"Não consegui ler o áudio de {caminho.name} (o arquivo tem faixa de áudio?)") from e
    return np.frombuffer(r.stdout, dtype="<f4").astype(np.float32)


def fluxo_espectral(y: np.ndarray, janela: int, salto: int) -> np.ndarray:
    """Soma das subidas de ``log(1 + γ·|X|)`` entre quadros vizinhos (janela de Hann centrada no quadro)."""
    meio = janela // 2
    y = np.pad(np.asarray(y, dtype=np.float32), (meio, meio))
    n = 1 + (len(y) - janela) // salto if len(y) >= janela else 0
    fluxo = np.zeros(max(n, 0))
    if n < 2:
        return fluxo
    quadros = np.lib.stride_tricks.sliding_window_view(y, janela)[::salto][:n]
    hann = (0.5 - 0.5 * np.cos(2 * np.pi * np.arange(janela) / janela)).astype(np.float32)
    escala = 2.0 / float(hann.sum())  # seno de amplitude 1 → magnitude ≈ 1
    anterior = None
    for i0 in range(0, n, _BLOCO):
        espectro = np.log1p(_GAMA * escala * np.abs(np.fft.rfft(quadros[i0:i0 + _BLOCO] * hann, axis=1)))
        base = np.zeros_like(espectro[:1]) if anterior is None else anterior  # antes do começo: silêncio
        subida = np.diff(np.vstack([base, espectro]), axis=0)
        fluxo[i0:i0 + len(espectro)] = np.maximum(subida, 0.0).sum(axis=1)
        anterior = espectro[-1:]
    return fluxo


def envelope_ataques(y: np.ndarray, taxa_hz: int, janela: int, salto: int) -> np.ndarray:
    """Fluxo espectral menos a média móvel, retificado e normalizado (desvio padrão 1)."""
    fluxo = fluxo_espectral(y, janela, salto)
    if len(fluxo) == 0:
        return fluxo
    n_media = max(1, int(round(_MEDIA_MOVEL_S * taxa_hz / salto))) | 1
    media = np.convolve(fluxo, np.ones(n_media) / n_media, mode="same")
    env = np.maximum(fluxo - media, 0.0)
    desvio = float(env.std())
    return env / desvio if desvio > 1e-12 else np.zeros_like(env)


# ---------------------------------------------------------------- tempo

def autocorrelacao(env: np.ndarray) -> np.ndarray:
    """Autocorrelação sem viés, normalizada pelo atraso zero (1,0 = repetição perfeita)."""
    n = len(env)
    x = env - env.mean()
    tam = 1 << int(np.ceil(np.log2(max(2 * n, 2))))
    f = np.fft.rfft(x, tam)
    ac = np.fft.irfft(f * np.conj(f), tam)[:n]
    ac = ac / (n - np.arange(n))
    return ac / ac[0] if ac[0] > 0 else np.zeros(n)


def _valor(ac: np.ndarray, atraso: float) -> float:
    if atraso < 0 or atraso > len(ac) - 1:
        return 0.0
    return float(np.interp(atraso, np.arange(len(ac)), ac))


def _pico_refinado(ac: np.ndarray, aproximado: float, raio: int = 2) -> float:
    """Máximo local perto de ``aproximado``, com interpolação parabólica (atraso fracionário)."""
    lo = max(1, int(round(aproximado)) - raio)
    hi = min(len(ac) - 2, int(round(aproximado)) + raio)
    if hi < lo:
        return float(aproximado)
    k = lo + int(np.argmax(ac[lo:hi + 1]))
    a, b, c = ac[k - 1], ac[k], ac[k + 1]
    den = a - 2 * b + c
    desl = 0.5 * (a - c) / den if den < 0 else 0.0
    return float(k + float(np.clip(desl, -0.5, 0.5)))


def estimar_tempo(env: np.ndarray, qps: float, p: dict) -> tuple[float, float]:
    """(período em quadros, confiança 0..1) pela autocorrelação com peso log-normal no BPM.

    Dobro/metade: entre picos parecidos o peso decide (centro ~110 BPM); fora da faixa preferida
    (``batidas_bpm_preferido``, 70–140) troca pelo dobro/metade quando a autocorrelação lá é pelo menos
    metade da escolhida.
    """
    ac = autocorrelacao(env)
    lag_min = max(1, int(np.floor(60.0 * qps / float(p["bpm_max"]))))
    lag_max = min(len(ac) - 2, int(np.ceil(60.0 * qps / float(p["bpm_min"]))))
    if lag_max <= lag_min:
        return 0.0, 0.0
    lags = np.arange(lag_min, lag_max + 1)
    bpms = 60.0 * qps / lags
    peso = np.exp(-0.5 * (np.log2(bpms / float(p["bpm_centro"])) / float(p["bpm_desvio_oitavas"])) ** 2)
    pico = (ac[lags] >= ac[lags - 1]) & (ac[lags] >= ac[lags + 1]) & (ac[lags] > 0)
    pontos = np.where(pico, ac[lags] * peso, -np.inf)
    if not np.isfinite(pontos).any():
        return 0.0, 0.0
    atraso = _pico_refinado(ac, float(lags[int(np.argmax(pontos))]))

    pref_min, pref_max = (float(v) for v in p["bpm_preferido"])
    bpm = 60.0 * qps / atraso
    atual = _valor(ac, atraso)
    if bpm > pref_max and bpm / 2 >= float(p["bpm_min"]) and _valor(ac, 2 * atraso) >= 0.5 * atual:
        atraso = _pico_refinado(ac, 2 * atraso)
    elif bpm < pref_min and bpm * 2 <= float(p["bpm_max"]) and _valor(ac, atraso / 2) >= 0.5 * atual:
        atraso = _pico_refinado(ac, atraso / 2)
    return atraso, float(np.clip(_valor(ac, atraso), 0.0, 1.0))


# ---------------------------------------------------------------- rastreamento

def rastrear(env: np.ndarray, periodo: float, rigidez: float) -> np.ndarray:
    """Batidas (índices de quadro) por programação dinâmica (Ellis 2007).

    Pontuação acumulada: C(t) = O(t) + max_τ [C(τ) − rigidez·log²((t−τ)/período)], com τ entre
    t − 2·período e t − período/2. Depois volta do último máximo forte e tira as batidas fracas das pontas.
    """
    n = len(env)
    m = max(1, int(round(periodo)))
    k = np.arange(-m, m + 1)
    local = np.convolve(env, np.exp(-0.5 * (k * 32.0 / periodo) ** 2), mode="full")[m:m + n]
    distancias = np.arange(max(1, int(round(periodo / 2))), int(round(2 * periodo)) + 1)
    penalidade = rigidez * np.log(distancias / periodo) ** 2
    acumulado = np.zeros(n)
    volta = np.full(n, -1, dtype=int)
    limiar_inicio = 0.01 * float(local.max())
    comecou = False
    for t in range(n):
        q = int(np.searchsorted(distancias, t, side="right"))
        if comecou and q > 0:
            anteriores = t - distancias[:q]
            pontos = acumulado[anteriores] - penalidade[:q]
            j = int(np.argmax(pontos))
            acumulado[t] = local[t] + pontos[j]
            volta[t] = anteriores[j]
        else:
            acumulado[t] = local[t]
        comecou = comecou or local[t] >= limiar_inicio

    interno = acumulado[1:-1]
    maximos = np.flatnonzero((interno > acumulado[:-2]) & (interno >= acumulado[2:])) + 1
    if len(maximos) == 0:
        return np.array([], dtype=int)
    mediana = float(np.median(acumulado[maximos]))
    fortes = maximos[acumulado[maximos] > 0.5 * mediana]
    t = int(fortes[-1] if len(fortes) else maximos[-1])
    batidas = [t]
    while volta[batidas[-1]] >= 0:
        batidas.append(int(volta[batidas[-1]]))
    batidas = np.array(batidas[::-1], dtype=int)

    forca = np.convolve(local[batidas], [0.5, 1.0, 0.5], mode="same")
    limiar = 0.5 * float(np.sqrt(np.mean(forca ** 2)))
    validas = np.flatnonzero(forca > limiar)
    if len(validas) == 0:
        return np.array([], dtype=int)
    ini, fim = int(validas[0]), int(validas[-1])
    # Introdução ou final baixos (música que começa só com piano/voz, fade-out) ficam abaixo do limiar
    # acima, mas têm ataque de verdade na batida: estende enquanto o pico do envelope junto da batida
    # passar de _PRESENCA da mediana. Silêncio (ou chiado até ~−40 dBFS) antes da música fica perto de zero.
    raio = max(1, int(round(periodo / 16)))
    borda = np.pad(env, raio)
    pico = np.array([float(borda[b:b + 2 * raio + 1].max()) for b in batidas])
    presente = pico >= _PRESENCA * float(np.median(pico[ini:fim + 1]))
    while ini > 0 and presente[ini - 1]:
        ini -= 1
    while fim < len(batidas) - 1 and presente[fim + 1]:
        fim += 1
    return batidas[ini:fim + 1]


def refinar_fase(tempos: np.ndarray, y: np.ndarray, taxa_hz: int) -> np.ndarray:
    """Acerta a fase das batidas (s) no envelope fino.

    1. Deslocamento global: o envelope grosso (janela longa) marca o ataque um pouco antes; procura o
       deslocamento que põe mais batidas em cima de ataques do envelope fino.
    2. Ajuste local: cada batida vai para o primeiro pico forte (≥ 70% do maior) entre a posição grossa
       (ou 20 ms antes da deslocada) e 20 ms depois da deslocada. Na dúvida, fica o ataque mais cedo
       (corte no transiente ou 1 quadro antes, guia §3).
    """
    fino = fluxo_espectral(y, _JANELA_FINA, _SALTO_FINO)
    if len(fino) < 3 or len(tempos) == 0 or float(fino.max()) <= 0:
        return tempos
    qps = taxa_hz / _SALTO_FINO
    borda = np.pad(fino, 1)
    suave = np.maximum(fino, np.maximum(borda[:-2], borda[2:]))
    grosso = np.clip(np.round(tempos * qps).astype(int), 0, len(fino) - 1)
    desl = np.arange(int(np.floor(_BUSCA_FASE_S[0] * qps)), int(np.ceil(_BUSCA_FASE_S[1] * qps)) + 1)
    grade = np.clip(grosso[:, None] + desl[None, :], 0, len(fino) - 1)
    idx = np.clip(grosso + desl[int(np.argmax(suave[grade].sum(axis=0)))], 0, len(fino) - 1)

    forte = float(np.median(fino[idx]))
    raio = max(1, int(round(_AJUSTE_LOCAL_S * qps)))
    if forte > 0:
        for i, c in enumerate(idx):
            lo = max(0, min(c - raio, grosso[i]))
            hi = min(len(fino), c + raio + 1)
            trecho = fino[lo:hi]
            maior = float(trecho.max())
            if maior < 0.5 * forte:
                continue
            vizinho = np.pad(trecho, 1)
            picos = np.flatnonzero((trecho >= vizinho[:-2]) & (trecho >= vizinho[2:]) & (trecho >= 0.7 * maior))
            idx[i] = lo + int(picos[0])
    return np.unique(idx) / qps  # duas batidas no mesmo ataque viram uma (raro)


def forca_batidas(tempos: np.ndarray, y: np.ndarray, taxa_hz: int) -> np.ndarray:
    """Energia média do sinal nos primeiros ``_FORCA_S`` depois de cada batida (a mais alta é a "mais forte")."""
    n = max(1, int(round(_FORCA_S * taxa_hz)))
    inicio = np.clip(np.round(tempos * taxa_hz).astype(int), 0, len(y))
    return np.array([float(np.mean(y[i:i + n] ** 2)) if i < len(y) else 0.0 for i in inicio])


def _periodo_final(tempos: np.ndarray) -> float:
    """Período (s) pela reta que melhor passa pelas batidas (robusta a batida pulada).

    O número de cada batida sai intervalo a intervalo (um erro pequeno na mediana não se acumula ao
    longo de uma música de minutos, o que trocaria o número das últimas batidas e entortaria a reta).
    """
    periodo = float(np.median(np.diff(tempos)))
    passos = np.maximum(np.round(np.diff(tempos) / periodo), 1.0)
    ordem = np.concatenate([[0.0], np.cumsum(passos)])
    if len(np.unique(ordem)) >= 2:
        periodo = float(np.polyfit(ordem, tempos, 1)[0])
    return periodo


def _compassos(tempos: np.ndarray, forca: np.ndarray, por_compasso: int) -> np.ndarray:
    """A cada ``por_compasso`` batidas, começando pela batida mais forte do início (4 primeiros compassos)."""
    if len(tempos) == 0 or por_compasso < 1:
        return tempos[:0]
    fim = min(len(tempos), 4 * por_compasso)
    pontos = np.array([forca[k:fim:por_compasso].mean() for k in range(min(por_compasso, fim))])
    # empate técnico (diferença < 10%) fica com a primeira: cliques iguais não "escolhem" fase ao acaso
    fase = int(np.flatnonzero(pontos >= 0.9 * pontos.max())[0]) if pontos.max() > 0 else 0
    return tempos[fase::por_compasso]


# ---------------------------------------------------------------- API

def _vazio(motivo: str, caminho: Path, confianca: float = 0.0) -> dict:
    log.warning("Sem batidas em %s: %s", caminho.name, motivo)
    return {"bpm": 0.0, "batidas_s": [], "compassos_s": [], "primeira_batida_s": None, "confianca": round(confianca, 3)}


def detectar_batidas(caminho_audio: str | Path) -> dict:
    """BPM, batidas e compassos (s) da música (ou do áudio de um vídeo).

    ``{"bpm", "batidas_s", "compassos_s", "primeira_batida_s", "confianca"}``. ``confianca`` (0..1) é o pico
    da autocorrelação normalizada do envelope (música com pulso claro fica acima de ~0,5); abaixo de
    ``batidas_confianca_descartar`` não devolve batidas (``bpm`` 0 e listas vazias).
    """
    caminho = Path(caminho_audio)
    p = parametros()
    taxa, janela, salto = int(p["taxa_hz"]), int(p["janela"]), int(p["salto"])
    y = decodificar(caminho, taxa)
    if len(y) < janela * 4 or float(np.max(np.abs(y))) < 1e-4:
        return _vazio("áudio curto demais ou em silêncio", caminho)
    qps = taxa / salto
    env = envelope_ataques(y, taxa, janela, salto)
    if not env.any():
        return _vazio("nenhum ataque no áudio", caminho)
    atraso, confianca = estimar_tempo(env, qps, p)
    if atraso <= 0 or confianca < float(p["confianca_descartar"]):
        return _vazio(f"não achei pulso regular (confiança {confianca:.2f})", caminho, confianca)
    quadros = rastrear(env, atraso, float(p["rigidez"]))
    if len(quadros) == 0:
        return _vazio("o rastreamento não achou batidas fortes", caminho)

    tempos = refinar_fase(quadros * salto / taxa, y, taxa)
    forca = forca_batidas(tempos, y, taxa)
    periodo = _periodo_final(tempos) if len(tempos) >= 2 else atraso / qps
    compassos = _compassos(tempos, forca, int(p["por_compasso"]))
    resultado = {
        "bpm": round(60.0 / periodo, 2),
        "batidas_s": [round(float(t), 3) for t in tempos],
        "compassos_s": [round(float(t), 3) for t in compassos],
        "primeira_batida_s": round(float(tempos[0]), 3),
        "confianca": round(confianca, 3),
    }
    log.info("Batidas de %s: %.1f BPM, %d batidas, primeira em %.2f s, confiança %.2f",
             caminho.name, resultado["bpm"], len(tempos), resultado["primeira_batida_s"], confianca)
    return resultado


def encaixar(tempo_s: float, batidas_s: list[float], tolerancia_s: float = 0.12) -> float:
    """Batida mais próxima de ``tempo_s`` (até ``tolerancia_s``); longe de todas, devolve o próprio tempo."""
    if not batidas_s:
        return float(tempo_s)
    perto = min(batidas_s, key=lambda b: abs(b - tempo_s))
    return float(perto) if abs(perto - tempo_s) <= tolerancia_s + 1e-9 else float(tempo_s)
