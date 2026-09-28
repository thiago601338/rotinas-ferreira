import {createHash,timingSafeEqual} from 'node:crypto';
import {Buffer} from 'node:buffer';
import {verify360Webhook,canonical360Webhook,COEXISTENCE_REVISION} from './lib/whatsapp-provider.ts';
import {importHistory,syncKnownContacts} from './lib/coexistence.ts';
import {env} from './lib/env.ts';
import {verifyChannelSignature,verifyHandshake,webhookChannel} from './lib/signature.ts';
import {normalizeWebhook,normalizeBusinessEchoes,channelReady} from './lib/meta.ts';
import {handleMessage,handleBusinessEcho} from './lib/pipeline.ts';
import {logError,logEvent} from './lib/logger.ts';
import {configuration,services,boundedBytes} from '../ai-test/services.ts';
import {REVISION} from '../ai-test/core.ts';
import {jpegForMeta} from './lib/image-conversion.ts';
declare const EdgeRuntime:{waitUntil(p:Promise<unknown>):void}|undefined;
const json=(data:any,status=200)=>Response.json(data,{status,headers:{'Cache-Control':'no-store'}});
export const WEBHOOK_REVISION='v6.2-meta-audio-silent-20260910-r1';
let lastRejectedAudit=0;
async function auditWebhook(kind:'webhook_received'|'webhook_rejected',detail:Record<string,unknown>){
 if(!env.supabaseUrl||!env.supabaseSecretKey)return;
 await logEvent({kind,level:kind==='webhook_rejected'?'warn':'info',detail:{...detail,revision:REVISION,webhookRevision:WEBHOOK_REVISION}});
}
export async function webhookHandler(req:Request):Promise<Response>{
 const url=new URL(req.url);
 if(url.searchParams.get('check')==='media'){
  const a=Buffer.from(req.headers.get('x-ai-test-token')??''),b=Buffer.from(env.testHarnessToken);
  if(!b.length||a.length!==b.length||!timingSafeEqual(a,b))return json({error:'unauthorized'},401);
  if(req.method!=='POST')return json({error:'method_not_allowed'},405);
  try{
   const svc=services(configuration()),product=(await svc.products()).find(p=>p.sku==='FB-9866');
   if(!product)throw Error('fixture_missing');
   const bytes=await jpegForMeta(await svc.photo(product));
   return json({ok:true,revision:REVISION,fixture:product.sku,mime:'image/jpeg',bytes:bytes.length,sha256:createHash('sha256').update(bytes).digest('hex'),sentToMeta:false});
  }catch(e){return json({ok:false,error:e instanceof Error?e.message:'media_check_failed',revision:REVISION},503);}
 }
 if(req.method==='GET'){
  const result=verifyHandshake(url,env.metaVerifyToken);
  return result.ok?new Response(result.challenge,{headers:{'Content-Type':'text/plain'}}):new Response('forbidden',{status:403});
 }
 if(req.method!=='POST')return new Response('method not allowed',{status:405});
 const is360=url.searchParams.get('provider')==='360dialog';
 if(is360&&!verify360Webhook(req.headers.get('x-ferreira-webhook-token'),env))return json({error:'invalid_provider_auth'},403);
 let raw:string;try{raw=new TextDecoder().decode(await boundedBytes(new Response(req.body),is360?8_000_000:2_000_000));}catch{return json({error:'body_too_large'},413);}
 let payload:any;try{payload=JSON.parse(raw);}catch{return json({error:'invalid_json'},400);}
 if(is360){try{payload=canonical360Webhook(payload);}catch{return json({error:'unsupported_provider_event'},400);}}
 const signature=is360?{valid:true as const}:verifyChannelSignature(raw,req.headers.get('x-hub-signature-256'),payload?.object,env);
 if(!signature.valid){
  // Bound unauthenticated audit volume; never store the header or request contents.
  if(Date.now()-lastRejectedAudit>60_000){lastRejectedAudit=Date.now();await auditWebhook('webhook_rejected',{reason:signature.reason,channel:webhookChannel(payload?.object),credentialSource:payload?.object==='instagram'&&env.instagramApiMode==='instagram_login'?'instagram_app':'meta_app'});}
  return new Response('invalid signature',{status:403});
 }
 const channel=webhookChannel(payload?.object);
 const messages=normalizeWebhook(payload).filter(m=>m.channel===channel),echoes=channel==='whatsapp'?normalizeBusinessEchoes(payload):[];
 const work=(async()=>{
  await auditWebhook('webhook_received',{stage:'authenticated_event',object:['instagram','page','whatsapp_business_account'].includes(payload?.object)?payload.object:'other',messages:messages.length,echoes:echoes.length,coexistenceRevision:COEXISTENCE_REVISION,provider:is360?'360dialog':'meta',sendingEnabled:env.sendingEnabled});
  let retry=false;
  for(const echo of echoes)if(!await handleBusinessEcho(echo))retry=true;
  if(channel==='whatsapp'){await importHistory(payload);await syncKnownContacts(payload);}
  for(const message of messages){
   if(message.isEcho){
    if(channelReady(message.channel,message.accountId)&&!await handleBusinessEcho({channel:message.channel,accountId:message.accountId,source:'api_echo',externalMessageId:message.externalMessageId,recipientId:message.recipientId,text:message.text,timestamp:message.timestamp}))retry=true;
    continue;
   }
   if(!await handleMessage(message))retry=true;
  }
  return !retry;
 })();
 if(typeof EdgeRuntime!=='undefined')EdgeRuntime.waitUntil(work);
 try{return await work?json({received:true}):json({received:false,retry:true},503);}
 catch(e){await logError('error',e,{fase:'webhook'});return json({received:false,retry:true},503);}
}
const d=(globalThis as any).Deno;if(d?.serve)d.serve(webhookHandler);

