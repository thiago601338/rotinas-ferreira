import { env } from "./env.ts";
export class SupabaseError extends Error{status:number;detail:string;constructor(message:string,status:number,detail:string){super(message);this.name="SupabaseError";this.status=status;this.detail=detail;}}
function requireConfig(){if(!env.supabaseUrl||!env.supabaseSecretKey)throw new SupabaseError("Supabase não configurado",500,"missing_env");}
function headers(extra:Record<string,string>={}):Record<string,string>{return{apikey:env.supabaseSecretKey,...(env.supabaseSecretKey.startsWith("eyJ")?{Authorization:`Bearer ${env.supabaseSecretKey}`}:{ }),"Content-Type":"application/json",...extra};}
export async function selectRows<T=any>(table:string,query:string):Promise<T[]>{requireConfig();const r=await fetch(`${env.supabaseUrl}/rest/v1/${table}?${query}`,{method:"GET",signal:AbortSignal.timeout(12000),headers:headers()});const b=await r.text();if(!r.ok)throw new SupabaseError(`select ${table} falhou`,r.status,b.slice(0,500));return b?JSON.parse(b) as T[]:[];}
export async function insertRow<T=any>(table:string,row:Record<string,unknown>,options:{onConflict?:string;ignoreDuplicates?:boolean}={}):Promise<T|null>{requireConfig();const p=new URLSearchParams();if(options.onConflict)p.set("on_conflict",options.onConflict);const prefer=["return=representation",options.ignoreDuplicates?"resolution=ignore-duplicates":options.onConflict?"resolution=merge-duplicates":""].filter(Boolean).join(",");const q=p.toString();const r=await fetch(`${env.supabaseUrl}/rest/v1/${table}${q?`?${q}`:""}`,{method:"POST",signal:AbortSignal.timeout(12000),headers:headers({Prefer:prefer}),body:JSON.stringify(row)});const b=await r.text();if(!r.ok)throw new SupabaseError(`insert ${table} falhou`,r.status,b.slice(0,500));const x=b?JSON.parse(b):[];return Array.isArray(x)?x[0]??null:x;}
export async function updateRows<T=any>(table:string,filter:string,patch:Record<string,unknown>):Promise<T[]>{requireConfig();const r=await fetch(`${env.supabaseUrl}/rest/v1/${table}?${filter}`,{method:"PATCH",signal:AbortSignal.timeout(12000),headers:headers({Prefer:"return=representation"}),body:JSON.stringify(patch)});const b=await r.text();if(!r.ok)throw new SupabaseError(`update ${table} falhou`,r.status,b.slice(0,500));return b?JSON.parse(b) as T[]:[];}
export async function rpc<T=any>(fn:string,args:Record<string,unknown>={}):Promise<T>{requireConfig();const r=await fetch(`${env.supabaseUrl}/rest/v1/rpc/${fn}`,{method:"POST",signal:AbortSignal.timeout(12000),headers:headers(),body:JSON.stringify(args)});const b=await r.text();if(!r.ok)throw new SupabaseError(`rpc ${fn} falhou`,r.status,b.slice(0,500));return b?JSON.parse(b) as T:null as T;}
export async function uploadInboxMedia(path:string,bytes:ArrayBuffer,contentType:string):Promise<string>{requireConfig();const r=await fetch(`${env.supabaseUrl}/storage/v1/object/ai-inbox-media/${path}`,{method:"POST",headers:{apikey:env.supabaseSecretKey,...(env.supabaseSecretKey.startsWith("eyJ")?{Authorization:`Bearer ${env.supabaseSecretKey}`}:{ }),"Content-Type":contentType,"x-upsert":"true"},body:bytes});if(!r.ok)throw new SupabaseError("upload de mídia falhou",r.status,(await r.text()).slice(0,500));return path;}


/** Bulk archive insertion is idempotent against the existing external-message unique index. */
export async function insertArchiveRows(rows:Record<string,unknown>[]):Promise<number>{
 requireConfig();if(!rows.length)return 0;
 const r=await fetch(`${env.supabaseUrl}/rest/v1/ai_messages`,{method:'POST',signal:AbortSignal.timeout(12000),headers:headers({Prefer:'return=representation,resolution=ignore-duplicates'}),body:JSON.stringify(rows)});
 const body=await r.text();
 // The external ID uses a partial unique index. A concurrent live insert can race
 // the preflight query; retry individual archive rows only on a uniqueness conflict.
 if(r.status===409){let saved=0;for(const row of rows){try{if(await insertRow('ai_messages',row))saved++;}catch(e){if(!(e instanceof SupabaseError&&e.status===409))throw e;}}return saved;}
 if(!r.ok)throw new SupabaseError('archive insert failed',r.status,body.slice(0,500));
 return body?JSON.parse(body).length:0;
}

