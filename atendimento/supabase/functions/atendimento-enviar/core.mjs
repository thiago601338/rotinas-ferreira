// Núcleo sem dependências de rede implícitas: os testes fornecem banco e Meta falsos.
import { commentReplyGuard } from './comment-guard.mjs';
export const REVISION = 'atendimento-enviar-20260928-r2';
const UUID = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
const META_ID = /^\d{5,40}$/;
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
/** @param {string} _name @returns {string | undefined} */
const emptyEnv = (_name) => undefined;

function json(body, status = 200) {
  return Response.json(body, { status, headers: { 'Cache-Control': 'no-store' } });
}

async function boundedJson(response, limit = 65536) {
  if (!response.body) throw new Error('empty_body');
  const reader = response.body.getReader();
  const chunks = [];
  let total = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      total += value.byteLength;
      if (total > limit) throw new Error('body_limit');
      chunks.push(value);
    }
  } finally {
    await reader.cancel().catch(() => {});
  }
  const bytes = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  return JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes));
}

function validToken(value) {
  return typeof value === 'string' && value.length >= 40 && value.length <= 4096 && !/\s/.test(value);
}

function identityValid(job) {
  return job && typeof job.lote === 'string' && job.lote.length <= 80
    && typeof job.n === 'string' && /^(?:\d{1,3}|c\d{1,3})$/.test(job.n)
    && Number.isInteger(job.parte) && job.parte >= 1 && job.parte <= 6
    && UUID.test(job.owner ?? '');
}

function validateJob(job, now) {
  if (!identityValid(job)) return 'claim_identidade_invalida';
  if (!['direct', 'comentario'].includes(job.tipo)) return 'claim_tipo_invalido';
  if (typeof job.texto !== 'string' || !job.texto.trim() || [...job.texto].length > 950) return 'claim_texto_invalido';
  if (job.tipo === 'direct' && (!META_ID.test(job.recipient ?? '') || !UUID.test(job.conversationId ?? ''))) return 'claim_destinatario_invalido';
  if (job.tipo === 'comentario' && (!META_ID.test(job.commentId ?? '') || job.parte !== 1)) return 'claim_comentario_invalido';
  // O banco só entrega linhas vencidas. Rejeita contratos antigos sem esse campo.
  const dueAt = Date.parse(job.enviarApos);
  if (!Number.isFinite(dueAt) || dueAt > now + 1000) return 'claim_horario_invalido';
  return null;
}

/** Exatamente uma tentativa de POST. Resposta ambígua nunca é repetida. */
export async function sendToMeta(job, token, config, fetcher = fetch, beforePost = async () => null) {
  if (job.tipo === 'comentario') {
    const error = await commentReplyGuard(job, token, config, fetcher, boundedJson);
    if (error) return { messageId: null, error };
  }
  // A leitura paginada pode levar segundos: modo e lease precisam ser conferidos
  // novamente depois dela, ainda antes de qualquer efeito externo.
  let blocked;
  try { blocked = await beforePost(); }
  catch { blocked = 'autorizacao_nao_verificada'; }
  if (blocked) return { messageId: null, error: blocked };
  const target = job.tipo === 'direct' ? `${config.accountId}/messages` : `${job.commentId}/replies`;
  const body = job.tipo === 'direct'
    ? { recipient: { id: job.recipient }, message: { text: job.texto } }
    : { message: job.texto };
  try {
    const response = await fetcher(`https://graph.instagram.com/${config.version}/${target}`, {
      method: 'POST', redirect: 'error', signal: AbortSignal.timeout(15000),
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    let data;
    try { data = await boundedJson(response); }
    catch { return { messageId: null, error: 'meta_delivery_unknown:resposta_ilegivel' }; }
    const id = data?.message_id ?? data?.id;
    if (response.ok && !data?.error && typeof id === 'string' && id.length > 0 && id.length <= 512 && !/\s/.test(id)) {
      return { messageId: id, error: null };
    }
    const code = Number.isInteger(data?.error?.code) ? data.error.code : response.status;
    const subcode = Number.isInteger(data?.error?.error_subcode) ? `_${data.error.error_subcode}` : '';
    // 408/5xx podem ocorrer depois da aceitação; 2xx sem id também não prova entrega.
    if (response.status === 408 || response.status >= 500 || response.ok || !Number.isInteger(data?.error?.code)) {
      return { messageId: null, error: `meta_delivery_unknown:http_${response.status}_code_${code}${subcode}` };
    }
    return { messageId: null, error: `meta_${code}${subcode}` };
  } catch {
    // Não propaga URL, texto da exceção ou corpo da Meta, que podem conter segredos.
    return { messageId: null, error: 'meta_delivery_unknown:conexao_ou_timeout' };
  }
}

async function finish(db, job, outcome, delay) {
  // Apenas repetir a confirmação local idempotente é seguro, nunca o POST externo.
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      const status = await db.complete(job, outcome);
      if (['enviado', 'erro', 'incerto', 'cancelado'].includes(status)) return status;
      return 'registro_pendente';
    } catch {
      if (attempt === 0) await delay(250);
    }
  }
  return 'registro_pendente';
}

export async function drain(db, token, config, options = {}) {
  const now = options.now ?? Date.now;
  const delay = options.sleep ?? sleep;
  const fetcher = options.fetch ?? fetch;
  const deadline = options.deadlineAt ?? now() + 65000;
  const results = [];
  let claims = 0;
  let databaseFailure = false;

  async function worker() {
    // Reserva 35 s para POST (15 s) e duas confirmações SQL (até 10 s cada).
    while (now() < deadline - 35000 && claims < 30 && !databaseFailure) {
      claims++;
      let job;
      try { job = await db.claim(); }
      catch { databaseFailure = true; return; }
      if (!job) return;
      const invalid = validateJob(job, now());
      if (!identityValid(job)) { databaseFailure = true; return; }
      let outcome = { messageId: null, error: invalid };
      if (!invalid) {
        // Repete as guardas no banco imediatamente antes do POST: modo, lease,
        // mensagem nova, resposta da equipe, janela e opt-out podem ter mudado.
        let authorized;
        try { authorized = await db.deliveryAllowed(job); }
        catch { outcome.error = 'autorizacao_nao_verificada'; }
        if (authorized === false) {
          let status;
          try { status = await db.status(job); }
          catch { status = 'registro_pendente'; databaseFailure = true; }
          results.push({ lote: job.lote, n: job.n, parte: job.parte, status: status ?? 'bloqueado', code: 'envio_nao_autorizado' });
          continue;
        }
        if (authorized === true) {
          if (databaseFailure || now() >= deadline - 35000) outcome.error = 'execucao_interrompida_antes_envio';
          else outcome = await sendToMeta(job, token, config, fetcher, async () => {
            if (databaseFailure || now() >= deadline - 35000) return 'execucao_interrompida_antes_envio';
            if (job.tipo === 'comentario' && !await db.deliveryAllowed(job)) return 'envio_nao_autorizado';
            return null;
          });
        } else if (!outcome.error) outcome.error = 'autorizacao_nao_verificada';
      }
      if (outcome.error === 'equipe_respondeu') {
        try {
          await db.commentReplied(job);
          if (!await db.deliveryAllowed(job)) outcome.error = 'envio_nao_autorizado';
        } catch { outcome.error = 'comentario_equipe_registro_nao_verificado'; }
      }
      if (outcome.error === 'envio_nao_autorizado') {
        let status;
        try { status = await db.status(job); }
        catch { status = 'registro_pendente'; databaseFailure = true; }
        results.push({ lote: job.lote, n: job.n, parte: job.parte, status: status ?? 'bloqueado', code: 'envio_nao_autorizado' });
        continue;
      }
      const status = await finish(db, job, outcome, delay);
      results.push({ lote: job.lote, n: job.n, parte: job.parte, status,
        ...(outcome.error ? { code: outcome.error } : {}),
        ...(status === 'registro_pendente' && outcome.messageId ? { metaAceitou: true } : {}) });
      if (status === 'registro_pendente') databaseFailure = true;
      // O SQL move enviar_apos da próxima parte para pelo menos 3 s após a aceitação.
      // Esta espera mantém um consumidor ativo enquanto a próxima parte ainda não vence.
      if (status === 'enviado') await delay(3000);
    }
  }

  await Promise.all(Array.from({ length: 5 }, () => worker()));
  return { ok: !databaseFailure, revision: REVISION, enviados: results.filter((r) => r.status === 'enviado').length,
    incertos: results.filter((r) => ['incerto', 'registro_pendente'].includes(r.status)).length,
    ...(databaseFailure ? { code: 'banco_ou_registro_indisponivel' } : {}), resultados: results };
}

/** openDatabase é chamado somente após validar método e formato do segredo. */
export function createHandler({ openDatabase, env = emptyEnv, fetch: fetcher = fetch, sleep: delay = sleep, now = Date.now }) {
  return async function handler(request) {
    const deadlineAt = now() + 75000;
    if (request.method !== 'POST') return json({ error: 'method_not_allowed' }, 405);
    const token = request.headers.get('x-ai-followup-token') ?? '';
    if (!/^[a-f0-9]{64}$/.test(token)) return json({ error: 'unauthorized' }, 401);
    let db;
    try {
      db = await openDatabase();
      if (!await db.authorize(token)) return json({ error: 'unauthorized' }, 401);
      let body;
      try { body = await boundedJson(new Response(request.body), 1024); }
      catch { return json({ error: 'invalid_body' }, 400); }
      if (!body || typeof body !== 'object' || Array.isArray(body)
        || Object.keys(body).some((key) => key !== 'action')
        || (body.action !== undefined && !['tick', 'verify'].includes(body.action))) {
        return json({ error: 'invalid_action' }, 400);
      }
      const config = { accountId: env('INSTAGRAM_ACCOUNT_ID') || '17841454587986765', version: env('META_GRAPH_VERSION') || 'v25.0' };
      if (!META_ID.test(config.accountId) || !/^v\d+\.\d+$/.test(config.version)) return json({ error: 'invalid_config' }, 503);
      let instagramToken;
      try { instagramToken = await db.metaToken(); } catch { /* reserva explícita abaixo */ }
      if (!validToken(instagramToken)) instagramToken = env('INSTAGRAM_TOKEN');
      if (!validToken(instagramToken)) return json({ error: 'instagram_token_unavailable' }, 503);
      if (body.action === 'verify') {
        return json({ ok: true, revision: REVISION, mode: await db.mode(), configurado: true, sentToMeta: false, claims: 0 });
      }
      const result = await drain(db, instagramToken, config, { fetch: fetcher, sleep: delay, now, deadlineAt });
      return json(result, result.ok ? 200 : 503);
    } catch {
      return json({ error: 'service_unavailable', revision: REVISION }, 503);
    } finally {
      if (db) await db.close().catch(() => {});
    }
  };
}
