import test from 'node:test';
import assert from 'node:assert/strict';
import { Graph, MetaError } from './graph.mjs';
import { addGap, readConversationDetail } from './recovery.mjs';

test('somente detalhe Meta 100/33 vira lacuna recuperável sem bloquear a próxima conversa', async () => {
  const visited = [];
  const graph = new Graph('test-only', async url => {
    const path = new URL(url).pathname; visited.push(path);
    if (path.endsWith('/inaccessible')) return Response.json({ error: { code: 100, error_subcode: 33, message: "Unsupported get request. Object with ID 'private' does not exist" } }, { status: 400 });
    return Response.json({ id: 'accessible', messages: { data: [{ id: 'synthetic-message' }] } });
  });
  const first = await readConversationDetail(graph, 'inaccessible');
  assert.equal(first.available, false);
  assert.deepEqual(first.issue, { etapa: 'conversa_detalhe', codigo: 100, subcodigo: 33, motivo: 'objeto_inacessivel' });
  assert.equal(JSON.stringify(first).includes('private'), false);
  const second = await readConversationDetail(graph, 'accessible');
  assert.equal(second.available, true); assert.equal(second.detail.messages.data.length, 1);
  assert.deepEqual(visited, ['/v25.0/inaccessible', '/v25.0/accessible']);
});
test('Meta100 sem subcódigo33, permissão e autenticação continuam falhas explícitas', async () => {
  for (const [code, subcode] of [[100, null], [100, 99], [10, 33], [190, 33]]) {
    const graph = { get: async () => { throw new MetaError(400, code, subcode); } };
    await assert.rejects(readConversationDetail(graph, 'synthetic'), error => error.code === code && error.subcode === subcode && error.operation === 'conversa_detalhe');
  }
});
test('erro de campo não é considerado conversa inacessível', async () => {
  const graph = new Graph('test-only', async () => Response.json({ error: { code: 100, message: 'Tried accessing nonexisting field (unsupported)' } }, { status: 400 }));
  await assert.rejects(readConversationDetail(graph, 'synthetic'), error => error.reason === 'campo_invalido');
});
test('contador de lacunas persiste sem ID e não aumenta ao revisitar mesma conversa', async () => {
  let cursor = { since: '2026-09-26T20:37:00Z', after: 'synthetic', index: 9, gaps: [] };
  cursor = await addGap(cursor, 'synthetic-private-conversation');
  assert.equal(cursor.gaps.length, 1); assert.match(cursor.gaps[0], /^[a-f0-9]{64}$/);
  assert.equal(JSON.stringify(cursor).includes('synthetic-private-conversation'), false);
  const resumed = JSON.parse(JSON.stringify(cursor));
  assert.equal((await addGap(resumed, 'synthetic-private-conversation')).gaps.length, 1);
  assert.equal((await addGap(resumed, 'other-conversation')).gaps.length, 2);
});
