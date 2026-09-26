"""A5 — posta os stories do plano pelo BlueStacks (ADB + uiautomator2), letra por letra.

Por letra: mídias → galeria do Android (``android.enviar_letra``) → Instagram → Criar → Story → galeria →
álbum ``<data>_<letra>`` → Selecionar → toca as N primeiras na ordem → confere a seleção → Avançar →
em cada mídia: música (vídeo sem som) e figurinha de link (só a última, URL sem ``https://``) →
ensaio: print de cada mídia e sai descartando | real: Seu story (Facebook desligado) → Concluir → feed
→ ``postados.registrar``.

Segurança: a letra inteira sai num único "Compartilhar"; ``seu_story``/``concluir_publicacao`` só podem ser
tocados dentro da publicação real; qualquer falha tira print + XML, descarta a edição e PARA a execução
(``ErroPostagem`` com ``resultado_parcial``). No real: sem o álbum da letra não publica pela grade "Recentes";
testa a gravação do ``postados.csv`` antes de começar e, se o registro falhar depois de publicar, grava o pendente
(``registros/postados_pendentes``) e para antes da próxima letra. Emulador de verdade: um por vez
(``fila/bluestacks.lock``). Seletores e tempos: ``config/bluestacks.json``.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from contextlib import contextmanager
from pathlib import Path

from .. import config, ferramentas, midia, registro
from ..contexto import Contexto, carimbo
from . import android, postados

log = registro.obter("stories.bluestacks")

dormir = time.sleep  # trocados nos testes
agora = time.monotonic
sortear = random.choice

CHAVES_PUBLICAR = frozenset({"seu_story", "concluir_publicacao"})
# sinais de que o toque em "criar" saiu do feed ("abrir_story" primeiro: aba "Story" de versões com "Criar")
CHAVES_STORY_ABERTO = ("abrir_story", "selecionar_varios", "album_menu", "abrir_galeria")
RE_LETRA = re.compile(r"^[A-Z]{1,2}$")


class ErroPostagem(RuntimeError):
    """A execução parou. ``resultado_parcial`` diz o que já foi publicado e o que não foi."""

    def __init__(self, mensagem: str, resultado_parcial: dict):
        super().__init__(mensagem)
        self.resultado_parcial = resultado_parcial


class ErroPasso(RuntimeError):
    """Um passo no Instagram não deu certo (a letra para ali)."""


class ErroRegistro(RuntimeError):
    """A letra FOI publicada, mas não entrou no ``postados.csv``: para antes da próxima letra."""


MSG_EM_USO = ("O BlueStacks está em uso por outro pedido ou teste (fila\\bluestacks.lock); nada foi feito. "
              "Esperar o outro terminar e pedir de novo.")


def _cfg() -> dict:
    return config.carregar("bluestacks")


# ---------------------------------------------------------------- plano

def validar_plano(plano: dict, cfg: dict | None = None) -> list[str]:
    """Problemas que impedem começar (lista vazia = pode seguir). Confere arquivos, formato, figurinha e música."""
    cfg = cfg or _cfg()
    problemas: list[str] = []
    if not android.RE_DATA.match(str(plano.get("data") or "")):
        problemas.append(f"data inválida no plano: {plano.get('data')!r}")
    letras = plano.get("letras")
    if not isinstance(letras, list) or not letras:
        return problemas + ["o plano não tem nenhuma letra para postar"]
    maximo = int(config.carregar("stories").get("max_midias_por_letra", 10))
    aceitas = {e.lower() for e in cfg.get("extensoes_galeria") or []}
    vistas: set[str] = set()
    for L in letras:
        letra = str(L.get("letra") or "")
        if not RE_LETRA.match(letra) or letra in vistas:
            problemas.append(f"letra inválida ou repetida: {letra!r}")
            continue
        vistas.add(letra)
        midias = L.get("midias") or []
        if not midias:
            problemas.append(f"letra {letra} sem mídias")
        if len(midias) > maximo:
            problemas.append(f"letra {letra} tem {len(midias)} mídias; o máximo é {maximo}")
        for i, m in enumerate(midias, 1):
            nome = m.get("nome") or f"{letra} #{i}"
            caminho = Path(str(m.get("caminho") or ""))
            if not m.get("caminho") or not caminho.is_file():
                problemas.append(f"{nome}: arquivo não encontrado ({caminho})")
                continue
            if aceitas and caminho.suffix.lower() not in aceitas:
                problemas.append(f"{nome}: formato {caminho.suffix} não aparece na galeria do emulador")
            if m.get("precisa_musica") and not (m.get("musica") or {}).get("busca"):
                problemas.append(f"{nome}: vídeo sem som, mas o plano não diz qual música pôr")
            fig = m.get("figurinha")
            if fig:
                url = str(fig.get("url") or "")
                if i != len(midias):
                    problemas.append(f"{nome}: figurinha de link só pode ir na última mídia da letra")
                if not url or url.lower().startswith("http") or "://" in url:
                    problemas.append(f"{nome}: a URL da figurinha tem que ser digitada sem https:// ({url!r})")
            esperado = str(m.get("hash") or "").lower()
            if esperado and midia.hash_arquivo(caminho) != esperado:
                problemas.append(f"{nome}: o arquivo mudou depois que o plano foi montado (hash diferente)")
    return problemas


def novo_resultado(plano: dict, ensaio: bool) -> dict:
    return {
        "ensaio": bool(ensaio),
        "id": plano.get("id"),
        "data": plano.get("data"),
        "letras": [
            {"letra": L.get("letra"), "estado": "nao_iniciada", "midias": [m.get("nome") for m in L.get("midias") or []],
             "prints": [], "erro": None}
            for L in plano.get("letras") or []
        ],
        "publicadas": [],
        "parou_em": None,
        "avisos": [],
    }


# ---------------------------------------------------------------- fluxo

class Postador:
    """Motor de passos sobre uma ``Tela`` (real ou dublê)."""

    def __init__(self, tela, ctx: Contexto, *, ensaio: bool = True, diagnostico: bool = False, enviar=None,
                 cfg: dict | None = None, pedido: str | None = None):
        self.tela = tela
        self.ctx = ctx
        self.ensaio = ensaio
        self.diagnostico = diagnostico
        self.enviar = enviar
        self.cfg = cfg or _cfg()
        self.pedido = pedido
        self.pacote = self.cfg.get("pacote_instagram", "com.instagram.android")
        self.n_passo = 0
        self.letra = "-"
        self.passo: str | None = None
        self.publicando = False
        self.tocou_publicar = False
        self.primeira_abertura = True

    # -- utilidades
    def _t(self, chave: str, padrao: float) -> float:
        return float(self.cfg.get(chave, padrao))

    def _pausa(self) -> None:
        dormir(self._t("pausa_toque_s", 0.8))

    @contextmanager
    def _passo(self, nome: str):
        self.passo = nome
        self.n_passo += 1
        log.info("Letra %s: %s", self.letra, nome.replace("_", " "))
        self._conferir_fora_do_direct()
        if self.diagnostico:
            self._salvar_tela(f"passo_{self.n_passo:03d}_{self.letra}_{nome}")
        yield

    def _na_tela_privada(self) -> bool:
        try:
            return bool(self.tela.existe("tela_privada"))
        except android.ErroSeletor:
            raise  # seletor faltando na config: erro de configuração, com a mensagem dele
        except Exception:  # noqa: BLE001 - tela não respondeu: sem saber, trata como privada (não salva)
            return True

    def _conferir_fora_do_direct(self) -> None:
        """Conversa do Direct na tela (ex.: toque que caiu numa notificação de mensagem): para tudo, sem digitar."""
        if self._na_tela_privada():
            raise ErroPasso("a tela saiu do story e foi para uma conversa do Direct (notificação de mensagem tocada?); "
                            "parei sem digitar nada")

    def _salvar_tela(self, prefixo: str) -> list[str]:
        if self._na_tela_privada():
            log.warning("Não salvei %s: a tela é do Direct (conversa de cliente)", prefixo)
            return []
        nomes = []
        try:
            self.ctx.arquivo(prefixo + ".xml").write_text(self.tela.xml() or "", encoding="utf-8")
            nomes.append(prefixo + ".xml")
        except Exception as e:  # noqa: BLE001 - registro não pode esconder o erro real
            log.warning("Não consegui salvar o XML da tela (%s): %s", prefixo, e)
        if self._print(prefixo + ".png"):
            nomes.append(prefixo + ".png")
        return nomes

    def _print(self, nome: str, r: dict | None = None) -> bool:
        if self._na_tela_privada():
            log.warning("Não salvei o print %s: a tela é do Direct (conversa de cliente)", nome)
            return False
        try:
            self.tela.print(self.ctx.arquivo(nome))
        except Exception as e:  # noqa: BLE001
            log.warning("Não consegui salvar o print %s: %s", nome, e)
            return False
        if r is not None:
            r["prints"].append(nome)
        return True

    def _dispensar_avisos(self) -> None:
        for _ in range(3):
            el = self.tela.achar("dispensar_aviso", 0, plano_b=False)
            if el is None:
                return
            log.info("Fechei um aviso do Instagram (%s)", el.texto or el.descricao or "sem texto")
            el.tocar()
            self._pausa()

    def _achar(self, chave: str, espera: float | None = None, **valores):
        el = self.tela.achar(chave, self._t("espera_curta_s", 2), plano_b=False, **valores)
        if el is None:
            self._dispensar_avisos()
            el = self.tela.achar(chave, self._t("espera_padrao_s", 10) if espera is None else espera, **valores)
        return el

    def _tocar(self, chave: str, espera: float | None = None, **valores):
        if chave in CHAVES_PUBLICAR and not self.publicando:
            raise ErroPasso(f"bloqueado: '{chave}' publica o story e só pode ser tocado na publicação real")
        el = self._achar(chave, espera, **valores)
        if el is None:
            raise ErroPasso(f"não achei '{chave}' na tela")
        if getattr(el, "plano_b", False) and any(self.tela.existe(k) for k in CHAVES_PUBLICAR):
            # coordenada às cegas numa tela com botão de publicar (ex.: editor): pode cair em "Seu story"
            raise ErroPasso(f"'{chave}' só foi achado pela coordenada (plano B) e há um botão de publicar na tela; "
                            "não toquei")
        if chave in CHAVES_PUBLICAR:
            self.tocou_publicar = True  # antes do toque: se o toque der erro no meio, a letra fica "incerta"
        el.tocar()
        self._pausa()
        return el

    # -- navegação
    def _esperar_uma(self, chaves: tuple[str, ...], espera: float) -> str | None:
        """Primeira das ``chaves`` que aparecer (só seletor real, nunca coordenada) em até ``espera`` segundos."""
        limite = agora() + espera
        while True:
            for chave in chaves:
                if self.tela.existe(chave):
                    return chave
            if agora() >= limite:
                return None
            dormir(self._t("intervalo_busca_s", 0.4))

    def _entrar_no_story(self) -> None:
        """Feed → galeria/câmera de story. No Instagram 448 o "Adicionar ao story" do "Seu story" já abre a galeria;
        em versões com a aba "Criar", ainda é preciso escolher "Story" (conferido primeiro, para não cair no modo
        publicação). Se o toque não abriu nada (feed ainda carregando, como no ensaio de 25/09 18:51), toca de novo."""
        tentativas = max(1, int(self.cfg.get("tentativas_criar", 3)))
        toques = 0
        for tentativa in range(1, tentativas + 1):
            with self._passo("criar"):
                self._tocar("criar")
                toques += 1
            aberta = self._esperar_uma(CHAVES_STORY_ABERTO, self._t("espera_abrir_story_s", 8))
            if aberta == "abrir_story":
                with self._passo("abrir_story"):
                    self._tocar("abrir_story")
                return
            if aberta is not None:
                log.info("Letra %s: 'Adicionar ao story' abriu direto a galeria/câmera (sem escolher 'Story')",
                         self.letra)
                return
            if tentativa < tentativas and self.tela.existe("criar"):
                log.warning("Letra %s: o toque em 'Adicionar ao story' não abriu a galeria (o feed ainda estava "
                            "carregando?); tocando de novo (%d de %d)", self.letra, tentativa + 1, tentativas)
                continue
            break
        raise ErroPasso(f"toquei {toques} vez(es) em 'Adicionar ao story' e a galeria/câmera do story não abriu")

    def _ir_para_feed(self, espera_inicial: float | None = None) -> None:
        for tentativa in range(int(self.cfg.get("max_voltar_saida", 8))):
            if tentativa == 0:
                espera = self._t("espera_padrao_s", 10) if espera_inicial is None else espera_inicial
            else:
                espera = self._t("espera_curta_s", 2)
            if self.tela.achar("feed", espera, plano_b=False) is not None:
                return
            descartar = self.tela.achar("descartar", 0, plano_b=False)
            if descartar is not None:
                descartar.tocar()
                self._pausa()
                continue
            self._dispensar_avisos()
            self.tela.voltar()
            self._pausa()
        raise ErroPasso("não cheguei ao feed do Instagram")

    def _abrir_instagram(self) -> None:
        self.tela.abrir_app(self.pacote, parar=self.primeira_abertura)
        self.primeira_abertura = False
        self._ir_para_feed(self._t("espera_abrir_app_s", 30))  # Instagram demora a abrir: não apertar voltar antes
        self._conferir_em_pe()

    def _conferir_em_pe(self) -> None:
        """Ensaio de 26/09 00:33: o Instagram abriu deitado (1600×900, layout de tablet) e "Adicionar ao story" levou a
        uma tela preta. Os toques e prints contam com a tela em pé: espera girar e, se não girar, para."""
        em_pe = getattr(self.tela, "em_pe", None)
        if em_pe is None:
            return
        limite = agora() + self._t("espera_em_pe_s", 10)
        while not em_pe():
            if agora() >= limite:
                w, h = self.tela.tamanho()
                raise ErroPasso(f"o Instagram abriu deitado (tela na horizontal, {w}×{h}); deixe o BlueStacks na "
                                "vertical e rode de novo")
            dormir(self._t("intervalo_busca_s", 0.4))

    def _abrir_galeria(self) -> None:
        if self.tela.achar("selecionar_varios", self._t("espera_curta_s", 2), plano_b=False) is None:
            self._tocar("abrir_galeria")
        if self._achar("selecionar_varios") is None:
            raise ErroPasso("a galeria do story não abriu")

    def _sair_com_seguranca(self) -> bool:
        """Volta ao feed descartando a edição. Nunca toca em nada que publique."""
        self.publicando = False
        for _ in range(int(self.cfg.get("max_voltar_saida", 8))):
            descartar = self.tela.achar("descartar", 0, plano_b=False)
            if descartar is not None:
                descartar.tocar()
                self._pausa()
                continue
            if self.tela.existe("feed"):
                return True
            self.tela.voltar()
            self._pausa()
        return self.tela.existe("feed")

    # -- galeria
    def _escolher_album(self, album: str, r: dict, res: dict) -> None:
        menu = self.tela.achar("album_menu", self._t("espera_curta_s", 2), plano_b=False)
        if menu is None:
            self._sem_album(album, r, res, "não achei o menu de álbuns")
            return
        menu.tocar()
        self._pausa()
        item = self.tela.achar("album_item", self._t("espera_curta_s", 2), plano_b=False, album=album)
        if item is None:
            # Instagram 448: o menu mostra Recentes/Fotos/Vídeos/Todos os álbuns; as pastas ficam em "Todos os álbuns"
            todos = self.tela.achar("album_todos", self._t("espera_curta_s", 2), plano_b=False)
            if todos is not None:
                todos.tocar()
                self._pausa()
                item = self.tela.achar("album_item", self._t("espera_lista_albuns_s", 4), plano_b=False, album=album)
        if item is None:
            item = self._rolar_ate("album_item", album=album)
        if item is None:
            if self.diagnostico:
                self._salvar_tela(f"album_{self.letra}_nao_achado")
            self.tela.voltar()  # fecha a lista de álbuns (no real, antes de parar)
            self._pausa()
            self._sem_album(album, r, res, f"o álbum {album} não apareceu na lista")
            if self.tela.achar("selecionar_varios", self._t("espera_curta_s", 2), plano_b=False) is None:
                raise ErroPasso(f"o álbum {album} não apareceu e a galeria fechou")
            return
        item.tocar()
        self._pausa()
        r["album"] = album

    def _rolar_ate(self, chave: str, **valores):
        """Rola a lista de álbuns (ex.: "Todos os álbuns" com muitas pastas) até ``chave`` aparecer. O arrasto é dentro
        dos itens da lista (``itens_lista_album``); sem itens na tela, não arrasta (fora do menu, fecharia o menu)."""
        for k in range(1, int(self.cfg.get("max_rolagens_album", 4)) + 1):
            itens = self.tela.grade("itens_lista_album")
            if len(itens) < 2:
                return None
            limites = (min(e.limites[0] for e in itens), min(e.limites[1] for e in itens),
                       max(e.limites[2] for e in itens), max(e.limites[3] for e in itens))
            self.tela.rolar(limites)
            self._pausa()
            el = self.tela.achar(chave, self._t("espera_curta_s", 2), plano_b=False, **valores)
            if el is not None:
                log.info("Letra %s: '%s' apareceu depois de rolar a lista %d vez(es)", self.letra, chave, k)
                return el
        return None

    def _sem_album(self, album: str, r: dict, res: dict, motivo: str) -> None:
        """Sem o álbum da letra, a grade é "Recentes" (tem as outras letras e o resto do emulador).
        Real: PARA (a conferência da seleção só conta quantas, não quais). Ensaio: segue por "Recentes" e avisa."""
        if not self.ensaio:
            raise ErroPasso(f"{motivo}; não publico pela grade 'Recentes' (pode pegar mídia de outra letra). "
                            "Ajustar 'album_menu'/'album_item' em config/bluestacks.json pelo XML do diagnóstico")
        self._recentes_seguro(album, r)
        r["recuo_recentes"] = True
        res["avisos"].append(f"Letra {self.letra}: {motivo}; no ENSAIO usei 'Recentes', mas a postagem real PARA "
                             "aqui (ajustar 'album_menu'/'album_item' em config/bluestacks.json).")
        log.warning(res["avisos"][-1])

    def _recentes_seguro(self, album: str, r: dict) -> None:
        """Sem o álbum, a grade é "Recentes". Se a data da foto/vídeo não segue a ordem da letra e o Instagram
        ordenar por ela, as N primeiras podem ser outras mídias do emulador: não arrisca."""
        ordem = ((r.get("envio") or {}).get("ordem_data_da_midia") or {})
        ruins = [c for c, ok in ordem.items() if ok is False]
        if ruins:
            raise ErroPasso(f"não consegui abrir o álbum {album} e a data das mídias ({', '.join(ruins)}) não segue "
                            "a ordem da letra: em 'Recentes' poderia selecionar mídias erradas; ajustar 'album_menu'/"
                            "'album_item' em config/bluestacks.json pelo XML do diagnóstico")

    def _contar_selecao(self) -> tuple[int, str]:
        badges = self.tela.grade("badge_selecao", filtro=lambda e: (e.texto or "").strip().isdigit())
        if badges:
            numeros = [int(e.texto.strip()) for e in badges]
            sequencia = list(range(1, len(numeros) + 1))
            if numeros == sequencia:
                return len(numeros), "números nas miniaturas"
            if sorted(numeros) == sequencia:
                raise ErroPasso(f"a seleção ficou fora de ordem ({numeros}); não publico")
            # números repetidos ou que não começam em 1 (ex.: 2, 3, 4 = há uma mídia selecionada fora da tela)
            raise ErroPasso(f"os números da seleção não conferem ({numeros}); não publico")
        texto = self.tela.ler_texto("contador_selecao")
        m = re.search(r"\d+", texto or "")
        if m:
            return int(m.group()), f"contador '{texto}'"
        grade = self.tela.grade("miniaturas_galeria")
        numeros = [x for x in (self._numero_selecao(e) for e in grade) if x]
        if numeros:
            if numeros == list(range(1, len(numeros) + 1)):
                return len(numeros), "número na descrição das miniaturas"
            raise ErroPasso(f"os números da seleção (descrição das miniaturas) não conferem ({numeros}); não publico")
        prefixo = str(self.cfg.get("descricao_nao_selecionado") or "").strip().lower()
        if prefixo:
            if grade and all((e.descricao or "").strip() for e in grade):
                marcadas = [e for e in grade if not (e.descricao or "").strip().lower().startswith(prefixo)]
                return len(marcadas), "descrição das miniaturas (não confere a ordem)"
        raise ErroPasso("não consegui conferir quantas mídias ficaram selecionadas (sem números nas miniaturas e sem contador)")

    def _numero_selecao(self, el) -> int | None:
        """Ordem da mídia na seleção pela descrição da miniatura: 0 = não selecionada, None = não dá para saber."""
        desc = (getattr(el, "descricao", "") or "").strip()
        prefixo = str(self.cfg.get("descricao_nao_selecionado") or "").strip().lower()
        if prefixo and desc.lower().startswith(prefixo):
            return 0
        m = re.search(str(self.cfg.get("descricao_numero_selecao") or r"(?i)selecionada\s+(\d+)"), desc)
        return int(m.group(1)) if m else None

    def _miniatura(self, i: int, n: int):
        grade = self.tela.grade("miniaturas_galeria")
        if len(grade) < n:
            raise ErroPasso(f"a galeria mostra {len(grade)} miniatura(s) e a letra tem {n}")
        return grade[i]

    def _selecionar_uma(self, i: int, n: int) -> None:
        """Toca a i-ésima miniatura e espera ela virar "selecionada {i+1}". Só toca de novo se ela ainda estiver
        "Não selecionado" (um toque a mais desmarcaria). Sem descrição legível, toca uma vez (a contagem final confere)."""
        tentativas = int(self.cfg.get("tentativas_selecao", 3))
        for tentativa in range(1, tentativas + 1):
            num = self._numero_selecao(self._miniatura(i, n))
            if num == i + 1:
                return
            if num not in (None, 0):
                raise ErroPasso(f"a mídia {i + 1} da letra ficou com o número {num} na seleção; não publico")
            if num is None and tentativa > 1:
                return
            self._miniatura(i, n).tocar()
            self._pausa()
            if num is None:
                return
            if self.diagnostico and self._numero_selecao(self._miniatura(i, n)) == 0:
                # print logo depois do toque que não pegou: pega aviso passageiro do Instagram (toast), se houver
                self._salvar_tela(f"selecao_{self.letra}_{i + 1}_toque{tentativa}")
            limite = agora() + self._t("espera_selecao_s", 4)
            while agora() < limite:
                num = self._numero_selecao(self._miniatura(i, n))
                if num == i + 1:
                    if tentativa > 1:
                        log.info("Letra %s: a mídia %d só pegou no toque %d", self.letra, i + 1, tentativa)
                    return
                if num not in (None, 0):
                    raise ErroPasso(f"a mídia {i + 1} da letra ficou com o número {num} na seleção; não publico")
                dormir(self._t("intervalo_busca_s", 0.4))
            log.info("Letra %s: a mídia %d ainda não aparece selecionada; tocando de novo", self.letra, i + 1)
        if "vídeo" in (self._miniatura(i, n).descricao or "").lower():
            raise ErroPasso(f"a mídia {i + 1} da letra (vídeo) não ficou selecionada depois de {tentativas} toques "
                            "(miniatura cinza = o Instagram do BlueStacks não leu o vídeo); não publico letra pela metade")
        raise ErroPasso(f"a mídia {i + 1} da letra não ficou selecionada depois de {tentativas} toques "
                        "(miniatura ainda carregando?); não publico letra pela metade")

    def _selecionar(self, n: int) -> None:
        with self._passo("selecionar_varios"):
            if self.tela.achar("selecao_ativa", 0, plano_b=False) is not None:
                log.info("Letra %s: a seleção de várias já estava ligada (botão 'Cancelar'); não toquei", self.letra)
            else:
                self._tocar("selecionar_varios")
        with self._passo("tocar_midias"):
            for i in range(n):
                self._selecionar_uma(i, n)
        with self._passo("conferir_selecao"):
            qtd, como = self._contar_selecao()
            if qtd != n:
                raise ErroPasso(f"a seleção tem {qtd} de {n} mídia(s) ({como}); não publico letra pela metade")
            log.info("Seleção conferida: %d mídia(s) (%s)", qtd, como)

    # -- editor
    def _esperar_editor(self, depois_de: str) -> None:
        if self.tela.achar("editor", self._t("espera_editor_s", 20), plano_b=False) is None:
            raise ErroPasso(f"o editor do story não apareceu depois de {depois_de}")

    def _ir_para_midia(self, i: int, n: int) -> None:
        if n == 1:
            return
        miniaturas = self.tela.grade("miniaturas_editor")
        if len(miniaturas) != n:
            # a mais (ex.: botão "+" na faixa) deslocaria o índice e a figurinha iria para a mídia errada
            raise ErroPasso(f"achei {len(miniaturas)} miniatura(s) no editor e a letra tem {n}")
        miniaturas[i - 1].tocar()
        self._pausa()

    def _digitar_conferindo(self, chave: str, texto: str, url: bool = False) -> None:
        tentativas = int(self.cfg.get("tentativas_digitar", 3))
        lido = None
        for n in range(1, tentativas + 1):
            self._conferir_fora_do_direct()
            if n > 1:
                self.tela.digitar(chave, "", espera_s=self._t("espera_curta_s", 2))  # apaga antes de redigitar
            self.tela.digitar(chave, texto, espera_s=self._t("espera_padrao_s", 10))
            self._pausa()
            lido = self.tela.ler_texto(chave, espera_s=self._t("espera_curta_s", 2))
            if lido == texto:
                log.info("Campo %s conferido: %s", chave, texto)
                return
            if url and "://" in (lido or ""):
                log.warning("O campo da URL ficou com '%s'. Com https:// a figurinha sai sem link: apagando e digitando de novo", lido)
            else:
                log.warning("O campo %s mostrou %r em vez de %r; digitando de novo", chave, lido, texto)
        raise ErroPasso(f"o campo '{chave}' não ficou com o texto certo em {tentativas} tentativas (mostrou {lido!r})")

    def _fechar_sugestao_teclado(self) -> None:
        """Balão de correção do teclado ("ADICIONAR AO DICIONÁRIO"/"EXCLUIR") por cima da busca: o Voltar fecha só ele."""
        if self.tela.existe("popup_sugestao_teclado"):
            log.info("Letra %s: fechei o balão de correção do teclado na busca de música", self.letra)
            self.tela.voltar()
            self._pausa()

    @staticmethod
    def _nome_faixa(el) -> str:
        """"Selecionar faixa Home de Sunset Exotic,sem royalties,3:14" → "Home de Sunset Exotic"."""
        d = re.sub(r"(?i)^selecionar faixa\s+", "", el.descricao or el.texto or "")
        return re.sub(r"(?i),\s*sem royalties", "", re.sub(r",\s*\d+:\d+$", "", d)).strip()

    def _faixas(self) -> list:
        return self.tela.grade("faixas_musica")

    def _esperar_faixas(self, antes: set[str]) -> list:
        """Espera a lista de faixas mudar depois da busca; se não mudar em ``espera_resultados_musica_s``, fica com a
        que está na tela."""
        limite = agora() + self._t("espera_resultados_musica_s", 10)
        while True:
            faixas = self._faixas()
            if faixas and {self._nome_faixa(e) for e in faixas} != antes:
                return faixas
            if agora() >= limite:
                if faixas:
                    log.warning("Letra %s: a lista de músicas não mudou depois da busca; sorteio entre as da tela",
                                self.letra)
                return faixas
            dormir(self._t("intervalo_busca_s", 0.4))

    def _musica(self, m: dict, r: dict, res: dict) -> None:
        """Regra do usuário: busca "fashion" (``musica_sem_som``) e escolhe AO ACASO qualquer uma das faixas que
        aparecem (entre as ``musica_aleatoria_entre`` primeiras, que cabem na tela)."""
        busca = (m.get("musica") or {}).get("busca")
        icone = self.tela.achar("musica", self._t("espera_curta_s", 2), plano_b=False)
        if icone is not None:
            icone.tocar()
            self._pausa()
        else:
            self._tocar("figurinhas")
            self._tocar("figurinha_musica")
        antes = {self._nome_faixa(e) for e in self._faixas()}
        # apaga o que ficou no campo sem tocar no "X" (fica no topo, onde cai a notificação do Android: ensaio 19:42)
        # e antes de digitar (digitar sobre palavra sublinhada abriu o balão de correção do teclado: ensaio 19:25)
        self._fechar_sugestao_teclado()
        self._conferir_fora_do_direct()
        self.tela.digitar("buscar_musica", "", espera_s=self._t("espera_padrao_s", 10))
        self.tela.digitar("buscar_musica", busca, espera_s=self._t("espera_padrao_s", 10))
        self._pausa()
        self._fechar_sugestao_teclado()
        self._conferir_fora_do_direct()  # a tecla Enter numa conversa enviaria mensagem
        enviar = self.tela.achar("enviar_busca_musica", 0)
        if enviar is not None:
            enviar.tocar()
            self._pausa()
        faixas = self._esperar_faixas(antes)
        if not faixas:
            if self.diagnostico:
                self._salvar_tela(f"busca_musica_{self.letra}")
            raise ErroPasso(f"a busca de música '{busca}' não trouxe nenhuma faixa")
        entre = faixas[: max(1, int(self.cfg.get("musica_aleatoria_entre", 6)))]
        escolhido = sortear(entre)
        nome = self._nome_faixa(escolhido)
        log.info("Letra %s: música sorteada entre %d da busca '%s': %s", self.letra, len(entre), busca, nome)
        escolhido.tocar()
        self._pausa()
        self._usar_musica()
        r.setdefault("musicas", []).append({"midia": m.get("nome"), "busca": busca, "musica": nome, "entre": len(entre)})

    def _usar_musica(self) -> None:
        """Instagram 448 (ensaio 19:44): tocar na faixa só toca a prévia e abre a barra de baixo; a seta da barra
        (``usar_musica``) usa a faixa. Depois pode vir a tela de ajuste com "Concluído" (``concluir_musica``) ou já o
        editor."""
        self._tocar("usar_musica")
        limite = agora() + self._t("espera_editor_s", 20)
        while True:
            if self.tela.existe("editor"):
                return
            concluir = self.tela.achar("concluir_musica", 0, plano_b=False)
            if concluir is not None:
                concluir.tocar()
                self._pausa()
                continue
            if agora() >= limite:
                raise ErroPasso("depois de escolher a música o editor não voltou")
            self._conferir_fora_do_direct()
            dormir(self._t("intervalo_busca_s", 0.4))

    def _conferir_figurinha(self, fig: dict, antes: int) -> None:
        """No 448 a figurinha na tela é um item genérico ("Figurinhas. Toque e mantenha pressionado…", sem o texto nem
        o link no XML; ensaio de 26/09 01:11): confere que apareceu uma figurinha a mais do que antes de pôr a de link."""
        depois = len(self.tela.grade("figurinha_na_tela"))
        if depois > antes:
            return
        xml = (self.tela.xml() or "").lower()
        if any(a.lower() in xml for a in (fig.get("texto"), "wa.me") if a):
            return
        if self.cfg.get("exigir_figurinha_no_xml", True):
            raise ErroPasso("a figurinha de link não apareceu na tela (XML)")
        log.warning("Não vi a figurinha no XML da tela; conferir no print")

    def _figurinha(self, m: dict, r: dict) -> None:
        fig = m["figurinha"]
        antes = len(self.tela.grade("figurinha_na_tela"))
        self._tocar("figurinhas")
        if self.tela.achar("figurinha_link", self._t("espera_curta_s", 2), plano_b=False) is None and self.tela.existe("buscar_figurinha"):
            self.tela.digitar("buscar_figurinha", "link")
            self._pausa()
        self._tocar("figurinha_link")
        self._digitar_conferindo("campo_url", fig["url"], url=True)
        texto = fig.get("texto")
        if texto:
            self._tocar("personalizar_texto")
            self._digitar_conferindo("campo_texto_figurinha", texto)
            self._tocar("confirmar_teclado")
            depois = self.tela.ler_texto("campo_texto_figurinha")
            if depois and depois != texto and depois.strip() == texto:
                raise ErroPasso("o ✓ do teclado pôs uma quebra de linha no texto da figurinha; ajustar "
                                "'confirmar_teclado' em config/bluestacks.json pelo XML do diagnóstico")
        self._tocar("concluir_figurinha")
        self._esperar_editor("a figurinha")
        self._conferir_figurinha(fig, antes)
        r["figurinha"] = {"midia": m.get("nome"), "url": fig["url"], "texto": texto}

    def _montar_midias(self, L: dict, r: dict, res: dict) -> None:
        midias = L["midias"]
        for i, m in enumerate(midias, 1):
            with self._passo(f"midia_{i}"):
                self._ir_para_midia(i, len(midias))
            if m.get("precisa_musica"):
                with self._passo(f"musica_{i}"):
                    self._musica(m, r, res)
            if m.get("figurinha"):
                with self._passo(f"figurinha_{i}"):
                    self._figurinha(m, r)
            self._print(f"{'ensaio' if self.ensaio else 'midia'}_{self.letra}_{i}.png", r)

    # -- publicação (só no modo real)
    def _interruptor_na_linha(self, rotulo):
        """O interruptor mais perto (na vertical) do texto do Facebook, na mesma linha. Nunca o de cima/baixo
        (ex.: a caixa marcada de "Seu story", logo acima, que não pode ser desmarcada)."""
        cy = rotulo.centro[1]
        candidatos = []
        for e in self.tela.grade("interruptores"):
            if e.limites == rotulo.limites:
                return e
            dy = abs(e.centro[1] - cy)
            if dy <= max(rotulo.altura, e.altura, 20) * 0.75:
                candidatos.append((dy, e))
        return min(candidatos, key=lambda c: c[0])[1] if candidatos else None

    def _estado_facebook(self):
        el = self.tela.achar("compartilhar_facebook_toggle", 0, plano_b=False)
        if el is None:
            return None, None
        if el.marcavel or (el.marcavel is None and el.marcado is not None):
            return el, el.marcado
        alvo = self._interruptor_na_linha(el)
        if alvo is None:
            raise ErroPasso("vi a opção de compartilhar no Facebook, mas não achei o botão dela; não publico sem garantir que está desligada")
        return alvo, alvo.marcado

    def _garantir_facebook_desligado(self) -> str:
        alvo, ligado = self._estado_facebook()
        if alvo is None:
            return "não apareceu"
        if not ligado:
            return "desligado"
        log.warning("Compartilhar no Facebook estava LIGADO; desligando antes de publicar")
        alvo.tocar()
        self._pausa()
        _, ligado = self._estado_facebook()
        if ligado:
            raise ErroPasso("não consegui desligar o compartilhamento no Facebook; não publiquei")
        return "desliguei"

    def _concluir_publicacao(self) -> None:
        limite = agora() + self._t("espera_publicacao_s", 120)
        tocou = False
        while agora() < limite:
            if self.tela.existe("feed"):
                return
            aviso = self.tela.achar("dispensar_aviso", 0, plano_b=False)
            if aviso is not None:  # ex.: "Compartilhar no Facebook?" → "Agora não" antes de qualquer "Compartilhar"
                log.info("Recusei um aviso depois de 'Seu story' (%s)", aviso.texto or aviso.descricao)
                aviso.tocar()
                self._pausa()
                continue
            if self.tela.existe("abrir_galeria"):  # voltou para a câmera do story: já publicou
                self.tela.voltar()
                self._pausa()
                continue
            if not tocou and self.tela.existe("concluir_publicacao"):
                self._garantir_facebook_desligado()
                self._tocar("concluir_publicacao")
                tocou = True
                continue
            dormir(self._t("intervalo_busca_s", 0.4))
        for _ in range(2):  # tela de compartilhamento que não fecha sozinha: voltar não publica nada
            self.tela.voltar()
            self._pausa()
            if self.tela.achar("feed", self._t("espera_curta_s", 2), plano_b=False) is not None:
                return
        raise ErroPasso("toquei em publicar, mas o Instagram não voltou ao feed")

    def _publicar(self, r: dict) -> None:
        with self._passo("conferir_editor"):
            if not self.tela.existe("editor") or self.tela.existe("feed"):
                # o feed também mostra "Seu story" (o próprio story no topo): tocar ali não publica nada
                raise ErroPasso("não estou no editor do story; não publico")
        self.publicando = True
        try:
            with self._passo("facebook"):
                r["facebook"] = self._garantir_facebook_desligado()
            with self._passo("seu_story"):
                self._tocar("seu_story")
            with self._passo("concluir_publicacao"):
                self._concluir_publicacao()
        finally:
            self.publicando = False

    def _registrar(self, data: str, L: dict, r: dict, res: dict) -> None:
        """Grava em ``postados.csv``. Se falhar: grava o pendente na pasta central (conta como publicada no
        próximo montar/postar) e levanta ``ErroRegistro`` para PARAR antes da próxima letra."""
        letra = L["letra"]
        midias = [{"nome": m.get("nome"), "arquivo": m.get("arquivo") or m.get("nome"), "cores": m.get("cores") or [],
                   "hash": m.get("hash")} for m in L["midias"]]
        try:
            r["registrado"] = postados.registrar(data, letra, L.get("sku"), L.get("peca"), midias, self.pedido)
            return
        except Exception as e:  # noqa: BLE001 - já publicou: guarda o que faltou registrar e para
            erro = e
        r["registro_erro"] = str(erro)
        aviso = (f"A letra {letra} FOI PUBLICADA, mas não consegui registrar em postados.csv: "
                 f"{str(erro).rstrip('. ') or erro.__class__.__name__}.")
        pendente = {"data": data, "letra": letra, "sku": L.get("sku"), "peca": L.get("peca"), "midias": midias,
                    "pedido": self.pedido}
        try:
            self.ctx.arquivo(f"postados_pendentes_{letra}.json").write_text(
                json.dumps(pendente, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:  # noqa: BLE001 - a cópia central abaixo é a que vale
            log.warning("Não consegui salvar a cópia do pendente na pasta do pedido: %s", e)
        try:
            linhas = getattr(erro, "linhas", None) or postados.linhas_do_registro(
                data, letra, L.get("sku"), L.get("peca"), midias, self.pedido)
            destino = postados.gravar_pendente(data, letra, linhas)
            r["registro_pendente"] = str(destino)
            aviso += (f" O registro ficou pendente em {destino}: a letra {letra} já conta como publicada no próximo "
                      "stories.montar/stories.postar e entra no CSV no próximo registro que der certo.")
        except Exception as e:  # noqa: BLE001
            aviso += (f" NÃO consegui gravar nem o registro pendente ({e}): a letra {letra} NÃO vai aparecer como "
                      f"publicada; tirar {letra} do próximo stories.montar.")
        res["avisos"].append(aviso)
        log.error(aviso)
        raise ErroRegistro(aviso)

    # -- letra e execução
    def _letra(self, plano: dict, L: dict, r: dict, res: dict) -> None:
        n = len(L["midias"])
        with self._passo("enviar_midias"):
            if self.enviar is not None:
                r["envio"] = self.enviar(L)
                res["avisos"] += [f"Letra {self.letra}: {a}" for a in (r["envio"] or {}).get("avisos") or []]
        with self._passo("abrir_instagram"):
            self._abrir_instagram()
        self._entrar_no_story()
        with self._passo("abrir_galeria"):
            self._abrir_galeria()
        with self._passo("escolher_album"):
            self._escolher_album(f"{plano['data']}_{L['letra']}", r, res)
        self._selecionar(n)
        with self._passo("avancar"):
            self._tocar("avancar")
            self._esperar_editor("Avançar")
        self._montar_midias(L, r, res)
        if self.ensaio:
            with self._passo("sair_sem_publicar"):
                if not self._sair_com_seguranca():
                    res["avisos"].append(f"Letra {self.letra}: não confirmei a volta ao feed depois do ensaio.")
            r["estado"] = "ensaio_ok"
            log.info("Letra %s montada em ENSAIO (nada publicado)", self.letra)
            return
        self._publicar(r)
        r["estado"] = "publicada"
        res["publicadas"].append(L["letra"])
        log.info("Letra %s PUBLICADA (%d mídia(s))", self.letra, n)
        self._print(f"publicada_{self.letra}.png", r)
        self._registrar(plano["data"], L, r, res)

    def _falhou(self, r: dict, res: dict, erro) -> None:
        passo = self.passo or "início"
        r["estado"] = "falhou"
        r["erro"] = str(erro) or erro.__class__.__name__
        if self.tocou_publicar:
            r["incerta"] = True
            r["erro"] += (" ATENÇÃO: já tinha tocado em 'Seu story'; a letra pode ter subido. "
                          "Conferir pelo JS antes de repetir.")
        res["parou_em"] = f"letra {self.letra}: {passo}"
        log.error("Letra %s falhou no passo '%s': %s", self.letra, passo, r["erro"])
        nomes = self._salvar_tela(f"falha_{self.letra}_{passo}")
        r["prints"] += [x for x in nomes if x.endswith(".png")]
        r["xml_falha"] = next((x for x in nomes if x.endswith(".xml")), None)
        try:
            if not self._sair_com_seguranca():
                res["avisos"].append("Depois da falha não confirmei a volta ao feed; conferir o BlueStacks.")
        except Exception as e:  # noqa: BLE001
            log.warning("Não consegui sair com segurança depois da falha: %s", e)

    def rodar(self, plano: dict, pular: set[str] | frozenset = frozenset()) -> dict:
        res = novo_resultado(plano, self.ensaio)
        for L, r in zip(plano["letras"], res["letras"]):
            if L["letra"] in pular:
                r["pulada"] = "já publicada antes (postados.csv)"
                log.warning("Letra %s já está em postados.csv para %s; não publico de novo", L["letra"], plano["data"])
                continue
            self.letra, self.passo, self.tocou_publicar = L["letra"], None, False
            try:
                self._letra(plano, L, r, res)
            except ErroRegistro as e:  # a letra subiu (continua "publicada"); só não dá para seguir sem registro
                res["parou_em"] = f"letra {self.letra}: registro em postados.csv"
                nao = [x["letra"] for x in res["letras"] if x["estado"] == "nao_iniciada" and not x.get("pulada")]
                raise ErroPostagem(f"{e} Parei antes da próxima letra (fechar o postados.csv no Excel). "
                                   f"Publicadas: {', '.join(res['publicadas'])}. "
                                   f"Não iniciadas: {', '.join(nao) or 'nenhuma'}.", res) from e
            except KeyboardInterrupt:
                self._falhou(r, res, "interrompido (Ctrl+C)")
                raise
            except Exception as e:  # noqa: BLE001 - qualquer falha para tudo, com segurança
                self._falhou(r, res, e)
                raise ErroPostagem(mensagem_parada(res, r), res) from e
        return res


def mensagem_parada(res: dict, r: dict) -> str:
    publicadas = ", ".join(res["publicadas"]) or "nenhuma"
    nao = [x["letra"] for x in res["letras"] if x["estado"] == "nao_iniciada" and not x.get("pulada")]
    passo = (res.get("parou_em") or "").split(": ", 1)[-1]
    return (f"Parei na letra {r['letra']} (passo '{passo}'): {r['erro']} "
            f"Publicadas antes: {publicadas}. Não iniciadas: {', '.join(nao) or 'nenhuma'}.")


def resumo(res: dict) -> str:
    linhas = ["ENSAIO: nada foi publicado." if res.get("ensaio") else "Postagem real."]
    for x in res.get("letras") or []:
        n = len(x.get("midias") or [])
        if x["estado"] == "publicada":
            linhas.append(f"- {x['letra']}: publicada ({n} mídia(s))")
        elif x["estado"] == "ensaio_ok":
            linhas.append(f"- {x['letra']}: montada em ensaio ({n} mídia(s)); prints: {', '.join(x.get('prints') or [])}")
        elif x["estado"] == "falhou":
            linhas.append(f"- {x['letra']}: FALHOU: {x.get('erro')}")
        else:
            linhas.append(f"- {x['letra']}: não iniciada" + (f" ({x['pulada']})" if x.get("pulada") else ""))
    if res.get("parou_em"):
        linhas.append(f"Parou em: {res['parou_em']}")
    linhas += [f"Aviso: {a}" for a in res.get("avisos") or []]
    return "\n".join(linhas)


# ---------------------------------------------------------------- entradas

def executar(plano: dict, ctx: Contexto, *, ensaio: bool = True, diagnostico: bool = False, tela=None, enviar=None,
             conexao: android.Conexao | None = None, repostar: list[str] | tuple = ()) -> dict:
    """Valida o plano, conecta no BlueStacks (se não vier ``tela``) e posta letra por letra."""
    cfg = _cfg()
    res = novo_resultado(plano, ensaio)
    try:
        problemas = validar_plano(plano, cfg)
    except Exception as e:  # noqa: BLE001 - ex.: arquivo aberto em outro programa ao calcular o hash
        res["parou_em"] = "validação do plano"
        raise ErroPostagem(f"Não consegui conferir o plano; nada foi feito: {e}", res) from e
    if problemas:
        res["parou_em"] = "validação do plano"
        raise ErroPostagem("O plano tem problemas; nada foi feito: " + "; ".join(problemas), res)
    trava = None
    if tela is None:  # emulador de verdade: um pedido/teste por vez (vigia, stories-postar, testar.bat)
        trava = _travar_emulador(res)
    try:
        return _postar(plano, ctx, res, cfg, ensaio=ensaio, diagnostico=diagnostico, tela=tela, enviar=enviar,
                       conexao=conexao, repostar=repostar)
    finally:
        if trava is not None:
            trava.liberar()


def _travar_emulador(res: dict | None):
    """Pega ``fila/bluestacks.lock``. Ocupada → ``ErroPostagem`` (ou ``RuntimeError`` sem ``res``)."""
    from .. import fila  # fila importa tarefas, que aponta para este módulo: importar só aqui

    trava = fila.Trava(fila.pasta_fila() / "bluestacks.lock")
    try:
        ok = trava.adquirir()
    except OSError as e:
        ok, detalhe = False, f" ({e})"
    else:
        detalhe = ""
    if ok:
        return trava
    log.error(MSG_EM_USO + detalhe)
    if res is None:
        raise RuntimeError(MSG_EM_USO + detalhe)
    res["parou_em"] = "trava do BlueStacks"
    raise ErroPostagem(MSG_EM_USO + detalhe, res)


def _postar(plano: dict, ctx: Contexto, res: dict, cfg: dict, *, ensaio: bool, diagnostico: bool, tela, enviar,
            conexao, repostar) -> dict:
    pular: set[str] = set()
    if not ensaio:
        try:
            ja = postados.letras_postadas(plano["data"]) - {str(x).upper() for x in repostar}
        except Exception as e:  # noqa: BLE001 - sem saber o que já subiu, não publica
            res["parou_em"] = "leitura de postados.csv"
            raise ErroPostagem(f"Não consegui ler o registro de já postados: {e}", res) from e
        pular = {L["letra"] for L in plano["letras"]} & ja
        try:
            postados.testar_gravacao()
        except Exception as e:  # noqa: BLE001 - publicar sem conseguir registrar faria a letra subir de novo depois
            res["parou_em"] = "gravação de postados.csv"
            raise ErroPostagem(f"Não consigo gravar em postados.csv; nada foi publicado. Fechar o arquivo (Excel) e "
                               f"pedir de novo: {e}", res) from e
    info = None
    if tela is None:
        try:
            conexao = conexao or android.conectar(cfg)
            info = conexao.info(cfg.get("pacote_instagram", "com.instagram.android"))
            log.info("BlueStacks: %s", info)
            tela = android.abrir_tela(conexao, cfg)
        except Exception as e:  # noqa: BLE001 - nada começou
            res["parou_em"] = "conexão com o BlueStacks"
            raise ErroPostagem(f"Não consegui falar com o BlueStacks: {e}", res) from e
    if enviar is None and conexao is not None:
        def enviar(L: dict) -> dict:
            return android.enviar_letra(conexao, plano["data"], L["letra"], L["midias"], cfg)
    log.info("Postando %d letra(s) de %s em modo %s", len(plano["letras"]), plano["data"], "ENSAIO" if ensaio else "REAL")
    postador = Postador(tela, ctx, ensaio=ensaio, diagnostico=diagnostico, enviar=enviar, cfg=cfg,
                        pedido=ctx.id_pedido or plano.get("id"))
    res = postador.rodar(plano, pular)
    if info:
        res["dispositivo"] = info
    return res


def _ler_plano(caminho: Path) -> dict:
    plano = json.loads(Path(caminho).read_text(encoding="utf-8-sig"))
    if isinstance(plano, dict) and isinstance(plano.get("plano"), dict):
        plano = plano["plano"]  # aceita também o resultado do stories-montar
    if not isinstance(plano, dict):
        raise ValueError(f"{caminho} não é um plano de postagem")
    return plano


def plano_mais_recente(data: str) -> Path:
    pasta = config.pastas().trabalho_stories / data
    planos = sorted(pasta.glob("plano-*.json"), key=lambda p: (p.stat().st_mtime, p.name))
    if not planos:
        raise FileNotFoundError(f"Nenhum plano em {pasta}. Rode o stories-montar antes.")
    return planos[-1]


def tarefa(args: dict, ctx: Contexto) -> dict:
    """Pedido ``stories.postar``: ``args = {"plano": {...}, "repostar"?: ["A"]}``. Publica só se nem o pedido
    nem o plano estiverem em ensaio."""
    plano = args.get("plano")
    if isinstance(plano, str):
        plano = _ler_plano(Path(plano))
    if not isinstance(plano, dict):
        raise ValueError("args.plano tem que ser o plano de postagem (objeto JSON)")
    ensaio = bool(ctx.ensaio) or bool(plano.get("ensaio", False))
    if ensaio and not ctx.ensaio:
        log.warning("O plano foi montado em ENSAIO; rodando em ensaio. Para publicar, monte de novo com --real.")
    try:
        resultado = executar(plano, ctx, ensaio=ensaio, diagnostico=bool(ctx.diagnostico), repostar=args.get("repostar") or ())
    except ErroPostagem as e:
        if isinstance(e.resultado_parcial, dict):
            _anexar_relatorio(plano, e.resultado_parcial, ctx)
        raise
    return _anexar_relatorio(plano, resultado, ctx)


def _anexar_relatorio(plano: dict, resultado: dict, ctx: Contexto) -> dict:
    """Põe no resultado o aviso pronto e o JS de conferência (a IA do Cowork não roda comandos no PC)."""
    from . import relatorio

    try:
        texto = relatorio.texto_resultado(plano, resultado)
        publicadas = list(resultado.get("publicadas") or [])
        # "incerta" = falhou depois de tocar em "Seu story" (_falhou marca r["incerta"]; o estado fica "falhou")
        incertas = [r.get("letra") for r in resultado.get("letras") or [] if r.get("incerta")]
        resultado["relatorio"] = texto
        resultado["js_conferencia"] = relatorio.js_conferencia(plano, publicadas + [x for x in incertas if x not in publicadas])
        ctx.arquivo("relatorio.txt").write_text(texto + "\n", encoding="utf-8")
    except Exception as e:  # noqa: BLE001 - o relatório nunca pode esconder o resultado da postagem
        log.warning("Não consegui montar o relatório: %s", e)
    return resultado


def cli(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="python -m rotinas stories-postar",
                                description="A5: posta os stories do plano pelo BlueStacks. Padrão: ENSAIO (não publica).")
    p.add_argument("--plano", required=True, help="arquivo plano-<id>.json gerado pelo stories-montar")
    modo = p.add_mutually_exclusive_group()
    modo.add_argument("--real", action="store_true", help="publica de verdade (sem isto é ensaio)")
    modo.add_argument("--ensaio", action="store_true", help="ensaio: monta tudo e não publica (é o padrão)")
    p.add_argument("--diagnostico", action="store_true", help="salva XML + print de cada passo")
    p.add_argument("--repostar", nargs="*", default=[], metavar="LETRA",
                   help="letras já registradas em postados.csv que podem ser publicadas de novo")
    a = p.parse_args(argv)
    plano = _ler_plano(Path(a.plano))
    marca = carimbo()
    pasta = config.pastas().trabalho_stories / str(plano.get("data") or "sem-data") / f"postar-{marca}"
    ctx = Contexto(pasta, ensaio=not a.real, diagnostico=a.diagnostico, id_pedido=f"postar-{marca}")
    if a.real and plano.get("ensaio"):
        log.warning("O plano foi montado em ensaio, mas --real foi pedido: vou PUBLICAR.")
    handler = registro.anexar_arquivo(pasta / "log.txt")
    codigo = 0
    try:
        try:
            res = executar(plano, ctx, ensaio=not a.real, diagnostico=a.diagnostico, repostar=a.repostar)
        except ErroPostagem as e:
            res, codigo = dict(e.resultado_parcial, erro=str(e)), 1
            print(f"ERRO: {e}", file=sys.stderr)
        (pasta / "resultado.json").write_text(registro.ocultar(json.dumps(res, ensure_ascii=False, indent=2)), encoding="utf-8")
        print(resumo(res))
        print(f"Pasta: {pasta}")
    finally:
        registro.remover(handler)
    return codigo


def teste_real(ctx: Contexto, argv: list[str]) -> dict:
    """``testar.bat bluestacks``: conecta, mostra o aparelho e percorre SEM publicar feed → Criar → Story →
    galeria → Selecionar → menu de álbuns, salvando XML + print de cada tela; depois volta."""
    argparse.ArgumentParser(prog="testar.bat bluestacks", description=teste_real.__doc__).parse_args(argv)
    trava = _travar_emulador(None)
    try:
        return _teste_real(ctx)
    finally:
        trava.liberar()


def _teste_real(ctx: Contexto) -> dict:
    cfg = _cfg()
    con = android.conectar(cfg)
    info = con.info(cfg.get("pacote_instagram", "com.instagram.android"))
    log.info("BlueStacks: %s", info)
    tela = android.abrir_tela(con, cfg)
    post = Postador(tela, ctx, ensaio=True, diagnostico=True, cfg=cfg)
    post.letra = "teste"
    extras: dict = {"tamanho_tela": list(tela.tamanho())}

    def selecionar() -> None:
        post._tocar("selecionar_varios")
        extras["miniaturas_galeria"] = len(tela.grade("miniaturas_galeria"))

    etapas = [("abrir_instagram", post._abrir_instagram, True), ("entrar_no_story", post._entrar_no_story, True),
              ("abrir_galeria", post._abrir_galeria, True),
              ("selecionar_varios", selecionar, True), ("album_menu", lambda: post._tocar("album_menu"), False)]
    passos = []
    for nome, acao, obrigatoria in etapas:
        try:
            with post._passo(nome):
                acao()
            passos.append({"passo": nome, "ok": True})
        except Exception as e:  # noqa: BLE001 - registra e para
            passos.append({"passo": nome, "ok": False, "erro": str(e)})
            if obrigatoria:
                break
    post._salvar_tela(f"passo_{post.n_passo + 1:03d}_teste_ultima_tela")
    saiu = post._sair_com_seguranca()
    ok = all(p["ok"] for p in passos if p["passo"] != "album_menu") and len(passos) == len(etapas)
    linhas = [f"BlueStacks {info.get('serial')} (Android {info.get('android')}, tela {info.get('tela')}), "
              f"Instagram {info.get('instagram')}"]
    linhas += [f"- {p['passo']}: {'ok' if p['ok'] else 'FALHOU: ' + p['erro']}" for p in passos]
    linhas.append("Voltou ao feed." if saiu else "Não confirmei a volta ao feed.")
    return {"ok": ok, "dispositivo": info, "passos": passos, "saiu_com_seguranca": saiu, **extras,
            "resumo": "\n".join(linhas)}


def plano_sintetico(pasta: Path) -> dict:
    """Letra de teste "T" (1 vídeo mudo + 2 fotos geradas na hora, em ``pasta``; nunca na pasta do usuário)
    com música no vídeo e figurinha de link na última foto — para afinar os passos do editor em ENSAIO.

    O vídeo imita um vídeo de celular (``sintetico_video_ffmpeg`` na config: H.264 Main sem B-frames, áudio AAC
    em silêncio, faststart): o H.264 High com B-frames e sem áudio ficou cinza na galeria do BlueStacks (25/09)."""
    from PIL import Image, ImageDraw

    from . import link

    pasta.mkdir(parents=True, exist_ok=True)
    video = pasta / "T - 1.mp4"
    if not video.exists():
        args = [str(a) for a in _cfg().get("sintetico_video_ffmpeg") or ()]
        if not args:
            raise ErroPasso("falta 'sintetico_video_ffmpeg' em config/bluestacks.json (como gerar o vídeo de teste)")
        ferramentas.rodar([midia.ffmpeg(), "-hide_banner", "-nostdin", "-y", *args, str(video)], timeout=180)
    fotos = []
    for n, cor in ((2, (170, 40, 70)), (3, (40, 110, 70))):
        foto = pasta / f"T - {n}.jpg"
        if not foto.exists():
            img = Image.new("RGB", (1080, 1920), cor)
            ImageDraw.Draw(img).text((80, 900), f"TESTE ROTINAS {n} - NAO POSTAR", fill=(255, 255, 255))
            img.save(foto, "JPEG", quality=90)
        fotos.append(foto)
    peca = "Peça de Teste"
    midias = [{"nome": "T - 1", "arquivo": video.name, "caminho": str(video), "tipo": "video", "hash": midia.hash_arquivo(video),
               "cores": ["Teste"], "precisa_musica": True, "musica": link.musica_sem_som(), "figurinha": None}]
    for i, foto in enumerate(fotos):
        ultima = i == len(fotos) - 1
        midias.append({"nome": foto.stem, "arquivo": foto.name, "caminho": str(foto), "tipo": "foto",
                       "hash": midia.hash_arquivo(foto), "cores": ["Teste"], "precisa_musica": False, "musica": None,
                       "figurinha": {"url": link.montar_link(peca), "texto": link.texto_figurinha(0)} if ultima else None})
    return {"data": "2000-01-01", "id": "teste-sintetico", "ensaio": True, "ordem": "letras",
            "letras": [{"letra": "T", "sku": "TESTE", "peca": peca, "categoria": "Teste", "midias": midias}],
            "cortes": [], "avisos": ["Plano sintético de teste: nunca publicar."]}


def teste_ensaio(ctx: Contexto, argv: list[str]) -> dict:
    """``testar.bat stories-ensaio --data D`` (plano mais recente), ``--plano arquivo`` ou ``--sintetico`` (letra de
    teste gerada na hora): ensaio + diagnóstico. Nunca publica."""
    p = argparse.ArgumentParser(prog="testar.bat stories-ensaio", description=teste_ensaio.__doc__)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--data", help="AAAA-MM-DD: usa o plano mais recente de stories/<data>/")
    g.add_argument("--plano", help="arquivo plano-<id>.json")
    g.add_argument("--sintetico", action="store_true", help="letra de teste (1 vídeo sem som + 2 fotos) gerada na hora")
    a = p.parse_args(argv)
    if a.sintetico:
        caminho = config.pastas().trabalho_stories / "_teste" / carimbo()
        plano = plano_sintetico(caminho)
        log.info("Ensaio com a letra de teste gerada em %s", caminho)
    else:
        caminho = Path(a.plano) if a.plano else plano_mais_recente(a.data)
        plano = _ler_plano(caminho)
        log.info("Ensaio com o plano %s", caminho)
    res = executar(plano, ctx, ensaio=True, diagnostico=True)
    res["plano"] = str(caminho)
    # "Recentes" no lugar do álbum passa no ensaio, mas a postagem real para ali: não é ok
    res["ok"] = all((x["estado"] == "ensaio_ok" and not x.get("recuo_recentes")) or x.get("pulada") for x in res["letras"])
    res["resumo"] = resumo(res)
    return res
