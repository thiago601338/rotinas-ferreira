# PC do usuário: instalação, vigia e fila

Decisões e armadilhas do Windows 11 do usuário (V15) para as rotinas. Origem: construção da Fase 1 (25/09/2026); o que
ainda não foi confirmado no PC real está marcado "(a confirmar)".

## Onde fica cada coisa
- Sistema (clone do repositório + `.venv` + `.env`): `C:\Users\V15\Documents\Rotinas Ferreira\sistema\`.
- Fila, logs, registros, trabalho: `C:\Users\V15\Documents\Rotinas Ferreira\` (`config/pastas.json`).
- `instalar.bat` (uma vez, idempotente), `atualizar.bat` (git pull + pip + religa o vigia), `diagnostico.bat`,
  `testar.bat <alvo>` (resultado em `execucoes/` e `git push`).

## Instalação (instalar.bat → `python -m rotinas instalar` → `python -m rotinas verificar`)
- winget instala Git (`Git.Git`, pede UAC), Python 3.12 (`Python.Python.3.12`, escopo do usuário), ffmpeg
  (`Gyan.FFmpeg`) e adb (`Google.PlatformTools`; o `HD-Adb.exe` do BlueStacks é a alternativa).
- Logo depois do winget o PATH da sessão não muda: os programas são procurados pelos caminhos conhecidos
  (`WinGet\Links`, `WinGet\Packages`, `Program Files\Git\cmd`, `Programs\Python\Python312`).
- O `python.exe` da pasta `WindowsApps` (atalho da Microsoft Store) é recusado.
- `.bat` precisam de CRLF: `.gitattributes` tem `*.bat -text` (o arquivo baixado sozinho do GitHub vem como
  está gravado). `chcp 65001` antes de qualquer acento.
- Enquanto a `main` não tiver o código, o instalador roda com o ramo como argumento:
  `instalar.bat claude/fase-1-briefing-x8e3im`.
- `.env` nunca é sobrescrito; o Bloco de Notas abre enquanto `SUPABASE_URL`, `SUPABASE_KEY`, `SUPABASE_EMAIL` ou `SUPABASE_SENHA` estiverem vazios (o estoque só abre para usuário logado: ver `stories.md`, "Como o script lê o estoque").

## Vigia (programa sem janela que executa a fila)
- Inicia no logon: tarefa agendada (PowerShell `Register-ScheduledTask`; se negar, `schtasks /XML`; se negar,
  atalho em Inicializar). O método usado fica em `registros/instalacao.json`. (a confirmar qual funciona sem admin)
- A tarefa agendada precisa de `ExecutionTimeLimit` zero (o padrão de 72 h mata o vigia) e de rodar na bateria
  (é notebook).
- Um vigia só (trava `fila/vigia.lock`). `vigia.vivo` é atualizado a cada ~2 s ocioso e ~30 s durante um pedido.
- Antes de `git pull`/`pip`, parar o vigia (`parar.flag`): no Windows o pip falha ao trocar DLL em uso.

## Fila (detalhes em `fila/README.md`)
- Nunca executa o mesmo id duas vezes; pedido que ficou em `andamento` (vigia caiu) vai para `erro` sem
  reexecutar — em postagem, conferir no Instagram o que já subiu antes de pedir de novo.
- No Windows, antivírus, miniatura do Explorer ou a própria IA lendo pela pasta montada seguram arquivos por
  instantes: toda troca de arquivo tem novas tentativas; se a pasta do pedido não puder ser movida, ela fica em
  `andamento\<id>\` e o resultado aponta para lá (o pedido não vira "interrompido" por isso).
- ids: letras, números, `.`, `-`, `_`; começam e terminam com letra ou número; nada de `con`, `nul`, `aux`,
  `prn`, `com1`…, `lpt1`… (nomes reservados do Windows).
- Segredos são tirados de cada texto do resultado (não do JSON inteiro, que quebrava o JSON).

## Ciclo de teste (`testar.bat`)
- Grava `execucoes/<aaaa-mm-dd_hhmm>_<alvo>/`, tira segredos de todo arquivo de texto, deixa fora do git vídeo e
  arquivo > 20 MB (ficam em `saida_local/`), commita só a pasta da execução e dá `git push`.
- O repositório é **público**: prints e XML de tela que vão para `execucoes/` ficam visíveis na internet.
- Commits do PC saem como "PC Ferreira Boutique". Push precisa do login do GitHub no Git do PC (Git Credential
  Manager abre o navegador na primeira vez); sem login, `testar.bat enviar` tenta de novo depois.

## Atualização com commit local (auditoria de 25/09/2026)
- `atualizar.bat`/`instalar.bat`: se o `git pull --ff-only` falha (ex.: execução do `testar.bat` que ficou só no PC), tentam `git pull --rebase --autostash`; se o rebase falha, desfazem (`git rebase --abort`) e pedem `testar.bat enviar` e depois o `atualizar.bat` de novo.
- Arquivo do sistema mudado à mão que bate com a versão nova: o código é atualizado, o arquivo fica como no GitHub e a mudança à mão vai para o `git stash` (FALHOU com "mande esta tela para a IA"). A IA leva o ajuste para o repositório; não pedir `git stash pop`.
- O vigia relê `config/*.json` a cada pedido: mudança de config vale no pedido seguinte, sem reiniciar.
