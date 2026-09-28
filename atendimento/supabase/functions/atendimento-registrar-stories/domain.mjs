import { iso, text } from '../atendimento-sync/domain.mjs';

export function validateRegistration(input, now = Date.now()) {
  if (!input || typeof input !== 'object' || Array.isArray(input)) throw Error('corpo_invalido');
  if (typeof input.letra !== 'string' || !/^[A-Za-z0-9_-]{1,20}$/.test(input.letra)) throw Error('letra_invalida');
  if (!Number.isInteger(input.n_midias) || input.n_midias < 1 || input.n_midias > 100) throw Error('n_midias_invalido');
  const start = iso(input.publicado_de), end = iso(input.publicado_ate);
  const zoned = value => typeof value === 'string' && /(?:Z|[+-]\d{2}:\d{2})$/.test(value);
  if (!start || !end || !zoned(input.publicado_de) || !zoned(input.publicado_ate) || Date.parse(start) > Date.parse(end) || Date.parse(end) - Date.parse(start) > 86400000 || Date.parse(end) > now + 60000) throw Error('janela_invalida');
  const perMedia = input.midias !== undefined;
  if (input.varios_modelos === true && !perMedia) throw Error('manifesto_por_midia_obrigatorio');
  if (perMedia && (!Array.isArray(input.midias) || input.midias.length !== input.n_midias)) throw Error('manifesto_contagem_invalida');
  const definitions = perMedia ? input.midias : [{ sku: input.sku, product_id: input.product_id, cor: input.cor }];
  const media = definitions.map((item, index) => {
    if (!item || typeof item !== 'object') throw Error('produto_invalido');
    const sku = text(item.sku, 100), productId = text(item.product_id, 36), color = text(item.cor, 100);
    if (item.cor !== undefined && item.cor !== null && !color) throw Error('cor_invalida');
    if ((!sku && !productId) || (productId && !/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(productId))) throw Error('produto_invalido');
    const storyId = item.story_id === undefined ? null : String(item.story_id);
    if (storyId && !/^\d{5,40}$/.test(storyId)) throw Error('story_id_invalido');
    return { sku, product_id: productId, cor: color, story_id: storyId, ordem: index + 1 };
  });
  const explicit = media.filter(x => x.story_id);
  if (explicit.length && (!perMedia || explicit.length !== media.length || new Set(explicit.map(x => x.story_id)).size !== media.length)) throw Error('story_ids_incompletos');
  return { letra: input.letra.toUpperCase(), n_midias: input.n_midias, publicado_de: start, publicado_ate: end, por_midia: perMedia, midias: media };
}

export function mapStories(input, stories, existing = []) {
  const min = Date.parse(input.publicado_de), max = Date.parse(input.publicado_ate);
  const unique = new Map();
  for (const story of stories) if (/^\d{5,40}$/.test(String(story.id)) && iso(story.timestamp) && Date.parse(story.timestamp) >= min && Date.parse(story.timestamp) <= max) unique.set(String(story.id), story);
  const registered = new Set(existing.map(x => String(x.story_id)));
  const candidates = [...unique.values()].filter(x => !registered.has(String(x.id))).sort((a, b) => Date.parse(a.timestamp) - Date.parse(b.timestamp) || String(a.id).localeCompare(String(b.id)));
  if (candidates.length !== input.n_midias) return { ok: false, motivo: 'contagem_divergente', esperadas: input.n_midias, encontradas: candidates.length };
  if (!input.por_midia) return { ok: true, pares: candidates.map(story => ({ story, produto: input.midias[0] })) };
  if (input.midias.every(x => x.story_id)) {
    const byId = new Map(candidates.map(x => [String(x.id), x]));
    if (input.midias.some(x => !byId.has(x.story_id))) return { ok: false, motivo: 'story_id_fora_da_janela' };
    return { ok: true, pares: input.midias.map(produto => ({ story: byId.get(produto.story_id), produto })) };
  }
  // Sem IDs explícitos, o manifesto segue a ordem real da publicação. Empate é ambíguo.
  if (new Set(candidates.map(x => Date.parse(x.timestamp))).size !== candidates.length) return { ok: false, motivo: 'ordem_ambigua_informe_story_ids' };
  return { ok: true, pares: candidates.map((story, index) => ({ story, produto: input.midias[index] })) };
}
