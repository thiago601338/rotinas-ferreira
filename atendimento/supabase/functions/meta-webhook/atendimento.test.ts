// Teste local isolado. Toda chamada HTTP é interceptada abaixo.
Deno.env.set('SUPABASE_URL', 'https://database.invalid');
Deno.env.set('SUPABASE_SERVICE_ROLE_KEY', 'chave-falsa-exclusiva-do-teste');
Deno.env.set('INSTAGRAM_TOKEN', 'token-falso-exclusivo-do-teste');
Deno.env.set('INSTAGRAM_ACCOUNT_ID', '17841454587986765');
Deno.env.set('AI_SENDING_ENABLED', 'false');
const { normalizeWebhook } = await import('./lib/meta.ts');
const { handleInstagramMessage } = await import('./lib/pipeline-instagram.ts');
const eq = (actual:unknown, expected:unknown) => { if(JSON.stringify(actual)!==JSON.stringify(expected))throw Error(`Não corresponde: ${JSON.stringify(actual)} / ${JSON.stringify(expected)}`); };
const assert = (condition:unknown, why:string) => { if(!condition)throw Error(why); };
const payload = (message:any, object='instagram') => ({ object, entry:[{ id:'17841454587986765', messaging:[{
 sender:{id:'17841400000000001'}, recipient:{id:'17841454587986765'}, timestamp:1790550000000,
 message:{ mid:'mid.test', ...message },
}]}] });
const events:any[]=[];
let mode='claude',duplicate=false,failOptout=false;
const imageBytes = new Uint8Array([255,216,255,224,1,2,3,4]);
globalThis.fetch=async (input:any, init:any={})=>{
 const url=new URL(typeof input==='string'?input:input.url),method=init.method??'GET';
 const body=typeof init.body==='string'?JSON.parse(init.body):null;
 events.push({url:url.href,pathname:url.pathname,method,body});
 if(url.hostname==='scontent.fbcdn.net'){
  assert(!url.pathname.endsWith('.mp4'),'não pode baixar vídeo');
  if(url.pathname.endsWith('.ogg')){
   const audio=new Uint8Array(32);audio.set(new TextEncoder().encode('OggS'));
   return new Response(audio,{headers:{'Content-Type':'audio/ogg'}});
  }
  return new Response(imageBytes,{headers:{'Content-Type':'image/jpeg'}});
 }
 assert(url.hostname==='database.invalid','tentativa de HTTP externo não permitida no teste');
 const table=url.pathname.split('/').at(-1);
 if(method==='GET'&&table==='ai_settings')return Response.json([{value:{instagram:mode}}]);
 if(method==='GET'&&table==='ai_conversations')return Response.json([{id:'00000000-0000-4000-8000-000000000001',channel:'instagram',metadata:{},status:'open'}]);
 if(method==='POST'&&table==='ai_messages')return duplicate?Response.json({error:'duplicate'},{status:409}):Response.json([{id:'00000000-0000-4000-8000-000000000002'}]);
 if(method==='POST'&&table==='ai_optouts')return failOptout?Response.json({error:'failed'},{status:503}):Response.json([]);
 if(method==='POST'&&table==='ai_logs')return Response.json([]);
 if(method==='POST'&&table==='ai_atendimento_registrar_midia')return Response.json(null);
 if(method==='POST'&&url.pathname.startsWith('/storage/'))return Response.json({ok:true});
 throw Error(`HTTP não simulado: ${method} ${url.pathname}`);
};
function reset(){events.length=0;mode='claude';duplicate=false;failOptout=false;}
const stored=()=>events.find(e=>e.pathname==='/rest/v1/ai_messages')?.body;

Deno.test('opt-out é persistido após inbound, sem inferência/envio',async()=>{
 reset();await handleInstagramMessage(normalizeWebhook(payload({text:'Não quero mais receber mensagens'}))[0]);
 eq(events.filter(e=>e.method==='POST').map(e=>e.pathname),['/rest/v1/ai_messages','/rest/v1/ai_optouts','/rest/v1/ai_logs']);
 eq(stored().raw_payload.processingStatus,'claude');
});
Deno.test('retry de inbound duplicado ainda persiste opt-out idempotente',async()=>{
 reset();duplicate=true;await handleInstagramMessage(normalizeWebhook(payload({text:'stop'}))[0]);
 eq(events.filter(e=>e.pathname==='/rest/v1/ai_optouts').length,1);
});
Deno.test('falha de persistência do opt-out propaga para permitir retry do webhook',async()=>{
 reset();failOptout=true;let failed=false;
 try{await handleInstagramMessage(normalizeWebhook(payload({text:'pare de me mandar mensagens'}))[0]);}catch{failed=true;}
 assert(failed,'falha não deve ser ignorada');eq(events.filter(e=>e.pathname==='/rest/v1/ai_messages').length,1);
});
Deno.test('vídeo preserva URL, id e capa no raw_payload e não faz download',async()=>{
 reset();const m=normalizeWebhook(payload({attachments:[{type:'video',payload:{id:'180000000000001',url:'https://scontent.fbcdn.net/clip.mp4',thumbnail_url:'https://scontent.fbcdn.net/frame.jpg'}}]}))[0];
 // Contrato usado pela IA permanece sem suporte ao vídeo.
 eq(m.mediaType,null);eq(m.mediaUrl,null);eq(m.supported,false);
 await handleInstagramMessage(m);
 eq(stored().message_type,'document');eq(stored().raw_payload.mediaType,'video');
 eq(stored().raw_payload.mediaId,'180000000000001');eq(stored().raw_payload.attachments[0].thumbnailUrl,'https://scontent.fbcdn.net/frame.jpg');
 eq(events.some(e=>new URL(e.url).hostname==='scontent.fbcdn.net'),false);
});
Deno.test('share, post e reel mantêm referência e id sem serem tratados como download',async()=>{
 for(const type of ['share','ig_post','ig_reel','post','reel']){
  reset();const m=normalizeWebhook(payload({attachments:[{type,payload:{id:'180000000000002',url:'https://instagram.com/reel/exemplo/',image_url:'https://scontent.fbcdn.net/capa.jpg'}}]}))[0];
  eq(m.supported,false);await handleInstagramMessage(m);
  eq(stored().raw_payload.postReference.id,'180000000000002');eq(stored().raw_payload.sharedMediaId,'180000000000002');
  eq(stored().raw_payload.postReference.thumbnailUrl,'https://scontent.fbcdn.net/capa.jpg');eq(stored().message_type,'image');
  eq(events.some(e=>new URL(e.url).hostname==='scontent.fbcdn.net'),false);
 }
});
Deno.test('shares com data preserva link mesmo sem id',async()=>{
 reset();await handleInstagramMessage(normalizeWebhook(payload({shares:{data:[{link:'https://instagram.com/p/exemplo/'}]}}))[0]);
 eq(stored().raw_payload.postReference.url,'https://instagram.com/p/exemplo/');eq(stored().raw_payload.postReference.id,null);
});
Deno.test('foto calcula SHA-256 e usa merge atômico após upload',async()=>{
 reset();await handleInstagramMessage(normalizeWebhook(payload({attachments:[{type:'image',payload:{url:'https://scontent.fbcdn.net/photo.jpg'}}]}))[0]);
 const rpc=events.find(e=>e.pathname==='/rest/v1/rpc/ai_atendimento_registrar_midia');
 const expected=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',imageBytes)),b=>b.toString(16).padStart(2,'0')).join('');
 eq(rpc.body.p_image_hash,expected);assert(rpc.body.p_path.endsWith('.jpeg'),'caminho da imagem');
 assert(events.findIndex(e=>e.pathname.startsWith('/storage/'))<events.indexOf(rpc),'upload antes do registro');
 eq(events.some(e=>e.method==='PATCH'),false);
});
Deno.test('IA desligada mantém retorno anterior mesmo para vídeo com referência adicional',async()=>{
 reset();mode='ia';await handleInstagramMessage(normalizeWebhook(payload({attachments:[{type:'video',payload:{url:'https://scontent.fbcdn.net/clip.mp4'}}]}))[0]);
 eq(stored(),undefined);eq(events.map(e=>e.pathname),['/rest/v1/ai_settings','/rest/v1/ai_logs']);
});
Deno.test('áudio continua sendo guardado e não recebe hash de imagem',async()=>{
 reset();await handleInstagramMessage(normalizeWebhook(payload({attachments:[{type:'audio',payload:{url:'https://scontent.fbcdn.net/audio.ogg'}}]}))[0]);
 eq(stored().message_type,'audio');eq(stored().raw_payload.mediaType,'audio');
 const rpc=events.find(e=>e.pathname==='/rest/v1/rpc/ai_atendimento_registrar_midia');
 eq(rpc.body.p_image_hash,null);assert(rpc.body.p_path.endsWith('.ogg'),'extensão áudio preservada');
});
Deno.test('Messenger mantém normalização sem metadados exclusivos do atendimento Instagram',()=>{
 const m=normalizeWebhook(payload({attachments:[{type:'video',payload:{url:'https://scontent.fbcdn.net/clip.mp4'}}]},'page'))[0];
 eq(m.channel,'messenger');eq(m.atendimentoMedia,undefined);eq(m.supported,false);
});
