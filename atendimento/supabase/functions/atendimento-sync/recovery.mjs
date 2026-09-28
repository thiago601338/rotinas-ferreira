import { MetaError } from './graph.mjs';

export const MESSAGE_FIELDS = 'id,created_time,from,to,message,attachments,shares,story';
const withStage = (error, stage) => { error.operation = stage; return error; };
export function metaIssue(error, stage) {
  return { etapa: stage, codigo: Number.isInteger(error?.code) ? error.code : null,
    subcodigo: Number.isInteger(error?.subcode) ? error.subcode : null,
    motivo: error instanceof MetaError ? error.reason : 'falha_de_leitura' };
}
export async function readConversationDetail(graph, id) {
  try { return { available: true, detail: await graph.get(id, { fields: `id,messages.limit(20){${MESSAGE_FIELDS}}` }) }; }
  catch (error) {
    // Somente a combinação confirmada em produção autoriza avançar esta conversa.
    if (error instanceof MetaError && error.code === 100 && error.subcode === 33) return { available: false, issue: metaIssue(error, 'conversa_detalhe') };
    throw withStage(error, 'conversa_detalhe');
  }
}
export async function addGap(cursor, conversationId) {
  const hash = new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(conversationId)));
  const fingerprint = [...hash].map(x => x.toString(16).padStart(2, '0')).join('');
  if (cursor.gaps.includes(fingerprint)) return cursor;
  if (cursor.gaps.length >= 1000) throw withStage(new Error('limite_conversas_inacessiveis'), 'conversa_detalhe');
  return { ...cursor, gaps: [...cursor.gaps, fingerprint] };
}
