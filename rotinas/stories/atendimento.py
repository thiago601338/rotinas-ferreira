"""Associa Stories já publicados às peças, sem publicar ou responder mensagens.

Falhas ficam pendentes em um arquivo sem segredos. Repetir o mesmo corpo é seguro:
atendimento-registrar-stories reconhece o hash do pedido no banco.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import requests

from .. import config


class RegistroPendente(ValueError):
    """Falta informação suficiente para associar os Stories com segurança."""


def _texto(valor) -> str | None:
    return valor.strip() if isinstance(valor, str) and valor.strip() else None


def montar_corpo(letra: dict, publicado_de: str, publicado_ate: str) -> dict:
    nome = str(letra.get("letra") or "").upper()
    if not re.fullmatch(r"[A-Z]{1,2}", nome):
        raise RegistroPendente("letra_invalida")
    try:
        inicio, fim = (datetime.fromisoformat(t.replace("Z", "+00:00")) for t in (publicado_de, publicado_ate))
        if inicio.tzinfo is None or fim.tzinfo is None or fim < inicio or (fim-inicio).total_seconds() > 86400:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise RegistroPendente("janela_invalida") from None
    midias = letra.get("midias")
    if not isinstance(midias, list) or not 1 <= len(midias) <= 100:
        raise RegistroPendente("midias_invalidas")
    varios = letra.get("varios_modelos") is True
    manifesto = []
    for midia in midias:
        if not isinstance(midia, dict):
            raise RegistroPendente("midia_invalida")
        sku, produto = _texto(midia.get("sku")), _texto(midia.get("product_id"))
        if not sku and not produto and not varios:
            sku, produto = _texto(letra.get("sku")), _texto(letra.get("product_id"))
        if not sku and not produto:
            raise RegistroPendente("sku_por_midia_ausente" if varios else "produto_ausente")
        cores = midia.get("cores") or []
        if not isinstance(cores, list):
            raise RegistroPendente("cores_invalidas")
        cores = list(dict.fromkeys(c.strip() for c in cores if isinstance(c, str) and c.strip()))
        # Foto com várias cores identifica a peça inteira, sem inventar uma cor única.
        cor = _texto(midia.get("cor")) or (cores[0] if len(cores) == 1 else None)
        item = {"cor": cor}
        if sku:
            item["sku"] = sku
        if produto:
            item["product_id"] = produto
        if midia.get("story_id") is not None:
            story = str(midia["story_id"])
            if not re.fullmatch(r"\d{5,40}", story):
                raise RegistroPendente("story_id_invalido")
            item["story_id"] = story
        manifesto.append(item)
    corpo = {"letra": nome, "n_midias": len(midias), "publicado_de": publicado_de, "publicado_ate": publicado_ate}
    if not varios and all(item == manifesto[0] for item in manifesto) and "story_id" not in manifesto[0]:
        corpo.update(manifesto[0])
    else:
        # O contrato da Edge usa varios_modelos para o manifesto por arquivo,
        # inclusive quando o mesmo SKU aparece com cores diferentes.
        corpo.update(varios_modelos=True, midias=manifesto)
    return corpo


def _enviar(corpo: dict) -> dict:
    cfg = config.carregar("atendimento")
    if cfg.get("registrar_stories") is not True:
        return {"status": "pendente", "motivo": "integracao_desativada"}
    token = config.segredo("ROTINAS_SEGREDO_ATENDIMENTO") or ""
    if not re.fullmatch(r"[a-f0-9]{64}", token):
        return {"status": "pendente", "motivo": "segredo_nao_configurado"}
    url = str(cfg.get("registrar_stories_url") or "")
    parsed = urlparse(url)
    if (parsed.scheme != "https" or not re.fullmatch(r"[a-z0-9]+\.supabase\.co", parsed.hostname or "")
            or parsed.path != "/functions/v1/atendimento-registrar-stories" or parsed.query or parsed.fragment
            or parsed.username or parsed.password or parsed.port):
        return {"status": "pendente", "motivo": "destino_invalido"}
    try:
        resposta = requests.post(url, json=corpo, headers={"x-ai-followup-token": token},
                                 timeout=(3, 10), allow_redirects=False)
        dados = resposta.json()
    except Exception:  # Nunca registrar corpo HTTP, URL assinada ou exceção com segredo.
        return {"status": "pendente", "motivo": "registro_sem_confirmacao"}
    if (resposta.status_code == 200 and isinstance(dados, dict) and dados.get("ok") is True
            and type(dados.get("registrados")) is int and dados["registrados"] == corpo["n_midias"]):
        return {"status": "registrado", "registrados": dados["registrados"],
                "ja_registrado": dados.get("ja_registrado") is True}
    return {"status": "pendente", "motivo": "http_"+str(resposta.status_code)}


def _gravar(arquivo: Path, registro: dict) -> None:
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    temporario = arquivo.with_suffix(".tmp")
    temporario.write_text(json.dumps(registro, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    temporario.replace(arquivo)


def registrar_letra(letra: dict, publicado_de: str, publicado_ate: str, pasta_saida: Path, *, ensaio=False) -> dict:
    """Melhor esforço após publicação. Nunca lança erro nem tenta publicar novamente."""
    if ensaio:
        return {"status": "ignorado", "motivo": "ensaio"}
    nome = str(letra.get("letra") or "").upper()
    if not re.fullmatch(r"[A-Z]{1,2}", nome):
        return {"status": "pendente", "motivo": "letra_invalida"}
    arquivo = Path(pasta_saida) / f"atendimento_stories_{nome}.json"
    try:
        corpo = montar_corpo(letra, publicado_de, publicado_ate)
    except RegistroPendente as erro:
        return {"status": "pendente", "motivo": str(erro)}
    try:
        # Salvar antes do HTTP permite recuperar o mesmo pedido após interrupção.
        _gravar(arquivo, {"corpo": corpo, "resultado": {"status": "pendente", "motivo": "aguardando_registro"}})
        resultado = _enviar(corpo)
        _gravar(arquivo, {"corpo": corpo, "resultado": resultado})
        return {**resultado, "arquivo": str(arquivo)}
    except Exception:
        return {"status": "pendente", "motivo": "registro_local_indisponivel", "arquivo": str(arquivo)}


def repetir_registro(arquivo: Path) -> dict:
    """Repete somente a associação pelo mesmo corpo; jamais chama o publicador."""
    registro = json.loads(arquivo.read_text(encoding="utf-8"))
    corpo = registro["corpo"]
    if not isinstance(corpo, dict) or not isinstance(corpo.get("n_midias"), int):
        raise ValueError("Arquivo de registro inválido")
    resultado = _enviar(corpo)
    _gravar(arquivo, {"corpo": corpo, "resultado": resultado})
    return resultado


def main() -> int:
    parser = argparse.ArgumentParser(description="Repete só a associação dos Stories já publicados às peças.")
    parser.add_argument("--arquivo", required=True, type=Path)
    args = parser.parse_args()
    try:
        resultado = repetir_registro(args.arquivo)
    except Exception:
        resultado = {"status": "pendente", "motivo": "arquivo_ou_configuracao_invalida"}
    print(json.dumps(resultado, ensure_ascii=False))
    return 0 if resultado["status"] == "registrado" else 1


if __name__ == "__main__":
    raise SystemExit(main())
