import test from 'node:test';
import assert from 'node:assert/strict';
import { mapStories, validateRegistration } from './domain.mjs';

const input = { letra: 'A', sku: 'FB-0001', cor: 'preto', n_midias: 2, publicado_de: '2026-09-27T12:00:00-03:00', publicado_ate: '2026-09-27T12:10:00-03:00' };
const now = Date.parse('2026-09-27T16:00:00Z');
const stories = [{ id: '10000001', timestamp: '2026-09-27T15:02:00Z', media_type: 'VIDEO' }, { id: '10000002', timestamp: '2026-09-27T15:03:00Z', media_type: 'IMAGE' }];
test('quantidade divergente não produz plano de gravação', () => {
  const plan = mapStories(validateRegistration(input, now), stories.slice(0, 1));
  assert.equal(plan.ok, false); assert.equal(plan.motivo, 'contagem_divergente'); assert.equal(plan.pares, undefined);
});
test('só considera stories na janela e não associa os já cadastrados', () => {
  const extra = { id: '99999999', timestamp: '2026-09-27T14:59:59Z' };
  const plan = mapStories(validateRegistration(input, now), [...stories, extra]);
  assert.equal(plan.ok, true); assert.equal(plan.pares.length, 2);
  assert.equal(mapStories(validateRegistration(input, now), stories, [{ story_id: stories[0].id }]).ok, false);
});
test('duplicata na paginação não aumenta quantidade', () => {
  assert.equal(mapStories(validateRegistration(input, now), [...stories, stories[0]]).pares.length, 2);
});
test('vários modelos exige manifesto e todos os arquivos precisam de produto', () => {
  assert.throws(() => validateRegistration({ ...input, varios_modelos: true }, now), /manifesto_por_midia/);
  assert.throws(() => validateRegistration({ ...input, midias: [{ sku: 'A' }, {}] }, now), /produto_invalido/);
});
test('manifesto usa ordem temporal real e recusa empate ambíguo', () => {
  const manifest = validateRegistration({ ...input, midias: [{ sku: 'FB-A' }, { sku: 'FB-B' }] }, now);
  assert.equal(mapStories(manifest, [...stories].reverse()).pares[0].produto.sku, 'FB-A');
  assert.equal(mapStories(manifest, [stories[0], { ...stories[1], timestamp: stories[0].timestamp }]).motivo, 'ordem_ambigua_informe_story_ids');
});
test('IDs explícitos mantêm produto correto mesmo com horário idêntico', () => {
  const manifest = validateRegistration({ ...input, midias: [{ sku: 'FB-B', story_id: stories[1].id }, { sku: 'FB-A', story_id: stories[0].id }] }, now);
  const plan = mapStories(manifest, [stories[0], { ...stories[1], timestamp: stories[0].timestamp }]);
  assert.equal(plan.pares[0].story.id, stories[1].id); assert.equal(plan.pares[0].produto.sku, 'FB-B');
  assert.throws(() => validateRegistration({ ...input, midias: [{ sku: 'A', story_id: stories[0].id }, { sku: 'B' }] }, now), /story_ids_incompletos/);
});
test('janela precisa de timezone e não admite horário futuro', () => {
  assert.throws(() => validateRegistration({ ...input, publicado_de: '2026-09-27T12:00:00' }, now), /janela_invalida/);
  assert.throws(() => validateRegistration({ ...input, publicado_ate: '2026-09-27T18:00:00Z' }, now), /janela_invalida/);
});
