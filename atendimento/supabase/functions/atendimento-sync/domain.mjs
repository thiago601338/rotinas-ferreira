export const REVISION = 'atendimento-sync-20260927-r3';
export const RECOVERY_FROM = '2026-09-26T20:37:00.000Z'; // 17:37, America/Maceio.
export const ACCOUNT_ID = '17841454587986765';
export const GRAPH_VERSION = 'v25.0';
export const list = value => Array.isArray(value) ? value : Array.isArray(value?.data) ? value.data : [];
export const text = (value, max = 8192) => typeof value === 'string' && value.length <= max && value.trim() ? value.trim() : null;
export const username = value => typeof value === 'string' && /^[A-Za-z0-9._]{1,30}$/.test(value) ? value : null;
export const iso = value => typeof value === 'string' && Number.isFinite(Date.parse(value)) ? new Date(value).toISOString() : null;

export function syncWindow(hours, now, recovered) {
  if (hours !== undefined && (!Number.isInteger(hours) || hours < 1 || hours > 168)) throw Error('horas_invalidas');
  const normal = now - (hours ?? 48) * 3600000;
  return new Date(recovered ? normal : Math.min(normal, Date.parse(RECOVERY_FROM))).toISOString();
}

export function trustedMediaUrl(value) {
  try {
    const u = new URL(value);
    return u.protocol === 'https:' && !u.username && !u.password && !u.port &&
      ['fbcdn.net', 'fbsbx.com', 'cdninstagram.com', 'facebook.com'].some(h => u.hostname === h || u.hostname.endsWith('.' + h));
  } catch { return false; }
}

export function pageAfter(page) {
  if (!page?.paging?.next) return null;
  const u = new URL(page.paging.next);
  if (u.protocol !== 'https:' || u.hostname !== 'graph.instagram.com' || u.username || u.password || u.port) throw Error('paginacao_invalida');
  const after = page.paging.cursors?.after ?? u.searchParams.get('after');
  if (typeof after !== 'string' || !after || after.length > 4000) throw Error('cursor_ausente');
  return after; // Nunca persistir paging.next: a Meta pode colocar o token na URL.
}

function attachment(a) {
  const p = a?.payload ?? {};
  const type = a?.type ?? (a?.image_data ? 'image' : a?.video_data ? 'video' : a?.audio_data ? 'audio' : 'file');
  return { id: text(a?.id, 500), type, url: text(p.url ?? a?.image_data?.url ?? a?.video_data?.url ?? a?.audio_data?.url ?? a?.file_url),
    thumbnailUrl: text(a?.video_data?.preview_url ?? a?.video_data?.thumbnail_url ?? p.thumbnail_url), payload: p };
}

export function normalizeMessage(m, accountId = ACCOUNT_ID) {
  const id = text(m?.id, 1000), at = iso(m?.created_time), from = text(m?.from?.id, 100);
  const recipients = list(m?.to);
  const outbound = from === accountId;
  const customer = outbound ? recipients.find(x => String(x?.id) !== accountId) : m?.from;
  const customerId = text(customer?.id, 100);
  if (!id || !at || !from || !customerId || !/^\d{5,40}$/.test(customerId)) throw Error('mensagem_invalida');
  if (!outbound && recipients.length && !recipients.some(x => String(x?.id) === accountId)) throw Error('conta_divergente');
  const attachments = list(m.attachments).map(attachment);
  const rawStory = m.story?.StoryReply ?? m.story?.StoryMention ?? m.story?.story_reply ?? m.story?.story_mention ?? m.story;
  const attachedStory = attachments.find(x => ['story_mention', 'story', 'ig_story'].includes(x.type));
  const s = m.reply_to?.story ?? (rawStory && (rawStory.id || rawStory.link || rawStory.url) ? rawStory : null) ?? attachedStory?.payload;
  const storyReference = s ? { kind: 'story', id: text(s.id, 200), url: text(s.url ?? s.link) } : null;
  const share = list(m.shares)[0] ?? attachments.find(x => ['share', 'ig_post', 'ig_reel', 'post', 'reel'].includes(x.type))?.payload;
  const postReference = share ? { kind: 'post', id: text(share.id, 200), url: text(share.link ?? share.url), thumbnailUrl: text(share.image_url ?? share.thumbnail_url ?? share.media_url) } : null;
  const media = attachments.find(x => ['image', 'audio', 'video', 'file'].includes(x.type));
  const mediaType = media?.type === 'file' && /\.(mp3|m4a|wav|ogg|aac)(\?|$)/i.test(media.url ?? '') ? 'audio' : media?.type ?? null;
  const raw = { channel: 'instagram', externalMessageId: id, senderId: from, threadId: customerId, recipientId: customerId,
    accountId, customerName: text(customer.name, 200), text: text(m.message, 20000), timestamp: at,
    isEcho: outbound, supported: true, processingStatus: 'claude', origemSync: true,
    ...(outbound ? { origem: 'conta_da_loja', enviado: true } : {}),
    storyReference, ...(postReference ? { postReference } : {}), replyTo: text(m.reply_to?.mid ?? m.reply_to?.id, 1000),
    mediaId: media?.id ?? null, mediaUrl: media?.url ?? null, mediaType,
    attachments, shares: list(m.shares), syncRevision: REVISION };
  return { externalId: id, customerId, username: username(customer.username), customerName: raw.customerName,
    direction: outbound ? 'outbound' : 'inbound', at, text: raw.text,
    type: mediaType === 'audio' ? 'audio' : ['video', 'file'].includes(mediaType) ? 'document' : (media || storyReference || postReference) ? 'image' : 'text', raw };
}

export function normalizeComment(c, media, shopUsername, replies) {
  const id = text(c?.id, 200), at = iso(c?.timestamp), name = username(c?.username);
  if (!id || !at || !text(media?.id, 200)) throw Error('comentario_invalido');
  return { id, media_id: media.id, media_caption: text(media.caption, 20000),
    media_url: text(media.thumbnail_url ?? media.media_url), media_type: text(media.media_type, 30),
    texto: typeof c.text === 'string' ? c.text : '', username: name, criado_em: at,
    hidden: c.hidden === true,
    loja_respondeu: name?.toLowerCase() === shopUsername.toLowerCase() ||
      replies.some(r => username(r?.username)?.toLowerCase() === shopUsername.toLowerCase()) };
}
