import base64
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from rotinas import config, fila, instalacao
from rotinas.instalacao import Saida

RAIZ = Path(__file__).resolve().parent.parent


class Gravador:
    """Troca ``instalacao.executar``: guarda cada comando e responde conforme ``regra``."""

    def __init__(self, regra=None):
        self.chamadas: list[list[str]] = []
        self.regra = regra or (lambda cmd: Saida(0, "ok"))

    def __call__(self, cmd, timeout=120, mostrar=False):
        cmd = [str(c) for c in cmd]
        self.chamadas.append(cmd)
        return self.regra(cmd)


def script_ps(cmd: list[str]) -> str:
    return base64.b64decode(cmd[cmd.index("-EncodedCommand") + 1]).decode("utf-16-le")


def tipo_chamada(cmd: list[str]) -> str:
    if "-EncodedCommand" in cmd:
        s = script_ps(cmd)
        if "Register-ScheduledTask" in s:
            return "tarefa-powershell"
        if "WScript.Shell" in s:
            return "atalho"
        return "powershell"
    if cmd[0] == "schtasks":
        return "schtasks-" + cmd[1].lstrip("/").lower()
    return Path(cmd[0]).name


@pytest.fixture
def windows(cfg, monkeypatch, tmp_path):
    """Finge Windows: nada de verdade é chamado (executar e iniciar_destacado viram mock)."""
    monkeypatch.setattr(instalacao, "NO_WINDOWS", True)
    inicializar = tmp_path / "Startup"
    cfg.alterar("instalacao", pasta_inicializar=str(inicializar))
    iniciados = []
    monkeypatch.setattr(instalacao, "iniciar_destacado", lambda cmd, cwd=None: iniciados.append([str(c) for c in cmd]) or 4321)
    g = Gravador()
    monkeypatch.setattr(instalacao, "executar", g)
    cfg.iniciados = iniciados
    cfg.gravador = g
    cfg.lnk = inicializar / "Rotinas Ferreira - Vigia.lnk"
    return cfg


# ------------------------------------------------------------ registro do vigia

def test_registro_do_vigia_tenta_na_ordem_ate_o_atalho(windows):
    xmls = []

    def regra(cmd):
        tipo = tipo_chamada(cmd)
        if tipo == "schtasks-create":
            xmls.append(Path(cmd[cmd.index("/XML") + 1]).read_bytes().decode("utf-16"))
            return Saida(1, "ERRO: Acesso negado.")
        if tipo == "atalho":
            windows.lnk.parent.mkdir(parents=True, exist_ok=True)
            windows.lnk.write_bytes(b"lnk")
            return Saida(0, "ok")
        return Saida(1, "ERRO: Acesso negado.")

    windows.gravador.regra = regra
    passo = instalacao.passo_registrar_vigia()
    assert passo.estado == instalacao.OK
    assert passo.extra["vigia_registro"] == "atalho"
    assert [tipo_chamada(c) for c in windows.gravador.chamadas] == ["tarefa-powershell", "schtasks-create", "atalho"]

    tarefa = script_ps(windows.gravador.chamadas[0])
    for trecho in ("New-ScheduledTaskTrigger -AtLogOn -User $usuario", "-RunLevel Limited",
                   "-ExecutionTimeLimit ([TimeSpan]::Zero)", "-AllowStartIfOnBatteries", "-DontStopIfGoingOnBatteries",
                   "-MultipleInstances IgnoreNew", f"-WorkingDirectory '{config.RAIZ}'", "vigia.pyw",
                   "-TaskName 'Rotinas Ferreira - Vigia'", "-Force"):
        assert trecho in tarefa, trecho

    xml = xmls[0]
    for trecho in ("<LogonTrigger>", "<ExecutionTimeLimit>PT0S</ExecutionTimeLimit>",
                   "<DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>",
                   "<StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>",
                   "<MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>",
                   "<RunLevel>LeastPrivilege</RunLevel>", f"<WorkingDirectory>{config.RAIZ}</WorkingDirectory>"):
        assert trecho in xml, trecho
    cmd_schtasks = windows.gravador.chamadas[1]
    assert cmd_schtasks[cmd_schtasks.index("/TN") + 1] == "Rotinas Ferreira - Vigia" and "/F" in cmd_schtasks
    assert not Path(cmd_schtasks[cmd_schtasks.index("/XML") + 1]).exists()  # XML temporário apagado

    atalho = script_ps(windows.gravador.chamadas[2])
    assert str(windows.lnk) in atalho and "WindowStyle = 7" in atalho and "vigia.pyw" in atalho


def test_registro_do_vigia_para_na_primeira_que_funciona_e_tira_atalho_antigo(windows):
    windows.lnk.parent.mkdir(parents=True)
    windows.lnk.write_bytes(b"atalho de uma instalacao antiga")
    passo = instalacao.passo_registrar_vigia()
    assert passo.estado == instalacao.OK and passo.extra["vigia_registro"] == "tarefa-powershell"
    assert [tipo_chamada(c) for c in windows.gravador.chamadas] == ["tarefa-powershell"]
    assert not windows.lnk.exists()


def test_registro_do_vigia_cai_no_schtasks(windows):
    windows.gravador.regra = lambda cmd: Saida(0, "ÊXITO") if tipo_chamada(cmd) == "schtasks-create" else Saida(1, "negado")
    passo = instalacao.passo_registrar_vigia()
    assert passo.extra["vigia_registro"] == "tarefa-schtasks"
    assert [tipo_chamada(c) for c in windows.gravador.chamadas] == ["tarefa-powershell", "schtasks-create"]


def test_registro_do_vigia_tudo_falha_diz_o_motivo_de_cada(windows):
    windows.gravador.regra = lambda cmd: Saida(1, "Acesso negado")
    passo = instalacao.passo_registrar_vigia()
    assert passo.estado == instalacao.FALHOU
    assert "PowerShell" in passo.detalhe and "schtasks" in passo.detalhe and "Inicializar" in passo.detalhe


def test_registro_do_vigia_erro_numa_tentativa_nao_impede_a_seguinte(windows, monkeypatch):
    def quebra(*a):
        raise OSError("sem pasta temporária")

    monkeypatch.setattr(instalacao, "_registrar_tarefa_schtasks", quebra)

    def regra(cmd):
        if tipo_chamada(cmd) == "atalho":
            windows.lnk.parent.mkdir(parents=True, exist_ok=True)
            windows.lnk.write_bytes(b"lnk")
            return Saida(0, "ok")
        return Saida(1, "negado")

    windows.gravador.regra = regra
    passo = instalacao.passo_registrar_vigia()
    assert passo.estado == instalacao.OK and passo.extra["vigia_registro"] == "atalho"


def test_registro_do_vigia_fora_do_windows_nao_chama_nada(cfg, monkeypatch):
    monkeypatch.setattr(instalacao, "NO_WINDOWS", False)
    g = Gravador()
    monkeypatch.setattr(instalacao, "executar", g)
    assert instalacao.passo_registrar_vigia().estado == instalacao.PULADO
    assert g.chamadas == []


def test_texto_powershell_escapa_aspas():
    assert instalacao._ps_texto("C:\\Users\\O'Neil\\x") == "'C:\\Users\\O''Neil\\x'"


def test_executar_de_verdade_nunca_levanta(tmp_path):
    assert instalacao.executar([sys.executable, "-c", "print('oi')"]) == Saida(0, "oi")
    ruim = instalacao.executar([str(tmp_path / "nao-existe.exe")])
    assert ruim.codigo == -1 and ruim.texto


def test_iniciar_destacado_de_verdade_nao_espera(tmp_path):
    marca = tmp_path / "marca.txt"
    inicio = time.monotonic()
    pid = instalacao.iniciar_destacado(
        [sys.executable, "-c", f"import time, pathlib; time.sleep(0.3); pathlib.Path({str(marca)!r}).write_text('ok')"],
        cwd=tmp_path,
    )
    assert pid and time.monotonic() - inicio < 0.3
    for _ in range(100):
        if marca.exists():
            break
        time.sleep(0.05)
    assert marca.read_text() == "ok"
    assert instalacao.iniciar_destacado([str(tmp_path / "nao-existe.exe")]) is None


# ------------------------------------------------------------ .env

def test_env_existente_nunca_e_sobrescrito(windows):
    env = config.caminho_env()
    antes = env.read_bytes()
    passo = instalacao.passo_env(abrir=True)
    assert passo.estado == instalacao.OK and "não mexi" in passo.detalhe
    assert env.read_bytes() == antes
    assert windows.iniciados == []  # já preenchido: não abre o Bloco de Notas


def test_env_criado_do_exemplo_e_aberto_no_bloco_de_notas(windows, tmp_path, monkeypatch):
    env = tmp_path / "novo" / ".env"
    env.parent.mkdir()
    monkeypatch.setenv("ROTINAS_ENV", str(env))
    passo = instalacao.passo_env(abrir=True)
    assert env.read_bytes() == (RAIZ / ".env.example").read_bytes()
    assert "criado" in passo.detalhe and "SUPABASE_EMAIL" in passo.detalhe and "SUPABASE_URL" not in passo.detalhe  # URL já vem preenchida
    assert windows.iniciados == [["notepad.exe", str(env)]]

    env.write_text("SUPABASE_URL=https://x.supabase.co\nSUPABASE_KEY=chave-do-usuario-123\n", encoding="utf-8")
    instalacao.passo_env(abrir=True)  # falta o usuário das rotinas: abre de novo
    assert len(windows.iniciados) == 2
    env.write_text("SUPABASE_URL=https://x.supabase.co\nSUPABASE_KEY=chave-do-usuario-123\n"
                   "SUPABASE_EMAIL=rotinas@loja.com\nSUPABASE_SENHA=senha-123456\n", encoding="utf-8")
    instalacao.passo_env(abrir=True)
    assert "chave-do-usuario-123" in env.read_text(encoding="utf-8")
    assert len(windows.iniciados) == 2


# ------------------------------------------------------------ pastas

def test_pastas_de_trabalho_criadas_e_idempotentes(cfg):
    primeiro = instalacao.passo_pastas()
    assert primeiro.estado == instalacao.OK
    p = cfg.p
    for q in [p.fila / e for e in ("pendente", "andamento", "feito", "erro")] + [
        p.logs, p.registros, p.rotinas / "stories", p.videos / "bruto", p.videos / "exportado",
        p.videos / "trabalho", p.backups,
    ]:
        assert q.is_dir(), q
    marcador = p.registros / "postados.csv"
    marcador.write_text("data,letra\n", encoding="utf-8")
    segundo = instalacao.passo_pastas()
    assert segundo.estado == instalacao.OK and segundo.detalhe.startswith("0 criada")
    assert marcador.read_text(encoding="utf-8") == "data,letra\n"


# ------------------------------------------------------------ ffmpeg, adb, git

def test_ffmpeg_instala_pelo_winget_quando_falta(windows, monkeypatch):
    instalado = {"sim": False}

    def localizar(nome, candidatos=None):
        if nome == "winget":
            return "C:/winget.exe"
        if nome in ("ffmpeg", "ffprobe") and instalado["sim"]:
            return f"C:/ff/{nome}.exe"
        return None

    def regra(cmd):
        instalado["sim"] = True
        return Saida(0)

    monkeypatch.setattr(instalacao.ferramentas, "localizar", localizar)
    windows.gravador.regra = regra
    passo = instalacao.passo_ffmpeg()
    assert passo.estado == instalacao.OK and "winget" in passo.detalhe
    (cmd,) = windows.gravador.chamadas
    assert cmd[:5] == ["C:/winget.exe", "install", "-e", "--id", "Gyan.FFmpeg"]
    assert {"--accept-source-agreements", "--accept-package-agreements", "--silent"} <= set(cmd)


def test_ffmpeg_ja_instalado_nao_chama_winget(windows, monkeypatch):
    monkeypatch.setattr(instalacao.ferramentas, "localizar", lambda n, c=None: f"C:/ff/{n}.exe")
    assert instalacao.passo_ffmpeg().estado == instalacao.OK
    assert windows.gravador.chamadas == []


def test_adb_do_bluestacks_serve_e_fica_registrado(windows, monkeypatch):
    hd = r"C:\Program Files\BlueStacks_nxt\HD-Adb.exe"
    vistos = []

    def localizar(nome, candidatos=None):
        vistos.append(list(candidatos or []))
        return hd if nome == "adb" else None

    monkeypatch.setattr(instalacao.ferramentas, "localizar", localizar)
    passo = instalacao.passo_adb()
    assert passo.estado == instalacao.OK and "BlueStacks" in passo.detalhe and passo.extra["adb"] == hd
    assert hd in vistos[0]  # candidatos vêm de config/bluestacks.json
    assert windows.gravador.chamadas == []


def test_adb_ausente_instala_platform_tools(windows, monkeypatch):
    estado = {"instalado": False}
    monkeypatch.setattr(instalacao.ferramentas, "localizar",
                        lambda n, c=None: "C:/winget.exe" if n == "winget" else ("C:/pt/adb.exe" if estado["instalado"] else None))
    windows.gravador.regra = lambda cmd: estado.update(instalado=True) or Saida(0)
    passo = instalacao.passo_adb()
    assert passo.estado == instalacao.OK and "platform-tools" in passo.detalhe
    assert "Google.PlatformTools" in windows.gravador.chamadas[0]


def test_git_so_define_o_que_falta_e_sem_global(windows, monkeypatch):
    monkeypatch.setattr(instalacao.ferramentas, "localizar", lambda n, c=None: "git")

    def regra(cmd):
        if "--get" in cmd:
            return Saida(0, "Fulano") if cmd[-1] == "user.name" else Saida(1, "")
        return Saida(0, "")

    windows.gravador.regra = regra
    passo = instalacao.passo_git()
    assert passo.estado == instalacao.OK and "user.email" in passo.detalhe and "user.name=" not in passo.detalhe
    gravacoes = [c for c in windows.gravador.chamadas if "--get" not in c]
    assert gravacoes == [["git", "-C", str(config.RAIZ), "config", "--local", "user.email",
                          "pc-ferreira@users.noreply.github.com"]]
    assert not any("--global" in c for c in windows.gravador.chamadas)


# ------------------------------------------------------------ cli_instalar

def test_instalar_nunca_aborta_no_primeiro_erro(windows, monkeypatch, capsys):
    chamados = []

    def ok(nome):
        return lambda *a, **k: chamados.append(nome) or instalacao.Passo(instalacao.OK, nome)

    def quebra(*a, **k):
        raise RuntimeError("winget sumiu")

    monkeypatch.setattr(instalacao, "passo_ffmpeg", quebra)
    for nome in ("passo_adb", "passo_pastas", "passo_env", "passo_git", "passo_registrar_vigia", "passo_iniciar_vigia"):
        monkeypatch.setattr(instalacao, nome, ok(nome))
    codigo = instalacao.cli_instalar([])
    saida = capsys.readouterr().out
    assert codigo == 1
    assert chamados == ["passo_adb", "passo_pastas", "passo_env", "passo_git", "passo_registrar_vigia", "passo_iniciar_vigia"]
    assert "FALHOU: erro inesperado: RuntimeError: winget sumiu" in saida
    assert saida.count("OK:") == 6
    registro_json = json.loads((windows.p.registros / "instalacao.json").read_text(encoding="utf-8"))
    assert [p["estado"] for p in registro_json["passos"]] == ["falhou"] + ["ok"] * 6


# ------------------------------------------------------------ vigia: iniciar / parar

def test_iniciar_vigia_apaga_flag_antigo_e_espera_sinal_de_vida(windows, monkeypatch):
    raiz = fila.preparar_pastas()
    (raiz / "parar.flag").write_text("sobra", encoding="utf-8")

    def iniciar(cmd, cwd=None):
        assert not (raiz / "parar.flag").exists()
        (raiz / "vigia.vivo").write_text("{}", encoding="utf-8")
        windows.iniciados.append([str(c) for c in cmd])
        return 999

    monkeypatch.setattr(instalacao, "iniciar_destacado", iniciar)
    passo = instalacao.passo_iniciar_vigia(espera_s=2)
    assert passo.estado == instalacao.OK and passo.extra["pid"] == 999
    assert windows.iniciados[0][-1] == str(config.RAIZ / "vigia.pyw")


def test_iniciar_vigia_nao_duplica_se_ja_roda(windows):
    raiz = fila.preparar_pastas()
    trava = fila.Trava(raiz / "vigia.lock")
    assert trava.adquirir()
    try:
        assert instalacao.passo_iniciar_vigia(espera_s=1).detalhe == "já estava rodando"
        assert windows.iniciados == []
    finally:
        trava.liberar()


def test_iniciar_vigia_sem_sinal_de_vida_falha(windows):
    fila.preparar_pastas()
    passo = instalacao.passo_iniciar_vigia(espera_s=0.6)
    assert passo.estado == instalacao.FALHOU and "sinal de vida" in passo.detalhe


def test_iniciar_vigia_ocupado_com_pedido_sem_sinal_de_vida_conta_como_iniciado(windows, monkeypatch):
    # Pedido pendente na fila: o vigia pega a trava e trabalha antes do primeiro sinal de vida.
    raiz = fila.preparar_pastas()
    trava = fila.Trava(raiz / "vigia.lock")

    def iniciar(cmd, cwd=None):
        assert trava.adquirir()
        return 777

    monkeypatch.setattr(instalacao, "iniciar_destacado", iniciar)
    try:
        passo = instalacao.passo_iniciar_vigia(espera_s=0.6)
    finally:
        trava.liberar()
    assert passo.estado == instalacao.OK and "executando um pedido" in passo.detalhe


def test_parar_vigia_sem_vigia_nao_grava_flag(cfg, capsys):
    raiz = fila.preparar_pastas()
    assert instalacao.parar_vigia(1) == 0
    assert not (raiz / "parar.flag").exists()
    assert "não está rodando" in capsys.readouterr().out


def test_parar_vigia_espera_sair(cfg):
    raiz = fila.preparar_pastas()
    trava = fila.Trava(raiz / "vigia.lock")
    assert trava.adquirir()
    visto = {}

    def vigia_falso():
        for _ in range(50):
            if (raiz / "parar.flag").exists():
                visto["flag"] = True
                (raiz / "parar.flag").unlink()
                break
            time.sleep(0.05)
        trava.liberar()

    t = threading.Thread(target=vigia_falso)
    t.start()
    try:
        assert instalacao.parar_vigia(5) == 0
    finally:
        t.join()
    assert visto.get("flag") and not (raiz / "parar.flag").exists()


def test_parar_vigia_ocupado_devolve_3_e_nao_deixa_flag(cfg, capsys):
    raiz = fila.preparar_pastas()
    trava = fila.Trava(raiz / "vigia.lock")
    assert trava.adquirir()
    try:
        assert instalacao.parar_vigia(0.6) == 3
    finally:
        trava.liberar()
    assert not (raiz / "parar.flag").exists()
    assert "rode de novo" in capsys.readouterr().out


# ------------------------------------------------------------ verificar

@pytest.fixture
def sem_rede(monkeypatch, supabase_falso):
    monkeypatch.setattr(instalacao, "_importavel", lambda m: (True, "1.0"))
    return supabase_falso


def test_verificar_json_sem_segredo_e_codigo_de_saida(cfg, sem_rede, capsys):
    instalacao.passo_pastas()
    codigo = instalacao.cli_verificar(["--json"])
    saida = capsys.readouterr().out
    assert cfg.segredo not in saida
    assert "exemplo.supabase.co" not in saida
    dados = json.loads(saida)
    itens = {i["chave"]: i for i in dados["itens"]}
    assert itens["env:SUPABASE_URL"]["detalhe"] == "preenchido"
    assert itens["env:SUPABASE_KEY"]["detalhe"] == "preenchido"
    assert itens["env:SUPABASE_EMAIL"]["detalhe"] == "preenchido" and itens["env:SUPABASE_SENHA"]["detalhe"] == "preenchido"
    assert cfg.senha not in saida
    assert itens["supabase"] == {"chave": "supabase", "nome": "Supabase (leitura)", "estado": "ok",
                                 "detalhe": "Login e leitura do estoque ok.", "acao": ""}
    assert itens["pastas"]["estado"] == "ok"
    # fora do Windows: itens do Windows não contam como problema
    assert itens["vigia_registrado"]["estado"] == "na" and itens["vigia_vivo"]["estado"] == "na"
    falhas = [i for i in dados["itens"] if i["estado"] == "falha"]
    assert codigo == dados["resumo"]["falhas"] == len(falhas)
    assert all(i["acao"] for i in falhas)


def test_verificar_supabase_so_le_id_nunca_cost_price(cfg, sem_rede, capsys):
    instalacao.cli_verificar(["--json"])
    capsys.readouterr()
    (leitura,) = sem_rede.gets
    assert leitura["url"] == "https://exemplo.supabase.co/rest/v1/products"
    assert leitura["params"] == [("select", "id"), ("limit", "1")]
    assert "cost_price" not in str(leitura) and "*" not in str(leitura["params"])
    assert leitura["headers"]["apikey"] == cfg.segredo and leitura["headers"]["Authorization"] == f"Bearer {cfg.token}"


def test_verificar_supabase_chave_recusada(cfg, supabase_falso):
    from conftest import RespostaFalsa

    supabase_falso.login = RespostaFalsa(401, {"message": "Invalid API key"})
    (item,) = instalacao._v_supabase()
    assert item.estado == "falha" and "SUPABASE_KEY" in item.detalhe and "SUPABASE_KEY" in item.acao


def test_verificar_supabase_sem_conexao_mostra_so_o_tipo_do_erro(cfg, monkeypatch):
    import requests

    def quebra(*a, **k):
        raise requests.ConnectionError(f"falhou com apikey={cfg.segredo}")

    monkeypatch.setattr(requests, "post", quebra)
    (item,) = instalacao._v_supabase()
    assert item.estado == "falha" and "Sem conexão" in item.detalhe and cfg.segredo not in item.detalhe


def test_verificar_env_vazio_nao_testa_conexao(cfg, sem_rede, tmp_path, monkeypatch, capsys):
    env = tmp_path / "vazio.env"
    env.write_text((RAIZ / ".env.example").read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setenv("ROTINAS_ENV", str(env))
    codigo = instalacao.cli_verificar(["--json"])
    dados = json.loads(capsys.readouterr().out)
    itens = {i["chave"]: i for i in dados["itens"]}
    assert itens["env:SUPABASE_KEY"]["detalhe"] == "vazio" and itens["env:SUPABASE_KEY"]["estado"] == "falha"
    assert itens["supabase"]["estado"] == "falha"
    assert sem_rede.posts == [] and sem_rede.gets == []
    assert codigo == dados["resumo"]["falhas"] >= 3


def test_verificar_tabela_tem_simbolos_e_o_que_fazer(cfg, sem_rede, monkeypatch, capsys):
    monkeypatch.setattr(instalacao, "_importavel", lambda m: (m != "uiautomator2", "ModuleNotFoundError: x"))
    codigo = instalacao.cli_verificar([])
    saida = capsys.readouterr().out
    assert "\x1b[" not in saida  # sem cores fora do terminal
    assert "✓" in saida and "✗ pacote uiautomator2" in saida
    assert saida.count("✗") - 1 == codigo  # a linha do resumo também tem um ✗
    assert saida.count("O que fazer:") == codigo
    assert "preenchido" in saida and cfg.segredo not in saida


def test_verificar_no_windows_vigia_registrado_e_vivo(windows, sem_rede, capsys):
    raiz = fila.preparar_pastas()
    (raiz / "vigia.vivo").write_text(json.dumps({"estado": "ocioso"}), encoding="utf-8")
    trava = fila.Trava(raiz / "vigia.lock")
    assert trava.adquirir()
    try:
        windows.gravador.regra = lambda cmd: Saida(0, "") if tipo_chamada(cmd) == "schtasks-query" else Saida(1, "")
        instalacao.cli_verificar(["--json"])
    finally:
        trava.liberar()
    itens = {i["chave"]: i for i in json.loads(capsys.readouterr().out)["itens"]}
    assert itens["vigia_registrado"]["estado"] == "ok" and "tarefa agendada" in itens["vigia_registrado"]["detalhe"]
    assert itens["vigia_vivo"]["estado"] == "ok"


def test_verificar_no_windows_vigia_parado_e_sem_registro(windows, sem_rede, capsys):
    raiz = fila.preparar_pastas()
    vivo = raiz / "vigia.vivo"
    vivo.write_text("{}", encoding="utf-8")
    antigo = time.time() - 3600
    import os

    os.utime(vivo, (antigo, antigo))
    windows.gravador.regra = lambda cmd: Saida(1, "")
    instalacao.cli_verificar(["--json"])
    itens = {i["chave"]: i for i in json.loads(capsys.readouterr().out)["itens"]}
    assert itens["vigia_registrado"]["estado"] == "falha" and itens["vigia_registrado"]["acao"]
    assert itens["vigia_vivo"]["estado"] == "falha" and "parado" in itens["vigia_vivo"]["detalhe"]
    assert "--iniciar-vigia" in itens["vigia_vivo"]["acao"]


def test_verificar_com_config_quebrada_nao_explode(cfg, sem_rede, capsys):
    (cfg.dir / "pastas.json").write_text("{", encoding="utf-8")
    config.limpar_cache()
    codigo = instalacao.cli_verificar(["--json"])
    dados = json.loads(capsys.readouterr().out)
    assert codigo == dados["resumo"]["falhas"] >= 1
    assert any("erro ao conferir" in i["detalhe"] for i in dados["itens"])


def test_verificar_de_verdade_nao_quebra(cfg, supabase_falso, capsys):
    """Sem mocks (só a rede do Supabase é falsa): roda na nuvem e devolve um número."""
    codigo = instalacao.cli_verificar([])
    assert isinstance(codigo, int) and "Verificação da instalação" in capsys.readouterr().out


def test_verificar_json_fica_limpo_mesmo_se_uma_biblioteca_imprimir(cfg, sem_rede, monkeypatch, capsys):
    def barulhento(modulo):
        print(f"aviso da biblioteca {modulo}")
        return True, "1.0"

    monkeypatch.setattr(instalacao, "_importavel", barulhento)
    instalacao.cli_verificar(["--json"])
    saida = capsys.readouterr()
    assert json.loads(saida.out)["itens"]
    assert "aviso da biblioteca" in saida.err


# ------------------------------------------------------------ vigia.pyw

def _rodar_como_pythonw(env_extra: dict, tmp_path: Path) -> subprocess.CompletedProcess:
    codigo = (
        "import runpy, sys; sys.stdout = None; sys.stderr = None; "
        f"runpy.run_path({str(RAIZ / 'vigia.pyw')!r}, run_name='__main__')"
    )
    import os

    env = dict(os.environ, **env_extra)
    return subprocess.run([sys.executable, "-c", codigo], env=env, cwd=tmp_path, capture_output=True, timeout=60)


def test_vigia_pyw_roda_sem_console_e_obedece_parar_flag(cfg, tmp_path):
    raiz = fila.preparar_pastas()
    (raiz / "parar.flag").write_text("", encoding="utf-8")
    r = _rodar_como_pythonw({}, tmp_path)
    assert r.returncode == 0, r.stderr
    assert (raiz / "vigia.vivo").exists()
    assert not (raiz / "parar.flag").exists()


def test_vigia_pyw_registra_falha_na_partida(tmp_path):
    vazia = tmp_path / "config_vazia"
    vazia.mkdir()
    temp = tmp_path / "temp"
    temp.mkdir()
    r = _rodar_como_pythonw({"ROTINAS_CONFIG_DIR": str(vazia), "TMPDIR": str(temp), "TEMP": str(temp)}, tmp_path)
    assert r.returncode == 1
    texto = (temp / "vigia-falha.txt").read_text(encoding="utf-8")
    assert "ErroConfig" in texto


# ------------------------------------------------------------ .bat (conferência estática)

@pytest.mark.parametrize("nome", ["instalar.bat", "atualizar.bat", "diagnostico.bat", "testar.bat"])
def test_bat_crlf_sem_bom_e_rotulos_existem(nome):
    dados = (RAIZ / nome).read_bytes()
    assert not dados.startswith(b"\xef\xbb\xbf"), "BOM quebra a primeira linha no cmd"
    assert dados.count(b"\n") == dados.count(b"\r\n"), "o cmd precisa de CRLF (goto/call falham com LF)"
    antes_do_chcp = dados.split(b"chcp 65001", 1)[0]
    assert all(b < 128 for b in antes_do_chcp), "acento antes do chcp 65001 sai quebrado"
    texto = "\n".join(linha for linha in dados.decode("utf-8").splitlines()
                      if not linha.strip().lower().startswith("rem"))  # comentários não contam
    rotulos = {m.lower() for m in re.findall(r"(?m)^:([A-Za-z_][\w]*)", texto)}
    usados = {m.lower() for m in re.findall(r"(?i)\bgoto\s+:?([A-Za-z_]\w*)", texto)}
    usados |= {m.lower() for m in re.findall(r"(?i)\bcall\s+:([A-Za-z_]\w*)", texto)}
    usados -= {"eof"}
    assert usados <= rotulos, f"rótulos inexistentes: {usados - rotulos}"
    assert "EnableDelayedExpansion" not in texto  # o fluxo não usa variável definida dentro de bloco
    assert not re.search(r"(?m)^\s*if .*\($", texto), "sem blocos if ( ... ): use goto"


def test_bat_fica_com_crlf_no_repositorio():
    # Sem isto, um commit feito no Windows (core.autocrlf) normaliza o .bat para LF e o instalar.bat
    # baixado sozinho do GitHub chega com LF.
    atributos = (RAIZ / ".gitattributes").read_text(encoding="utf-8")
    assert re.search(r"(?m)^\*\.bat\s+-text\b", atributos)


def test_instalar_bat_recusa_python_da_pasta_windowsapps():
    texto = (RAIZ / "instalar.bat").read_text(encoding="utf-8")
    sub = texto.split(":testar_python", 2)[2]
    assert sub.index("\\WindowsApps\\") < sub.index('set "PY=%~1"')


def test_atualizar_bat_liga_o_vigia_pelo_python():
    texto = (RAIZ / "atualizar.bat").read_text(encoding="utf-8")
    assert "-m rotinas instalar --iniciar-vigia" in texto
    assert "pythonw.exe" not in texto  # o Python escolhe o pythonw e confere o sinal de vida


# ------------------------------------------------------------ .bat: git pull com histórico divergente

PASSO_SEGUINTE = {"atualizar.bat": "dependencias", "instalar.bat": "passo_venv"}


def rodar_trecho_do_pull(nome: str, sistema: Path, env: dict) -> tuple[int, str]:
    """Interpreta, com o git de verdade, o trecho do .bat que vai do ``pull --ff-only`` até o passo seguinte.

    Entende só o que o trecho usa (rótulo, rem, echo, goto, ``if errorlevel 1``, ``set /a FALHAS+=1`` e
    ``"%GIT%" -C "%SISTEMA%" ...``); qualquer outra linha faz o teste falhar, para não aprovar sintaxe que
    ele não confere. Devolve (FALHAS, saída).
    """
    linhas = (RAIZ / nome).read_text(encoding="utf-8").splitlines()
    rotulos = {l[1:].strip().lower(): i for i, l in enumerate(linhas) if l.startswith(":")}
    fim = PASSO_SEGUINTE[nome]
    i = next(i for i, l in enumerate(linhas) if "pull --ff-only" in l)
    nivel, falhas, saida = 0, 0, []
    for _ in range(200):
        linha = linhas[i].strip()
        i += 1
        if linha.startswith(":"):
            if linha[1:].lower() == fim:
                return falhas, "\n".join(saida)
            continue
        if not linha or linha.lower().startswith("rem"):
            continue
        cond = re.fullmatch(r"(?i)if errorlevel 1 (.+)", linha)
        if cond:
            if nivel < 1:
                continue
            linha = cond.group(1)
        if linha.lower().startswith("goto :"):
            alvo = linha[len("goto :"):].lower()
            if alvo == fim:
                return falhas, "\n".join(saida)
            i = rotulos[alvo] + 1
        elif linha.lower().startswith("echo"):
            saida.append(linha[4:].strip())
        elif linha == "set /a FALHAS+=1":
            falhas += 1
        elif m := re.fullmatch(r'"%GIT%" -C "%SISTEMA%" (.+?)(?: >nul 2>&1)?', linha):
            r = subprocess.run(["git", "-C", str(sistema), *m.group(1).split()], env=env,
                               capture_output=True, text=True)
            nivel = r.returncode
            saida.append(r.stdout + r.stderr)
        else:
            raise AssertionError(f"{nome}: linha que o teste não sabe interpretar: {linha}")
    raise AssertionError(f"{nome}: o trecho do pull não chegou a :{fim}")


@pytest.fixture
def clones(tmp_path):
    """``origem`` faz o papel do GitHub; ``pc`` é a pasta do sistema, clonada dela e com identidade local."""
    if not shutil.which("git"):
        pytest.skip("git não instalado")
    global_vazio = tmp_path / "gitconfig"
    global_vazio.write_text("", encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_GLOBAL=str(global_vazio), GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0",
               LC_ALL="C", LANGUAGE="C")

    def git(pasta: Path, *args: str) -> str:
        r = subprocess.run(["git", "-C", str(pasta), "-c", "user.name=T", "-c", "user.email=t@t", *args],
                           env=env, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        return r.stdout.strip()

    origem, pc = tmp_path / "origem", tmp_path / "pc"
    origem.mkdir()
    git(origem, "init", "-q", "-b", "main")
    (origem / "config").mkdir()
    (origem / "config" / "bluestacks.json").write_text('{"v": 1}\n', encoding="utf-8")
    (origem / "leia.txt").write_text("a\n", encoding="utf-8")
    git(origem, "add", ".")
    git(origem, "commit", "-q", "-m", "inicio")
    git(tmp_path, "clone", "-q", str(origem), str(pc))
    git(pc, "config", "--local", "user.name", "PC Ferreira Boutique")  # como o instalacao.passo_git deixa
    git(pc, "config", "--local", "user.email", "pc-ferreira@users.noreply.github.com")

    class Clones:
        pass

    c = Clones()
    c.origem, c.pc, c.env, c.git = origem, pc, env, git

    def commit_execucao_que_nao_subiu():
        pasta = pc / "execucoes" / "20260925-101010_diagnostico"
        pasta.mkdir(parents=True)
        (pasta / "resultado.json").write_text("{}\n", encoding="utf-8")
        git(pc, "add", "execucoes")
        git(pc, "commit", "-q", "-m", "execução do testar.bat")

    def atualizacao_na_nuvem(conteudo='{"v": 2}\n'):
        (origem / "config" / "bluestacks.json").write_text(conteudo, encoding="utf-8")
        git(origem, "commit", "-q", "-am", "seletores novos")

    c.commit_execucao_que_nao_subiu = commit_execucao_que_nao_subiu
    c.atualizacao_na_nuvem = atualizacao_na_nuvem
    return c


def _rebase_em_andamento(pc: Path) -> bool:
    return (pc / ".git" / "rebase-merge").exists() or (pc / ".git" / "rebase-apply").exists()


@pytest.mark.parametrize("nome", ["atualizar.bat", "instalar.bat"])
def test_bat_pull_sem_divergencia_continua_so_com_ff_only(nome, clones):
    clones.atualizacao_na_nuvem()
    falhas, saida = rodar_trecho_do_pull(nome, clones.pc, clones.env)
    assert falhas == 0 and "--rebase" not in saida
    assert clones.git(clones.pc, "rev-parse", "HEAD") == clones.git(clones.origem, "rev-parse", "HEAD")


@pytest.mark.parametrize("nome", ["atualizar.bat", "instalar.bat"])
def test_bat_pull_com_execucao_do_testar_que_nao_subiu_atualiza_por_cima(nome, clones):
    # Achado #7: o testar.bat commitou execucoes/ no PC, o push falhou e a nuvem andou: o --ff-only
    # sozinho parava aqui ("Not possible to fast-forward").
    clones.commit_execucao_que_nao_subiu()
    clones.atualizacao_na_nuvem()
    falhas, saida = rodar_trecho_do_pull(nome, clones.pc, clones.env)
    assert falhas == 0, saida
    assert "OK: código atualizado" in saida
    assert clones.git(clones.pc, "rev-parse", "HEAD~1") == clones.git(clones.origem, "rev-parse", "HEAD")
    assert (clones.pc / "execucoes" / "20260925-101010_diagnostico" / "resultado.json").exists()
    assert (clones.pc / "config" / "bluestacks.json").read_text(encoding="utf-8") == '{"v": 2}\n'
    assert not _rebase_em_andamento(clones.pc)


@pytest.mark.parametrize("nome", ["atualizar.bat", "instalar.bat"])
def test_bat_pull_mudanca_a_mao_que_bate_nao_deixa_marca_de_conflito(nome, clones):
    # O pull --rebase --autostash devolve 0 mesmo quando o stash não volta limpo e deixa
    # <<<<<<< dentro do arquivo: o JSON quebraria em silêncio.
    clones.commit_execucao_que_nao_subiu()
    clones.atualizacao_na_nuvem()
    (clones.pc / "config" / "bluestacks.json").write_text('{"v": "mão"}\n', encoding="utf-8")
    (clones.pc / "leia.txt").write_text("mudado\n", encoding="utf-8")
    falhas, saida = rodar_trecho_do_pull(nome, clones.pc, clones.env)
    assert falhas == 1
    assert "git stash" in saida and "IA" in saida
    assert (clones.pc / "config" / "bluestacks.json").read_text(encoding="utf-8") == '{"v": 2}\n'
    assert clones.git(clones.pc, "ls-files", "-u") == ""
    assert clones.git(clones.pc, "rev-parse", "HEAD~1") == clones.git(clones.origem, "rev-parse", "HEAD")
    guardado = clones.git(clones.pc, "stash", "show", "-p", "stash@{0}")
    assert '"mão"' in guardado and "mudado" in guardado  # nada do que foi feito à mão se perdeu
    assert not _rebase_em_andamento(clones.pc)


@pytest.mark.parametrize("nome", ["atualizar.bat", "instalar.bat"])
def test_bat_pull_rebase_com_conflito_desfaz_e_manda_testar_enviar(nome, clones):
    # Commit local que mexe no mesmo arquivo que a nuvem: o rebase para no meio e tem de ser desfeito.
    (clones.pc / "config" / "bluestacks.json").write_text('{"v": "pc"}\n', encoding="utf-8")
    clones.git(clones.pc, "commit", "-q", "-am", "commit local")
    antes = clones.git(clones.pc, "rev-parse", "HEAD")
    (clones.pc / "leia.txt").write_text("mudado\n", encoding="utf-8")
    clones.atualizacao_na_nuvem()
    falhas, saida = rodar_trecho_do_pull(nome, clones.pc, clones.env)
    assert falhas == 1
    assert "FALHOU: o git pull não funcionou" in saida and "testar.bat enviar" in saida
    assert not _rebase_em_andamento(clones.pc)
    assert clones.git(clones.pc, "rev-parse", "HEAD") == antes
    assert (clones.pc / "leia.txt").read_text(encoding="utf-8") == "mudado\n"  # o autostash voltou
    assert clones.git(clones.pc, "stash", "list") == ""


@pytest.mark.parametrize("nome", ["atualizar.bat", "instalar.bat"])
def test_bat_pull_ordem_dos_comandos_e_mensagem(nome):
    texto = (RAIZ / nome).read_text(encoding="utf-8")
    ordem = ["pull --ff-only", "pull --rebase --autostash", "diff --quiet --diff-filter=U", "reset --merge",
             "rebase --abort", ":pull_falhou"]
    posicoes = [texto.index(p) for p in ordem]
    assert posicoes == sorted(posicoes)
    falhou = texto.split("\n:pull_falhou", 1)[1].split("\ngoto", 1)[0]
    assert "testar.bat enviar" in falhou
    trecho = texto[texto.index("pull --ff-only"):texto.index("\n:pull_falhou")]
    assert "%ERRORLEVEL%" not in trecho.upper()  # só "if errorlevel 1", logo depois do comando do git
