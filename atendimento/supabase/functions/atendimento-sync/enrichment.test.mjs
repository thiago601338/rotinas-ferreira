import test from 'node:test';
import assert from 'node:assert/strict';
import { explicitOptOut, mergeRecoveredRaw, needsMediaRecovery, recoveredPatch } from './enrichment.mjs';

const stored = (overrides = {}) => ({ external_message_id: 'mid-1', direction: 'inbound', message_type: 'text', text_content: 'Valor?', media_path: null, raw_payload: {}, ...overrides });
const incoming = (overrides = {}) => ({ externalId: 'mid-1', direction: 'inbound', type: 'image', text: 'Valor?', raw: { mediaType: 'image', mediaId: 'photo-1', mediaUrl: 'https://scontent.fbcdn.net/new.jpg', processingStatus: 'claude', origemSync: true }, ...overrides });

test('enriquece DM incompleta sem trocar texto, transcrição, origem ou atendimento humano', () => {
  const before = stored({ text_content: 'transcrição revisada', raw_payload: { processingStatus: 'human_answered', origem: 'webhook', supported: false, transcription: { status: 'done', model: 'existente' }, storyReference: { kind: 'story', id: '123456', url: null } } });
  const recovered = incoming({ raw: { ...incoming().raw, storyReference: { kind: 'story', id: '123456', url: 'https://scontent.fbcdn.net/story.jpg' } } });
  const patch = recoveredPatch(before, recovered, 'instagram/saved.jpg');
  assert.equal(patch.media_path, 'instagram/saved.jpg'); assert.equal(patch.message_type, 'image');
  assert.equal(patch.text_content, undefined);
  assert.equal(patch.raw_payload.processingStatus, 'human_answered'); assert.equal(patch.raw_payload.origem, 'webhook');
  assert.equal(patch.raw_payload.supported, false); assert.deepEqual(patch.raw_payload.transcription, before.raw_payload.transcription);
  assert.equal(patch.raw_payload.storyReference.url, recovered.raw.storyReference.url);
  assert.equal(before.raw_payload.storyReference.url, null, 'não altera objeto original');
});
test('nova tentativa conserva arquivo bom e não regrava o mesmo enriquecimento', () => {
  const first = recoveredPatch(stored(), incoming(), 'instagram/saved.jpg');
  const updated = { ...stored(), ...first };
  assert.equal(recoveredPatch(updated, incoming(), 'instagram/replacement.jpg'), null);
  assert.equal(needsMediaRecovery(updated, incoming()), false);
});
test('não une URLs a outro story/post ou a outro ID de anexo', () => {
  const before = stored({ raw_payload: { storyReference: { kind: 'story', id: '123456', url: null }, postReference: { id: '111111', url: null }, mediaId: 'photo-old' } });
  const message = incoming({ raw: { ...incoming().raw, storyReference: { kind: 'story', id: '654321', url: 'other-story' }, postReference: { id: '222222', url: 'other-post' } } });
  const merged = mergeRecoveredRaw(before.raw_payload, message.raw);
  assert.deepEqual(merged.storyReference, before.raw_payload.storyReference);
  assert.deepEqual(merged.postReference, before.raw_payload.postReference);
  assert.equal(merged.mediaUrl, undefined); assert.equal(needsMediaRecovery(before, message), false);
  assert.equal(recoveredPatch(before, message, 'instagram/other.jpg')?.media_path, undefined);
});
test('sucesso de cache recupera falha, mas falha posterior não substitui cache salvo', () => {
  const success = { mediaCache: { status: 'saved', path: 'instagram/a.jpg' } };
  assert.deepEqual(mergeRecoveredRaw({ mediaCache: { status: 'unavailable' } }, success).mediaCache, success.mediaCache);
  assert.deepEqual(mergeRecoveredRaw(success, { mediaCache: { status: 'unavailable' } }).mediaCache, success.mediaCache);
});
test('hash recuperado só é associado ao mesmo arquivo já salvo', () => {
  const old = { mediaCache: { status: 'saved', path: 'instagram/a.jpg' } };
  const fresh = { mediaCache: { status: 'saved', path: 'instagram/a.jpg', sha256: 'verified' } };
  assert.equal(mergeRecoveredRaw(old, fresh).mediaCache.sha256, 'verified');
  assert.equal(mergeRecoveredRaw(old, { mediaCache: { ...fresh.mediaCache, path: 'instagram/other.jpg' } }).mediaCache.sha256, undefined);
});
test('não altera eco/outbound nem mensagem com ID diferente', () => {
  assert.equal(recoveredPatch(stored({ direction: 'outbound' }), incoming({ direction: 'outbound' }), 'other.jpg'), null);
  assert.equal(recoveredPatch(stored(), incoming({ externalId: 'mid-other' }), 'other.jpg'), null);
});
test('anexo existente ganha URL pelo mesmo ID, preservando demais anexos', () => {
  const before = { attachments: [{ id: 'a', type: 'image', url: null }, { id: 'b', url: 'good' }] };
  const after = mergeRecoveredRaw(before, { attachments: [{ id: 'a', type: 'image', url: 'recovered' }, { id: 'b', url: 'bad' }] });
  assert.equal(after.attachments[0].url, 'recovered'); assert.equal(after.attachments[1].url, 'good');
});
test('opt-out explícito segue o webhook e só considera inbound', () => {
  for (const text of ['Pare de me mandar mensagem', 'Não quero mais receber', 'quero sair da lista', 'me remova', 'cancele o recebimento', 'STOP', 'sair']) {
    assert.equal(explicitOptOut(incoming({ text })), true, text);
    assert.equal(explicitOptOut(incoming({ text, direction: 'outbound' })), false, 'eco da loja');
  }
  for (const text of ['Não quero esse vestido', 'Vou sair agora', 'Cancelar o pedido', 'obrigada', 'Qual o valor?']) assert.equal(explicitOptOut(incoming({ text })), false, text);
});
test('transcrição já existente também preserva opt-out quando a API retorna áudio sem texto', () => {
  assert.equal(explicitOptOut(incoming({ text: null, type: 'audio' }), 'Não quero mais receber mensagem'), true);
});
