-- Base congelada de ai_track_wait de 27/09/2026.
-- Mudança restrita a Instagram + modo claude + origemSync:true.
-- Preserva ecos reais (sem origemSync), modo ia e demais canais.
-- FUNCAO public.ai_track_wait
CREATE OR REPLACE FUNCTION public.ai_track_wait()
 RETURNS trigger
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
declare c public.ai_conversations; w public.ai_human_waits; inbound_time timestamptz; manual_time timestamptz; manual_active boolean; resumed_at timestamptz; quiet_worker boolean;
begin
 if coalesce((new.raw_payload->>'importedHistory')::boolean,false) then return new; end if;
 select * into c from public.ai_conversations where id=new.conversation_id for update;
 -- Sync recompõe histórico; não representa intervenção ao vivo da equipe.
 -- O registro em ai_messages e os demais gatilhos (incluindo prefetch) continuam.
 if c.channel='instagram' and atendimento.modo_atual()='claude'
    and coalesce(new.raw_payload->>'origemSync','false')='true'
 then return new; end if;
 if c.status='closed' then return new; end if;
 quiet_worker:=c.channel='instagram' and exists(select 1 from public.ai_settings where key='instagram_turn_policy' and value->>'enabled'='true' and value->>'workerFunction'='instagram-turn-worker-v6');
 select * into w from public.ai_human_waits where conversation_id=c.id for update;
 if new.direction='inbound' then
  inbound_time:=new.created_at;
  if w.last_human_at is not null and inbound_time<=w.last_human_at then return new; end if;
  if w.inbound_at is not null and inbound_time<w.inbound_at then return new; end if;
  select max(created_at) into manual_time from public.ai_messages
   where conversation_id=c.id and direction='outbound'
   and coalesce(raw_payload->>'importedHistory','false')<>'true' and coalesce(raw_payload->>'enviado','true')<>'false'
   and (raw_payload->>'origem' in ('whatsapp_business_app','conta_da_loja') or raw_payload->>'coexistence'='true');
  select greatest((c.metadata->>'aiResumedAt')::timestamptz,max(created_at)) into resumed_at from public.ai_messages
   where conversation_id=c.id and direction='outbound' and raw_payload->>'enviado'='true' and raw_payload->>'turn_complete'='true';
  manual_active:=manual_time is not null and (resumed_at is null or manual_time>resumed_at) and (c.channel<>'instagram' or not (exists(select 1 from public.ai_settings where key='instagram_turn_policy' and value->>'enabled'='true' and value->>'workerFunction'='instagram-turn-worker-v6')) or manual_time>=inbound_time-interval '10 minutes');
  if not manual_active and c.status='human' and coalesce(w.category,'')<>'human_request' and not(c.metadata ? 'aiProcessing') then
   -- Previous unanswered messages remain available to the team, never replayed.
   update public.ai_messages set raw_payload=coalesce(raw_payload,'{}'::jsonb)||'{"processingStatus":"human_wait","needsHuman":true}'::jsonb
    where conversation_id=c.id and id<>new.id and direction='inbound' and raw_payload->>'processingStatus'='pending';
   update public.ai_conversations set status='open' where id=c.id;
  end if;
  if manual_active then
   update public.ai_conversations set status='human',metadata=coalesce(metadata,'{}'::jsonb)||jsonb_build_object('manualEchoObservedAt',manual_time) where id=c.id;
  end if;
  insert into public.ai_human_waits(conversation_id,last_inbound_id,inbound_at,waiting_since,due_at,state,unread)
  values(c.id,new.id,inbound_time,inbound_time,case when manual_active then (case when quiet_worker then manual_time else inbound_time end)+interval '10 minutes' else null end,'waiting',true)
  on conflict(conversation_id) do update set last_inbound_id=excluded.last_inbound_id,inbound_at=excluded.inbound_at,
    waiting_since=case when not manual_active and coalesce(ai_human_waits.category,'')<>'human_request' then excluded.waiting_since when ai_human_waits.state in ('waiting','evaluating') then ai_human_waits.waiting_since else excluded.waiting_since end,
    due_at=case when not manual_active then null when quiet_worker then manual_time+interval '10 minutes' when ai_human_waits.state in ('waiting','evaluating') then ai_human_waits.waiting_since+interval '10 minutes' else excluded.due_at end,
    state=case when ai_human_waits.state='blocked' and ai_human_waits.category='human_request' then 'blocked' else 'waiting' end,
    category=case when not manual_active and coalesce(ai_human_waits.category,'')<>'human_request' then null else ai_human_waits.category end,
    reason=case when not manual_active and coalesce(ai_human_waits.category,'')<>'human_request' then null else ai_human_waits.reason end,
    last_human_at=greatest(ai_human_waits.last_human_at,manual_time),
    technical_attempts=0,generation=gen_random_uuid(),unread=true,updated_at=now();
  -- A new customer message invalidates an in-flight automatic fallback.
  if c.metadata ? 'aiFollowup' then update public.ai_conversations set status=case when manual_active then 'human' else 'open' end where id=c.id; end if;
 elsif new.direction='outbound' and (new.raw_payload->>'origem' in ('whatsapp_business_app','conta_da_loja') or new.raw_payload->>'coexistence'='true') then
  if w.last_inbound_id is null or new.created_at>=w.inbound_at then
   update public.ai_conversations set status='human',metadata=(coalesce(metadata,'{}'::jsonb)-'aiProcessing'-'aiFollowup')||jsonb_build_object('manualEchoObservedAt',now()) where id=c.id;
  else
   update public.ai_conversations set metadata=coalesce(metadata,'{}'::jsonb)||jsonb_build_object('manualEchoObservedAt',now()) where id=c.id;
  end if;
  update public.ai_human_waits set state=case when inbound_at<=new.created_at then 'answered' else state end,
    due_at=case when inbound_at<=new.created_at then null else due_at end,
    unread=case when inbound_at<=new.created_at then false else unread end,
    last_human_at=greatest(last_human_at,new.created_at),generation=case when inbound_at<=new.created_at then gen_random_uuid() else generation end,updated_at=now() where conversation_id=c.id;
  update public.ai_messages set raw_payload=coalesce(raw_payload,'{}'::jsonb)||'{"processingStatus":"human_answered"}'::jsonb
    where conversation_id=c.id and direction='inbound' and created_at<=new.created_at and raw_payload->>'processingStatus' in ('pending','processing','human_wait');
 end if;
 return new;
end $function$
;
