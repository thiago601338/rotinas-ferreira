# Briefing — rotina "responder o Business Suite" (Direct e comentários do Instagram)

Para: ChatGPT / Codex · Escrito pelo Claude (Cowork) em 27/09/2026 · Dono: Tiago, Ferreira Boutique

## 0. Objetivo

Quando o dono pedir ao Claude "responde o Business Suite", a resposta tem que sair gastando poucos tokens:

- um script (sem IA) entrega as conversas pendentes já em texto curto, com preço, parcelamento e estoque calculados;
- o Claude só decide e escreve as respostas;
- outro script envia pela API do Instagram e registra.

Hoje o Claude teria de abrir o Business Suite no navegador e ler print por print. É isso que fica caro.

É o mesmo princípio das rotinas de stories e de edição de vídeo deste repositório: o script faz tudo que não exige
julgamento, e uma skill curta deixa para a IA só o que exige julgamento. A diferença é que aqui não precisa do PC nem do
vigia: as mensagens já chegam no Supabase.

### 0.1 Acesso que você precisa

- Este repositório (`rotinas-ferreira`).
- Supabase do projeto `nailfzcujyxydqldktgg` pela variável de ambiente `SUPABASE_ACCESS_TOKEN` (token pessoal do dono).
  Use a CLI (`npx supabase … --project-ref nailfzcujyxydqldktgg`) ou a Management API
  (`POST https://api.supabase.com/v1/projects/nailfzcujyxydqldktgg/database/query`) para SQL e publicação de funções.
- Sem esse acesso: deixe tudo pronto no repositório, com passo a passo de publicação, e pare aí.

## 1. O que já existe (medido em produção em 27/09/2026)

### 1.1 Instagram

- API: Instagram API with Instagram Login (host `graph.instagram.com`, versão `v25.0`). Conta IG `17841454587986765`.
- Token ativo: renovado pelo `instagram-token-guardian` (cron a cada 5 min). Ler como o `send()` do worker v6 lê
  (`fonte-atual/worker-v6-modulos.txt`, módulo `index.mjs`): RPC `ai_meta_token_get` (tabela
  `private.instagram_runtime_credentials`), com o secret `INSTAGRAM_TOKEN` como reserva.
  Saúde em `ai_settings.instagram_delivery_health` (saudável; expira 23/11/2026; renovação prevista 09/11).
- Webhook: Edge Function `meta-webhook` (versão 50, `WEBHOOK_REVISION v6.2-meta-audio-silent-20260910-r1`).
  Grava em `ai_conversations` e `ai_messages` (`direction` inbound/outbound). As respostas que a equipe manda pelo app
  chegam como eco e são gravadas como outbound com `raw_payload.origem='conta_da_loja'`.
- IA automática: `instagram-turn-worker-v6` (cron `ferreira-instagram-quiet-worker`, a cada 5 s, `ai_ig_dispatch()`).
  Hoje não envia nada: secret `AI_SENDING_ENABLED=false`.
- Janela da Meta: pela API só dá para responder até 24 h depois da última mensagem da cliente. A etiqueta
  `HUMAN_AGENT` (até 7 dias) é só para resposta escrita por uma pessoa da equipe e depende de análise da Meta: não
  usar. No app do Instagram essa janela não existe; por isso as conversas com mais de 24 h são respondidas pelo
  Instagram no Chrome (3.5 e 3.8).

### 1.2 Problema atual (importante)

- Desde **26/09/2026 às 17:37 (Maceió)** nenhuma mensagem de cliente é gravada.
- Motivo: em `lib/pipeline-instagram.ts` → `handleInstagramMessage`, a guarda
  `if(!env.sendingEnabled||!m.accountId||!channelReady(...)){ logEvent(... 'canal desativado ou conta não configurada'); return true; }`
  sai **antes** do `recordMessage`. Com `AI_SENDING_ENABLED=false`, o webhook recebe (`ai_logs`, kind
  `webhook_received`, dezenas por hora) e descarta.
- Os ecos da equipe continuam gravados (em 27/09 há respostas da equipe até 19:25).
- A mesma guarda existe em `lib/pipeline.ts` → `handleMessage` (outros canais).

### 1.3 Gatilhos AFTER INSERT em `ai_messages` (considerar todos no modo novo)

| Gatilho | Função | O que faz |
|---|---|---|
| `ai_messages_story_prefetch` | `ai_prefetch_instagram_story()` | Chama a Edge `instagram-story-prefetch`, que baixa o quadro do story respondido para `ai-inbox-media/instagram-story-cache/image/<story_id>/<message_id>.<ext>` e grava em `raw_payload.storyPrefetch.imagePath`. **Não usa IA.** Só roda se `ai_settings.instagram_turn_policy.enabled=true` (hoje true) e se o story ainda não está em `ai_story_products`. |
| `ai_z_instagram_quiet_after_message` | `ai_ig_track_quiet()` | Enfileira o turno da IA em `ai_instagram_turn_queue`. |
| `ai_instagram_audio_preprocess_after_insert` | `private.ai_audio_preprocess_dispatch()` | Chama `instagram-audio-preprocess` (transcrição pela OpenAI). Só com `processingStatus='pending'`. |
| `trg_ai_instagram_text_normalizer` | `private.ai_enqueue_instagram_text_normalizer()` | Chama `instagram-text-normalizer`. Só com `processingStatus='pending'`. |
| `ai_track_wait_after_message` | `ai_track_wait()` | Controle de espera humana (`ai_human_waits`). |

Crons: `ferreira-human-followup` (1 min), `ferreira-story-registry-learn` (2 min, `ai_learn_story_products()`: aprende
story → produto pelas respostas de preço da equipe), `ferreira-instagram-token-guardian` (5 min),
`ferreira-story-publisher` (1 min), limpezas diárias.

### 1.4 Catálogo e regras comerciais

- `products` (`status='Ativo'`, `deleted_at is null`, `sale_price`, `fabric`, `category`, `photo_url`, `catalog_media`,
  `search_aliases`) e `product_variations` (`color`, `size`, `stock`).
- Busca pronta: `ai_search_products(p_terms text[], p_color text, p_size text, p_limit int)`. O `matched_stock` trata
  cor e tamanho juntos (tem preto e tem M, mas não tem preto no M → não tem).
- Normalizadores: `ai_color_key`, `ai_size_key`, `ferreira_color_display`, `ferreira_text_key`.
- Parcelamento: `ai_settings.public_installment_policy`. Até R$149,99 → 2x; de R$150,00 a R$319,98 → 3x; a partir de
  R$319,99 → 5x; sem juros. À vista com 3% de desconto, pela mesma conta do worker (`installments.mjs`):
  `floor((centavos*(10000-300)+5000)/10000)`.
- Dinheiro no formato da loja: `R$229,99` (colado, com vírgula). Textos prontos no worker (`voice.mjs`):
  `installmentsText(n)` = "Dividimos em até Nx sem juros"; `cashText` = "À vista fica R$…".
- Endereço confirmado: `ai_settings.assistant.public_store_address`.
- Story → produto: `ai_story_products` (story_id, account_id, product_id, color, method, expires_at…). Hoje há 78
  registros, com os métodos `human_price_match` e `visual_verified`.
- Fotos do cadastro: bucket público `product-photos` (uma por cor em `<product_id>/site-20260910/<cor>-front-*.webp`).

### 1.5 O que fica fora

- Comentários: `ig_analytics_comments` e `ig_analytics_media` são uma exportação de análise (última coleta em 25/09).
  Não servem para responder. A Fase 2 cria o caminho próprio.
- Messenger (Facebook) e WhatsApp não passam pelo sistema (só 3 mensagens de teste de WhatsApp em 10/09). Ficam fora
  desta entrega.

As fontes de produção congeladas estão em `fonte-atual/` (ver `fonte-atual/SOBRE.md`).

## 2. Arquitetura

```
Instagram ─webhook─> meta-webhook ─(modo claude: só grava)─> ai_messages ─gatilho─> story-prefetch (quadro do story)
          └──────── atendimento-sync (cron 10 min + sob demanda): Conversations API + comentários → completa o que faltar

Claude (Cowork) ─execute_sql─> atendimento.pendentes()        texto curto do lote
                               atendimento.produto()          candidatos com preço e estoque
                               atendimento.folha_produtos()   URL da folha de fotos do cadastro
                ─curl────────> atendimento-midia (Edge)       folha JPEG das mídias sem peça
                ─execute_sql─> atendimento.responder()        valida e enfileira ─pg_net─> atendimento-enviar (Edge) → Instagram
                               atendimento.status()           resultado por item
```

Tudo que o Claude chama fica no schema `atendimento` (fora da API REST pública).

## 3. Fase 1 — Direct do Instagram

### 3.1 Chave de modo

- `ai_settings`, key `atendimento_modo`, valor `{"instagram":"claude"}` ou `{"instagram":"ia"}`.
  Sem a chave vale `ia`, que é o comportamento de hoje.
- `atendimento.modo(p_modo text default null) returns text`: sem parâmetro mostra o modo; com `'claude'` ou `'ia'`
  troca e registra em `ai_logs`.
- No modo `claude`:
  - o webhook grava toda mensagem da cliente (texto, resposta a story, foto, áudio, compartilhamento) e baixa a mídia
    como hoje;
  - o quadro do story continua sendo capturado (prefetch);
  - áudio é transcrito pelo `instagram-audio-preprocess` se a chave da OpenAI funcionar. Se falhar, o item mostra
    `[áudio sem transcrição]`. Nenhum outro uso da OpenAI: sem normalizador de texto, sem worker, sem visão;
  - a IA automática não roda: `ai_ig_track_quiet` não enfileira, `ai_ig_dispatch` não despacha e `human-followup`
    não envia nada;
  - `AI_SENDING_ENABLED` continua `false`. Não mexer.
- No modo `ia`: exatamente o comportamento de hoje. Voltar a chave para `ia` reverte tudo.

### 3.2 Webhook (mudança mínima)

- Em `handleInstagramMessage` (e no trecho equivalente de `pipeline.ts`, só para Instagram): se o modo for `claude` e o
  canal estiver configurado (`channelReady`), gravar a mensagem com o mesmo `recordMessage` e o mesmo formato de
  `raw_payload` de hoje (`storyReference`, `replyTo`, `mediaId`/`mediaUrl`/`mediaType`, `customerName` etc.), com
  `processingStatus:'claude'`. Baixar a mídia de foto e áudio para `ai-inbox-media` como o pipeline já faz e retornar
  sem inferência.
- Não mudar assinatura, handshake, eco, coexistence nem o caminho do modo `ia`.
- Eco dos envios do Claude (ver 3.8): continua passando por `handleBusinessEcho`. Durante o envio, o Claude marca
  `ai_conversations.metadata.aiProcessing=true` para o eco esperar 1,5 s e reconhecer o id. Essa espera já existe.
- Publicar com o modo ainda em `ia` (sem efeito), conferir que nada mudou e só então trocar para `claude`.

### 3.3 Sincronização de segurança — Edge `atendimento-sync`

- Conversations API (Instagram Login):
  `GET https://graph.instagram.com/v25.0/me/conversations?platform=instagram` e
  `GET https://graph.instagram.com/v25.0/<CONVERSATION_ID>?fields=messages{...}`.
  A API só devolve as **20 mensagens mais recentes** de cada conversa.
- Para cada conversa atualizada nas últimas `horas` (padrão 48), inserir em `ai_conversations`/`ai_messages` só o que
  faltar, sem duplicar (pelo `external_message_id`), no mesmo formato do webhook e com `raw_payload.origemSync=true`.
  Não usar `importedHistory`, que desliga o prefetch. Direção pela conta: `from.id` da loja → outbound com
  `origem='conta_da_loja'`.
- Quem chama: cron a cada 10 min (só no modo `claude`) e `atendimento.sincronizar()`, que dispara por `pg_net` e
  responde na hora "sincronização pedida".
- Guarda a hora da última sincronização (o cabeçalho do `pendentes` mostra "sinc. há N min").
- Primeira execução: recuperar o que ficou sem gravar desde 26/09 17:37.
- A Fase 2 acrescenta os comentários nesta mesma função.

### 3.4 Tabelas no schema `atendimento` (sugestão; os nomes internos são livres)

- `lotes`: id no formato `L0927-1930` (mês, dia, hora e minuto de Maceió), criado_em, token da folha, expira_em.
- `lote_itens`: lote, n, tipo (direct ou comentario), conversation_id ou comment_id, last_inbound_id, última mensagem
  da loja vista, mídias sem peça com seus rótulos (s1, f1, p1…).
- `envios`: lote, n, parte, texto, status, message_id da Meta, erro, tentativas, enviar_apos, enviado_em.
  Único em (lote, n, parte).
- `pulos`: conversation_id ou comment_id, last_inbound_id, motivo, lote, data. Item pulado não volta até chegar
  mensagem nova.
- `midia_produto` (Fase 2): media_id do post/reel → product_id, cor, método.
- `estado`: chave/valor (última sincronização etc.).

### 3.5 `atendimento.pendentes(p_max_direct int default 20, p_max_comentarios int default 10, p_max_fora int default 10) returns text`

Devolve um único texto (não JSON, não uma linha por registro). Cada chamada cria um lote novo. Ordem: quem espera há
mais tempo primeiro.

Entra na lista a conversa do Instagram cuja última mensagem é da cliente, dentro da janela de 24 h, sem opt-out
(`ai_optouts`) e sem pulo registrado para essa mesma última mensagem.

Fica fora da lista (só contado no rodapé):

- sinal forte de etapa da equipe: a loja já mandou link ou chave de pagamento, ou pediu endereço/CPF; a cliente mandou
  comprovante ou disse que pagou ou vai pagar agora; perguntou se é robô ou quem está falando; reclamação; pediu
  atendente ou pessoa;
- turno só de cortesia: ok, tá bom, entendi, obrigada depois de resposta da loja, emoji, figurinha, curtida;
- só áudio sem transcrição;
- última mensagem da cliente com mais de 7 dias;
- modo `ia` ligado (o cabeçalho avisa e não lista nada).

Fora da janela da API: conversa cuja última mensagem da cliente tem entre 24 h e 7 dias, sem resposta da loja depois
dela, entra num bloco separado no fim do texto, `FORA DA JANELA (pelo Instagram)`, com itens `#j1`, `#j2`…. Mesmo
formato dos outros itens, mais o `@usuario` da cliente (User Profile API, ver 3.7) e as horas desde a última mensagem.
A API não deixa responder essas; o Claude responde pelo Instagram no Chrome (3.8).

Sinal fraco — entrega, frete, envio, retirada, reserva/separar, troca/devolução, desconto, pix, cartão, sem os sinais
fortes acima → o item aparece com `⚠ <assunto>?` e o Claude decide. Parcelamento e à vista ele responde; o resto fica
com a equipe.

Conteúdo de cada item:

- linha do item: `#n · espera · janela restante`, mais `saudar` quando não há mensagem da loja nas últimas 6 h, e
  `equipe há N min` quando a equipe falou na conversa há menos de 30 min;
- até 8 mensagens da cliente desde a última mensagem da loja (cada uma com até 200 caracteres e hora de Maceió),
  precedidas das 2 últimas mensagens da loja (`L:`), para dar contexto;
- mídia (regras completas das imagens em 3.7):
  - resposta a story com peça conhecida → linha de fatos;
  - story sem peça → `[story s1 sem peça]` (o rótulo entra na folha);
  - foto/print da cliente → `[foto f1 sem peça]`, ou a peça, se a imagem já estiver no cache de imagens verificadas
    (chaves `ig_verified_image:*` em `ai_settings`);
  - vídeo da cliente → `[vídeo v1 sem peça]` (quadro na folha);
  - post/reel compartilhado → `[post p1 …]`;
  - mídia sem imagem nenhuma → `[story s1 sem imagem · @usuario · 26/09 18:05]` (ver 3.7);
  - áudio → `[áudio] "transcrição"` ou `[áudio sem transcrição]`;
- contexto: se a cliente respondeu a um story nas últimas 48 h e agora só escreve ("tem M?"), repetir a linha de fatos
  desse story como `[contexto]`;
- linha de fatos, calculada pelo script com os dados do momento:
  `SKU Nome · cor · R$preço · Nx · à vista R$… · cor: tamanhos com estoque · outras: cor tam tam; cor tam · tecido: …`
  Só tamanhos com estoque maior que zero. Cor sem estoque aparece como `rosa: acabou`. Produto sem estoque nenhum →
  `sem estoque`.

Exemplo (valores ilustrativos):

```
LOTE L0927-1930 · direct 3 · comentários 1 · sinc. há 1 min · modo claude
folha: https://nailfzcujyxydqldktgg.supabase.co/functions/v1/atendimento-midia?l=L0927-1930&t=… · ordem: s1
#1 · 12 min · janela 23h · saudar
  [story] FB-0091 Vestido longo drapeado · rosa · R$429,99 · 5x · à vista R$417,09 · rosa: P G · outras: preto P M; verde G · tecido: crepe
  19:02 C: valor?
  19:03 C: tem no M?
#2 · 40 min · janela 23h · equipe há 22 min
  18:40 L: Olá meu bem
  18:40 L: R$189,99 Dividimos em até 3x sem juros
  [contexto] FB-0122 Conjunto colete e pantalona · marrom · R$189,99 · 3x · à vista R$184,29 · marrom: P M G
  18:52 C: tem G?
#3 · 2 h · janela 21h · saudar
  [story s1 sem peça]
  17:30 C: quanto?
#c1 · comentário · 20 min · reel 12/09 "vestido midi preto com cinto…"
  [post] FB-0154 Vestido midi com cinto · preto · R$210,00 · 3x · à vista R$203,70 · preto: P M G GG
  19:10 C: valor?
FORA DA JANELA (pelo Instagram)
#j1 · @usuario · 31 h · saudar
  [story] FB-0122 Conjunto colete e pantalona · marrom · R$189,99 · 3x · à vista R$184,29 · marrom: P M G
  26/09 12:10 C: valor?
fora da lista: equipe 2 · cortesia 3 · áudio 1 · mais de 7 dias 2 · pulados antes 4
```

- Sem nome ou telefone da cliente no texto. O @ só aparece nos itens `#j` e nos `sem imagem` (3.7).
- Meta de tamanho: 20 conversas em até ~10.000 caracteres.
- Nada pendente: `LOTE — nada pendente · sinc. há N min` (sem criar lote).

### 3.6 `atendimento.produto(p_termos text, p_cor text default null, p_tamanho text default null) returns text`

Até 5 candidatos ativos, uma linha cada, no mesmo formato da linha de fatos. Usar `ai_search_products` e respeitar o
`matched_stock` quando vierem cor e tamanho.

### 3.7 Imagens e folhas — Edge `atendimento-midia` e `atendimento.folha_produtos(p_skus text) returns text`

Imagem é o que diz ao Claude qual é a peça. Conta como imagem: o story que a cliente respondeu (foto ou vídeo), a
foto ou print que ela manda, o vídeo que ela manda e o post/reel que ela compartilha.

- **Guardar quando a mensagem chega.** O quadro do story já é salvo pelo prefetch (de 24 a 26/09, 160 de 161 respostas
  a story chegaram com imagem ou com a peça já conhecida). Foto e vídeo da cliente: baixar para `ai-inbox-media`
  como o pipeline já faz (no modo `claude` também). Post/reel compartilhado: guardar a capa (Graph API).
- **Tentar de novo antes de desistir.** Ao montar o lote, mídia sem imagem guardada ganha uma nova tentativa: URL do
  `storyReference` ou do anexo, Graph API enquanto o story tem menos de 24 h e o extrator de quadro de vídeo que o
  prefetch já usa. Vale principalmente para as mensagens recuperadas pelo `atendimento-sync`, em que o story pode já
  ter vencido.
- **Sem imagem nenhuma → Instagram (regra do dono).** O item sai como
  `[story s1 sem imagem · @usuario · 26/09 18:05]` (ou `foto`, `vídeo`, `post`). O @ da cliente (aqui e nos itens `#j`)
  vem da User Profile API (`GET https://graph.instagram.com/v25.0/<IGSID>?fields=username`) e fica guardado em
  `ai_conversations.metadata.username`. Com isso o Claude abre a conversa da cliente no Instagram, onde a resposta ao
  story aparece, e identifica a peça por lá.
- **Aprender.** Quando o Claude identifica a peça (campo `produto`/`cor` do `responder`), a próxima resposta ao mesmo
  story, post ou imagem já sai com a linha de fatos, sem imagem.
- `atendimento-midia?l=<lote>&t=<token>` devolve um único JPEG com as miniaturas das mídias `sem peça` do lote
  (quadro do story, foto da cliente, quadro do vídeo, capa do post), na ordem da linha `folha`. Cada miniatura com no
  máximo ~256×456 px, até 12 por folha (`&p=2` para a próxima). Rótulo desenhado em cada miniatura se der; senão vale
  a ordem. Token aleatório por lote, válido por 6 h.
- `atendimento.folha_produtos('FB-0091,FB-0154')` devolve uma URL com token (6 h) de uma folha com a foto de frente do
  cadastro de cada SKU (uma por cor com estoque), rotulada com SKU e cor.
- Usar a mesma biblioteca de imagem que o worker já usa (ImageMagick WASM, em `crop.mjs`) ou outra que rode no Edge.
- As folhas existem para o Claude olhar **uma imagem por rodada**, em vez de uma por mídia.

### 3.8 `atendimento.responder(p_lote text, p_itens jsonb, p_ensaio boolean default false) returns text` + Edge `atendimento-enviar`

Formato de `p_itens` (é o que o SKILL.md usa — não mudar):

```json
[{"n":1,"msgs":["Olá meu bem","R$429,99\nDividimos em até 5x sem juros"]},
 {"n":3,"produto":"FB-0122","cor":"marrom","msgs":["R$189,99\nDividimos em até 3x sem juros"]},
 {"n":4,"pular":"pagamento"},
 {"n":"c1","msgs":["R$210,00 meu bem 😍"]}]
```

`n` pode vir como número ou texto (`1`, `"1"`, `"c1"`, `"j1"`).

Validação na hora. Item com problema volta como `rejeitado: motivo`; os outros seguem.

- `n` existe no lote. Direct: de 1 a 6 mensagens, cada uma com até 950 caracteres. Comentário: exatamente 1.
- Barrar texto com cara de robô ou proibido: "opção 1", listas numeradas, "como posso ajudar", "assistente",
  "sou uma IA", "me chamo", "print", "reenvi…".
- Todo valor `R$…` citado tem que bater com o preço ou com o à vista de um produto ativo.
- `produto`/`cor`, quando vierem: SKU ativo e cor existente no cadastro. Gravar o aprendizado:
  story → `ai_story_products` (método `claude_verificado`, mesmas regras de validade dos outros registros);
  post/reel → `midia_produto`; foto → o cache existente, se fizer sentido.
- `pular`: gravar em `pulos` com o motivo.
- `p_ensaio=true`: valida e mostra o que seria enviado, sem gravar nada.
- Item `jN` (fora da janela): valida igual, mas não vai para a API. Fica em `envios` com status `pelo_instagram`, e a
  resposta do `responder` traz a lista pronta para o Claude digitar no Instagram:
  `#j1 @usuario → "Olá meu bem" | "R$189,99\nDividimos em até 3x sem juros"`.
  Um gatilho em `ai_messages` (outbound) reconhece o eco dessas mensagens (mesma conversa, mesmo texto, até 2 h
  depois) e marca `origem='claude'` e o status `enviado_instagram`.

Envio (`atendimento-enviar`, disparado por `pg_net` na hora e por cron enquanto houver fila):

- Antes de cada parte, conferir no banco:
  - chegou mensagem nova da cliente depois do lote → segura a conversa (`nova_mensagem`);
  - a equipe respondeu depois do lote → cancela (`equipe_respondeu`);
  - última mensagem da cliente com 24 h ou mais → `fora_da_janela` (no próximo `pendentes` ela aparece como `#j`).
- `POST https://graph.instagram.com/v25.0/<conta>/messages` com
  `{"recipient":{"id":"<IGSID>"},"message":{"text":"…"}}`, usando o token ativo (§1.1).
- Partes da mesma conversa em ordem, com 2–4 s entre elas. Conversas diferentes em paralelo (até 5).
- Logo depois de cada parte aceita, gravar em `ai_messages` (outbound, texto, `external_message_id` = id devolvido
  pela Meta, `raw_payload` `{origem:'claude', lote, n, parte, enviado:true}`). Se a linha já existir porque o eco chegou
  antes, só trocar `origem` para `claude`. Marcar `aiProcessing` na conversa durante o envio e desmarcar no fim.
- Nunca enviar a mesma parte duas vezes (estado/lease por parte). Erro da Meta fica gravado com o código.
- Comentário (Fase 2): `POST https://graph.instagram.com/v25.0/<comment_id>/replies` com `message`.
- `origem='claude'` é o que separa, no banco, o que o Claude respondeu do que a equipe respondeu.

### 3.9 `atendimento.status(p_lote text) returns text`

Uma linha curta com todos os itens, por exemplo:
`#1 enviado 2/2 · #3 enviado 1/1 · #4 pulado pagamento · #5 nova_mensagem · #6 erro 10 (mensagem da Meta) ·
#j1 enviado_instagram · #j2 pelo_instagram`.

### 3.10 Segurança

- Funções no schema `atendimento`, sem `EXECUTE` para `anon` e `authenticated`. O schema não entra na API REST.
- Edge Functions com `verify_jwt=false`, protegidas por segredo no mesmo padrão das atuais (`x-ai-followup-token`
  validado por `ai_followup_valid`). `atendimento-midia` aceita só o token do lote.
- Não gravar o token da Meta em tabela nova nem em log.

### 3.11 Critérios de aceite da Fase 1

1. Com o modo em `ia`, depois de publicar o webhook novo, nada muda (mesmos logs de hoje).
2. Com o modo em `claude`, uma DM de teste mandada pela conta pessoal do dono aparece no `pendentes` em até 10 s. Uma
   resposta a story mostra a peça quando ela está em `ai_story_products`, e `[story s1 sem peça]` com a folha quando
   não está.
3. `responder(..., true)` mostra o plano e não envia nada.
4. Envio real só para a conta de teste: as mensagens chegam na ordem, com 2–4 s entre elas; `ai_messages` fica com
   `origem='claude'` e o id da Meta; nenhum handoff "uma pessoa da equipe respondeu" é aberto por causa do eco; a
   conversa sai do `pendentes`.
5. A equipe responde pelo app depois do lote → `equipe_respondeu`, nada enviado. Mensagem nova da cliente depois do
   lote → `nova_mensagem`.
6. Conversa com 24 h ou mais não sai pela API: aparece como `#j` com o @ da cliente; o `responder` devolve a lista
   pronta; depois de enviada pelo Instagram, o eco marca `enviado_instagram` e `origem='claude'`.
7. O modo `claude` não gera chamada à OpenAI além da transcrição de áudio (conferir `private.ai_cost_usage_daily` e
   `ai_logs`) e não gera envio automático.
8. O `atendimento-sync` recupera o que ficou sem gravar desde 26/09 17:37, sem duplicar nada. Mídia recuperada sem
   imagem sai como `sem imagem · @usuario` (3.7), nunca some da lista.
9. Imagens: resposta a story, foto da cliente e post compartilhado de teste aparecem na folha; depois de um `responder`
   com `produto`/`cor`, uma nova resposta ao mesmo story sai com a linha de fatos e fora da folha.
10. O `pendentes` com 20 conversas fica em até ~10.000 caracteres.
11. Voltar para `ia` restaura o comportamento de antes.

Durante os testes, **nunca** enviar mensagem para cliente real.

## 4. Fase 2 — comentários do Instagram

- O `atendimento-sync` passa a buscar os comentários dos posts e reels recentes e guardar em `atendimento.comentarios`:
  - `GET https://graph.instagram.com/v25.0/me/media?fields=id,caption,permalink,timestamp,media_type,media_product_type,comments_count,thumbnail_url,media_url`;
  - `GET https://graph.instagram.com/v25.0/<media_id>/comments?fields=id,text,timestamp,username,hidden,replies{id,text,timestamp,username}`;
  - o @ da loja vem de `GET https://graph.instagram.com/v25.0/me?fields=username`.
- Pendente = comentário de cliente sem resposta da loja, não oculto, com até 7 dias, que não seja só marcação (@) ou
  emoji solto.
- Peça do post: `atendimento.midia_produto` (aprendida pelo campo `produto` do `responder`). Sem registro →
  `[post pN sem peça]`, com a capa na folha.
- Resposta pública: `POST https://graph.instagram.com/v25.0/<comment_id>/replies` com `message`. Conferir se o token tem
  `instagram_business_manage_comments`. Se não tiver, o `pendentes` mostra "comentários: sem permissão" e segue só com
  o Direct.
- Aceite: um comentário de teste do dono aparece como `#c1`, a resposta sai pública e o comentário deixa de aparecer.

## 5. Fase 3 — peça de cada story gravada na hora de postar

Motivo: 84,5% das conversas do Direct começam respondendo a um story, e a maior causa de o atendimento travar é não
saber qual é a peça (53,8% dos encaminhamentos para a equipe, análise de 25/09). Se cada story postado pela rotina
`postar-stories-ferreira` já sair registrado, o Claude quase nunca precisa olhar imagem.

- Nova Edge `atendimento-registrar-stories` (mesma proteção por segredo). Recebe
  `{letra, sku ou product_id, cor, n_midias, publicado_de, publicado_ate}`, lista
  `GET https://graph.instagram.com/v25.0/me/stories?fields=id,timestamp,media_type`, pega os stories publicados nessa
  janela que ainda não estão em `ai_story_products` e, **só se a quantidade bater com `n_midias`**, grava cada um com
  método `postagem`. Se não bater, registra no log e não grava nada.
- No vigia do PC, depois que a letra aparece publicada, chamar essa função. Não mudar mais nada no fluxo de postagem.
- Letra de vestido de festa com vários modelos: gravar por mídia só se o manifesto tiver o SKU de cada arquivo; senão,
  não grava.
- Aceite: postar uma letra de teste → os stories aparecem em `ai_story_products` com o SKU e a cor certos, e as
  respostas a esses stories já saem no `pendentes` com a linha de fatos.

## 6. Onde fica no repositório

- `atendimento/`: este briefing, `supabase/migrations/…`, `supabase/functions/atendimento-*` e a cópia versionada do
  `meta-webhook` com a mudança.
- A skill `skill/responder-business-suite-ferreira/SKILL.md` vai para a mesma pasta das skills
  `postar-stories-ferreira` e `editar-video-ferreira`.
- O contrato das funções `atendimento.*` e o formato do `pendentes` são os do SKILL.md. Se algo mudar, atualizar o
  SKILL.md junto e listar a mudança no relatório final.

## 7. Regras de trabalho

- Não apagar nem desligar nada que já existe (funções, crons, gatilhos, tabelas). Mudar só o necessário e sempre atrás
  da chave `atendimento_modo`.
- Não ligar `AI_SENDING_ENABLED`.
- Antes de publicar uma função que já existe, guardar a versão atual (as de 27/09 estão em `fonte-atual/`).
- Testes de envio só com a conta pessoal do dono. Pedir a ele a DM e o comentário de teste e seguir no que não depende
  disso.
- Relatório final: o que foi publicado (com versões), o resultado de cada critério de aceite e o que ficou pendente.
