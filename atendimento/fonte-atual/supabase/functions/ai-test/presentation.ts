/** One product at a time: image, contextual stock sizes, then catalog price. */
import { colorKey, sizeKey, norm, inStock, sizesOf, join, kindOf, stockFor, decodeImage, type Product, type Services } from './core.ts';
import {CATALOG_PAGE_SIZE} from './customer-experience.ts';

export function availability(p: Product, color: string | null, size: string | null) {
  const colorLabel=color?.toLocaleLowerCase('pt-BR')??null;
  const variants = inStock(p).filter(v => (!color || colorKey(v.color) === colorKey(color)) && (!size || sizeKey(v.size) === sizeKey(size)));
  const scoped = { ...p, variations: variants };
  const sizes = sizesOf(scoped);
  const groups = new Map<string, { cor: string; tamanhos: string[] }>();
  for (const v of variants) {
    const key = colorKey(v.color), label = String(v.color || 'Cor não informada').toLocaleLowerCase('pt-BR');
    if (!groups.has(key)) groups.set(key, { cor: label, tamanhos: sizesOf({ ...p, variations: variants.filter(x => colorKey(x.color) === key) }) });
  }
  const stockText = !variants.length
    ? `Tamanhos disponíveis${color ? ' em ' + colorLabel : ''}${size ? ' no ' + size : ''}: indisponível no momento.`
    : color
      ? `Tamanhos disponíveis em ${colorLabel}: ${sizes.length ? join(sizes) : 'a confirmar'}.`
      : `Tamanhos disponíveis: ${[...groups.values()].map(g => `${g.cor}: ${g.tamanhos.length ? join(g.tamanhos) : 'a confirmar'}`).join('; ')}.`;
  const price = p.sale_price !== null && String(p.sale_price).trim() !== '' && Number.isFinite(Number(p.sale_price)) && Number(p.sale_price) > 0 ? Number(p.sale_price) : null;
  const priceText = price === null ? 'Preço: a confirmar com a equipe.' : `Preço: ${price.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })}.`;
  return { tamanhosDisponiveis: sizes, variacoesDisponiveis: [...groups.values()], tamanhosTexto: stockText, preco: price, precoTexto: priceText };
}

export function photoAsset(p: Product, color: string | null, size: string | null, back = false) {
  const all = Array.isArray(p.catalog_media?.colors) ? p.catalog_media.colors : [];
  const view = back ? 'back' : 'front';
  const relevant = all.filter(c => c[view]?.path && (!color || colorKey(c.color) === colorKey(color)) && (color || stockFor(p, c.color, size) > 0));
  const preferred = relevant.find(c => colorKey(c.color) === colorKey(p.catalog_media?.cover_color)) ?? relevant[0];
  if (preferred) return { path: preferred[view]!.path, corFoto: preferred.color, vista: view, avisoFoto: null };
  // A named color/view must never be illustrated with another color or an unlabelled cover.
  if (back || color || all.some(c=>c.front?.path)) return null;
  if (p.photo_url) return { path: p.photo_url, corFoto: null, vista: 'legacy', avisoFoto: 'Foto de referência do modelo; a cor e a vista da foto não estão confirmadas.' };
  return null;
}

export async function productPhoto(p: Product, svc: Services, color: string | null, size: string | null, back = false) {
  if(stockFor(p,color,size)<=0)throw Error('variant_unavailable');
  const asset = photoAsset(p, color, size, back);
  if (!asset) throw new Error(back ? 'back_photo_missing' : 'photo_missing');
  const image = await svc.photo({ ...p, photo_url: asset.path });
  decodeImage(image); // Never treat a non-image body as a delivered catalog photograph.
  const { path, ...details } = asset;
  return { id: p.id, ref: p.sku, nome: kindOf(p), image, ...details, ...availability(p, color??asset.corFoto, size), caption: kindOf(p) };
}

/** Show each photographed, available color with its own sizes and price. */
export async function productPhotos(p:Product,svc:Services,color:string|null,size:string|null,back=false,limit=CATALOG_PAGE_SIZE,skipColors:string[]=[]){
 const mapped=p.catalog_media?.colors??[],view=back?'back':'front';
 const order=[...new Set(p.variations.map(v=>colorKey(v.color)))];
 const colors=[...new Map(mapped.filter(c=>c[view]?.path&&stockFor(p,c.color,size)>0&&(!color||colorKey(c.color)===colorKey(color))&&!skipColors.includes(colorKey(c.color))).map(c=>[colorKey(c.color),c.color])).values()].sort((a,b)=>order.indexOf(colorKey(a))-order.indexOf(colorKey(b)));
 const photos:any[]=[];
 if(colors.length){for(const c of colors.slice(0,limit))try{photos.push(await productPhoto(p,svc,c,size,back));}catch{}return photos;}
 if(!skipColors.length)try{photos.push(await productPhoto(p,svc,color,size,back));}catch{}
 return photos;
}

export function photoGap(p:Product,photos:any[],color:string|null,size:string|null,back=false){
 if(stockFor(p,color,size)<=0)return '';
 if(!photos.length)return back?'A foto de costas eu ainda não tenho aqui. Quer que a equipe confira pra você?':color?`A foto desse modelo em ${color} eu ainda não tenho aqui. Quer que a equipe confira pra você?`:'A foto desse modelo eu ainda não tenho aqui. Quer que a equipe confira pra você?';
 if(photos.some(f=>f.vista==='legacy'))return 'Essa foto mostra o modelo. Quando escolher a cor, posso pedir à equipe uma foto dela.';
 const missing=[...new Set(inStock(p).filter(v=>(!color||colorKey(v.color)===colorKey(color))&&(!size||sizeKey(v.size)===sizeKey(size))).map(v=>colorKey(v.color)))].filter(c=>!photos.some(f=>colorKey(f.corFoto)===c));
 return missing.length?'Se quiser ver outra cor desse modelo, me diga qual.':'';
}

export function photoMessages(photos:any[],selectable:string[]=[]){
 return photos.flatMap(f=>[
  {tipo:'imagem',produtoId:f.id,imagem:f.image,legenda:f.caption,corFoto:f.corFoto??null,purpose:f.purpose??'product',selecionavel:selectable.includes(f.id)},
  {tipo:'texto',produtoId:f.id,purpose:f.purpose??'product',corFoto:f.corFoto??null,texto:f.purpose==='confirm_identity'?'É esse modelo que você quer?':`${f.tamanhosTexto}\n${f.precoTexto}${f.recommendation?'\n'+f.recommendation:''}`}
 ]);
}

export async function presentProducts(result: any, input: any, svc: Services) {
  const ps = await svc.products(), by = new Map(ps.filter(p => norm(p.status) === 'ativo').map(p => [p.id, p]));
  const context=result.contextoProduto;
  const scoped=context?.mode==='browse'&&context.search?context.search:context;
  const c = scoped ? scoped.color??null : result.interpretacao?.cor??null;
  const s = scoped ? scoped.size??null : result.interpretacao?.tamanho??null;
  const decision = result.diagnostico?.decision;
  const noPhotos=/\b(sem fotos?|sem imagens?|nao (?:me )?(?:mande|envie|mostre) (?:as )?(?:fotos|imagens))\b/.test(norm(input.text));
  if(decision==='confirm_product'&&!noPhotos){
    // Identity confirmation is not a sales gallery. No stock, price or alternatives before confirmation.
    const id=(result.candidatosConfirmaveis??[])[0],p=by.get(id);let f:any=null;
    if(p)try{const path=p.photo_url??p.catalog_media?.colors?.find(c=>c.front?.path)?.front?.path;if(path){const image=await svc.photo({...p,photo_url:path});decodeImage(image);f={id:p.id,ref:p.sku,nome:kindOf(p),image,purpose:'confirm_identity',caption:'Confere o modelo pra mim',corFoto:null};}}catch{}
    result.fotos=f?[f]:[];result.candidatosConfirmaveis=f?[id]:[];result.opcoesSelecionaveis=[];
    result.respostaProposta=f?'Me confirma se é esse modelo? Aí eu confiro a cor e o tamanho que você quer.':'Pode me mandar uma foto mais de perto da peça? Quero conferir o modelo certinho pra você.';
    result.mensagens=f?photoMessages([f],[id]):[{tipo:'texto',texto:result.respostaProposta}];
    if(f){result.mensagens[1].texto=result.respostaProposta;result.contextoProduto={productId:null,mode:'browse',color:c,size:s,search:{kind:kindOf(p!),color:c,size:s,exclude:[],shown:[],choices:[id]},recognizedProducts:[id],awaitingConfirmation:true};}
    return result;
  }
  if (noPhotos) {
    if(decision==='confirm_product'){result.respostaProposta='Pode me dizer algum detalhe desse modelo ou a referência da peça? Assim eu confiro sem te mandar fotos.';result.candidatosConfirmaveis=[];}
    result.fotos = [];
    result.opcoesSelecionaveis = [];
    result.mensagens = [{ tipo: 'texto', texto: result.respostaProposta }];
    return result;
  }
  const quiet = new Set(['hello', 'thanks', 'handoff', 'clarify_product', 'clarify_request', 'clarify_selection', 'clarify_filters', 'clarify_color', 'clarify_size', 'repair_clarify', 'invalid_selection']);
  const ids = new Set<string>((result.fotos ?? []).map((p: any) => p.id));
  if (!quiet.has(decision) && result.contextoProduto?.mode !== 'browse') {
    for (const id of (result.candidatosConfirmaveis ?? []).slice(0, 3)) ids.add(id);
    if (result.contextoProduto?.productId) ids.add(result.contextoProduto.productId);
  }
  const back = /\b(costas|parte de tras|atras)\b/.test(norm(input.text));
  const photos: any[] = [], failures: string[] = [];
  for (const id of ids) {
    if(photos.length>=CATALOG_PAGE_SIZE)break;
    const p = by.get(id); if (!p) continue;
    const existing = (result.fotos ?? []).find((f: any) => f.id === id && f.tamanhosTexto && (!back || f.vista === 'back'));
    try {
      if(stockFor(p,c,s)<=0)continue;
      const fs=existing?[existing]:await productPhotos(p,svc,c,s,back,CATALOG_PAGE_SIZE-photos.length);
      if(!fs.length)throw Error('photo_missing');
      const option=[...new Set(photos.map(f=>f.id)),id].indexOf(id)+1;
      photos.push(...fs.map(f=>({...f,caption:`Opção ${option} · ${kindOf(p)}${f.corFoto?' · '+f.corFoto:''}`})));
    } catch { failures.push(id); }
  }
  result.fotos = photos;
  result.opcoesSelecionaveis = (result.opcoesSelecionaveis ?? []).filter((id: string) => photos.some(f => f.id === id));
  const selectable = new Set([...(result.opcoesSelecionaveis ?? []), ...(result.candidatosConfirmaveis ?? [])]);
  result.mensagens = photoMessages(photos,[...selectable]);
  if (failures.length) {
    const focus=context?.productId?by.get(context.productId):null;
    const note = focus?photoGap(focus,photos,c,s,back):back ? 'A foto de costas eu ainda não tenho aqui. Quer que a equipe confira pra você?' : 'Não consegui carregar todas as fotos agora. Quer que a equipe confira pra você?';
    // Do not claim that a failed image was shown, even when an old decision requested it.
    if (!photos.length&&!focus) result.respostaProposta = note;
    else result.respostaProposta += ' ' + note;
    result.diagnostico.falhasFotos = failures.length;
  }
  if(photos.some(f=>f.vista==='legacy')&&!/Essa foto mostra o modelo/.test(result.respostaProposta))result.respostaProposta+=' Essa foto mostra o modelo. Quando escolher a cor, posso pedir à equipe uma foto dela.';
  if (photos.length) result.respostaProposta = result.respostaProposta.replace(/Veja as fotos abaixo\.\s*/g, '').replace(/da foto abaixo/g, 'da foto');
  result.mensagens.push({ tipo: 'texto', texto: result.respostaProposta });
  return result;
}
