# fonte-atual — cópia de produção de 27/09/2026 (somente consulta)

Tirado do Supabase `nailfzcujyxydqldktgg` em 27/09/2026. Produção continua sendo a fonte da verdade.

- `supabase/functions/meta-webhook/` e `supabase/functions/ai-test/`: arquivos da Edge Function `meta-webhook`
  (versão 50) do jeito que estão publicados. O `meta-webhook` importa módulos de `../ai-test/`.
  A guarda que hoje descarta as mensagens está em `meta-webhook/lib/pipeline-instagram.ts` (`handleInstagramMessage`)
  e `meta-webhook/lib/pipeline.ts` (`handleMessage`).
- `worker-v6-modulos.txt`: os módulos do `instagram-turn-worker-v6` guardados na tabela `public.ai_worker_sources`
  (bundle `instagram-turn-worker-v6`). Referência para o envio seguro (`send()` em `index.mjs`, RPCs
  `ai_meta_token_get`, `ai_delivery_allowed`, `ai_begin_send`), textos da loja (`voice.mjs`) e parcelamento
  (`installments.mjs`).
- `sql/estado-do-banco.sql`: definição das funções `ai_*` e `ferreira_*` (schemas public e private), índices das
  tabelas `ai_*`, os crons e as colunas das tabelas `ai_*`, `ig_*`, `products`, `product_variations` e
  `private.instagram_runtime_credentials`.

Outras funções (por exemplo `instagram-story-prefetch`, `instagram-audio-preprocess`, `instagram-token-guardian`) podem
ser baixadas com `npx supabase functions download <nome> --project-ref nailfzcujyxydqldktgg`.
