---
name: postar-stories-ferreira
description: Postar stories da Ferreira Boutique pelo BlueStacks a partir da pasta do dia (Stories da Loja\<data>) — prepara as mídias, confere estoque e repetição, põe o link do WhatsApp e publica pela fila de pedidos do PC. Usar sempre que o usuário pedir para postar, montar ou conferir stories da loja.
---

# Postar stories — Ferreira Boutique

Você (IA no Cowork) só lê e grava arquivos nas pastas do PC. Quem executa é o **vigia** no Windows: você grava um pedido
JSON na fila e lê o resultado. Detalhes da fila: `C:\Users\V15\Documents\Rotinas Ferreira\sistema\fila\README.md`.
Regras completas: `...\sistema\conhecimento\stories.md` (obrigatórias).

## Quando usar
"Posta os stories de hoje", "monta a pasta 2026-09-22", "sobe a compilação de modelos", "confere se subiu".

## Pré-requisitos (conferir antes; se faltar, pedir ao usuário UMA coisa por vez, com o passo exato)
- Vigia vivo: `Rotinas Ferreira\fila\vigia.vivo` muda entre duas leituras (~10 s ocioso, ~60 s executando). Parado →
  pedir: dois cliques em `C:\Users\V15\Documents\Rotinas Ferreira\sistema\atualizar.bat`.
- Mídias do dia em `C:\Users\V15\Documents\Stories da Loja\<AAAA-MM-DD>\`.
- Para publicar: BlueStacks aberto, Instagram logado, ADB ligado (BlueStacks → Configurações → Avançado → Android
  Debug Bridge) e `Rotinas Ferreira\registros\postados.csv` **fechado** no Excel.

## Como pedir e esperar
1. Gravar `Rotinas Ferreira\fila\pendente\<id>.json.tmp` e renomear para `<id>.json` (ou gravar `<id>.json` de uma vez).
   Campos: `id` (= nome do arquivo; modelo `aaaammdd-hhmmss-<tipo-com-hífen>-<detalhe>`, nunca reutilizar), `tipo`,
   `args`, `ensaio`, `diagnostico`, `criado_em` (ISO com fuso), `origem: "cowork"`.
2. A cada ~10 s, ler `fila\feito\<id>.json` ou `fila\erro\<id>.json` (só aparece quando terminou). Conferir `pedido.criado_em`.
3. Prints, XML e log ficam na pasta indicada em `pasta` do resultado.

## Passo a passo (o que é script e o que você decide)
**1. Preparar a pasta** — `tipo: "stories.preparar"`, `args: {"data": "2026-09-22", "simular": true}`.
   - Script: agrupa as mídias novas em letras (subpasta = letra; soltas por data de captura), gera folhas de contato.
   - **Você decide:** olhando SÓ as folhas `Rotinas Ferreira\stories\<data>\folhas\<L>.jpg`, se cada letra é um modelo
     só. Errado → refazer com `"grupos": [["IMG_1.MOV","IMG_2.JPG"], ["IMG_3.JPG"]]` (nomes originais).
   - Certo → mesmo pedido sem `simular` (com `grupos` se usou) — **obrigatório antes do montar** (o montar nunca prepara
     a pasta: sem `manifesto.json` ele para com "Sem manifesto.json"). O script renomeia (`A - 1` vídeo, `A - 2`… fotos,
     na próxima letra livre), converte `.mov`→`.mp4`, guarda originais em `_originais` e marca vídeo sem áudio.
   - Anote as letras com `"nova": true` no resultado do preparar **real**: são as de hoje. Letra que já existia
     (`nova: false`, mídias com `origem: null`) não se identifica, a não ser que o usuário peça; no montar ela sai como
     aviso "Letra A sem identificação: ficou de fora" (normal). Rodar o preparar de novo mostra todas como `nova: false`.
**2. Identificar peça e cor** — **você decide**, pelas folhas: qual peça é cada letra e qual cor aparece em cada mídia.
   - Confirmar no cadastro: `tipo: "stories.estoque"`, `args: {"consultas": [{"sku": "FB-0123"}, {"termo": "vestido midi"}]}`.
     Use o SKU e os **nomes de cor exatamente como vêm no resultado** (`estoque_por_cor`; `texto` traz a tabela pronta).
   - `termo` procura só no **nome** (não na categoria): as palavras na ordem, com qualquer coisa entre elas ("vestido
     festa" acha "Vestido Longo Festa"; "festa vestido" não). Maiúsculas tanto faz; acento conta ("alça" ≠ "alca").
     `sku` é exato, como no cadastro (`FB-0410`; `fb-0410` não acha). `encontrados: 0` não é erro: tente outro termo.
   - Modelo zerado (`total: 0`) ou cor zerada: **ponha mesmo assim** no montar; o script corta e registra no relatório.
**3. Montar em ensaio** — `tipo: "stories.montar"`, `"ensaio": true`, `args`:
   ```json
   {"data": "2026-09-22", "postar": true, "ensaio": true,
    "identificacao": {
      "A": {"sku": "FB-0123", "midias": {"A - 1": ["Verde"], "A - 2": ["Verde"], "A - 3": ["Preto"]}},
      "B": {"sku": "FB-0456", "midias": {"B - 1": ["Azul"], "B - 2": ["Azul", "Branco"]}, "excluir": {"B - 3": "outra peça"}}
    }}
   ```
   - Toda mídia da letra entra em `midias` (≥ 1 cor) ou em `excluir` (com motivo). Compilação de modelos: `"ordem": "categorias"`.
   - Mande **todas** as letras novas num pedido só: letra fora de `identificacao` fica de fora e o `stories.postar` já vai
     para a fila sem ela.
   - Script: corta cor sem estoque e modelo zerado, bloqueia já postado, monta o link, escolhe a música dos vídeos sem som
     e grava o pedido `stories.postar`. O resultado traz `relatorio` e `pedido_postagem` (id): espere por esse também.
   - Conferir no `relatorio` (e em `plano.letras`): cortes certos, festa "sem link", link `wa.me/…` sem `https://` só na
     última mídia de cada letra, música nos vídeos sem som. Aviso "cor aproximada: 'verde' → 'Verde Bandeira'" = o script
     aceitou um nome parecido: confira se é a cor certa; se não, refaça com o nome exato.
   - O `stories.postar` de ensaio monta cada letra no Instagram e **para antes de publicar**; prints `ensaio_<L>_<n>.png`.
     `"diagnostico": true` no montar vale para o postar gerado (XML + print de cada passo).
   - O relatório do postar tem "Avisos da postagem:" (ex.: 'Recentes' no lugar do álbum, ordem por data): mostre ao
     usuário; com aviso de 'Recentes' ou de ordem, confira os prints antes de liberar o real.
   - `stories.postar` deu erro → ler `erro` e `resultado_parcial.relatorio` / `parou_em` (tabela abaixo). Para repetir,
     resolver a causa e gravar **outro `stories.montar`** (novo id); nunca reenviar nem escrever o `stories.postar` à mão.
**4. Aprovação** — mostrar ao usuário o relatório do ensaio (e os prints, se ele quiser ver). Só publicar com o "pode postar" dele.
**5. Publicar** — repetir o passo 3 com `"ensaio": false` **no pedido e nos args**. Esperar o `stories.postar` real.
**6. Conferir no Instagram (obrigatório)** — o resultado do `stories.postar` traz `resultado.relatorio` (aviso pronto)
   e `resultado.js_conferencia` (em erro, dentro de `resultado_parcial`). Rodar o JS no console do navegador logado no
   Instagram: ele lista os itens, mostra onde está o `LINK` e termina em **CONFERE** ou **NÃO CONFERE**. Não confiar no
   visual do editor. NÃO CONFERE → dizer ao usuário o que falta, sem repostar por conta própria.

## Regras fixas do usuário (valem sempre)
- É **story**, não feed. Só pelo BlueStacks. Nunca compartilhar no Facebook.
- **Estoque primeiro:** cor com estoque 0 não vai; modelo sem nenhuma peça não entra; avisar depois o que ficou de fora.
- **Não repetir:** modelo já postado não entra de novo (o script diz quando e onde saiu). Só repetir se o usuário mandar
  (`"permitir_repeticao": ["B"]`).
- Uma letra por modelo; `A - 1` é o vídeo, depois as fotos. Nunca sobrescrever nem apagar mídia do usuário.
- Vídeo sem áudio recebe música do Instagram da lista de `config\stories.json` (`audios_sem_som`).
- Figurinha de link **só na última mídia de cada letra**: `wa.me/5582988748649?text=<mensagem com o nome da peça>`,
  **sem `https://`** (com https a figurinha sai sem link). Texto: "Comprar", "Comprar agora" ou "Comprar pelo Whatsapp".
- **Vestido de festa não leva link** (categorias `Vestidos de Festa` / `VESTIDO DE FESTA` do cadastro).
- Compilação de modelos: ordem conjuntos → vestidos casuais → macacões → vestidos de festa.
- Postagem real só depois de ensaio aprovado.

## Aviso final ao usuário (curto)
```
Subiu: A (Vestido Midi Alça) 3 mídias, link na A - 3 · F (Vestido Longo Festa) 2 mídias, sem link (festa).
Ficou de fora: A - 4 (Preto sem estoque — avise se repor) · C inteira (já postada em 18/09, letra B).
Conferência no Instagram: CONFERE (5 itens, LINK na A - 3).
Você precisa: nada.   (ou: repor Preto / aprovar o ensaio / fechar o postados.csv…)
```

## Erros conhecidos e solução
| Erro | Solução |
|---|---|
| montar: "cor 'X' não existe no cadastro" / "é ambígua" (vem com "Cores válidas do cadastro") | Usar um nome da lista. Nada foi cortado nem gravado na fila. |
| montar: "Mais de um produto para termo …. Informe o SKU." | Passar o `sku`. |
| "O Supabase recusou o e-mail ou a senha do usuário das rotinas" / "Falta SUPABASE_… no .env" | Pedir ao usuário para conferir no `.env` o usuário das rotinas (`SUPABASE_EMAIL`, `SUPABASE_SENHA`) e a `SUPABASE_KEY`; nunca pedir a senha no chat. |
| "Login ok, mas a leitura veio vazia" | O usuário das rotinas não enxerga os produtos (RLS): avisar o usuário; não postar sem estoque. |
| montar: "B - 3 sem identificação" | Pôr a mídia em `midias` (cores) ou em `excluir` (motivo). |
| `ErroRegra` sobre vestido de festa | `link_em_vestido_de_festa` voltou a `null` na config: não decidir; perguntar ao usuário (a resposta vai para `config/stories.json` no repositório; vale no pedido seguinte depois do `atualizar.bat`). |
| montar: "Sem manifesto.json" | Gravar o `stories.preparar` real (sem `simular`, com os mesmos `grupos`) e depois o montar. Nada foi alterado. |
| Pedido em `pendente` há mais de 1 min | Vigia parado → `atualizar.bat`. |
| "Não consegui conectar ao BlueStacks pelo ADB" / sem dispositivo | Pedir para abrir o BlueStacks e ligar o ADB (caminho acima); depois novo montar. |
| "Não encontrei o adb (nem o HD-Adb.exe do BlueStacks)" | Pedir dois cliques em `sistema\instalar.bat`; depois novo montar. |
| "a galeria não mostrou …" | Envio pelo ADB falhou para algum arquivo; pedir de novo com outro id. |
| Letra `falhou` em um passo (`parou_em`) | Nada daquela letra foi publicado; as anteriores sim (ver `resultado_parcial`). Se for seletor da tela: com `parou_em` em abrir_instagram, criar, abrir_story, abrir_galeria ou selecionar_varios, pedir ao usuário `testar.bat bluestacks`; nos demais passos, `testar.bat stories-ensaio --data <data>` (XML + print de cada passo, sem publicar). Com a pasta do resultado, ajustar `config/bluestacks.json` **no repositório**. Não editar arquivos de `sistema\` no PC: trava o `git pull` do `atualizar.bat`. |
| "toquei N vez(es) em 'Adicionar ao story' e a galeria/câmera do story não abriu" | Nada foi publicado. O feed não respondeu ao toque (o script já tocou de novo). Pedir ao usuário para conferir se o Instagram do BlueStacks abre o story à mão; depois `testar.bat stories-ensaio --sintetico` para ver os prints. |
| "a mídia N da letra (vídeo) não ficou selecionada … o Instagram do BlueStacks não leu o vídeo" | Nada foi publicado. Ver o print `selecao_*` do resultado: miniatura cinza = o emulador não leu o vídeo. Conferir o formato do arquivo convertido (`ffprobe`) e registrar em `conhecimento/stories.md`; não repetir o mesmo pedido. |
| Aviso "não achei '<música>' … na busca do Instagram; usei <outra>" | Normal: a música pedida não apareceu e o script usou a seguinte de `audios_sem_som`. Nada a fazer; se repetir sempre com a mesma música, avisar o usuário. |
| "não achei nenhuma música da lista na busca do Instagram … a busca mostrou: …" | Nada foi publicado. Se a busca só mostra faixas "sem royalties", perguntar ao usuário como ele acha essas músicas no celular (não trocar a lista por conta própria). |
| Letra `incerta` | Pode ter subido: rodar o `js_conferencia` **antes** de repetir (ela já está nele); CONFERE = subiu. Repetir só o que não subiu. |
| "Não consigo gravar em postados.csv; nada foi publicado" | Nada subiu. Pedir para fechar o `postados.csv` no Excel e gravar outro montar. |
| "A letra X FOI PUBLICADA, mas não consegui registrar em postados.csv" | X **subiu**: não repostar. O registro fica em `registros\postados_pendentes\` e já conta como postado. O postar parou antes da próxima letra: pedir para fechar o Excel e mandar só as letras não iniciadas. |
| "Registro pendente ilegível" | Não publica sem saber o que subiu: pedir ao usuário para mostrar o arquivo de `registros\postados_pendentes\`; conferir no Instagram. |
| "não publico pela grade 'Recentes'" | O álbum da letra não abriu (seletores `album_menu`/`album_item`): pedir `testar.bat bluestacks` e ajustar no repositório. |
| "O BlueStacks está em uso por outro pedido ou teste" | Nada foi feito. Esperar o outro terminar e pedir de novo; não pedir testes no PC com postagem na fila. |
| "Já existe um pedido stories.postar real…" | Esperar o pedido anterior terminar; não criar outro. |
| "Interrompido" em `erro` | O vigia caiu no meio: o relatório diz "postagem INTERROMPIDA" e traz o JS de todas as letras. Rodar antes de pedir de novo; mandar só as letras que faltam. |
