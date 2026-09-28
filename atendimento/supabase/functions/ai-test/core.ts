/** Pure conversation and identification logic. No Meta sending or catalog writes. */
import { createHash } from 'node:crypto';
import { Buffer } from 'node:buffer';
export type Variation = { color: string | null; size: string | null; stock: number | null };
export type Product = { id: string; name: string; sku: string | null; category: string | null; fabric?:string|null; status: string; sale_price: string | number | null; photo_url: string | null; catalog_attributes?: Record<string,unknown>; search_aliases?: string[]; catalog_media?: { cover_color?: string; colors?: { color: string; front?: { path: string }; back?: { path: string } }[] }; variations: Variation[] };
export type Context = { productId: string; displayName?: string; color: string | null; size?: string | null; imageHash?: string | null };
export type Details = { color: string | null; size: string | null; colors: string[]; sizes: string[]; wantsColors: boolean; wantsSizes: boolean; wantsPrice: boolean; alternatives: boolean; changeProduct: boolean; human: boolean; thanks: boolean; hello: boolean };
export type Manifest = { product_id: string; photo_ref: string; etag: string | null; byte_size: number | null };
export type Match = { productId: string; score: number; sameModel: boolean; reason: string; method: string };
export type Services = { products: () => Promise<Product[]>; manifest: () => Promise<Manifest[]>; photo: (p: Product) => Promise<string>; describe: (image: string) => Promise<any>; compare: (image: string, ps: Product[]) => Promise<Match[]>; interpret?: (input:any)=>Promise<any> };
export const VERSION = 'v6.0-product-messages';
export const REVISION = 'v6.0-semantic-conversation-20260910-r9';
export function norm(v: unknown): string { return String(v ?? '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim(); }
const ALIASES: Record<string, string> = { preta: 'preto', branca: 'branco', vermelha: 'vermelho', amarela: 'amarelo', roxa: 'roxo', dourada: 'dourado', prateada: 'prata', offwhite: 'off white' };
export function colorKey(v: unknown): string { const n = norm(v); return ALIASES[n] ?? n; }
export function sizeKey(v: unknown): string { const n = norm(v).replace(/\s/g, ''); return n === 'unico' ? 'U' : n.toUpperCase(); }
export function units(v: unknown): number { const n = Number(v); return Number.isFinite(n) && n > 0 ? Math.floor(n) : 0; }
const KINDS: [RegExp, string][] = [
  [/\bconjuntos?\b/, 'conjunto'], [/\bvestidos?\b/, 'vestido'], [/\b(macacao|macacoes)\b/, 'macac\u00e3o'], [/\bmacaquinhos?\b/, 'macaquinho'],
  [/\bblazers?\b/, 'blazer'], [/\bcoletes?\b/, 'colete'], [/\bblusas?\b/, 'blusa'], [/\bcalcas?\b/, 'cal\u00e7a'], [/\bsaias?\b/, 'saia'],
  [/\bcamisas?\b/, 'camisa'], [/\bshorts?\b/, 'short'], [/\bbod(y|ies)\b/, 'body'], [/\bcorsets?\b/, 'corset'], [/\bcapas?\b/, 'capa'], [/\bcintos?\b/, 'cinto'], [/\bbolsas?\b/, 'bolsa']
];
export function kindOf(p: Pick<Product, 'category' | 'name'>): string {
  for (const input of [p.category, p.name]) for (const [re, k] of KINDS) if (re.test(norm(input))) return k;
  return 'pe\u00e7a';
}
export function noun(k: string): string { return ['blusa', 'cal\u00e7a', 'saia', 'camisa', 'capa', 'bolsa', 'pe\u00e7a'].includes(k) ? `essa ${k}` : `esse ${k}`; }
export function join(xs: string[]): string { return xs.length < 2 ? (xs[0] ?? '') : `${xs.slice(0, -1).join(', ')} e ${xs.at(-1)}`; }
function unique(xs: string[], key: (x: string) => string): string[] { const seen = new Set<string>(); return xs.filter(x => { const k = key(x); if (!k || seen.has(k)) return false; seen.add(k); return true; }); }
export function inStock(p: Product): Variation[] { return (p.variations ?? []).filter(v => units(v.stock) > 0); }
export function colorsOf(p: Product, s: string | null = null): string[] {
  return unique(inStock(p).filter(v => !s || sizeKey(v.size) === sizeKey(s)).map(v => String(v.color ?? '')).filter(Boolean), colorKey).map(c => c.toLocaleLowerCase('pt-BR').trim());
}
export function sizesOf(p: Product, c: string | null = null): string[] {
  const order = ['PP', 'P', 'M', 'G', 'GG', 'G1', 'G2', 'G3', 'U'];
  return unique(inStock(p).filter(v => !c || colorKey(v.color) === colorKey(c)).map(v => sizeKey(v.size)), x => x).sort((a, b) => (order.indexOf(a) < 0 ? 100 : order.indexOf(a)) - (order.indexOf(b) < 0 ? 100 : order.indexOf(b)) || a.localeCompare(b));
}
export function stockFor(p: Product, c: string | null, s: string | null): number {
  return inStock(p).filter(v => (!c || colorKey(v.color) === colorKey(c)) && (!s || sizeKey(v.size) === sizeKey(s))).reduce((n, v) => n + units(v.stock), 0);
}
const COLORS = ['preto', 'branco', 'vermelho', 'amarelo', 'roxo', 'azul', 'azul marinho', 'azul royal', 'azul serenity', 'verde', 'verde oliva', 'verde militar', 'verde menta', 'verde esmeralda', 'rosa', 'rosa beb\u00ea', 'ros\u00e9', 'pink', 'lil\u00e1s', 'bege', 'nude', 'marrom', 'cinza', 'vinho', 'marsala', 'caramelo', 'areia', 'bege areia', 'off white', 'f\u00facsia', 'laranja', 'prata', 'dourado', 'terracota', 'creme', 'coral', 'salm\u00e3o', 'turquesa'];
export function parseDetails(text: string, products: Product[]): Details {
  const n = norm(text), source = unique([...products.flatMap(p => (p.variations ?? []).map(v => String(v.color ?? ''))), ...COLORS], colorKey);
  const terms = source.map(display => ({ display: display.toLocaleLowerCase('pt-BR'), key: colorKey(display) }));
  for (const [alias, key] of Object.entries(ALIASES)) terms.push({ display: terms.find(x => x.key === key)?.display ?? key, key: alias });
  terms.sort((a, b) => b.key.length - a.key.length);
  let remaining = ` ${n} `; const found: string[] = [];
  for (const t of terms) { const marker = ` ${t.key} `; if (remaining.includes(marker)) { found.push(t.display); remaining = remaining.split(marker).join(' '); } }
  if (!found.length) { const m = n.match(/\b(?:na cor|cor|tem em|nesse tom de)\s+([a-z ]+?)(?=\s+(?:no|na|tamanho|tam|por|e)\b|$)/); if (m && m[1].length <= 35 && !/\b(qual|qualquer|outra|mesma|e|ou|nem|tamanho|tamanhos|disponivel|disponiveis)\b/.test(m[1])) found.push(m[1]); }
  const colors = unique(found, colorKey);
  // References and currency amounts are not clothing sizes.
  const sizeText = n.replace(/\bfb\s*\d+\b/g, '').replace(/\b(?:r |reais )\d+(?: \d+)?\b/g, '')
    .replace(/\bp\s+(?=(?:mim|voce|vcs|minha|meu|casamento|festa|formatura|trabalhar|usar|ir|presentear)\b)/g,'para ');
  const sizes = unique((sizeText.match(/\b(?:pp|gg|g[123]|p|m|g|u|unico|3[468]|4[02468]|5[024])\b/g) ?? []).map(sizeKey), x => x);
  return { color: colors.length === 1 ? colors[0] : null, size: sizes.length === 1 ? sizes[0] : null, colors, sizes,
    wantsColors: /\b(cores|outra cor|qual cor|quais cor)\b/.test(n), wantsSizes: /\b(tamanhos|quais tamanho|qual tamanho|numeracoes)\b/.test(n), wantsPrice: /\b(preco|valor|quanto|custa)\b/.test(n),
    alternatives: /\b(parecid[oa]s?|outro modelo|outra peca|outras opcoes|outros modelos)\b/.test(n), changeProduct: /\b(outro produto|outra peca|outro modelo|trocar de modelo|nova peca)\b/.test(n),
    human: /\b(atendente|humano|vendedora|reclamacao|reembolso|estorno|defeito|desconto|paguei|procon|troca|devolucao)\b/.test(n), thanks: /^(obrigad[oa]|valeu|certo|ok|tudo bem)$/.test(n), hello: /^(oi|ola|bom dia|boa tarde|boa noite)$/.test(n) };
}
export function mergeContext(p: Product, previous: Context | null, d: Details, imageHash: string | null, imageColor: string | null): Context {
  const same = previous?.productId === p.id;
  // A new photo never carries another product's color/size. A repeated photo keeps the current selection.
  return { productId: p.id, displayName: kindOf(p), color: d.color ?? (imageHash && imageHash !== previous?.imageHash ? imageColor ?? (same ? previous?.color : null) : same ? previous?.color : null) ?? null,
    size: d.size ?? (same ? previous?.size : null) ?? null, imageHash: imageHash ?? (same ? previous?.imageHash : null) ?? null };
}
export function replyFor(p: Product, ctx: Context, d: Details): { reply: string; decision: string } {
  const k = kindOf(p), item = noun(k), c = ctx.color, s = ctx.size ?? null, all = colorsOf(p), inSize = colorsOf(p, s), inColor = sizesOf(p, c);
  const out = (reply: string, decision: string) => ({ reply, decision });
  if (d.human) return out('Vou encaminhar seu atendimento para a equipe.', 'handoff');
  if (d.colors.length > 1) return out(`Qual dessas cores voc\u00ea prefere para ${item}?`, 'clarify_color');
  if (d.sizes.length > 1) return out('Qual tamanho voc\u00ea quer conferir primeiro?', 'clarify_size');
  if (d.wantsPrice && !d.color && !d.size) { const n = Number(p.sale_price); return out(p.sale_price !== null && Number.isFinite(n) ? `${item.startsWith('essa') ? 'A' : 'O'} ${k} custa ${n.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })}.` : 'Vou pedir para a equipe confirmar o pre\u00e7o.', 'price'); }
  if (d.thanks) return out('Por nada!', 'thanks');
  if (d.hello) return out('Ol\u00e1! Como posso te ajudar?', 'hello');
  if (!inStock(p).length) return out(`No momento, ${item} est\u00e1 esgotad${item.startsWith('essa') ? 'a' : 'o'} em todas as cores.`, 'sold_out');
  if (d.wantsColors) {
    if (s && !inSize.length) return out(`No ${s}, n\u00e3o temos ${item} no momento. Em outros tamanhos, temos em ${join(all)}.`, 'no_size');
    return out(`Temos ${item}${s ? ' no ' + s : ''} em ${join(s ? inSize : all)}. Qual cor voc\u00ea prefere?`, 'list_colors');
  }
  if (d.wantsSizes) {
    if (c && !inColor.length) return out(`Nessa cor, n\u00e3o temos ${item} agora. Temos em ${join(all)}. Qual dessas cores voc\u00ea prefere?`, 'no_color');
    return out(`Temos ${item}${c ? ' em ' + c : ''} nos tamanhos ${join(sizesOf(p, c))}. Qual voc\u00ea procura?`, 'list_sizes');
  }
  if (c && !inColor.length) {
    if (s && !inSize.length) return out(`Nessa cor, n\u00e3o temos ${item}. Tamb\u00e9m n\u00e3o temos no ${s}. Em outros tamanhos, temos em ${join(all)}.`, 'no_color_or_size');
    return out(`Nessa cor, n\u00e3o temos ${item} agora. Temos em ${join(s ? inSize : all)}${s ? ' no ' + s : ''}. Qual dessas cores voc\u00ea prefere?`, 'no_color');
  }
  if (c && !s) return out(`Temos ${item} em ${c}. Qual tamanho voc\u00ea procura?`, 'ask_size');
  if (c && s) {
    if (stockFor(p, c, s) > 0) return out(`Temos ${item} em ${c} no ${s}.`, 'available');
    if (inSize.length) return out(`Em ${c}, n\u00e3o temos ${item} no ${s}. No ${s}, temos em ${join(inSize)}. Qual dessas cores voc\u00ea prefere?`, 'no_combination');
    return out(`Em ${c}, n\u00e3o temos ${item} no ${s}. Nessa cor, temos nos tamanhos ${join(inColor)}.`, 'no_combination');
  }
  if (s) {
    if (inSize.length) return out(`Temos ${item} no ${s} em ${join(inSize)}. Qual cor voc\u00ea prefere?`, 'ask_color');
    return out(`No ${s}, n\u00e3o temos ${item} no momento.`, 'no_size');
  }
  return out(`Temos ${item} em ${join(all)}. Qual cor voc\u00ea prefere?`, 'ask_color');
}
export function safeContext(x: any): Context | null {
  if (!x || typeof x.productId !== 'string' || !/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(x.productId)) return null;
  const clean = (v: any, max = 45) => typeof v === 'string' && v.length <= max ? v : null;
  return { productId: x.productId, color: clean(x.color), size: clean(x.size, 6), imageHash: clean(x.imageHash, 64) };
}
export function decodeImage(image: string): { bytes: Buffer; mime: string; sha: string; md5: string } {
  const m = /^data:(image\/(?:jpeg|png|webp|gif));base64,([A-Za-z0-9+/=]+)$/i.exec(image);
  if (!m || m[2].length > 14_000_000) throw new Error('invalid_image');
  const bytes = Buffer.from(m[2], 'base64'); if (!bytes.length || bytes.length > 10 * 1024 * 1024) throw new Error('invalid_image');
  const valid = (bytes[0] === 0xff && bytes[1] === 0xd8) || bytes.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10])) || (bytes.subarray(0, 4).toString() === 'RIFF' && bytes.subarray(8, 12).toString() === 'WEBP') || /^GIF8[79]a$/.test(bytes.subarray(0, 6).toString());
  if (!valid) throw new Error('invalid_image');
  return { bytes, mime: m[1], sha: createHash('sha256').update(bytes).digest('hex'), md5: createHash('md5').update(bytes).digest('hex') };
}
export function selectVisual(ms: Match[]): Match | null {
  const rows = [...ms].sort((a, b) => b.score - a.score), a = rows[0], b = rows.find(x => x.productId !== a?.productId);
  return a?.sameModel === true && a.score >= .90 && (!b || a.score - b.score >= .12) ? a : null;
}
export async function identify(image: string, products: Product[], svc: Services, deadline = Date.now() + 100000): Promise<any> {
  const im = decodeImage(image), manifest = await svc.manifest(), by = new Map(products.map(p => [p.id, p])), exact: Product[] = [];
  // ETag/size only prefilter; SHA-256 of downloaded bytes decides an exact match. No SKU hardcoding.
  const possible = manifest.filter(m => by.has(m.product_id) && ((m.etag ?? '').replaceAll('"', '') === im.md5 || Number(m.byte_size) === im.bytes.length));
  for (const m of possible) { const p = by.get(m.product_id)!; try { if (decodeImage(await svc.photo(p)).sha === im.sha) exact.push(p); } catch {} }
  const ids = unique(exact.map(p => p.id), x => x); let analysis: any = null;
  try { analysis = await svc.describe(image); } catch {}
  if (ids.length) return { matches: ids.map(productId => ({ productId, score: 1, sameModel: true, reason: 'Arquivo id\u00eantico, conferido por SHA-256.', method: 'sha256' })), selected: ids.length === 1 ? by.get(ids[0]) : null, analysis, sha: im.sha, method: ids.length === 1 ? 'exact_file' : 'duplicate_photo', compared: ids.length, eligible: manifest.length, complete: true };
  if (analysis?.nao_e_roupa === true) return { matches: [], selected: null, analysis, sha: im.sha, method: 'not_garment', compared: 0, eligible: 0, complete: true };
  const kind = kindOf({ category: analysis?.tipo ?? '', name: '' }), all = products.filter(p => p.photo_url);
  const primary = kind === 'pe\u00e7a' ? all : all.filter(p => kindOf(p) === kind || (['colete', 'blazer'].includes(kind) && kindOf(p) === 'conjunto'));
  const rest = all.filter(p => !primary.some(x => x.id === p.id)); let matches: Match[] = [], compared = 0, complete = true, eligible = primary.length;
  for (const [i, group] of [primary, rest].entries()) {
    if (!group.length) continue; if (i === 1) eligible += rest.length;
    for (let offset = 0; offset < group.length; offset += 12) {
      if (Date.now() > deadline - 30000) { complete = false; break; }
      const batches = [group.slice(offset, offset + 6), group.slice(offset + 6, offset + 12)].filter(b => b.length);
      const results = await Promise.allSettled(batches.map(batch => svc.compare(image, batch)));
      results.forEach((r, j) => { if (r.status === 'fulfilled') { const allowed = new Set(batches[j].map(p => p.id)); const valid = r.value.filter(m => allowed.has(m.productId)); matches.push(...valid); compared += valid.length; if (valid.length !== batches[j].length) complete = false; } else complete = false; });
    }
    if (!complete || selectVisual(matches)) break;
  }
  const best = new Map<string, Match>(); for (const m of matches) if (by.has(m.productId) && (!best.has(m.productId) || best.get(m.productId)!.score < m.score)) best.set(m.productId, m);
  matches = [...best.values()].sort((a, b) => b.score - a.score);
  // Visual similarity is NOT a probability or an identity guarantee. Ask for confirmation.
  return { matches, selected: null, analysis, sha: im.sha, method: 'visual_confirmation', compared, eligible, complete };
}
export async function runTurn(input: any, svc: Services): Promise<any> {
  const ps = (await svc.products()).filter(p => norm(p.status) === 'ativo'), by = new Map(ps.map(p => [p.id, p])), text = String(input.text ?? '').slice(0, 2000), d = parseDetails(text, ps), previous = safeContext(input.context);
  let selected: Product | null = null, identity: any = null, ctx: Context | null = null;
  const image = typeof input.image === 'string' && input.image ? input.image : null;
  if (d.human) return response('Vou encaminhar seu atendimento para a equipe.', 'handoff', null, previous, null, 'cliente pediu equipe');
  if (image) { identity = await identify(image, ps, svc); selected = identity.selected; }
  const sku = text.match(/\bFB[-\s]?(\d+)\b/i); if (!image && sku) selected = ps.find(p => norm(p.sku) === norm('FB-' + sku[1])) ?? null;
  const mentioned = kindOf({ category: text, name: '' }), old = previous ? by.get(previous.productId) : null;
  if (!image && !sku && !d.changeProduct && old && (mentioned === 'pe\u00e7a' || mentioned === kindOf(old))) selected = old;
  if (!image && input.confirmProductId) selected = by.get(String(input.confirmProductId)) ?? null;
  if (!selected) {
    if (identity) {
      const reasonable = (identity.matches ?? []).filter((m: Match) => m.method === 'sha256' || (m.sameModel && m.score >= .65)).slice(0, 1);
      // Keep full comparison in diagnostics; only reasonable candidates can be confirmed in UI.
      identity.confirmable = reasonable;
      return response(reasonable.length ? 'Me confirma se é esse modelo? Aí eu confiro a cor e o tamanho que você quer.' : 'Pode me mandar uma foto mais de perto da peça? Quero conferir o modelo certinho pra você.', 'confirm_product', null, null, identity);
    }
    return response(d.hello ? 'Ol\u00e1! Me envie a foto da pe\u00e7a que voc\u00ea procura.' : d.thanks ? 'Por nada!' : 'De qual pe\u00e7a voc\u00ea est\u00e1 falando? Me envie a foto para eu conferir.', 'clarify_product', null, null, null);
  }
  ctx = mergeContext(selected, previous, d, identity?.sha ?? null, identity?.analysis?.cor_principal ?? null);
  if (input.confirmProductId && !d.color && typeof input.pendingColor === 'string') ctx.color = input.pendingColor.slice(0, 45);
  if (input.confirmProductId && !d.size && typeof input.pendingSize === 'string') ctx.size = sizeKey(input.pendingSize).slice(0, 6);
  if (d.alternatives) return response('Voc\u00ea procura outro modelo no mesmo estilo? Me diga o que prefere.', 'clarify_alternative', selected, ctx, identity);
  const r = replyFor(selected, ctx, d); return response(r.reply, r.decision, selected, ctx, identity);
  function response(reply: string, decision: string, p: Product | null, context: Context | null, id: any, handoff: string | null = null) {
    return { ok: true, versaoLogica: VERSION, respostaProposta: reply, contextoProduto: context, analiseImagem: id?.analysis ?? null,
      interpretacao: { cor: context?.color ?? d.color ?? id?.analysis?.cor_principal ?? null, tamanho: context?.size ?? d.size, termos: [] },
      comparacaoVisual: (id?.matches ?? []).map((m: Match) => ({ ...m, productName: by.get(m.productId) ? kindOf(by.get(m.productId)!) : 'pe\u00e7a', sku: by.get(m.productId)?.sku ?? null })),
      candidatosConfirmaveis: (id?.confirmable ?? []).map((m: Match) => m.productId),
      produtos: p ? [{ id: p.id, nome: kindOf(p), ref: p.sku, preco: p.sale_price, estoqueTotal: stockFor(p, null, null),
        estoqueNaCombinacaoPedida: context?.color || context?.size ? stockFor(p, context?.color ?? null, context?.size ?? null) : null,
        disponivelNoQuePediu: decision === 'available' ? true : decision.startsWith('no_') || decision === 'sold_out' ? false : null,
        coresDisponiveis: colorsOf(p), tamanhosNessaCor: sizesOf(p, context?.color ?? null), coresNesseTamanho: colorsOf(p, context?.size ?? null) }] : [],
      handoff, auditoria: { passed: true, corrections: [], mode: 'deterministic' },
      diagnostico: { decision, focusSku: p?.sku ?? null, imageMethod: id?.method ?? null, compared: id?.compared ?? 0, eligiblePhotos: id?.eligible ?? 0, coverageComplete: id?.complete ?? null, imageSha256: id?.sha ?? null },
      aviso: 'Simula\u00e7\u00e3o: nenhuma mensagem foi enviada para a Meta.' };
  }
}
