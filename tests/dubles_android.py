"""Dublês do BlueStacks para os testes de A5: relógio falso, adb falso (galeria/MediaStore),
device falso do uiautomator2 e uma tela roteirizada do Instagram (``TelaFalsa``)."""

from __future__ import annotations

import copy
import re
import subprocess
from datetime import datetime
from pathlib import Path

from rotinas.stories.android import Elemento


class Relogio:
    """Troca ``dormir``/``agora``: o tempo só anda quando alguém "dorme"."""

    def __init__(self, inicio: float = 1_758_800_000.0):
        self.t = inicio

    def dormir(self, s: float) -> None:
        self.t += float(s)

    def agora(self) -> float:
        return self.t


# ---------------------------------------------------------------- adb falso

def _like(padrao: str) -> re.Pattern:
    partes = []
    for c in padrao:
        partes.append(".*" if c == "%" else "." if c == "_" else re.escape(c))
    return re.compile("^" + "".join(partes) + "$")


class AdbFalso:
    """Faz o papel de ``ferramentas.rodar`` para o adb: arquivos no emulador + MediaStore."""

    def __init__(self, relogio: Relogio, metodos_ok=("broadcast",), perder=(), dispositivos=None,
                 conectaveis=("127.0.0.1:5555",), hora_android="20260925183000", date_added_fixo=None,
                 sem_datetaken=False, delete_funciona=True, datetaken_fixo=None):
        self.relogio = relogio
        self.metodos_ok = set(metodos_ok)
        self.perder = set(perder)  # nomes de arquivo que nunca entram na galeria
        self.dispositivos = dispositivos if dispositivos is not None else [("127.0.0.1:5555", "device")]
        self.conectaveis = set(conectaveis)
        self.hora_android = hora_android
        self.date_added_fixo = date_added_fixo
        self.sem_datetaken = sem_datetaken
        self.delete_funciona = delete_funciona
        self.datetaken_fixo = datetaken_fixo  # data da foto igual em todas (não segue a ordem da letra)
        self.arquivos: dict[str, dict] = {}
        self.media: dict[str, dict] = {}
        self.eventos: list[tuple] = []
        self._id = 100

    @staticmethod
    def canonico(caminho: str) -> str:
        return caminho.replace("/sdcard/", "/storage/emulated/0/", 1) if caminho.startswith("/sdcard/") else caminho

    def _varrer(self, caminho: str) -> None:
        nome = caminho.rsplit("/", 1)[-1]
        if caminho not in self.arquivos or nome in self.perder:
            return
        mtime = self.arquivos[caminho].get("mtime")
        modificado = int(datetime.strptime(mtime, "%Y%m%d%H%M.%S").timestamp()) if mtime else int(self.relogio.t)
        self._id += 1
        self.media[self.canonico(caminho)] = {
            "_id": self._id,
            "date_added": self.date_added_fixo or int(self.relogio.t),
            "date_modified": modificado,
            "datetaken": self.datetaken_fixo or modificado * 1000,
        }

    def _query(self, comando: str) -> str:
        if self.sem_datetaken and "datetaken" in comando:
            return "Error while accessing provider:media\njava.lang.IllegalArgumentException: no such column: datetaken"
        m = re.search(r"_data LIKE '([^']*)'", comando)
        regex = _like(m.group(1))
        colunas = re.search(r"--projection (\S+)", comando).group(1).split(":")
        linhas = []
        for caminho, dados in sorted(self.media.items()):
            if regex.match(caminho):
                valores = {"_data": caminho, **dados}
                linhas.append(", ".join(f"{c}={valores.get(c, 'NULL')}" for c in colunas))
        if not linhas:
            return "No result found.\n"
        return "".join(f"Row: {i} {l}\n" for i, l in enumerate(linhas))

    def _shell(self, comando: str) -> str:
        if comando.startswith("date "):
            return self.hora_android + "\n"
        if comando.startswith("touch -m -t "):
            _, _, _, mtime, caminho = comando.split(" ", 4)
            caminho = caminho.strip("'")
            if caminho in self.arquivos:
                self.arquivos[caminho]["mtime"] = mtime
            self.eventos.append(("touch", caminho.rsplit("/", 1)[-1], mtime))
            return ""
        if comando.startswith("am broadcast"):
            caminho = comando.split("file://", 1)[1].strip()
            self.eventos.append(("varredura", "broadcast", caminho.rsplit("/", 1)[-1]))
            if "broadcast" in self.metodos_ok:
                self._varrer(caminho)
            return "Broadcasting: Intent\nBroadcast completed: result=0\n"
        if comando.startswith("content call") and "scan_file" in comando:
            caminho = comando.split("--arg ", 1)[1].strip()
            self.eventos.append(("varredura", "scan_file", caminho.rsplit("/", 1)[-1]))
            if "scan_file" in self.metodos_ok:
                self._varrer(caminho)
            return "Result: Bundle[...]\n"
        if comando.startswith("content call") and "scan_volume" in comando:
            self.eventos.append(("varredura", "scan_volume", None))
            if "scan_volume" in self.metodos_ok:
                for caminho in list(self.arquivos):
                    if self.canonico(caminho) not in self.media:
                        self._varrer(caminho)
            return ""
        if comando.startswith("content query"):
            return self._query(comando)
        if comando.startswith("content delete"):
            self.eventos.append(("delete", re.search(r"LIKE '([^']*)'", comando).group(1)))
            if self.delete_funciona:
                regex = _like(re.search(r"LIKE '([^']*)'", comando).group(1))
                self.media = {k: v for k, v in self.media.items() if not regex.match(k)}
            return ""
        if comando.startswith("rm -rf "):
            alvo = comando[len("rm -rf "):].strip("'")
            self.eventos.append(("rm", alvo))
            self.arquivos = {k: v for k, v in self.arquivos.items() if not k.startswith(alvo + "/")}
            return ""
        if comando.startswith("mkdir -p "):
            self.eventos.append(("mkdir", comando[len("mkdir -p "):].strip("'")))
            return ""
        if comando.startswith("getprop ro.build.version.release"):
            return "11\n"
        if comando.startswith("getprop"):
            return "x\n"
        if comando.startswith("wm size"):
            return "Physical size: 1080x1920\n"
        if comando.startswith("dumpsys package"):
            return "  versionName=300.0.0.1\n  versionCode=123\n"
        return ""

    def __call__(self, cmd, timeout=None, verificar=True, entrada=None, binario=False, cwd=None):
        cmd = [str(c) for c in cmd]
        args = cmd[1:]
        if args[:1] == ["-s"]:
            args = args[2:]
        saida = ""
        if args == ["start-server"]:
            saida = ""
        elif args[0] == "connect":
            saida = f"connected to {args[1]}\n" if args[1] in self.conectaveis else f"cannot connect to {args[1]}\n"
        elif args[0] == "devices":
            saida = "List of devices attached\n" + "".join(f"{s}\t{e}\n" for s, e in self.dispositivos)
        elif args[0] == "push":
            self.arquivos[args[2]] = {"mtime": None, "local": args[1]}
            self.eventos.append(("push", args[2].rsplit("/", 1)[-1]))
            saida = "1 file pushed.\n"
        elif args[0] == "shell":
            saida = self._shell(args[1])
        return subprocess.CompletedProcess(cmd, 0, saida, "")


# ---------------------------------------------------------------- uiautomator2 falso

def elemento_u2(text="", desc="", classe="android.widget.TextView", rid="", limites=(0, 0, 100, 50),
                checked=False, checkable=False) -> dict:
    l, t, r, b = limites
    return {"text": text, "contentDescription": desc, "className": classe, "resourceName": rid,
            "bounds": {"left": l, "top": t, "right": r, "bottom": b}, "checked": checked, "checkable": checkable}


class _ObjFalso:
    def __init__(self, d: "U2Falso", sel: dict):
        self.d = d
        self.sel = dict(sel)

    def _bate(self, e: dict) -> bool:
        for k, v in self.sel.items():
            if k == "instance":
                continue
            valor = {"text": e["text"], "textContains": e["text"], "textMatches": e["text"],
                     "description": e["contentDescription"], "descriptionContains": e["contentDescription"],
                     "descriptionMatches": e["contentDescription"], "className": e["className"],
                     "resourceId": e["resourceName"], "checkable": e["checkable"]}.get(k)
            if k.endswith("Contains"):
                if v not in (valor or ""):
                    return False
            elif k.endswith("Matches"):
                if not re.fullmatch(v, valor or ""):
                    return False
            elif valor != v:
                return False
        return True

    def _todos(self) -> list[dict]:
        achados = [e for e in self.d.elementos if self._bate(e)]
        if "instance" in self.sel:
            i = self.sel["instance"]
            return achados[i:i + 1]
        return achados

    @property
    def exists(self) -> bool:
        return bool(self._todos())

    @property
    def info(self) -> dict:
        return copy.deepcopy(self._todos()[0])

    def info_list(self) -> list[dict]:
        return [copy.deepcopy(e) for e in self._todos()]

    def set_text(self, texto):
        self._todos()[0]["text"] = texto or ""
        self.d.digitados.append((self.sel, texto))


class U2Falso:
    def __init__(self, elementos: list[dict]):
        self.elementos = elementos
        self.cliques: list[tuple[int, int]] = []
        self.teclas: list[str] = []
        self.digitados: list = []
        self.apps: list = []

    def __call__(self, **sel):
        return _ObjFalso(self, sel)

    def click(self, x, y):
        self.cliques.append((x, y))

    def press(self, tecla):
        self.teclas.append(tecla)

    def window_size(self):
        return 1000, 2000

    def dump_hierarchy(self):
        return "<hierarchy />"

    def screenshot(self, caminho):
        Path(caminho).write_bytes(b"\x89PNG falso")

    def app_start(self, pacote, stop=False):
        self.apps.append((pacote, stop))


# ---------------------------------------------------------------- Instagram roteirizado

class TelaFalsa:
    """Tela do Instagram com a mesma interface da ``android.Tela``, guiada por estado.

    Registra todos os toques (``toques``), o que foi digitado (``digitados``) e cada publicação
    (``publicacoes``: álbum + edições de cada mídia + estado do Facebook). Botões de ajuste:
    ``quebrar`` ({"abertura": n, "chave": k} some com a chave na n-ésima abertura do story),
    ``ignorar_miniatura`` (índices de toque que não selecionam), ``url_https`` (quantas vezes o campo
    da URL mostra https:// na frente), ``facebook_ligado``, ``modo_publicacao`` ("compartilhar" | "direto").
    """

    def __init__(self, eventos: list | None = None):
        self.estado = "fora"
        self.eventos = eventos if eventos is not None else []
        self.toques: list[str] = []
        self.digitados: list[tuple[str, str]] = []
        self.prints: list[Path] = []
        self.xmls = 0
        self.apps: list[tuple[str, bool]] = []
        self.publicacoes: list[dict] = []
        self.albuns: dict[str, int] = {}
        self.recentes = 12
        self.aberturas = 0
        self.quebrar: dict | None = None
        self.ignorar_miniatura: set[int] = set()
        self.url_https = 0
        self.facebook_ligado = False
        self.facebook_rotulo = False
        self.modo_publicacao = "compartilhar"
        self.aviso_facebook = False  # depois de "Seu story": "Compartilhar no Facebook?" [Compartilhar] [Agora não]
        self.volta_para_camera = False  # depois de publicar, o Instagram volta à câmera (não ao feed)
        self.enter_quebra_linha = False  # o Enter vira quebra de linha no texto da figurinha
        self.plano_b_chaves: set[str] = set()  # chaves que, sem seletor na tela, caem na coordenada (plano B)
        self.story_abre_rascunho = False  # "Story" reabre um rascunho no editor (em vez da câmera)
        self.criar_abre_camera = False  # Instagram 448: "Adicionar ao story" já abre a câmera de story
        self.criar_abre_galeria = False  # Instagram 448 no PC: "Adicionar ao story" já abre a galeria
        self.album_via_todos = False  # Instagram 448: as pastas ficam em "Todos os álbuns" dentro do menu
        self.numeros_na_selecao = True  # False: sem número na miniatura; só a descrição muda
        self.selecao_ja_ativa = False  # a galeria abre com "Selecionar várias" já ligado (botão "Cancelar")
        self.carregando: set[int] = set()  # miniaturas ainda carregando: o 1º toque nelas não pega (vídeo recém-enviado)
        self.pre_selecionados = 0  # mídias já selecionadas (fora da tela) quando liga o "Selecionar"
        self.miniaturas_editor_extra = 0  # elementos a mais na faixa de miniaturas do editor (ex.: "+")
        self.caixa_seu_story = False  # na folha de compartilhar, a caixa marcada de "Seu story" logo acima
        self.seu_story_marcado = True
        self.resultados_musica = [
            ("Áudio original", "neetunomusic"),
            ("Áudio original", "petermarkoski"),
            ("I Know What You Want", "Madison Beer, Calley"),
            ("Clocks", "leveviolao"),
        ]
        self._limpar_story()

    # -- estado interno
    def _limpar_story(self):
        self.album = "Recentes"
        self.modo_selecao = False
        self.selecao: list[int] = []
        self.midias: list[dict] = []
        self.atual = 0
        self.busca = None
        self.musica_escolhida = None
        self.campo_url = ""
        self.campo_texto = None
        self.personalizado = False
        self.teclado = False
        self.anterior = "editor"
        self.todos_aberto = False

    def _n_grade(self) -> int:
        return self.albuns.get(self.album, 0) if self.album != "Recentes" else self.recentes

    def _visiveis(self) -> set[str]:
        e = self.estado
        v: set[str] = set()
        if e == "feed":
            v = {"feed", "criar", "seu_story"}  # o próprio story no topo do feed também diz "Seu story"
        elif e == "criacao":
            v = {"abrir_story"}
        elif e == "camera":
            v = {"abrir_galeria"}
        elif e == "galeria":
            v = {"album_menu", "selecionar_varios", "miniaturas_galeria"}
            if self.modo_selecao:
                v.add("selecao_ativa")
            if self.selecao:
                v |= {"avancar"} | ({"badge_selecao"} if self.numeros_na_selecao else set())
        elif e == "album_menu":
            v = {"album_todos"} if self.album_via_todos and not self.todos_aberto else {"album_item"}
        elif e == "editor":
            v = {"editor", "figurinhas", "musica", "seu_story", "miniaturas_editor"}
            if self.midias and self.midias[self.atual].get("figurinha"):
                v.add("figurinha_na_tela")
        elif e == "figurinhas":
            v = {"figurinha_link", "figurinha_musica", "buscar_figurinha"}
        elif e == "musica":
            v = {"buscar_musica"} | ({"escolher_musica"} if self.busca else set())
            if self.musica_escolhida:
                v.add("concluir_musica")
        elif e == "link":
            v = {"campo_url", "personalizar_texto", "confirmar_teclado", "concluir_figurinha"}
            if self.personalizado:
                v.add("campo_texto_figurinha")
        elif e == "compartilhar":
            v = {"compartilhar_facebook_toggle", "concluir_publicacao", "interruptores"}
        elif e == "aviso_fb":
            v = {"dispensar_aviso", "concluir_publicacao"}
        elif e == "dialogo":
            v = {"descartar"}
        if self.quebrar and self.aberturas == self.quebrar["abertura"]:
            v.discard(self.quebrar["chave"])
        return v

    def _publicar(self):
        pub = {"album": self.album, "midias": copy.deepcopy(self.midias), "facebook": self.facebook_ligado,
               "seu_story": self.seu_story_marcado}
        self.publicacoes.append(pub)
        self.eventos.append(("publicou", self.album))
        self._limpar_story()
        self.estado = "camera" if self.volta_para_camera else "feed"

    def _acao(self, chave: str, **valores):
        def tocar():
            self.toques.append(chave)
            e = self.estado
            if chave == "criar":
                self.estado = "criacao"
                if self.criar_abre_galeria:
                    self.aberturas += 1
                    self._limpar_story()
                    self.estado = "galeria"
                    self.modo_selecao = self.selecao_ja_ativa
                elif self.criar_abre_camera:
                    self.aberturas += 1
                    self._limpar_story()
                    self.estado = "camera"
            elif chave == "abrir_story":
                self.aberturas += 1
                self._limpar_story()
                self.estado = "camera"
                if self.story_abre_rascunho:
                    self.midias = [{"indice": "rascunho", "musica": None, "figurinha": None}]
                    self.estado = "editor"
            elif chave == "seu_story" and e == "feed":
                self.estado = "visualizador_story"  # abre o próprio story: nada é publicado
            elif chave == "abrir_galeria":
                self.estado = "galeria"
            elif chave == "album_menu":
                self.estado = "album_menu"
                self.todos_aberto = False
            elif chave == "album_todos":
                self.todos_aberto = True
            elif chave == "album_item":
                self.album = valores["album"]
                self.estado = "galeria"
            elif chave == "selecionar_varios":
                self.modo_selecao = not self.modo_selecao  # o mesmo botão liga e desliga ("Cancelar")
                self.selecao = [-1 - k for k in range(self.pre_selecionados)] if self.modo_selecao else []
            elif chave == "avancar":
                self.midias = [{"indice": i, "musica": None, "figurinha": None} for i in self.selecao]
                self.atual = 0
                self.estado = "editor"
            elif chave in ("musica", "figurinha_musica"):
                self.busca, self.musica_escolhida = None, None
                self.estado = "musica"
            elif chave == "figurinhas":
                self.estado = "figurinhas"
            elif chave == "concluir_musica":
                self.midias[self.atual]["musica"] = self.musica_escolhida
                self.estado = "editor"
            elif chave == "figurinha_link":
                self.campo_url, self.campo_texto, self.personalizado, self.teclado = "", None, False, False
                self.estado = "link"
            elif chave == "personalizar_texto":
                self.personalizado = True
            elif chave == "confirmar_teclado":
                self.teclado = True
                if self.enter_quebra_linha and self.campo_texto:
                    self.campo_texto += "\n"
            elif chave == "concluir_figurinha":
                self.midias[self.atual]["figurinha"] = {"url": self.campo_url, "texto": self.campo_texto,
                                                        "teclado_confirmado": self.teclado}
                self.estado = "editor"
            elif chave == "seu_story":
                if self.aviso_facebook:
                    self.estado = "aviso_fb"
                elif self.modo_publicacao == "direto":
                    self._publicar()
                else:
                    self.estado = "compartilhar"
            elif chave == "dispensar_aviso" and e == "aviso_fb":
                self.aviso_facebook = False
                if self.modo_publicacao == "direto":
                    self._publicar()
                else:
                    self.estado = "compartilhar"
            elif chave in ("compartilhar_facebook_toggle", "interruptores"):
                self.facebook_ligado = not self.facebook_ligado
            elif chave == "concluir_publicacao":
                if e == "aviso_fb":  # "Compartilhar" do aviso: liga o Facebook e publica lá também
                    self.facebook_ligado = True
                self._publicar()
            elif chave == "descartar":
                self._limpar_story()
                self.estado = "camera"
            else:
                raise AssertionError(f"toque sem roteiro: {chave} no estado {e}")
        return tocar

    def _plano_b(self, chave: str) -> Elemento:
        def tocar():
            self.toques.append(f"coordenada:{chave}")
            if self.estado == "editor":  # no editor, o canto de baixo à esquerda é o "Seu story"
                self._acao("seu_story")()
        return Elemento(texto=f"coordenada {chave}", plano_b=True, acao=tocar)

    def _elemento(self, chave: str, **valores) -> Elemento:
        if chave == "compartilhar_facebook_toggle" and self.facebook_rotulo:
            # só o texto (não é o interruptor): o fluxo tem que achar o interruptor na mesma linha
            return Elemento(texto="Compartilhar também no Facebook", marcado=False, marcavel=False,
                            limites=(100, 1500, 800, 1560), acao=lambda: self.toques.append("rotulo_facebook"))
        if chave in ("compartilhar_facebook_toggle", "interruptores"):
            return Elemento(texto="Compartilhar também no Facebook", marcado=self.facebook_ligado, marcavel=True,
                            limites=(900, 1500, 1000, 1560), acao=self._acao(chave))
        return Elemento(texto=chave, limites=(0, 0, 100, 50), acao=self._acao(chave, **valores))

    # -- interface da Tela
    def achar(self, chave, espera_s=None, plano_b=True, **valores):
        if chave not in self._visiveis():
            return self._plano_b(chave) if plano_b and chave in self.plano_b_chaves else None
        if chave == "album_item" and valores.get("album") not in self.albuns:
            return None
        return self._elemento(chave, **valores)

    def existe(self, chave, **valores):
        return self.achar(chave, 0, False, **valores) is not None

    def tocar(self, chave, espera_s=None, **valores):
        el = self.achar(chave, espera_s, **valores)
        if el is None:
            raise AssertionError(f"'{chave}' não está na tela ({self.estado})")
        el.tocar()
        return el

    def digitar(self, chave, texto, espera_s=None, **valores):
        if chave not in self._visiveis():
            raise AssertionError(f"campo '{chave}' não está na tela ({self.estado})")
        self.digitados.append((chave, texto))
        if chave == "buscar_musica":
            self.busca = texto or None
        elif chave == "campo_url":
            if texto and self.url_https > 0:
                self.url_https -= 1
                texto = "https://" + texto
            self.campo_url = texto
        elif chave == "campo_texto_figurinha":
            self.campo_texto = texto

    def ler_texto(self, chave, espera_s=0, **valores):
        if chave not in self._visiveis():
            return None
        return {"campo_url": self.campo_url, "campo_texto_figurinha": self.campo_texto}.get(chave)

    def grade(self, chave, filtro=None, **valores):
        if chave not in self._visiveis():
            return []
        els: list[Elemento] = []
        if chave == "miniaturas_galeria":
            for i in range(self._n_grade()):
                linha, coluna = divmod(i, 4)
                desc = ((f"Número da mídia selecionada {self.selecao.index(i) + 1}" if i in self.selecao else "Não selecionado")
                        + " Miniatura de foto com criação em 24 de setembro")
                els.append(Elemento(texto="", descricao=desc,
                                    limites=(coluna * 250, 400 + linha * 250, coluna * 250 + 240, 640 + linha * 250),
                                    acao=self._tocar_miniatura(i)))
        elif chave == "badge_selecao":
            for ordem, i in enumerate(self.selecao, 1):
                if i < 0:
                    continue  # selecionada fora da tela: o número dela não aparece
                linha, coluna = divmod(i, 4)
                els.append(Elemento(texto=str(ordem), limites=(coluna * 250, 400 + linha * 250, coluna * 250 + 40, 440 + linha * 250)))
        elif chave == "miniaturas_editor":
            for k in range(self.miniaturas_editor_extra):  # à esquerda das miniaturas; tocar não troca a mídia
                els.append(Elemento(limites=(k * 50, 1800, k * 50 + 40, 1900),
                                    acao=lambda: self.toques.append("editor_extra")))
            for i in range(len(self.midias)):
                els.append(Elemento(limites=(100 + i * 120, 1800, 200 + i * 120, 1900), acao=self._ir_midia(i)))
        elif chave == "escolher_musica":
            for i, (titulo, autor) in enumerate(self.resultados_musica):
                topo = 300 + i * 160
                els.append(Elemento(texto=titulo, limites=(150, topo, 900, topo + 50), acao=self._escolher(titulo, autor)))
                els.append(Elemento(texto=autor, limites=(150, topo + 60, 900, topo + 100), acao=self._escolher(titulo, autor)))
        elif chave == "interruptores":
            if self.caixa_seu_story:
                els.append(Elemento(texto="", marcado=self.seu_story_marcado, marcavel=True,
                                    limites=(900, 1400, 1000, 1460), acao=self._alternar_seu_story))
            els.append(self._elemento("interruptores"))
        els = sorted(els, key=lambda e: (e.limites[1], e.limites[0]))
        return [e for e in els if filtro is None or filtro(e)]

    def _tocar_miniatura(self, i):
        def tocar():
            self.toques.append(f"miniatura_{i}")
            if i in self.carregando:
                self.carregando.discard(i)
                return
            if self.modo_selecao and i not in self.ignorar_miniatura:
                if i in self.selecao:
                    self.selecao.remove(i)  # tocar de novo desmarca, como no Instagram
                else:
                    self.selecao.append(i)
        return tocar

    def _alternar_seu_story(self):
        self.toques.append("caixa_seu_story")
        self.seu_story_marcado = not self.seu_story_marcado

    def _ir_midia(self, i):
        def tocar():
            self.toques.append(f"editor_midia_{i}")
            self.atual = i
        return tocar

    def _escolher(self, titulo, autor):
        def tocar():
            self.toques.append(f"musica:{titulo}|{autor}")
            self.musica_escolhida = f"{titulo} | {autor}"
        return tocar

    def xml(self):
        self.xmls += 1
        nos = "".join(f'<node resource-id="falso:{k}" />' for k in sorted(self._visiveis()))
        return f"<hierarchy estado=\"{self.estado}\">{nos}</hierarchy>"

    def print(self, caminho):
        Path(caminho).write_bytes(b"\x89PNG falso")
        self.prints.append(Path(caminho))

    def voltar(self):
        self.toques.append("voltar")
        self.estado = {
            "feed": "fora", "criacao": "feed", "camera": "feed", "galeria": "camera", "album_menu": "galeria",
            "editor": "dialogo", "dialogo": "editor", "musica": "editor", "figurinhas": "editor", "link": "editor",
            "compartilhar": "editor", "aviso_fb": "editor", "visualizador_story": "feed",
        }.get(self.estado, self.estado)

    def tamanho(self):
        return 1080, 1920

    def abrir_app(self, pacote, parar=False):
        self.apps.append((pacote, parar))
        if parar or self.estado == "fora":
            self._limpar_story()
            self.estado = "feed"
