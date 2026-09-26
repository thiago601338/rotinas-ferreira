"""B3: gera o rascunho do CapCut 9.5 a partir do plano (``videos/trabalho/<projeto>/plano.json``).

Gerador próprio sobre um gabarito real (o projeto "0925" do PC, BRIEFING §5 B3): clona do gabarito o
esqueleto da linha do tempo, os protótipos de faixa/segmento/material e os arquivos auxiliares, e
monta a linha do tempo nova (tempos do plano em segundos → µs). Efeitos e transições da biblioteca
não entram (licença e risco de "mídia perdida"): vão para o relatório, para o acabamento manual.

Ordem de segurança: CapCut fechado → gabarito em JSON aberto → monta e valida tudo em memória →
backup → grava numa pasta temporária e troca pelo nome final → registra no ``root_meta_info.json``.
Validação falhou = nada gravado. Nunca sobrescreve nem apaga projeto do usuário.
Formato e decisões: ``conhecimento/capcut-avaliacao-ferramentas.md``.
"""

from __future__ import annotations

import argparse
import copy
import fnmatch
import json
import math
import os
import re
import shutil
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .. import config, ferramentas, midia, registro
from ..contexto import Contexto, carimbo
from . import capcut

log = registro.obter("video.rascunho")

sondar_midia = midia.sondar  # trocável nos testes

TIPOS = ("video", "audio", "text")
CHAVE_MATERIAL = {"video": "videos", "audio": "audios", "text": "texts"}

# Protótipos de reserva, usados só quando o gabarito não tem aquele tipo de faixa. Vêm do rascunho
# gerado pelo pyCapCut 0.0.3 (formato do CapCut 6.7): não confirmados na 9.5 — o relatório avisa.
_CLIP = {"alpha": 1.0, "flip": {"horizontal": False, "vertical": False}, "rotation": 0.0,
         "scale": {"x": 1.0, "y": 1.0}, "transform": {"x": 0.0, "y": 0.0}}
_SEGMENTO_BASE = {"enable_adjust": True, "enable_color_correct_adjust": False, "enable_color_curves": True,
                  "enable_color_match_adjust": False, "enable_color_wheels": True, "enable_lut": True,
                  "enable_smart_color_adjust": False, "last_nonzero_volume": 1.0, "reverse": False,
                  "track_attribute": 0, "track_render_index": 0, "visible": True, "id": "", "material_id": "",
                  "target_timerange": {"start": 0, "duration": 0}, "common_keyframes": [], "keyframe_refs": [],
                  "source_timerange": {"start": 0, "duration": 0}, "speed": 1.0, "volume": 1.0,
                  "extra_material_refs": [], "clip": _CLIP, "render_index": 0}
_ESTILO_TEXTO = {"fill": {"alpha": 1.0, "content": {"render_type": "solid", "solid": {"alpha": 1.0, "color": [1.0, 1.0, 1.0]}}},
                 "range": [0, 0], "size": 15.0, "bold": False, "italic": False, "underline": False, "strokes": []}
_VELOCIDADE = {"curve_speed": None, "id": "", "mode": 0, "speed": 1.0, "type": "speed"}
RESERVA = {
    "video": {
        "segmento": {**_SEGMENTO_BASE, "uniform_scale": {"on": True, "value": 1.0},
                     "hdr_settings": {"intensity": 1.0, "mode": 1, "nits": 1000}},
        "material": {"audio_fade": None, "category_id": "", "category_name": "local", "check_flag": 63487,
                     "crop": {"upper_left_x": 0.0, "upper_left_y": 0.0, "upper_right_x": 1.0, "upper_right_y": 0.0,
                              "lower_left_x": 0.0, "lower_left_y": 1.0, "lower_right_x": 1.0, "lower_right_y": 1.0},
                     "crop_ratio": "free", "crop_scale": 1.0, "duration": 0, "height": 0, "id": "",
                     "local_material_id": "", "material_id": "", "material_name": "", "media_path": "", "path": "",
                     "type": "video", "width": 0},
        "refs": [("speeds", _VELOCIDADE)],
    },
    "audio": {
        "segmento": {**_SEGMENTO_BASE, "clip": None, "hdr_settings": None},
        "material": {"app_id": 0, "category_id": "", "category_name": "local", "check_flag": 3,
                     "copyright_limit_type": "none", "duration": 0, "effect_id": "", "formula_id": "", "id": "",
                     "local_material_id": "", "music_id": "", "name": "", "path": "", "source_platform": 0,
                     "type": "extract_music", "wave_points": []},
        "refs": [("speeds", _VELOCIDADE)],
    },
    "text": {
        "segmento": {**_SEGMENTO_BASE, "source_timerange": None, "uniform_scale": {"on": True, "value": 1.0},
                     "render_index": 15000},
        "material": {"id": "", "content": json.dumps({"styles": [_ESTILO_TEXTO], "text": ""}, ensure_ascii=False),
                     "typesetting": 0, "alignment": 1, "letter_spacing": 0.0, "line_spacing": 0.02, "line_feed": 1,
                     "line_max_width": 0.82, "force_apply_line_max_width": False, "check_flag": 7, "type": "text",
                     "global_alpha": 1.0},
        "refs": [],
    },
}
META_RESERVA = {"draft_cover": "", "draft_fold_path": "", "draft_id": "", "draft_is_ai_shorts": False,
                "draft_is_invisible": False, "draft_json_file": "", "draft_name": "", "draft_new_version": "",
                "draft_root_path": "", "draft_timeline_materials_size_": 0, "tm_draft_create": 0,
                "tm_draft_modified": 0, "tm_draft_removed": 0, "tm_duration": 0,
                "draft_materials": [{"type": 0, "value": []}]}
_ENTRADA_MIDIA = {"ai_group_type": "", "create_time": -1, "duration": 0, "enter_from": 0, "extra_info": "",
                  "file_Path": "", "height": 0, "id": "", "import_time": -1, "import_time_ms": -1, "item_source": 1,
                  "material_color_tag": "", "md5": "", "metetype": "video",
                  "roughcut_time_range": {"duration": -1, "start": -1}, "sub_time_range": {"duration": -1, "start": -1},
                  "type": 0, "width": 0}
_PROPORCOES = {(9, 16): "9:16", (16, 9): "16:9", (1, 1): "1:1", (3, 4): "3:4", (4, 3): "4:3", (4, 5): "4:5", (2, 1): "2:1"}


class ErroRascunho(capcut.ErroCapCut):
    """Não deu para gerar o rascunho."""


class ErroValidacao(ErroRascunho):
    """O rascunho montado não passou na validação (nada foi gravado)."""

    def __init__(self, erros: list[str]):
        self.erros = list(erros)
        resumo = "; ".join(self.erros[:8]) + (f" (+{len(self.erros) - 8})" if len(self.erros) > 8 else "")
        super().__init__(f"Rascunho não gravado: {len(self.erros)} problema(s) na validação: {resumo}")
        self.resultado_parcial = {"erros_validacao": self.erros}


# ---------------------------------------------------------------- gabarito

@dataclass
class ArquivoLinha:
    """Um arquivo do gabarito que guarda a linha do tempo (direta ou num envelope)."""

    nome: str
    raiz: dict
    caminho: tuple
    recuo: int | str | None

    @property
    def doc(self) -> dict:
        return capcut.achar_linha_do_tempo(self.raiz)[0]


@dataclass
class Gabarito:
    pasta: Path
    linhas: list[ArquivoLinha]
    meta: dict | None
    meta_recuo: int | str | None = None
    avisos: list[str] = field(default_factory=list)

    @property
    def doc(self) -> dict:
        return self.linhas[0].doc

    @property
    def principal(self) -> str:
        return self.linhas[0].nome

    @property
    def versao(self) -> str | None:
        plataforma = self.doc.get("last_modified_platform") or self.doc.get("platform") or {}
        return plataforma.get("app_version") if isinstance(plataforma, dict) else None


def carregar_gabarito(pasta: Path) -> Gabarito:
    """Lê o projeto gabarito. Recusa se estiver criptografado (não começa com ``{``)."""
    pasta = Path(pasta)
    c = capcut.cfg()
    if not pasta.is_dir():
        raise ErroRascunho(f"Pasta do gabarito não existe: {pasta}")
    linhas: list[ArquivoLinha] = []
    avisos: list[str] = []
    for nome in c["arquivos_linha_do_tempo"]:
        arq = pasta / nome
        fmt = capcut.formato(arq)
        if fmt == "ausente":
            continue
        if fmt == "criptografado":
            raise capcut.GabaritoCriptografado(
                f"O {nome} do gabarito não é JSON aberto (parece criptografado). Esta versão do CapCut não dá para "
                "automatizar por arquivo; mande o diagnóstico para análise."
            )
        if fmt != "json":
            raise ErroRascunho(f"O {nome} do gabarito está {fmt.replace('_', ' ')}.")
        texto = arq.read_text(encoding="utf-8-sig")
        raiz = json.loads(texto)
        achado = capcut.achar_linha_do_tempo(raiz)
        if not achado:
            avisos.append(f"{nome} do gabarito é JSON sem linha do tempo: vai copiado como arquivo auxiliar.")
            continue
        linhas.append(ArquivoLinha(nome, raiz, achado[1], capcut.recuo_de(texto)))
    if not linhas:
        raise ErroRascunho(f"O gabarito {pasta} não tem linha do tempo legível ({', '.join(c['arquivos_linha_do_tempo'])}).")
    meta, meta_recuo = None, None
    arq_meta = pasta / c["arquivo_meta"]
    fmt = capcut.formato(arq_meta)
    if fmt == "criptografado":
        raise capcut.GabaritoCriptografado(f"O {c['arquivo_meta']} do gabarito não é JSON aberto.")
    if fmt == "json":
        texto = arq_meta.read_text(encoding="utf-8-sig")
        meta, meta_recuo = json.loads(texto), capcut.recuo_de(texto)
    else:
        avisos.append(f"Gabarito sem {c['arquivo_meta']} legível: usei o modelo mínimo (não confirmado na 9.5).")
    return Gabarito(pasta, linhas, meta, meta_recuo, avisos)


def _indice_materiais(doc: dict) -> dict[str, tuple[str, dict]]:
    indice: dict[str, tuple[str, dict]] = {}
    for chave, lista in (doc.get("materials") or {}).items():
        if isinstance(lista, list):
            for m in lista:
                if isinstance(m, dict) and m.get("id"):
                    indice[m["id"]] = (chave, m)
    return indice


@dataclass
class Prototipo:
    tipo: str
    faixa: dict
    segmento: dict
    material: dict
    refs: list[tuple[str, dict]]
    origem: str  # "gabarito" ou "reserva"

    @property
    def chave(self) -> str:
        return CHAVE_MATERIAL[self.tipo]


def prototipos(doc: dict) -> dict[str, Prototipo]:
    """Um protótipo por tipo (vídeo, áudio, texto), preferindo mídia local à da biblioteca."""
    c = capcut.cfg()
    indice = _indice_materiais(doc)
    melhores: dict[str, tuple[int, Prototipo]] = {}
    for faixa in doc.get("tracks") or []:
        tipo = faixa.get("type")
        if tipo not in TIPOS:
            continue
        for seg in faixa.get("segments") or []:
            chave, mat = indice.get(seg.get("material_id"), (None, None))
            if chave != CHAVE_MATERIAL[tipo]:
                continue
            nota = 0
            if mat.get("category_name") == "local":
                nota += 2
            if (tipo == "video" and mat.get("type") == "video") or (tipo == "audio" and mat.get("type") == c["tipo_audio_local"]):
                nota += 1
            if tipo in melhores and melhores[tipo][0] >= nota:
                continue
            refs = [indice[r] for r in seg.get("extra_material_refs") or [] if r in indice]
            base_faixa = {k: v for k, v in faixa.items() if k != "segments"}
            melhores[tipo] = (nota, Prototipo(tipo, copy.deepcopy(base_faixa), copy.deepcopy(seg), copy.deepcopy(mat),
                                              copy.deepcopy(refs), "gabarito"))
    return {t: p for t, (_, p) in melhores.items()}


def prototipo_reserva(tipo: str) -> Prototipo:
    r = RESERVA[tipo]
    faixa = {"attribute": 0, "flag": 0, "id": "", "is_default_name": True, "name": "", "type": tipo}
    return Prototipo(tipo, faixa, copy.deepcopy(r["segmento"]), copy.deepcopy(r["material"]),
                     copy.deepcopy(r["refs"]), "reserva")


# ---------------------------------------------------------------- utilidades

def _s(valor: float) -> str:
    return f"{valor:.2f}".replace(".", ",")


# Técnicas que o rascunho já faz sozinho: #1 punch-in e o 100/110% do jump cut entram na escala do clipe;
# #14 corte na batida e #15 jump cut são os próprios cortes da linha do tempo. Pedir de novo à mão dá zoom duplo.
APLICADAS_PELO_RASCUNHO = {1, 14, 15}


def _aplicado_pelo_rascunho(efeito: dict) -> bool:
    """O efeito do plano já está no rascunho (não vai para a lista do acabamento à mão)?"""
    try:
        tecnica = int(efeito.get("tecnica"))
    except (TypeError, ValueError):
        return False
    if tecnica in APLICADAS_PELO_RASCUNHO:
        return True
    # efeito sonoro com arquivo: entra como faixa de áudio (plano.audio, papel "efeito_sonoro")
    return tecnica == 57 and bool((efeito.get("parametros") or {}).get("arquivo"))


def _proporcao(largura: int, altura: int) -> str:
    d = math.gcd(int(largura), int(altura)) or 1
    return _PROPORCOES.get((int(largura) // d, int(altura) // d), "original")


def _normalizado(x_px: float, y_px: float, largura: int, altura: int) -> tuple[float, float]:
    """Pixels do quadro (origem no canto de cima) → transform do CapCut (−1..1, y para cima)."""
    return round((float(x_px) - largura / 2) / (largura / 2), 6), round((altura / 2 - float(y_px)) / (altura / 2), 6)


def _distribuir(itens: list[tuple[int, int, dict]]) -> list[list[tuple[int, int, dict]]]:
    """Distribui itens (início, fim, dado) em faixas sem sobreposição (primeira faixa livre)."""
    faixas: list[list] = []
    fins: list[int] = []
    for item in sorted(itens, key=lambda t: t[0]):
        for i, fim in enumerate(fins):
            if item[0] >= fim:
                faixas[i].append(item)
                fins[i] = item[1]
                break
        else:
            faixas.append([item])
            fins.append(item[1])
    return faixas


def _trocar_textos(valor, trocas: dict[str, str]):
    """Troca textos (ids e caminhos antigos do gabarito) em qualquer estrutura JSON."""
    if isinstance(valor, str):
        for antigo, novo in trocas.items():
            if antigo in valor:
                valor = valor.replace(antigo, novo)
        return valor
    if isinstance(valor, dict):
        return {k: _trocar_textos(v, trocas) for k, v in valor.items()}
    if isinstance(valor, list):
        return [_trocar_textos(v, trocas) for v in valor]
    return valor


def _limpar_caminhos_derivados(valor, topo: bool = True) -> None:
    """Zera, em qualquer nível, os campos de texto ``*_path`` (menos o ``path`` do próprio material)."""
    if isinstance(valor, dict):
        for k, v in valor.items():
            if isinstance(v, str) and k.lower().endswith("_path") and not (topo and k == "path"):
                valor[k] = ""
            elif isinstance(v, (dict, list)):
                _limpar_caminhos_derivados(v, False)
    elif isinstance(valor, list):
        for v in valor:
            _limpar_caminhos_derivados(v, False)


def _trocas_em_texto_json(trocas: dict[str, str]) -> dict[str, str]:
    """Acrescenta a forma escapada no JSON (``\\\\``) das trocas com barra invertida (texto cru do arquivo)."""
    saida = dict(trocas)
    for antigo, novo in trocas.items():
        if "\\" in antigo:
            saida.setdefault(antigo.replace("\\", "\\\\"), novo.replace("\\", "\\\\"))
    return saida


def _carimbo_agora(referencia) -> int:
    """Agora na unidade do carimbo do gabarito (s, ms ou µs); sem referência válida, µs (o que o CapCut usa)."""
    valor = capcut.carimbo_como(referencia)
    if isinstance(valor, bool) or not isinstance(valor, int) or valor <= 0:
        return capcut.us(datetime.now().timestamp())
    return valor


def _serializar(dados, recuo) -> bytes:
    if recuo in (None, 0, ""):
        return json.dumps(dados, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return json.dumps(dados, ensure_ascii=False, indent=recuo).encode("utf-8")


def pasta_trabalho(projeto: str) -> Path:
    return config.pastas().videos / "trabalho" / projeto


# ---------------------------------------------------------------- montagem

@dataclass
class Montagem:
    doc: dict
    meta: dict
    arquivos: dict[str, bytes]
    midias: dict[str, dict]
    resumo: dict
    avisos: list[str]
    manual: list[str]
    protos: dict[str, Prototipo]
    entrada_indice: dict | None = None


class _Construtor:
    def __init__(self, gabarito: Gabarito, plano: dict, nome: str, pasta_rascunhos: Path):
        self.c = capcut.cfg()
        self.g = gabarito
        self.plano = plano
        self.nome = nome
        self.pasta_rascunhos = Path(pasta_rascunhos)
        self.pasta_final = self.pasta_rascunhos / nome
        self.avisos: list[str] = list(gabarito.avisos)
        self.manual: list[str] = []
        self.omitidos: set[str] = set()
        self.protos = prototipos(gabarito.doc)
        for tipo in TIPOS:
            if tipo not in self.protos:
                self.protos[tipo] = prototipo_reserva(tipo)
        self.midias: dict[str, dict] = {}
        exemplos = [(gabarito.meta or {}).get("draft_fold_path")] + [p.material.get("path") for p in self.protos.values()]
        self.sep = capcut.estilo_separador(*exemplos)
        canvas = plano.get("canvas") or {}
        self.largura = int(canvas.get("largura", 1080))
        self.altura = int(canvas.get("altura", 1920))
        self.fps = float(canvas.get("fps", 30))

    # -------------------------------------------------- materiais

    def _novo_material(self, proto: Prototipo) -> dict:
        m = copy.deepcopy(proto.material)
        antigo, novo = m.get("id"), capcut.novo_id()
        for k, v in list(m.items()):
            if antigo and v == antigo:
                m[k] = novo  # ex.: "material_id" repetindo o id (pyCapCut)
        m["id"] = novo
        return m

    def _refs(self, proto: Prototipo, velocidade: float = 1.0) -> list[str]:
        ids = []
        omitir = set(self.c.get("omitir_materiais") or [])
        for chave, mat in proto.refs:
            if chave in omitir:
                self.omitidos.add(chave)
                continue
            novo = copy.deepcopy(mat)
            novo["id"] = capcut.novo_id()
            if chave == "speeds":
                novo["speed"] = velocidade
                if "mode" in novo:
                    novo["mode"] = 0
                if "curve_speed" in novo:
                    novo["curve_speed"] = None
            elif chave == "audio_fades":
                for k in ("fade_in_duration", "fade_out_duration"):
                    if k in novo:
                        novo[k] = 0
            elif chave == "material_animations" and isinstance(novo.get("animations"), list) and novo["animations"]:
                novo["animations"] = []
                self.omitidos.add("animações de entrada/saída")
            self.doc["materials"].setdefault(chave, []).append(novo)
            ids.append(novo["id"])
        return ids

    def _midia(self, tipo: str, arquivo: str) -> dict:
        """Material de vídeo/foto/áudio (um por arquivo) + a entrada de ``draft_materials`` do meta."""
        caminho = Path(arquivo)
        if not caminho.is_absolute():
            caminho = pasta_trabalho(str(self.plano.get("projeto") or "")) / caminho
        chave_cache = f"{tipo}|{caminho}"
        if chave_cache in self.midias:
            return self.midias[chave_cache]
        if not caminho.exists():
            raise ErroValidacao([f"arquivo de mídia não existe: {caminho}"])
        info = sondar_midia(caminho)
        proto = self.protos[tipo]
        m = self._novo_material(proto)
        foto = tipo == "video" and midia.eh_foto(caminho)
        duracao = int(self.c["foto_duracao_us"]) if foto else capcut.us(info.duracao_s or 0)
        if proto.material.get("category_name") not in (None, "local"):
            # Protótipo tirado de item da Biblioteca: vira mídia local (valores das 3 ferramentas avaliadas).
            for campo in self.c.get("limpar_campos_origem") or []:
                if isinstance(m.get(campo), str):
                    m[campo] = ""
            m["category_name"] = "local"
            if "copyright_limit_type" in m:
                m["copyright_limit_type"] = "none"
            for campo in self.c.get("zerar_campos_origem") or ["source_platform"]:
                if isinstance(m.get(campo), int) and not isinstance(m.get(campo), bool):
                    m[campo] = 0
            aviso = f"O protótipo de {tipo} do gabarito veio da Biblioteca do CapCut: limpei os campos de origem (conferir)."
            if aviso not in self.avisos:
                self.avisos.append(aviso)
        # Arquivos derivados da mídia do GABARITO (reverso, estabilização, "intensifies"...): apontariam para
        # arquivos que não são deste vídeo. Vale também para protótipo local.
        _limpar_caminhos_derivados(m)
        m["path"] = capcut.caminho_capcut(caminho, self.sep)
        m["duration"] = duracao
        if tipo == "video":
            m["material_name"] = caminho.name
            m["type"] = "photo" if foto else "video"
            m["width"], m["height"] = int(info.largura or 0), int(info.altura or 0)
            if isinstance(m.get("crop"), dict):
                m["crop"] = copy.deepcopy(RESERVA["video"]["material"]["crop"])
            if "crop_ratio" in m:
                m["crop_ratio"] = "free"
            if "crop_scale" in m:
                m["crop_scale"] = 1.0
            if "has_audio" in m:
                m["has_audio"] = bool(info.tem_audio)
        else:
            m["name"] = caminho.name
            m["type"] = self.c["tipo_audio_local"]
            if "music_id" in m:
                m["music_id"] = str(uuid.uuid4())
            if isinstance(m.get("wave_points"), list):
                m["wave_points"] = []
        local_id = capcut.novo_id()
        m["local_material_id"] = local_id
        self.doc["materials"].setdefault(proto.chave, []).append(m)
        dado = {"material": m, "caminho": caminho, "info": info, "local_id": local_id,
                "metetype": "photo" if foto else ("video" if tipo == "video" else "music")}
        self.midias[chave_cache] = dado
        return dado

    def _material_texto(self, texto: str, tamanho_px: float, estilo_nome: str) -> dict:
        proto = self.protos["text"]
        m = self._novo_material(proto)
        estilos = self.c.get("estilos_texto") or {}
        estilo = estilos.get(estilo_nome) or estilos.get("padrao") or {}
        try:
            conteudo = json.loads(m.get("content") or "{}")
        except (TypeError, ValueError):
            conteudo = {}
        if not isinstance(conteudo, dict):
            conteudo = {}
        base = (conteudo.get("styles") or [_ESTILO_TEXTO])[0]
        st = copy.deepcopy(base if isinstance(base, dict) else _ESTILO_TEXTO)
        tamanho = round(float(tamanho_px) / float(self.c["texto_px_por_unidade"]), 2)
        st["range"] = [0, capcut.tamanho_utf16(texto)]
        st["size"] = tamanho
        if "negrito" in estilo:
            st["bold"] = bool(estilo["negrito"])
        if estilo.get("cor"):
            fill = st.setdefault("fill", copy.deepcopy(_ESTILO_TEXTO["fill"]))
            solid = fill.setdefault("content", {}).setdefault("solid", {"alpha": 1.0})
            fill["content"].setdefault("render_type", "solid")
            solid["color"] = capcut.cor_rgb(estilo["cor"])
        contorno = bool(estilo.get("contorno_cor"))
        if contorno:
            largura = float(estilo.get("contorno_largura", 40)) / 100.0 * 0.2  # escala do pyCapCut (não confirmada)
            existentes = st.get("strokes") if isinstance(st.get("strokes"), list) else []
            traco = copy.deepcopy(existentes[0]) if existentes and isinstance(existentes[0], dict) else {}
            traco.setdefault("content", {}).setdefault("solid", {"alpha": 1.0})["color"] = capcut.cor_rgb(estilo["contorno_cor"])
            traco["width"] = round(largura, 4)
            st["strokes"] = [traco]
        conteudo["styles"] = [st]
        conteudo["text"] = texto
        m["content"] = json.dumps(conteudo, ensure_ascii=False)
        if "font_size" in m:
            m["font_size"] = tamanho
        if "alignment" in m and "alinhamento" in estilo:
            m["alignment"] = int(estilo["alinhamento"])
        if contorno and isinstance(m.get("check_flag"), int) and not isinstance(m.get("check_flag"), bool):
            m["check_flag"] |= 8
        if isinstance(m.get("words"), dict):
            m["words"] = {k: ([] if isinstance(v, list) else v) for k, v in m["words"].items()}
        self.doc["materials"].setdefault("texts", []).append(m)
        return m

    # -------------------------------------------------- segmentos

    def _segmento(self, proto: Prototipo, material_id: str, refs: list[str], ini: int, dur: int,
                  fonte: tuple[int, int] | None, velocidade: float, volume: float, faixa_idx: int) -> dict:
        s = copy.deepcopy(proto.segmento)
        s["id"] = capcut.novo_id()
        s["material_id"] = material_id
        s["extra_material_refs"] = refs
        s["target_timerange"] = {"start": ini, "duration": dur}
        if fonte is not None:
            s["source_timerange"] = {"start": fonte[0], "duration": fonte[1]}
        elif isinstance(s.get("source_timerange"), dict):
            s["source_timerange"] = {"start": 0, "duration": dur}
        if "speed" in s:
            s["speed"] = velocidade
        if "volume" in s:
            s["volume"] = volume
        if "last_nonzero_volume" in s and volume > 0:
            s["last_nonzero_volume"] = volume
        for k in ("common_keyframes", "keyframe_refs"):
            if isinstance(s.get(k), list):
                s[k] = []
        for k in ("group_id", "raw_segment_id"):
            if isinstance(s.get(k), str):
                s[k] = ""
        if isinstance(s.get("reverse"), bool):
            s["reverse"] = False  # o trecho do gabarito podia estar invertido; o plano não pede isso
        for k in ("render_index", "track_render_index"):
            if isinstance(s.get(k), int) and not isinstance(s.get(k), bool):
                s[k] = s[k] + faixa_idx
        return s

    @staticmethod
    def _clip(s: dict, escala: float | None = None, x: float | None = None, y: float | None = None) -> None:
        clip = s.get("clip")
        if not isinstance(clip, dict):
            return
        if escala is not None:
            clip["scale"] = {"x": escala, "y": escala}
            if isinstance(s.get("uniform_scale"), dict) and "value" in s["uniform_scale"]:
                s["uniform_scale"]["value"] = escala
        if x is not None or y is not None:
            transform = clip.setdefault("transform", {"x": 0.0, "y": 0.0})
            transform["x"], transform["y"] = x or 0.0, y or 0.0
        clip["alpha"] = 1.0
        clip["rotation"] = 0.0
        if isinstance(clip.get("flip"), dict):
            clip["flip"] = {"horizontal": False, "vertical": False}

    def _tempos(self, item: dict, onde: str) -> tuple[int, int]:
        try:
            ini_s, dur_s = float(item["ini_s"]), float(item["dur_s"])
        except (KeyError, TypeError, ValueError) as e:
            raise ErroValidacao([f"{onde}: 'ini_s' e 'dur_s' são obrigatórios ({e})"]) from e
        ini = capcut.us(ini_s)
        return ini, capcut.us(ini_s + dur_s) - ini

    def _trechos_midia(self, tipo: str, itens: list[dict], rotulo: str) -> list[tuple[int, int, dict]]:
        saida = []
        quadro = capcut.us(1 / self.fps)
        for i, item in enumerate(itens):
            onde = f"plano.{rotulo}[{i}]"
            if not item.get("arquivo"):
                raise ErroValidacao([f"{onde}: sem 'arquivo'"])
            ini, dur = self._tempos(item, onde)
            velocidade = float(item.get("velocidade") or 1.0)
            dado = self._midia(tipo, item["arquivo"])
            fonte_ini = capcut.us(float(item.get("fonte_ini_s") or 0.0))
            fonte_dur = int(round(dur * velocidade))
            limite = int(dado["material"]["duration"])
            excesso = fonte_ini + fonte_dur - limite
            if 0 < excesso <= quadro:
                fonte_dur -= excesso
            if item.get("fonte_fim_s") is not None:
                fim_pedido = capcut.us(float(item["fonte_fim_s"]))
                if abs(fim_pedido - (fonte_ini + fonte_dur)) > quadro:
                    self.avisos.append(f"{onde}: fonte_fim_s não bate com dur_s × velocidade; usei dur_s.")
            saida.append((ini, ini + dur, {"item": item, "dado": dado, "fonte": (fonte_ini, fonte_dur),
                                           "velocidade": velocidade, "i": i}))
        return saida

    def _faixa(self, proto: Prototipo, j: int, segmentos: list[dict], nome: str | None = None) -> dict:
        f = copy.deepcopy(proto.faixa)
        f["id"] = capcut.novo_id()
        if nome is not None and "name" in f:
            f["name"] = nome
            if "is_default_name" in f:
                f["is_default_name"] = False
        elif j and "name" in f and f.get("name") and not f.get("is_default_name"):
            f["name"] = f"{f['name']} {j + 1}"
        f["segments"] = segmentos
        return f

    def _faixas_midia(self, tipo: str, rotulo: str) -> list[dict]:
        itens = self.plano.get(rotulo) or []
        proto = self.protos[tipo]
        faixas = []
        for j, grupo in enumerate(_distribuir(self._trechos_midia(tipo, itens, rotulo))):
            segs = []
            for ini, fim, d in grupo:
                item = d["item"]
                volume = capcut.db_para_linear(float(item.get("volume_db") or 0.0))
                if item.get("papel") == "guia" or item.get("mudo"):
                    volume = 0.0  # faixa-guia só marca o ritmo: nunca pode sair no arquivo exportado
                refs = self._refs(proto, d["velocidade"])
                s = self._segmento(proto, d["dado"]["material"]["id"], refs, ini, fim - ini, d["fonte"],
                                   d["velocidade"], volume, j)
                if tipo == "video":
                    x = y = None
                    if item.get("x") is not None or item.get("y") is not None:
                        x, y = _normalizado(item.get("x", self.largura / 2), item.get("y", self.altura / 2),
                                            self.largura, self.altura)
                    self._clip(s, float(item.get("escala") or 1.0), x, y)
                segs.append(s)
            faixas.append(self._faixa(proto, j, segs))
        return faixas

    def _faixas_texto(self, rotulo: str, padrao: dict | None, deslocamento: int = 0) -> list[dict]:
        itens = self.plano.get(rotulo) or []
        proto = self.protos["text"]
        trechos = []
        for i, item in enumerate(itens):
            onde = f"plano.{rotulo}[{i}]"
            if not str(item.get("texto") or "").strip():
                raise ErroValidacao([f"{onde}: sem 'texto'"])
            ini, dur = self._tempos(item, onde)
            trechos.append((ini, ini + dur, {"item": {**(padrao or {}), **{k: v for k, v in item.items() if v is not None}}}))
        faixas = []
        nome = "legendas" if rotulo == "legendas" else None
        for j, grupo in enumerate(_distribuir(trechos)):
            segs = []
            for ini, fim, d in grupo:
                item = d["item"]
                tamanho = float(item.get("tamanho_px") or (padrao or {}).get("tamanho_px") or 64)
                estilo = str(item.get("estilo") or ("legenda" if rotulo == "legendas" else "padrao"))
                m = self._material_texto(str(item["texto"]), tamanho, estilo)
                refs = self._refs(proto)
                s = self._segmento(proto, m["id"], refs, ini, fim - ini, None, 1.0, 1.0, j + deslocamento)
                x, y = _normalizado(item.get("x", self.largura / 2), item.get("y", self.altura / 2), self.largura, self.altura)
                self._clip(s, 1.0, x, y)
                segs.append(s)
            faixas.append(self._faixa(proto, j, segs, f"{nome} {j + 1}" if nome and j else nome))
        return faixas

    # -------------------------------------------------- documento

    def _esqueleto(self) -> dict:
        doc = copy.deepcopy(self.g.doc)
        for chave, valor in list(doc.items()):
            if chave in ("materials", "keyframes") and isinstance(valor, dict):
                for sub, lista in valor.items():
                    if isinstance(lista, list):
                        valor[sub] = []
            elif chave in ("cover", "retouch_cover", "time_marks") and valor is not None:
                doc[chave] = None
            elif isinstance(valor, list):
                doc[chave] = []
        doc["tracks"] = []
        doc["id"] = capcut.novo_id()
        doc["name"] = self.nome
        if isinstance(doc.get("static_cover_image_path"), str):
            doc["static_cover_image_path"] = ""
        canvas = copy.deepcopy(doc.get("canvas_config") or {})
        mesmo = canvas.get("width") == self.largura and canvas.get("height") == self.altura
        canvas["width"], canvas["height"] = self.largura, self.altura
        if not (mesmo and canvas.get("ratio")):
            canvas["ratio"] = _proporcao(self.largura, self.altura)
        doc["canvas_config"] = canvas
        fps_gabarito = self.g.doc.get("fps")
        doc["fps"] = int(self.fps) if isinstance(fps_gabarito, int) and self.fps.is_integer() else self.fps
        for k in ("create_time", "update_time"):
            doc[k] = capcut.carimbo_como(doc.get(k))
        return doc

    def _ordem_tipos(self) -> list[str]:
        ordem = []
        for faixa in self.g.doc.get("tracks") or []:
            if faixa.get("type") in TIPOS and faixa["type"] not in ordem:
                ordem.append(faixa["type"])
        return ordem + [t for t in TIPOS if t not in ordem]

    def montar(self) -> Montagem:
        self.doc = self._esqueleto()
        faixas: dict[str, list[dict]] = {
            "video": self._faixas_midia("video", "video"),
            "audio": self._faixas_midia("audio", "audio"),
        }
        textos = self._faixas_texto("textos", None)
        padrao_legenda = dict(self.c.get("legenda_padrao") or {})
        faixas["text"] = textos + self._faixas_texto("legendas", padrao_legenda, len(textos))
        for tipo in self._ordem_tipos():
            self.doc["tracks"].extend(faixas[tipo])
        fim = 0
        for faixa in self.doc["tracks"]:
            for s in faixa["segments"]:
                fim = max(fim, s["target_timerange"]["start"] + s["target_timerange"]["duration"])
        self.doc["duration"] = fim
        for tipo in TIPOS:
            confirmado = tipo == "audio" and self.c.get("audio_reserva_confirmado")
            if (self.protos[tipo].origem == "reserva" and not confirmado
                    and any(f["type"] == tipo and f["segments"] for f in self.doc["tracks"])):
                self.avisos.append(f"O gabarito não tem faixa de {tipo}: usei o protótipo de reserva (pyCapCut, "
                                   "não confirmado na 9.5). Conferir esse item no CapCut.")
        if faixas["text"] and not self.c.get("texto_calibrado"):
            self.avisos.append(f"Tamanho dos textos aproximado (fator provisório {self.c['texto_px_por_unidade']} px por "
                               "unidade de 'size'): conferir no CapCut e calibrar com a régua.")
        if len(faixas["video"]) > 1:
            self.avisos.append(f"Trechos de vídeo do plano se sobrepõem: foram para {len(faixas['video'])} faixas de "
                               "vídeo (a de cima cobre a de baixo). Conferir o plano.")
        self._manual()
        id_meta = self.doc["id"] if (self.g.meta or {}).get("draft_id") == self.g.doc.get("id") else capcut.novo_id()
        meta = self._meta(id_meta)
        trocas = self._trocas(id_meta)
        arquivos = self._arquivos(meta, trocas)
        resumo = {
            "nome": self.nome, "duracao_s": capcut.segundos(fim), "largura": self.largura, "altura": self.altura,
            "fps": self.doc["fps"], "video": sum(len(f["segments"]) for f in faixas["video"]),
            "audio": sum(len(f["segments"]) for f in faixas["audio"]),
            "textos": len(self.plano.get("textos") or []), "legendas": len(self.plano.get("legendas") or []),
            "faixas": {t: len(faixas[t]) for t in TIPOS}, "arquivos": sorted(arquivos),
        }
        return Montagem(self.doc, meta, arquivos, self.midias, resumo, self.avisos, self.manual, self.protos)

    def _manual(self) -> None:
        """Acabamento à mão, completo: transições que não são corte seco, efeitos que o rascunho não aplica,
        o ``acabamento`` do plano (composição, cor, faixa-guia, loop, legendas) e os protótipos omitidos."""
        for t in self.plano.get("transicoes") or []:
            tipo = str(t.get("tipo") or "")
            if tipo and tipo not in ("corte_seco", "corte", "nenhuma"):
                entre = t.get("entre") or []
                self.manual.append(f"Transição '{tipo}' entre os blocos {' e '.join(str(int(x) + 1) for x in entre)}"
                                   f" ({_s(float(t.get('dur_s') or 0))} s): fazer à mão (aba Transições, item comercial "
                                   "ou equivalente feito com ferramentas).")
        acabamento = self.plano.get("acabamento")
        tem_acabamento = isinstance(acabamento, list)
        vistos = set()
        for e in self.plano.get("efeitos") or []:
            if _aplicado_pelo_rascunho(e):
                continue
            if tem_acabamento and e.get("manual"):
                continue  # já está no acabamento do plano, com o "como fazer"
            ini = float(e.get("ini_s") or 0)
            chave = (e.get("tecnica"), round(ini, 3), e.get("som"))
            if chave in vistos:
                continue
            vistos.add(chave)
            fim = ini + float(e.get("dur_s") or 0)
            nome = e.get("nome") or ""
            if e.get("som"):
                nome = f"{nome} ({e['som']})" if nome else str(e["som"])
            self.manual.append(f"Efeito {e.get('tecnica', '?')} '{nome}' em {_s(ini)}–{_s(fim)} s: fazer à mão "
                               "(edicao-video-capcut.md §4.2).")
        if tem_acabamento:
            self.manual.extend(str(x) for x in acabamento if str(x).strip() and str(x) not in self.manual)
        for chave in sorted(self.omitidos):
            self.manual.append(f"O protótipo do gabarito tinha '{chave}': não copiado (biblioteca). Se precisar, aplicar à mão.")

    def _meta(self, id_meta: str) -> dict:
        g = self.g.meta
        meta = copy.deepcopy(g) if isinstance(g, dict) else copy.deepcopy(META_RESERVA)
        fold = capcut.caminho_capcut(self.pasta_final, self.sep)
        raiz = capcut.caminho_capcut(self.pasta_rascunhos, self.sep)
        antigo_fold = (g or {}).get("draft_fold_path") if isinstance(g, dict) else None
        if isinstance(antigo_fold, str) and len(antigo_fold) >= 8:
            # Antes de preencher os campos novos (o caminho novo pode começar com o antigo).
            meta = _trocar_textos(meta, {antigo_fold.replace("\\", "/"): fold.replace("\\", "/"),
                                         antigo_fold.replace("/", "\\"): fold.replace("/", "\\")})
        agora = _carimbo_agora((g or {}).get("tm_draft_create") if isinstance(g, dict) else None)
        tamanho = 0
        for d in self.midias.values():
            try:
                tamanho += d["caminho"].stat().st_size
            except OSError:
                pass
        meta.update({"draft_id": id_meta, "draft_name": self.nome, "draft_fold_path": fold, "draft_root_path": raiz,
                     "draft_cover": "", "tm_draft_create": agora, "tm_draft_modified": agora,
                     "tm_duration": self.doc["duration"]})
        if "draft_json_file" in meta:
            meta["draft_json_file"] = fold + self.sep + self.g.principal
        for k in ("draft_timeline_materials_size_", "draft_timeline_materials_size"):
            if k in meta:
                meta[k] = tamanho
        for k in ("draft_segment_extra_info", "draft_materials_copied_info"):
            if isinstance(meta.get(k), list):
                meta[k] = []
        meta["draft_materials"] = self._draft_materials(meta.get("draft_materials"))
        achado = capcut.achar_linha_do_tempo(meta)
        if achado and achado[1]:
            capcut.recolocar(meta, achado[1], self.doc)
        return meta

    def _draft_materials(self, grupos) -> list:
        grupos = copy.deepcopy(grupos) if isinstance(grupos, list) else [{"type": 0, "value": []}]
        alvo = next((g for g in grupos if isinstance(g, dict) and g.get("type") == 0), None)
        if alvo is None:
            alvo = {"type": 0, "value": []}
            grupos.insert(0, alvo)
        modelo = next((v for v in alvo.get("value") or [] if isinstance(v, dict)), None) or _ENTRADA_MIDIA
        for g in grupos:
            if isinstance(g, dict) and isinstance(g.get("value"), list):
                g["value"] = []
        for d in self.midias.values():
            e = copy.deepcopy(modelo)
            info, m = d["info"], d["material"]
            e.update({"id": d["local_id"], "file_Path": m["path"], "extra_info": d["caminho"].name,
                      "duration": m["duration"], "metetype": d["metetype"], "type": 0,
                      "width": 0 if d["metetype"] == "music" else int(info.largura or 0),
                      "height": 0 if d["metetype"] == "music" else int(info.altura or 0)})
            for k in ("create_time", "import_time", "import_time_ms"):
                if k in e:
                    e[k] = capcut.carimbo_como(e[k])
            if "md5" in e:
                e["md5"] = ""
            alvo["value"].append(e)
        return grupos

    def _trocas(self, id_meta: str) -> dict[str, str]:
        trocas: dict[str, str] = {}
        for a in self.g.linhas:
            antigo = a.doc.get("id")
            if isinstance(antigo, str) and len(antigo) >= 8:
                trocas[antigo] = self.doc["id"]
        antigo_meta = (self.g.meta or {}).get("draft_id")
        if isinstance(antigo_meta, str) and len(antigo_meta) >= 8:
            trocas[antigo_meta] = id_meta
        antigo_fold = (self.g.meta or {}).get("draft_fold_path")
        if isinstance(antigo_fold, str) and len(antigo_fold) >= 8:
            fold = capcut.caminho_capcut(self.pasta_final, self.sep)
            trocas[antigo_fold.replace("\\", "/")] = fold.replace("\\", "/")
            trocas[antigo_fold.replace("/", "\\")] = fold.replace("/", "\\")
        return trocas

    def _arquivos(self, meta: dict, trocas: dict[str, str]) -> dict[str, bytes]:
        """Tudo o que vai para a pasta do projeto: auxiliares clonados + linha do tempo + meta."""
        c = self.c
        arquivos: dict[str, bytes] = {}
        padroes = list(c.get("nao_copiar") or [])
        midia_ext = {e.lower() for e in c.get("extensoes_midia") or []}
        limite = int(float(c.get("max_mb_arquivo_auxiliar", 5)) * 1024 * 1024)
        proprios = {a.nome for a in self.g.linhas} | {c["arquivo_meta"]}
        trocas_cru = _trocas_em_texto_json(trocas)  # no texto cru do JSON, "C:\x" aparece como "C:\\x"
        for pasta_atual, subpastas, nomes in os.walk(self.g.pasta):
            subpastas[:] = sorted(s for s in subpastas if not capcut.ignorar(s, padroes))
            for nome in sorted(nomes):
                arq = Path(pasta_atual) / nome
                rel = arq.relative_to(self.g.pasta).as_posix()
                if rel in proprios or capcut.ignorar(nome, padroes):
                    continue
                if arq.suffix.lower() in midia_ext:
                    self.avisos.append(f"Mídia do gabarito não copiada: {rel}")
                    continue
                if arq.stat().st_size > limite:
                    self.avisos.append(f"Arquivo grande do gabarito não copiado: {rel}")
                    continue
                dados = arq.read_bytes()
                try:
                    texto = dados.decode("utf-8")
                except UnicodeDecodeError:
                    arquivos[rel] = dados
                    continue
                for antigo, novo in trocas_cru.items():
                    texto = texto.replace(antigo, novo)
                arquivos[rel] = texto.encode("utf-8")
        for a in self.g.linhas:
            raiz = capcut.recolocar(copy.deepcopy(a.raiz), a.caminho, self.doc)
            if a.caminho:
                raiz = _trocar_textos(raiz, trocas)
                capcut.recolocar(raiz, a.caminho, self.doc)
            arquivos[a.nome] = _serializar(raiz, a.recuo)
        arquivos[c["arquivo_meta"]] = _serializar(meta, self.g.meta_recuo)
        if c.get("timelines") == "espelhar":
            arquivos.update(self._timelines(trocas))
        return arquivos

    def _timelines(self, trocas: dict[str, str]) -> dict[str, bytes]:
        base = self.g.pasta / "Timelines"
        projeto = base / "project.json"
        if not base.is_dir():
            return {}
        antigo = None
        if capcut.formato(projeto) == "json":
            antigo = capcut.ler_json(projeto).get("main_timeline_id")
        dirs = [d for d in sorted(base.iterdir()) if d.is_dir()]
        principal = next((d for d in dirs if d.name == antigo), dirs[0] if dirs else None)
        novo = self.doc["id"]
        mapa = _trocas_em_texto_json(trocas)
        for d in dirs:
            mapa.setdefault(d.name, novo)
        if antigo:
            mapa[antigo] = novo
        saida: dict[str, bytes] = {}
        ignorar = [x for x in (self.c.get("nao_copiar") or []) if x != "Timelines"]
        for arq in sorted(base.rglob("*")):
            if not arq.is_file() or any(fnmatch.fnmatch(arq.name, x) for x in ignorar):
                continue  # .bak, capa e travas do gabarito não vão para o projeto novo
            partes = arq.relative_to(base).parts
            if len(partes) > 1 and principal is not None and partes[0] != principal.name:
                self.avisos.append(f"Linha do tempo extra do gabarito não copiada: Timelines/{'/'.join(partes)}")
                continue
            rel = "Timelines/" + "/".join((novo,) + partes[1:] if len(partes) > 1 else partes)
            if len(partes) > 1 and arq.name in self.c["arquivos_linha_do_tempo"] and capcut.formato(arq) == "json":
                raiz = capcut.ler_json(arq)
                achado = capcut.achar_linha_do_tempo(raiz)
                if achado:
                    saida[rel] = _serializar(capcut.recolocar(raiz, achado[1], self.doc), None)
                    continue
            try:
                texto = arq.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                saida[rel] = arq.read_bytes()
                continue
            for a, n in mapa.items():
                texto = texto.replace(a, n)
            saida[rel] = texto.encode("utf-8")
        return saida


# ---------------------------------------------------------------- validação

def _tipo_json(v) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, (int, float)):
        return "numero"
    if isinstance(v, str):
        return "texto"
    if isinstance(v, list):
        return "lista"
    if isinstance(v, dict):
        return "objeto"
    return type(v).__name__


def _comparar(referencia: dict, gerado: dict, onde: str, erros: list[str]) -> None:
    for chave, valor in referencia.items():
        if chave not in gerado:
            erros.append(f"{onde}: falta a chave '{chave}' que o gabarito tem")
            continue
        a, b = _tipo_json(valor), _tipo_json(gerado[chave])
        if "null" not in (a, b) and a != b:
            erros.append(f"{onde}: '{chave}' é {b}, no gabarito é {a}")


def validar(doc: dict, gabarito: Gabarito, protos: dict[str, Prototipo] | None = None,
            meta: dict | None = None, midias: dict[str, dict] | None = None) -> list[str]:
    """Confere o rascunho montado contra o gabarito. Devolve a lista de problemas (vazia = ok)."""
    erros: list[str] = []
    ref_doc = gabarito.doc
    _comparar({k: v for k, v in ref_doc.items()}, doc, "linha do tempo", erros)
    ref_mats = ref_doc.get("materials") or {}
    for chave in ref_mats:
        if chave not in (doc.get("materials") or {}):
            erros.append(f"materials: falta a lista '{chave}'")
    # Referência de cada tipo: o protótipo clonado (do gabarito ou de reserva); senão o 1º exemplo do gabarito.
    ref_mat: dict[str, dict] = {}
    for chave, exemplos in ref_mats.items():
        if isinstance(exemplos, list) and exemplos and isinstance(exemplos[0], dict):
            ref_mat[chave] = exemplos[0]
    ref_seg: dict[str, dict] = {}
    for faixa in ref_doc.get("tracks") or []:
        if faixa.get("segments") and faixa.get("type") not in ref_seg:
            ref_seg[faixa["type"]] = faixa["segments"][0]
    for p in (protos or {}).values():
        ref_mat[p.chave] = p.material
        ref_mat.update({k: m for k, m in p.refs})
        ref_seg[p.tipo] = p.segmento
    for chave, lista in (doc.get("materials") or {}).items():
        if isinstance(lista, list) and chave in ref_mat:
            for i, m in enumerate(lista):
                _comparar(ref_mat[chave], m, f"materials.{chave}[{i}]", erros)
    indice = _indice_materiais(doc)
    ids: dict[str, str] = {}

    def registrar_id(valor, onde):
        if not valor:
            erros.append(f"{onde}: id vazio")
        elif valor in ids:
            erros.append(f"{onde}: id repetido ({valor}, também em {ids[valor]})")
        else:
            ids[valor] = onde

    for chave, lista in (doc.get("materials") or {}).items():
        for i, m in enumerate(lista if isinstance(lista, list) else []):
            if isinstance(m, dict):
                registrar_id(m.get("id"), f"materials.{chave}[{i}]")
    fim_total = 0
    for fi, faixa in enumerate(doc.get("tracks") or []):
        registrar_id(faixa.get("id"), f"tracks[{fi}]")
        janelas = []
        for si, s in enumerate(faixa.get("segments") or []):
            onde = f"tracks[{fi}].segments[{si}]"
            registrar_id(s.get("id"), onde)
            if faixa.get("type") in ref_seg:
                _comparar(ref_seg[faixa["type"]], s, onde, erros)
            if s.get("material_id") not in indice:
                erros.append(f"{onde}: material_id não existe nos materiais")
            elif faixa.get("type") in CHAVE_MATERIAL and indice[s["material_id"]][0] != CHAVE_MATERIAL[faixa["type"]]:
                erros.append(f"{onde}: faixa de {faixa['type']} aponta para material de "
                             f"'{indice[s['material_id']][0]}' (esperado '{CHAVE_MATERIAL[faixa['type']]}')")
            for r in s.get("extra_material_refs") or []:
                if r not in indice:
                    erros.append(f"{onde}: extra_material_refs aponta para material inexistente ({r})")
            alvo = s.get("target_timerange") or {}
            ini, dur = alvo.get("start"), alvo.get("duration")
            if not all(isinstance(v, int) and not isinstance(v, bool) for v in (ini, dur)) or ini < 0 or dur <= 0:
                erros.append(f"{onde}: target_timerange precisa de inteiros em µs (start ≥ 0, duration > 0)")
                continue
            janelas.append((ini, ini + dur))
            fim_total = max(fim_total, ini + dur)
            fonte = s.get("source_timerange")
            if isinstance(fonte, dict):
                fi_, fd = fonte.get("start"), fonte.get("duration")
                if not all(isinstance(v, int) and not isinstance(v, bool) for v in (fi_, fd)) or fi_ < 0 or fd <= 0:
                    erros.append(f"{onde}: source_timerange precisa de inteiros em µs")
                else:
                    chave, mat = indice.get(s.get("material_id"), (None, {}))
                    if chave in ("videos", "audios") and isinstance(mat.get("duration"), int) and fi_ + fd > mat["duration"]:
                        erros.append(f"{onde}: trecho pedido ({fi_ + fd} µs) passa do fim do arquivo ({mat['duration']} µs)")
            if faixa.get("type") == "text":
                chave, mat = indice.get(s.get("material_id"), (None, {}))
                try:
                    conteudo = json.loads(mat.get("content") or "")
                    ok = isinstance(conteudo.get("text"), str) and isinstance(conteudo.get("styles"), list)
                except (TypeError, ValueError, AttributeError):
                    ok = False
                if not ok:
                    erros.append(f"{onde}: conteúdo do texto não é o JSON com 'styles' e 'text'")
        janelas.sort()
        for (a0, a1), (b0, _b1) in zip(janelas, janelas[1:], strict=False):
            if b0 < a1:
                erros.append(f"tracks[{fi}]: segmentos sobrepostos ({a0}–{a1} µs e {b0} µs)")
    if doc.get("duration") != fim_total:
        erros.append(f"duração da linha do tempo ({doc.get('duration')}) diferente do fim do último segmento ({fim_total})")
    for d in (midias or {}).values():
        if not Path(d["caminho"]).exists():
            erros.append(f"mídia não encontrada: {d['caminho']}")
    if meta is not None:
        ref_meta = gabarito.meta if isinstance(gabarito.meta, dict) else META_RESERVA
        _comparar(ref_meta, meta, "draft_meta_info", erros)
        registrados = {v.get("id") for g in meta.get("draft_materials") or [] if isinstance(g, dict)
                       for v in g.get("value") or [] if isinstance(v, dict)}
        for chave in ("videos", "audios"):
            for m in (doc.get("materials") or {}).get(chave) or []:
                if m.get("local_material_id") not in registrados:
                    erros.append(f"materials.{chave}: local_material_id sem entrada em draft_materials ({m.get('path')})")
    return erros


# ---------------------------------------------------------------- índice e gravação

def _registrar_indice(pasta_rascunhos: Path, pasta_final: Path, meta: dict, gabarito: Gabarito, sep: str) -> str:
    """Acrescenta o projeto no ``root_meta_info.json`` clonando uma entrada existente. Devolve o motivo."""
    c = capcut.cfg()
    modo = c.get("registrar_no_indice", "auto")
    arq = Path(pasta_rascunhos) / c["arquivo_indice"]
    if modo == "nunca":
        return "não registrado (config: nunca)"
    indice = capcut.ler_indice(pasta_rascunhos)
    if indice is None and arq.exists():
        return f"não registrado: {arq.name} ilegível (deixado como está)"
    chave = capcut.chave_do_indice(indice) if indice else None
    lista = indice.get(chave) if (indice and chave) else None
    if modo == "auto" and not lista:
        return f"não registrado: {arq.name} não existe ou não lista projetos (modo auto)"
    indice = indice or {}
    chave = chave or "all_draft_store"
    lista = list(indice.get(chave) or [])
    nome_gab = (gabarito.meta or {}).get("draft_name") or gabarito.pasta.name
    modelo = next((e for e in lista if isinstance(e, dict) and e.get("draft_name") == nome_gab), None) \
        or next((e for e in lista if isinstance(e, dict)), None)
    fold = capcut.caminho_capcut(pasta_final, sep)
    entrada = copy.deepcopy(modelo) if modelo else {
        "draft_cover": "", "draft_fold_path": "", "draft_id": "", "draft_is_ai_shorts": False,
        "draft_is_invisible": False, "draft_json_file": "", "draft_name": "", "draft_new_version": "",
        "draft_root_path": "", "draft_timeline_materials_size": 0, "tm_draft_create": 0, "tm_draft_modified": 0,
        "tm_draft_removed": 0, "tm_duration": 0}
    entrada.update({
        "draft_fold_path": fold, "draft_id": meta.get("draft_id"), "draft_name": meta.get("draft_name"),
        "draft_json_file": fold + sep + gabarito.principal, "draft_root_path": capcut.caminho_capcut(pasta_rascunhos, sep),
        "draft_cover": "", "tm_draft_removed": 0, "tm_duration": meta.get("tm_duration"),
    })
    if modelo:  # carimbos na unidade que o próprio índice usa
        entrada["tm_draft_create"] = entrada["tm_draft_modified"] = _carimbo_agora(modelo.get("tm_draft_create"))
    else:
        entrada["tm_draft_create"], entrada["tm_draft_modified"] = meta.get("tm_draft_create"), meta.get("tm_draft_modified")
    if "draft_timeline_materials_size" in entrada:
        entrada["draft_timeline_materials_size"] = meta.get("draft_timeline_materials_size_",
                                                             meta.get("draft_timeline_materials_size", 0))
    lista.append(entrada)
    indice[chave] = lista
    atual = indice.get("draft_ids")
    if isinstance(atual, int) and not isinstance(atual, bool):
        # Suposição (confirmar com o índice real): contador de projetos. Nunca diminui — se for um
        # contador que só cresce (projetos apagados continuam contados), baixar para len(lista) quebraria.
        indice["draft_ids"] = max(atual + 1, len(lista))
    recuo = capcut.recuo_de(arq.read_text(encoding="utf-8-sig")) if arq.exists() else None
    capcut.gravar_json(arq, indice, recuo)
    return f"registrado em {arq.name}"


def _gravar_projeto(pasta_rascunhos: Path, nome: str, arquivos: dict[str, bytes]) -> Path:
    """Grava numa pasta temporária e troca pelo nome final (nunca sobre uma pasta existente)."""
    tmp = Path(pasta_rascunhos) / f".rotinas-tmp-{uuid.uuid4().hex[:10]}"
    final = Path(pasta_rascunhos) / nome
    tmp.mkdir(parents=True)
    try:
        for rel, dados in arquivos.items():
            alvo = tmp / Path(rel)
            alvo.parent.mkdir(parents=True, exist_ok=True)
            alvo.write_bytes(dados)
        for tentativa in range(5):
            if final.exists():
                raise ErroRascunho(f"Apareceu uma pasta '{nome}' durante a gravação; nada foi sobrescrito.")
            try:
                os.replace(tmp, final)
                break
            except PermissionError:  # Windows: antivírus/indexador segurando um arquivo recém-gravado
                if tentativa == 4:
                    raise
                time.sleep(0.5)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)  # só a pasta temporária criada aqui
        raise
    return final


# ---------------------------------------------------------------- relatório

@dataclass
class Resultado:
    pasta: Path
    nome: str
    resumo: dict
    avisos: list[str]
    manual: list[str]
    backup: Path | None
    indice: str
    relatorio: Path | None
    relatorio_texto: str
    gabarito: Path

    def como_dict(self) -> dict:
        return {"rascunho": self.nome, "pasta": str(self.pasta), "resumo": self.resumo, "avisos": self.avisos,
                "manual": self.manual, "backup": str(self.backup) if self.backup else None, "indice": self.indice,
                "relatorio": str(self.relatorio) if self.relatorio else None, "gabarito": str(self.gabarito)}


def texto_relatorio(plano: dict, m: Montagem, pasta: Path, gabarito: Gabarito, backup: Path | None, indice: str) -> str:
    r = m.resumo
    L = [f"Rascunho do CapCut: {r['nome']}", f"Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')}",
         f"Projeto: {plano.get('projeto', '?')} · receita {plano.get('receita', '?')} · destino {plano.get('destino', '?')}",
         f"Pasta: {pasta}",
         f"Gabarito: {gabarito.pasta} (CapCut {gabarito.versao or '?'}; linha do tempo em "
         f"{', '.join(a.nome for a in gabarito.linhas)})",
         f"Duração: {_s(r['duracao_s'])} s · {r['largura']}×{r['altura']} · {r['fps']} fps",
         f"Backup: {backup}" if backup else "Backup: não feito (modo ensaio ou desligado)",
         f"Índice do CapCut: {indice}", "", "O que entrou:"]
    for i, it in enumerate(plano.get("video") or [], 1):
        vel = float(it.get("velocidade") or 1)
        L.append(f"- Vídeo {i}: {_s(float(it['ini_s']))}–{_s(float(it['ini_s']) + float(it['dur_s']))} s ← "
                 f"{Path(str(it['arquivo'])).name} a partir de {_s(float(it.get('fonte_ini_s') or 0))} s"
                 f" · vel {_s(vel)} · vol {_s(float(it.get('volume_db') or 0))} dB · {it.get('papel') or ''}".rstrip(" ·"))
    for i, it in enumerate(plano.get("textos") or [], 1):
        estilo = it.get("estilo") or it.get("papel") or "padrão"
        L.append(f"- Texto {i}: {_s(float(it['ini_s']))}–{_s(float(it['ini_s']) + float(it['dur_s']))} s \"{it['texto']}\""
                 f" ({estilo}, {it.get('tamanho_px', '?')} px, x {it.get('x', '?')} y {it.get('y', '?')})")
    if plano.get("legendas"):
        L.append(f"- Legendas: {len(plano['legendas'])} bloco(s) na faixa 'legendas'")
    for i, it in enumerate(plano.get("audio") or [], 1):
        L.append(f"- Áudio {i}: {_s(float(it['ini_s']))}–{_s(float(it['ini_s']) + float(it['dur_s']))} s ← "
                 f"{Path(str(it['arquivo'])).name} · vol {_s(float(it.get('volume_db') or 0))} dB"
                 f" · {it.get('papel') or ''}".rstrip(" ·"))
    L += ["", "Fica para o acabamento manual:"]
    L += [f"- {x}" for x in m.manual] or ["- nada além do checklist"]
    L.append("- Checklist antes de exportar: conhecimento/edicao-video-capcut.md §9 (cor fiel, volume, zonas seguras).")
    if m.avisos:
        L += ["", "Avisos:"] + [f"- {x}" for x in m.avisos]
    L += ["", f"Próximo passo: abrir o CapCut, abrir o projeto \"{r['nome']}\" e conferir se abriu sem \"mídia perdida\"; "
          "depois o acabamento acima e a exportação (python -m rotinas video-exportar)."]
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- gerar

def gerar_completo(plano: dict, pasta_rascunhos: Path, gabarito: Path, nome: str, *, fazer_backup: bool = True,
                   verificar_capcut: bool = True, pasta_relatorio: Path | None = None,
                   criar_pasta: bool = False) -> Resultado:
    """Gera o rascunho e devolve tudo o que aconteceu (``gerar`` devolve só a pasta).

    ``criar_pasta`` só no ensaio: na pasta de rascunhos do CapCut, pasta inexistente é config errada
    (o projeto iria para um lugar que o CapCut não lê), então recusa.
    """
    pasta_rascunhos = Path(pasta_rascunhos)
    if plano.get("violacoes"):
        raise ErroValidacao([f"O plano tem violação das regras (corrigir as escolhas e planejar de novo): {v}"
                             for v in plano["violacoes"]])
    if verificar_capcut:
        capcut.exigir_capcut_fechado()
    gab = carregar_gabarito(Path(gabarito))
    if not pasta_rascunhos.is_dir():
        if not criar_pasta:
            raise ErroRascunho(f"A pasta de rascunhos do CapCut não existe: {pasta_rascunhos} "
                               "(conferir capcut_rascunhos em config/pastas.json). Nada foi gravado.")
        pasta_rascunhos.mkdir(parents=True)
    nome_final = capcut.nome_livre(pasta_rascunhos, nome, capcut.ler_indice(pasta_rascunhos))
    if nome_final != capcut.sanitizar_nome(nome):
        log.info("Já existe um projeto '%s': o novo vai se chamar '%s'", nome, nome_final)
    faltando = []
    for rotulo in ("video", "audio"):
        for i, item in enumerate(plano.get(rotulo) or []):
            arq = item.get("arquivo")
            if arq and Path(arq).is_absolute() and not Path(arq).exists():
                faltando.append(f"plano.{rotulo}[{i}]: arquivo não existe: {arq}")
    if faltando:
        raise ErroValidacao(faltando)
    construtor = _Construtor(gab, plano, nome_final, pasta_rascunhos)
    m = construtor.montar()
    erros = validar(m.doc, gab, m.protos, m.meta, m.midias)
    if erros:
        raise ErroValidacao(erros)
    copia = None
    if fazer_backup:
        mesmo_nome = pasta_rascunhos / capcut.sanitizar_nome(nome)
        copia = capcut.backup(pasta_rascunhos, [mesmo_nome] if mesmo_nome.is_dir() else [])
    if verificar_capcut:
        capcut.exigir_capcut_fechado()
    pasta = _gravar_projeto(pasta_rascunhos, nome_final, m.arquivos)
    try:
        indice = _registrar_indice(pasta_rascunhos, pasta, m.meta, gab, construtor.sep)
    except Exception as e:  # noqa: BLE001 — o projeto já está gravado: avisar e seguir para o relatório
        indice = f"não registrado: {e}"
        m.avisos.append(f"Não consegui registrar no índice do CapCut ({e}); o projeto foi gravado mesmo assim.")
    texto = texto_relatorio(plano, m, pasta, gab, copia, indice)
    relatorio = None
    if pasta_relatorio is None and plano.get("projeto"):
        pasta_relatorio = pasta_trabalho(str(plano["projeto"]))
    if pasta_relatorio is not None:
        relatorio = Path(pasta_relatorio) / "relatorio_rascunho.txt"
        relatorio.parent.mkdir(parents=True, exist_ok=True)
        relatorio.write_text(texto, encoding="utf-8")
    log.info("Rascunho '%s' gravado em %s", nome_final, pasta)
    return Resultado(pasta, nome_final, m.resumo, m.avisos, m.manual, copia, indice, relatorio, texto, gab.pasta)


def gerar(plano: dict, pasta_rascunhos: Path, gabarito: Path, nome: str, **opcoes) -> Path:
    """Gera o rascunho do CapCut a partir do plano. Devolve a pasta do projeto criado."""
    return gerar_completo(plano, pasta_rascunhos, gabarito, nome, **opcoes).pasta


# ---------------------------------------------------------------- gabarito: onde achar e inspecionar

def _projeto_no_pc(pasta_rascunhos: Path, projeto: str) -> Path | None:
    direto = Path(pasta_rascunhos) / projeto
    if direto.is_dir():
        return direto
    if not Path(pasta_rascunhos).is_dir():
        return None
    for pasta in sorted(p for p in Path(pasta_rascunhos).iterdir() if p.is_dir()):
        meta = pasta / capcut.cfg()["arquivo_meta"]
        try:
            if capcut.formato(meta) == "json" and capcut.ler_json(meta).get("draft_name") == projeto:
                return pasta
        except (OSError, ValueError, AttributeError):
            continue
    return None


def _tem_linha(pasta: Path) -> bool:
    return any((pasta / n).is_file() for n in capcut.cfg()["arquivos_linha_do_tempo"])


def _pasta_execucoes() -> str:
    try:
        return config.carregar("diagnostico").get("execucao", {}).get("pasta", "execucoes")
    except config.ErroConfig:
        return "execucoes"


def _copias_do_diagnostico(raiz: Path, projeto: str) -> list[Path]:
    """Cópias ``execucoes/<carimbo>_diagnostico/capcut_<projeto>/`` feitas pelo diagnóstico, da mais nova à mais velha."""
    pasta = _pasta_execucoes()
    nome = "capcut_" + re.sub(r"[^\w.\-]+", "_", projeto)
    base = Path(raiz) / pasta
    if not base.is_dir():
        return []
    return sorted((p / nome for p in base.iterdir() if (p / nome).is_dir()), key=lambda p: p.parent.name, reverse=True)


def localizar_gabarito(pasta_rascunhos: Path | None = None, raiz: Path | None = None) -> Path:
    """Onde está o gabarito, nesta ordem: ``config gabarito_pasta`` no repositório; a cópia mais nova feita pelo
    diagnóstico (``execucoes/*/capcut_0925``); o projeto "0925" nos rascunhos do PC (só leitura)."""
    c = capcut.cfg()
    raiz = Path(raiz) if raiz else config.RAIZ
    base = Path(c["gabarito_pasta"])
    base = base if base.is_absolute() else raiz / base
    for candidato in (base / c["gabarito_projeto"], base):
        if candidato.is_dir() and _tem_linha(candidato):
            return candidato
    if c.get("gabarito_procurar_execucoes", True):
        for candidato in _copias_do_diagnostico(raiz, c["gabarito_projeto"]):
            if _tem_linha(candidato):
                return candidato
    if c.get("gabarito_usar_projeto_do_pc", True):
        achado = _projeto_no_pc(pasta_rascunhos or config.pastas().capcut_rascunhos, c["gabarito_projeto"])
        if achado and _tem_linha(achado):
            return achado
    onde = [str(base)]
    if c.get("gabarito_procurar_execucoes", True):
        onde.append(f"cópias do diagnóstico em {raiz / _pasta_execucoes()}")
    if c.get("gabarito_usar_projeto_do_pc", True):
        onde.append(f"rascunhos do CapCut em {pasta_rascunhos or config.pastas().capcut_rascunhos}")
    raise ErroRascunho(
        f"Gabarito do CapCut não encontrado: o projeto '{c['gabarito_projeto']}' não está nos rascunhos do CapCut "
        f"(procurei em: {'; '.join(onde)}). Confirmar se o projeto '{c['gabarito_projeto']}' existe no CapCut ou "
        "qual projeto usar como gabarito e repetir informando a pasta dele em 'gabarito' (args.gabarito do "
        "pedido video.rascunho; no terminal, --gabarito)."
    )


def inspecionar(pasta: Path) -> dict:
    """O que o gabarito tem e o que falta para o gerador (útil quando o gabarito real chegar)."""
    c = capcut.cfg()
    pasta = Path(pasta)
    d: dict = {"pasta": str(pasta), "arquivos": {}}
    for nome in list(c["arquivos_linha_do_tempo"]) + [c["arquivo_meta"]]:
        d["arquivos"][nome] = capcut.formato(pasta / nome)
    d["timelines"] = (pasta / "Timelines").is_dir()
    try:
        gab = carregar_gabarito(pasta)
    except capcut.ErroCapCut as e:
        d["erro"] = str(e)
        return d
    doc = gab.doc
    d.update({"principal": gab.principal, "versao": gab.versao, "new_version": doc.get("new_version"),
              "version": doc.get("version"), "canvas": doc.get("canvas_config"), "fps": doc.get("fps"),
              "avisos": gab.avisos, "chaves_topo": sorted(doc),
              "espelhos_iguais": all(a.doc == doc for a in gab.linhas),
              "envelopes": {a.nome: "/".join(a.caminho) for a in gab.linhas if a.caminho}})
    protos = prototipos(doc)
    d["prototipos"] = {t: {"material": p.material.get("type"), "categoria": p.material.get("category_name"),
                           "refs": [k for k, _ in p.refs], "tem_local_material_id": "local_material_id" in p.material}
                       for t, p in protos.items()}
    d["faltam"] = [t for t in TIPOS if t not in protos]
    if gab.meta is not None:
        grupos = gab.meta.get("draft_materials") or []
        d["draft_materials"] = {str(g.get("type")): len(g.get("value") or []) for g in grupos if isinstance(g, dict)}
    return d


# ---------------------------------------------------------------- fila, terminal e teste real

def _nome_padrao(plano: dict) -> str:
    modelo = capcut.cfg().get("nome_padrao", "{projeto} {data}")
    return modelo.format(projeto=plano.get("projeto") or "rascunho", data=datetime.now().strftime("%Y-%m-%d"),
                         destino=plano.get("destino") or "")


def _ler_plano(projeto: str, arquivo: str | None = None) -> dict:
    caminho = Path(arquivo) if arquivo else pasta_trabalho(projeto) / "plano.json"
    if not caminho.is_file():
        raise ErroRascunho(f"Plano não encontrado: {caminho} (rode antes o video-planejar).")
    plano = json.loads(caminho.read_text(encoding="utf-8-sig"))
    plano.setdefault("projeto", projeto)
    return plano


def tarefa(args: dict, ctx: Contexto) -> dict:
    """Tipo ``video.rascunho``: ``{"projeto", "nome"?, "gabarito"?}``. Em ensaio grava na pasta da execução."""
    projeto = args.get("projeto")
    if not projeto:
        raise ErroRascunho("Falta 'projeto' nos argumentos.")
    plano = _ler_plano(projeto, args.get("plano"))
    nome = args.get("nome") or _nome_padrao(plano)
    if ctx.ensaio:
        destino = ctx.pasta_saida / "rascunhos_ensaio"
        gabarito = Path(args["gabarito"]) if args.get("gabarito") else localizar_gabarito()
        # relatório só na pasta do pedido: o do projeto é o do rascunho real (o video.exportar lê de lá)
        r = gerar_completo(plano, destino, gabarito, nome, fazer_backup=False, verificar_capcut=False,
                           criar_pasta=True, pasta_relatorio=ctx.pasta_saida)
    else:
        gabarito = Path(args["gabarito"]) if args.get("gabarito") else localizar_gabarito()
        r = gerar_completo(plano, config.pastas().capcut_rascunhos, gabarito, nome)
    ctx.arquivo("relatorio_rascunho.txt").write_text(r.relatorio_texto, encoding="utf-8")
    return {**r.como_dict(), "ensaio": ctx.ensaio}


def cli(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="python -m rotinas video-rascunho",
                                description="B3: gera o rascunho do CapCut a partir do plano (CapCut fechado).")
    p.add_argument("--projeto", help="projeto em videos/trabalho/<projeto>/ (lê plano.json)")
    p.add_argument("--plano", help="caminho de outro plano.json")
    p.add_argument("--nome", help="nome do projeto no CapCut (padrão: config/capcut.json nome_padrao)")
    p.add_argument("--gabarito", help="pasta do projeto gabarito (padrão: gabaritos/capcut-9.5 ou o '0925' do PC)")
    p.add_argument("--ensaio", action="store_true", help="grava numa pasta de ensaio, fora do CapCut")
    p.add_argument("--inspecionar", nargs="?", const="", metavar="PASTA", help="só mostra o que o gabarito tem")
    a = p.parse_args(argv)
    try:
        if a.inspecionar is not None:
            pasta = Path(a.inspecionar) if a.inspecionar else (Path(a.gabarito) if a.gabarito else localizar_gabarito())
            print(json.dumps(inspecionar(pasta), ensure_ascii=False, indent=2))
            return 0
        if not a.projeto:
            p.error("informe --projeto (ou --inspecionar)")
        ctx = Contexto(config.pastas().logs / "rascunho" / carimbo(), ensaio=a.ensaio)
        r = tarefa({"projeto": a.projeto, "plano": a.plano, "nome": a.nome, "gabarito": a.gabarito}, ctx)
    except ErroValidacao as e:
        print(str(e), file=sys.stderr)
        for x in e.erros:
            print(f"  - {x}", file=sys.stderr)
        return 1
    except (capcut.ErroCapCut, midia.ErroMidia, ferramentas.FerramentaAusente, ferramentas.ErroComando) as e:
        print(str(e), file=sys.stderr)
        return 1
    print(f"Rascunho '{r['rascunho']}' gravado em {r['pasta']}")
    if r.get("relatorio"):
        print(f"Relatório: {r['relatorio']}")
    for x in r["manual"]:
        print(f"  manual: {x}")
    return 0


def _sintetico(pasta: Path, nome: str, t: dict) -> tuple[Path, Path]:
    """Vídeo testsrc2 1080×1920 com tom + uma faixa de música (arquivos novos, nunca sobrescreve)."""
    ffmpeg = ferramentas.exigir("ffmpeg")
    pasta.mkdir(parents=True, exist_ok=True)
    video, musica = pasta / f"{nome}.mp4", pasta / f"{nome}_musica.m4a"
    for arq in (video, musica):
        if arq.exists():
            raise ErroRascunho(f"Já existe {arq}; não sobrescrevo.")
    d = float(t["duracao_s"])
    ferramentas.rodar([ffmpeg, "-hide_banner", "-loglevel", "error", "-n",
                       "-f", "lavfi", "-i", f"testsrc2=s={t['largura']}x{t['altura']}:r={t['fps']}:d={d}",
                       "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={d}",
                       "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(video)], timeout=300)
    ferramentas.rodar([ffmpeg, "-hide_banner", "-loglevel", "error", "-n", "-f", "lavfi",
                       "-i", f"sine=frequency=220:sample_rate=48000:duration={d}", "-c:a", "aac", str(musica)], timeout=120)
    return video, musica


def plano_de_teste(video: Path, musica: Path, t: dict) -> dict:
    d = float(t["duracao_s"])
    meio = round(d / 2, 3)
    return {
        "projeto": t["pasta_trabalho"], "receita": "teste", "destino": "reels",
        "canvas": {"largura": int(t["largura"]), "altura": int(t["altura"]), "fps": int(t["fps"])}, "duracao_s": d - 1,
        "video": [
            {"arquivo": str(video), "tomada": "T01", "fonte_ini_s": 1.0, "fonte_fim_s": 1.0 + meio - 0.5, "ini_s": 0.0,
             "dur_s": meio - 0.5, "velocidade": 1.0, "escala": 1.0, "papel": "gancho", "volume_db": 0.0},
            {"arquivo": str(video), "tomada": "T01", "fonte_ini_s": meio + 0.5, "fonte_fim_s": d, "ini_s": meio - 0.5,
             "dur_s": d - meio - 0.5, "velocidade": 1.0, "escala": 1.0, "papel": "look", "volume_db": -6.0},
        ],
        "textos": [{"texto": "TESTE ROTINAS", "ini_s": 0.0, "dur_s": 2.0, "x": 540, "y": 520, "tamanho_px": 96,
                    "estilo": "gancho", "papel": "gancho"}],
        "legendas": [{"texto": "legenda de teste", "ini_s": 0.5, "dur_s": 2.0}],
        "audio": [{"arquivo": str(musica), "ini_s": 0.0, "dur_s": d - 1, "fonte_ini_s": 0.0, "volume_db": -18.0,
                   "papel": "musica"}],
        "transicoes": [], "efeitos": [], "avisos": [], "violacoes": [],
    }


def teste_copiar(ctx: Contexto, argv: list[str]) -> dict:
    """``testar.bat capcut-copiar "<projeto>"``: copia um projeto do CapCut como ele está agora (sem as mídias) para
    comparar — ex.: o "Teste Rotinas …" depois de o CapCut abrir e regravar, ou um projeto feito à mão para servir de
    gabarito (texto, legenda, música). Não muda nada nos projetos."""
    p = argparse.ArgumentParser(prog="testar capcut-copiar")
    p.add_argument("projeto", help='nome do projeto no CapCut, ex.: "Teste Rotinas 20260926-022653"')
    a = p.parse_args(argv)
    c = capcut.cfg()
    capcut.exigir_capcut_fechado()  # com o CapCut aberto, o rascunho pode estar no meio de uma gravação
    pasta = config.pastas().capcut_rascunhos / a.projeto
    if not (pasta / "draft_content.json").is_file() and not (pasta / "draft_info.json").is_file():
        existentes = sorted(x.name for x in config.pastas().capcut_rascunhos.iterdir() if x.is_dir())[-15:]
        raise FileNotFoundError(f"Projeto {a.projeto!r} não encontrado em {pasta.parent}. "
                                f"Projetos mais recentes (por nome): {', '.join(existentes)}")
    limite = int(float(c.get("max_mb_arquivo_auxiliar", 5)) * 1024 * 1024)
    midia_ext = {e.lower() for e in c.get("extensoes_midia") or []}
    copia = capcut.copiar_arvore(pasta, ctx.pasta_saida / "projeto" / pasta.name, limite, extensoes_fora=midia_ext)
    ctx.arquivo("inspecao.json").write_text(json.dumps(inspecionar(pasta), ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "projeto": a.projeto, "copiados": len(copia["copiados"]),
            "resumo": f"Copiei {len(copia['copiados'])} arquivo(s) do projeto {a.projeto!r} (sem as mídias)."}


def teste_real(ctx: Contexto, argv: list[str]) -> dict:
    """No PC: gera 'Teste Rotinas <carimbo>' com mídia sintética e copia rascunho + gabarito para comparação."""
    p = argparse.ArgumentParser(prog="testar capcut-rascunho")
    p.add_argument("--gabarito", help="pasta do gabarito (padrão: localizar_gabarito)")
    a = p.parse_args(argv)
    c = capcut.cfg()
    t = c["teste_real"]
    marca = datetime.now().strftime("%Y%m%d-%H%M%S")
    gabarito = Path(a.gabarito) if a.gabarito else localizar_gabarito()
    capcut.exigir_capcut_fechado()
    trabalho = pasta_trabalho(t["pasta_trabalho"])
    video, musica = _sintetico(trabalho, f"teste_{marca}", t)
    plano = plano_de_teste(video, musica, t)
    (trabalho / f"plano_{marca}.json").write_text(json.dumps(plano, ensure_ascii=False, indent=2), encoding="utf-8")
    r = gerar_completo(plano, config.pastas().capcut_rascunhos, gabarito, t["nome"].format(carimbo=marca),
                       pasta_relatorio=ctx.pasta_saida)
    limite = int(float(c.get("max_mb_arquivo_auxiliar", 5)) * 1024 * 1024)
    midia_ext = {e.lower() for e in c.get("extensoes_midia") or []}
    copia_r = capcut.copiar_arvore(r.pasta, ctx.pasta_saida / "rascunho_gerado" / r.pasta.name, limite, extensoes_fora=midia_ext)
    copia_g = capcut.copiar_arvore(gabarito, ctx.pasta_saida / "gabarito_usado" / gabarito.name, limite, extensoes_fora=midia_ext)
    ctx.arquivo("inspecao_gabarito.json").write_text(json.dumps(inspecionar(gabarito), ensure_ascii=False, indent=2),
                                                     encoding="utf-8")
    indice = config.pastas().capcut_rascunhos / c["arquivo_indice"]
    if indice.is_file():
        shutil.copy2(indice, ctx.arquivo(f"indice_depois/{indice.name}"))
    return {
        **r.como_dict(),
        "copias": {"rascunho_gerado": len(copia_r["copiados"]), "gabarito_usado": len(copia_g["copiados"])},
        "pedido_ao_usuario": (
            f"Abra o CapCut, procure o projeto \"{r.nome}\" e me diga: 1) abriu sem erro? 2) apareceu \"mídia perdida\" "
            "ou pedido para vincular mídia? 3) aparecem 2 trechos de vídeo, o texto TESTE ROTINAS em cima, a legenda "
            "embaixo e a música? Depois feche o CapCut sem salvar mudanças."
        ),
    }
