import { insertRow } from "./supabase.ts";
export type LogKind="webhook_received"|"webhook_rejected"|"webhook_duplicate"|"message_sent"|"message_send_failed"|"rate_limited"|"handoff_opened"|"optout"|"vision_analysis"|"catalog_search"|"loop_guard"|"error";
interface LogInput{kind:LogKind;level?:"info"|"warn"|"error";channel?:string|null;conversationId?:string|null;detail?:Record<string,unknown>;}
const REDACT=/token|secret|authorization|apikey|api_key|password|signature/i;
function scrub(v:unknown,d=0):unknown{if(d>4)return"[profundo]";if(v===null||typeof v!=="object")return v;if(Array.isArray(v))return v.slice(0,20).map(x=>scrub(x,d+1));const o:Record<string,unknown>={};for(const[k,x]of Object.entries(v as Record<string,unknown>))o[k]=REDACT.test(k)?"[removido]":scrub(x,d+1);return o;}
export async function logEvent(i:LogInput):Promise<void>{const r={kind:i.kind,level:i.level??"info",channel:i.channel??null,conversation_id:i.conversationId??null,detail:scrub(i.detail??{}) as Record<string,unknown>};try{await insertRow("ai_logs",r);}catch(e){console.error("[ai_logs]",{kind:r.kind,error:e instanceof Error?e.message:String(e)});}}
export async function logError(kind:LogKind,error:unknown,extra:Record<string,unknown>={}):Promise<void>{await logEvent({kind,level:"error",detail:{...extra,message:error instanceof Error?error.message:String(error)}});}

