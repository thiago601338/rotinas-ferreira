# Rotinas Ferreira

Scripts e skills que automatizam as rotinas de **stories** (BlueStacks) e **edição de vídeo** (CapCut 9.5) da
Ferreira Boutique. A IA (Claude no Cowork) só decide o que exige julgamento; o resto roda no PC, sem IA.

## Instalar (uma vez, no PC Windows 11)
No Prompt de Comando:
```
curl -L -o "%USERPROFILE%\Downloads\instalar.bat" https://raw.githubusercontent.com/thiago601338/rotinas-ferreira/main/instalar.bat && "%USERPROFILE%\Downloads\instalar.bat"
```
(Enquanto o código estiver só no ramo de desenvolvimento, troque `main` por `claude/fase-1-briefing-x8e3im` na URL e
passe o mesmo nome como argumento do `instalar.bat`.)

O instalador instala Git, Python 3.12, ffmpeg e adb (winget), clona o sistema em
`C:\Users\V15\Documents\Rotinas Ferreira\sistema\`, cria a `.venv`, abre o `.env` para preencher
(`SUPABASE_URL`, `SUPABASE_KEY` só leitura), registra o **vigia** para iniciar no logon e termina com uma tabela
✓/✗. Pode rodar de novo quando quiser (pula o que já existe).

| Arquivo (em `sistema\`) | Para quê |
|---|---|
| `atualizar.bat` | baixa a versão nova, atualiza dependências e religa o vigia |
| `diagnostico.bat` | versões, ADB do BlueStacks, tela do Instagram, gabarito do CapCut → envia para `execucoes/` |
| `testar.bat <alvo>` | teste real no PC, resultado em `execucoes/<data_hora>_<alvo>/` enviado pelo git (`testar.bat` sem nada lista os alvos) |

## Como funciona
- **Fila de pedidos:** a IA grava `Rotinas Ferreira\fila\pendente\<id>.json`; o vigia executa e devolve
  `fila\feito\<id>.json` (ou `erro`) com log e prints. Formato: [`fila/README.md`](fila/README.md).
- **Stories:** preparar a pasta do dia → a IA identifica peça e cor pelas folhas de contato → o script corta sem estoque
  e já postado, monta o link `wa.me/...` (sem `https://`) → ensaio no BlueStacks → aprovação → postagem → conferência
  pelo JS. Skill: [`.claude/skills/postar-stories-ferreira`](.claude/skills/postar-stories-ferreira/SKILL.md).
- **Vídeo:** preparar o bruto (tomadas, silêncios, transcrição, batidas) → a IA escolhe receita, tomadas e textos →
  plano validado → rascunho no CapCut → acabamento e exportação → conferência automática do `.mp4`.
  Skill: [`.claude/skills/editar-video-ferreira`](.claude/skills/editar-video-ferreira/SKILL.md).
- Tudo que publica tem **modo ensaio** (padrão) e registra log + prints. Mídia do usuário nunca é sobrescrita.

## Pelo terminal do PC (opcional)
Na pasta `sistema`: `.venv\Scripts\python.exe -m rotinas` lista os comandos (`stories-preparar`, `stories-estoque`,
`stories-montar`, `stories-postar`, `stories-relatorio`, `video-preparar`, `video-receitas`, `video-planejar`,
`video-rascunho`, `video-exportar`, `video-conferir`, `fila`, `vigia`, `verificar`). Cada um tem `--help`.

## Onde está cada coisa
- `rotinas/` código · `config/*.json` pastas, regras e presets · `receitas/` R1–R12 · `tests/` pytest (mídia sintética)
- `conhecimento/` regras e aprendizados (ler antes de mudar qualquer rotina) · `BRIEFING.md` o que construir
- `execucoes/` resultados dos testes no PC (repositório público: não pôr nada sensível)

## Desenvolver
`pip install -r requirements-dev.txt` e `python -m pytest` (precisa de ffmpeg no PATH). Regras do código em
[`CLAUDE.md`](CLAUDE.md).
