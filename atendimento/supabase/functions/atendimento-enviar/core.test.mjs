import test from 'node:test';
import assert from 'node:assert/strict';
import { createHandler, drain, sendToMeta } from './core.mjs';
import { createDatabase } from './database.mjs';

const AUTH = 'a'.repeat(64);
const META = 'secret-do-not-print-'.repeat(4);
const clock = Date.parse('2026-09-27T23:00:00Z');
const config = { accountId: '17841454587986765', version: 'v25.0' };
const job = (overrides = {}) => ({ lote: 'L0927-2000', n: '1', parte: 1, texto: 'Olá meu bem', tipo: 'direct',
  recipient: '17841400000000001', conversationId: '00000000-0000-4000-8000-000000000001',
  owner: '00000000-0000-4000-8000-000000000002', enviarApos: new Date(clock).toISOString(), ...overrides });
const request = (body = {}, token = AUTH) => new Request('https://local.invalid/', {
  method: 'POST', headers: { 'x-ai-followup-token': token }, body: JSON.stringify(body),
});
function fakeDb(jobs = []) {
  return {
    claims: 0, completed: [], closes: 0,
    async authorize() { return true; },
    async metaToken() { return META; },
    async mode() { return 'claude'; },
    async claim() { this.claims++; return jobs.shift() ?? null; },
    async deliveryAllowed() { return await this.mode() === 'claude'; },
    async status() { return 'cancelado'; },
    async complete(item, result) {
      this.completed.push({ item, result });
      return result.messageId ? 'enviado' : result.error.startsWith('meta_delivery_unknown:') ? 'incerto' : 'erro';
    },
    async close() { this.closes++; },
  };
}
const noDelay = async () => {};
const success = () => Response.json({ message_id: 'mid.accepted' });
const commentJob = () => job({ tipo: 'comentario', n: 'c1', commentId: '18000000000000001' });
const shop = { id: '17841400000000009', username: 'loja_teste' };
function commentFetch(pages, calls = []) {
  return async (url, options) => {
    calls.push({ url, options });
    if (options.method === 'POST') return success();
    if (!new URL(url).pathname.endsWith('/replies')) return Response.json(shop);
    const page = pages.shift();
    if (page instanceof Error) throw page;
    return page instanceof Response ? page : Response.json(page);
  };
}

test('método e segredo malformado não abrem o banco nem enviam', async () => {
  let calls = 0;
  const handler = createHandler({ openDatabase: async () => { calls++; throw Error(); }, fetch: () => { throw Error('Meta não devia ser chamada'); } });
  assert.equal((await handler(new Request('https://local.invalid/'))).status, 405);
  assert.equal((await handler(request({}, 'invalido'))).status, 401);
  assert.equal(calls, 0);
});

test('segredo bem formado revogado no banco retorna 401 sem claim', async () => {
  const db = fakeDb([job()]);
  db.authorize = async () => false;
  const handler = createHandler({ openDatabase: async () => db });
  assert.equal((await handler(request())).status, 401);
  assert.equal(db.claims, 0);
  assert.equal(db.closes, 1);
});

test('verify autenticado confere configuração sem claim nem POST', async () => {
  const db = fakeDb([job()]);
  const handler = createHandler({ openDatabase: async () => db, fetch: () => { throw Error(); } });
  const data = await (await handler(request({ action: 'verify' }))).json();
  assert.equal(data.sentToMeta, false);
  assert.equal(data.claims, 0);
  assert.equal(db.claims, 0);
  assert.ok(!JSON.stringify(data).includes(META));
});

test('não aceita payload arbitrário que tente escolher cliente ou texto', async () => {
  const db = fakeDb([job()]);
  const handler = createHandler({ openDatabase: async () => db });
  assert.equal((await handler(request({ recipient: 'outro', text: 'ignorar fila' }))).status, 400);
  assert.equal(db.claims, 0);
});

test('sem token Instagram não faz claim, evitando reservar itens que não pode enviar', async () => {
  const db = fakeDb([job()]);
  db.metaToken = async () => null;
  const handler = createHandler({ openDatabase: async () => db });
  assert.equal((await handler(request())).status, 503);
  assert.equal(db.claims, 0);
});

test('falha ou fila vazia no claim causa zero chamadas Meta', async () => {
  for (const fail of [false, true]) {
    const db = fakeDb();
    if (fail) db.claim = async () => { throw Error('db indisponível'); };
    let posts = 0;
    const result = await drain(db, META, config, { fetch: async () => { posts++; return success(); }, sleep: noDelay, now: () => clock });
    assert.equal(posts, 0);
    assert.equal(result.ok, !fail);
  }
});

test('claim inválido ou futuro nunca chega à Meta', async () => {
  for (const change of [{ tipo: 'fora' }, { recipient: 'https://outro' }, { owner: 'sem-lease' },
    { enviarApos: undefined }, { enviarApos: new Date(clock + 4000).toISOString() }, { texto: 'x'.repeat(951) }]) {
    const db = fakeDb([job(change)]);
    let posts = 0;
    await drain(db, META, config, { fetch: async () => { posts++; return success(); }, sleep: noDelay, now: () => clock });
    assert.equal(posts, 0);
  }
});

test('pausa entre claim e POST cancela a tentativa sem chamar Meta', async () => {
  const db = fakeDb([job()]);
  db.mode = async () => 'ia';
  let posts = 0;
  const result = await drain(db, META, config, { fetch: async () => { posts++; return success(); }, sleep: noDelay, now: () => clock });
  assert.equal(posts, 0);
  assert.equal(result.resultados[0].code, 'envio_nao_autorizado');
  assert.equal(db.completed.length, 0);
});

test('nova mensagem e resposta da equipe bloqueiam a parte já reservada', async () => {
  for (const reason of ['nova_mensagem', 'equipe_respondeu', 'fora_da_janela', 'cancelado']) {
    const db = fakeDb([job()]);
    db.deliveryAllowed = async () => false;
    db.status = async () => reason;
    let posts = 0;
    const result = await drain(db, META, config, { fetch: async () => { posts++; return success(); }, sleep: noDelay, now: () => clock });
    assert.equal(posts, 0);
    assert.equal(result.resultados[0].status, reason);
    assert.equal(db.completed.length, 0);
  }
});

test('erro na revalidação do claim impede envio e registra falha conhecida antes do POST', async () => {
  const db = fakeDb([job()]);
  db.deliveryAllowed = async () => { throw Error(); };
  let posts = 0;
  const result = await drain(db, META, config, { fetch: async () => { posts++; return success(); }, sleep: noDelay, now: () => clock });
  assert.equal(posts, 0);
  assert.equal(result.resultados[0].code, 'autorizacao_nao_verificada');
  assert.equal(result.resultados[0].status, 'erro');
});

test('Direct e comentário usam endpoint e corpo corretos; token só em Authorization', async () => {
  const calls = [];
  const fetcher = commentFetch([{ data: [] }], calls);
  await sendToMeta(job(), META, config, fetcher);
  await sendToMeta(job({ tipo: 'comentario', commentId: '18000000000000001' }), META, config, fetcher);
  const posts = calls.filter(c => c.options.method === 'POST');
  assert.equal(posts[0].url, 'https://graph.instagram.com/v25.0/17841454587986765/messages');
  assert.deepEqual(JSON.parse(posts[0].options.body), { recipient: { id: job().recipient }, message: { text: job().texto } });
  assert.equal(posts[1].url, 'https://graph.instagram.com/v25.0/18000000000000001/replies');
  assert.deepEqual(JSON.parse(posts[1].options.body), { message: job().texto });
  for (const call of calls) {
    assert.equal(call.options.headers.Authorization, `Bearer ${META}`);
    assert.equal(call.options.redirect, 'error');
    assert.ok(!call.url.includes(META));
  }
  assert.equal(new URL(calls[1].url).pathname, '/v25.0/me');
  assert.equal(new URL(calls[2].url).searchParams.get('fields'), 'id,username');
});

test('resposta da loja posterior ao sync bloqueia POST e marca equipe_respondeu no banco', async () => {
  for (const reply of [{ username: 'LOJA_TESTE' }, { from: { username: 'Loja_Teste' } },
    { from: { id: config.accountId } }, { from: { id: shop.id } }]) {
    const db = fakeDb([commentJob()]);
    let marked = false;
    db.commentReplied = async item => { assert.equal(item.commentId, commentJob().commentId); marked = true; };
    db.deliveryAllowed = async () => !marked;
    db.status = async () => 'equipe_respondeu';
    const calls = [];
    const result = await drain(db, META, config, { fetch: commentFetch([{ data: [reply] }], calls), sleep: noDelay, now: () => clock });
    assert.equal(calls.filter(c => c.options.method === 'POST').length, 0);
    assert.equal(marked, true);
    assert.equal(result.resultados[0].status, 'equipe_respondeu');
    assert.equal(db.completed.length, 0);
  }
});

test('resposta da loja na segunda página bloqueia envio e token de paging.next não é reutilizado', async () => {
  const calls = [];
  const result = await sendToMeta(commentJob(), META, config, commentFetch([
    { data: [{ username: 'outra_conta' }], paging: { next: `https://graph.instagram.com/v25.0/${commentJob().commentId}/replies?after=pagina2&access_token=nao_reutilizar` } },
    { data: [{ from: { id: shop.id } }] },
  ], calls));
  assert.equal(result.error, 'equipe_respondeu');
  assert.equal(calls.filter(c => c.options.method === 'POST').length, 0);
  assert.equal(new URL(calls[2].url).searchParams.get('after'), 'pagina2');
  assert.ok(!calls[2].url.includes('access_token'));
});

test('paginação completa sem resposta da loja envia uma única vez após revalidar o banco', async () => {
  const calls = [], events = [];
  const db = fakeDb([commentJob()]);
  db.deliveryAllowed = async () => { events.push('banco'); return true; };
  const fetcher = commentFetch([
    { data: [{ from: { id: '17841400000000003' } }], paging: { next: `https://graph.instagram.com/v25.0/${commentJob().commentId}/replies?after=pagina2` } },
    { data: [{ username: 'outra_conta' }] },
  ], calls);
  const result = await drain(db, META, config, { fetch: async (...args) => { events.push(args[1].method); return fetcher(...args); }, sleep: noDelay, now: () => clock });
  assert.equal(result.enviados, 1);
  assert.deepEqual(events, ['banco', 'GET', 'GET', 'GET', 'banco', 'POST']);
  assert.equal(calls.filter(c => c.options.method === 'POST').length, 1);
});

test('erro, autor ausente e paginação incompleta falham fechados antes de qualquer POST', async () => {
  const next = `https://graph.instagram.com/v25.0/${commentJob().commentId}/replies?after=repetido`;
  const scenarios = [[new Error(META)], [Response.json({ error: { code: 10, message: META } }, { status: 403 })],
    [new Response('ilegivel')], [{ success: true }], [{ data: [{}] }],
    [{ data: [], paging: { next: 'https://outro.invalid/replies?after=2' } }],
    [{ data: [], paging: { next: false } }],
    [{ data: [], paging: { next: `https://graph.instagram.com/v25.0/${commentJob().commentId}/replies` } }],
    [{ data: [], paging: { next } }, { data: [], paging: { next } }],
    [{ data: [], paging: { next } }, new Error(META)],
    [Response.json({ data: [], padding: 'x'.repeat(70000) })]];
  for (const pages of scenarios) {
    const calls = [];
    const db = fakeDb([commentJob()]);
    const result = await drain(db, META, config, { fetch: commentFetch(pages, calls), sleep: noDelay, now: () => clock });
    assert.equal(calls.filter(c => c.options.method === 'POST').length, 0);
    assert.equal(result.resultados[0].code, 'comentario_nao_verificado');
    assert.equal(result.resultados[0].status, 'erro');
    assert.equal(result.incertos, 0);
    assert.ok(!JSON.stringify(result).includes(META));
  }
});

test('conta da loja não verificável impede consultar replies e enviar', async () => {
  for (const account of [{}, { id: shop.id }, { id: 'invalido', username: shop.username }]) {
    const calls = [];
    const result = await sendToMeta(commentJob(), META, config, async (_url, options) => {
      calls.push(options.method); return Response.json(account);
    });
    assert.equal(result.error, 'comentario_nao_verificado');
    assert.deepEqual(calls, ['GET']);
  }
});

test('pausa durante a consulta Meta barra o POST e preserva o status SQL', async () => {
  const db = fakeDb([commentJob()]);
  let checks = 0;
  db.deliveryAllowed = async () => ++checks === 1;
  const calls = [];
  const result = await drain(db, META, config, { fetch: commentFetch([{ data: [] }], calls), sleep: noDelay, now: () => clock });
  assert.equal(calls.filter(c => c.options.method === 'POST').length, 0);
  assert.equal(result.resultados[0].status, 'cancelado');
  assert.equal(db.completed.length, 0);
});

test('limite de páginas não libera um comentário cuja varredura ficou incompleta', async () => {
  const calls = [];
  const pages = Array.from({ length: 100 }, (_, index) => ({ data: [],
    paging: { next: `https://graph.instagram.com/v25.0/${commentJob().commentId}/replies?after=pagina${index + 1}` } }));
  const result = await sendToMeta(commentJob(), META, config, commentFetch(pages, calls));
  assert.equal(result.error, 'comentario_nao_verificado');
  assert.equal(calls.filter(c => c.options.method === 'POST').length, 0);
});

test('prazo esgotado durante a leitura dos replies não inicia POST', async () => {
  let time = clock;
  const calls = [];
  const fetcher = commentFetch([{ data: [] }], calls);
  const result = await drain(fakeDb([commentJob()]), META, config, { fetch: async (...args) => {
    const response = await fetcher(...args);
    time = clock + 31000;
    return response;
  }, sleep: noDelay, now: () => time });
  assert.equal(calls.filter(c => c.options.method === 'POST').length, 0);
  assert.equal(result.resultados[0].code, 'execucao_interrompida_antes_envio');
});

test('erro de registro da resposta da equipe não permite POST nem falso enviado', async () => {
  const db = fakeDb([commentJob()]);
  db.commentReplied = async () => { throw Error(META); };
  const calls = [];
  const result = await drain(db, META, config, { fetch: commentFetch([{ data: [{ username: shop.username }] }], calls), sleep: noDelay, now: () => clock });
  assert.equal(calls.filter(c => c.options.method === 'POST').length, 0);
  assert.equal(result.enviados, 0);
  assert.equal(result.resultados[0].code, 'comentario_equipe_registro_nao_verificado');
});

test('sucesso só é persistido depois do id confirmado pela Meta', async () => {
  const events = [];
  const db = fakeDb([job()]);
  db.complete = async (_job, result) => { events.push('registro'); assert.equal(result.messageId, 'mid.accepted'); return 'enviado'; };
  const result = await drain(db, META, config, { fetch: async () => { events.push('meta'); return success(); }, sleep: noDelay, now: () => clock });
  assert.deepEqual(events, ['meta', 'registro']);
  assert.equal(result.enviados, 1);
});

test('timeout, 5xx, resposta grande e 2xx sem id são incertos e nunca repetem POST', async () => {
  const scenarios = [async () => { throw Error(`segredo ${META}`); },
    async () => Response.json({ error: { code: 2, message: META } }, { status: 503 }),
    async () => Response.json({ success: true }),
    async () => Response.json({ message_id: 'mid.accepted', extra: 'x'.repeat(70000) })];
  for (const scenario of scenarios) {
    const db = fakeDb([job()]);
    let posts = 0;
    const result = await drain(db, META, config, { fetch: async (...args) => { posts++; return scenario(...args); }, sleep: noDelay, now: () => clock });
    assert.equal(posts, 1);
    assert.equal(result.incertos, 1);
    assert.equal(result.enviados, 0);
    assert.ok(!JSON.stringify(result).includes(META));
  }
});

test('rejeição Meta 400 registra código sem repetir POST ou expor corpo', async () => {
  const db = fakeDb([job()]);
  let posts = 0;
  const result = await drain(db, META, config, { fetch: async () => {
    posts++; return Response.json({ error: { code: 10, error_subcode: 2018001, message: META } }, { status: 400 });
  }, sleep: noDelay, now: () => clock });
  assert.equal(posts, 1);
  assert.equal(result.resultados[0].status, 'erro');
  assert.equal(result.resultados[0].code, 'meta_10_2018001');
  assert.ok(!JSON.stringify(result).includes(META));
});

test('retry é só da confirmação SQL; Meta aceita uma única vez', async () => {
  const db = fakeDb([job()]);
  let posts = 0, writes = 0;
  db.complete = async () => { writes++; if (writes === 1) throw Error('resposta SQL perdida'); return 'enviado'; };
  const result = await drain(db, META, config, { fetch: async () => { posts++; return success(); }, sleep: noDelay, now: () => clock });
  assert.equal(posts, 1);
  assert.equal(writes, 2);
  assert.equal(result.enviados, 1);
});

test('Meta aceitou mas banco falhou: registro pendente, sem falso sucesso nem reenvio', async () => {
  const db = fakeDb([job()]);
  db.complete = async () => { throw Error('banco offline'); };
  let posts = 0;
  const result = await drain(db, META, config, { fetch: async () => { posts++; return success(); }, sleep: noDelay, now: () => clock });
  assert.equal(posts, 1);
  assert.equal(result.ok, false);
  assert.equal(result.enviados, 0);
  assert.equal(result.resultados[0].status, 'registro_pendente');
  assert.equal(result.resultados[0].metaAceitou, true);
});

test('no máximo cinco conversas fazem POST simultâneo', async () => {
  const db = fakeDb(Array.from({ length: 12 }, (_, n) => job({ n: String(n + 1) })));
  let active = 0, max = 0, total = 0;
  const result = await drain(db, META, config, { fetch: async () => {
    total++; active++; max = Math.max(max, active);
    await new Promise((resolve) => setTimeout(resolve, 2));
    active--; return success();
  }, sleep: noDelay, now: () => clock });
  assert.equal(max, 5);
  assert.equal(total, 12);
  assert.equal(result.enviados, 12);
});

test('partes continuam na ordem e esperam enviar_apos após confirmação anterior', async () => {
  let time = clock, nextPart = 1, due = clock, active = false;
  const db = fakeDb();
  db.claim = async () => {
    if (active || nextPart > 3 || time < due) return null;
    active = true;
    return job({ parte: nextPart, enviarApos: new Date(due).toISOString() });
  };
  db.complete = async () => { active = false; nextPart++; due = time + 3000; return 'enviado'; };
  const sent = [];
  const result = await drain(db, META, config, { fetch: async () => { sent.push({ part: nextPart, at: time }); return success(); },
    sleep: async (ms) => { time += ms; }, now: () => time });
  assert.deepEqual(sent.map((s) => s.part), [1, 2, 3]);
  assert.equal(sent[1].at - sent[0].at, 3000);
  assert.equal(sent[2].at - sent[1].at, 3000);
  assert.equal(result.enviados, 3);
});

test('usa token renovado do banco e fallback somente quando necessário', async () => {
  for (const useFallback of [false, true]) {
    const db = fakeDb([job()]);
    if (useFallback) db.metaToken = async () => { throw Error(); };
    const fallback = 'fallback-safe-token-'.repeat(4);
    let seen;
    const handler = createHandler({ openDatabase: async () => db, env: (name) => name === 'INSTAGRAM_TOKEN' ? fallback : undefined,
      fetch: async (_url, options) => { seen = options.headers.Authorization; return success(); }, sleep: noDelay, now: () => clock });
    assert.equal((await handler(request())).status, 200);
    assert.equal(seen, `Bearer ${useFallback ? fallback : META}`);
  }
});

test('adaptador usa funções corretas e parâmetros SQL separados do texto', async () => {
  const queries = [];
  const sql = async (strings, ...values) => { queries.push({ query: strings.join('?'), values }); return [{ valid: true, allowed: true, token: META, mode: 'claude', job: job(), status: 'enviado' }]; };
  sql.end = async () => {};
  const db = createDatabase(sql);
  assert.equal(await db.authorize(AUTH), true);
  assert.equal(await db.metaToken(), META);
  assert.equal(await db.mode(), 'claude');
  await db.claim();
  await db.complete(job(), { messageId: 'mid.accepted', error: null });
  assert.equal(await db.deliveryAllowed(job()), true);
  assert.match(queries[3].query, /atendimento\.claim_envio\(\)/);
  assert.match(queries[4].query, /atendimento\.concluir_envio/);
  assert.ok(!queries[0].query.includes(AUTH));
  assert.deepEqual(queries[4].values, [job().lote, job().n, 1, job().owner, 'mid.accepted', null]);
  assert.match(queries[5].query, /atendimento\.envio_autorizado/);
  await db.commentReplied(commentJob());
  assert.match(queries[6].query, /update atendimento\.comentarios set loja_respondeu=true/);
  assert.deepEqual(queries[6].values, [commentJob().commentId]);
});
