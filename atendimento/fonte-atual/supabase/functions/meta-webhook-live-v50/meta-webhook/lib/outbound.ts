import {whatsappRequest} from './whatsapp-provider.ts';
/** Same ordered response contract used by the test console and real channels. */
import {CATALOG_PAGE_SIZE, MESSAGE_DELAY_MS} from '../../ai-test/customer-experience.ts';
export type Part={tipo:'imagem'|'texto';produtoId?:string;imagem?:string;texto?:string;legenda?:string;purpose?:string;corFoto?:string|null};
export function outboundParts(result:any):Part[]{
  if(!result?.ok||!Array.isArray(result.mensagens))throw Error('invalid_engine_response');
  const parts:Part[]=result.mensagens.map((p:any)=>({...p}));
  if(parts.length>CATALOG_PAGE_SIZE*2+3)throw Error('too_many_response_parts');
  for(let i=0;i<parts.length;i++){
    const p=parts[i];
    if(p.tipo==='imagem'){
      const details=parts[i+1];
      const confirmation=p.purpose==='confirm_identity'&&details?.purpose==='confirm_identity';
      if(!p.imagem?.startsWith('data:image/')||!p.produtoId||details?.tipo!=='texto'||details.produtoId!==p.produtoId||(!confirmation&&(!details.texto?.includes('Tamanhos disponíveis')||!details.texto.includes('Preço:'))))throw Error('image_details_order_invalid');
      // Instagram attachments have no caption: put the option label with its details.
      details.texto=(p.legenda?p.legenda+'\n':'')+details.texto;
    }else if(p.tipo!=='texto'||!p.texto)throw Error('invalid_response_part');
  }
  return parts;
}
export function splitText(text:string,max=950):string[]{
  const out:string[]=[];let left=text;
  while(left.length>max){let at=left.lastIndexOf('\n',max);if(at<max/2)at=left.lastIndexOf(' ',max);if(at<max/2)at=max;out.push(left.slice(0,at));left=left.slice(at).trimStart();}
  if(left)out.push(left);return out;
}
export function messageRequest(config:any,channel:string,to:string,part:{text?:string;mediaId?:string;mediaUrl?:string}){
  const version=channel==='instagram'?(config.instagramGraphVersion??config.metaGraphVersion):config.metaGraphVersion;
  const ig=channel==='instagram',wa=channel==='whatsapp';
  const account=wa?config.whatsappPhoneNumberId:ig?config.instagramAccountId:config.messengerPageId;
  const token=wa?(config.whatsappProvider==='360dialog'?config.whatsapp360ApiKey:config.whatsappToken):ig?config.instagramToken:config.messengerToken;
  if(!token||!/^\d+$/.test(account??'')||!/^\d+$/.test(to)||!/^v\d+\.\d+$/.test(version))throw Error('channel_not_configured');
  const host=ig&&config.instagramApiMode==='instagram_login'?'graph.instagram.com':'graph.facebook.com';
  const message=part.text!==undefined?{text:part.text}:{attachment:{type:'image',payload:{url:part.mediaUrl}}};
  const body=wa?{messaging_product:'whatsapp',recipient_type:'individual',to,...(part.text!==undefined?{type:'text',text:{preview_url:false,body:part.text}}:{type:'image',image:{id:part.mediaId}})}:{recipient:{id:to},...(channel==='messenger'?{messaging_type:'RESPONSE'}:{}),message};
  return wa?{...whatsappRequest(config,'messages'),body}:{url:`https://${host}/${version}/${account}/messages`,token,headers:{Authorization:'Bearer '+token},body};
}
export type DeliveryPacing={minimumDelayMs?:number;previousAcceptedAt?:number;now?:()=>number;wait?:(ms:number)=>Promise<void>;onPause?:()=>Promise<unknown>};
export async function orderedDelivery(parts:Part[],send:(part:Part,index:number)=>Promise<any>,record:(part:Part,index:number,result:any)=>Promise<void>,maySend:()=>Promise<boolean>,pacing:DeliveryPacing={}){
  const now=pacing.now??Date.now,wait=pacing.wait??(ms=>new Promise<void>(resolve=>setTimeout(resolve,ms)));
  let delivered=0;
  for(const [index,part]of parts.entries()){
    if(!await maySend())return {complete:false,delivered,error:'human_takeover_or_closed'};
    const remaining=pacing.previousAcceptedAt===undefined?0:Math.max(0,(pacing.minimumDelayMs??MESSAGE_DELAY_MS)-(now()-pacing.previousAcceptedAt));
    if(remaining>0){
      // Typing is best effort. Its failure never removes the minimum pause or blocks delivery.
      await Promise.all([wait(remaining),Promise.resolve().then(()=>pacing.onPause?.()).catch(()=>{})]);
      if(!await maySend())return {complete:false,delivered,error:'human_takeover_or_closed'};
    }
    const result=await send(part,index);
    if(result.sent)pacing.previousAcceptedAt=now();
    // Record the accepted provider ID before attempting the next part.
    await record(part,index,result);
    if(!result.sent)return {complete:false,delivered,error:result.error??result.skipped??'send_failed'};
    delivered++;
  }
  return {complete:true,delivered};
}

