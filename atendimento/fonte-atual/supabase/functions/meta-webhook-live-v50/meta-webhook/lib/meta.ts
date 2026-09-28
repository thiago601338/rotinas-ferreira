import {whatsappRequest,whatsappDownloadRequest} from './whatsapp-provider.ts';
import {audioFormat,MAX_AUDIO_BYTES} from './audio.ts';
import {deliveryStillAllowed} from './human-wait.ts';
import {eventTime} from './coexistence.ts';
import { Buffer } from "node:buffer";
import {createHash} from "node:crypto";
import { env,type ChannelName } from "./env.ts";
import { boundedBytes } from "../../ai-test/services.ts";
import { messageRequest } from "./outbound.ts";
import { jpegForMeta } from "./image-conversion.ts";
import {instagramStoryReference,type StoryReference} from "./references.ts";
import { uploadInboxMedia,selectRows,rpc } from "./supabase.ts";
export function graph(p:string){return `https://graph.facebook.com/${env.metaGraphVersion}/${p}`;}
function token(c:ChannelName){return c==='whatsapp'?(env.whatsappProvider==='360dialog'?env.whatsapp360ApiKey:env.whatsappProvider==='meta'?env.whatsappToken:''):c==='instagram'?env.instagramToken:env.messengerToken;}
export function isWithinServiceWindow(t:string|Date|null):boolean{if(!t)return false;const at=new Date(t).getTime(),age=Date.now()-at;return Number.isFinite(at)&&age>=-60000&&age<24*3600000;}
export function channelReady(channel:string,accountId?:string):boolean{
 if(!['whatsapp','instagram','messenger'].includes(channel))return false;
 if(channel==='whatsapp'&&env.whatsappProvider==='360dialog'&&(!env.whatsappCoexistenceEnabled||env.whatsapp360WebhookSecret.length<32))return false;
 const account=channel==='whatsapp'?env.whatsappPhoneNumberId:channel==='instagram'?env.instagramAccountId:env.messengerPageId;
 return Boolean(account&&token(channel as ChannelName)&&(!accountId||accountId===account));
}
async function post(url:string,t:string,body:unknown,authHeaders:Record<string,string>={Authorization:`Bearer ${t}`}){
 try{
  const form=body instanceof FormData;
  const r=await fetch(url,{method:'POST',headers:{...authHeaders,...(form?{}:{'Content-Type':'application/json'})},body:form?body:JSON.stringify(body),signal:AbortSignal.timeout(15000),redirect:'error'});
  const data=JSON.parse(new TextDecoder().decode(await boundedBytes(r,100000)));
  if(!r.ok)return {sent:false,status:r.status,error:'meta_'+(data?.error?.code??r.status)};
  const id=data?.messages?.[0]?.id??data?.message_id??data?.id;
  if(!id)return {sent:false,error:'meta_missing_message_id'};
  return {sent:true,externalMessageId:String(id)};
 }catch{return {sent:false,error:'meta_delivery_unknown'};}
 // Unknown outcomes are never retried automatically: that can duplicate customer messages.
}
export async function sendPart(i:{channel:ChannelName;recipientId:string;part:any;lastInboundAt:string|null;conversationId:string;turnId:string;index:number;lastInboundId?:string}){
 if(!env.sendingEnabled)return {sent:false,skipped:'sending_disabled'};
 if(!channelReady(i.channel))return {sent:false,skipped:'channel_not_configured'};
 if(!isWithinServiceWindow(i.lastInboundAt))return {sent:false,skipped:'outside_window'};
 let content:any={text:i.part.texto};
 if(i.part.tipo==='imagem'){
  const bytes=await jpegForMeta(i.part.imagem);
  if(i.channel==='whatsapp'){
   const form=new FormData();form.append('messaging_product','whatsapp');form.append('type','image/jpeg');form.append('file',new Blob([bytes],{type:'image/jpeg'}),'peca.jpg');
   const upload=whatsappRequest(env,'media');
   const media=await post(upload.url,upload.token,form,upload.headers);
   if(!media.sent)return media;content={mediaId:media.externalMessageId};
  }else{
   const path=`outbound/catalog/${createHash("sha256").update(bytes).digest("hex")}.jpg`;
   await uploadInboxMedia(path,bytes.buffer as ArrayBuffer,'image/jpeg');
   const key=env.supabaseSecretKey,headers={apikey:key,...(key.startsWith('eyJ')?{Authorization:`Bearer ${key}`}:{})};
   const r=await fetch(env.supabaseUrl+'/storage/v1/object/sign/ai-inbox-media/'+path,{method:'POST',headers:{...headers,'Content-Type':'application/json'},body:JSON.stringify({expiresIn:3600}),signal:AbortSignal.timeout(12000)});
   if(!r.ok)return {sent:false,error:'image_link_failed'};
   const data=await r.json(),link=data.signedURL??data.signedUrl;
   if(typeof link!=='string'||!link.startsWith('/object/sign/ai-inbox-media/'))return {sent:false,error:'image_link_invalid'};
   content={mediaUrl:env.supabaseUrl+'/storage/v1'+link};
  }
 }
 const request=messageRequest(env,i.channel,i.recipientId,content);
 if(i.lastInboundId&&!await deliveryStillAllowed(i.conversationId,i.lastInboundId,i.turnId))return {sent:false,skipped:'new_message_or_human_response'};
 // A vendedora may take over while image conversion or upload is in flight.
 if(i.part.tipo==='imagem'){const rows=await selectRows('ai_conversations',`select=status&id=eq.${i.conversationId}`);if(rows[0]?.status!=='open')return {sent:false,skipped:'human_takeover_or_closed'};}
 if(i.lastInboundId&&!await rpc('ai_begin_send',{p_conversation:i.conversationId,p_last_inbound:i.lastInboundId,p_owner:i.turnId,p_part:i.index}))return {sent:false,skipped:'new_message_or_human_response'};
 return post(request.url,request.token,request.body,request.headers);
}
export async function sendText(i:any){return sendPart({...i,part:{tipo:'texto',texto:i.text},turnId:crypto.randomUUID(),index:0});}
export function whatsappTypingRequest(config:any,inboundId:string){
 if(!inboundId||inboundId.length>500)throw Error('invalid_inbound_id');
 const request=messageRequest(config,'whatsapp','0',{text:''});
 return {...request,body:{messaging_product:'whatsapp',status:'read',message_id:inboundId,typing_indicator:{type:'text'}}};
}
export async function sendTyping(i:{channel:ChannelName;inboundId:string;lastInboundAt:string|null}){
 // The connected Instagram Login flow has no verified typing endpoint in this implementation.
 // All channels still use the same five-second pacing independently of this indicator.
 if(i.channel!=='whatsapp'||!env.sendingEnabled||!channelReady(i.channel)||!isWithinServiceWindow(i.lastInboundAt))return false;
 try{
  const r=whatsappTypingRequest(env,i.inboundId);
  const response=await fetch(r.url,{method:'POST',headers:{...r.headers,'Content-Type':'application/json'},body:JSON.stringify(r.body),signal:AbortSignal.timeout(2000),redirect:'error'});
  await response.body?.cancel();return response.ok;
 }catch{return false;}
}
export async function downloadMedia(i:{channel:ChannelName;mediaId?:string|null;mediaUrl?:string|null;mediaType?:string|null}):Promise<{ok:true;bytes:ArrayBuffer;contentType:string}|{ok:false;error:string}>{
 try{
  let u=i.mediaUrl??'',auth=false;const t=token(i.channel);
  if(i.channel==='whatsapp'){
   if(!i.mediaId||!/^\d+$/.test(i.mediaId)||!t)return {ok:false,error:'media_not_configured'};
   const source=whatsappRequest(env,'metadata',i.mediaId);
   const metadata=await fetch(source.url,{headers:source.headers,signal:AbortSignal.timeout(12000),redirect:'error'});
   if(!metadata.ok)return {ok:false,error:'media_metadata_failed'};u=(await metadata.json())?.url??'';auth=true;
  }
  if(i.channel==='whatsapp'){const source=whatsappDownloadRequest(env,u);u=source.url;}
  const url=new URL(u),host=url.hostname;
  const trusted=(i.channel==='whatsapp'&&env.whatsappProvider==='360dialog'&&host==='waba-v2.360dialog.io')||['facebook.com','fbcdn.net','fbsbx.com','cdninstagram.com'].some(h=>host===h||host.endsWith('.'+h));
  if(url.protocol!=='https:'||url.username||url.password||url.port||!trusted)return {ok:false,error:'media_host_invalid'};
  const r=await fetch(u,{headers:auth?whatsappDownloadRequest(env,u).headers:{},signal:AbortSignal.timeout(12000),redirect:'error'});
  if(!r.ok)return {ok:false,error:'media_download_failed'};
  const ct=(r.headers.get('content-type')??'').split(';')[0].toLowerCase();
  if(i.mediaType==='audio'){const data=await boundedBytes(r,MAX_AUDIO_BYTES);const format=audioFormat(data,ct);return {ok:true,bytes:data.buffer as ArrayBuffer,contentType:format.mime};}
  if(!/^image\/(jpeg|png|webp|gif)$/.test(ct))return {ok:false,error:'media_type_unsupported'};
  return {ok:true,bytes:(await boundedBytes(r,10*1024*1024)).buffer as ArrayBuffer,contentType:ct};
 }catch{return {ok:false,error:'media_download_failed'};}
}
export function toDataUrl(bytes:ArrayBuffer,type:string){return `data:${type};base64,${Buffer.from(bytes).toString('base64')}`;}
export interface NormalizedMessage{channel:ChannelName;externalMessageId:string;senderId:string;threadId:string;recipientId:string;text:string|null;mediaId:string|null;mediaUrl:string|null;customerName:string|null;isEcho:boolean;timestamp:string|null;accountId?:string;replyTo?:string|null;storyReference?:StoryReference|null;supported?:boolean;mediaType?:'image'|'audio'|null;}
export function normalizeWebhook(p:any):NormalizedMessage[]{const out:NormalizedMessage[]=[],es=Array.isArray(p?.entry)?p.entry:[];for(const e of es){for(const ch of e?.changes??[]){const field=String(ch?.field??""),v=ch?.value;if(field&&field!=="messages")continue;if(!v?.messages)continue;const contacts=v.contacts??[],phone=v?.metadata?.phone_number_id??"";for(const m of v.messages){const from=String(m?.from??"");out.push({channel:"whatsapp",externalMessageId:String(m?.id??""),senderId:from,threadId:from,recipientId:from,accountId:String(phone),replyTo:m?.context?.id??null,supported:["text","image","audio","button","interactive"].includes(m?.type),text:m?.text?.body??m?.button?.text??m?.interactive?.button_reply?.title??m?.interactive?.list_reply?.title??m?.image?.caption??null,mediaId:m?.image?.id??m?.audio?.id??null,mediaType:m?.type==="audio"?"audio":m?.type==="image"?"image":null,mediaUrl:null,customerName:contacts?.[0]?.profile?.name??null,isEcho:Boolean(phone&&from===String(phone)),timestamp:eventTime(m?.timestamp)});}}const instagramChanges=p?.object==="instagram"?(e?.changes??[]).filter((ch:any)=>ch?.field==="messages").map((ch:any)=>ch.value):[];for(const ev of [...(e?.messaging??[]),...instagramChanges]){const m=ev?.message;if(!m)continue;const ig=e?.messaging_product==="instagram"||p?.object==="instagram";if(m?.is_echo){out.push({channel:ig?"instagram":"messenger",externalMessageId:String(m?.mid??""),senderId:String(ev?.sender?.id??""),threadId:String(ev?.recipient?.id??""),recipientId:String(ev?.recipient?.id??""),accountId:String(ev?.sender?.id??""),text:m?.text??null,mediaId:null,mediaUrl:null,customerName:null,isEcho:true,timestamp:ev?.timestamp?new Date(Number(ev.timestamp)).toISOString():null});continue;}const storyReference=ig?instagramStoryReference(m):null,a=(m?.attachments??[]).find((x:any)=>["image","audio"].includes(x?.type)),s=String(ev?.sender?.id??"");out.push({channel:ig?"instagram":"messenger",externalMessageId:String(m?.mid??""),senderId:s,threadId:s,recipientId:s,accountId:String(ev?.recipient?.id??e.id??""),replyTo:m?.reply_to?.mid??null,storyReference,supported:!m?.is_unsupported&&(m?.attachments??[]).filter((x:any)=>["image","audio"].includes(x?.type)).length<=1&&Boolean(m?.text||a||storyReference)&&!(m?.attachments??[]).some((x:any)=>!["image","audio","story_mention","story","ig_story"].includes(x?.type)),text:m?.text??null,mediaId:null,mediaUrl:a?.payload?.url??null,mediaType:a?.type??null,customerName:null,isEcho:false,timestamp:ev?.timestamp?new Date(Number(ev.timestamp)).toISOString():null});}}return out.filter(m=>m.externalMessageId&&m.senderId);}
export interface BusinessEcho{channel:ChannelName;externalMessageId:string;recipientId:string;text:string|null;timestamp:string|null;accountId?:string;replyTo?:string|null;supported?:boolean;messageType?:string;mediaId?:string|null;source?:'business_app'|'api_echo';}
export function normalizeBusinessEchoes(p:any):BusinessEcho[]{
 const out:BusinessEcho[]=[];
 for(const e of Array.isArray(p?.entry)?p.entry:[])for(const ch of Array.isArray(e.changes)?e.changes:[]){
  if(ch.field!=='smb_message_echoes')continue;
  const v=ch.value,account=String(v?.metadata?.phone_number_id??'');
  if(!/^\d+$/.test(account))continue;
  const list=Array.isArray(v?.message_echoes)?v.message_echoes:Array.isArray(v?.smb_message_echoes)?v.smb_message_echoes:[];
  for(const m of list){
   const id=String(m?.id??''),to=String(m?.to??''),type=String(m?.type??'unknown'),timestamp=eventTime(m?.timestamp);
   if(!id||id.length>500||!/^\d{5,20}$/.test(to)||!timestamp)continue;
   out.push({channel:'whatsapp',externalMessageId:id,recipientId:to,accountId:account,text:m?.text?.body??m?.[type]?.caption??null,timestamp,messageType:type,mediaId:m?.[type]?.id??null,source:'business_app'});
  }
 }
 return out;
}
export function collectUnhandledFields(p:any):string[]{const known=/^(messages|message_echoes|smb_message_echoes|history|smb_app_state_sync)$/i,s=new Set<string>();for(const e of p?.entry??[])for(const ch of e?.changes??[]){const f=String(ch?.field??""),v=ch?.value??{},handled=known.test(f)||Array.isArray(v.messages)||Array.isArray(v.message_echoes)||Array.isArray(v.smb_message_echoes)||Array.isArray(v.statuses);if(!handled&&f)s.add(f);}return[...s];}

