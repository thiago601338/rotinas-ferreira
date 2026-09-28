import { REVISION } from './domain.mjs';

const record = value => value && typeof value === 'object' && !Array.isArray(value) ? value : {};
const empty = value => value === null || value === undefined || value === '';
const copy = value => structuredClone(value);
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const conflict = (a, b) => !empty(a) && !empty(b) && a !== b;
function mediaConflict(old, fresh) {
  return conflict(old.mediaId, fresh.mediaId) || conflict(old.storyReference?.id, fresh.storyReference?.id) ||
    conflict(old.postReference?.id, fresh.postReference?.id) ||
    (old.mediaType !== 'file' && fresh.mediaType !== 'file' && conflict(old.mediaType, fresh.mediaType));
}

// Padrões explícitos do webhook, incluindo a conjugação "cancele o recebimento".
const OPTOUT = [/\bpar(e|ar) de (me )?(mandar|enviar)\b/i, /\bn[ãa]o quero (mais )?receber\b/i, /\bdescadastr/i,
  /\bsair da lista\b/i, /\bme remov/i, /\b(?:cancelar?|cancele) (o )?recebimento\b/i, /^\s*(sair|parar|stop)\s*$/i];
export function explicitOptOut(message, storedText = null) {
  return message.direction === 'inbound' && [message.text, storedText].some(value => typeof value === 'string' && OPTOUT.some(re => re.test(value)));
}

function fillObject(existing, incoming, keys) {
  const old = record(existing), fresh = record(incoming), result = copy(old);
  for (const key of keys) if (empty(result[key]) && !empty(fresh[key])) result[key] = copy(fresh[key]);
  return result;
}
function reference(existing, incoming) {
  const old = record(existing), fresh = record(incoming);
  if (conflict(old.id, fresh.id) || conflict(old.kind, fresh.kind)) return copy(old);
  return fillObject(old, fresh, ['kind', 'id', 'url', 'thumbnailUrl']);
}
function attachments(existing, incoming) {
  if (!Array.isArray(incoming) || !incoming.length) return existing;
  if (!Array.isArray(existing) || !existing.length) return copy(incoming);
  return existing.map(old => {
    const fresh = incoming.find(item => old?.id && item?.id === old.id);
    return fresh ? fillObject(old, fresh, ['type', 'url', 'thumbnailUrl', 'payload']) : copy(old);
  });
}

export function mergeRecoveredRaw(existing, incoming) {
  const old = record(existing), fresh = record(incoming), result = copy(old);
  const conflictingMedia = mediaConflict(old, fresh);
  // Estados de envio, handoff, transcrição e inferência ficam fora desta lista.
  for (const key of ['channel', 'externalMessageId', 'senderId', 'threadId', 'recipientId', 'accountId', 'customerName', 'timestamp', 'replyTo']) {
    if (empty(result[key]) && !empty(fresh[key])) result[key] = copy(fresh[key]);
  }
  for (const key of ['storyReference', 'postReference']) {
    if (Object.keys(record(fresh[key])).length) result[key] = reference(old[key], fresh[key]);
  }
  if (!conflictingMedia) {
    for (const key of ['mediaId', 'mediaUrl', 'mediaType', 'videoFramePath']) if (empty(result[key]) && !empty(fresh[key])) result[key] = copy(fresh[key]);
    // MIME confirmado pode refinar o anexo genérico, sem trocar um tipo já identificado.
    if (result.mediaType === 'file' && ['image', 'audio', 'video'].includes(fresh.mediaType) && fresh.mediaCache?.status === 'saved') result.mediaType = fresh.mediaType;
    if (fresh.mediaCache?.status === 'saved' && old.mediaCache?.status !== 'saved') result.mediaCache = copy(fresh.mediaCache);
    else if (fresh.mediaCache?.status === 'saved' && old.mediaCache?.status === 'saved' && fresh.mediaCache.path === old.mediaCache.path) {
      result.mediaCache = fillObject(old.mediaCache, fresh.mediaCache, ['sha256', 'mime']);
    }
    const merged = attachments(old.attachments, fresh.attachments);
    if (merged !== undefined) result.attachments = merged;
  }
  if ((!Array.isArray(old.shares) || !old.shares.length) && Array.isArray(fresh.shares) && fresh.shares.length) result.shares = copy(fresh.shares);
  return result;
}

export function needsMediaRecovery(existing, message) {
  if (!existing) return true;
  if (existing.direction !== 'inbound' || message.direction !== 'inbound') return false;
  const old = record(existing.raw_payload), fresh = record(message.raw);
  if (mediaConflict(old, fresh)) return false;
  const merged = mergeRecoveredRaw(old, fresh);
  if (empty(existing.media_path) && (merged.mediaUrl || merged.postReference?.id || merged.postReference?.thumbnailUrl)) return true;
  return merged.mediaType === 'video' && !merged.videoFramePath && !!merged.attachments?.some(a => a.type === 'video' && a.thumbnailUrl);
}

export function recoveredPatch(existing, message, mediaPath) {
  if (existing.direction !== 'inbound' || message.direction !== 'inbound' || existing.external_message_id !== message.externalId) return null;
  const old = record(existing.raw_payload), raw = mergeRecoveredRaw(old, message.raw);
  const patch = {};
  if (!same(old, raw)) patch.raw_payload = { ...raw, enriquecidoSync: true, syncRevision: REVISION };
  if (empty(existing.media_path) && mediaPath && !mediaConflict(old, record(message.raw))) patch.media_path = mediaPath;
  if (empty(existing.text_content) && !empty(message.text)) patch.text_content = message.text;
  if (!mediaConflict(old, record(message.raw)) && ['text', 'document'].includes(existing.message_type) && message.type !== 'text' && message.type !== existing.message_type && raw.mediaType) patch.message_type = message.type;
  return Object.keys(patch).length ? patch : null;
}
