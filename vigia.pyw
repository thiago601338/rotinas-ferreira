"""Vigia da fila sem janela: é o que a tarefa agendada (ou o atalho em Inicializar) roda no logon.

Roda com o ``pythonw.exe`` da ``.venv``. Sem console, ``sys.stdout`` e ``sys.stderr`` são ``None``:
aqui eles viram um destino nulo, para nenhuma biblioteca quebrar ao escrever. Um erro na partida
vai para ``logs/vigia-falha.txt`` (ou para a pasta temporária, se nem a config abrir).
"""

from __future__ import annotations

import os
import sys
import tempfile
import traceback
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
os.chdir(RAIZ)
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

for _fluxo in ("stdout", "stderr"):
    if getattr(sys, _fluxo, None) is None:
        setattr(sys, _fluxo, open(os.devnull, "w", encoding="utf-8"))


def _registrar_falha() -> None:
    texto = traceback.format_exc()
    try:
        from rotinas import config, registro

        texto = registro.ocultar(texto)
        pasta = config.pastas().logs
    except Exception:
        pasta = Path(tempfile.gettempdir())
    try:
        pasta.mkdir(parents=True, exist_ok=True)
        with open(pasta / "vigia-falha.txt", "a", encoding="utf-8") as f:
            f.write(f"--- {datetime.now():%Y-%m-%d %H:%M:%S}\n{texto}\n")
    except Exception:
        pass


def main() -> int:
    try:
        from rotinas.fila import cli_vigia

        return int(cli_vigia([]) or 0)
    except Exception:
        _registrar_falha()
        return 1


if __name__ == "__main__":
    sys.exit(main())
