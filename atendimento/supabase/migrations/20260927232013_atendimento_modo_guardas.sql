-- Guardas de modo sobre as versões congeladas de 27/09.

-- FUNCAO public.ai_ig_track_quiet
CREATE OR REPLACE FUNCTION public.ai_ig_track_quiet()
 RETURNS trigger
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
declare c public.ai_conversations; w public.ai_human_waits; receipt timestamptz:=clock_timestamp();
begin
 if atendimento.modo_atual()='claude' then return new; end if;
 if coalesce(new.raw_payload->>'importedHistory','false')='true' then return new; end if;
 if not exists(select 1 from public.ai_settings where key='instagram_turn_policy' and value->>'enabled'='true') then return new; end if;
 select * into c from public.ai_conversations where id=new.conversation_id for update;
 if not found or c.channel<>'instagram' or c.status='closed' then return new; end if;
 select * into w from public.ai_human_waits where conversation_id=c.id for update;
 if new.direction='inbound' and w.state='waiting' and w.inbound_at>receipt-interval '24 hours' and (w.last_human_at is null or new.created_at>w.last_human_at) then
  insert into public.ai_instagram_turn_queue(conversation_id,last_inbound_id,received_at,due_at,not_before,state) values(c.id,w.last_inbound_id,receipt,receipt+interval '60 seconds',receipt+interval '60 seconds','queued')
  on conflict(conversation_id) do update set last_inbound_id=excluded.last_inbound_id,received_at=excluded.received_at,due_at=excluded.due_at,not_before=excluded.not_before,state='queued',owner=null,lease_until=null,attempts=0,after_human_wait=false,updated_at=receipt;
  update public.ai_conversations set last_message_at=greatest(last_message_at,receipt),metadata=coalesce(metadata,'{}'::jsonb)-'aiIgAfterHumanWait' where id=c.id;
 elsif new.direction='outbound' and (new.raw_payload->>'origem' in ('conta_da_loja','whatsapp_business_app') or new.raw_payload->>'coexistence'='true') and (w.last_inbound_id is null or new.created_at>=w.inbound_at) then
  update public.ai_instagram_turn_queue set state='cancelled',owner=null,lease_until=null,updated_at=receipt where conversation_id=c.id;
 end if;
 return new;
end $function$
;


-- FUNCAO public.ai_ig_dispatch
CREATE OR REPLACE FUNCTION public.ai_ig_dispatch()
 RETURNS bigint
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
declare request_id bigint;
begin
 if atendimento.modo_atual()='claude' then return null; end if;
 if not exists(select 1 from public.ai_settings where key='instagram_turn_policy' and value->>'enabled'='true') then return null; end if;
 if exists(select 1 from public.ai_settings where key='instagram_delivery_health' and value->>'status'='blocked') then return null; end if;
 perform public.ai_recover_followups();
 perform public.ai_ig_dispatch_reference_recovery();
 perform public.ai_ig_dispatch_dialogue_continuity();
 update public.ai_instagram_turn_queue q set state='queued',owner=null,lease_until=null,not_before=greatest(q.due_at,coalesce(w.due_at,now())),updated_at=now() from public.ai_conversations c,public.ai_human_waits w where q.conversation_id=c.id and w.conversation_id=c.id and q.last_inbound_id=w.last_inbound_id and q.state='preflight' and q.lease_until<now() and not(c.metadata ? 'aiProcessing') and w.state='waiting';
 if not exists(select 1 from public.ai_instagram_turn_queue q join public.ai_conversations c on c.id=q.conversation_id join public.ai_human_waits w on w.conversation_id=c.id where q.state='queued' and q.not_before<=now() and q.due_at<=now() and w.state='waiting' and q.last_inbound_id=w.last_inbound_id and w.inbound_at>now()-interval '24 hours' and not exists(select 1 from public.ai_optouts o where o.channel=c.channel and o.external_user_id=c.external_user_id) and (c.status='open' or (c.status='human' and w.due_at<=now() and c.metadata ? 'manualEchoObservedAt' and coalesce(w.category,'')<>'human_request' and w.last_human_at is not null
   and w.last_human_at+interval '10 minutes'<=clock_timestamp()
   and exists(select 1 from public.ai_messages hm where hm.conversation_id=c.id
     and hm.direction='outbound' and hm.created_at=w.last_human_at
     and coalesce(hm.raw_payload->>'importedHistory','false')<>'true'
     and coalesce(hm.raw_payload->>'enviado','true')<>'false'
     and (hm.raw_payload->>'origem' in ('conta_da_loja','whatsapp_business_app') or hm.raw_payload->>'coexistence'='true')))) and not(c.metadata ? 'aiProcessing')) then return null; end if;
 select net.http_post(url:='https://nailfzcujyxydqldktgg.supabase.co/functions/v1/instagram-turn-worker-v6',headers:=jsonb_build_object('Content-Type','application/json','x-ai-followup-token',(select secret from private.ai_followup_config where id=true)),body:='{"action":"tick"}'::jsonb,timeout_milliseconds:=10000) into request_id;
 return request_id;
end
$function$
;


-- FUNCAO private.ai_audio_preprocess_dispatch
CREATE OR REPLACE FUNCTION private.ai_audio_preprocess_dispatch()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare
  v_secret text;
begin
  if new.direction <> 'inbound'
     or coalesce(new.raw_payload->>'channel','') <> 'instagram'
     or coalesce(new.raw_payload->>'mediaType','') <> 'audio'
     or new.raw_payload @> '{"supported":false}'::jsonb
     or new.raw_payload @> '{"importedHistory":true}'::jsonb
     or coalesce(new.raw_payload->>'processingStatus','pending') not in ('pending','claude')
  then
    return new;
  end if;

  select secret into v_secret
  from private.ai_followup_config
  where id = true;

  if v_secret is null or v_secret !~ '^[a-f0-9]{64}$' then
    return new;
  end if;

  perform net.http_post(
    url := 'https://nailfzcujyxydqldktgg.supabase.co/functions/v1/instagram-audio-preprocess',
    body := jsonb_build_object('messageId', new.id),
    headers := jsonb_build_object(
      'Content-Type','application/json',
      'x-ai-followup-token',v_secret
    ),
    timeout_milliseconds := 55000
  );
  return new;
exception when others then
  return new;
end;
$function$
;


