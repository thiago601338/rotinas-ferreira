/** Intent routing above the v4 identity/stock core. No writes and no Meta sends.
 * A product focus is not a permanent search constraint: explicit alternatives
 * switch to catalog browsing while keeping the requested kind/color/size.
 */
import { productPhoto, photoAsset, presentProducts } from './presentation.ts';
import { runTurn as focusTurn, norm, kindOf, stockFor, sizeKey, colorKey, VERSION, REVISION, type Product, type Services } from './core.ts';
import {currentRequest, recentCatalogRequest, serviceTopic, matchesOccasion, occasionValue, type Occasion, type Topic} from './conversation-context.ts';
import {semanticConversation} from './semantic.ts';
import {CATALOG_PAGE_SIZE, galleryFollowup, finishCustomerPresentation} from './customer-experience.ts';
export type Search = { kind: string; occasion?: Occasion; color: string | null; size: string | null; exclude: string[]; shown: string[]; choices: string[] };
type State = { productId: string | null; displayName?: string; color: string | null; size: string | null; imageHash?: string | null; mode: 'focus' | 'browse'; search?: Search; topic?: Topic; contextRevision?: number; lastIntent?: string; lastReply?: string; recovery: number };
const ID = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
const KINDS = new Set(['conjunto', 'vestido', 'macac\u00e3o', 'macaquinho', 'blazer', 'colete', 'blusa', 'cal\u00e7a', 'saia', 'camisa', 'short', 'body', 'corset', 'capa', 'cinto', 'bolsa']);
const cut = (v: any, n = 50): string | null => typeof v === 'string' && v.length <= n ? v : null;
const ids = (xs: any): string[] => Array.isArray(xs) ? [...new Set(xs.filter(x => typeof x === 'string' && ID.test(x)))].slice(0, 100) as string[] : [];
function readState(x: any): State | null {
  if (!x || typeof x !== 'object') return null;
  const pid = typeof x.productId === 'string' && ID.test(x.productId) ? x.productId : null;
  let search: Search | undefined;
  if (x.search && KINDS.has(x.search.kind)) search = { kind: x.search.kind, occasion: occasionValue(x.search.occasion), color: cut(x.search.color), size: cut(x.search.size, 6), exclude: ids(x.search.exclude), shown: ids(x.search.shown), choices: ids(x.search.choices) };
  if (!pid && !search && !cut(x.color) && !cut(x.size, 6)) return null;
  const topic=search ? {kind:search.kind,occasion:search.occasion??null} : x.topic&&KINDS.has(x.topic.kind) ? {kind:x.topic.kind,occasion:occasionValue(x.topic.occasion)} : undefined;
  return { productId: pid, color: cut(x.color), size: cut(x.size, 6), imageHash: cut(x.imageHash, 64), mode: x.mode === 'browse' && search ? 'browse' : 'focus', search, topic, contextRevision:x.contextRevision===2?2:0, lastIntent: cut(x.lastIntent), lastReply: cut(x.lastReply, 900) ?? undefined, recovery: Math.min(2, Math.max(0, Number(x.recovery) || 0)) };
}
export function intentOf(text: string) {
  const n = norm(text);
  const photo = /\b(fotos?|imagens?|fotografias?)\b/.test(n);
  const complaint = /\b(repetindo|repete|repetir|repetiu|mesma coisa|mesma resposta|nao entendeu|nao foi isso|nao respondeu|ja pedi|ja falei|ta errado|esta errado)\b/.test(n);
  const stay = /\b(?:nao (?:quero|preciso|mande|envie|mostre|me mande|me mostre)(?: ver)?|sem)\s+(?:outros?|outras?|alternativas)\b/.test(n) || /\b(?:quero|prefiro|volta|voltar)(?: para| pro| ao| a)?\s+(?:o |a )?(?:mesmo|mesma|anterior|primeiro da foto)\b/.test(n);
  const variationOnly = /\boutr[oa]s? (?:cor(?:es)?|tamanhos?|numeracoes?)\b/.test(n);
  const other = /\b(?:outros?|outras?|alternativas?|parecid[oa]s?|semelhantes?|diferentes?)\b/.test(n);
  const more = /\b(?:tem mais|mostr[ae] mais|manda mais|envia mais|quero ver mais|mais opcoes|mais modelos|mais fotos|mais conjuntos)\b/.test(n) || n === 'mais';
  const alternatives = !stay && ((other && !variationOnly) || more);
  const resend = /\b(?:de novo|novamente|reenvia|reenviar|nao (?:chegou|recebi|carregou)|nao apareceram|nao vieram)\b/.test(n);
  const catalog = kindOf({ category: text, name: '' }) !== 'peça' && !/\b(esse|essa|desse|dessa|deste|desta|mesmo|mesma)\b/.test(n) && !/\b(nao quero|nao preciso|nao mostre|sem fotos|sem imagens)\b/.test(n);
  return { photo, complaint, alternatives, more, stay, resend, variationOnly, catalog };
}
export function eligibleAlternatives(products: Product[], search: Search): Product[] {
  return products.filter(p => norm(p.status) === 'ativo' && kindOf(p) === search.kind && matchesOccasion(p,search.occasion??null) && !search.exclude.includes(p.id) && stockFor(p, search.color, search.size) > 0)
    .sort((a, b) => Number(Boolean(photoAsset(b, search.color, search.size))) - Number(Boolean(photoAsset(a, search.color, search.size))) || a.id.localeCompare(b.id));
}
function plural(k: string): string { return ({'macac\u00e3o': 'macac\u00f5es', 'body': 'bodies'} as Record<string, string>)[k] ?? k + 's'; }
function ordinal(text: string): number | null {
  const n = norm(text), words: Record<string, number> = { primeiro: 1, primeira: 1, segundo: 2, segunda: 2, terceiro: 3, terceira: 3, quarto: 4, quarta: 4, quinto: 5, quinta: 5, sexto: 6, sexta: 6 };
  for (const [w, i] of Object.entries(words)) if (new RegExp(`\\b${w}\\b`).test(n)) return i - 1;
  const m = n.match(/\b(?:foto|opcao|numero)\s*([1-6])\b/) ?? n.match(/^([1-6])$/); return m ? Number(m[1]) - 1 : null;
}
const scopeWords = (s: Search): string => `${plural(s.kind)}${s.occasion ? ' de festa' : ''}${s.color ? ' em ' + s.color : ''}${s.size ? ' no ' + s.size : ''}`;
function productSummary(p: Product, color: string | null, size: string | null) {
  return { id: p.id, nome: kindOf(p), ref: p.sku, preco: p.sale_price, estoqueNaCombinacaoPedida: stockFor(p, color, size), disponivelNoQuePediu: Boolean(color && size && stockFor(p, color, size)), estoqueTotal: stockFor(p, null, null) };
}
export async function runConversation(input: any, svc: Services): Promise<any> {
  if(svc.interpret&&!input.image&&!input.confirmProductId)return finishCustomerPresentation(await semanticConversation(input,svc));
  const result=await presentProducts(await routeConversation(input, svc), input, svc);
  result.revisaoLogica=REVISION;
  if(svc.interpret&&result.contextoProduto){
    result.contextoProduto.conversationId=input.conversationId??null;
    result.contextoProduto.semanticScope={kind:result.contextoProduto.topic?.kind??result.contextoProduto.displayName,color:result.contextoProduto.color,size:result.contextoProduto.size,occasion:result.contextoProduto.topic?.occasion??null,terms:[],excludedColors:[]};
  }
  return finishCustomerPresentation(result);
}
async function routeConversation(input: any, svc: Services): Promise<any> {
  const products = (await svc.products()).filter(p => norm(p.status) === 'ativo'), by = new Map(products.map(p => [p.id, p]));
  const text = String(input.text ?? '').slice(0, 2000), request=currentRequest(text,products), d=request.details, it = intentOf(request.text), previous = readState(input.context);
  it.stay=intentOf(text).stay; it.complaint=intentOf(text).complaint;
  const old = previous?.productId ? by.get(previous.productId) ?? null : null;
  const mentioned = request.kind, image = typeof input.image === 'string' && input.image ? input.image : null;
  const topic=previous?.topic??(old?{kind:kindOf(old),occasion:null}:null);
  // Recover purpose omitted by legacy clients, using only the latest compatible user topic.
  const recent=previous?.contextRevision!==2 ? recentCatalogRequest(input.history,products) : null;
  const occasion=request.occasion??(!request.reset&&recent&&recent.kind===topic?.kind?recent.occasion:null);
  const fresh=request.reset || Boolean(topic&&mentioned!=='peça'&&mentioned!==topic.kind) || Boolean(occasion&&occasion!==topic?.occasion);
  const correctedContext=previous ? {...previous,color:d.color??(request.clearColor?null:previous.color),size:d.size??(request.clearSize?null:previous.size)} : null;
  const focusInput={...input,text:request.correction?(request.text||'tem?'):text,context:correctedContext};
  const human = d.human && !/\b(?:trocar de modelo|troca(?:r)? de assunto|troca(?:r)? (?:o modelo|esse modelo|a peca))\b/.test(norm(text));
  if (human) return answer('Vou encaminhar seu atendimento para a equipe.', 'handoff', previous, [], [], 'cliente pediu equipe');
  const service=serviceTopic(text);
  if(service) return answer(`Vou pedir à equipe para confirmar as informações sobre ${service}.`, 'handoff', null, [], [], service);
  // A new picture starts identity resolution, never a stock-based substitution.
  if (image) {
    const identified = await focusTurn(input, svc);
    if (it.alternatives && identified.contextoProduto) return routeConversation({ ...input, image: null, context: identified.contextoProduto }, svc);
    return enrich(identified, previous, 'identity');
  }
  let selectedId = typeof input.confirmProductId === 'string' ? input.confirmProductId : null;
  if (selectedId && (!ID.test(selectedId) || !by.has(selectedId))) return answer('Essa pe\u00e7a n\u00e3o est\u00e1 mais dispon\u00edvel no cat\u00e1logo. Vamos conferir outra?', 'invalid_selection', previous);
  const choices = previous?.search?.choices ?? [];
  const choiceIndex = ordinal(text);
  if (!selectedId && previous?.mode === 'browse' && choiceIndex !== null) selectedId = choices[choiceIndex] ?? null;
  if (choiceIndex !== null && previous?.mode === 'browse' && !selectedId) return answer('Qual das fotos que mostrei voc\u00ea escolheu?', 'clarify_selection', previous);
  if (selectedId) {
    const p = by.get(selectedId)!;
    const sameTopic=!topic||kindOf(p)===topic.kind;
    const color = d.color ?? (request.clearColor?null:cut(input.pendingColor) ?? (sameTopic?previous?.search?.color ?? previous?.color:null)) ?? null;
    const size = d.size ?? (request.clearSize?null:cut(input.pendingSize, 6) ?? (sameTopic?previous?.search?.size ?? previous?.size:null)) ?? null;
    const selected = { productId: p.id, color, size, displayName: kindOf(p), imageHash: null };
    return enrich(await focusTurn({ text: request.correction?(request.text||'tem?'):text || 'tem?', context: selected }, svc), sameTopic?previous:null, 'selection');
  }
  const sku = /\bFB[-\s]?\d+\b/i.test(text);
  if (sku) return enrich(await focusTurn(focusInput, svc), previous, 'selection');
  if(request.declinedColor||request.declinedSize) {
    const state=correctedContext?.search ? {...correctedContext,search:{...correctedContext.search,color:correctedContext.color,size:correctedContext.size,shown:[],choices:[]}} : correctedContext;
    return answer(request.declinedColor?'Qual cor você prefere?':'Qual tamanho você procura?',request.declinedColor?'clarify_color':'clarify_size',state);
  }
  if(old&&previous?.mode!=='browse'&&request.occasion&&!request.reset&&!it.alternatives&&/\b(esse|essa|ele|ela|mesmo|mesma)\b/.test(request.text)) {
    const evidence=matchesOccasion(old,request.occasion);
    return answer(evidence?'Esse é um modelo de festa. Você vai como convidada ou madrinha?':'Preciso confirmar se esse modelo combina com a ocasião. Vou pedir ajuda à equipe.',evidence?'product_occasion':'handoff',correctedContext,evidence?[old]:[],[],evidence?null:'orientação sobre ocasião');
  }
  // Correct a failed exchange using the last search, not by repeating stock of the anchor.
  if (it.complaint && !it.catalog && !request.correction && !occasion) {
    if ((previous?.recovery ?? 0) >= 1) return answer('Desculpe, ainda n\u00e3o consegui resolver seu pedido. Vou encaminhar a conversa para a equipe.', 'handoff', previous, [], [], 'recuperacao da conversa falhou');
    const lastRequest = previous?.search ? null : recentCatalogRequest(input.history,products);
    if (previous?.search || lastRequest || it.alternatives) {
      const rd = lastRequest?.details ?? d;
      const rk = lastRequest?.kind ?? mentioned;
      const s = searchFrom(previous?.search, rk, rd.color ?? d.color, rd.size ?? d.size,lastRequest?.occasion??occasion);
      if (s) return browse(s, true, true);
    }
    return answer('Desculpe pela repeti\u00e7\u00e3o. Voc\u00ea quer ver outras pe\u00e7as ou conferir uma informa\u00e7\u00e3o dessa?', 'repair_clarify', previous ? { ...previous, recovery: 1 } : null);
  }
  const changeKind = mentioned !== 'pe\u00e7a' && topic && mentioned !== topic.kind;
  if (it.catalog || it.alternatives || changeKind || occasion || (previous?.mode === 'browse' && !it.stay)) {
    if (d.thanks || d.hello) return answer(d.thanks ? 'Por nada!' : 'Ol\u00e1! Como posso te ajudar?', d.thanks ? 'thanks' : 'hello', previous);
    if (!fresh && !it.catalog && previous?.mode === 'browse' && d.wantsPrice && choiceIndex === null) return answer('De qual das fotos voc\u00ea quer saber o valor? Pode me dizer o n\u00famero.', 'clarify_selection', previous);
    if (previous?.mode === 'browse' && /^(?:quero |gostei d[oa] |esse|essa|sim)/.test(norm(text)) && !it.catalog && !it.alternatives && !d.color && !d.size) return answer('Qual das fotos voc\u00ea escolheu? Pode me dizer o n\u00famero.', 'clarify_selection', previous);
    if (previous?.mode === 'browse' && (d.wantsColors || d.wantsSizes) && !d.color && !d.size) return answer('De qual das fotos voc\u00ea quer conferir as varia\u00e7\u00f5es?', 'clarify_selection', previous);
    const browseRequest=it.catalog||it.alternatives||it.photo||it.resend||changeKind||occasion||d.color||d.size||request.correction;
    if(!browseRequest) return answer('O que você gostaria de saber? Se for sobre uma das peças, pode indicar a foto.', 'clarify_request', previous);
    const s = searchFrom(previous?.search, mentioned, d.color, d.size);
    if (!s) return answer('Voc\u00ea procura conjunto, vestido ou outro tipo de pe\u00e7a?', 'clarify_kind', previous);
    if (d.colors.length > 1 || d.sizes.length > 1) return answer(d.colors.length > 1 ? 'Qual cor voc\u00ea quer conferir primeiro?' : 'Qual tamanho voc\u00ea quer conferir primeiro?', 'clarify_filters', previous);
    return browse(s, request.correction || request.reset || it.resend || (it.photo && !it.catalog && !it.alternatives && !d.color && !d.size), request.correction || (it.complaint&&it.catalog));
  }
  if (it.stay && old) return enrich(await focusTurn({ text: d.color || d.size ? request.text : 'tem?', context: { productId: old.id, color: correctedContext!.color, size: correctedContext!.size } }, svc), previous, 'focus');
  if ((it.photo || /\b(costas|parte de tras|atras)\b/.test(norm(text))) && old) {
    const color = correctedContext!.color, size = correctedContext!.size;
    const state = { ...previous!, color, size };
    let photo: any; try { photo = await productPhoto(old, svc, color, size, /\b(costas|parte de tras|atras)\b/.test(norm(text))); } catch {}
    return answer(photo ? 'Aqui está a foto do modelo.' : 'Não consegui carregar a foto solicitada agora. Vou pedir ajuda à equipe.', photo ? 'show_product_photo' : 'photo_unavailable', state, [old], photo ? [photo] : []);
  }
  if (!old && previous?.mode !== 'browse' && (d.color || d.size)) {
    if (d.colors.length > 1 || d.sizes.length > 1) return answer('Qual cor e tamanho você quer conferir primeiro?', 'clarify_filters', previous);
    const state: State = { productId: null, color: d.color ?? previous?.color ?? null, size: d.size ?? previous?.size ?? null, mode: 'focus', recovery: 0 };
    return answer('Você procura conjunto, vestido ou outro tipo de peça?', 'clarify_kind', state);
  }

  // Unknown speech is not permission to replay the last availability template.
  const inventory = request.correction || d.color || d.size || d.wantsColors || d.wantsSizes || d.wantsPrice || d.thanks || d.hello || /\b(tem|disponivel|estoque|quero|gostei|essa|esse)\b/.test(norm(text));
  if (old && !inventory) return answer('O que voc\u00ea gostaria de saber sobre essa pe\u00e7a?', 'clarify_request', previous);
  const result = await focusTurn(focusInput, svc);
  return enrich(result, previous, 'focus');

  function searchFrom(existing: Search | undefined, requestedKind: string, color: string | null, size: string | null, requestedOccasion: Occasion=occasion): Search | null {
    const kind = requestedKind !== 'pe\u00e7a' ? requestedKind : existing?.kind ?? topic?.kind ?? (old ? kindOf(old) : null);
    if (!kind || !KINDS.has(kind)) return null;
    const newTopic=fresh||Boolean(topic&&kind!==topic.kind)||Boolean(requestedOccasion&&requestedOccasion!==topic?.occasion);
    const c = color ?? (request.clearColor||newTopic&&!request.keepColor?null:existing?.color ?? previous?.color ?? null);
    const s = size ?? (request.clearSize||newTopic&&!request.keepSize?null:existing?.size ?? previous?.size ?? null);
    const purpose=requestedOccasion??(newTopic?null:existing?.occasion??topic?.occasion??null);
    const same = !newTopic && existing && existing.kind === kind && existing.occasion===purpose && colorKey(existing.color) === colorKey(c) && sizeKey(existing.size) === sizeKey(s);
    return { kind, occasion:purpose, color: c, size: s, exclude: newTopic||it.catalog&&!it.alternatives ? [] : existing?.exclude ?? (old ? [old.id] : []), shown: same ? existing.shown : [], choices: same ? existing.choices : [] };
  }
  async function browse(s: Search, resend: boolean, repair: boolean): Promise<any> {
    const eligible = eligibleAlternatives(products, s), byEligible = new Map(eligible.map(p => [p.id, p]));
    const sourceId = old&&kindOf(old)===s.kind&&!fresh ? old.id : null;
    const state: State = { productId: sourceId, displayName: s.kind, color: s.color, size: s.size, mode: 'browse', search: s, topic:{kind:s.kind,occasion:s.occasion??null}, contextRevision:2, lastIntent: 'alternatives', recovery: repair ? 1 : 0 };
    const apology = repair ? 'Você tem razão. Vou considerar seu pedido atual. ' : '';
    if (!eligible.length) return answer(`${apology}No momento, não temos outros ${scopeWords(s)}. Quer ver outro estilo?`, 'alternatives_none', state);
    const candidates = resend && s.choices.length ? s.choices.map(id => byEligible.get(id)).filter(Boolean) as Product[] : eligible.filter(p => !s.shown.includes(p.id));
    if (!candidates.length) {
      return answer(`${apology}Por enquanto, são esses os modelos. Quer rever algum ou procurar outro estilo?`, 'alternatives_exhausted', state);
    }
    const shown: Product[] = [], photos: any[] = [], failed: string[] = [];
    // Limit per turn, but fill gaps by trying the next eligible product when a photo is missing.
    for (const p of candidates.slice(0, 12)) {
      if (photos.length >= CATALOG_PAGE_SIZE) break;
      try {
        const photo = await productPhoto(p, svc, s.color, s.size, /\b(costas|parte de tras|atras)\b/.test(norm(text)));
        shown.push(p); photos.push({ ...photo, caption: `Opção ${photos.length + 1} · ${kindOf(p)}` });
      } catch { failed.push(p.id); }
    }
    s.choices = shown.map(p => p.id); s.shown = [...new Set([...s.shown, ...s.choices])];
    let reply: string;
    if (photos.length) reply = apology + galleryFollowup(eligible.filter(p => !s.shown.includes(p.id)).length, !s.size ? 'Qual tamanho você usa?' : !s.color ? 'Qual cor você prefere?' : 'De qual você gostou mais?', new Set(shown.map(p=>p.id)).size);
    else reply = 'Não consegui carregar as fotos agora. Vou pedir ajuda pra te mostrar os modelos.';
    const r = answer(reply, photos.length ? repair ? 'repair_alternatives' : 'show_alternatives' : 'alternatives_photos_unavailable', state, shown, photos);
    r.alternativas = shown.map(p => productSummary(p, s.color, s.size)); r.opcoesSelecionaveis = shown.map(p => p.id);
    r.avisoFotos = photos.length ? 'Fotos de refer\u00eancia dos modelos. A cor da imagem pode ser diferente; a disponibilidade foi consultada na cor e no tamanho pedidos.' : null;
    Object.assign(r.diagnostico, { matchingCount: eligible.length, photoCount: photos.length, missingPhotos: failed.length, remainingCount: eligible.filter(p => !s.shown.includes(p.id)).length, sourceSku: sourceId?old?.sku:null, requestedColor: s.color, requestedSize: s.size, requestedKind: s.kind, requestedOccasion:s.occasion??null, contextAction:fresh?'new_topic':request.correction?'correct_filters':'continue' });
    return r;
  }
  function enrich(r: any, oldState: State | null, intent: string) {
    if (r.contextoProduto) {
      const p=by.get(r.contextoProduto.productId),kind=p?kindOf(p):null;
      const priorTopic=oldState?.topic??(oldState?.search?{kind:oldState.search.kind,occasion:oldState.search.occasion??null}:null);
      r.contextoProduto = { ...r.contextoProduto, topic:kind?{kind,occasion:kind===priorTopic?.kind?priorTopic.occasion:null}:undefined, contextRevision:2, mode: 'focus', lastIntent: intent, lastReply: r.respostaProposta, recovery: 0 };
    }
    r.versaoLogica = VERSION;
    r.opcoesSelecionaveis = [];
    return r;
  }
  function answer(reply: string, decision: string, state: State | null, ps: Product[] = [], photos: any[] = [], handoff: string | null = null) {
    const focused = state?.mode === 'focus' && state.productId ? by.get(state.productId) : null;
    const c = state ? state.mode==='browse'&&state.search ? state.search.color : state.color : null;
    const s = state ? state.mode==='browse'&&state.search ? state.search.size : state.size : null;
    if (state) state = { ...state, lastReply: reply, lastIntent: decision.startsWith('alternatives') || decision.includes('alternatives') ? 'alternatives' : state.lastIntent };
    return { alternativas: [] as ReturnType<typeof productSummary>[], avisoFotos: null as string | null, ok: true, versaoLogica: VERSION, respostaProposta: reply, contextoProduto: state, analiseImagem: null, interpretacao: { cor: c, tamanho: s, termos: [] }, comparacaoVisual: [], candidatosConfirmaveis: [], opcoesSelecionaveis: [], fotos: photos, produtos: ps.map(p => productSummary(p, c, s)), handoff, auditoria: { passed: true, corrections: [], mode: 'deterministic' }, diagnostico: { decision, focusSku: focused?.sku ?? null, imageMethod: null, compared: 0, eligiblePhotos: 0, coverageComplete: null }, aviso: 'Simula\u00e7\u00e3o: nenhuma mensagem foi enviada para a Meta.' };
  }
}

