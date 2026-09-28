/** Interpret the current request before merging any prior search constraints. */
import {norm, kindOf, parseDetails, type Product} from './core.ts';
export type Occasion = 'casamento' | 'festa' | 'formatura' | null;
export type Topic = {kind: string; occasion: Occasion};
export const occasionValue = (x: unknown): Occasion => ['casamento','festa','formatura'].includes(String(x)) ? x as Occasion : null;
export function occasionOf(text: string): Occasion {
  const n=norm(text);
  if (/\b(casamento|madrinha|convidada)\b/.test(n)) return 'casamento';
  if (/\b(formatura|formanda)\b/.test(n)) return 'formatura';
  if (/\b(festas?|gala)\b/.test(n)) return 'festa';
  return null;
}
export function matchesOccasion(p: Product, occasion: Occasion) {
  if (!occasion) return true;
  // Only catalog evidence, never infer suitability from a photo or stock alone.
  const evidence=norm(`${p.name} ${p.category}`);
  return /\b(festa|festas|gala)\b/.test(evidence) || (occasion==='casamento' ? /\b(casamento|madrinha|convidada)\b/ : /\b(formatura|formanda)\b/).test(evidence);
}
export function serviceTopic(text: string): string | null {
  const n=norm(text);
  if (/\b(entrega|entregam|frete|envio|prazo|retirada|retirar)\b/.test(n)) return 'entrega e retirada';
  if (/\b(pix|cartao|parcelamento|parcelam|parcelas|pagamento|boleto)\b/.test(n)) return 'formas de pagamento';
  if (/\b(endereco|localizacao|onde fica|horario|abre|fecham|abrem)\b/.test(n)) return 'endereço e horário da loja';
  if (/\b(meu pedido|minha compra|rastreio|rastreamento)\b/.test(n)) return 'seu pedido';
  return null;
}
export function currentRequest(text: string, products: Product[]) {
  let clearColor=false,clearSize=false,declinedColor=false,declinedSize=false;
  // Keep clause boundaries: a rejected filter must not swallow its replacement.
  const clauses=text.normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase()
    .split(/[,;.!?]|\bmas\b|\be sim\b/);
  const clean=clauses.map(clause=>norm(clause).replace(
    /\b(?:nao\s+(?:(?:disse|falei|pedi|perguntei|escolhi|defini|mencionei|quero|preciso|e|era)\b\s*)?|sem\s+(?:preferencia|restricao|filtro)(?:s)?(?:\s+de)?\s*|esquece(?:r)?\s+(?:o |a |os |as )?)(.*?)(?=\b(?:mas|quero|prefiro|falei|disse|agora|estou perguntando|me mostra|me mostre|me manda)\b|$)/g,
    (span: string, body: string)=>{
      const rejected=parseDetails(body,products);
      const first=body.replace(/^(?:no|na|em)\s+/,'').split(' ')[0]??'';
      const leading=parseDetails(first,products);
      // “Não tem outros preto G?” is a question, not rejection of preto/G.
      if(/^nao\b/.test(span)&&!/^nao (?:disse|falei|pedi|perguntei|escolhi|defini|mencionei|quero|preciso|e|era)\b/.test(span)&&!leading.color&&!leading.size) return span;
      const color=rejected.colors.length>0||/\b(cor|cores)\b/.test(body);
      const size=rejected.sizes.length>0||/\b(tamanho|tamanhos|numeracao)\b/.test(body);
      clearColor ||= color; clearSize ||= size;
      declinedColor ||= color&&/\bnao (?:quero|preciso)\b/.test(span);
      declinedSize ||= size&&/\bnao (?:quero|preciso)\b/.test(span);
      return ' ';
    })).join(' ');
  const n=norm(text),positive=norm(clean),details=parseDetails(positive,products);
  if (/\b(?:qualquer |todas? (?:as )?|sem (?:definir |escolher )?)(?:cor|cores)\b/.test(n)) clearColor=true;
  if (/\b(?:qualquer |todos? (?:os )?|sem (?:definir |escolher )?)(?:tamanho|tamanhos)\b/.test(n)) clearSize=true;
  if (/\b(?:qualquer|todas as) cor(?:es)? (?:e|ou) tamanho\b/.test(n)) {clearColor=true;clearSize=true;}
  // A new request can explicitly keep one dimension without carrying the other.
  const keepColor=/\b(?:mesma cor|mesmo tom|mant(?:em|enha|er) (?:a )?cor)\b/.test(positive);
  const keepSize=/\b(?:mesmo tamanho|mesma numeracao|mant(?:em|enha|er) (?:o )?tamanho|mesma cor e tamanho)\b/.test(positive);
  const keepBoth=/\b(?:mesmos filtros|mesma cor e (?:no )?mesmo tamanho)\b/.test(positive);
  const kind=kindOf({category:positive,name:''}),occasion=occasionOf(positive);
  const reset=/\b(?:agora|outro assunto|mudando de assunto|nova busca|nova pesquisa|do zero|esquece|esquecer|na verdade|estou perguntando|eu perguntei)\b/.test(n) && (kind!=='peça'||occasion!==null);
  return {text:positive,details,kind,occasion,reset,keepColor:keepColor||keepBoth,keepSize:keepSize||keepBoth,
    clearColor,clearSize,declinedColor:declinedColor&&!details.color,declinedSize:declinedSize&&!details.size,
    correction:clearColor||clearSize};
}
/** A history repair is limited to the newest user topic, never the first search. */
export function recentCatalogRequest(history: any, products: Product[]) {
  if (!Array.isArray(history)) return null;
  for (const row of history.slice(-12).reverse()) {
    if (!row||row.role!=='user'||typeof row.content!=='string') continue;
    const text=row.content.slice(0,2000);
    if (serviceTopic(text)) return null;
    const request=currentRequest(text,products);
    if (request.kind!=='peça'||request.occasion) return request;
    if (/\b(outros|outras|alternativas|mais modelos)\b/.test(norm(text))) return request;
  }
  return null;
}
