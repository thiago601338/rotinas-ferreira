# Sincronização de Direct e comentários

`index.ts` aceita somente POST com `x-ai-followup-token`, validado por `public.ai_followup_valid`. Corpo `{}` ou `{"horas":48}`; `horas` deve estar entre 1 e 168. Só executa no modo `claude`. Não envia mensagens nem chama IA.

Usa `SUPABASE_DB_URL` para acessar o schema privado `atendimento`, `SUPABASE_URL` e `SUPABASE_SERVICE_ROLE_KEY` para o bucket privado `ai-inbox-media`. O token do Instagram vem de `ai_meta_token_get()` e usa `INSTAGRAM_TOKEN` como reserva. As versões das dependências são fixadas. Publicar com `verify_jwt=false`; o segredo próprio continua obrigatório.

A identidade da conta é verificada comparando o ID canônico de `GET /me?fields=id,username` com o ID canônico retornado por `GET /17841454587986765?fields=id`, usando o mesmo token. Na integração de 27/09/2026, ambos resolveram para `25585141051165365`. Esse resultado não substitui `ACCOUNT_ID=17841454587986765`, que continua sendo o identificador usado nas mensagens. O ID canônico não é fixado no código; divergência entre os endpoints bloqueia a execução.

O Direct consulta até 20 mensagens por conversa. Na primeira varredura, amplia a janela até 26/09/2026 às 17:37 de Maceió. A limitação da Meta impede garantir recuperação de mensagens anteriores às 20 últimas: `conversas_limite_20` sinaliza essa condição. Uma recuperação concluída significa varredura concluída da API disponível.

O estado contém cursores retomáveis, lease de 3 minutos e os resultados `ultima_sync`, `ultima_sync_comentarios` e `sync_ultima_tentativa`. A invocação usa até aproximadamente 75 segundos. Resposta 202 indica trabalho parcial ou outra execução ativa; 207 indica falha parcial. O cron retoma os cursores na chamada seguinte. A hora exibida no cabeçalho só avança após completar a varredura do Direct. Cursores armazenam somente `after`, nunca URLs com token.

Na revisão `r2`, limpar um cursor serializa explicitamente o valor JSON `null` antes do cast para `jsonb`. Isso corrige o SQLSTATE `23502` encontrado na primeira integração: `postgres.js` enviava `sql.json(null)` como NULL SQL, embora `atendimento.estado.valor` seja NOT NULL. O reparo vale tanto para Direct quanto para comentários e permite concluir a varredura sem perder os dados já gravados. Erros de banco passam a informar apenas `db_<SQLSTATE>`, sem detalhes de linhas ou dados pessoais.

A sincronização guarda `origemSync:true`, `processingStatus:'claude'` e o instante real da mensagem. A conversa usa IGSID em `external_thread_id`, como o webhook; o ID da Conversations API fica em `metadata.instagramConversationId`. O índice único de `external_message_id` impede duplicação inclusive quando o webhook grava ao mesmo tempo. Ecos existentes conservam a origem já reconhecida pelo sistema.

Na revisão `r3`, somente erro Meta `100`, subcódigo `33`, no **detalhe de uma conversa** permite avançar para a próxima. A página continua sujeita ao tratamento normal de erro; não se descarta uma página inteira. O cursor persiste a próxima posição e hashes das lacunas para contagem sem IDs. `sync_direct_diagnostico` guarda apenas etapa, código, subcódigo e quantidade. Ao chegar ao fim com lacunas, `direct=true` significa varredura encerrada, enquanto `direct_com_lacunas=true`, `parcial=true` e `recuperacao_inicial.concluida=false` deixam explícito que o histórico está incompleto. Outros erros de parâmetro, permissão ou autenticação não são convertidos em sucesso.

Na revisão `r4`, a leitura de uma página de conversas pode esperar até 25 s, ainda dentro do orçamento global da execução. O limite de 10 s estava interrompendo repetidamente uma página profunda com `tempo_esgotado`; o cursor voltou a avançar após a mudança. As outras consultas mantêm 10 s.

Inbound já existente passa por enriquecimento sob bloqueio da linha: preenche referências, anexos e caminhos ausentes, preservando texto já preenchido, transcrição, estado humano, origem e arquivos existentes. IDs conflitantes não são combinados. Username válido também é preservado. `mensagens_enriquecidas` registra o número de recuperações efetivas, sem contar repetição idêntica. Opt-out explícito em texto recuperado ou transcrição já salva entra em `ai_optouts` na mesma transação, pelo índice `(channel, external_user_id)`, sem substituir recusa já registrada. Mensagens da loja não geram opt-out.

Stories mantêm `storyReference` para o gatilho de prefetch. Posts/reels usam `postReference`. Fotos/áudios/vídeos são guardados no bucket com caminhos determinísticos. Vídeo usa `message_type='document'`, conforme a constraint atual, e `raw_payload.mediaType='video'`; havendo capa da Meta, `videoFramePath` aponta para a imagem. Se a API não fornecer capa, o lote deve mostrar `sem imagem` e o usuário do Instagram. Não há promessa de reconstrução de mídia expirada.

`raw_payload.mediaCache.sha256` contém o SHA-256 dos bytes efetivamente baixados. O nome do arquivo combina o hash do ID da mensagem e o hash do conteúdo; isso permite repetir uploads sem associar um hash novo a um arquivo antigo. O enriquecimento só acrescenta hash a um cache já salvo quando o caminho também coincide.

Comentários: varre posts/reels publicados nos últimos 90 dias, guarda comentários dos últimos 7 dias e pagina também as respostas antes de considerar ausência da loja. O estado `comentarios_permissao` marca `sem_permissao` quando a Meta confirma falta de acesso. A função preserva `loja_respondeu=true` já registrado por um envio, evitando regressão por leitura atrasada da API.

Validação local, sem rede externa nem dados de clientes:

```powershell
node --test atendimento/supabase/functions/atendimento-sync/domain.test.mjs atendimento/supabase/functions/atendimento-sync/enrichment.test.mjs atendimento/supabase/functions/atendimento-sync/recovery.test.mjs atendimento/supabase/functions/atendimento-registrar-stories/domain.test.mjs
npx --yes deno check --lock=atendimento/supabase/functions/atendimento-sync/deno.lock atendimento/supabase/functions/atendimento-sync/index.ts atendimento/supabase/functions/atendimento-registrar-stories/index.ts
npx --yes deno test --allow-env --lock=atendimento/supabase/functions/atendimento-sync/deno.lock atendimento/supabase/functions/atendimento-sync/runtime_test.ts
```

Referências consultadas: [Edge Functions e Postgres](https://supabase.com/docs/guides/functions/connect-to-postgres), [Storage em Edge Functions](https://supabase.com/docs/guides/functions/ephemeral-storage), briefing versionado de 27/09/2026 e contratos do webhook congelado. A integração com a conta real deve ser avaliada pelo estado `recuperacao_inicial` e pelas lacunas; recuperar algumas mensagens não comprova conclusão da varredura.
