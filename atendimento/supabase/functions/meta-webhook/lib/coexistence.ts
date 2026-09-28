import {env} from './env.ts';
import {selectRows,insertRow,updateRows,insertArchiveRows} from './supabase.ts';
import {findConversation} from './conversation.ts';
import {COEXISTENCE_REVISION} from './whatsapp-provider.ts';
import {logEvent} from './logger.ts';

const arr=(x:any):any[]=>Array.isArray(x)?x:[];
const string=(v:any,max=500):string|null=>typeof v==='string'&&v.length>0&&v.length<=max?v:null;
export function eventTime(value:any,now=Date.now()):string|null{
 if(value===null||value===undefined||value==='')return null;
 const n=Number(value),ms=n<1e12?n*1000:n;
 if(!Number.isFinite(ms)||ms<Date.UTC(2000,0,1)||ms>now+60000)return null;
 return new Date(ms).toISOString();
}
export type ArchivedMessage={accountId:string;threadId:string;externalMessageId:string;direction:'inbound'|'outbound';text:string|null;messageType:string;timestamp:string;mediaId:string|null;phase:number|null;chunk:number|null;progress:number|null};
export function normalizeHistory(p:any,accountId:string):ArchivedMessage[]{
 const out:ArchivedMessage[]=[];
 for(const e of arr(p?.entry))for(const change of arr(e.changes)){
  if(change.field!=='history'||String(change.value?.metadata?.phone_number_id??'')!==accountId)continue;
  const batches=[...arr(change.value.history),{threads:arr(change.value.messages).map((m:any)=>({id:m.to??m.from,messages:[m]}))}];
  for(const batch of batches)for(const thread of arr(batch.threads))for(const m of arr(thread.messages)){
   if(out.length>=5000)throw Error('history_batch_too_large');
   const id=string(m.id),tid=String(thread.id??''),from=String(m.from??''),to=String(m.to??''),timestamp=eventTime(m.timestamp);
   if(!id||!/^\d{5,20}$/.test(tid)||!timestamp)continue;
   // Direction follows the customer thread and explicit recipient, not a comparison of phone vs phone-ID.
   const direction=to===tid?'outbound':from===tid?'inbound':null;
   if(!direction)continue;
   const type=string(m.type,40)??'unknown';
   out.push({accountId,threadId:tid,externalMessageId:id,direction,timestamp,messageType:type,
    text:type==='text'?string(m.text?.body,20000):string(m[type]?.caption,20000),mediaId:string(m[type]?.id),
    phase:Number.isFinite(batch.metadata?.phase)?batch.metadata.phase:null,chunk:Number.isFinite(batch.metadata?.chunk_order)?batch.metadata.chunk_order:null,progress:Number.isFinite(batch.metadata?.progress)?batch.metadata.progress:null});
  }
 }
 return out;
}
export async function importHistory(p:any):Promise<number>{
 if(!env.whatsappCoexistenceEnabled||!env.whatsappPhoneNumberId)return 0;
 const messages=normalizeHistory(p,env.whatsappPhoneNumberId),threads=new Map<string,ArchivedMessage[]>();
 let imported=0;
 for(const m of messages.sort((a,b)=>a.timestamp.localeCompare(b.timestamp))){const group=threads.get(m.threadId)??[];group.push(m);threads.set(m.threadId,group);}
 for(const [threadId,history] of threads){
  let c=await findConversation('whatsapp',threadId);
  if(!c){
   c=await insertRow('ai_conversations',{channel:'whatsapp',external_user_id:threadId,external_thread_id:threadId,status:'open',created_at:history[0].timestamp,last_message_at:history.at(-1)!.timestamp,metadata:{historyImported:true}}, {onConflict:'channel,external_user_id,external_thread_id',ignoreDuplicates:true});
   if(!c)c=await findConversation('whatsapp',threadId);
  }
  if(!c)throw Error('history_conversation_unavailable');
  // Batch requests keep the 180-day import from making one network round trip per message.
  for(let offset=0;offset<history.length;offset+=100){
   const batch=history.slice(offset,offset+100),ids=batch.map(m=>JSON.stringify(m.externalMessageId)).join(',');
   const query=new URLSearchParams({select:'id,external_message_id,raw_payload',conversation_id:'eq.'+c.id,external_message_id:'in.('+ids+')'});
   const existing=await selectRows('ai_messages',query.toString()),byId=new Map(existing.map(m=>[m.external_message_id,m]));
   const rows=[];
   for(const m of batch){
    const prior=byId.get(m.externalMessageId);
    if(prior){
     // Media details can arrive after the placeholder; never overwrite a live message.
     if(prior.raw_payload?.importedHistory&&m.mediaId&&!prior.raw_payload.mediaId)await updateRows('ai_messages',`id=eq.${prior.id}`,{message_type:m.messageType,...(m.text?{text_content:m.text}:{}),raw_payload:{...prior.raw_payload,mediaId:m.mediaId}});
     continue;
    }
    rows.push({conversation_id:c.id,direction:m.direction,message_type:m.messageType,external_message_id:m.externalMessageId,text_content:m.text,created_at:m.timestamp,raw_payload:{importedHistory:true,processingStatus:'imported',coexistence:true,enviado:m.direction==='outbound',mediaId:m.mediaId,accountId:m.accountId,phase:m.phase,chunk:m.chunk,progress:m.progress,revision:COEXISTENCE_REVISION}});
   }
   imported+=await insertArchiveRows(rows);
  }
 }
 if(messages.length)await logEvent({kind:'webhook_received',channel:'whatsapp',detail:{stage:'history_imported',received:messages.length,imported,revision:COEXISTENCE_REVISION}});
 // No inference, sends, handoffs, current context changes, or service-window updates here.
 return imported;
}
export async function syncKnownContacts(p:any):Promise<number>{
 if(!env.whatsappCoexistenceEnabled)return 0;
 let updated=0;
 for(const e of arr(p?.entry))for(const change of arr(e.changes)){
  if(change.field!=='smb_app_state_sync'||String(change.value?.metadata?.phone_number_id??'')!==env.whatsappPhoneNumberId)continue;
  for(const item of arr(change.value.state_sync)){
   const phone=String(item.contact?.phone_number??''),name=string(item.contact?.full_name,200),stamp=eventTime(item.metadata?.timestamp);
   if(item.type!=='contact'||item.action!=='add'||!/^\d{5,20}$/.test(phone)||!name||!stamp)continue;
   // Fill only a missing display name; out-of-order sync cannot replace existing names or status.
   const rows=await updateRows('ai_conversations',`channel=eq.whatsapp&external_user_id=eq.${phone}&customer_name=is.null`,{customer_name:name});updated+=rows.length;
  }
 }
 return updated;
}
