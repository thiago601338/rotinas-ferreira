import { ACCOUNT_ID, GRAPH_VERSION } from './domain.mjs';

export async function verifiedAccount(graph, fields = 'id') {
  // Instagram Login pode devolver em /me um ID canônico diferente do ID usado nas mensagens.
  // A prova de identidade é a resolução dos dois endpoints pelo mesmo token, nunca um ID fixo de /me.
  const [me, configured] = await Promise.all([
    graph.get('me', { fields }),
    graph.get(ACCOUNT_ID, { fields: 'id' }),
  ]);
  const meId = typeof me?.id === 'string' ? me.id : '';
  const configuredId = typeof configured?.id === 'string' ? configured.id : '';
  if (!/^\d{5,40}$/.test(meId) || meId !== configuredId) throw Error('conta_instagram_divergente');
  return me;
}

export class MetaError extends Error {
  constructor(status, code, subcode, description = '') {
    super('meta_' + (code ?? status)); this.status = status; this.code = code; this.subcode = subcode;
    // A mensagem original não é guardada: apenas classificação sem IDs, URLs ou texto de cliente.
    this.reason = /nonexisting field|nonexistent field|invalid (?:parameter.*)?field|unknown field/i.test(description) ? 'campo_invalido'
      : /cursor|paging|pagination|after.*invalid|invalid.*after/i.test(description) ? 'cursor_invalido'
      : /unsupported get request|does not exist|cannot be loaded|not available|deleted|could not be found/i.test(description) ? 'objeto_inacessivel' : 'parametro_ou_acesso';
  }
  get permissionDenied() { return [10, 200].includes(this.code); }
}

export async function bytes(response, maximum) {
  if (Number(response.headers.get('content-length')) > maximum) { await response.body?.cancel(); throw Error('resposta_muito_grande'); }
  const reader = response.body?.getReader();
  if (!reader) return new Uint8Array();
  const chunks = []; let total = 0;
  try {
    while (true) {
      const part = await reader.read(); if (part.done) break;
      total += part.value.length;
      if (total > maximum) throw Error('resposta_muito_grande');
      chunks.push(part.value);
    }
  } catch (error) { await reader.cancel(); throw error; }
  const result = new Uint8Array(total); let offset = 0;
  for (const chunk of chunks) { result.set(chunk, offset); offset += chunk.length; }
  return result;
}

export class Graph {
  constructor(token, fetcher = fetch, deadline = Date.now() + 70000) { this.token = token; this.fetcher = fetcher; this.deadline = deadline; }
  async get(path, params = {}) {
    if (!/^(?:me|[A-Za-z0-9_:.=-]+)(?:\/(?:conversations|media|messages|comments|replies|stories|permissions))?$/.test(path)) throw Error('caminho_meta_invalido');
    const left = this.deadline - Date.now(); if (left < 1500) throw Error('prazo_sync');
    const url = new URL(`https://graph.instagram.com/${GRAPH_VERSION}/${path}`);
    for (const [key, value] of Object.entries(params)) if (value !== null && value !== undefined) url.searchParams.set(key, String(value));
    // Páginas profundas de conversas podem demorar mais que os demais endpoints.
    // O orçamento global do sync continua limitando a execução.
    const requestTimeout = path === 'me/conversations' ? 25000 : 10000;
    const response = await this.fetcher(url, { headers: { Authorization: 'Bearer ' + this.token }, redirect: 'error', signal: AbortSignal.timeout(Math.min(left, requestTimeout)) });
    let data; try { data = JSON.parse(new TextDecoder().decode(await bytes(response, 4 * 1024 * 1024))); } catch { throw Error('meta_resposta_invalida'); }
    if (!response.ok || data.error) throw new MetaError(response.status, data.error?.code, data.error?.error_subcode, data.error?.message ?? '');
    return data;
  }
}
