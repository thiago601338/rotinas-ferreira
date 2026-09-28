import { createHmac,timingSafeEqual } from "node:crypto"; import { Buffer } from "node:buffer";
export type SignatureResult={valid:true}|{valid:false;reason:"missing_secret"|"missing_header"|"bad_format"|"mismatch"};
export function verifyMetaSignature(rawBody:string,headerValue:string|null,appSecret:string):SignatureResult{if(!appSecret)return{valid:false,reason:"missing_secret"};if(!headerValue)return{valid:false,reason:"missing_header"};if(!headerValue.startsWith("sha256="))return{valid:false,reason:"bad_format"};const received=headerValue.slice(7).trim().toLowerCase();if(!/^[0-9a-f]{64}$/.test(received))return{valid:false,reason:"bad_format"};const expected=createHmac("sha256",appSecret).update(rawBody,"utf8").digest("hex");const a=Buffer.from(received,"hex"),b=Buffer.from(expected,"hex");if(a.length!==b.length)return{valid:false,reason:"mismatch"};return timingSafeEqual(a,b)?{valid:true}:{valid:false,reason:"mismatch"};}
export function verifyHandshake(url:URL,expectedToken:string):{ok:true;challenge:string}|{ok:false;reason:string}{const mode=url.searchParams.get("hub.mode"),token=url.searchParams.get("hub.verify_token"),challenge=url.searchParams.get("hub.challenge");if(!expectedToken)return{ok:false,reason:"verify_token_not_configured"};if(mode!=="subscribe")return{ok:false,reason:"bad_mode"};if(!token||!challenge)return{ok:false,reason:"missing_params"};const a=Buffer.from(token),b=Buffer.from(expectedToken);if(a.length!==b.length||!timingSafeEqual(a,b))return{ok:false,reason:"token_mismatch"};return{ok:true,challenge};}

export function webhookChannel(object:unknown):'instagram'|'whatsapp'|'messenger'|null{return object==='instagram'?'instagram':object==='whatsapp_business_account'?'whatsapp':object==='page'?'messenger':null;}
export function verifyChannelSignature(raw:string,header:string|null,object:unknown,config:{metaAppSecret:string;instagramAppSecret:string;instagramApiMode:string}):SignatureResult{
 // The unsigned object is used ONLY to select a verification key. No event is trusted
 // until its complete raw body has passed HMAC verification with that channel's key.
 const key=object==='instagram'&&config.instagramApiMode==='instagram_login'?config.instagramAppSecret:config.metaAppSecret;
 return verifyMetaSignature(raw,header,key);
}

