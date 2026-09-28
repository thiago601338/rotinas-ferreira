import test from 'node:test';
import assert from 'node:assert/strict';
import { ACCOUNT_ID, RECOVERY_FROM, normalizeMessage, normalizeComment, syncWindow, pageAfter, trustedMediaUrl } from './domain.mjs';
import { Graph, MetaError, bytes, verifiedAccount } from './graph.mjs';

const inbound = { id: 'mid.test', created_time: '2026-09-27T16:00:00+0000', from: { id: '123456789', username: 'cliente.teste' }, to: { data: [{ id: ACCOUNT_ID }] }, message: 'Tem M?' };

test('recuperação inicial alcança 26/09 17:37 Maceió mesmo se executada dias depois', () => {
  const now = Date.parse('2026-10-04T12:00:00Z');
  assert.equal(syncWindow(48, now, false), RECOVERY_FROM);
  assert.equal(syncWindow(48, now, true), '2026-10-02T12:00:00.000Z');
  assert.throws(() => syncWindow(-1, now, false));
});
test('DM mantém story e reply para o prefetch, sem importedHistory nem processing pending', () => {
  const m = normalizeMessage({ ...inbound, story: { StoryReply: { id: '987654321', link: 'https://scontent.cdninstagram.com/story.jpg' } }, reply_to: { mid: 'referencia' } });
  assert.deepEqual(m.raw.storyReference, { kind: 'story', id: '987654321', url: 'https://scontent.cdninstagram.com/story.jpg' });
  assert.equal(m.raw.replyTo, 'referencia');
  assert.equal(m.raw.processingStatus, 'claude');
  assert.equal(m.raw.importedHistory, undefined);
  assert.equal(m.raw.origemSync, true);
  assert.equal(m.username, 'cliente.teste');
  assert.equal(m.customerId, m.raw.threadId);
});
test('eco é da loja e conserva IGSID da cliente; mensagem de outra conta é rejeitada', () => {
  const m = normalizeMessage({ ...inbound, from: { id: ACCOUNT_ID }, to: { data: [inbound.from] } });
  assert.equal(m.direction, 'outbound'); assert.equal(m.raw.origem, 'conta_da_loja');
  assert.equal(m.customerId, inbound.from.id);
  assert.throws(() => normalizeMessage({ ...inbound, to: { data: [{ id: '55555555' }] } }), /conta_divergente/);
});
test('foto, áudio, vídeo e post sem texto continuam reconhecíveis', () => {
  const photo = normalizeMessage({ ...inbound, message: '', attachments: { data: [{ id: 'foto', image_data: { url: 'https://scontent.fbcdn.net/a.jpg' } }] } });
  assert.equal(photo.raw.mediaType, 'image'); assert.equal(photo.raw.mediaId, 'foto');
  const audio = normalizeMessage({ ...inbound, message: '', attachments: { data: [{ file_url: 'https://scontent.fbsbx.com/a.m4a?x=1' }] } });
  assert.equal(audio.type, 'audio');
  const video = normalizeMessage({ ...inbound, attachments: { data: [{ video_data: { url: 'https://scontent.fbcdn.net/a.mp4', preview_url: 'https://scontent.fbcdn.net/a.jpg' } }] } });
  assert.equal(video.type, 'document'); assert.equal(video.raw.mediaType, 'video');
  const post = normalizeMessage({ ...inbound, message: '', shares: { data: [{ id: '111111111', link: 'https://instagram.com/p/teste/' }] } });
  assert.equal(post.raw.postReference.id, '111111111'); assert.equal(post.type, 'image');
});
test('paginação nunca retém token nem aceita outro host', () => {
  assert.equal(pageAfter({ paging: { next: 'https://graph.instagram.com/v25.0/me/media?after=abc&access_token=secret' } }), 'abc');
  assert.throws(() => pageAfter({ paging: { next: 'https://evil.example/?after=a' } }), /paginacao_invalida/);
  assert.equal(pageAfter({ data: [] }), null);
});
test('cache aceita só CDN Meta HTTPS e recusa hosts parecidos, porta e credenciais', () => {
  assert.equal(trustedMediaUrl('https://scontent.cdninstagram.com/image.jpg'), true);
  for (const url of ['http://scontent.fbcdn.net/a', 'https://fbcdn.net.evil.test/a', 'https://user@fbcdn.net/a', 'https://127.0.0.1/a', 'https://fbcdn.net:444/a']) assert.equal(trustedMediaUrl(url), false);
});
test('comentário respondido pela loja é reconhecido mesmo após paginar respostas', () => {
  const row = normalizeComment({ id: 'c1', timestamp: inbound.created_time, username: 'cliente', text: 'Valor?', hidden: true }, { id: 'p1', thumbnail_url: 'capa' }, 'Ferreira.Boutique', [{ username: 'outra' }, { username: 'ferreira.boutique' }]);
  assert.equal(row.loja_respondeu, true); assert.equal(row.hidden, true);
});
test('Graph envia token só no header e preserva códigos de permissão', async () => {
  let seen;
  const graph = new Graph('token-secreto', async (url, options) => { seen = { url: String(url), options }; return Response.json({ error: { code: 10, message: 'sensitive' } }, { status: 403 }); });
  await assert.rejects(graph.get('me/media', { fields: 'id' }), e => e instanceof MetaError && e.permissionDenied && e.message === 'meta_10');
  assert.equal(seen.url.includes('token-secreto'), false); assert.equal(seen.options.headers.Authorization, 'Bearer token-secreto');
  assert.equal(seen.options.redirect, 'error');
});
test('leitura limitada recusa corpo excessivo inclusive sem Content-Length', async () => {
  await assert.rejects(bytes(new Response('123456'), 5), /resposta_muito_grande/);
});
test('ID canônico de /me é validado pela resolução da conta configurada', async () => {
  const requests = [];
  const graph = new Graph('token-teste', async url => {
    requests.push(new URL(url));
    return Response.json({ id: '25585141051165365', username: 'ferreira.boutique' });
  });
  const me = await verifiedAccount(graph, 'id,username');
  assert.equal(me.id, '25585141051165365'); assert.equal(me.username, 'ferreira.boutique');
  assert.deepEqual(requests.map(x => x.pathname).sort(), [`/v25.0/${ACCOUNT_ID}`, '/v25.0/me'].sort());
  const echo = normalizeMessage({ ...inbound, from: { id: ACCOUNT_ID }, to: { data: [inbound.from] } });
  assert.equal(echo.direction, 'outbound'); assert.equal(echo.raw.accountId, ACCOUNT_ID);
});
test('IDs canônicos diferentes ou ausentes não validam token de outra conta', async () => {
  for (const configuredId of ['11111111111111111', null]) {
    const graph = new Graph('token-teste', async url => Response.json({ id: new URL(url).pathname.endsWith('/me') ? '25585141051165365' : configuredId }));
    await assert.rejects(verifiedAccount(graph), /conta_instagram_divergente/);
  }
});
