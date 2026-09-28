import {VERSION,REVISION,norm,kindOf,colorKey,sizeKey,stockFor,parseDetails,replyFor,type Product,type Services} from './core.ts';
import {CATALOG_PAGE_SIZE,galleryFollowup} from './customer-experience.ts';
import {availability,productPhotos,photoGap,photoMessages} from './presentation.ts';
import {CONSULT_FIELDS,CONSULT_VALUES,CONSULTATION_REVISION,consultationQuestion,styleScoped,styleRank} from './style-guidance.ts';
import {matchesOccasion,occasionValue} from './conversation-context.ts';
import {ACTIONS,KINDS,type SemanticPlan,type Slot,type Evidence} from './semantic-protocol.ts';
const uuid=/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
const string=(x:any,max=2000)=>typeof x==='string'?x.slice(0,max):'';
const list=(xs:any)=>Array.isArray(xs)?xs:[];
const ids=(xs:any)=>list(xs).filter(x=>typeof x==='string'&&uuid.test(x)).slice(0,100);
// Recover the actual user substring when the model changes casing or spacing.
// The reply still quotes original bytes; no generated wording becomes evidence.
export function actualQuote(source:string,quote:string):string|null{
  const escaped=quote.trim().split(/\s+/).map(s=>s.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')).join('\\s+');
  const left=/^[\p{L}\p{N}]/u.test(quote.trim())?'(?<![\\p{L}\\p{N}])':'';
  const right=/[\p{L}\p{N}]$/u.test(quote.trim())?'(?![\\p{L}\\p{N}])':'';
  return escaped?source.match(new RegExp(left+escaped+right,'iu'))?.[0]??null:null;
}
function supportsSize(quote:string,value:string):boolean{
  const spelled=({P:/\bpequen[a-z]*\b/,M:/\bmedi[oa]\b/,G:/\bgrand[a-z]*\b/} as any)[value];
  return parseDetails(quote,[]).sizes.includes(value)||Boolean(spelled?.test(norm(quote)));
}
function supportsColor(quote:string,value:string):boolean{
  const words=norm(quote).split(' ');
  return norm(value).split(' ').every(part=>words.some(w=>w===part||(part.length>=4&&w.startsWith(part.slice(0,4)))));
}
export function conversationTurns(input:any){
  const out:any[]=[];let length=0;
  for(const r of list(input.history).slice(-40).reverse()){
    if(!r||!['user','assistant'].includes(r.role)||typeof r.content!=='string')continue;
    const content=r.content.slice(0,2000);if(length+content.length>16000)break;length+=content.length;out.unshift({role:r.role,content});
  }
  return [...out.map((r,i)=>({...r,id:'h'+i})),{id:'current',role:'user',content:string(input.text)}];
}
export function validatePlan(raw:any,turns:any[],current:any):SemanticPlan {
  if(!raw||!ACTIONS.includes(raw.action)||!['new','continue','correct','resume'].includes(raw.transition)||!['first','next','repeat'].includes(raw.page)||!['stock','colors','sizes','price','features','photo'].includes(raw.detail)||!['auto','show','hide'].includes(raw.photos))throw Error('intent_invalid');
  const by=new Map(turns.map(t=>[t.id,t]));
  function evidence(e:any,allowCurrent=true,field='reference'):Evidence {
    const t=by.get(e?.turn),q=string(e?.quote,400),actual=t&&q?actualQuote(t.content,q):null;
    if(!t||t.role!=='user'||!actual||(!allowCurrent&&t.id==='current'))throw Error('intent_unproved:'+field+':'+String(e?.turn));
    return {turn:t.id,quote:actual};
  }
  function slot(x:any,field:string):Slot {
    if(!x||x.value===null)return {value:null,evidence:{turn:null,quote:null},carryQuote:null};
    if(typeof x.value!=='string'||!x.value.trim()||x.value.length>60)throw Error('intent_invalid');
    let proof=evidence(x.evidence,true,field);
    if(raw.transition==='new'&&proof.turn!=='current'){
      const repeated=actualQuote(by.get('current').content,proof.quote!);
      if(repeated)proof={turn:'current',quote:repeated};
    }
    const carry=raw.transition==='new'&&field!=='kind'&&proof.turn!=='current'?(string(x.carryQuote,200)||null):null;
    if(carry&&!actualQuote(by.get('current').content,carry))throw Error('intent_unproved:carry:'+field);
    if(raw.transition==='new'&&field!=='kind'&&proof.turn!=='current'&&!carry)return {value:null,evidence:{turn:null,quote:null},carryQuote:null};
    let value=x.value.trim();
    if(field==='kind'&&!KINDS.includes(value))throw Error('intent_invalid_kind');
    if(field==='occasion'&&!occasionValue(value))throw Error('intent_invalid_occasion');
    if(field==='size'){value=sizeKey(value);if(!/^(PP|P|M|G|GG|G[1-3]|U|3[468]|4[02468]|5[024])$/.test(value))throw Error('intent_invalid_size');}
    if(field==='color')value=colorKey(value);
    if(field==='size'){
      const source=by.get(proof.turn).content;
      if(value==='P'&&/\bp\s+(?:mim|voce|vcs|minha|meu|casamento|festa|formatura|trabalhar|usar|ir|presentear)\b/.test(norm(source))&&!supportsSize(source,'P'))return {value:null,evidence:{turn:null,quote:null},carryQuote:null};
      if(!supportsSize(proof.quote!,value))throw Error('intent_unproved_size');
    }
    if(field==='color'){
      if(!supportsColor(proof.quote!,value))throw Error('intent_unproved_color');
    }
    return {value,evidence:proof,carryQuote:carry};
  }
  const dialogue=['respond','clarify','handoff'].includes(raw.action);
  const used=dialogue?{}:raw;
  const plan:any={action:raw.action,transition:raw.transition,kind:slot(used.kind,'kind'),color:slot(used.color,'color'),size:slot(used.size,'size'),occasion:slot(used.occasion,'occasion'),terms:list(used.terms).slice(0,4).map(x=>slot(x,'term')),excludedColors:list(used.excludedColors).slice(0,5).map(x=>slot(x,'color')),productId:null,page:raw.page,detail:raw.detail,photos:raw.photos,reply:string(raw.reply,700).trim(),followup:string(raw.followup,240).trim(),reference:{turn:null,quote:null}};
  plan.consultation=Object.fromEntries(CONSULT_FIELDS.map(field=>{
    // Optional styling facts without a valid USER source remain unknown. They
    // must neither become a preference nor discard the client's valid event/time.
    try{
      const fact=Array.isArray(used.consultation)?used.consultation.find((x:any)=>x?.name===field):used.consultation?.[field];
      const value=slot(fact,'consultation.'+field);
      if(value.value&&CONSULT_VALUES[field]&&!CONSULT_VALUES[field]!.includes(value.value))return [field,slot(null,'consultation.'+field)];
      return [field,value];
    }catch{return [field,slot(null,'consultation.'+field)];}
  }));
  const allowed=new Set([current?.productId,...ids(current?.search?.choices),...ids(current?.recognizedProducts)]);
  if(!dialogue&&raw.productId!==null){if(!uuid.test(raw.productId)||!allowed.has(raw.productId))throw Error('intent_invalid_selection');plan.productId=raw.productId;}
  if(raw.action==='explain_context'&&raw.reference?.turn){
    const reference=evidence(raw.reference,false),now=parseDetails(by.get('current').content,[]);
    const color=now.color??current?.color,size=now.size??current?.size;
    // A real quote is not enough: it must support the attributes being questioned.
    if((!color||supportsColor(reference.quote!,color))&&(!size||supportsSize(reference.quote!,size)))plan.reference=reference;
  }
  if(raw.action==='explain_context'){
    // A challenge is a dialogue repair, not a request to restore another topic's filters.
    plan.color=slot(null,'color');plan.size=slot(null,'size');plan.excludedColors=[];
  }
  const shortSize=norm(by.get('current').content);
  if(['focus','browse'].includes(plan.action)&&/^(pp|p|m|g|gg|g[123]|u|3[468]|4[02468]|5[024])$/.test(shortSize)){
    // In a size-only follow-up, the typed value outranks an older cited size.
    plan.size=slot({value:shortSize,evidence:{turn:'current',quote:by.get('current').content},carryQuote:null},'size');
  }
  // A plural catalogue question has no single selected product. Repair only
  // this inconsistent route when the model supplied a proven catalogue scope.
  // A singular "esse" without identification must still wait for a human.
  const nowText=norm(by.get('current').content);
  if(plan.action==='focus'&&!plan.productId&&plan.kind.value&&current?.mode==='browse'
    &&/\b(quais|desses|dessas|modelos|pecas|vestidos|conjuntos)\b/.test(nowText)
    &&!/\b(esse|essa|este|esta|primeir[oa]|segund[oa]|terceir[oa]|opcao [1-9])\b/.test(nowText))plan.action='browse';
  return plan;
}
export async function semanticConversation(input:any,svc:Services):Promise<any>{
  const pageSize=Math.min(CATALOG_PAGE_SIZE,Math.max(1,Number(input.maxPhotos)||CATALOG_PAGE_SIZE));
  const products=(await svc.products()).filter(p=>norm(p.status)==='ativo'),by=new Map(products.map(p=>[p.id,p]));
  const conversationId=string(input.conversationId,80)||null;
  // Context from another conversation cannot supply product identity or filters.
  const supplied=input.context&&typeof input.context==='object'?input.context:null;
  const mismatch=Boolean(conversationId&&supplied?.conversationId&&conversationId!==supplied.conversationId);
  const previous=mismatch?null:supplied;
  const turns=conversationTurns(mismatch?{...input,history:[]}:input);
  const sku=string(input.text).match(/\bFB[-\s]?(\d+)\b/i);
  const recognized=sku?products.filter(p=>norm(p.sku)===norm('FB-'+sku[1])).map(p=>p.id):[];
  const choices=ids(previous?.search?.choices);
  const knownIds=[...new Set([...recognized,previous?.productId,...choices])].filter(id=>by.has(id));
  const attributeKeys=['tecido','material','modelagem','comprimento','decote','manga','fit','length','lining','closure','sleeves','stretch','neckline','description','measurements'];
  const knownProducts=knownIds.slice(0,CATALOG_PAGE_SIZE+1).map(id=>{
    const p=by.get(id)!;
    const attributes=Object.fromEntries(attributeKeys.flatMap(key=>typeof p.catalog_attributes?.[key]==='string'?[[key,string(p.catalog_attributes[key],180)]]:[]));
    // Only references and customer-facing characteristics. Prices/stock/raw metadata stay local.
    return {id:p.id,option:choices.includes(id)?choices.indexOf(id)+1:null,kind:kindOf(p),attributes};
  });
  const payload={turns,contextHint:previous?{productId:by.has(previous.productId)?previous.productId:null,mode:previous.mode,kind:previous.search?.kind??previous.topic?.kind,color:previous.color,size:previous.size,occasion:previous.search?.occasion??previous.topic?.occasion,choices:ids(previous.search?.choices),consultation:previous.consultation??null,awaitingConfirmation:previous.awaitingConfirmation??previous.referenceContext?.awaitingConfirmation??false}:null,knownProducts,knownBusiness:[],vocabulary:{kinds:KINDS,colors:[...new Set(products.flatMap(p=>p.variations.map(v=>colorKey(v.color))).filter(Boolean))].slice(0,120),sizes:[...new Set(products.flatMap(p=>p.variations.map(v=>sizeKey(v.size))).filter(Boolean))]}};
  let plan:SemanticPlan,modelInfo:any=null;
  try{const interpreted=await svc.interpret!(payload);modelInfo=interpreted.meta;plan=validatePlan(interpreted.plan??interpreted,turns,{...previous,recognizedProducts:recognized});}
  catch(e){return response('Não consegui entender esse pedido com segurança. Pode me dizer o que você quer ver ou saber agora?', 'semantic_clarify', previous,[],[],{interpreter:'unavailable',failure:e instanceof Error?e.message:'intent_failed',modelInfo});}
  const consult=Object.fromEntries(CONSULT_FIELDS.map(k=>[k,plan.consultation[k].value]));
  const values={kind:plan.kind.value,color:plan.color.value,size:plan.size.value,occasion:plan.occasion.value,terms:plan.terms.map(t=>t.value).filter(Boolean),excludedColors:plan.excludedColors.map(t=>t.value).filter(Boolean),consultation:consult};
  // An actual reply to a sent color photo is an explicit selection of that variant.
  // The channel creates this marker only from its accepted outbound message record.
  if(plan.action==='focus'&&plan.transition==='continue'&&plan.productId===previous?.productId&&!values.color&&previous?.quotedPhotoColor&&plan.detail!=='colors')values.color=colorKey(previous.quotedPhotoColor);
  let state:any={productId:plan.productId,displayName:values.kind,color:values.color,size:values.size,mode:plan.action==='browse'?'browse':'focus',topic:{kind:values.kind,occasion:values.occasion},contextRevision:3,conversationId,semanticScope:values};
  state.consultation={...consult,awaiting:null};
  const diag={interpreter:'language_model',consultationRevision:CONSULTATION_REVISION,contextAction:plan.transition,requestedKind:values.kind,requestedColor:values.color,requestedSize:values.size,requestedOccasion:values.occasion,modelInfo,evidence:{kind:plan.kind.evidence,color:plan.color.evidence,size:plan.size.evidence,occasion:plan.occasion.evidence,consultation:plan.consultation},historyTurns:turns.length-1};
  if(['respond','clarify','handoff'].includes(plan.action)) {
    // Dialogue does not advance a gallery. Keep the visual references for a subsequent answer.
    state=previous?{...previous,conversationId}:null;
    if(plan.transition==='new')state=null;
    const fallback=plan.action==='handoff'?'A equipe precisa confirmar essa informação para você.':'Pode me dizer um pouco mais sobre o que você procura?';
    return response(plan.reply||fallback,plan.action==='handoff'?'handoff':'semantic_'+plan.action,state,[],[],diag,plan.action==='handoff'?'informação solicitada pela cliente':null);
  }
  if(plan.action==='explain_context'){
    state={...state,productId:null,mode:'browse',search:{...values,exclude:[],shown:[],choices:[]}};
    // Verbatim reference is assembled from a verified USER message, never generated by the model.
    const source=plan.reference.quote;
    const intro=source?`Eu tinha entendido isso quando você disse: “${source}”. Podemos mudar, sem problema.`:'Desculpa, meu bem, eu me confundi. Você não tinha pedido isso.';
    return response(`${intro} ${plan.followup||'O que você prefere ver agora?'}`,'explain_context',state,[],[],{...diag,reference:plan.reference});
  }
  const scoped=(p:Product):Product=>styleScoped(p,values,consult);
  if(plan.action==='focus'){
    const product=plan.productId?by.get(plan.productId):null;
    if(!product)return response('Qual das peças você quer conferir? Pode indicar a foto.','semantic_clarify',previous,[],[],diag);
    const p=scoped(product);state={...state,productId:p.id,displayName:kindOf(p),mode:'focus',topic:{kind:kindOf(p),occasion:values.occasion}};
    const details=parseDetails('',products);details.wantsColors=plan.detail==='colors';details.wantsSizes=plan.detail==='sizes';details.wantsPrice=plan.detail==='price';
    const fact=replyFor(p,{productId:p.id,color:values.color,size:values.size},details);
    const reply=plan.detail==='features'?(plan.reply||'Preciso confirmar esse detalhe pra te passar certinho.'):fact.reply;
    const back=plan.detail==='photo'&&/\b(costas|tras|atras)\b/.test(norm(input.text));
    const skip=plan.page==='next'&&previous?.productId===p.id?previous?.shownPhotoColors??[]:[];
    const photoColor=plan.detail==='colors'?null:values.color;
    const photos=plan.photos!=='hide'?await productPhotos(p,svc,photoColor,values.size,back,pageSize,skip):[];
    state.shownPhotoColors=[...new Set([...skip,...photos.map(f=>colorKey(f.corFoto)).filter(Boolean)])];
    const note=plan.photos!=='hide'?' '+photoGap(p,photos,photoColor,values.size,back):'';
    return response(reply+note,fact.decision,state,[p],photos,{...diag,focusSku:p.sku});
  }
  if(!values.kind&&!values.occasion&&!values.terms.length)return response(plan.followup||'Que tipo de peça você procura?','semantic_clarify',previous,[],[],diag);
  const signature=JSON.stringify(values),oldSignature=JSON.stringify(previous?.semanticScope??null);
  const same=plan.transition!=='new'&&signature===oldSignature;
  const oldShown=same?ids(previous?.search?.shown):[],oldChoices=same?ids(previous?.search?.choices):[];
  const exclude=same?ids(previous?.search?.exclude):[];
  if(plan.transition==='continue'&&previous?.mode==='focus'&&by.has(previous.productId))exclude.push(previous.productId);
  const eligible=products.map(scoped).filter(p=>(!values.kind||kindOf(p)===values.kind)&&matchesOccasion(p,occasionValue(values.occasion))&&!exclude.includes(p.id)&&stockFor(p,values.color,values.size)>0&&values.terms.every(t=>norm(`${p.name} ${p.category} ${p.fabric??''} ${(p.search_aliases??[]).join(' ')} ${JSON.stringify(p.catalog_attributes??{})}`).includes(norm(t)))).sort((a,b)=>styleRank(b,values,consult).score-styleRank(a,values,consult).score||a.id.localeCompare(b.id));
  const candidates=plan.page==='repeat'&&oldChoices.length?eligible.filter(p=>oldChoices.includes(p.id)):plan.page==='next'?eligible.filter(p=>!oldShown.includes(p.id)):eligible;
  state={...state,productId:null,mode:'browse',search:{...values,exclude,shown:oldShown,choices:[]}};
  const scope=`${values.kind?({body:'bodies',macacão:'macacões'} as any)[values.kind]??values.kind+'s':'peças'}${values.occasion?' de festa':''}${values.color?' em '+values.color:''}${values.size?' no '+values.size:''}`;
  if(!eligible.length){const empty=response(`No momento, não temos ${scope}${values.terms.length?' com '+values.terms.join(', '):''}. ${plan.followup||'Quer que eu veja outras opções pra você?'}`,'alternatives_none',state,[],[],diag);empty.catalogSearchEvidence={...values,checkedProducts:products.length,matchingCount:0};return empty;}
  const question=consultationQuestion(values,consult,plan,previous);
  if(question&&!input.requireFactualAnswer){state.consultation.awaiting=question.field;return response(question.text,'consultation_question',state,[],[],diag);}
  if(!candidates.length)return response('Por enquanto, são esses os modelos. Quer rever algum ou procurar outro estilo?','alternatives_exhausted',state,[],[],diag);
  const shown:Product[]=[],photos:any[]=[];
  for(const p of candidates.slice(0,12)){
    if(shown.length>=pageSize||photos.length>=pageSize)break;
    if(plan.photos==='hide'){shown.push(p);continue;}
    const fs=await productPhotos(p,svc,values.color,values.size,false,pageSize-photos.length);
    if(fs.length){photos.push(...fs.map(f=>({...f,recommendation:styleRank(f.corFoto?{...p,variations:p.variations.filter(v=>colorKey(v.color)===colorKey(f.corFoto))}:p,values,consult).reason})));shown.push(p);}
  }
  state.search.choices=shown.map(p=>p.id);state.search.shown=[...new Set([...oldShown,...state.search.choices])];
  const remaining=eligible.filter(p=>!state.search.shown.includes(p.id)).length;
  let reply=shown.length?galleryFollowup(remaining,plan.followup,new Set(shown.map(p=>p.id)).size):values.color?`Tenho modelos em ${values.color}${values.size?' no '+values.size:''}, mas as fotos nessa cor ainda não estão aqui. Quer que a equipe confira as fotos pra você?`:'As fotos desses modelos ainda não estão aqui. Quer que a equipe confira pra você?';
  if(photos.some(f=>f.vista==='legacy'))reply='Essas fotos mostram os modelos. Quando escolher uma cor, posso pedir à equipe uma foto dela. '+reply;
  if(plan.photos==='hide')reply=shown.map((p,i)=>{const facts=availability(p,values.color,values.size);return `Opção ${i+1} · ${kindOf(p)}\n${facts.tamanhosTexto}\n${facts.precoTexto}`;}).join('\n\n')+(plan.followup?'\n'+plan.followup:'');
  return response(reply,shown.length?'show_alternatives':'alternatives_photos_unavailable',state,shown,photos,{...diag,matchingCount:eligible.length,photoCount:photos.length,remainingCount:eligible.filter(p=>!state.search.shown.includes(p.id)).length});

  function response(reply:string,decision:string,context:any,ps:Product[]=[],photos:any[]=[],diagnostic:any={},handoff:string|null=null){
    const c=context?.color??null,s=context?.size??null;
    const optionIds=[...new Set(photos.map(f=>f.id))];
    const fotos=photos.map(f=>({...f,caption:`Opção ${optionIds.indexOf(f.id)+1} · ${f.nome}${f.corFoto?' · '+f.corFoto:''}`}));
    const selectable=context?.mode==='browse'&&decision==='show_alternatives'?ps.map(p=>p.id):[];
    const mensagens=photoMessages(fotos,selectable);
    if(fotos.length&&decision==='show_alternatives'&&context?.consultation?.event)mensagens.unshift({tipo:'texto',texto:'Separei estes modelos para você olhar. Me conta de qual gostou mais.'} as any);
    if(input.requireFactualAnswer&&!fotos.length&&ps.length&&!/R\$|Preço:/i.test(reply)&&!handoff){
      const cards=ps.slice(0,pageSize).map(p=>{const a=availability(p,c,s);return `${kindOf(p)}\n${a.tamanhosTexto}\n${a.precoTexto}`;});
      reply=cards.join('\n\n')+'\n'+reply;
    }
    mensagens.push({tipo:'texto',texto:reply.trim()} as any);
    return {ok:true,versaoLogica:VERSION,revisaoLogica:REVISION,respostaProposta:reply,contextoProduto:context,interpretacao:{cor:c,tamanho:s,termos:[]},fotos,mensagens,opcoesSelecionaveis:selectable,candidatosConfirmaveis:[],produtos:ps.map(p=>({id:p.id,nome:kindOf(p),ref:p.sku,preco:availability(p,c,s).preco,estoqueNaCombinacaoPedida:stockFor(p,c,s),estoqueTotal:stockFor(p,null,null)})),alternativas:[],comparacaoVisual:[],analiseImagem:null,handoff,auditoria:{passed:diagnostic.interpreter==='language_model',mode:'semantic_intent_catalog_facts',corrections:[]},diagnostico:{decision,focusSku:null,imageMethod:null,compared:0,eligiblePhotos:0,...diagnostic},aviso:'Simulação: nenhuma mensagem foi enviada para a Meta.'};
  }
}

