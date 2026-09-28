// Webhook isolado: nenhuma chamada alcança banco, Meta ou clientes reais.
Deno.env.set('SUPABASE_URL','https://database.invalid');
Deno.env.set('SUPABASE_SERVICE_ROLE_KEY','chave-falsa-exclusiva-do-teste');
Deno.env.set('INSTAGRAM_TOKEN','token-falso-exclusivo-do-teste');
Deno.env.set('INSTAGRAM_ACCOUNT_ID','17841454587986765');
Deno.env.set('AI_SENDING_ENABLED','false');
const {handleBusinessEcho}=await import('./lib/pipeline.ts');
const eq=(actual:unknown,expected:unknown)=>{if(JSON.stringify(actual)!==JSON.stringify(expected))throw Error(`Não corresponde: ${JSON.stringify(actual)} / ${JSON.stringify(expected)}`);};
const conversation='00000000-0000-4000-8000-000000000001';
const events:any[]=[];
let processing=false,manualExpected=false,confirmedAfter=Infinity,idReads=0,mode='claude';
const echo={channel:'instagram' as const,externalMessageId:'mid.equipe',recipientId:'17841400000000001',text:'Olá meu bem',timestamp:'2026-09-28T00:00:00Z',accountId:'17841454587986765',source:'api_echo' as const};

globalThis.fetch=async(input:any,init:any={})=>{
 const url=new URL(typeof input==='string'?input:input.url),method=init.method??'GET';
 if(url.hostname!=='database.invalid')throw Error('HTTP externo proibido');
 const body=typeof init.body==='string'?JSON.parse(init.body):null;
 events.push({url,method,body});
 const table=url.pathname.split('/').at(-1);
 if(method==='GET'&&table==='ai_messages'){
  if(url.searchParams.has('external_message_id')){
   eq(url.searchParams.get('external_message_id'),'eq.'+echo.externalMessageId);
   return Response.json(++idReads>=confirmedAfter?[{id:'stored-confirmed'}]:[]);
  }
  return Response.json([{created_at:'2026-09-27T23:59:00Z'}]);
 }
 if(method==='GET'&&table==='ai_conversations')return Response.json([{id:conversation,channel:'instagram',status:'open',metadata:processing?{aiProcessing:{owner:'teste'}}:{}}]);
 if(method==='GET'&&table==='ai_settings')return Response.json([{value:{instagram:mode}}]);
 if(method==='GET'&&table==='ai_handoffs')return Response.json([]);
 if(method==='POST'&&table==='ai_atendimento_echo_previsto')return Response.json(manualExpected);
 if(method==='POST'&&table==='ai_messages')return Response.json([{id:'new-echo'}]);
 if(method==='PATCH'&&table==='ai_conversations')return Response.json([]);
 if(method==='POST'&&['ai_handoffs','ai_logs'].includes(table!))return Response.json([]);
 throw Error(`HTTP não simulado: ${method} ${url.pathname}`);
};
function reset(){events.length=0;processing=false;manualExpected=false;confirmedAfter=Infinity;idReads=0;mode='claude';}
const inserted=()=>events.find(e=>e.method==='POST'&&e.url.pathname==='/rest/v1/ai_messages')?.body;
const handoffs=()=>events.filter(e=>e.method==='POST'&&e.url.pathname==='/rest/v1/ai_handoffs').length;

Deno.test('eco com ID já confirmado não cria mensagem nem handoff',async()=>{
 reset();confirmedAfter=1;eq(await handleBusinessEcho(echo),true);
 eq(idReads,1);eq(inserted(),undefined);eq(handoffs(),0);
});
Deno.test('ID confirmado durante espera concilia API sem comparar texto',async()=>{
 reset();processing=true;confirmedAfter=2;eq(await handleBusinessEcho(echo),true);
 eq(idReads,2);eq(inserted(),undefined);eq(handoffs(),0);
 eq(events.some(e=>e.url.pathname.endsWith('/ai_atendimento_echo_previsto')),false);
});
Deno.test('texto igual à parte em envio com ID não confirmado permanece da equipe',async()=>{
 reset();processing=true;eq(await handleBusinessEcho(echo),true);
 eq(inserted().external_message_id,'mid.equipe');
 eq(inserted().raw_payload.origem,'conta_da_loja');eq(handoffs(),1);
});
Deno.test('pelo_instagram mantém reconhecimento por texto e não abre handoff',async()=>{
 reset();manualExpected=true;eq(await handleBusinessEcho(echo),true);
 eq(inserted().raw_payload.origem,'claude');eq(handoffs(),0);
});
Deno.test('modo ia não usa previsão do atendimento',async()=>{
 reset();mode='ia';manualExpected=true;eq(await handleBusinessEcho(echo),true);
 eq(inserted().raw_payload.origem,'conta_da_loja');eq(handoffs(),1);
 eq(events.some(e=>e.url.pathname.endsWith('/ai_atendimento_echo_previsto')),false);
});
