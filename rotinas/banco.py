"""Acesso de LEITURA ao Supabase da loja (tabelas ``products`` e ``product_variations``).

As tabelas têm RLS: só o papel ``authenticated`` lê (a chave pública sozinha recebe lista vazia). Por isso o script
entra com um usuário próprio das rotinas (e-mail e senha do Supabase Auth) e usa o token dele:

- ``SUPABASE_URL``: ``https://nailfzcujyxydqldktgg.supabase.co``
- ``SUPABASE_KEY``: chave pública do projeto (publishable ``sb_publishable_…`` ou a legada ``anon``)
- ``SUPABASE_EMAIL`` / ``SUPABASE_SENHA``: usuário das rotinas

Pelas políticas atuais, um usuário logado também pode gravar nessas tabelas; o script nunca grava: este módulo só
faz GET em ``/rest/v1/<tabela>`` e só nas tabelas permitidas. Nada daqui vai para log sem ``registro.ocultar``.
"""

from __future__ import annotations

import threading
import time

from . import config, registro

log = registro.obter("banco")

VARIAVEIS = ("SUPABASE_URL", "SUPABASE_KEY", "SUPABASE_EMAIL", "SUPABASE_SENHA")
TABELAS_PERMITIDAS = ("products", "product_variations")
MARGEM_TOKEN_S = 60

_cache: dict[tuple[str, str], tuple[str, float]] = {}
_trava = threading.Lock()


class ErroBanco(RuntimeError):
    """Problema de acesso ao Supabase (mensagem em português, sem segredo)."""

    def __init__(self, mensagem: str, status: int | None = None, codigo: str | None = None):
        super().__init__(mensagem)
        self.status = status
        self.codigo = codigo


def faltando() -> list[str]:
    """Variáveis do ``.env`` que estão vazias."""
    return [n for n in VARIAVEIS if not (config.segredo(n) or "").strip()]


def limpar_cache() -> None:
    with _trava:
        _cache.clear()


def _json(r):
    try:
        return r.json()
    except ValueError:
        return None


class Sessao:
    """Login com o usuário das rotinas e GET de leitura. O token fica em memória até perto de expirar."""

    def __init__(self, url: str | None = None, chave: str | None = None, email: str | None = None,
                 senha: str | None = None, timeout_s: float = 20.0, http=None):
        valores = {
            "SUPABASE_URL": url or config.segredo("SUPABASE_URL"),
            "SUPABASE_KEY": chave or config.segredo("SUPABASE_KEY"),
            "SUPABASE_EMAIL": email or config.segredo("SUPABASE_EMAIL"),
            "SUPABASE_SENHA": senha or config.segredo("SUPABASE_SENHA"),
        }
        vazias = [n for n, v in valores.items() if not (v or "").strip()]
        if vazias:
            raise ErroBanco(
                f"Falta {', '.join(vazias)} no .env ({config.caminho_env()}). As tabelas do estoque só abrem para "
                "usuário logado: preencha SUPABASE_EMAIL e SUPABASE_SENHA com o usuário das rotinas e SUPABASE_KEY "
                "com a chave pública do projeto."
            )
        base = valores["SUPABASE_URL"].strip().rstrip("/")
        for sufixo in ("/rest/v1", "/auth/v1"):
            if base.endswith(sufixo):
                base = base[: -len(sufixo)]
        if not base.startswith(("https://", "http://")):
            raise ErroBanco("SUPABASE_URL no .env precisa começar com https:// (ex.: https://<projeto>.supabase.co).")
        self.base = base
        self._chave = valores["SUPABASE_KEY"].strip()
        self._email = valores["SUPABASE_EMAIL"].strip()
        self._senha = valores["SUPABASE_SENHA"]
        self.timeout_s = float(timeout_s)
        if http is None:
            import requests as http  # noqa: N813 - importado aqui para o módulo carregar sem requests
        self._http = http

    def __repr__(self) -> str:  # nunca mostrar chave, e-mail ou senha
        return "Sessao()"

    # -- login
    def token(self, renovar: bool = False) -> str:
        chave_cache = (self.base, self._email)
        with _trava:
            guardado = _cache.get(chave_cache)
            if guardado and not renovar and guardado[1] - MARGEM_TOKEN_S > time.time():
                return guardado[0]
        r = self._pedir("post", f"{self.base}/auth/v1/token", params={"grant_type": "password"},
                        headers={"apikey": self._chave, "Content-Type": "application/json"},
                        json={"email": self._email, "password": self._senha})
        corpo = _json(r)
        if r.status_code in (400, 401, 422):
            codigo = (corpo or {}).get("error_code") or (corpo or {}).get("error") if isinstance(corpo, dict) else None
            if codigo in ("invalid_credentials", "invalid_grant"):
                raise ErroBanco("O Supabase recusou o e-mail ou a senha do usuário das rotinas: confira SUPABASE_EMAIL "
                                "e SUPABASE_SENHA no .env.", r.status_code, codigo)
            if codigo == "email_not_confirmed":
                raise ErroBanco("O usuário das rotinas ainda não foi confirmado no Supabase (Authentication > Users: "
                                "confirmar o e-mail ou recriar com 'Auto Confirm User').", r.status_code, codigo)
            if r.status_code == 401:
                raise ErroBanco("O Supabase recusou a chave do projeto: confira SUPABASE_KEY no .env (chave pública "
                                "'publishable' ou 'anon').", r.status_code, codigo)
            detalhe = registro.ocultar(str((corpo or {}).get("msg") or (corpo or {}).get("error_description")
                                           or r.text or ""))[:200] if isinstance(corpo, dict) else ""
            raise ErroBanco(f"Login no Supabase recusado (HTTP {r.status_code}, {codigo or 'sem código'}): {detalhe}",
                            r.status_code, codigo)
        if not 200 <= r.status_code < 300 or not isinstance(corpo, dict) or not corpo.get("access_token"):
            raise ErroBanco(f"Login no Supabase falhou (HTTP {r.status_code}).", r.status_code)
        token = str(corpo["access_token"])
        validade = time.time() + float(corpo.get("expires_in") or 3600)
        with _trava:
            _cache[chave_cache] = (token, validade)
        log.info("Login no Supabase ok (usuário das rotinas)")
        return token

    # -- leitura
    def get(self, tabela: str, params: list[tuple[str, str]]):
        """GET em ``/rest/v1/<tabela>`` com o token do usuário. Renova o token uma vez se ele expirou."""
        if tabela not in TABELAS_PERMITIDAS:
            raise ErroBanco(f"Leitura recusada: a tabela {tabela!r} não é das rotinas ({', '.join(TABELAS_PERMITIDAS)}).")
        r = self._pedir("get", f"{self.base}/rest/v1/{tabela}", params=params, headers=self._cabecalhos(self.token()))
        if r.status_code == 401:
            r = self._pedir("get", f"{self.base}/rest/v1/{tabela}", params=params,
                            headers=self._cabecalhos(self.token(renovar=True)))
        return r

    def _cabecalhos(self, token: str) -> dict[str, str]:
        return {"apikey": self._chave, "Authorization": f"Bearer {token}", "Accept": "application/json"}

    def _pedir(self, metodo: str, url: str, **kwargs):
        try:
            return getattr(self._http, metodo)(url, timeout=self.timeout_s, **kwargs)
        except Exception as e:  # noqa: BLE001 - rede: só o tipo e a mensagem limpa
            nome = e.__class__.__name__
            if "Timeout" in nome:
                raise ErroBanco(f"O Supabase não respondeu em {self.timeout_s:g} s. Confira a internet.") from e
            raise ErroBanco(f"Sem conexão com o Supabase ({nome}): {registro.ocultar(str(e))[:200]}") from e


def testar_leitura(timeout_s: float = 20.0, http=None) -> dict:
    """Login + leitura de 1 id de ``products`` (nunca ``cost_price``). Usado pelo ``verificar`` e pelo diagnóstico.

    ``ok`` só com login aceito, HTTP 200 e pelo menos 1 produto visível (lista vazia = RLS barrou ou banco vazio).
    """
    vazias = faltando()
    if vazias:
        return {"configurado": False, "ok": False, "status_http": None,
                "mensagem": f"Falta {', '.join(vazias)} no .env."}
    try:
        sessao = Sessao(timeout_s=timeout_s, http=http)
        r = sessao.get("products", [("select", "id"), ("limit", "1")])
    except ErroBanco as e:
        return {"configurado": True, "ok": False, "status_http": e.status, "mensagem": str(e)}
    status = int(r.status_code)
    linhas = _json(r) if 200 <= status < 300 else None
    if 200 <= status < 300 and isinstance(linhas, list) and linhas:
        return {"configurado": True, "ok": True, "status_http": status, "mensagem": "Login e leitura do estoque ok."}
    if 200 <= status < 300:
        return {"configurado": True, "ok": False, "status_http": status,
                "mensagem": "Login ok, mas a leitura veio vazia: o usuário não enxerga os produtos (RLS)."}
    if status == 404:
        return {"configurado": True, "ok": False, "status_http": status,
                "mensagem": "Endereço não encontrado: confira SUPABASE_URL no .env."}
    return {"configurado": True, "ok": False, "status_http": status, "mensagem": f"O Supabase respondeu {status}."}
