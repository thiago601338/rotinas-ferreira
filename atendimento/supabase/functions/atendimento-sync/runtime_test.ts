import { cacheMedia, safeError, state } from './runtime.ts';
import { Graph } from './graph.mjs';

function assert(value: unknown, message: string): asserts value { if (!value) throw Error(message); }
async function withStorage(test: (calls: string[]) => Promise<void>) {
  const oldFetch = globalThis.fetch;
  const oldUrl = Deno.env.get('SUPABASE_URL'), oldKey = Deno.env.get('SUPABASE_SERVICE_ROLE_KEY');
  const calls: string[] = [];
  Deno.env.set('SUPABASE_URL', 'https://storage.invalid'); Deno.env.set('SUPABASE_SERVICE_ROLE_KEY', 'test-only');
  globalThis.fetch = async (input: string | URL | Request, options?: RequestInit) => {
    const url = String(input); calls.push(url);
    if (url.startsWith('https://storage.invalid/')) {
      assert(options?.method === 'POST', 'upload esperado');
      return Response.json({ Key: 'stored' });
    }
    const mime = url.endsWith('.jpg') ? 'image/jpeg' : url.endsWith('.mp4') ? 'video/mp4' : 'audio/mp4';
    return new Response(new Uint8Array([0, 1, 2, 3]), { headers: { 'Content-Type': mime } });
  };
  try { await test(calls); } finally {
    globalThis.fetch = oldFetch;
    if (oldUrl === undefined) Deno.env.delete('SUPABASE_URL'); else Deno.env.set('SUPABASE_URL', oldUrl);
    if (oldKey === undefined) Deno.env.delete('SUPABASE_SERVICE_ROLE_KEY'); else Deno.env.set('SUPABASE_SERVICE_ROLE_KEY', oldKey);
  }
}

Deno.test('vídeo conserva original e grava capa JPEG separada para a folha', async () => {
  await withStorage(async calls => {
    const message: any = { externalId: 'synthetic-message', customerId: '123456789', type: 'document',
      raw: { mediaType: 'video', mediaUrl: 'https://scontent.fbcdn.net/clip.mp4',
        attachments: [{ type: 'video', thumbnailUrl: 'https://scontent.fbcdn.net/frame.jpg' }] } };
    const path = await cacheMedia(message, new Graph('test-only'));
    assert(path?.endsWith('.mp4'), 'original preservado');
    assert(message.raw.mediaCache.sha256 === '054edec1d0211f624fed0cbca9d4f9400b0e491c43742af2c5b0abebf0c990d8', 'hash dos bytes baixados');
    assert(path?.includes(message.raw.mediaCache.sha256), 'caminho distingue versões de conteúdo');
    assert(message.raw.videoFramePath?.endsWith('.jpg'), 'quadro disponível');
    assert(message.raw.videoFramePath !== path, 'arquivos distintos');
    assert(calls.filter(x => x.startsWith('https://storage.invalid/')).length === 2, 'dois uploads');
  });
});
Deno.test('áudio em URL sem extensão ganha tipo audio a partir do MIME', async () => {
  await withStorage(async () => {
    const message: any = { externalId: 'synthetic-audio', customerId: '123456789', type: 'document',
      raw: { mediaType: 'file', mediaUrl: 'https://scontent.fbsbx.com/opaque?asset_id=123' } };
    const path = await cacheMedia(message, new Graph('test-only'));
    assert(path?.endsWith('.m4a'), 'extensão pelo MIME');
    assert(message.type === 'audio' && message.raw.mediaType === 'audio', 'elegível para transcrição');
  });
});
Deno.test('URL externa não é baixada nem enviada ao bucket', async () => {
  await withStorage(async calls => {
    const message: any = { externalId: 'synthetic-unsafe', customerId: '123456789', raw: { mediaType: 'image', mediaUrl: 'https://evil.invalid/customer' } };
    assert(await cacheMedia(message, new Graph('test-only')) === null, 'sem mídia');
    assert(calls.length === 0, 'sem chamada de rede');
    assert(message.raw.mediaCache.reason === 'media_host_invalid', 'motivo preservado');
  });
});
Deno.test('conclusão do Direct e comentários limpa cursor com null JSON sem NULL SQL', async () => {
  for (const key of ['sync_direct_cursor', 'sync_comentarios_cursor']) {
    let query = '', parameters: unknown[] = [];
    const sql = async (strings: TemplateStringsArray, ...args: unknown[]) => { query = strings.join('?'); parameters = args; return []; };
    await state(sql, key, null);
    assert(parameters[0] === key, 'cursor correto');
    assert(parameters.length === 1, 'nenhum parâmetro para o valor null');
    assert(query.includes("'null'::jsonb"), 'literal JSON null, sem serialização dupla');
    assert(parameters.every(value => value !== null), 'nenhum parâmetro é NULL SQL');
  }
});
Deno.test('estado serializa objeto uma única vez e rejeita undefined', async () => {
  let encoded: unknown;
  const sql: any = async (_strings: TemplateStringsArray, ...args: unknown[]) => { encoded = args[1]; return []; };
  sql.json = (value: unknown) => ({ json: value });
  await state(sql, 'sync_direct_cursor', { after: null, index: 14 });
  assert(typeof encoded === 'object' && (encoded as any)?.json?.index === 14, 'objeto passado ao serializador nativo');
  let rejected = false;
  try { await state(sql, 'sync_direct_cursor', undefined); } catch (e) { rejected = e instanceof Error && e.message === 'estado_invalido'; }
  assert(rejected, 'undefined não é estado válido');
});
Deno.test('diagnóstico de banco preserva SQLSTATE e descarta mensagem potencialmente sensível', () => {
  assert(safeError({ name: 'PostgresError', code: '23502', message: 'row contains sensitive data', detail: 'private' }) === 'db_23502', 'SQLSTATE seguro');
  assert(safeError(new Error('https://private.invalid/customer?token=secret')) === 'falha_interna', 'mensagem arbitrária omitida');
  assert(safeError(new DOMException('private request timed out', 'TimeoutError')) === 'tempo_esgotado', 'timeout identificado');
});
