import { ACCOUNT_ID, list, pageAfter } from '../atendimento-sync/domain.mjs';
import { Graph, verifiedAccount } from '../atendimento-sync/graph.mjs';
import { activeToken, authorized, body, database, json, log, safeError } from '../atendimento-sync/runtime.ts';
import { mapStories, validateRegistration } from './domain.mjs';

const REVISION = 'atendimento-registrar-stories-20260927-r1';

async function resolveProducts(sql: any, input: any) {
  for (const item of input.midias) {
    const products = await sql`select id,sku from public.products where deleted_at is null and lower(status)='ativo'
      and (${item.product_id}::uuid is null or id=${item.product_id}::uuid)
      and (${item.sku}::text is null or upper(sku)=upper(${item.sku})) limit 2`;
    if (products.length !== 1) throw Error('produto_inativo_ou_ambiguo');
    item.product_id = products[0].id; item.sku = products[0].sku;
    if (item.cor) {
      const colors = await sql`select color from public.product_variations where product_id=${item.product_id} and public.ai_color_key(color)=public.ai_color_key(${item.cor}) order by color limit 1`;
      if (!colors.length) throw Error('cor_inexistente');
      item.cor = colors[0].color;
    }
  }
}

export async function handler(req: Request) {
  if (req.method !== 'POST') return json({ error: 'method_not_allowed' }, 405);
  let sql: any;
  try {
    sql = database();
    if (!await authorized(sql, req)) return json({ error: 'unauthorized' }, 401);
    let input;
    try { input = validateRegistration(await body(req)); } catch (error) { return json({ ok: false, error: safeError(error) }, 400); }
    try { await resolveProducts(sql, input); } catch (error) { return json({ ok: false, error: safeError(error) }, 422); }
    const digest = new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(JSON.stringify(input))));
    const requestId = [...digest].map(x => x.toString(16).padStart(2, '0')).join('');
    const previous = await sql`select story_id from public.ai_story_products where account_id=${ACCOUNT_ID} and method='postagem' and evidence->>'atendimentoRequestId'=${requestId}`;
    if (previous.length === input.n_midias) return json({ ok: true, ja_registrado: true, registrados: previous.length, revision: REVISION });
    // A leitura da API usa somente o token ativo da conta; nunca recebe token do corpo.
    const graph = new Graph(await activeToken(sql), fetch, Date.now() + 45000);
    await verifiedAccount(graph);
    let after = null, stories: any[] = [];
    do {
      const page = await graph.get('me/stories', { fields: 'id,timestamp,media_type', limit: 100, after });
      stories = stories.concat(list(page)); after = pageAfter(page);
      if (stories.length > 1000) throw Error('stories_limite_excedido');
    } while (after);
    const result = await sql.begin(async (tx: any) => {
      await tx`select pg_advisory_xact_lock(hashtextextended('atendimento-registrar-stories:'||${ACCOUNT_ID}::text,0))`;
      const repeated = await tx`select story_id from public.ai_story_products where account_id=${ACCOUNT_ID} and method='postagem' and evidence->>'atendimentoRequestId'=${requestId}`;
      if (repeated.length === input.n_midias) return { ok: true, ja_registrado: true, registrados: repeated.length };
      const ids = stories.map(s => String(s.id));
      const existing = ids.length ? await tx`select story_id from public.ai_story_products where story_id=any(${ids}::text[])` : [];
      const plan = mapStories(input, stories, existing);
      if (!plan.ok) return plan;
      // Validar novamente no mesmo instante da gravação: todos os produtos devem continuar ativos.
      await resolveProducts(tx, input);
      for (const pair of plan.pares!) {
        const evidence = { letra: input.letra, atendimentoRequestId: requestId, revision: REVISION,
          publicado_de: input.publicado_de, publicado_ate: input.publicado_ate, publicado_em: pair.story.timestamp,
          media_type: pair.story.media_type ?? null, n_midias: input.n_midias, ordem: pair.produto.ordem, sku: pair.produto.sku };
        const [inserted] = await tx`select atendimento.registrar_story(${String(pair.story.id)},${pair.produto.product_id}::uuid,${pair.produto.cor},${input.letra},${tx.json(evidence)}) ok`;
        // Qualquer falha/conflito desfaz o lote inteiro; nunca deixa meia letra associada.
        if (!inserted?.ok) throw Error('registro_concorrente_ou_produto_alterado');
      }
      return { ok: true, ja_registrado: false, registrados: plan.pares!.length };
    });
    await log(sql, result.ok ? 'atendimento_stories_registradas' : 'atendimento_stories_nao_registradas', { letra: input.letra, requestId, ...result }, result.ok ? 'info' : 'warn');
    return json({ ...result, revision: REVISION }, result.ok ? 200 : 409);
  } catch (error) {
    const code = safeError(error);
    if (sql) try { await log(sql, 'atendimento_stories_erro', { code }, 'error'); } catch { /* não exibir erro SQL/credenciais */ }
    return json({ ok: false, error: code }, 503);
  } finally { if (sql) await sql.end({ timeout: 3 }); }
}
Deno.serve(handler);
