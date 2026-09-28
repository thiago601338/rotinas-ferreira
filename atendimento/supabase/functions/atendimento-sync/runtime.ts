import postgres from 'npm:postgres@3.4.7';
import { bytes, Graph } from './graph.mjs';
import { trustedMediaUrl } from './domain.mjs';

export function database() {
  const connection = Deno.env.get('SUPABASE_DB_URL');
  if (!connection) throw Error('banco_nao_configurado');
  return postgres(connection, { prepare: false, max: 1, idle_timeout: 10, connect_timeout: 10 });
}
export function json(value: unknown, status = 200) {
  return Response.json(value, { status, headers: { 'Cache-Control': 'no-store' } });
}
export async function body(req: Request, max = 20000) {
  const parsed = JSON.parse(new TextDecoder().decode(await bytes(new Response(req.body), max)));
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw Error('corpo_invalido');
  return parsed;
}
export async function authorized(sql: any, req: Request) {
  const token = req.headers.get('x-ai-followup-token') ?? '';
  if (!/^[a-f0-9]{64}$/.test(token)) return false;
  const [row] = await sql`select public.ai_followup_valid(${token}) valid`;
  return row?.valid === true;
}
export async function activeToken(sql: any) {
  let token: string | undefined;
  try { const [row] = await sql`select public.ai_meta_token_get() token`; token = row?.token; } catch { /* reserva usada pelo worker atual */ }
  if (typeof token !== 'string' || token.length < 40) token = Deno.env.get('INSTAGRAM_TOKEN');
  if (!token || token.length < 40) throw Error('instagram_nao_configurado');
  return token;
}
export async function mode(sql: any) { return (await sql`select atendimento.modo_atual() modo`)[0]?.modo; }
export async function state(sql: any, key: string, value: unknown) {
  if (value === undefined) throw Error('estado_invalido');
  // postgres.js serializa uma string marcada ::jsonb outra vez. Para limpar
  // cursores, usar literal JSON null; para objetos, usar o serializador nativo.
  if (value === null) {
    await sql`insert into atendimento.estado(chave,valor) values(${key},'null'::jsonb)
      on conflict(chave) do update set valor=excluded.valor,atualizado_em=now()`;
  } else {
    await sql`insert into atendimento.estado(chave,valor) values(${key},${sql.json(value)})
      on conflict(chave) do update set valor=excluded.valor,atualizado_em=now()`;
  }
}
export async function log(sql: any, kind: string, detail: unknown, level = 'info') {
  await sql`insert into public.ai_logs(level,kind,channel,detail) values(${level},${kind},'instagram',${sql.json(detail)})`;
}
export function safeError(error: any) {
  // Sem mensagens arbitrárias de Postgres/Meta: podem conter dados pessoais ou URLs assinadas.
  if (error?.name === 'PostgresError' && typeof error?.code === 'string' && /^[0-9A-Z]{5}$/.test(error.code)) return 'db_' + error.code.toLowerCase();
  if (error?.name === 'TimeoutError') return 'tempo_esgotado';
  if (error?.name === 'AbortError') return 'operacao_cancelada';
  const candidate = String(error?.message ?? 'falha');
  return /^[a-z_0-9]{1,80}$/.test(candidate) ? candidate : 'falha_interna';
}

export async function cacheMedia(message: any, graph: Graph) {
  const raw = message.raw;
  if (raw.mediaType === 'video') {
    const thumbnail = raw.attachments?.find((a: any) => a.type === 'video')?.thumbnailUrl;
    if (thumbnail) {
      const frame = { externalId: message.externalId + ':frame', customerId: message.customerId, raw: { mediaUrl: thumbnail, mediaType: 'image' } };
      const path = await cacheMedia(frame, graph);
      if (path) raw.videoFramePath = path;
    }
  }
  if (raw.postReference?.id && !raw.postReference.thumbnailUrl) {
    try {
      const p = await graph.get(raw.postReference.id, { fields: 'id,media_type,media_url,thumbnail_url' });
      raw.postReference.thumbnailUrl = p.thumbnail_url ?? (p.media_type === 'IMAGE' ? p.media_url : null);
    } catch { raw.postReference.imageUnavailable = true; }
  }
  const source = raw.mediaUrl ?? raw.postReference?.thumbnailUrl;
  if (!source) return null;
  if (!trustedMediaUrl(source)) { raw.mediaCache = { status: 'unavailable', reason: 'media_host_invalid' }; return null; }
  const base = Deno.env.get('SUPABASE_URL'), key = Deno.env.get('SUPABASE_SERVICE_ROLE_KEY');
  if (!base || !key) throw Error('storage_nao_configurado');
  try {
    const remaining = graph.deadline - Date.now(); if (remaining < 2000) throw Error('prazo_sync');
    const response = await fetch(source, { redirect: 'error', signal: AbortSignal.timeout(Math.min(remaining, 10000)) });
    if (!response.ok) { await response.body?.cancel(); throw Error('media_download_failed'); }
    const mime = (response.headers.get('content-type') ?? '').split(';')[0].toLowerCase();
    const extensions: Record<string, string> = { 'image/jpeg': 'jpg', 'image/png': 'png', 'image/webp': 'webp', 'image/gif': 'gif', 'video/mp4': 'mp4', 'audio/mp4': 'm4a', 'audio/mpeg': 'mp3', 'audio/ogg': 'ogg', 'audio/wav': 'wav', 'audio/x-wav': 'wav', 'audio/aac': 'aac' };
    if (!extensions[mime]) { await response.body?.cancel(); throw Error('media_type_unsupported'); }
    if (raw.mediaType === 'file') {
      // URLs assinadas de áudio nem sempre têm extensão; o MIME confirma o tipo.
      if (mime.startsWith('audio/')) { raw.mediaType = 'audio'; message.type = 'audio'; }
      else if (mime.startsWith('video/')) { raw.mediaType = 'video'; message.type = 'document'; }
      else if (mime.startsWith('image/')) { raw.mediaType = 'image'; message.type = 'image'; }
    }
    const buffer = await bytes(response, mime.startsWith('image/') ? 10 * 1024 * 1024 : 25 * 1024 * 1024);
    const digest = new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(message.externalId)));
    const id = [...digest].map(x => x.toString(16).padStart(2, '0')).join('');
    const contentDigest = new Uint8Array(await crypto.subtle.digest('SHA-256', buffer));
    const sha256 = [...contentDigest].map(x => x.toString(16).padStart(2, '0')).join('');
    // O conteúdo participa do caminho: um 409 só reutiliza os mesmos bytes, nunca uma versão anterior.
    const path = `instagram/atendimento-sync/${message.customerId}/${id}-${sha256}.${extensions[mime]}`;
    const upload = await fetch(`${base}/storage/v1/object/ai-inbox-media/${path}`, {
      method: 'POST', headers: { apikey: key, Authorization: 'Bearer ' + key, 'Content-Type': mime, 'x-upsert': 'false' },
      body: buffer, signal: AbortSignal.timeout(10000), redirect: 'error',
    });
    // Caminho determinístico: arquivo já salvo em execução interrompida pode ser reutilizado.
    if (!upload.ok) {
      const result = await upload.json().catch(() => ({}));
      if (String(result.statusCode) !== '409' && result.error !== 'Duplicate') throw Error('media_storage_failed');
    } else await upload.body?.cancel();
    raw.mediaCache = { status: 'saved', path, mime, sha256 };
    return path;
  } catch (error) { raw.mediaCache = { status: 'unavailable', reason: safeError(error) }; return null; }
}
