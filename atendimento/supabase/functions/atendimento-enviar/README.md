# atendimento-enviar

Worker de Direct e respostas públicas a comentários do Instagram. Não escreve respostas nem escolhe clientes: consome exclusivamente a fila validada por `atendimento.responder`.

## Configuração

No `supabase/config.toml` do projeto:

```toml
[functions.atendimento-enviar]
verify_jwt = false
```

O próprio handler exige `x-ai-followup-token` e valida o valor com `public.ai_followup_valid` antes de acessar a fila. O segredo nunca é retornado ou registrado. A função não aceita destinos nem mensagens no corpo.

Variáveis usadas:

| Variável | Uso |
| --- | --- |
| `SUPABASE_DB_URL` | Conexão Postgres fornecida pelo ambiente Supabase; obrigatória. TLS exigido, cinco conexões, statements preparados desativados. |
| `INSTAGRAM_TOKEN` | Reserva somente se `public.ai_meta_token_get()` não devolver um token utilizável. |
| `INSTAGRAM_ACCOUNT_ID` | Conta da loja; padrão `17841454587986765`. |
| `META_GRAPH_VERSION` | Versão; padrão `v25.0`, conforme briefing. |

`AI_SENDING_ENABLED` não é alterado nem utilizado como habilitação desta fila humana assistida. A autorização vem do modo `claude`, da fila e das guardas SQL.

## Chamadas

- `POST {}` ou `POST {"action":"tick"}`: processa a fila autorizada.
- `POST {"action":"verify"}`: confere autenticação, disponibilidade do token e modo; faz **zero claims e zero chamadas à Meta**. Não testa a validade do token na Meta.
- Outros métodos, corpos, campos e ações são rejeitados.

O resultado lista `lote`, `n`, `parte` e `status`. `enviados` só conta partes aceitas pela Meta **e** confirmadas no banco. `registro_pendente` indica falha ao registrar o resultado; se a Meta havia devolvido um id, inclui `metaAceitou:true`. Nesse caso, não há nova tentativa de envio.

## Contrato com o banco

1. `atendimento.claim_envio()` é a única origem de mensagens. Deve persistir um `owner` e retornar `lote`, `n` textual, `parte`, `texto`, `tipo`, `recipient`, `commentId`, `conversationId`, `owner` e `enviarApos`. Campos inválidos impedem o POST.
2. `atendimento.envio_autorizado(lote,n,parte,owner)` roda imediatamente antes do POST. Confere dono/lease, modo, mensagem nova, resposta da equipe, janela, opt-out e estado do comentário. `false` impede envio; o worker consulta o status já gravado sem sobrescrevê-lo.
3. `atendimento.concluir_envio(lote,n,parte,owner,message_id,erro)` confirma a resposta. Deve ser idempotente para o mesmo dono/resultado e tratar o prefixo `meta_delivery_unknown:` como `incerto`.
4. O SQL deve bloquear partes posteriores até a anterior estar `enviado`, agendar a próxima em pelo menos três segundos após a confirmação e impedir claims concorrentes para a mesma conversa/comentário. Casos incertos de outros lotes precisam continuar bloqueados.

Antes de cada POST de comentário, o worker consulta `/me` (`id,username`) e todas as páginas de `/{commentId}/replies` (`id,username`). Uma resposta da loja bloqueia o envio, atualiza `comentarios.loja_respondeu` e passa pela guarda SQL existente para registrar `equipe_respondeu`. Usa o username atual e, se devolvidos, IDs configurado/canônico em `from`; nunca depende apenas do último sync. Falha de acesso, timeout, autor não identificável, paginação inválida/repetida ou varredura incompleta registra `comentario_nao_verificado`, sem POST. A leitura tem limite total de 15 segundos e 100 páginas; atingir o limite bloqueia. Só cursores são reutilizados, mantendo o token fora das URLs. Após a leitura, as guardas SQL e o prazo da execução são conferidos novamente.

O schema `atendimento` permanece fora da API REST. O adaptador usa consultas parametrizadas por Postgres direto. Nenhuma tabela de catálogo é modificada.

## Concorrência e resultados incertos

São cinco consumidores por invocação, com até 30 tentativas de claim. O limite global entre invocações é aplicado no SQL. Depois de uma confirmação, o consumidor aguarda três segundos para buscar a próxima parte. `enviar_apos` no banco garante o intervalo também entre workers e execuções diferentes. Rede lenta ou fila concorrente podem aumentar a espera.

Cada parte gera **no máximo um POST à Meta**. Erros HTTP 4xx com código Meta ficam como `erro`; timeout, conexão interrompida, 408, 5xx, resposta ilegível/grande e 2xx sem id ficam como `incerto`. Corpo da resposta e mensagens de exceção não são registrados para evitar exposição de tokens ou dados da cliente.

Somente a confirmação SQL é repetida, uma vez, porque ela é idempotente. A fila incerta exige conferência do histórico real antes de qualquer nova autorização. O worker não pode garantir transação única entre Meta e Postgres; o estado incerto é a proteção contra duplicação nessa fronteira.

O handler reserva até 75 segundos desde a entrada para a execução, com margem para o POST (15 segundos) e confirmações SQL (10 segundos cada). Não aceita novos envios perto desse limite. Trabalho remanescente continua no próximo disparo da fila. Não usa `waitUntil`: a resposta HTTP representa o processamento observado nessa chamada.

## Verificação local

Na pasta desta função:

```powershell
node --test core.test.mjs
npx --yes deno@2.9.6 check --config deno.json index.ts
```

Os 29 testes cobrem autenticação, ensaio sem claim, payload indevido, token renovado/reserva, ausência de claim, pausa/revalidação, destinos Direct/comentário, conferência paginada das respostas da loja, bloqueio por leitura incompleta ou prazo, ordem/intervalo, limite de concorrência, confirmação após a Meta, erro conhecido, envio incerto e confirmação SQL idempotente. Todos usam banco e HTTP falsos. `deno.lock` fixa `postgres@3.4.7` com integridade.

Versão 2 publicada em 27/09/2026; uma chamada autenticada com fila vazia confirmou `enviados=0` e a revisão `atendimento-enviar-20260928-r2`. Os endpoints de leitura `/me` e `/replies?fields=id,username` responderam 200 na conta atual. A validação de bloqueio e resposta pública com comentário da conta pessoal do dono ainda depende desse teste real.

Documentação consultada: [autenticação de Edge Functions](https://supabase.com/docs/guides/functions/auth), [conexão Postgres](https://supabase.com/docs/guides/functions/connect-to-postgres) e [changelog](https://supabase.com/changelog).
