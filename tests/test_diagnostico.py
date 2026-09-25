"""Diagnóstico com adb falso, uiautomator2 falso, BlueStacks.conf falso e pasta do CapCut falsa."""

import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

from rotinas import diagnostico, ferramentas, fila, tarefas
from rotinas.contexto import Contexto

XML_TELA = '<?xml version="1.0"?><hierarchy><node package="com.instagram.android" text="Seu story"/></hierarchy>'
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _cp(cmd, saida="", erro="", codigo=0):
    return subprocess.CompletedProcess([str(c) for c in cmd], codigo, saida, erro)


class PCFalso:
    """Responde como adb, git, reg, ffmpeg e o 'verificar' responderiam no PC."""

    def __init__(self, portas_ok=("127.0.0.1:5556",), instagram=True, falhar=()):
        self.portas_ok = set(portas_ok)
        self.conectados: list[str] = []
        self.instagram = instagram
        self.falhar = set(falhar)
        self.comandos: list[list[str]] = []

    def localizar(self, nome, candidatos=None):
        return None if nome in self.falhar and nome == "adb" else nome

    def rodar(self, cmd, timeout=None, verificar=True, entrada=None, binario=False, cwd=None):
        cmd = [str(c) for c in cmd]
        self.comandos.append(cmd)
        prog = Path(cmd[0]).name
        for f in self.falhar:
            if f == prog or (prog == "adb" and f in " ".join(cmd[1:])):
                raise ferramentas.ErroComando(f"falha simulada em {f}", 1)
        if prog == "adb":
            return self._adb(cmd)
        if prog == "reg":
            return _cp(cmd, "HKEY_LOCAL_MACHINE\\SOFTWARE\\BlueStacks_nxt\n"
                            "    Version    REG_SZ    5.21.580.1019\n"
                            "    UserDefinedDir    REG_SZ    C:\\ProgramData\\BlueStacks_nxt\n"
                            "    UserGuid    REG_SZ    guid-que-nao-interessa\n")
        if prog == "git":
            respostas = {"HEAD": "abc123def456", "--abbrev-ref": "principal", "--porcelain": "", "--format=%ci": "2026-09-25"}
            for chave, valor in respostas.items():
                if chave in cmd:
                    return _cp(cmd, valor + "\n")
            return _cp(cmd, "git version 2.46.0.windows.1\n")
        if prog in ("ffmpeg", "ffprobe"):
            return _cp(cmd, f"{prog} version 7.0 Copyright\n")
        if "verificar" in cmd:
            itens = [{"chave": "ffmpeg", "nome": "ffmpeg", "estado": "ok"}, {"chave": "vigia", "nome": "vigia agendado", "estado": "falha"}]
            return _cp(cmd, json.dumps({"resumo": {"falhas": 1}, "itens": itens}), "", 1)
        return _cp(cmd, "", "comando desconhecido", 1)

    def _adb(self, cmd):
        args = cmd[1:]
        if args[:1] == ["-s"]:
            args = args[2:]
        if args[0] == "version":
            return _cp(cmd, "Android Debug Bridge version 1.0.41\nVersion 35.0.1\n")
        if args[0] == "connect":
            if args[1] in self.portas_ok:
                self.conectados.append(args[1])
                return _cp(cmd, f"connected to {args[1]}\n")
            return _cp(cmd, f"cannot connect to {args[1]}: No connection could be made (10061)\n")
        if args[0] == "devices":
            linhas = ["List of devices attached"] + [f"{s}\tdevice product:Pie64 model:SM_S908E transport_id:1" for s in self.conectados]
            return _cp(cmd, "\n".join(linhas) + "\n\n")
        if args[0] == "pull":
            destino = Path(args[2])
            if args[1].endswith(".xml"):
                destino.write_text(XML_TELA, encoding="utf-8")
            else:
                destino.write_bytes(PNG)
            return _cp(cmd, "1 file pulled\n")
        if args[0] == "shell":
            return self._shell(cmd, args[1])
        return _cp(cmd, "", "?", 1)

    def _shell(self, cmd, c):
        if c.startswith("getprop ro.build.version.release"):
            return _cp(cmd, "9\n")
        if c.startswith("getprop ro.product.model"):
            return _cp(cmd, "SM-S908E\n")
        if c.startswith("wm size"):
            return _cp(cmd, "Physical size: 1080x1920\n")
        if c.startswith("wm density"):
            return _cp(cmd, "Physical density: 240\n")
        if c.startswith("dumpsys package"):
            if not self.instagram:
                return _cp(cmd, "Unable to find package: com.instagram.android\n")
            return _cp(cmd, "Packages:\n    versionCode=372512 minSdk=28 targetSdk=34\n    versionName=350.0.0.44.109\n")
        if c.startswith("ls -l"):
            if "Pictures" in c:
                return _cp(cmd, "total 8\ndrwxrwx--x 2 root sdcard_rw 4096 2026-09-25 10:00 Screenshots\n"
                                "drwxrwx--x 2 root sdcard_rw 4096 2026-09-25 10:00 Rotinas Ferreira\n"
                                "-rw-rw---- 1 root sdcard_rw 10 2026-09-25 10:00 a.jpg\n")
            return _cp(cmd, "drwxrwx--x 2 root sdcard_rw 4096 2026-09-25 10:00 Camera\n")
        if c.startswith("content query"):
            return _cp(cmd, "Row: 0 _id=1\nRow: 1 _id=2\nRow: 2 _id=7\n")
        if c.startswith("monkey"):
            return _cp(cmd, "Events injected: 1\n")
        if c.startswith("uiautomator dump"):
            return _cp(cmd, f"UI hierchary dumped to: {c.split()[-1]}\n")
        if c.startswith(("screencap", "rm -f")):
            return _cp(cmd, "")
        return _cp(cmd, "", "comando shell desconhecido", 1)


class DispositivoU2:
    info = {"productName": "Pie64", "displayWidth": 1080, "displayHeight": 1920}

    def __init__(self, serial):
        self.serial = serial
        self.parado = False

    def dump_hierarchy(self):
        return '<hierarchy><node text="Início" package="com.instagram.android"/></hierarchy>'

    def stop_uiautomator(self):
        self.parado = True


def _foto_da_pasta(pasta: Path) -> dict:
    return {str(p.relative_to(pasta)): (p.stat().st_mtime_ns, p.read_bytes()) for p in sorted(pasta.rglob("*")) if p.is_file()}


@pytest.fixture
def pc(cfg, tmp_path, monkeypatch, supabase_falso):
    conf = tmp_path / "ProgramData" / "bluestacks.conf"
    conf.parent.mkdir(parents=True)
    conf.write_text(
        'bst.enable_adb_access="1"\n'
        'bst.instance.Pie64.status.adb_port="5556"\n'
        'bst.instance.Pie64.adb_port="5556"\n'
        'bst.instance.Pie64.display_name="BlueStacks App Player"\n'
        'bst.version_machine="5.21.580.1019"\n',
        encoding="utf-8",
    )
    cfg.alterar("bluestacks", bluestacks_conf=str(conf), dispositivo_padrao="127.0.0.1:5555")
    cfg.alterar("diagnostico", capcut_max_mb_por_arquivo=0.001, instagram_espera_s=0)

    rasc = cfg.p.capcut_rascunhos
    proj = rasc / "0925"
    (proj / "Resources" / "audio").mkdir(parents=True)
    (proj / "Resources" / "video").mkdir(parents=True)
    conteudo = {"id": "ABC", "duration": 7000000, "fps": 30.0, "canvas_config": {"width": 1080, "height": 1920},
                "platform": {"app_source": "cc", "app_version": "9.5.0", "os": "windows", "device_id": "x"},
                "tracks": [], "materials": {}}
    (proj / "draft_content.json").write_text(json.dumps(conteudo), encoding="utf-8")
    (proj / "draft_info.json").write_bytes(b"\x8a\x13\xfe\x02criptografado" * 4)
    (proj / "draft_meta_info.json").write_text(json.dumps({"draft_name": "0925"}), encoding="utf-8")
    (proj / "Resources" / "audio" / "a.json").write_text("{}", encoding="utf-8")
    (proj / "Resources" / "video" / "cache.bin").write_bytes(b"x" * 3000)
    (rasc / "Outro projeto").mkdir()
    (rasc / "root_meta_info.json").write_text('{"all_draft_store": []}', encoding="utf-8")
    for v in ("9.5.0.2345", "9.4.1.100", "Configs"):
        (cfg.p.capcut_apps / v).mkdir(parents=True)

    for data, n in (("2026-09-22", 3), ("2026-09-23", 1)):
        pasta = cfg.p.stories_fonte / data
        pasta.mkdir(parents=True)
        for i in range(n):
            (pasta / f"A - {i + 1}.jpg").write_bytes(b"jpg")

    falso = PCFalso()
    monkeypatch.setattr(ferramentas, "rodar", falso.rodar)
    monkeypatch.setattr(ferramentas, "localizar", falso.localizar)
    monkeypatch.setattr(diagnostico, "dormir", lambda s: None)
    dispositivos = []

    def conectar_u2(serial):
        d = DispositivoU2(serial)
        dispositivos.append(d)
        return d

    monkeypatch.setitem(sys.modules, "uiautomator2", types.SimpleNamespace(connect=conectar_u2))
    falso.http = supabase_falso
    falso.u2 = dispositivos
    falso.rascunhos = rasc
    return falso


def test_diagnostico_completo(pc, cfg, tmp_path):
    foto_antes = _foto_da_pasta(pc.rascunhos)
    saida = tmp_path / "saida"
    dados = diagnostico.executar(saida)
    assert json.loads((saida / "diagnostico.json").read_text(encoding="utf-8")) == dados

    # nunca mostra segredo nem valor do .env
    for arq in saida.rglob("*"):
        if arq.is_file():
            conteudo = arq.read_bytes()
            assert cfg.segredo.encode() not in conteudo, arq
            assert b"exemplo.supabase.co" not in conteudo, arq
    assert dados["env"]["variaveis"] == {"SUPABASE_KEY": "preenchida", "SUPABASE_URL": "preenchida",
                                         "SUPABASE_EMAIL": "preenchida", "SUPABASE_SENHA": "preenchida"}
    for arq in saida.rglob("*"):
        if arq.is_file():
            assert cfg.senha.encode() not in arq.read_bytes(), arq

    v = dados["versoes"]
    assert v["bluestacks"]["registro"]["Version"] == "5.21.580.1019"
    assert "UserGuid" not in v["bluestacks"]["registro"]
    assert v["capcut"]["mais_recente"] == "9.5.0.2345"
    assert v["repositorio"]["commit"] == "abc123def456"
    if dados["verificar"]["disponivel"]:  # rotinas.instalacao existe nesta versão
        assert dados["verificar"]["codigo"] == 1 and dados["verificar"]["resultado"]["resumo"] == {"falhas": 1}
        assert "O verificar da instalação marcou com falha: vigia agendado." in dados["problemas"]

    pd = dados["pastas"]["stories_fonte"]["pastas_de_data"]
    assert {"nome": "2026-09-22", "arquivos": 3} in pd and {"nome": "2026-09-23", "arquivos": 1} in pd

    b = dados["bluestacks"]
    assert b["ligado"] is True and b["serial"] == "127.0.0.1:5556"
    assert set(b["conexoes"]) == {"127.0.0.1:5555", "127.0.0.1:5556"}
    assert b["conf"]["instancias"]["Pie64"]["status.adb_port"] == "5556"

    a = dados["android"]
    assert a["android_versao"] == "9" and a["modelo"] == "SM-S908E"
    assert a["instagram"]["versao"] == "350.0.0.44.109"
    assert a["tela_inicial"]["xml"]["pacote_na_tela"] == "com.instagram.android"
    assert a["pastas_android"]["/sdcard/Pictures"]["pastas"] == ["Rotinas Ferreira", "Screenshots"]
    assert a["mediastore"] == {"responde": True, "itens": 3}
    assert a["uiautomator2"]["ok"] is True and pc.u2[0].serial == "127.0.0.1:5556" and pc.u2[0].parado
    for nome in ("tela_inicial_instagram.xml", "tela_inicial_instagram.png", "tela_inicial_u2.xml"):
        assert (saida / nome).exists(), nome
    shells = [c for c in pc.comandos if Path(c[0]).name == "adb" and "shell" in c]
    assert all(c[1:3] == ["-s", "127.0.0.1:5556"] for c in shells)
    assert any("monkey -p com.instagram.android" in c[-1] for c in shells)
    assert any('--where "_id>0"' in c[-1] for c in shells)

    c = dados["capcut"]
    assert c["projetos"] == ["0925", "Outro projeto"]
    assert (saida / "capcut_0925" / "draft_content.json").exists()
    assert (saida / "capcut_0925" / "Resources" / "audio" / "a.json").exists()
    assert not (saida / "capcut_0925" / "Resources" / "video" / "cache.bin").exists()
    assert c["copia"]["omitidos"] == [{"arquivo": "Resources/video/cache.bin", "tamanho_mb": 0.0}]
    assert (saida / "capcut_raiz" / "root_meta_info.json").exists()
    arvore = (saida / "arvore_capcut.txt").read_text(encoding="utf-8")
    assert "Resources/video/cache.bin" in arvore and "não copiado" in arvore
    assert c["formato"]["draft_content.json"]["formato"] == "json_aberto"
    assert c["formato"]["draft_content.json"]["platform"] == {"app_source": "cc", "app_version": "9.5.0", "os": "windows"}
    assert c["formato"]["draft_info.json"]["formato"] == "parece_criptografado"
    assert c["formato"]["template-2.tmp"]["formato"] == "ausente"
    assert _foto_da_pasta(pc.rascunhos) == foto_antes  # nada gravado na pasta do CapCut

    s = dados["supabase"]
    assert s == {"configurado": True, "status_http": 200, "ok": True, "mensagem": "Login e leitura do estoque ok."}
    leitura = pc.http.gets[0]
    assert leitura["url"].endswith("/rest/v1/products") and dict(leitura["params"])["select"] == "id"
    assert leitura["headers"]["Authorization"] == f"Bearer {cfg.token}"
    assert "cost_price" not in json.dumps(pc.http.gets, default=str)

    assert any("draft_info.json" in p and "criptografado" in p for p in dados["problemas"])
    texto = (saida / "resumo.txt").read_text(encoding="utf-8")
    assert "ADB do BlueStacks ligado" in texto and "350.0.0.44.109" in texto


def test_item_com_erro_nao_derruba_os_outros(pc, tmp_path, monkeypatch):
    pc.falhar = {"reg", "dumpsys"}

    def u2_quebrado(serial):
        raise RuntimeError("atx-agent não subiu")

    monkeypatch.setitem(sys.modules, "uiautomator2", types.SimpleNamespace(connect=u2_quebrado))
    saida = tmp_path / "saida"
    dados = diagnostico.executar(saida)
    assert "erro" in dados["versoes"]["bluestacks"]["registro"]
    assert "erro" in dados["android"]["instagram"]
    assert "erro" in dados["android"]["uiautomator2"]
    assert dados["android"]["modelo"] == "SM-S908E"
    assert dados["capcut"]["formato"]["draft_content.json"]["formato"] == "json_aberto"
    assert dados["supabase"]["ok"] is True
    assert any("uiautomator2 falhou" in p for p in dados["problemas"])
    assert (saida / "diagnostico.json").exists()


def test_adb_desligado_explica_onde_ligar(pc, cfg, tmp_path):
    conf = Path(json.loads((cfg.dir / "bluestacks.json").read_text(encoding="utf-8"))["bluestacks_conf"])
    conf.write_text('bst.enable_adb_access="0"\nbst.instance.Pie64.status.adb_port="5556"\n', encoding="utf-8")
    pc.portas_ok = set()
    dados = diagnostico.executar(tmp_path / "saida", verificar=False)
    b = dados["bluestacks"]
    assert b["ligado"] is False and b["serial"] is None
    assert "DESLIGADO" in b["mensagem"] and "Avançado" in b["mensagem"] and "Android Debug Bridge" in b["mensagem"]
    assert dados["android"] == {"pulado": "nenhum dispositivo ADB conectado"}
    assert b["mensagem"] in dados["problemas"]
    assert dados["capcut"]["gabarito_encontrado"] is True


def test_sem_adb_segue_com_o_resto(pc, tmp_path):
    pc.falhar = {"adb"}
    dados = diagnostico.executar(tmp_path / "saida", verificar=False)
    assert dados["bluestacks"]["adb"] is None and "Não encontrei o adb" in dados["bluestacks"]["mensagem"]
    assert dados["versoes"]["adb"] == {"encontrado": False}
    assert dados["capcut"]["copia"]["copiados"] == 4


def test_instagram_ausente_nao_abre_nada(pc, tmp_path):
    pc.instagram = False
    dados = diagnostico.executar(tmp_path / "saida", verificar=False)
    assert dados["android"]["tela_inicial"] == {"pulado": "Instagram não encontrado no BlueStacks"}
    assert not any("monkey" in " ".join(c) for c in pc.comandos)
    assert "O Instagram não foi encontrado no BlueStacks." in dados["problemas"]


def test_gabarito_achado_pelo_nome_do_rascunho(pc, cfg, tmp_path):
    (cfg.p.capcut_rascunhos / "0925").rename(cfg.p.capcut_rascunhos / "A1B2C3")
    dados = diagnostico.executar(tmp_path / "saida", verificar=False, u2=False)
    assert dados["capcut"]["gabarito_encontrado"] is True
    assert (tmp_path / "saida" / "capcut_0925" / "draft_content.json").exists()


def test_saida_dentro_do_capcut_e_recusada(pc, cfg):
    foto_antes = _foto_da_pasta(pc.rascunhos)
    with pytest.raises(ValueError):
        diagnostico.executar(cfg.p.capcut_rascunhos / "diag", verificar=False, u2=False, instagram=False)
    assert not (cfg.p.capcut_rascunhos / "diag").exists()
    assert _foto_da_pasta(pc.rascunhos) == foto_antes


def test_supabase_sem_env(cfg, monkeypatch, tmp_path):
    env = tmp_path / "vazio.env"
    env.write_text("SUPABASE_URL=\nSUPABASE_KEY=\n", encoding="utf-8")
    monkeypatch.setenv("ROTINAS_ENV", str(env))
    assert diagnostico.supabase()["configurado"] is False
    e = diagnostico.env()
    assert {k: e["variaveis"][k] for k in ("SUPABASE_KEY", "SUPABASE_URL")} == {"SUPABASE_KEY": "vazia", "SUPABASE_URL": "vazia"}
    assert set(e["variaveis"]) == {"SUPABASE_URL", "SUPABASE_KEY", "SUPABASE_EMAIL", "SUPABASE_SENHA"}


def test_supabase_chave_recusada(cfg, supabase_falso):
    from conftest import RespostaFalsa

    supabase_falso.login = RespostaFalsa(401, {"message": "Invalid API key"})
    s = diagnostico.supabase()
    assert s["ok"] is False and "SUPABASE_KEY" in s["mensagem"] and cfg.senha not in json.dumps(s)


def test_supabase_login_recusado_e_leitura_vazia(cfg, supabase_falso):
    from conftest import RespostaFalsa

    supabase_falso.login = RespostaFalsa(400, {"error_code": "invalid_credentials", "msg": "Invalid login credentials"})
    s = diagnostico.supabase()
    assert s["ok"] is False and "SUPABASE_EMAIL" in s["mensagem"]
    supabase_falso.login = None
    supabase_falso.leituras = [RespostaFalsa(200, [])]  # RLS barrou: 200 com lista vazia não é "ok"
    s = diagnostico.supabase()
    assert s["ok"] is False and "vazia" in s["mensagem"]


def test_formato_rascunho(tmp_path):
    aberto = tmp_path / "a.json"
    aberto.write_bytes(b"\xef\xbb\xbf  " + json.dumps({"version": 360000, "tracks": []}).encode())
    assert diagnostico.formato_rascunho(aberto)["formato"] == "json_aberto"
    fechado = tmp_path / "b.json"
    fechado.write_bytes(b"U2FsdGVkX1+abc" * 10)
    assert diagnostico.formato_rascunho(fechado)["formato"] == "parece_criptografado"
    quebrado = tmp_path / "c.json"
    quebrado.write_text("{ quebrado", encoding="utf-8")
    assert diagnostico.formato_rascunho(quebrado)["formato"] == "json_invalido"


def test_tarefa_da_fila(pc, cfg, monkeypatch):
    raiz = fila.preparar_pastas()
    caminho = fila.criar_pedido("diagnostico", {"u2": False, "supabase": False, "verificar": False})
    fila.Vigia(intervalo_s=0.01).rodar(uma_vez=True)
    res = json.loads((raiz / "feito" / caminho.name).read_text(encoding="utf-8"))
    assert res["estado"] == "feito"
    assert res["resultado"]["android"]["uiautomator2"] == {"pulado": "opção --sem-u2"}
    assert "diagnostico.json" in res["arquivos"] and "tela_inicial_instagram.xml" in res["arquivos"]
    assert cfg.segredo not in json.dumps(res)


def test_tarefa_devolve_o_mesmo_json(pc, tmp_path):
    ctx = Contexto(pasta_saida=tmp_path / "ctx")
    dados = diagnostico.tarefa({"u2": False, "verificar": False}, ctx)
    assert dados == json.loads((tmp_path / "ctx" / "diagnostico.json").read_text(encoding="utf-8"))
    assert tarefas.TAREFAS["diagnostico"] == "rotinas.diagnostico:tarefa"
