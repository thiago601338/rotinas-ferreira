# Briefing — Fase 1: stories e edição de vídeo

## 1. Objetivo
Hoje as duas rotinas são feitas pela IA clicando na tela do PC do usuário (BlueStacks e CapCut), com um print por passo. É isso que mais consome crédito e tempo. Esta fase entrega:

- **Stories:** tudo o que é mecânico vira script, e os cliques no BlueStacks viram automação direta no emulador (ADB + uiautomator2).
- **Edição de vídeo:** a montagem no CapCut vira rascunho gerado por script a partir de receitas. A IA só escolhe tomadas e textos, e confere o resultado.
- Para cada rotina, uma **skill** curta que diz à IA exatamente quais scripts rodar e o que ela ainda decide.

Qualidade é requisito: as regras de `conhecimento/` valem por inteiro. Nenhuma vira opcional por causa da automação.

## 2. Como a rotina vai rodar depois (alvo)
No dia a dia, quem opera é o Claude no app desktop (Cowork). Ele acessa as pastas do PC por uma VM Linux com as pastas montadas: lê e grava arquivos, mas **não alcança programas do Windows** (BlueStacks/ADB, CapCut). Por isso:

**Ponte por fila de arquivos.** A IA grava um pedido em `C:\Users\V15\Documents\Rotinas Ferreira\fila\pendente\<id>.json`. Um vigia no Windows (tarefa agendada no logon, janela oculta) executa e devolve o resultado (JSON + log + prints) em `fila\feito\` ou `fila\erro\`. Estados: `pendente → andamento → feito | erro`. O vigia nunca executa o mesmo pedido duas vezes. O formato dos pedidos fica documentado em `fila/README.md` com exemplos.

**Stories, rodada típica:**
1. Script prepara a pasta do dia e gera uma folha de contato por letra (uma imagem com todas as mídias da letra, numeradas).
2. A IA olha só as folhas de contato, identifica peça e cor de cada mídia e confere o estoque.
3. Script corta as cores sem estoque, checa "já postado", monta os links e grava o pedido na fila.
4. O vigia posta pelo BlueStacks.
5. A IA confere no Instagram (uma chamada JS no navegador logado, ver `conhecimento/stories.md`) e avisa o usuário: o que subiu, o que ficou de fora e por quê.

**Vídeo, rodada típica:**
1. Script inventaria o bruto, detecta tomadas e silêncios, transcreve a fala, marca as batidas da música e gera folhas de contato.
2. A IA escolhe a receita, as tomadas e os textos, e grava o pedido.
3. Script gera o rascunho no CapCut; a exportação vai pelos atalhos; script confere o arquivo exportado.

## 3. Arquitetura e instalação
- Pastas (configuráveis em `config/pastas.json`):
  - Stories (fonte, sempre): `C:\Users\V15\Documents\Stories da Loja\<data>\`
  - Rotinas (fila, logs, registros): `C:\Users\V15\Documents\Rotinas Ferreira\`
  - Rascunhos do CapCut: `C:\Users\V15\AppData\Local\CapCut\User Data\Projects\com.lveditor.draft\`
  - Vídeos (bruto e exportado): `Rotinas Ferreira\videos\` enquanto o usuário não indicar outra pasta.
- `instalar.bat` (roda uma vez, com duplo clique): Python, Git, ffmpeg, platform-tools (ou o `HD-Adb.exe` do BlueStacks), dependências Python, clone deste repositório, cópia de `.env.example` para `.env` (abre no Bloco de Notas para ele preencher) e registro do vigia. Idempotente, e no fim mostra o que funcionou e o que não funcionou.
- `atualizar.bat`: `git pull` + dependências.
- `.env`: `SUPABASE_URL`, `SUPABASE_KEY` (só leitura) e o que mais surgir.

## 4. Entregável A — Stories
Regras completas em `conhecimento/stories.md`. Módulos:

- **A1. Preparar a pasta do dia.** Receber mídias novas e nomear na próxima letra livre (`A - 1` vídeo, `A - 2`… fotos), sem sobrescrever; agrupar por letra, na ordem certa; converter `.mov` → `.mp4` (H.264/AAC, sem perda visível, arquivo novo); detectar vídeo sem áudio ou em silêncio; gerar a folha de contato de cada letra (quadros do vídeo + fotos, numerados).
- **A2. Estoque.** Consulta de leitura em `products` + `product_variations` (SQL em `conhecimento/stories.md`; filtros `status = 'Ativo'` e `deleted_at is null`). Entrada: o que a IA identificou (SKU ou termo + cor de cada mídia). Saída: mídias aprovadas, mídias cortadas e o motivo. Modelo sem nenhuma peça não entra.
- **A3. Já postado.** Registro próprio (`registros/postados.csv`: data, letra, SKU, cor, arquivo, hash) + varredura das pastas de data. Bloqueia repetição e diz quando e onde a peça saiu.
- **A4. Link e figurinha.** `wa.me/5582988748649?text=<mensagem com o nome da peça>`, **sem `https://`**, com a mensagem codificada para URL; texto da figurinha escolhido entre as variações do `config`. Só na última mídia de cada letra.
- **A5. Postar no BlueStacks** (ADB + uiautomator2):
  - Mandar as mídias direto para a galeria do Android e atualizar a galeria (substitui o Gerenciador de Mídia, que perde arquivo em lote). Conferir que todas apareceram.
  - Instagram → story → galeria → Selecionar → tocar na ordem → Avançar; música de "Áudio original" (lista do `config`) nos vídeos sem áudio; figurinha de link na última mídia da letra, confirmando no ✓ do teclado; "Seu story" → Concluir; nunca compartilhar no Facebook.
  - Seletores por texto/descrição em PT-BR, com alternativas. Nada de coordenada fixa sem plano B.
  - `--ensaio`: faz tudo até antes de publicar e salva um print de cada mídia montada.
  - `--diagnostico`: salva a hierarquia da tela (XML) + print a cada passo.
  - Se um passo falhar: parar com segurança (nunca publicar letra pela metade), registrar onde parou e o que já subiu.
- **A6. Relatório do pedido.** O que subiu, o que foi cortado (cor sem estoque, já postado) e o trecho JS de conferência pronto para a IA rodar no navegador.
- **A7. Skill `postar-stories-ferreira`** em `.claude/skills/` (ver §7).

## 5. Entregável B — Edição de vídeo (CapCut)
Guia completo em `conhecimento/edicao-video-capcut.md`. Formato do rascunho, ferramentas e modal de exportação em `conhecimento/capcut-rascunho-e-exportacao.md`.

- **B1. Preparar o bruto.** Inventário com ffprobe (resolução, fps, HDR, rotação, áudio); detecção de tomadas; trechos em silêncio; transcrição em PT-BR no próprio PC (faster-whisper) → legendas `.srt`; batidas da música escolhida; folha de contato por tomada.
- **B2. Receitas.** Transformar as receitas de moda (§4.4) e as regras de montagem, texto, cor, áudio e zonas seguras (§3–§7, §10) em modelos `receitas/*.json`. Uma receita define a estrutura: gancho no quadro 1, ritmo, textos na zona segura, legendas, transições dentro do orçamento da §4.1, música e volumes.
- **B3. Gerar o rascunho do CapCut 9.5** a partir de receita + mídias + textos:
  - Primeiro, pegar um rascunho real do PC (vem no diagnóstico) como gabarito e confirmar o formato da 9.5.
  - Avaliar pyCapCut, VectCutAPI, capcut-cli e capcut-mcp. Usar o que gerar um rascunho que abre sem erro na 9.5, ou escrever um gerador próprio sobre o gabarito.
  - Fazer backup da pasta de rascunhos antes de gravar, sempre com o CapCut fechado.
- **B4. Exportar e conferir.** Abrir o rascunho e exportar pelos atalhos, com o preset do destino (§8), se isso ficar confiável. Senão, o rascunho fica pronto e a exportação é um clique do usuário. Depois, conferência automática do arquivo: duração, 1080×1920, fps, taxa de bits, áudio presente, loudness perto de −14 LUFS e tamanho dentro do limite do stories (~100 MB). Relatório com o que passou e o que não passou.
- **B5. Skill `editar-video-ferreira`** em `.claude/skills/` (ver §7). O guia de CapCut continua valendo para o acabamento manual.

## 6. Ciclo de teste com o PC do usuário
1. Na nuvem: `pytest` com mídia sintética (ffmpeg gera vídeos com e sem áudio, `.mov` e fotos), mock do uiautomator2 e validação do rascunho gerado contra o gabarito.
2. No PC: `testar.bat <alvo>` roda o teste real, grava `execucoes/<aaaa-mm-dd_hhmm>_<alvo>/` (log, prints, XML de tela, versões) **sem segredos** e faz `git push`. Aqui, é só dar `git pull`.
3. Primeiro pedido ao usuário, logo depois do esqueleto e do instalador: rodar `instalar.bat` e `diagnostico.bat` (versões, `adb devices`, se o ADB do BlueStacks está ligado, XML da tela inicial do Instagram, cópia do rascunho do projeto de teste "0925" do CapCut).
4. Postagem real só depois de um `--ensaio` aprovado pelo usuário.

## 7. Skills (formato)
Cada skill tem um `SKILL.md` curto (até ~150 linhas), em português, com:
- quando usar;
- pré-requisitos (vigia rodando, `.env`, BlueStacks aberto);
- passo a passo com os **comandos exatos** e o que a IA decide em cada passo (identificar peça e cor, escolher receita e textos). O resto é script;
- as regras fixas do usuário (link sem `https://`, estoque, já postado, figurinha só na última mídia…);
- a conferência final e o formato do aviso ao usuário;
- os erros conhecidos e a solução de cada um.

As skills depois vão para a conta do usuário, então não podem depender de nada desta sessão na nuvem.

## 8. Critérios de aceite
- [ ] `instalar.bat` roda do zero num Windows 11 e termina com tudo verde.
- [ ] Stories: uma pasta de data real vai de "mídias soltas" a "pedido na fila" sem clique, com cortes de estoque e bloqueio de repetição corretos.
- [ ] Stories: `--ensaio` monta uma letra completa (fotos, vídeo com música, figurinha com link sem `https://`) e para antes de publicar; os prints são conferidos pelo usuário.
- [ ] Stories: postagem real de uma letra, conferida pelo JS (quantidade de itens e `LINK` na última mídia).
- [ ] Vídeo: um bruto real vira um rascunho que abre na 9.5 sem "mídia perdida", seguindo uma receita.
- [ ] Vídeo: o arquivo exportado passa na conferência automática.
- [ ] As duas skills escritas e testadas uma vez seguindo só o que está nelas; `conhecimento/` atualizado com tudo o que foi aprendido.
- [ ] `README.md` com instalação e uso em uma página.

## 9. Ordem de trabalho
0. Esqueleto do repositório, `config/`, `.env.example`, `instalar.bat`, `diagnostico.bat`, `testar.bat` → pedir ao usuário para rodar o instalador e o diagnóstico.
1. A1–A4 e A6 (testáveis aqui) + testes.
2. B1–B2 + testes.
3. A5 com o ciclo real (diagnóstico → ensaio → postagem real).
4. B3–B4 com o ciclo real.
5. Skills, README e atualização de `conhecimento/`.
6. Relatório final ao usuário: o que ficou automático, o que ainda passa pela IA e o que ele faz em cada rodada.

## 10. Depois dos critérios de aceite (se ainda houver crédito)
- Identificar a peça automaticamente por semelhança com as fotos do cadastro (`products.photo_url`, `products.catalog_media`), deixando para a IA só confirmar.
- Gerar as versões Stories e TikTok a partir do master de um Reels.
