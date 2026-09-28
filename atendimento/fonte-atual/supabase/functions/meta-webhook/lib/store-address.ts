/** Public store fact only. Never infer an address from customer history. */
export const STORE_ADDRESS_REVISION = 'public-store-address-20260911-r1';

export function isStoreAddressQuestion(text: string): boolean {
  if (typeof text !== 'string' || text.length > 300) return false;
  let n = text.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase()
    .replace(/[?!.,;:]/g, ' ').replace(/\s+/g, ' ').trim();
  n = n.replace(/^(?:oi+|ola|bom dia|boa tarde|boa noite)\s+/, '')
    .replace(/(?:\s+)?por favor$/, '').trim();
  n = n.replace(/\b(?:o )?seu endereco\b/g, 'o endereco da loja')
    .replace(/\b(?:a )?sua localizacao\b/g, 'a localizacao da loja')
    .replace(/^(?:voces|vcs) ficam onde$/, 'onde voces ficam');
  // Whole-request allowlist: mixed requests and personal addresses never pass.
  return /^(?:(?:qual (?:e )?(?:o |a )?|(?:me )?(?:manda|mande|envia|envie|informa|informe|passe|passa)(?: me)? (?:o |a )?|(?:pode|poderia) (?:me )?(?:mandar|enviar|informar|passar) (?:o |a )?)?(?:endereco|localizacao)(?: (?:da loja|da ferreira boutique|da ferreira|de voces|de vcs))?|onde (?:fica|fica localizada|esta localizada|e) (?:a loja|a ferreira boutique|a ferreira)|onde (?:voces|vcs) (?:ficam|estao|se localizam)|onde fica|como (?:chegar|chego) (?:na loja|a loja|na ferreira boutique)|(?:qual (?:e )?(?:o )?)?ponto de referencia(?: da loja)?)$/.test(n);
}

export function storeAddressReply(address: any): string | null {
  if (!address || address.source !== 'owner_confirmed' || !Number.isFinite(Date.parse(address.confirmedAt))) return null;
  const clean = (v: unknown): v is string => typeof v === 'string' && v.trim().length > 0 && v.length <= 200 && !/[\r\n<>]|https?:|[{}]/i.test(v);
  if (!['street','number','neighborhood','city','state','reference'].every(k => clean(address[k]))) return null;
  if (!/^\d{1,6}[A-Za-z]?$/.test(address.number) || !/^[A-Z]{2}$/.test(address.state)) return null;
  if (address.formerStreetName && !clean(address.formerStreetName)) return null;
  const former = address.formerStreetName ? ` (antiga ${address.formerStreetName.trim()})` : '';
  return `Estamos na ${address.street.trim()}${former}, nº ${address.number}, ${address.neighborhood.trim()}, ${address.city.trim()} – ${address.state}.\n\n${address.reference.trim()}`;
}
