/** Customer presentation only; stock, identity and conversation evidence stay in the engine. */
export const EXPERIENCE_REVISION = 'v6.2.3-gallery-count-20260910-r1';
export const CATALOG_PAGE_SIZE = 6;
export const MESSAGE_DELAY_MS = 5000;
export const INTRODUCTION = 'Olá, meu bem! Me chamo Swemilly e vou assumir seu atendimento a partir daqui.';
export const INTRODUCTION_KEY = 'swemilly-v1';

export function customerText(value: string): string {
  return String(value ?? '').split('\n').filter(line => !/^\s*Foto (?:de referência do modelo|do modelo em .+; os tamanhos informados)/i.test(line)).join('\n').trim();
}

export function galleryFollowup(remaining: number, followup: string, shownModels: number): string {
  if (shownModels < 1) return '';
  if (shownModels === 1) return remaining > 0 ? 'Gostou desse modelo ou quer ver mais opções?' : 'Gostou desse modelo?';
  if (remaining > 0) return 'Tenho mais modelos também. Quer ver mais ou gostou de algum desses?';
  return customerText(followup) || 'Gostou de algum desses modelos?';
}

export function finishCustomerPresentation(result: any) {
  result.experienceRevision = EXPERIENCE_REVISION;
  result.deliveryPolicy = { minimumDelayMs: MESSAGE_DELAY_MS, catalogPageSize: CATALOG_PAGE_SIZE };
  result.respostaProposta = customerText(result.respostaProposta);
  result.mensagens = (result.mensagens ?? []).map((p: any) => p.tipo === 'texto' ? { ...p, texto: customerText(p.texto) } : p).filter((p: any) => p.tipo !== 'texto' || p.texto);
  return result;
}

/** The simulator has no persistent channel session. Real channels persist the accepted introduction. */
export function addSimulationIntroduction(result: any, input: any) {
  const hasReply = Array.isArray(input.history) && input.history.some((m: any) => m.role === 'assistant');
  if (!hasReply) result.mensagens.unshift({ tipo: 'texto', texto: INTRODUCTION, purpose: 'introduction' });
  return result;
}
