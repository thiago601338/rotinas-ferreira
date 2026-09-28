import { REVISION, iso, list, normalizeComment, normalizeMessage, pageAfter, syncWindow, username } from './domain.mjs';
import { Graph, MetaError, verifiedAccount } from './graph.mjs';
import { activeToken, authorized, body, cacheMedia, database, json, log, mode, safeError, state } from './runtime.ts';
import { explicitOptOut, needsMediaRecovery, recoveredPatch } from './enrichment.mjs';
import { addGap, metaIssue, readConversationDetail } from './recovery.mjs';

const MEDIA_FIELDS = 'id,caption,permalink,timestamp,media_type,media_product_type,comments_count,thumbnail_url,media_url';
const COMMENT_FIELDS = 'id,text,timestamp,username,hidden,replies{id,text,timestamp,username}';

async function savedState(sql: any, key: string) {
  return (await sql`select valor from atendimento.estado where chave=${key}`)[0]?.valor ?? null;
}
async function persistMessage(sql: any, m: any, threadId: string, mediaPath: string | null) {
  return sql.begin(async (tx: any) => {
    if (await mode(tx) !== 'claude') throw Error('modo_ia');
    const metadata = { instagramConversationId: threadId, ...(m.username ? { username: m.username } : {}) };
    // O webhook usa IGSID como external_thread_id, não o ID da Conversations API.
    const [c] = await tx`insert into public.ai_conversations(channel,external_user_id,external_thread_id,customer_name,status,last_message_at,metadata)
      values('instagram',${m.customerId},${m.customerId},${m.customerName},'open',${m.at},${tx.json(metadata)})
      on conflict(channel,external_thread_id) do update set
        metadata=coalesce(ai_conversations.metadata,'{}'::jsonb)
          ||case when nullif(ai_conversations.metadata->>'instagramConversationId','') is null then jsonb_build_object('instagramConversationId',${threadId}::text) else '{}'::jsonb end
          ||case when coalesce(ai_conversations.metadata->>'username','') !~ '^[A-Za-z0-9._]{1,30}$' and ${m.username}::text is not null then jsonb_build_object('username',${m.username}::text) else '{}'::jsonb end,
        last_message_at=greatest(ai_conversations.last_message_at,excluded.last_message_at),updated_at=now()
      returning id`;
    const inserted = await tx`insert into public.ai_messages(conversation_id,direction,message_type,external_message_id,text_content,media_path,raw_payload,created_at)
      values(${c.id},${m.direction},${m.type},${m.externalId},${m.text},${mediaPath},${tx.json(m.raw)},${m.at})
      on conflict(external_message_id) where external_message_id is not null do nothing returning id`;
    let enriched = false, storedText = null;
    if (!inserted.length) {
      const [existing] = await tx`select m.*,c.channel,c.external_user_id from public.ai_messages m
        join public.ai_conversations c on c.id=m.conversation_id where m.external_message_id=${m.externalId} for update of m,c`;
      // Um ID jamais autoriza mover mensagem entre clientes ou alterar um eco/outbound.
      if (!existing || existing.channel !== 'instagram' || existing.external_user_id !== m.customerId || existing.direction !== m.direction) throw Error('identidade_mensagem_divergente');
      storedText = existing.text_content;
      const patch = recoveredPatch(existing, m, mediaPath);
      if (patch) {
        await tx`update public.ai_messages set ${tx({ ...patch, ...(patch.raw_payload ? { raw_payload: tx.json(patch.raw_payload) } : {}) })} where id=${existing.id}`;
        enriched = true;
      }
      // Conversas antigas podem ter external_thread_id diferente do webhook atual.
      if (m.username) await tx`update public.ai_conversations set metadata=coalesce(metadata,'{}'::jsonb)||jsonb_build_object('username',${m.username}::text)
        where id=${existing.conversation_id} and coalesce(metadata->>'username','') !~ '^[A-Za-z0-9._]{1,30}$'`;
    }
    let optout = false;
    if (explicitOptOut(m, storedText)) {
      const rows = await tx`insert into public.ai_optouts(channel,external_user_id,reason)
        values('instagram',${m.customerId},'pedido explícito da cliente') on conflict(channel,external_user_id) do nothing returning id`;
      optout = rows.length > 0;
      if (optout) await log(tx, 'optout', { reason: 'pedido explícito da cliente', origem: 'atendimento_sync' });
    }
    return { inserted: inserted.length > 0, enriched, optout };
  });
}

async function syncDirect(sql: any, graph: Graph, hours: number | undefined, counts: any, deadline: number) {
  const recovery = await savedState(sql, 'recuperacao_inicial');
  let cursor = await savedState(sql, 'sync_direct_cursor');
  const since = cursor?.since ?? syncWindow(hours, Date.now(), recovery?.concluida === true || recovery?.varredura_concluida === true);
  const profiles = new Map<string, string | null>();
  let after = cursor?.after ?? null, index = cursor?.index ?? 0;
  let gaps = Array.isArray(cursor?.gaps) ? cursor.gaps.filter((x: any) => typeof x === 'string' && /^[a-f0-9]{64}$/.test(x)) : [];
  counts.conversas_inacessiveis_total = gaps.length;
  while (Date.now() < deadline - 5000) {
    let page;
    try { page = await graph.get('me/conversations', { platform: 'instagram', fields: 'id,updated_time', limit: 25, after }); }
    catch (error: any) { error.operation = 'conversas_pagina'; throw error; }
    const conversations = list(page);
    for (; index < conversations.length; index++) {
      await state(sql, 'sync_direct_cursor', { since, after, index, gaps });
      if (Date.now() >= deadline - 5000) return false;
      const c = conversations[index];
      if (iso(c.updated_time) && Date.parse(c.updated_time) < Date.parse(since)) continue;
      const detail = await readConversationDetail(graph, c.id);
      if (!detail.available) {
        const next = await addGap({ gaps }, c.id);
        gaps = next.gaps;
        counts.conversas_inacessiveis++;
        counts.conversas_inacessiveis_total = gaps.length;
        await state(sql, 'sync_direct_cursor', { since, after, index: index + 1, gaps });
        await state(sql, 'sync_direct_diagnostico', { etapa: 'conversa_detalhe', codigo: 100, subcodigo: 33,
          conversas_inacessiveis: gaps.length, desde: since, at: new Date().toISOString(), acao: 'avancou_com_lacuna' });
        continue;
      }
      const messages = list(detail.detail?.messages).slice(0, 20);
      if (messages.length === 20) counts.conversas_limite_20++;
      counts.conversas_lidas++;
      for (const item of messages.sort((a: any, b: any) => Date.parse(a.created_time) - Date.parse(b.created_time))) {
        if (!iso(item.created_time) || Date.parse(item.created_time) < Date.parse(since)) continue;
        let m: any;
        try { m = normalizeMessage(item); } catch { counts.mensagens_invalidas++; continue; }
        if (!profiles.has(m.customerId)) {
          const existing = await sql`select metadata->>'username' username from public.ai_conversations where channel='instagram' and external_user_id=${m.customerId} order by updated_at desc limit 1`;
          let name = username(existing[0]?.username) ?? m.username;
          if (!name) try { name = username((await graph.get(m.customerId, { fields: 'username' })).username); } catch { counts.perfis_indisponiveis++; }
          profiles.set(m.customerId, name);
        }
        m.username = profiles.get(m.customerId) ?? null;
        const [existing] = await sql`select id,external_message_id,direction,raw_payload,media_path,text_content,message_type from public.ai_messages where external_message_id=${m.externalId} limit 1`;
        const recoverMedia = needsMediaRecovery(existing, m);
        const mediaPath = recoverMedia ? await cacheMedia(m, graph) : null;
        if (m.raw.mediaCache?.status === 'unavailable') counts.midias_indisponiveis++;
        const persisted = await persistMessage(sql, m, c.id, mediaPath);
        if (persisted.inserted) counts.mensagens_inseridas++; else counts.duplicadas++;
        if (persisted.enriched) counts.mensagens_enriquecidas++;
        if (persisted.optout) counts.optouts_registrados++;
      }
      await state(sql, 'sync_direct_cursor', { since, after, index: index + 1, gaps });
    }
    after = pageAfter(page); index = 0;
    if (!after) {
      await state(sql, 'sync_direct_cursor', null);
      if (!recovery?.concluida && !recovery?.varredura_concluida) await state(sql, 'recuperacao_inicial', { concluida: gaps.length === 0, varredura_concluida: true,
        conversas_inacessiveis: gaps.length, desde: since, at: new Date().toISOString(), limite_por_conversa: 20 });
      return true;
    }
    await state(sql, 'sync_direct_cursor', { since, after, index, gaps });
  }
  return false;
}

async function syncComments(sql: any, graph: Graph, counts: any, deadline: number, me: any) {
  if (!username(me.username)) throw Error('username_loja_indisponivel');
  // Consultar permissões explicitamente quando a conta disponibiliza essa edge.
  try {
    const permissions = list(await graph.get('me/permissions'));
    if (permissions.length && !permissions.some((p: any) => p.permission === 'instagram_business_manage_comments' && p.status === 'granted')) {
      await state(sql, 'comentarios_permissao', { status: 'sem_permissao', at: new Date().toISOString() }); return true;
    }
  } catch (error) {
    if (!(error instanceof MetaError) || ![100, 10, 200].includes(error.code)) throw error;
    // Alguns fluxos não oferecem /permissions; o GET /comments abaixo confirma acesso efetivo.
  }
  let cursor = await savedState(sql, 'sync_comentarios_cursor');
  let after = cursor?.after ?? null, index = cursor?.index ?? 0;
  const commentCutoff = Date.now() - 7 * 86400000, mediaCutoff = Date.now() - 90 * 86400000;
  let permissionVerified = false;
  while (Date.now() < deadline - 5000) {
    const page = await graph.get('me/media', { fields: MEDIA_FIELDS, limit: 25, after });
    const media = list(page);
    for (; index < media.length; index++) {
      const post = media[index];
      if (iso(post.timestamp) && Date.parse(post.timestamp) < mediaCutoff) continue;
      let commentAfter = cursor?.media_id === post.id ? cursor?.comment_after ?? null : null;
      let commentIndex = cursor?.media_id === post.id ? cursor?.comment_index ?? 0 : 0;
      while (true) {
        await state(sql, 'sync_comentarios_cursor', { after, index, media_id: post.id, comment_after: commentAfter, comment_index: commentIndex });
        if (Date.now() >= deadline - 5000) return false;
        let comments;
        try { comments = await graph.get(`${post.id}/comments`, { fields: COMMENT_FIELDS, limit: 100, after: commentAfter }); }
        catch (error) {
          if (error instanceof MetaError && error.permissionDenied) {
            await state(sql, 'comentarios_permissao', { status: 'sem_permissao', at: new Date().toISOString(), codigo: error.code }); return true;
          }
          throw error;
        }
        permissionVerified = true;
        const rows = list(comments);
        for (; commentIndex < rows.length; commentIndex++) {
          const c = rows[commentIndex];
          if (!iso(c.timestamp) || Date.parse(c.timestamp) < commentCutoff) continue;
          await state(sql, 'sync_comentarios_cursor', { after, index, media_id: post.id, comment_after: commentAfter, comment_index: commentIndex });
          let replies = list(c.replies), replyAfter = pageAfter(c.replies);
          while (replyAfter && !replies.some((r: any) => username(r.username)?.toLowerCase() === me.username.toLowerCase())) {
            const next = await graph.get(`${c.id}/replies`, { fields: 'id,text,timestamp,username', limit: 100, after: replyAfter });
            replies = replies.concat(list(next)); replyAfter = pageAfter(next);
          }
          const row = normalizeComment(c, post, me.username, replies);
          await sql.begin(async (tx: any) => {
            if (await mode(tx) !== 'claude') throw Error('modo_ia');
            await tx`insert into atendimento.comentarios ${tx(row)} on conflict(id) do update set
              media_caption=excluded.media_caption,media_url=excluded.media_url,media_type=excluded.media_type,
              texto=excluded.texto,username=excluded.username,hidden=excluded.hidden,
              loja_respondeu=atendimento.comentarios.loja_respondeu or excluded.loja_respondeu,atualizado_em=now()`;
          });
          counts.comentarios_lidos++;
        }
        commentAfter = pageAfter(comments); commentIndex = 0;
        if (!commentAfter) break;
      }
      await state(sql, 'sync_comentarios_cursor', { after, index: index + 1 });
      cursor = null;
    }
    after = pageAfter(page); index = 0;
    if (!after) {
      await state(sql, 'sync_comentarios_cursor', null);
      // Sem posts, não afirmar que a permissão foi confirmada por uma leitura inexistente.
      await state(sql, 'comentarios_permissao', { status: permissionVerified ? 'ok' : 'nao_verificada', at: new Date().toISOString() });
      return true;
    }
  }
  return false;
}

export async function handler(req: Request) {
  if (req.method !== 'POST') return json({ error: 'method_not_allowed' }, 405);
  let sql: any; let owner: string | null = null;
  try {
    sql = database();
    if (!await authorized(sql, req)) return json({ error: 'unauthorized' }, 401);
    let input;
    try { input = await body(req); syncWindow(input.horas, Date.now(), true); } catch { return json({ error: 'parametros_invalidos' }, 400); }
    if (await mode(sql) !== 'claude') return json({ ok: true, executada: false, motivo: 'modo_ia' });
    owner = crypto.randomUUID();
    const lease = await sql`insert into atendimento.estado(chave,valor) values('sync_lease',jsonb_build_object('owner',${owner}::text,'ate',now()+interval '3 minutes'))
      on conflict(chave) do update set valor=excluded.valor,atualizado_em=now()
      where (atendimento.estado.valor->>'ate')::timestamptz<now() returning chave`;
    if (!lease.length) return json({ ok: true, executada: false, motivo: 'em_andamento' }, 202);
    const started = Date.now(), deadline = started + 75000;
    const graph = new Graph(await activeToken(sql), fetch, deadline);
    const me = await verifiedAccount(graph, 'id,username');
    const counts = { conversas_lidas: 0, conversas_inacessiveis: 0, conversas_inacessiveis_total: 0, mensagens_inseridas: 0, mensagens_enriquecidas: 0, optouts_registrados: 0, duplicadas: 0, mensagens_invalidas: 0, perfis_indisponiveis: 0, midias_indisponiveis: 0, conversas_limite_20: 0, comentarios_lidos: 0 };
    let direct = false, comments = false, directError = null, commentError = null;
    let directIssue = null;
    try { direct = await syncDirect(sql, graph, input.horas, counts, started + 43000); }
    catch (e: any) { directError = safeError(e); directIssue = metaIssue(e, e?.operation ?? 'direct'); }
    try { if (await mode(sql) === 'claude') comments = await syncComments(sql, graph, counts, deadline, me); }
    catch (e) { commentError = safeError(e); }
    const result = { at: new Date().toISOString(), direct, comentarios: comments, parcial: !direct || !comments || counts.conversas_inacessiveis_total > 0,
      direct_com_lacunas: counts.conversas_inacessiveis_total > 0, direct_diagnostico: directIssue,
      direct_erro: directError, comentarios_erro: commentError, ...counts, limite_historico_por_conversa: 20, posts_dias: 90, revision: REVISION };
    await state(sql, 'sync_ultima_tentativa', result);
    // O cabeçalho só diz "sincronizado" depois de uma varredura concluída do Direct.
    if (direct) await state(sql, 'ultima_sync', result);
    if (comments) await state(sql, 'ultima_sync_comentarios', result);
    await log(sql, 'atendimento_sync', result, directError || commentError ? 'warn' : 'info');
    return json({ ok: !directError && !commentError, ...result }, directError || commentError ? 207 : result.parcial ? 202 : 200);
  } catch (error) {
    const code = safeError(error);
    if (sql) try { await log(sql, 'atendimento_sync_erro', { code }, 'error'); } catch { /* sem log de credenciais */ }
    return json({ ok: false, error: code }, 503);
  } finally {
    if (sql) {
      if (owner) try { await sql`delete from atendimento.estado where chave='sync_lease' and valor->>'owner'=${owner}`; } catch { /* lease expira */ }
      await sql.end({ timeout: 3 });
    }
  }
}
Deno.serve(handler);
