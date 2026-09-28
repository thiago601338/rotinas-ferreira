# Atendimento do Instagram — operação e proteção

Fonte funcional: `atendimento/BRIEFING.md`. A execução diária está em `.claude/skills/responder-business-suite-ferreira/SKILL.md`.

## Fluxo

1. O webhook grava mensagens e ecos. O `atendimento-sync` recupera mensagens perdidas e lê comentários, com cursor para continuar varreduras grandes. Executa a cada 10 minutos no modo `claude`; `atendimento.sincronizar()` pede uma execução adicional. A API de Conversas só oferece as 20 mensagens mais recentes por conversa, portanto uma recuperação antiga pode ter lacunas inevitáveis.
2. `atendimento.pendentes()` entrega um lote curto, com contexto, preço e estoque atuais. Mídias sem peça vão para uma folha JPEG. `atendimento.produto()` pesquisa candidatos. `atendimento.folha_produtos()` mostra fotos do cadastro.
3. `atendimento.responder(lote,itens,true)` valida sem gravar ou enviar. Sem o terceiro argumento, a função aceita ou rejeita cada item, guarda tratamento único e enfileira as partes. `atendimento-enviar` só envia após conferir novamente o estado da conversa. `atendimento.status(lote)` confirma o resultado por parte; estado `incerto` exige apuração, nunca reenvio automático.
4. O modo `claude` impede a IA antiga de enfileirar, despachar ou fazer acompanhamento humano. `AI_SENDING_ENABLED` permanece `false`. O pré-processamento de áudio pode transcrever; os demais caminhos da OpenAI ficam desativados nesse modo.

## Limites de atendimento

- Toda afirmação comercial precisa vir do lote ou de `atendimento.produto()`, conferidos contra o cadastro atual. Quando houver dúvida sobre peça ou cor, pular `sem_peca`; quando faltar dado, pular `sem_dado`.
- A validação do `responder` compara cada `R$` ao preço ou valor à vista da peça identificada, nunca a qualquer produto do catálogo. Se o item não tiver vínculo inequívoco, informar `produto` com o SKU conferido; SKU conflitante com story, post ou foto já vinculados é rejeitado.
- Pagamento, frete, entrega, reserva, troca, desconto negociado, reclamação, dados pessoais e pedido de pessoa ficam com a equipe. A IA pode responder parcelamento e valor à vista presentes no lote.
- Resposta nova da equipe, mensagem nova da cliente, opt-out e janela da API vencida barram o envio. A janela da API é de 24 horas; `#j` depende de envio manual pelo Instagram e confirmação por eco.
- Comentários exigem leitura atual de todas as páginas de respostas na Meta antes do POST. O `atendimento-enviar` identifica a loja pelo `/me` atual e pelo autor das respostas, grava `loja_respondeu` quando encontra resposta da equipe e revalida as guardas SQL depois da leitura. Falha de permissão, identidade/autor ausente, timeout, cursor inválido ou varredura incompleta bloqueia com `comentario_nao_verificado`; nunca confiar apenas no último sync nem contornar o bloqueio com envio manual.
- No Direct, eco de envio pela API só é atribuído ao Claude pelo ID externo confirmado pela Meta; texto idêntico de uma resposta da equipe continua sendo resposta da equipe. Igualdade de texto vale apenas para o fluxo manual `pelo_instagram`. Se `status` mostrar `incerto` ou `registro_pendente`, apurar o eco/ID antes de qualquer nova tentativa.
- Nunca enviar teste para cliente real. Primeiro receber uma DM e um comentário da conta pessoal do dono, formar lote, ensaiar e conferir os retornos. Um clique, uma fila ou uma resposta HTTP sem eco não comprovam entrega.
- O @ da cliente só deve aparecer nos casos de mídia sem imagem e fora da janela; não expor nomes ou telefones no lote nem em relatórios.

## Stories publicados

`atendimento-registrar-stories` vincula stories a SKU e cor somente quando a janela de publicação e a quantidade de mídias correspondem. Para letra com peças diferentes, exige manifesto por mídia. Se o registro falhar, a publicação continua válida e o vínculo fica pendente para diagnóstico; não republicar a letra para corrigir o cadastro.

## Verificação e recuperação

- `select atendimento.modo();` consulta o modo. `select atendimento.modo('claude');` ativa a rotina; `select atendimento.modo('ia');` restaura o fluxo anterior. A troca é registrada. Não alterar o secret `AI_SENDING_ENABLED`.
- Cabeçalho `sinc. há nunca` ou antigo: conferir `atendimento.estado` (`sync_ultima_tentativa`, `ultima_sync`, `ultima_sync_comentarios`, cursores e `comentarios_permissao`) e pedir nova sincronização. Pedido aceito por `pg_net` ainda não significa execução concluída.
- Ao limpar um cursor em `atendimento.estado`, gravar JSON `null`, não SQL NULL. O serializador `postgres.js` também não deve receber uma string JSON seguida de `::jsonb`, pois isso grava uma string JSON em vez do objeto. Conferir `jsonb_typeof(valor)` ao diagnosticar retomadas.
- Se comentários estiverem sem permissão da Meta, continuar apenas o Direct e registrar a pendência. Se houver erro parcial, conservar o cursor; não marcar como sincronizado até uma varredura completa.
- O token da Meta vem de `ai_meta_token_get()` com o secret antigo como reserva. Na API Instagram Login, `/me` pode devolver um ID canônico diferente do ID presente nas mensagens; a checagem compara a resolução de `/me` e do ID configurado, e a direção das mensagens usa o ID configurado.
- As funções `atendimento.*` são restritas a `service_role`; as Edge Functions usam segredo próprio e a folha usa token temporário. Nunca registrar ou publicar tokens, URLs assinadas ou conteúdo de cliente em logs de diagnóstico.
