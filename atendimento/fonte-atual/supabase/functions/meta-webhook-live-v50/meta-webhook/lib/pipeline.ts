import {isStoreAddressQuestion,storeAddressReply,STORE_ADDRESS_REVISION} from './store-address.ts';
import {handleInstagramMessage} from './pipeline-instagram.ts';
import {currentBurst,freshCatalogQuestion} from './current-turn.ts';
import {transcribeAudio,AUDIO_REVISION} from './audio.ts';
import {evaluateAnswer,sensitiveQuestion,silent,greetingReply,type AnswerVerdict} from './answer-policy.ts';
import {blockForHuman,resolveHumanWait,deliveryStillAllowed} from './human-wait.ts';
import {env} from './env.ts';
import {logEvent,logError} from './logger.ts';
import {selectRows,updateRows,rpc,uploadInboxMedia} from './supabase.ts';
import {getOrCreateConversation,recordMessage,getHistory,checkGuards,isOptedOut,looksLikeOptOut,registerOptOut,openHandoff,touchConversation,finishEvent,findConversation,messageExists} from './conversation.ts';
import {downloadMedia,toDataUrl,sendPart,sendTyping,channelReady,type NormalizedMessage,type BusinessEcho} from './meta.ts';
import {runConversation} from '../../ai-test/router.ts';
import {configuration,services} from '../../ai-test/services.ts';
import {REVISION} from '../../ai-test/core.ts';
import {outboundParts,splitText,orderedDelivery,type DeliveryPacing} from './outbound.ts';
import {INTRODUCTION,INTRODUCTION_KEY,EXPERIENCE_REVISION} from '../../ai-test/customer-experience.ts';
import {STORY_REFERENCE_REVISION,referencedTurn,referenceHistory,unresolvedReference,attachReferenceContext} from './references.ts';

// Every inbound event is persisted before inference. A database lease serializes
// model + image/text batch across Edge instances, including Meta webhook retries.
export async function handleMessage(m:NormalizedMessage,recovery?:{owner:string;conversation:any;afterHumanWait?:boolean}):Promise<boolean>{
 if(m.channel==='instagram')return handleInstagramMessage(m,recovery);
 if(!env.sendingEnabled||!m.accountId||!channelReady(m.channel,m.accountId)){
  await logEvent({kind:'webhook_received',channel:m.channel,detail:{motivo:'canal desativado ou conta não configurada'}});return true;
 }
 if(await isOptedOut(m.channel,m.senderId))return true;
 const initial=recovery?.conversation??await getOrCreateConversation({channel:m.channel,externalUserId:m.senderId,externalThreadId:m.threadId,customerName:m.customerName});
 if(!recovery)await recordMessage({conversationId:initial.id,direction:'inbound',messageType:m.mediaType==='audio'?'audio':m.mediaId||m.mediaUrl||m.storyReference?'image':'text',externalMessageId:m.externalMessageId,text:m.text,occurredAt:m.timestamp??undefined,rawPayload:{...m,processingStatus:'pending'}});
 const owner=recovery?.owner??crypto.randomUUID();let lease=recovery?{status:'acquired',conversation:initial}:await rpc<any>('ai_acquire_turn',{p_conversation:initial.id,p_owner:owner});
 if(lease.status==='busy')return false;
 if(lease.status==='interrupted'){await rpc('ai_recover_followups',{});lease=await rpc<any>('ai_acquire_turn',{p_conversation:initial.id,p_owner:owner});}
 if(lease.status!=='acquired')return true;
 const c=lease.conversation;let context:any=null,commit=false,pending:any[]=[];
 try{
  pending=await selectRows('ai_messages',`select=*&conversation_id=eq.${c.id}&direction=eq.inbound&raw_payload->>processingStatus=eq.pending&order=created_at.desc&limit=100`);
  if(!pending.length)return true;
  const burst=currentBurst(pending);
  for(const old of burst.older)await updateRows('ai_messages',`id=eq.${old.id}&raw_payload->>processingStatus=eq.pending`,{raw_payload:{...old.raw_payload,processingStatus:'human_wait',needsHuman:true}});
  pending=burst.current;
  let text=pending.map(p=>p.text_content).filter(Boolean).join('\n');
  if(looksLikeOptOut(text)){await registerOptOut(m.channel,m.senderId,'pedido explícito da cliente');await openHandoff(c,'cliente pediu para não receber mensagens');await mark('done');return true;}
  const guard=await checkGuards(c);if(!guard.allowed){if(guard.handoff)await openHandoff(c,guard.reason);await mark('done');return true;}
  await mark('processing');
  const latest=pending.at(-1).raw_payload,media=pending.filter(p=>p.raw_payload?.mediaType!=='audio'&&(p.raw_payload?.mediaId||p.raw_payload?.mediaUrl));
  let visual=referencedTurn(pending);
  // An explicit reference to the recent Story may arrive in a later message burst.
  if(!visual.reference&&/\b(story|storys|stories)\b/i.test(text)){
   const recent=await selectRows('ai_messages',`select=*&conversation_id=eq.${c.id}&direction=eq.inbound&raw_payload->>storyReference=not.is.null&created_at=gte.${encodeURIComponent(new Date(Date.parse(pending.at(-1).created_at)-30*60000).toISOString())}&order=created_at.desc&limit=1`);
   if(recent[0])visual=referencedTurn(recent);
  }
  const reference=visual.reference,story=reference?.story??null;
  const freshCatalog=!visual.reference&&freshCatalogQuestion(text);
  let referenceAnchor:any=freshCatalog?null:c.metadata?.aiContext?.referenceContext??null;
  if(story||visual.ambiguous){
   referenceAnchor={kind:'story',id:story?.id??null,sourceMessageId:reference?.row.raw_payload?.externalMessageId??latest.externalMessageId,since:reference?.row.created_at??pending[0].created_at,question:text};
   context=unresolvedReference(referenceAnchor);commit=true;
  }
  let partOffset=0;
  const lastOutbound=await selectRows('ai_messages',`select=created_at&conversation_id=eq.${c.id}&direction=eq.outbound&raw_payload->>enviado=eq.true&order=created_at.desc&limit=1`);
  const previousAcceptedAt=lastOutbound[0]?Date.parse(lastOutbound[0].created_at):NaN;
  const pacing:DeliveryPacing={...(Number.isFinite(previousAcceptedAt)?{previousAcceptedAt}:{}),onPause:async()=>{if(await deliveryStillAllowed(c.id,pending.at(-1).id,owner))return sendTyping({channel:m.channel,inboundId:latest.externalMessageId,lastInboundAt:latest.timestamp});}};
  const audios=pending.filter(p=>p.raw_payload?.mediaType==='audio');
  if(audios.length){
   if(!env.audioEnabled||audios.length>3){await notifyHandoff('Recebi seus áudios. A equipe vai ajudar com esse conteúdo.','áudio desativado ou mais de três áudios no mesmo turno');return true;}
   for(const row of audios){
    try{
     if(row.raw_payload?.transcription?.status==='done'&&row.text_content)continue;
     const downloaded=await downloadMedia(row.raw_payload);
     if(!downloaded.ok)throw Error(downloaded.error);
     const transcript=await transcribeAudio(downloaded.bytes,downloaded.contentType,env.openaiApiKey,env.audioModel);
     row.raw_payload={...row.raw_payload,transcription:{status:transcript.needsClarification?'unclear':'done',model:transcript.model,revision:AUDIO_REVISION,reason:transcript.reason,bytes:transcript.bytes,at:new Date().toISOString()}};
     row.text_content=transcript.needsClarification?null:transcript.text;
     await updateRows('ai_messages',`id=eq.${row.id}`,{message_type:'audio',text_content:row.text_content,raw_payload:row.raw_payload});
     if(transcript.needsClarification){
      return await hold(silent('unclear',transcript.reason==='audio_too_long'?'Áudio longo demais para compreensão completa.':'Áudio não compreendido com segurança.'));
     }
    }catch{
     row.raw_payload={...row.raw_payload,transcription:{status:'failed',revision:AUDIO_REVISION,at:new Date().toISOString()}};
     await updateRows('ai_messages',`id=eq.${row.id}`,{raw_payload:row.raw_payload});
     return await hold(silent('unclear','Não foi possível transcrever o áudio.'));
    }
   }
   text=pending.map(p=>p.text_content).filter(Boolean).join('\n');
   if(looksLikeOptOut(text)){await registerOptOut(m.channel,m.senderId,'pedido explícito da cliente em áudio');await openHandoff(c,'cliente pediu para não receber mensagens');await mark('done');return true;}
   if(text.length>2000)return await hold(silent('unclear','Pedido extenso demais para compreensão completa.'));
  }
  if(text.length>2000)return await hold(silent('unclear','Pedido extenso demais para compreensão completa.'));
  const addressOnly=isStoreAddressQuestion(text)&&!visual.reference&&!visual.ambiguous&&media.length===0&&pending.every(p=>p.raw_payload?.supported!==false&&!p.raw_payload?.storyReference&&(p.raw_payload?.mediaType!=='audio'||p.raw_payload?.transcription?.status==='done'));
  const sensitive=addressOnly?null:sensitiveQuestion(text);if(sensitive)return await hold(sensitive);
  if(addressOnly){
   const rows=await selectRows('ai_settings','select=address:value->public_store_address&key=eq.assistant&limit=1');
   const reply=storeAddressReply(rows[0]?.address);
   if(!reply)return await hold(silent('missing_fact','Endereço público da loja não confirmado no cadastro.'));
   const last=pending.at(-1);
   last.raw_payload={...last.raw_payload,answerDecision:{allowed:true,category:'store_info',reason:'Endereço público confirmado pela loja.',revision:STORE_ADDRESS_REVISION}};
   await updateRows('ai_messages',`id=eq.${last.id}&raw_payload->>processingStatus=eq.processing`,{raw_payload:last.raw_payload});
   const delivered=await deliver([{tipo:'texto',texto:reply,purpose:'public_store_address'}],c.metadata?.aiContext??null);
   if(!delivered.complete){
    if(cancelled(delivered.error)){commit=false;await mark('superseded');return true;}
    return await hold(silent('technical','Falha ao enviar endereço público da loja.'));
   }
   // No conversation reopening or replacement of the existing product context.
   commit=false;await mark('done');await resolveHumanWait(c.id,last.id);await touchConversation(c.id);
   await finishEvent(m.channel,m.externalMessageId,'done');return true;
  }
  let image:string|null=null;
  if(visual.ambiguous)return await askReference('Você respondeu a mais de uma imagem. Pode me mandar a foto da peça que quer conferir primeiro?','multiple_references');
  if(pending.some(p=>p.raw_payload?.supported===false)||media.length>1){
   if(story)return await askReference('Não consegui abrir a imagem desse story. Pode me mandar um print da peça?','story_unsupported');
   await notifyHandoff('Recebi sua mensagem. A equipe vai ajudar com esse conteúdo.','conteúdo não suportado ou várias imagens no mesmo pedido');return true;
  }
  if(story&&!story.url)return await askReference('Não consegui abrir a imagem desse story. Pode me mandar um print da peça?','story_url_missing');
  if(story&&media.length)return await askReference('Pode me mandar só a foto da peça que você quer conferir? Vieram duas imagens diferentes.','story_and_attachment');
  const mediaRow=story?reference!.row:media[0];
  if(mediaRow){
   const row=mediaRow,source=story?{...row.raw_payload,mediaType:'image',mediaId:null,mediaUrl:story.url}:row.raw_payload,download=await downloadMedia(source);
   if(!download.ok){
    if(story||referenceAnchor?.awaitingImage)return await askReference('Não consegui abrir a imagem desse story. Pode me mandar um print da peça?','story_media_unavailable');
    await notifyHandoff('Não consegui abrir essa imagem. Pode reenviar a foto?','falha ao baixar a imagem recebida');return true;
   }
   image=toDataUrl(download.bytes,download.contentType);
   const path=`${m.channel}/${c.id}/${row.id}.${download.contentType.split('/')[1]}`;
   await uploadInboxMedia(path,download.bytes,download.contentType);
   await updateRows('ai_messages',`id=eq.${row.id}`,{media_path:path});
  }
  const all=await getHistory(c.id,100),pendingIds=new Set(pending.map(p=>p.id));
  let previous=story||freshCatalog?null:c.metadata?.aiContext??null;
  if(reference?.replyTo&&!story){
   const refs=await selectRows('ai_messages',`select=raw_payload&conversation_id=eq.${c.id}&direction=eq.outbound&external_message_id=eq.${encodeURIComponent(reference.replyTo)}&limit=1`);
   const ref=refs[0]?.raw_payload;
   if(ref?.enviado&&ref.productId){
    // The quoted, actually sent photo identifies the item. Natural text remains
    // a question, so 'quanto custa essa?' is still interpreted by the model.
    previous={productId:ref.productId,mode:'focus',color:ref.photoColor??ref.context?.color??null,size:ref.context?.size??null,quotedPhotoColor:ref.photoColor??null};
    referenceAnchor=null;
   }else if(!image){
    referenceAnchor={kind:'message',sourceMessageId:reference.replyTo,since:reference.row.created_at,question:text};
    return await askReference('Não consegui identificar a peça dessa mensagem. Pode me mandar a foto dela?','quoted_product_unknown');
   }
  }
  const history=referenceHistory(freshCatalog?all.filter((p:any)=>Date.parse(p.created_at)>=Date.parse(pending[0].created_at)):all,referenceAnchor).filter((p:any)=>!pendingIds.has(p.id)&&(p.direction==='inbound'||p.raw_payload?.enviado===true||p.raw_payload?.coexistence===true)).filter(p=>p.text_content).map(p=>({role:p.direction==='inbound'?'user':'assistant',content:p.text_content}));
  const currentText=image&&referenceAnchor?.awaitingImage&&!text.trim()?referenceAnchor.question:text;
  const config=configuration(),svc=services(config);
  const greeting=!(recovery?.afterHumanWait??!!recovery)&&!image&&!visual.reference&&pending.every(p=>!p.raw_payload?.mediaId&&!p.raw_payload?.mediaUrl&&!p.raw_payload?.storyReference&&p.raw_payload?.supported!==false) ? greetingReply(currentText) : null;
  const result=greeting ? {ok:true,revisaoLogica:REVISION,respostaProposta:greeting,mensagens:[{tipo:'texto',texto:greeting}],contextoProduto:previous,produtos:[],fotos:[],auditoria:{passed:true},diagnostico:{decision:'simple_greeting'}} : await runConversation({text:currentText,image,history,context:previous,conversationId:c.id,requireFactualAnswer:true,maxPhotos:3},svc);
  result.contextoProduto=attachReferenceContext(result,referenceAnchor);
  if(result.revisaoLogica!==REVISION)throw Error('engine_revision_mismatch');
  if(result.analiseImagem&&mediaRow)await updateRows('ai_messages',`id=eq.${mediaRow.id}`,{image_analysis:result.analiseImagem});
  const authorization=await evaluateAnswer({text:currentText,history,result,products:await svc.products(),afterHumanWait:recovery?.afterHumanWait??!!recovery},config);
  const lastPending=pending.at(-1);
  lastPending.raw_payload={...lastPending.raw_payload,answerDecision:{allowed:authorization.allowed,category:authorization.category,reason:authorization.reason,engine:result.diagnostico?.decision,interpreter:result.diagnostico?.interpreter,failure:result.diagnostico?.failure,revision:authorization.revision}};
  await updateRows('ai_messages',`id=eq.${lastPending.id}&raw_payload->>processingStatus=eq.processing`,{raw_payload:lastPending.raw_payload});
  if(!authorization.allowed)return await hold(authorization);
  // No greeting, typing/read indication, clarification or other customer-facing
  // action happens before the complete factual answer is authorized.
  const introductions=await selectRows('ai_messages',`select=id&conversation_id=eq.${c.id}&direction=eq.outbound&raw_payload->>introduction=eq.${INTRODUCTION_KEY}&raw_payload->>enviado=eq.true&limit=1`);
  if(!introductions.length){
   const introduction=await deliver([{tipo:'texto',texto:INTRODUCTION,purpose:'introduction'}],null,false);
   if(!introduction.complete){if(cancelled(introduction.error)){await mark('superseded');return true;}return await hold(silent('technical','Falha ao iniciar atendimento.'));}
  }
  const parts=outboundParts(result).flatMap(p=>p.tipo==='texto'?splitText(p.texto!).map(texto=>({...p,texto})):p);
  const delivery=await deliver(parts,result.contextoProduto);
  if(!delivery.complete){if(cancelled(delivery.error)){await mark('superseded');return true;}if(await retryTechnical(delivery.error??'send_failed'))return true;await blockForHuman(c.id,pending.at(-1).id,silent('unclear','Envio interrompido: conferir a conversa antes de responder.'));await openHandoff(c,'envio incompleto: '+delivery.error);await mark('failed');return true;}
  context=result.contextoProduto;commit=true;await mark('done');await resolveHumanWait(c.id,pending.at(-1).id);await touchConversation(c.id);
  await finishEvent(m.channel,m.externalMessageId,'done');return true;

  async function askReference(reply:string,reason:string){
   context=unresolvedReference(referenceAnchor);commit=true;
   return await hold(silent('unclear','A referência da peça precisa ser conferida pela equipe: '+reason));
  }
  async function deliver(parts:any[],nextContext:any,final=true){
   const offset=partOffset;partOffset+=parts.length;
   return orderedDelivery(parts,(part,index)=>sendPart({channel:m.channel,recipientId:m.senderId,part,lastInboundAt:latest.timestamp,conversationId:c.id,turnId:owner,index:offset+index,lastInboundId:pending.at(-1).id}),async(part:any,index,sent)=>{
    const stored=await recordMessage({conversationId:c.id,direction:'outbound',messageType:part.tipo==='imagem'?'image':'text',externalMessageId:sent.externalMessageId??null,text:part.texto??part.legenda??null,rawPayload:{enviado:sent.sent,erro:sent.error??sent.skipped??null,turnId:owner,part:offset+index,turn_complete:final&&sent.sent&&index===parts.length-1,productId:part.produtoId??null,photoColor:part.corFoto??null,purpose:part.purpose??null,introduction:part.purpose==='introduction'?INTRODUCTION_KEY:null,context:{color:nextContext?.color??null,size:nextContext?.size??null},revision:REVISION,experienceRevision:EXPERIENCE_REVISION,storyReferenceRevision:STORY_REFERENCE_REVISION,referenceKind:referenceAnchor?.kind??null}});
    if(!stored)throw Error('outbound_record_failed');
    if(sent.sent||sent.skipped||!['meta_delivery_unknown','meta_missing_message_id'].includes(sent.error))await rpc('ai_end_send',{p_conversation:c.id,p_owner:owner,p_part:offset+index});
   },()=>deliveryStillAllowed(c.id,pending.at(-1).id,owner),pacing);
  }
  async function retryTechnical(reason:string){return await rpc<boolean>('ai_retry_turn',{p_conversation:c.id,p_last_inbound:pending.at(-1).id,p_owner:owner,p_reason:reason});}
  function cancelled(error:string){return ['human_takeover_or_closed','new_message_or_human_response'].includes(error);}
  async function hold(verdict:AnswerVerdict){if(verdict.category==='technical'&&await retryTechnical(verdict.reason))return true;await blockForHuman(c.id,pending.at(-1).id,verdict);await mark('human_wait');await openHandoff(c,verdict.reason);return true;}
  async function notifyHandoff(reply:string,reason:string){return await hold(silent('unclear',reason));}
 }catch(e){
  await logError('error',e,{fase:'channel_turn',conversationId:c.id,revision:REVISION});
  if(pending.length&&await rpc<boolean>('ai_retry_turn',{p_conversation:c.id,p_last_inbound:pending.at(-1).id,p_owner:owner,p_reason:'Falha temporária no processamento.'}))return true;
  if(pending.length){await mark('failed');await blockForHuman(c.id,pending.at(-1).id,silent('unclear','Falha no atendimento automático; conferir mensagens enviadas.'));await openHandoff(c,'falha no atendimento automático; conferir mensagens enviadas');}
  await finishEvent(m.channel,m.externalMessageId,'failed','channel_turn_failed');return pending.length>0;
 }finally{await rpc('ai_release_turn',{p_conversation:c.id,p_owner:owner,p_context:context,p_commit:commit});}
 async function mark(status:string){for(const p of pending){p.raw_payload={...p.raw_payload,processingStatus:status};await updateRows('ai_messages',`id=eq.${p.id}&raw_payload->>processingStatus=not.eq.human_answered`,{raw_payload:p.raw_payload});}}
}
export async function handleBusinessEcho(e:BusinessEcho):Promise<boolean>{
 try{
  if(!e.accountId||!channelReady(e.channel,e.accountId))return true;
  if(await messageExists(e.externalMessageId))return true;
  let c=await findConversation(e.channel,e.recipientId);
  if(!c)c=await getOrCreateConversation({channel:e.channel,externalUserId:e.recipientId,externalThreadId:e.recipientId,initialStatus:'human'});
  // SMB echoes are explicitly messages from the phone: pause immediately, even during inference.
  if(e.source!=='business_app'&&c.metadata?.aiProcessing){await new Promise(r=>setTimeout(r,1500));if(await messageExists(e.externalMessageId))return true;}
  const lastInbound=(await selectRows('ai_messages',`select=created_at&conversation_id=eq.${c.id}&direction=eq.inbound&order=created_at.desc&limit=1`))[0];
  const stale=!!e.timestamp&&!!lastInbound?.created_at&&Date.parse(e.timestamp)<Date.parse(lastInbound.created_at);
  if(!stale&&c.status!=='human')await openHandoff(c,'uma pessoa da equipe respondeu pelo canal da loja');
  else if(!stale&&e.source==='business_app')await openHandoff(c,'atendimento iniciado pela equipe no WhatsApp Business');
  await recordMessage({conversationId:c.id,direction:'outbound',messageType:e.messageType??'text',externalMessageId:e.externalMessageId,text:e.text,occurredAt:e.timestamp??undefined,rawPayload:{origem:e.source==='business_app'?'whatsapp_business_app':'conta_da_loja',coexistence:e.source==='business_app',enviado:true,accountId:e.accountId,mediaId:e.mediaId??null}});
  await touchConversation(c.id);return true;
 }catch(x){await logError('error',x,{fase:'handleBusinessEcho'});return false;}
}

