import {timingSafeEqual} from 'node:crypto';
import {Buffer} from 'node:buffer';

export const COEXISTENCE_REVISION='v6.0-coexistence-20260910-r1';
export function whatsappProvider(c:any):'meta'|'360dialog'{
 const p=c.whatsappProvider||'meta';
 if(p!=='meta'&&p!=='360dialog')throw Error('invalid_whatsapp_provider');
 return p;
}
export function whatsappRequest(c:any,operation:'messages'|'media'|'metadata',mediaId?:string){
 const provider=whatsappProvider(c),key=provider==='360dialog'?c.whatsapp360ApiKey:c.whatsappToken;
 if(!key||!/^\d+$/.test(c.whatsappPhoneNumberId??''))throw Error('whatsapp_not_configured');
 if(operation==='metadata'&&!/^\d+$/.test(mediaId??''))throw Error('invalid_media_id');
 if(provider==='360dialog')return {url:'https://waba-v2.360dialog.io/'+(operation==='metadata'?mediaId:operation),token:key,headers:{'D360-API-KEY':key} as Record<string,string>};
 if(!/^v\d+\.\d+$/.test(c.metaGraphVersion??''))throw Error('invalid_graph_version');
 return {url:`https://graph.facebook.com/${c.metaGraphVersion}/`+(operation==='metadata'?mediaId:c.whatsappPhoneNumberId+'/'+operation),token:key,headers:{Authorization:'Bearer '+key}};
}
export function whatsappDownloadRequest(c:any,mediaUrl:string){
 const u=new URL(mediaUrl),provider=whatsappProvider(c);
 if(u.protocol!=='https:'||u.username||u.password||u.port)throw Error('invalid_media_url');
 if(provider==='360dialog'){
  if(!['lookaside.fbsbx.com','waba-v2.360dialog.io'].includes(u.hostname)||!u.pathname.startsWith('/whatsapp_business/attachments/'))throw Error('invalid_media_host');
  u.hostname='waba-v2.360dialog.io';
  return {url:u.toString(),headers:whatsappRequest(c,'media').headers};
 }
 if(!['facebook.com','fbcdn.net','fbsbx.com'].some(h=>u.hostname===h||u.hostname.endsWith('.'+h)))throw Error('invalid_media_host');
 return {url:u.toString(),headers:whatsappRequest(c,'media').headers};
}
export function verify360Webhook(header:string|null,c:any):boolean{
 if(c.whatsappProvider!=='360dialog'||!c.whatsappCoexistenceEnabled)return false;
 const expected=String(c.whatsapp360WebhookSecret??'');
 if(expected.length<32||!header||header.length>512)return false;
 const a=Buffer.from(header),b=Buffer.from(expected);
 return a.length===b.length&&timingSafeEqual(a,b);
}
/** This conversion is only called after the dedicated provider header is authenticated. */
export function canonical360Webhook(p:any):any{
 if(p?.object==='whatsapp_business_account'&&Array.isArray(p.entry))return p;
 if(['history','smb_app_state_sync','smb_message_echoes'].includes(p?.event)&&p?.data?.messaging_product==='whatsapp')return {object:'whatsapp_business_account',entry:[{id:String(p.data.id??''),changes:[{field:p.event,value:p.data}]}]};
 throw Error('unsupported_provider_event');
}
