/** Curated guidance, not product facts. Sources and limits in knowledge/consultoria-de-estilo.md. */
import {norm,colorKey,stockFor,type Product} from './core.ts';
export const CONSULTATION_REVISION='v6.0-consultoria-20260910-r1';
export const CONSULT_FIELDS=['event','time','role','dressCode','venue','colorPreference','sizePreference','skipQuestions'] as const;
export const CONSULT_VALUES:Record<string,string[]|null>={event:null,time:['dia','noite','indefinido'],role:['convidada','madrinha','noiva','formanda','indefinido'],dressCode:['formal','semiformal','casual','livre','indefinido'],venue:['praia','campo','salao','igreja','indefinido'],colorPreference:['livre','indefinido'],sizePreference:['indefinido'],skipQuestions:['sim']};
export const STYLE_GUIDANCE=`Ajude a escolher, sem tratar gosto como regra. Convite, papel no evento, horário, local e preferência pessoal vêm antes de uma regra de moda. Em casamento, pergunte se é convidada/madrinha/noiva e se há traje ou paleta definidos; não sugira branco/off-white/marfim/creme a convidada ou madrinha por iniciativa própria. Pedido explícito da cliente ou orientação dos anfitriões pode mudar isso. Não proíba preto nem imponha cores pela pele, idade ou corpo. De dia ou ao ar livre, leveza pode ser útil; à noite e em evento formal, acabamento de festa/longos podem fazer sentido. Cor clara não é obrigação de dia, nem escura de noite. Só atribua tecido, comprimento, caimento, brilho e detalhes a uma peça se constarem nos dados dela. Sem esses dados, apresente opções para a cliente avaliar; não declare que um modelo é perfeito para a ocasião. Não assuma medidas, orçamento nem equivalência de tamanhos.`;

export function consultationQuestion(values:any,consult:any,plan:any,previous:any):{text:string;field:string}|null{
 if(plan.action!=='browse'||plan.page==='next'||plan.page==='repeat'||consult.skipQuestions==='sim'||plan.photos==='show')return null;
 // Already displayed searches can be refined without restarting the interview.
 if(plan.transition==='continue'&&previous?.search?.choices?.length&&!previous?.consultation?.awaiting)return null;
 const party=Boolean(values.occasion||['casamento','formatura','festa','aniversario','gala'].includes(norm(consult.event)));
 const event=consult.event??(values.occasion==='festa'?null:values.occasion);
 if(party&&!event)return {field:'event',text:'Claro, meu bem! É para qual evento? Vai ser de dia ou à noite?'};
 if(party&&!consult.time)return {field:'time',text:'O evento vai ser de dia ou à noite?'};
 if(norm(event)==='casamento'&&(!consult.role||!consult.dressCode))return {field:'wedding',text:!consult.role&&!consult.dressCode?'Você vai como convidada, madrinha ou noiva? Pediram alguma cor ou tipo de traje?':!consult.role?'Você vai como convidada, madrinha ou noiva?':'Pedíram alguma cor ou tipo de traje no convite?'.replace('Pedíram','Pediram')};
 if(!values.color&&!consult.colorPreference&&!values.size&&!consult.sizePreference)return {field:'preferences',text:'Você tem alguma cor em mente ou quer sugestões? E qual tamanho costuma usar?'};
 if(!values.size&&!consult.sizePreference)return {field:'size',text:'Qual tamanho você costuma usar?'};
 if(!values.color&&!consult.colorPreference)return {field:'color',text:'Tem alguma cor em mente ou quer que eu te mostre algumas sugestões?'};
 return null;
}
const white=/^(branco|branca|off white|offwhite|marfim|ivory|creme)$/;
function colorScore(color:string|null,values:any,consult:any){
 if(values.color||consult.colorPreference!=='livre')return 0;
 const c=colorKey(color);
 if(consult.time==='dia'&&/^(lavanda|lilas|rosa bebe|rosa bb|azul serenity|azul bebe|azul bb|verde menta)$/.test(c))return 2;
 if(consult.time==='noite'&&/^(azul marinho|azul royal|vinho|marsala|verde esmeralda|preto)$/.test(c))return 2;
 return 0;
}
export function styleScoped(p:Product,values:any,consult:any):Product{
 const wedding=norm(consult.event??values.occasion)==='casamento';
 const guest=['convidada','madrinha'].includes(consult.role);
 return {...p,variations:p.variations.filter(v=>!(values.excludedColors??[]).includes(colorKey(v.color))&&(!wedding||!guest||values.color||!white.test(colorKey(v.color)))).sort((a,b)=>colorScore(b.color,values,consult)-colorScore(a.color,values,consult))};
}
function evidence(p:Product){
 const a=p.catalog_attributes??{};
 return norm([p.name,p.category,p.fabric,...['tecido','material','comprimento','modelagem','manga','length','fit','sleeves','description'].map(k=>typeof a[k]==='string'?a[k]:'')].join(' '));
}
export function styleRank(p:Product,values:any,consult:any):{score:number;reason:string|null}{
 const e=evidence(p);let score=0,reason:string|null=null;
 const palette=p.variations.filter(v=>Number(v.stock)>0&&(!values.size||v.size===values.size)).find(v=>colorScore(v.color,values,consult)>0);
 if(palette){score+=2;reason=consult.time==='dia'?`Eu sugeriria o ${colorKey(palette.color)} para uma proposta suave durante o dia.`:`O ${colorKey(palette.color)} é uma sugestão para a festa à noite.`;}
 if((consult.time==='dia'||['praia','campo'].includes(consult.venue))&&/\b(chiffon|fluido|fluida|leve|leves)\b/.test(e)){score+=4;reason='A proposta leve desse modelo pode combinar com o evento ao ar livre.';if(!['praia','campo'].includes(consult.venue))reason='A proposta leve desse modelo pode combinar com o evento durante o dia.';}
 if(consult.time==='noite'&&consult.dressCode==='formal'&&/\b(longo|longa)\b/.test(e)){score+=4;reason='O comprimento longo combina com a proposta de um evento formal à noite.';}
 if(consult.dressCode==='casual'&&/\b(paiete|paete|gala)\b/.test(e))score-=3;
 if(consult.dressCode==='formal'&&/\b(casual|malha|praia)\b/.test(e))score-=3;
 if(p.catalog_media?.colors?.some(c=>c.front?.path&&stockFor(p,c.color,values.size)>0&&(!values.color||colorKey(values.color)===colorKey(c.color))))score+=1;
 return {score,reason};
}
