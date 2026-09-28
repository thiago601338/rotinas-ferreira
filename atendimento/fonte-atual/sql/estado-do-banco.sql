-- Estado do banco nailfzcujyxydqldktgg em 27/09/2026 (somente consulta)
-- FUNCAO public.ai_recover_followups
CREATE OR REPLACE FUNCTION public.ai_recover_followups()
 RETURNS integer
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
declare c public.ai_conversations; w public.ai_human_waits; owner uuid; total integer:=0; retried boolean;
begin
 for c in select * from public.ai_conversations where (metadata ? 'aiProcessing' and (metadata->'aiProcessing'->>'expiresAt')::timestamptz<now()) or (metadata ? 'aiFollowup' and not(metadata ? 'aiProcessing') and coalesce((metadata->'aiFollowup'->>'startedAt')::timestamptz,updated_at)<now()-interval '180 seconds') for update skip locked loop
  owner:=coalesce(c.metadata->'aiProcessing'->>'owner',c.metadata->'aiFollowup'->>'owner')::uuid;
  select * into w from public.ai_human_waits where conversation_id=c.id for update;
  if c.metadata->'aiProcessing'->>'lastInboundId' is not null and c.metadata->'aiProcessing'->>'lastInboundId'<>w.last_inbound_id::text then
   update public.ai_messages set raw_payload=raw_payload||'{"processingStatus":"superseded"}'::jsonb where conversation_id=c.id and direction='inbound' and raw_payload->>'processingStatus'='processing';
   update public.ai_conversations set metadata=metadata-'aiProcessing'-'aiFollowup'-'aiSendAttempt' where id=c.id;
   total:=total+1;continue;
  end if;
  if exists(select 1 from public.ai_messages where conversation_id=c.id and direction='outbound' and raw_payload->>'turnId'=owner::text and raw_payload->>'turn_complete'='true' and raw_payload->>'enviado'='true') then
   perform public.ai_wait_finish(c.id,w.last_inbound_id,'answered',null,null,'v6.3');
   update public.ai_messages set raw_payload=raw_payload||'{"processingStatus":"done"}'::jsonb where conversation_id=c.id and direction='inbound' and raw_payload->>'processingStatus'='processing';
   update public.ai_conversations set status=case when status='closed' then 'closed' else 'open' end,metadata=(metadata-'aiProcessing'-'aiFollowup'-'aiSendAttempt')||jsonb_build_object('aiResumedAt',now()) where id=c.id;
   total:=total+1;continue;
  end if;
  retried:=false;
  if c.metadata->'aiProcessing'->>'recoverySafe'='true' then retried:=public.ai_retry_turn(c.id,w.last_inbound_id,owner,'Processamento interrompido antes do envio; nova tentativa limitada.'); end if;
  if not retried and w.state in ('waiting','evaluating') then
   perform public.ai_wait_finish(c.id,w.last_inbound_id,'blocked','technical','Envio parcial ou resultado incerto; conferir antes de repetir.','v6.3');
   update public.ai_messages set raw_payload=raw_payload||'{"processingStatus":"human_wait","needsHuman":true}'::jsonb where conversation_id=c.id and direction='inbound' and raw_payload->>'processingStatus'='processing';
  end if;
  update public.ai_conversations set metadata=metadata-'aiProcessing'-'aiFollowup'-'aiSendAttempt' where id=c.id;
  total:=total+1;
 end loop;
 return total;
end $function$
;

-- FUNCAO public.ai_followup_valid
CREATE OR REPLACE FUNCTION public.ai_followup_valid(p_token text)
 RETURNS boolean
 LANGUAGE sql
 SET search_path TO ''
AS $function$
 select exists(select 1 from private.ai_followup_config where secret=p_token and length(p_token)=64)
$function$
;

-- FUNCAO public.ferreira_text_key
CREATE OR REPLACE FUNCTION public.ferreira_text_key(value text)
 RETURNS text
 LANGUAGE sql
 IMMUTABLE
AS $function$
  select trim(regexp_replace(lower(unaccent(coalesce(value, ''))), '[^a-z0-9]+', ' ', 'g'));
$function$
;

-- FUNCAO public.ferreira_phone_key
CREATE OR REPLACE FUNCTION public.ferreira_phone_key(value text)
 RETURNS text
 LANGUAGE plpgsql
 IMMUTABLE
AS $function$
declare
  digits text;
begin
  digits := regexp_replace(coalesce(value, ''), '\\D', '', 'g');
  if length(digits) > 11 and left(digits, 2) = '55' then
    digits := substr(digits, 3);
  end if;
  return digits;
end;
$function$
;

-- FUNCAO public.ferreira_color_display
CREATE OR REPLACE FUNCTION public.ferreira_color_display(value text)
 RETURNS text
 LANGUAGE sql
 IMMUTABLE
AS $function$
  select upper(trim(regexp_replace(replace(replace(coalesce(value, ''), '-', ' '), '_', ' '), '\\s+', ' ', 'g')));
$function$
;

-- FUNCAO public.ferreira_prepare_customer
CREATE OR REPLACE FUNCTION public.ferreira_prepare_customer()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
begin
  new.full_name := trim(regexp_replace(coalesce(new.full_name, ''), '\\s+', ' ', 'g'));
  new.phone := trim(coalesce(new.phone, ''));
  new.name_key := public.ferreira_text_key(new.full_name);
  new.phone_key := public.ferreira_phone_key(new.phone);
  return new;
end;
$function$
;

-- FUNCAO public.ferreira_prepare_color
CREATE OR REPLACE FUNCTION public.ferreira_prepare_color()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
begin
  new.color := public.ferreira_color_display(new.color);
  return new;
end;
$function$
;

-- FUNCAO public.ai_color_key
CREATE OR REPLACE FUNCTION public.ai_color_key(value text)
 RETURNS text
 LANGUAGE sql
 IMMUTABLE
 SET search_path TO 'public'
AS $function$
  select case public.ferreira_text_key(value)
    -- variações e erro de digitação observados na base
    when 'branca'         then 'branco'
    when 'braco'          then 'branco'
    when 'preta'          then 'preto'
    when 'azul serenite'  then 'azul serenity'
    when 'vermelha'       then 'vermelho'
    when 'amarela'        then 'amarelo'
    when 'cafe'           then 'marrom'
    else public.ferreira_text_key(value)
  end;
$function$
;

-- FUNCAO public.ai_size_key
CREATE OR REPLACE FUNCTION public.ai_size_key(value text)
 RETURNS text
 LANGUAGE sql
 IMMUTABLE
 SET search_path TO 'public'
AS $function$
  select case public.ferreira_text_key(value)
    when 'unico'   then 'u'
    when 'un'      then 'u'
    when 'tamanho unico' then 'u'
    when 'pp'      then 'pp'
    when 'p'       then 'p'
    when 'm'       then 'm'
    when 'g'       then 'g'
    when 'gg'      then 'gg'
    else public.ferreira_text_key(value)
  end;
$function$
;

-- FUNCAO public.ai_search_products
CREATE OR REPLACE FUNCTION public.ai_search_products(p_terms text[] DEFAULT '{}'::text[], p_color text DEFAULT NULL::text, p_size text DEFAULT NULL::text, p_limit integer DEFAULT 8)
 RETURNS TABLE(id uuid, name text, sku text, category text, fabric text, sale_price numeric, photo_url text, score numeric, total_stock bigint, variations jsonb, matched_stock bigint)
 LANGUAGE sql
 STABLE
 SET search_path TO 'public'
AS $function$
  with terms as (
    select distinct public.ferreira_text_key(t) as t
    from unnest(coalesce(p_terms, '{}')) as t
    where length(public.ferreira_text_key(t)) >= 3
  ),
  want as (
    select
      nullif(public.ai_color_key(p_color), '') as color_key,
      nullif(public.ai_size_key(p_size), '')   as size_key
  ),
  base as (
    select
      p.id, p.name, p.sku, p.category, p.fabric, p.sale_price, p.photo_url,
      -- Pontuação simples e auditável: sku exato pesa mais que nome,
      -- que pesa mais que categoria, que pesa mais que tecido.
      coalesce((
        select sum(
          case
            when public.ferreira_text_key(p.sku)  = t.t then 10
            when public.ferreira_text_key(p.name) like '%' || t.t || '%' then 3
            when public.ferreira_text_key(p.category) like '%' || t.t || '%' then 2
            when public.ferreira_text_key(p.fabric)   like '%' || t.t || '%' then 1
            else 0
          end
        )
        from terms t
      ), 0)::numeric as score
    from public.products p
    -- status real do catálogo é 'Ativo', não 'active'
    where public.ferreira_text_key(p.status) = 'ativo'
  ),
  filtered as (
    select b.*
    from base b, want w
    where
      -- sem termos => catálogo geral (usado pela busca por cor/tamanho puro)
      ((select count(*) from terms) = 0 or b.score > 0)
      -- se a cliente citou cor, o produto precisa ter alguma variação nessa cor
      and (
        w.color_key is null
        or exists (
          select 1 from public.product_variations v
          where v.product_id = b.id
            and public.ai_color_key(v.color) like '%' || w.color_key || '%'
        )
      )
      -- idem para tamanho
      and (
        w.size_key is null
        or exists (
          select 1 from public.product_variations v
          where v.product_id = b.id
            and public.ai_size_key(v.size) = w.size_key
        )
      )
  )
  select
    f.id, f.name, f.sku, f.category, f.fabric, f.sale_price, f.photo_url,
    f.score,
    coalesce((
      select sum(greatest(v.stock, 0))
      from public.product_variations v where v.product_id = f.id
    ), 0)::bigint as total_stock,
    coalesce((
      select jsonb_agg(jsonb_build_object(
               'id', v.id, 'size', v.size, 'color', v.color, 'stock', v.stock
             ) order by v.color, v.size)
      from public.product_variations v where v.product_id = f.id
    ), '[]'::jsonb) as variations,
    -- Estoque da combinação exata pedida. NULL = cliente não especificou.
    (
      select case when w.color_key is null and w.size_key is null then null
             else coalesce(sum(greatest(v.stock, 0)), 0)
             end
      from public.product_variations v
      where v.product_id = f.id
        and (w.color_key is null
             or public.ai_color_key(v.color) like '%' || w.color_key || '%')
        and (w.size_key is null
             or public.ai_size_key(v.size) = w.size_key)
    )::bigint as matched_stock
  from filtered f, want w
  order by f.score desc, total_stock desc, f.name
  limit greatest(1, least(coalesce(p_limit, 8), 25));
$function$
;

-- FUNCAO public.ai_photo_manifest_v4
CREATE OR REPLACE FUNCTION public.ai_photo_manifest_v4()
 RETURNS TABLE(product_id uuid, photo_ref text, etag text, byte_size bigint)
 LANGUAGE sql
 STABLE
 SET search_path TO ''
AS $function$ select p.id, p.photo_url, trim(both '"' from o.metadata->>'eTag'), case when (o.metadata->>'size') ~ '^[0-9]+$' then (o.metadata->>'size')::bigint else null end from public.products p left join storage.objects o on o.bucket_id='product-photos' and o.name=p.photo_url where lower(p.status)='ativo' and nullif(p.photo_url,'') is not null $function$
;

-- FUNCAO public.ai_release_turn
CREATE OR REPLACE FUNCTION public.ai_release_turn(p_conversation uuid, p_owner uuid, p_context jsonb, p_commit boolean)
 RETURNS boolean
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
begin
  update public.ai_conversations set metadata=(coalesce(metadata,'{}'::jsonb)-'aiProcessing') || case when p_commit then jsonb_build_object('aiContext',p_context) else '{}'::jsonb end,updated_at=now()
  where id=p_conversation and metadata->'aiProcessing'->>'owner'=p_owner::text;
  return found;
end;$function$
;

-- FUNCAO public.ai_wait_finish
CREATE OR REPLACE FUNCTION public.ai_wait_finish(p_conversation uuid, p_last_inbound uuid, p_state text, p_category text, p_reason text, p_revision text)
 RETURNS boolean
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
begin
 if p_state not in ('blocked','answered') then return false; end if;
 update public.ai_human_waits set state=p_state,unread=(p_state='blocked'),due_at=null,category=p_category,reason=left(p_reason,500),policy_revision=p_revision,updated_at=now()
 where conversation_id=p_conversation and last_inbound_id=p_last_inbound and state in ('waiting','evaluating','blocked') and (p_state='blocked' or state in ('waiting','evaluating'));
 return found;
end $function$
;

-- FUNCAO public.ai_operator_wait
CREATE OR REPLACE FUNCTION public.ai_operator_wait(p_conversation uuid, p_generation uuid, p_action text)
 RETURNS boolean
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
declare w public.ai_human_waits;
begin
 if p_action not in ('resolved','human_only') then return false; end if;
 perform 1 from public.ai_conversations where id=p_conversation for update;
 select * into w from public.ai_human_waits where conversation_id=p_conversation for update;
 if not found or w.generation<>p_generation or w.state='answered' then return false; end if;
 update public.ai_conversations set status='human',metadata=coalesce(metadata,'{}'::jsonb)-'aiProcessing'-'aiFollowup' where id=p_conversation;
 update public.ai_human_waits set state=case when p_action='resolved' then 'answered' else 'blocked' end,
   unread=(p_action<>'resolved'),due_at=null,category=case when p_action='resolved' then null else 'human_request' end,
   reason=case when p_action='resolved' then null else 'Atendente manteve este pedido sob atendimento humano.' end,
   last_human_at=case when p_action='resolved' then now() else last_human_at end,generation=gen_random_uuid(),updated_at=now() where conversation_id=p_conversation;
 if p_action='resolved' then
  update public.ai_messages set raw_payload=coalesce(raw_payload,'{}'::jsonb)||'{"processingStatus":"human_answered"}'::jsonb where conversation_id=p_conversation and direction='inbound' and created_at<=w.inbound_at and raw_payload->>'processingStatus' in ('pending','processing','human_wait');
 end if;
 return true;
end $function$
;

-- FUNCAO public.ai_delivery_allowed
CREATE OR REPLACE FUNCTION public.ai_delivery_allowed(p_conversation uuid, p_last_inbound uuid, p_owner uuid)
 RETURNS boolean
 LANGUAGE sql
 SET search_path TO ''
AS $function$
 select exists(select 1 from public.ai_conversations c join public.ai_human_waits w on w.conversation_id=c.id
 where c.id=p_conversation and c.status='open' and c.metadata->'aiProcessing'->>'owner'=p_owner::text
 and (c.metadata->'aiProcessing'->>'expiresAt')::timestamptz>now()
 and not exists(select 1 from public.ai_instagram_turn_queue q where q.conversation_id=c.id and (q.last_inbound_id<>p_last_inbound or q.due_at>clock_timestamp()))
 and (c.channel<>'instagram' or not exists(select 1 from public.ai_settings where key='instagram_turn_policy' and value->>'enabled'='true' and value->>'workerFunction'='instagram-turn-worker-v6')
   or not exists(select 1 from public.ai_messages hm where hm.conversation_id=c.id and hm.direction='outbound'
     and hm.created_at>clock_timestamp()-interval '10 minutes'
     and coalesce(hm.raw_payload->>'importedHistory','false')<>'true'
     and coalesce(hm.raw_payload->>'enviado','true')<>'false'
     and (hm.raw_payload->>'origem' in ('conta_da_loja','whatsapp_business_app') or hm.raw_payload->>'coexistence'='true')))
 and w.last_inbound_id=p_last_inbound and w.state in ('waiting','evaluating')
 and (w.last_human_at is null or w.last_human_at<w.inbound_at)
 and not exists(select 1 from public.ai_optouts o where o.channel=c.channel and o.external_user_id=c.external_user_id));
$function$
;

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

-- FUNCAO public.ai_acquire_turn
CREATE OR REPLACE FUNCTION public.ai_acquire_turn(p_conversation uuid, p_owner uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
declare c public.ai_conversations; lease jsonb;
begin
  select * into c from public.ai_conversations where id=p_conversation for update;
  if not found then return jsonb_build_object('status','missing'); end if;
  if c.status in ('human','closed') then return jsonb_build_object('status',c.status); end if;
  
  if c.channel='instagram' and exists(select 1 from public.ai_instagram_turn_queue q where q.conversation_id=c.id) then
   if not exists(select 1 from public.ai_instagram_turn_queue q join public.ai_human_waits w on w.conversation_id=q.conversation_id where q.conversation_id=c.id and q.last_inbound_id=w.last_inbound_id and q.state='ready' and q.due_at<=clock_timestamp() and q.not_before<=clock_timestamp() and (w.due_at is null or w.due_at<=now())) then
    return jsonb_build_object('status','debounced');
   end if;
  end if;
  if c.channel='instagram' and exists(select 1 from public.ai_settings where key='instagram_turn_policy' and value->>'enabled'='true' and value->>'workerFunction'='instagram-turn-worker-v6') then return jsonb_build_object('status','debounced'); end if;
  lease:=c.metadata->'aiProcessing';
  if lease is not null then
    if (lease->>'expiresAt')::timestamptz>now() then return jsonb_build_object('status','busy'); end if;
    return jsonb_build_object('status','interrupted');
  end if;
  update public.ai_conversations set metadata=coalesce(metadata,'{}'::jsonb)||jsonb_build_object('aiProcessing',jsonb_build_object('owner',p_owner,'expiresAt',now()+interval '180 seconds','recoverySafe',true,'lastInboundId',(select last_inbound_id from public.ai_human_waits where conversation_id=c.id))) where id=c.id;
  return jsonb_build_object('status','acquired','conversation',to_jsonb(c));
end;$function$
;

-- FUNCAO public.ai_finish_followup
CREATE OR REPLACE FUNCTION public.ai_finish_followup(p_conversation uuid, p_owner uuid)
 RETURNS boolean
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
declare c public.ai_conversations; w public.ai_human_waits;
begin
 select * into c from public.ai_conversations where id=p_conversation for update;
 if c.metadata->'aiFollowup'->>'owner' is distinct from p_owner::text then return false; end if;
 select * into w from public.ai_human_waits where conversation_id=c.id for update;
 update public.ai_conversations set status=case when status='closed' then 'closed' when w.state='answered' then 'open' else status end,
 metadata=(metadata-'aiFollowup'-'aiProcessing'-'aiSendAttempt')||case when w.state='answered' then jsonb_build_object('aiResumedAt',now()) else '{}'::jsonb end,updated_at=now() where id=c.id;
 if w.state='evaluating' then
  perform public.ai_wait_finish(c.id,w.last_inbound_id,'blocked','unclear','Processamento interrompido; conferir mensagens enviadas.','v6.3');
 end if;
 return true;
end $function$
;

-- FUNCAO public.ai_begin_send
CREATE OR REPLACE FUNCTION public.ai_begin_send(p_conversation uuid, p_last_inbound uuid, p_owner uuid, p_part integer)
 RETURNS boolean
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
begin
 perform 1 from public.ai_conversations where id=p_conversation for update;
 if not public.ai_delivery_allowed(p_conversation,p_last_inbound,p_owner) then return false; end if;
 update public.ai_conversations set metadata=metadata||jsonb_build_object('aiSendAttempt',jsonb_build_object('owner',p_owner,'part',p_part,'startedAt',now())) where id=p_conversation;
 return true;
end $function$
;

-- FUNCAO public.ai_retry_turn
CREATE OR REPLACE FUNCTION public.ai_retry_turn(p_conversation uuid, p_last_inbound uuid, p_owner uuid, p_reason text)
 RETURNS boolean
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
declare c public.ai_conversations; w public.ai_human_waits;
begin
 select * into c from public.ai_conversations where id=p_conversation for update;
 if c.status<>'open' or c.metadata->'aiProcessing'->>'owner' is distinct from p_owner::text or c.metadata ? 'aiSendAttempt' then return false; end if;
 select * into w from public.ai_human_waits where conversation_id=c.id for update;
 if w.last_inbound_id<>p_last_inbound or w.state not in ('waiting','evaluating') or w.technical_attempts>=2 then return false; end if;
 if exists(select 1 from public.ai_messages where conversation_id=c.id and direction='outbound' and raw_payload->>'turnId'=p_owner::text and raw_payload->>'enviado'='true') then return false; end if;
 update public.ai_human_waits set state='waiting',due_at=now()+interval '20 seconds',technical_attempts=technical_attempts+1,category='technical',reason=left(p_reason,300),updated_at=now() where conversation_id=c.id;
 update public.ai_messages set raw_payload=raw_payload||'{"processingStatus":"pending"}'::jsonb where conversation_id=c.id and direction='inbound' and raw_payload->>'processingStatus'='processing';
 return true;
end $function$
;

-- FUNCAO public.ai_end_send
CREATE OR REPLACE FUNCTION public.ai_end_send(p_conversation uuid, p_owner uuid, p_part integer)
 RETURNS boolean
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
begin
 update public.ai_conversations set metadata=metadata-'aiSendAttempt' where id=p_conversation and metadata->'aiSendAttempt'->>'owner'=p_owner::text and metadata->'aiSendAttempt'->>'part'=p_part::text;
 return found;
end $function$
;

-- FUNCAO public.ai_hold_turn
CREATE OR REPLACE FUNCTION public.ai_hold_turn(p_conversation uuid, p_last_inbound uuid, p_owner uuid, p_category text, p_reason text, p_revision text)
 RETURNS boolean
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
declare c public.ai_conversations; w public.ai_human_waits;
begin
 select * into c from public.ai_conversations where id=p_conversation for update;
 if not found or c.channel<>'instagram' or c.status<>'open' or c.metadata->'aiProcessing'->>'owner' is distinct from p_owner::text then return false; end if;
 select * into w from public.ai_human_waits where conversation_id=c.id for update;
 if w.last_inbound_id is distinct from p_last_inbound or w.state not in ('waiting','evaluating') then return false; end if;
 if not public.ai_wait_finish(c.id,p_last_inbound,'blocked',p_category,left(p_reason,300),p_revision) then return false; end if;
 update public.ai_conversations set status='human',updated_at=now() where id=c.id;
 insert into public.ai_handoffs(conversation_id,reason,status)
 select c.id,left(p_reason,500),'open' where not exists(select 1 from public.ai_handoffs where conversation_id=c.id and status='open');
 return true;
end $function$
;

-- FUNCAO public.ai_ig_track_quiet
CREATE OR REPLACE FUNCTION public.ai_ig_track_quiet()
 RETURNS trigger
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
declare c public.ai_conversations; w public.ai_human_waits; receipt timestamptz:=clock_timestamp();
begin
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

-- FUNCAO public.ai_ig_finish_turn
CREATE OR REPLACE FUNCTION public.ai_ig_finish_turn(p_conversation uuid, p_last_inbound uuid, p_owner uuid, p_mode text, p_ids uuid[], p_context jsonb DEFAULT NULL::jsonb, p_reason text DEFAULT NULL::text)
 RETURNS boolean
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
declare c public.ai_conversations; w public.ai_human_waits; q public.ai_instagram_turn_queue;
begin
 if p_mode not in ('done','ready','retry','blocked') then raise exception 'invalid_finish_mode'; end if;
 select * into c from public.ai_conversations where id=p_conversation for update;
 if c.channel<>'instagram' or c.status<>'open' or c.metadata->'aiProcessing'->>'owner' is distinct from p_owner::text then return false; end if;
 select * into w from public.ai_human_waits where conversation_id=c.id for update;
 select * into q from public.ai_instagram_turn_queue where conversation_id=c.id for update;
 if w.last_inbound_id is distinct from p_last_inbound or q.last_inbound_id is distinct from p_last_inbound or q.owner is distinct from p_owner then return false; end if;
 if p_mode in ('ready','retry') and (c.metadata ? 'aiSendAttempt' or exists(select 1 from public.ai_messages where conversation_id=c.id and direction='outbound' and raw_payload->>'turnId'=p_owner::text and raw_payload->>'enviado'='true')) then raise exception 'cannot_retry_sent_turn'; end if;
 if p_mode='retry' and q.attempts>=2 then p_mode:='blocked'; end if;
 if p_mode='done' then
  if not exists(select 1 from public.ai_messages where conversation_id=c.id and direction='outbound' and raw_payload->>'turnId'=p_owner::text and raw_payload->>'enviado'='true' and raw_payload->>'turn_complete'='true') then raise exception 'completed_turn_not_sent'; end if;
  perform public.ai_wait_finish(c.id,p_last_inbound,'answered',null,null,'instagram-quiet60-preferences-20260911-r1');
 elsif p_mode='blocked' then
  perform public.ai_hold_turn(c.id,p_last_inbound,p_owner,'unclear',coalesce(p_reason,'O atendimento precisa ser conferido pela equipe.'),'instagram-quiet60-preferences-20260911-r1');
 else
  update public.ai_human_waits set state='waiting',due_at=case when p_mode='retry' then now()+interval '20 seconds' else null end,updated_at=now() where conversation_id=c.id;
 end if;
 update public.ai_messages set raw_payload=coalesce(raw_payload,'{}'::jsonb)||jsonb_build_object('processingStatus',case when p_mode='done' then 'done' when p_mode='blocked' then 'human_wait' else 'pending' end) where conversation_id=c.id and direction='inbound' and id=any(p_ids) and raw_payload->>'processingStatus' in ('pending','processing');
 update public.ai_instagram_turn_queue set state=case when p_mode='retry' then 'queued' else p_mode end,not_before=case when p_mode='retry' then now()+interval '20 seconds' else due_at end,owner=null,lease_until=null,updated_at=now() where conversation_id=c.id;
 update public.ai_conversations set metadata=(coalesce(metadata,'{}'::jsonb)-'aiProcessing'-'aiSendAttempt')||case when p_mode='done' then jsonb_build_object('aiContext',p_context,'aiResumedAt',now()) else '{}'::jsonb end,updated_at=now(),last_message_at=case when p_mode='done' then now() else last_message_at end where id=c.id;
 return true;
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

-- FUNCAO public.ai_ig_cancel_stale
CREATE OR REPLACE FUNCTION public.ai_ig_cancel_stale(p_conversation uuid, p_last_inbound uuid, p_owner uuid, p_ids uuid[])
 RETURNS boolean
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
declare c public.ai_conversations; w public.ai_human_waits;
begin
 select * into c from public.ai_conversations where id=p_conversation for update;
 if not found or c.channel<>'instagram' or c.status<>'open' or c.metadata->'aiProcessing'->>'owner' is distinct from p_owner::text then return false; end if;
 select * into w from public.ai_human_waits where conversation_id=c.id for update;
 if not found or w.last_inbound_id is not distinct from p_last_inbound then return false; end if;
 if c.metadata ? 'aiSendAttempt' then
  perform public.ai_hold_turn(c.id,w.last_inbound_id,p_owner,'technical','Envio anterior incerto; conferir antes de repetir.','instagram-reviewed150-20260911-r3');
  update public.ai_instagram_turn_queue set state='blocked',owner=null,lease_until=null,updated_at=now() where conversation_id=c.id;
 end if;
 update public.ai_messages set raw_payload=coalesce(raw_payload,'{}'::jsonb)||'{"processingStatus":"superseded"}'::jsonb where conversation_id=c.id and id=any(p_ids) and direction='inbound' and raw_payload->>'processingStatus'='processing';
 return true;
end $function$
;

-- FUNCAO public.ai_ig_finish_turn_v5
CREATE OR REPLACE FUNCTION public.ai_ig_finish_turn_v5(p_conversation uuid, p_last_inbound uuid, p_owner uuid, p_mode text, p_ids uuid[], p_context jsonb DEFAULT NULL::jsonb, p_reason text DEFAULT NULL::text, p_category text DEFAULT 'unclear'::text)
 RETURNS boolean
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
declare c public.ai_conversations; w public.ai_human_waits; q public.ai_instagram_turn_queue; revision text:='instagram-story-brand-20260911-r5';
begin
 if p_mode not in ('done','retry','blocked') then raise exception 'invalid_finish_mode'; end if;
 select * into c from public.ai_conversations where id=p_conversation for update;
 if not found or c.channel<>'instagram' or c.status<>'open' or c.metadata->'aiProcessing'->>'owner' is distinct from p_owner::text then return false; end if;
 select * into w from public.ai_human_waits where conversation_id=c.id for update;
 if not found or w.state not in ('waiting','evaluating') or w.last_inbound_id is distinct from p_last_inbound then return false; end if;
 select * into q from public.ai_instagram_turn_queue where conversation_id=c.id for update;
 if not found or q.last_inbound_id is distinct from p_last_inbound or q.owner is distinct from p_owner or q.state<>'preflight' then return false; end if;
 if p_mode='retry' and (c.metadata ? 'aiSendAttempt' or exists(select 1 from public.ai_messages where conversation_id=c.id and direction='outbound' and raw_payload->>'turnId'=p_owner::text and raw_payload->>'enviado'='true')) then
  p_mode:='blocked'; p_category:='technical'; p_reason:='Envio parcial ou incerto; conferir antes de repetir.';
 end if;
 if p_mode='retry' and q.attempts>=2 then p_mode:='blocked'; p_category:='technical'; end if;
 if p_category is null or p_category not in ('technical','unclear','missing_fact','delivery','payment','reservation','order_change','return_exchange','negotiation','personal_data','human_request') then p_category:='unclear'; end if;
 if p_mode='done' then
  if c.metadata ? 'aiSendAttempt' or not exists(select 1 from public.ai_messages where conversation_id=c.id and direction='outbound' and raw_payload->>'turnId'=p_owner::text and raw_payload->>'enviado'='true' and raw_payload->>'turn_complete'='true') then raise exception 'completed_turn_not_sent'; end if;
  if not public.ai_wait_finish(c.id,p_last_inbound,'answered',null,null,revision) then return false; end if;
 elsif p_mode='blocked' then
  if not public.ai_hold_turn(c.id,p_last_inbound,p_owner,p_category,coalesce(p_reason,'O atendimento precisa ser conferido pela equipe.'),revision) then return false; end if;
 else
  update public.ai_human_waits set state='waiting',due_at=now()+interval '20 seconds',updated_at=now() where conversation_id=c.id;
 end if;
 update public.ai_messages set raw_payload=coalesce(raw_payload,'{}'::jsonb)||jsonb_build_object('processingStatus',case when p_mode='done' then 'done' when p_mode='blocked' then 'human_wait' else 'pending' end)
 where conversation_id=c.id and direction='inbound' and id=any(p_ids) and raw_payload->>'processingStatus' in ('pending','processing');
 update public.ai_instagram_turn_queue set state=case when p_mode='retry' then 'queued' else p_mode end,not_before=case when p_mode='retry' then now()+interval '20 seconds' else due_at end,owner=null,lease_until=null,updated_at=now() where conversation_id=c.id;
 update public.ai_conversations set metadata=(coalesce(metadata,'{}'::jsonb)-'aiProcessing'-'aiSendAttempt')||case when p_mode='done' then jsonb_build_object('aiContext',p_context,'aiResumedAt',now()) else '{}'::jsonb end,updated_at=now(),last_message_at=case when p_mode='done' then now() else last_message_at end where id=c.id;
 return true;
end $function$
;

-- FUNCAO public.ai_ig_claim_reference_recovery
CREATE OR REPLACE FUNCTION public.ai_ig_claim_reference_recovery(p_conversation uuid, p_last_inbound uuid, p_generation uuid, p_owner uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
declare c public.ai_conversations; w public.ai_human_waits; q public.ai_instagram_turn_queue;
begin
 select * into c from public.ai_conversations where id=p_conversation for update;
 if not found or c.channel<>'instagram' or c.status='closed' or c.metadata ? 'aiProcessing' or c.metadata ? 'aiSendAttempt' then return null; end if;
 select * into w from public.ai_human_waits where conversation_id=c.id for update;
 if not found or w.last_inbound_id<>p_last_inbound or w.generation<>p_generation or w.state<>'blocked' or coalesce(w.category,'') not in ('unclear','missing_fact') or w.inbound_at<now()-interval '24 hours' or w.last_human_at>=w.inbound_at then return null; end if;
 if exists(select 1 from public.ai_optouts where channel=c.channel and external_user_id=c.external_user_id) or exists(select 1 from public.ai_messages where conversation_id=c.id and direction='inbound' and created_at>w.inbound_at) or exists(select 1 from public.ai_messages where conversation_id=c.id and direction='outbound' and created_at>=w.waiting_since) then return null; end if;
 select * into q from public.ai_instagram_turn_queue where conversation_id=c.id for update;
 if not found or q.last_inbound_id<>p_last_inbound or q.due_at>clock_timestamp() or q.state not in ('ready','blocked') then return null; end if;
 update public.ai_human_waits set state='evaluating',updated_at=now() where conversation_id=c.id;
 update public.ai_instagram_turn_queue set state='preflight',owner=p_owner,lease_until=now()+interval '180 seconds',updated_at=now() where conversation_id=c.id;
 update public.ai_conversations set status='open',metadata=(metadata-'aiFollowup')||jsonb_build_object('aiProcessing',jsonb_build_object('owner',p_owner,'expiresAt',now()+interval '180 seconds','lastInboundId',p_last_inbound,'recoverySafe',false,'worker','verified-reference-recovery')),updated_at=now() where id=c.id returning * into c;
 return jsonb_build_object('conversation',to_jsonb(c),'lastInboundId',p_last_inbound,'inboundAt',w.inbound_at,'generation',w.generation);
end $function$
;

-- FUNCAO public.ai_ig_finish_reference_recovery
CREATE OR REPLACE FUNCTION public.ai_ig_finish_reference_recovery(p_conversation uuid, p_last_inbound uuid, p_owner uuid, p_answered_ids uuid[], p_pending_ids uuid[])
 RETURNS boolean
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
declare c public.ai_conversations; w public.ai_human_waits; q public.ai_instagram_turn_queue; item uuid; reason text:='Uma referência visual deste pedido ainda precisa ser identificada pela equipe; as demais perguntas de tamanho já foram respondidas.';
begin
 if coalesce(cardinality(p_answered_ids),0)<1 or cardinality(p_answered_ids)>6 or coalesce(cardinality(p_pending_ids),0)<1 or cardinality(p_pending_ids)>6 or p_answered_ids && p_pending_ids then return false; end if;
 select * into c from public.ai_conversations where id=p_conversation for update;
 if not found or c.status<>'open' or c.channel<>'instagram' or c.metadata->'aiProcessing'->>'owner' is distinct from p_owner::text or c.metadata ? 'aiSendAttempt' then return false; end if;
 select * into w from public.ai_human_waits where conversation_id=c.id for update;
 select * into q from public.ai_instagram_turn_queue where conversation_id=c.id for update;
 if w.last_inbound_id is distinct from p_last_inbound or q.owner is distinct from p_owner or q.state<>'preflight' then return false; end if;
 foreach item in array (p_answered_ids||p_pending_ids) loop
  if not exists(select 1 from public.ai_messages where id=item and conversation_id=c.id and direction='inbound') then return false; end if;
 end loop;
 foreach item in array p_answered_ids loop
  if not exists(select 1 from public.ai_messages where conversation_id=c.id and direction='outbound' and raw_payload->>'turnId'=p_owner::text and raw_payload->>'recoveredInboundId'=item::text and raw_payload->>'enviado'='true') then return false; end if;
 end loop;
 if not public.ai_hold_turn(c.id,p_last_inbound,p_owner,'unclear',reason,'instagram-reference-recovery-20260911-r6') then return false; end if;
 update public.ai_messages set raw_payload=(coalesce(raw_payload,'{}'::jsonb)-'needsHuman')||jsonb_build_object('processingStatus','done','referenceRecoveryRevision','instagram-reference-recovery-20260911-r6') where conversation_id=c.id and id=any(p_answered_ids) and raw_payload->>'processingStatus' not in ('human_answered','done');
 update public.ai_messages set raw_payload=coalesce(raw_payload,'{}'::jsonb)||jsonb_build_object('processingStatus','human_wait','needsHuman',true,'referenceRecoveryRevision','instagram-reference-recovery-20260911-r6') where conversation_id=c.id and id=any(p_pending_ids) and raw_payload->>'processingStatus'<>'human_answered';
 update public.ai_instagram_turn_queue set state='blocked',owner=null,lease_until=null,updated_at=now() where conversation_id=c.id;
 update public.ai_conversations set metadata=metadata-'aiProcessing'-'aiSendAttempt'-'aiFollowup',updated_at=now(),last_message_at=now() where id=c.id;
 return true;
end $function$
;

-- FUNCAO public.ai_meta_token_store
CREATE OR REPLACE FUNCTION public.ai_meta_token_store(p_token text, p_source text, p_expires_at timestamp with time zone DEFAULT NULL::timestamp with time zone, p_metadata jsonb DEFAULT '{}'::jsonb)
 RETURNS boolean
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
begin
  if p_token is null or length(p_token)<40 or length(p_token)>4096 then return false; end if;
  if p_source is null or length(p_source)>80 then return false; end if;
  insert into private.instagram_runtime_credentials(id,access_token,token_source,expires_at,metadata,updated_at)
  values(true,p_token,p_source,p_expires_at,coalesce(p_metadata,'{}'::jsonb),clock_timestamp())
  on conflict(id) do update
     set access_token=excluded.access_token,
         token_source=excluded.token_source,
         expires_at=excluded.expires_at,
         metadata=excluded.metadata,
         updated_at=excluded.updated_at;
  return true;
end
$function$
;

-- FUNCAO public.ai_ig_renew_turn_v5
CREATE OR REPLACE FUNCTION public.ai_ig_renew_turn_v5(p_conversation uuid, p_last_inbound uuid, p_owner uuid)
 RETURNS boolean
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
declare c public.ai_conversations; w public.ai_human_waits; q public.ai_instagram_turn_queue;
begin
 select * into c from public.ai_conversations where id=p_conversation for update;
 if not found or c.channel<>'instagram' or c.status<>'open' or c.metadata->'aiProcessing'->>'owner' is distinct from p_owner::text or (c.metadata->'aiProcessing'->>'expiresAt')::timestamptz<=clock_timestamp() then return false; end if;
 select * into w from public.ai_human_waits where conversation_id=c.id for update;
 if not found or w.last_inbound_id is distinct from p_last_inbound or w.state<>'evaluating' or w.inbound_at<=now()-interval '24 hours' then return false; end if;
 select * into q from public.ai_instagram_turn_queue where conversation_id=c.id for update;
 if not found or q.owner is distinct from p_owner or q.last_inbound_id is distinct from p_last_inbound or q.state<>'preflight' then return false; end if;
 if exists(select 1 from public.ai_optouts o where o.channel=c.channel and o.external_user_id=c.external_user_id) then return false; end if;
 update public.ai_conversations set metadata=jsonb_set(metadata,'{aiProcessing,expiresAt}',to_jsonb(clock_timestamp()+interval '180 seconds')),updated_at=now() where id=c.id;
 update public.ai_instagram_turn_queue set lease_until=clock_timestamp()+interval '180 seconds',updated_at=now() where conversation_id=c.id;
 return true;
end $function$
;

-- FUNCAO public.ai_ig_finish_turn_v6
CREATE OR REPLACE FUNCTION public.ai_ig_finish_turn_v6(p_conversation uuid, p_last_inbound uuid, p_owner uuid, p_mode text, p_ids uuid[], p_context jsonb DEFAULT NULL::jsonb, p_reason text DEFAULT NULL::text, p_category text DEFAULT 'unclear'::text)
 RETURNS boolean
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
declare
  c public.ai_conversations;
  w public.ai_human_waits;
  q public.ai_instagram_turn_queue;
  revision text := 'ferreira-voice-20260914-r1';
  safe_handoff_context jsonb := null;
begin
  if p_mode not in ('done','retry','blocked','silent') then
    raise exception 'invalid_finish_mode';
  end if;

  select * into c from public.ai_conversations where id=p_conversation for update;
  if not found or c.channel<>'instagram' or c.status<>'open' or c.metadata->'aiProcessing'->>'owner' is distinct from p_owner::text then
    return false;
  end if;

  select * into w from public.ai_human_waits where conversation_id=c.id for update;
  if not found or w.state not in ('waiting','evaluating') or w.last_inbound_id is distinct from p_last_inbound then
    return false;
  end if;

  select * into q from public.ai_instagram_turn_queue where conversation_id=c.id for update;
  if not found or q.last_inbound_id is distinct from p_last_inbound or q.owner is distinct from p_owner or q.state<>'preflight' then
    return false;
  end if;

  if p_mode='retry' and (
    c.metadata ? 'aiSendAttempt' or exists(
      select 1 from public.ai_messages
      where conversation_id=c.id and direction='outbound'
        and raw_payload->>'turnId'=p_owner::text and raw_payload->>'enviado'='true'
    )
  ) then
    p_mode := 'blocked';
    p_category := 'technical';
    p_reason := 'Envio parcial ou incerto; conferir antes de repetir.';
  end if;

  if p_mode='retry' and q.attempts>=2 then
    p_mode := 'blocked';
    p_category := 'technical';
  end if;

  if p_category is null or p_category not in (
    'technical','unclear','missing_fact','delivery','payment','reservation',
    'order_change','return_exchange','negotiation','personal_data','human_request','courtesy'
  ) then
    p_category := 'unclear';
  end if;

  if p_mode='blocked'
     and jsonb_typeof(p_context)='object'
     and coalesce(p_context->>'handoffSafe','false')='true'
     and coalesce(p_context->>'conversationId','')=c.id::text
     and coalesce(p_context->>'mode','')='focus'
  then
    safe_handoff_context := p_context - 'handoffSafe';
  end if;

  if p_mode='done' then
    if c.metadata ? 'aiSendAttempt' or not exists(
      select 1 from public.ai_messages
      where conversation_id=c.id and direction='outbound'
        and raw_payload->>'turnId'=p_owner::text and raw_payload->>'enviado'='true'
        and raw_payload->>'turn_complete'='true'
    ) then
      raise exception 'completed_turn_not_sent';
    end if;
    if not public.ai_wait_finish(c.id,p_last_inbound,'answered',null,null,revision) then return false; end if;
  elsif p_mode='silent' then
    if c.metadata ? 'aiSendAttempt' or exists(
      select 1 from public.ai_messages
      where conversation_id=c.id and direction='outbound' and raw_payload->>'turnId'=p_owner::text
    ) then
      raise exception 'silent_turn_has_messages';
    end if;
    if not public.ai_wait_finish(c.id,p_last_inbound,'answered','courtesy',coalesce(p_reason,'Mensagem sem pergunta; não precisa de resposta.'),revision) then return false; end if;
  elsif p_mode='blocked' then
    if not public.ai_hold_turn(c.id,p_last_inbound,p_owner,p_category,coalesce(p_reason,'O atendimento precisa ser conferido pela equipe.'),revision) then return false; end if;
  else
    update public.ai_human_waits
      set state='waiting', due_at=now()+interval '20 seconds', updated_at=now()
      where conversation_id=c.id;
  end if;

  update public.ai_messages
    set raw_payload=coalesce(raw_payload,'{}'::jsonb)||jsonb_build_object(
      'processingStatus',case
        when p_mode='done' then 'done'
        when p_mode='silent' then 'done_silent'
        when p_mode='blocked' then 'human_wait'
        else 'pending'
      end
    )
    where conversation_id=c.id and direction='inbound' and id=any(p_ids)
      and raw_payload->>'processingStatus' in ('pending','processing','superseded');

  update public.ai_instagram_turn_queue
    set state=case when p_mode='retry' then 'queued' when p_mode='silent' then 'done' else p_mode end,
        not_before=case when p_mode='retry' then now()+interval '20 seconds' else due_at end,
        owner=null, lease_until=null, updated_at=now()
    where conversation_id=c.id;

  update public.ai_conversations
    set metadata=(coalesce(metadata,'{}'::jsonb)-'aiProcessing'-'aiSendAttempt') ||
      case
        when p_mode in ('done','silent') then jsonb_build_object('aiContext',p_context,'aiResumedAt',now())
        when p_mode='blocked' and safe_handoff_context is not null then jsonb_build_object('aiContext',safe_handoff_context)
        else '{}'::jsonb
      end,
      updated_at=now(),
      last_message_at=case when p_mode='done' then now() else last_message_at end
    where id=c.id;

  return true;
end
$function$
;

-- FUNCAO public.ai_claim_followup
CREATE OR REPLACE FUNCTION public.ai_claim_followup(p_owner uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
declare c public.ai_conversations; w public.ai_human_waits; m public.ai_messages;
begin
 -- Lock conversations first, matching the inbound/manual-message trigger order.
 select c0.* into c from public.ai_conversations c0 join public.ai_human_waits w0 on w0.conversation_id=c0.id
 where not (c0.channel='instagram' and exists(select 1 from public.ai_settings where key='instagram_turn_policy' and value->>'enabled'='true' and value->>'workerFunction'='instagram-turn-worker-v6')) and w0.state='waiting' and ((c0.status='human' and w0.due_at<=now() and c0.metadata ? 'manualEchoObservedAt') or (c0.status='open' and (w0.updated_at<now()-interval '30 seconds' or c0.channel='instagram') and (w0.due_at is null or w0.due_at<=now()))) and w0.inbound_at>now()-interval '24 hours'
 and not exists(select 1 from public.ai_instagram_turn_queue q where q.conversation_id=c0.id and (q.last_inbound_id<>w0.last_inbound_id or q.state<>'ready' or q.due_at>clock_timestamp() or q.not_before>clock_timestamp()))
 and not(c0.metadata ? 'aiProcessing')
 and not exists(select 1 from public.ai_optouts o where o.channel=c0.channel and o.external_user_id=c0.external_user_id)
 order by w0.due_at for update of c0 skip locked limit 1;
 if not found then return null; end if;
 select * into w from public.ai_human_waits where conversation_id=c.id for update;
 if w.state<>'waiting' or w.due_at>now() then return null; end if;
 select * into m from public.ai_messages where id=w.last_inbound_id;
 if not found then return null; end if;
 update public.ai_human_waits set state='evaluating',updated_at=now() where conversation_id=c.id;
 update public.ai_conversations set status='open',metadata=coalesce(metadata,'{}'::jsonb)||jsonb_build_object(
  'aiProcessing',jsonb_build_object('owner',p_owner,'expiresAt',now()+interval '180 seconds','recoverySafe',true,'lastInboundId',(select last_inbound_id from public.ai_human_waits where conversation_id=c.id)),
  'aiFollowup',jsonb_build_object('owner',p_owner,'lastInboundId',w.last_inbound_id,'generation',w.generation,'startedAt',now(),'afterHumanWait',(c.status='human' or coalesce((c.metadata->>'aiIgAfterHumanWait')::boolean,false))))
 where id=c.id returning * into c;
 return jsonb_build_object('conversation',to_jsonb(c),'message',m.raw_payload,'lastInboundId',w.last_inbound_id,'owner',p_owner,'afterHumanWait',c.metadata->'aiFollowup'->'afterHumanWait');
end $function$
;

-- FUNCAO public.ai_meta_token_status
CREATE OR REPLACE FUNCTION public.ai_meta_token_status()
 RETURNS jsonb
 LANGUAGE sql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
  select case when r.id is null then jsonb_build_object('configured',false)
              else jsonb_build_object(
                'configured',true,
                'source',r.token_source,
                'expiresAt',r.expires_at,
                'updatedAt',r.updated_at,
                'metadata',r.metadata
              ) end
  from (select 1) x
  left join private.instagram_runtime_credentials r on r.id=true
$function$
;

-- FUNCAO public.ai_meta_token_get
CREATE OR REPLACE FUNCTION public.ai_meta_token_get()
 RETURNS text
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
  select access_token
  from private.instagram_runtime_credentials
  where id=true and (expires_at is null or expires_at>clock_timestamp()+interval '5 minutes')
  limit 1
$function$
;

-- FUNCAO public.ai_ig_dispatch_reference_recovery
CREATE OR REPLACE FUNCTION public.ai_ig_dispatch_reference_recovery()
 RETURNS bigint
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
declare c public.ai_conversations; w public.ai_human_waits; run_name text; request_id bigint; claimed integer;
begin
 if not exists(select 1 from public.ai_settings where key='instagram_turn_policy' and value->>'enabled'='true' and value->>'workerFunction'='instagram-turn-worker-v6' and value->>'partialReferenceRecovery'='true') then return null; end if;
 select c0.* into c from public.ai_conversations c0 join public.ai_human_waits w0 on w0.conversation_id=c0.id join public.ai_instagram_turn_queue q0 on q0.conversation_id=c0.id join public.ai_messages m on m.id=w0.last_inbound_id
 where c0.channel='instagram' and c0.status='human' and not(c0.metadata ? 'aiProcessing') and not(c0.metadata ? 'aiSendAttempt') and w0.state='blocked' and w0.category in ('unclear','missing_fact') and w0.inbound_at>now()-interval '24 hours' and (w0.last_human_at is null or w0.last_human_at<w0.waiting_since) and q0.state='blocked' and q0.last_inbound_id=w0.last_inbound_id
 and m.raw_payload->'answerDecision'->>'revision'='instagram-independent-stories-20260911-r6' and jsonb_typeof(m.raw_payload->'referenceDiagnostics')='array'
 and exists(select 1 from jsonb_array_elements(m.raw_payload->'referenceDiagnostics') x where x->>'productId' is not null and x->>'blocked' is null)
 and exists(select 1 from jsonb_array_elements(m.raw_payload->'referenceDiagnostics') x where x->>'blocked' in ('unclear','missing_fact'))
 and not exists(select 1 from public.ai_messages o where o.conversation_id=c0.id and o.direction='outbound' and o.created_at>=w0.waiting_since)
 and not exists(select 1 from public.ai_optouts o where o.channel=c0.channel and o.external_user_id=c0.external_user_id)
 and not exists(select 1 from public.ai_settings s where s.key='instagram_reference_recovery:'||w0.generation::text)
 order by w0.inbound_at limit 1;
 if not found then return null; end if;
 select * into w from public.ai_human_waits where conversation_id=c.id;
 insert into public.ai_settings(key,value) values('instagram_reference_recovery:'||w.generation::text,jsonb_build_object('queuedAt',now(),'conversationId',c.id,'lastInboundId',w.last_inbound_id)) on conflict(key) do nothing;
 get diagnostics claimed=row_count;
 if claimed=0 then return null; end if;
 run_name:='ig_r6_auto_recovery_'||replace(w.generation::text,'-','');
 select net.http_post(url:='https://nailfzcujyxydqldktgg.supabase.co/functions/v1/instagram-verified-reference-recovery',headers:=jsonb_build_object('Content-Type','application/json','x-ai-followup-token',(select secret from private.ai_followup_config where id=true)),body:=jsonb_build_object('action','send','run',run_name,'conversationId',c.id,'lastInboundId',w.last_inbound_id,'generation',w.generation),timeout_milliseconds:=10000) into request_id;
 return request_id;
end $function$
;

-- FUNCAO public.ai_meta_token_state
CREATE OR REPLACE FUNCTION public.ai_meta_token_state()
 RETURNS jsonb
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
  select jsonb_build_object(
    'accessToken', access_token, 'source', token_source, 'expiresAt', expires_at,
    'metadata', metadata, 'updatedAt', updated_at
  ) from private.instagram_runtime_credentials where id = true limit 1
$function$
;

-- FUNCAO public.ai_ig_finish_dialogue_continuity
CREATE OR REPLACE FUNCTION public.ai_ig_finish_dialogue_continuity(p_conversation uuid, p_last_inbound uuid, p_owner uuid, p_source uuid, p_kind text, p_text text, p_context jsonb)
 RETURNS boolean
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
declare c public.ai_conversations; w public.ai_human_waits; done boolean;
begin
 if p_kind not in ('clarification','factual','handoff') or p_context is null or p_context->>'conversationId' is distinct from p_conversation::text then return false; end if;
 select * into c from public.ai_conversations where id=p_conversation for update;
 if not found or c.channel<>'instagram' or c.status<>'open' or c.metadata->'aiProcessing'->>'owner' is distinct from p_owner::text or c.metadata ? 'aiSendAttempt' then return false; end if;
 select * into w from public.ai_human_waits where conversation_id=c.id for update;
 if not found or w.last_inbound_id is distinct from p_last_inbound or w.state<>'evaluating' then return false; end if;
 if not exists(select 1 from public.ai_messages where id=p_source and conversation_id=c.id and direction='inbound' and created_at<=w.inbound_at) then return false; end if;
 if not exists(select 1 from public.ai_messages where conversation_id=c.id and direction='outbound' and text_content=p_text and external_message_id is not null and raw_payload->>'turnId'=p_owner::text and raw_payload->>'revision'='instagram-dialogue-continuity-20260911-r1' and raw_payload->>'sourceRequestId'=p_source::text and raw_payload->>'enviado'='true' and raw_payload->>'turn_complete'='true') then return false; end if;
 done:=public.ai_ig_finish_turn_v6(c.id,p_last_inbound,p_owner,case when p_kind='handoff' then 'blocked' else 'done' end,'{}'::uuid[],p_context,case when p_kind='handoff' then 'Identificação da peça precisa de conferência da equipe; cliente avisada.' else null end,'unclear');
 if not done then return false; end if;
 update public.ai_conversations set metadata=jsonb_set(coalesce(metadata,'{}'::jsonb),'{aiContext}',p_context),updated_at=now() where id=c.id;
 update public.ai_messages set raw_payload=coalesce(raw_payload,'{}'::jsonb)||jsonb_build_object('processingStatus',case when p_kind='factual' then 'done' when p_kind='handoff' then 'human_wait' else 'awaiting_clarification' end,'dialogueRevision','instagram-dialogue-continuity-20260911-r1','dialogueSourceId',p_source,'dialogueUpdatedAt',now()) where conversation_id=c.id and id in (p_last_inbound,p_source) and raw_payload->>'processingStatus' not in ('done','human_answered');
 return true;
end $function$
;

-- FUNCAO public.ai_register_prefetched_story
CREATE OR REPLACE FUNCTION public.ai_register_prefetched_story()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare
  sid text;
  pid uuid;
  mid uuid;
  aid text;
  clr text;
  existing uuid;
begin
  if new.page<>0
     or new.run_id not like 'ig_r6_storyprefetch_%'
     or coalesce((new.result->>'complete')::boolean,false)<>true
     or coalesce((new.result->>'passed')::boolean,false)<>true
  then return new; end if;

  sid := new.result->>'storyId';
  if sid is null or sid !~ '^\d{5,40}$'
     or coalesce(new.result->>'productId','') !~ '^[0-9a-fA-F-]{36}$'
     or coalesce(new.result->>'messageId','') !~ '^[0-9a-fA-F-]{36}$'
  then return new; end if;

  pid := (new.result->>'productId')::uuid;
  mid := (new.result->>'messageId')::uuid;
  clr := nullif(left(coalesce(new.result->'description'->>'color',''),45),'');

  select m.raw_payload->>'accountId' into aid
    from public.ai_messages m
   where m.id=mid and m.direction='inbound'
   limit 1;

  if aid is null or aid='' or not exists(
    select 1 from public.products p where p.id=pid and lower(p.status)='ativo'
  ) then return new; end if;

  select sp.product_id into existing
    from public.ai_story_products sp
   where sp.story_id=sid
   for update;

  if existing is not null and existing<>pid then
    insert into public.ai_logs(kind,level,channel,conversation_id,detail)
    select 'story_identity_conflict','warn','instagram',m.conversation_id,
      jsonb_build_object(
        'storyId',sid,'registered',existing,'proposed',pid,
        'run',new.run_id,'revision','instagram-story-prefetch-20260916-r3',
        'visualRevision',coalesce(new.result->>'revision','unknown')
      )
      from public.ai_messages m where m.id=mid;
    return new;
  end if;

  insert into public.ai_story_products(
    story_id,account_id,product_id,color,layout,method,image_hash,evidence,
    verified_at,expires_at,updated_at
  ) values (
    sid,aid,pid,clr,'single','visual_verified',nullif(new.result->>'imageHash',''),
    jsonb_build_object(
      'source','story_prefetch','run',new.run_id,'messageId',mid,
      'revision','instagram-story-prefetch-20260916-r3',
      'visualRevision',coalesce(new.result->>'revision','unknown'),
      'imageSource',new.result->>'imageSource'
    ),
    clock_timestamp(),clock_timestamp()+interval '30 days',clock_timestamp()
  )
  on conflict(story_id) do update
     set account_id=excluded.account_id,
         product_id=excluded.product_id,
         color=coalesce(excluded.color,public.ai_story_products.color),
         layout='single',
         method='visual_verified',
         image_hash=coalesce(excluded.image_hash,public.ai_story_products.image_hash),
         evidence=excluded.evidence,
         verified_at=excluded.verified_at,
         expires_at=excluded.expires_at,
         updated_at=excluded.updated_at
   where public.ai_story_products.product_id=excluded.product_id;

  perform public.ai_requeue_story_context(sid);
  return new;
end
$function$
;

-- FUNCAO public.ai_ig_dispatch_dialogue_continuity
CREATE OR REPLACE FUNCTION public.ai_ig_dispatch_dialogue_continuity()
 RETURNS bigint
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
BEGIN
 -- The independent clarification sender was superseded by the human-silent policy.
 -- Leave queued conversations and all human timers untouched.
 RETURN NULL;
END $function$
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
     or coalesce(new.raw_payload->>'processingStatus','pending') <> 'pending'
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

-- FUNCAO private.ai_enqueue_instagram_text_normalizer
CREATE OR REPLACE FUNCTION private.ai_enqueue_instagram_text_normalizer()
 RETURNS trigger
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
declare
  v_token text;
  v_request_id bigint;
begin
  if new.direction is distinct from 'inbound'
     or new.message_type is distinct from 'text'
     or new.raw_payload->>'channel' is distinct from 'instagram'
     or new.raw_payload->>'processingStatus' is distinct from 'pending'
     or coalesce(new.raw_payload->>'supported','true') = 'false'
     or coalesce(new.raw_payload->>'importedHistory','false') = 'true'
     or new.text_content is null
     or btrim(new.text_content) = ''
  then
    return new;
  end if;

  select secret into v_token
  from private.ai_followup_config
  where length(secret)=64
  limit 1;

  if v_token is null then return new; end if;

  select net.http_post(
    url := 'https://nailfzcujyxydqldktgg.supabase.co/functions/v1/instagram-text-normalizer',
    body := jsonb_build_object('messageId', new.id),
    headers := jsonb_build_object('Content-Type','application/json','x-ai-followup-token',v_token),
    timeout_milliseconds := 30000
  ) into v_request_id;

  return new;
exception when others then
  return new;
end;
$function$
;

-- FUNCAO public.ai_resolve_answered_handoffs
CREATE OR REPLACE FUNCTION public.ai_resolve_answered_handoffs()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
begin
  if new.state='answered' and old.state is distinct from 'answered' then
    update public.ai_handoffs
       set status='resolved',resolved_at=coalesce(resolved_at,clock_timestamp())
     where conversation_id=new.conversation_id and status='open';
  end if;
  return new;
end
$function$
;

-- FUNCAO private.ai_restore_audio_dress_context
CREATE OR REPLACE FUNCTION private.ai_restore_audio_dress_context()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare
  v_original text;
  v_current text;
  v_intent_text text;
  v_intent_norm text;
  v_latest_kind text;
  v_occasion text;
  v_phrase text;
begin
  if new.direction is distinct from 'inbound'
     or coalesce(new.raw_payload->>'channel','') <> 'instagram'
     or coalesce(new.raw_payload->>'mediaType','') <> 'audio'
     or coalesce(new.raw_payload->'transcription'->>'status','') <> 'done'
     or coalesce(old.raw_payload->'transcription'->>'status','') = 'done'
     or new.text_content is null
     or btrim(new.text_content) = ''
  then
    return new;
  end if;

  v_original := new.text_content;
  v_current := lower(public.unaccent(v_original));

  if v_current ~ '\m(festa|gala|debutante|casamento|madrinh|formatura|formanda|casual|praia|dia a dia|trabalho)\M' then
    return new;
  end if;

  select m.text_content
    into v_intent_text
  from public.ai_messages m
  where m.conversation_id = new.conversation_id
    and m.direction = 'inbound'
    and m.created_at < new.created_at
    and m.created_at >= new.created_at - interval '72 hours'
    and m.text_content is not null
    and lower(public.unaccent(m.text_content)) ~ '\m(vestid[a-z]*|madrinh[a-z]*)\M'
    and lower(public.unaccent(m.text_content)) ~ '\m(festa|gala|debutante|casamento|madrinh[a-z]*|formatura|formanda|casual|praia|dia a dia|trabalho)\M'
  order by m.created_at desc
  limit 1;

  if v_intent_text is null then
    return new;
  end if;

  v_intent_norm := lower(public.unaccent(v_intent_text));
  v_occasion := case
    when v_intent_norm ~ '\m(casual|praia|dia a dia|trabalho)\M' then 'casual'
    when v_intent_norm ~ '\m(formatura|formanda)\M' then 'formatura'
    when v_intent_norm ~ '\m(casamento|madrinh[a-z]*|convidada)\M' then 'casamento'
    when v_intent_norm ~ '\m(festa|gala|debutante)\M' then 'festa'
    else null
  end;

  v_phrase := case v_occasion
    when 'festa' then 'vestido de festa'
    when 'casamento' then 'vestido de festa para casamento'
    when 'formatura' then 'vestido de festa para formatura'
    when 'casual' then 'vestido casual'
    else null
  end;

  if v_phrase is null then
    return new;
  end if;

  if v_current ~ '\mvestidos?\M' then
    new.text_content := regexp_replace(new.text_content, '\mvestido\M', v_phrase, 'i');
    if new.text_content = v_original then
      new.text_content := regexp_replace(new.text_content, '\mvestidos\M', replace(v_phrase,'vestido','vestidos'), 'i');
    end if;
  elsif v_current !~ '\m(conjunto[a-z]*|blusa[a-z]*|calca[a-z]*|saia[a-z]*|macacao[a-z]*|body|blazer[a-z]*|colete[a-z]*|camisa[a-z]*)\M' then
    select case
      when lower(public.unaccent(m.text_content)) ~ '\m(vestid[a-z]*|madrinh[a-z]*)\M' then 'dress'
      else 'other'
    end
      into v_latest_kind
    from public.ai_messages m
    where m.conversation_id = new.conversation_id
      and m.direction = 'inbound'
      and m.created_at < new.created_at
      and m.created_at >= new.created_at - interval '72 hours'
      and m.text_content is not null
      and lower(public.unaccent(m.text_content)) ~ '\m(vestid[a-z]*|madrinh[a-z]*|conjunto[a-z]*|blusa[a-z]*|calca[a-z]*|saia[a-z]*|macacao[a-z]*|body|blazer[a-z]*|colete[a-z]*|camisa[a-z]*)\M'
    order by m.created_at desc
    limit 1;

    if v_latest_kind = 'dress' then
      if btrim(v_current) ~ '^(pp|p|m|g|gg|g[123]|u|3[468]|4[02468]|5[024])[?.! ]*$' then
        new.text_content := regexp_replace(btrim(new.text_content), '[?.! ]+$', '') || ' para ' || v_phrase;
      elsif btrim(v_current) ~ '^(preto|branco|vermelho|amarelo|azul|verde|rosa|rose|pink|lilas|roxo|fucsia|nude|marrom|terracota|vinho|marsala|caramelo|bege|areia|creme|salmao|coral|laranja|cinza|prata|dourado|turquesa)[?.! ]*$' then
        new.text_content := regexp_replace(btrim(new.text_content), '[?.! ]+$', '') || ' para ' || v_phrase;
      elsif v_current ~ '\m(outros modelos|mais modelos)\M' then
        new.text_content := regexp_replace(new.text_content, '\m(outros modelos|mais modelos)\M', '\1 de ' || v_phrase, 'i');
      end if;
    end if;
  end if;

  if new.text_content is distinct from v_original then
    new.raw_payload := coalesce(new.raw_payload,'{}'::jsonb) || jsonb_build_object(
      'textNormalization', jsonb_build_object(
        'status','corrected',
        'revision','instagram-audio-dress-context-20260912-r1',
        'contextRevision','instagram-dress-occasion-context-20260912-r2',
        'at',to_char(clock_timestamp() at time zone 'UTC','YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'),
        'originalText',v_original,
        'correctedText',new.text_content,
        'corrections',jsonb_build_array(jsonb_build_object('kind','dress_occasion_context','occasion',v_occasion,'sourceText',v_intent_text))
      )
    );
  end if;

  return new;
end;
$function$
;

-- FUNCAO public.ai_ig_claim_turn
CREATE OR REPLACE FUNCTION public.ai_ig_claim_turn(p_owner uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
declare c public.ai_conversations; w public.ai_human_waits; q public.ai_instagram_turn_queue; was_human boolean;
begin
 if not pg_try_advisory_xact_lock(732015994216::bigint) then return null; end if;
 if (select count(*) from public.ai_instagram_turn_queue where state='preflight' and lease_until>clock_timestamp())>=2 then return null; end if;
 select c0.* into c
 from public.ai_conversations c0
 join public.ai_human_waits w0 on w0.conversation_id=c0.id
 join public.ai_instagram_turn_queue q0 on q0.conversation_id=c0.id and q0.last_inbound_id=w0.last_inbound_id
 where c0.channel='instagram'
   and q0.state='queued'
   and q0.due_at<=clock_timestamp()
   and q0.not_before<=clock_timestamp()
   and w0.state='waiting'
   and w0.inbound_at>now()-interval '24 hours'
   and (c0.status='open' or (c0.status='human' and w0.due_at<=now() and c0.metadata ? 'manualEchoObservedAt' and coalesce(w0.category,'')<>'human_request' and w0.last_human_at is not null
   and w0.last_human_at+interval '10 minutes'<=clock_timestamp()
   and exists(select 1 from public.ai_messages hm where hm.conversation_id=c0.id
     and hm.direction='outbound' and hm.created_at=w0.last_human_at
     and coalesce(hm.raw_payload->>'importedHistory','false')<>'true'
     and coalesce(hm.raw_payload->>'enviado','true')<>'false'
     and (hm.raw_payload->>'origem' in ('conta_da_loja','whatsapp_business_app') or hm.raw_payload->>'coexistence'='true'))))
   and not(c0.metadata ? 'aiProcessing')
   and not exists(select 1 from public.ai_optouts o where o.channel=c0.channel and o.external_user_id=c0.external_user_id)
   and not exists (
     select 1 from public.ai_messages am
     where am.conversation_id=c0.id
       and am.direction='inbound'
       and am.raw_payload->>'processingStatus'='pending'
       and am.raw_payload->>'mediaType'='audio'
       and coalesce(am.raw_payload->'transcription'->>'status','')<>'done'
       and coalesce(am.raw_payload->'audioPreprocess'->>'status','')<>'failed'
       and am.created_at>now()-interval '130 seconds'
   )
 order by q0.not_before
 for update of c0 skip locked
 limit 1;
 if not found then return null; end if;
 select * into w from public.ai_human_waits where conversation_id=c.id for update;
 select * into q from public.ai_instagram_turn_queue where conversation_id=c.id for update;
 if w.state<>'waiting' or q.last_inbound_id<>w.last_inbound_id or q.state<>'queued' or q.due_at>clock_timestamp() then return null; end if;
 was_human:=c.status='human';
 update public.ai_instagram_turn_queue set state='preflight',owner=p_owner,lease_until=now()+interval '180 seconds',attempts=attempts+1,after_human_wait=was_human,updated_at=now() where conversation_id=c.id;
 update public.ai_human_waits set state='evaluating',updated_at=now() where conversation_id=c.id;
 update public.ai_conversations set status='open',metadata=coalesce(metadata,'{}'::jsonb)||jsonb_build_object('aiIgAfterHumanWait',was_human,'aiProcessing',jsonb_build_object('owner',p_owner,'expiresAt',now()+interval '180 seconds','lastInboundId',w.last_inbound_id,'recoverySafe',true,'worker','instagram-quiet60-audio-clean')) where id=c.id returning * into c;
 return jsonb_build_object('conversation',to_jsonb(c),'lastInboundId',w.last_inbound_id,'inboundAt',w.inbound_at,'receivedAt',q.received_at,'afterHumanWait',was_human,'attempts',q.attempts+1);
end
$function$
;

-- FUNCAO public.ai_learn_story_products
CREATE OR REPLACE FUNCTION public.ai_learn_story_products()
 RETURNS integer
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
declare
 rec record;
 learned integer:=0;
 quoted numeric;
 cand uuid[];
 matches uuid[];
begin
 for rec in
  select m.id as msg_id, m.conversation_id, m.created_at,
         m.raw_payload->'storyReference'->>'id' as story_id,
         coalesce(m.raw_payload->>'accountId','') as account_id,
         m.raw_payload as payload,
         h.id as reply_id, h.text_content as reply_text, h.created_at as reply_at
  from public.ai_messages m
  join lateral (
    select h.* from public.ai_messages h
    where h.conversation_id=m.conversation_id
      and h.direction='outbound'
      and h.raw_payload->>'origem'='conta_da_loja'
      and h.created_at>m.created_at
      and h.created_at<m.created_at+interval '45 minutes'
      and h.text_content ~* '^\s*(?:ol[aá][^\n]*\n+\s*)?(?:custa |esse custa |esse modelo custa |o valor [eé] |fica )?(?:r\$ ?)?\d{1,3}(?:\.\d{3})?,\d{2}\s*$'
    order by h.created_at limit 1
  ) h on true
  where m.direction='inbound'
    and m.raw_payload->'storyReference'->>'id' ~ '^\d{5,40}$'
    and m.created_at>now()-interval '14 days'
    and coalesce(m.raw_payload->>'importedHistory','false')<>'true'
    and not exists (
      select 1 from public.ai_story_products r
       where r.story_id=m.raw_payload->'storyReference'->>'id'
    )
    and not exists (
      select 1 from public.ai_messages o
       where o.conversation_id=m.conversation_id
         and o.id<>m.id
         and o.direction='inbound'
         and o.created_at>m.created_at-interval '10 minutes'
         and o.created_at<h.created_at
    )
    and not exists (
      select 1 from public.ai_messages o
       where o.conversation_id=m.conversation_id
         and o.direction='outbound'
         and o.created_at>m.created_at
         and o.created_at<h.created_at
    )
 loop
  quoted:=replace(replace(substring(rec.reply_text from '(\d{1,3}(?:\.\d{3})?,\d{2})'),'.',''),',','.')::numeric;

  select array_agg(distinct pid) into cand from (
    select (d->>'productId')::uuid as pid
    from jsonb_array_elements(case when jsonb_typeof(rec.payload->'referenceDiagnostics')='array' then rec.payload->'referenceDiagnostics' else '[]'::jsonb end) d
    where d->>'storyId'=rec.story_id
      and d->>'productId' ~ '^[0-9a-f-]{36}$'
      and coalesce(d->'crop'->>'layout','single') in ('single','same_model_variants')

    union

    select (t->>'productId')::uuid
    from jsonb_array_elements(case when jsonb_typeof(rec.payload->'referenceDiagnostics')='array' then rec.payload->'referenceDiagnostics' else '[]'::jsonb end) d,
         jsonb_array_elements(case when jsonb_typeof(d->'top')='array' then d->'top' else '[]'::jsonb end) t
    where d->>'storyId'=rec.story_id
      and coalesce(d->'crop'->>'layout','single') in ('single','same_model_variants')
      and (t->>'sameModel')='true'
      and (t->>'score')::numeric>=0.9
      and t->>'productId' ~ '^[0-9a-f-]{36}$'

    union

    select (value->>'productId')::uuid
    from public.ai_settings
    where (key like 'ig_verified_crop:'||rec.account_id||':'||rec.story_id||':%'
        or key like 'ig_verified_image:'||rec.account_id||':'||rec.story_id||':%')
      and value->>'productId' ~ '^[0-9a-f-]{36}$'
      and coalesce(value->'crop'->>'layout',value->>'layout','single') in ('single','same_model_variants')

    union

    select (rv.result->>'productId')::uuid
    from public.ai_instagram_reviews rv
    where rv.page=0
      and rv.run_id like 'ig_r6_storyprefetch_%'
      and rv.result->>'messageId'=rec.msg_id::text
      and rv.result->>'storyId'=rec.story_id
      and rv.result->>'productId' ~ '^[0-9a-f-]{36}$'

    union

    select (x.item->>'productId')::uuid
    from public.ai_instagram_reviews rv
    cross join lateral jsonb_array_elements(
      case when jsonb_typeof(rv.result->'matches')='array' then rv.result->'matches' else '[]'::jsonb end
    ) x(item)
    where rv.page=0
      and rv.run_id like 'ig_r6_storyprefetch_%'
      and rv.result->>'messageId'=rec.msg_id::text
      and rv.result->>'storyId'=rec.story_id
      and x.item->>'productId' ~ '^[0-9a-f-]{36}$'
      and (
        coalesce(x.item->>'same_model',x.item->>'sameModel','false')='true'
        or coalesce(nullif(x.item->>'similarity',''),nullif(x.item->>'score',''),'0')::numeric>=0.9
      )
  ) c where pid is not null;

  if cand is null then continue; end if;

  select array_agg(p.id) into matches
    from public.products p
   where p.id=any(cand)
     and lower(p.status)='ativo'
     and abs(p.sale_price::numeric-quoted)<0.005;

  if matches is not null and array_length(matches,1)=1 then
   insert into public.ai_story_products(
     story_id,account_id,product_id,method,layout,evidence,verified_at,expires_at
   ) values(
     rec.story_id,rec.account_id,matches[1],'human_price_match','single',
     jsonb_build_object(
       'messageId',rec.msg_id,
       'replyId',rec.reply_id,
       'quoted',quoted,
       'candidates',to_jsonb(cand),
       'revision','story-registry-20260916-r2',
       'prefetchAware',true
     ),
     rec.reply_at,rec.reply_at+interval '30 days'
   ) on conflict(story_id) do nothing;
   if found then
     learned:=learned+1;
     perform public.ai_requeue_story_context(rec.story_id);
   end if;
  elsif matches is null then
   insert into public.ai_logs(kind,level,channel,conversation_id,detail)
   select 'story_price_conflict','warn','instagram',rec.conversation_id,
          jsonb_build_object(
            'storyId',rec.story_id,'quoted',quoted,'candidates',to_jsonb(cand),
            'messageId',rec.msg_id,'replyId',rec.reply_id,
            'revision','story-registry-20260916-r2'
          )
   where not exists(
     select 1 from public.ai_logs l
      where l.kind='story_price_conflict'
        and l.detail->>'storyId'=rec.story_id
        and (l.detail->>'quoted')::numeric=quoted
   );
  end if;
 end loop;
 return learned;
end
$function$
;

-- FUNCAO public.ai_worker_sources_sha
CREATE OR REPLACE FUNCTION public.ai_worker_sources_sha()
 RETURNS trigger
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
begin new.sha256:=encode(sha256(convert_to(new.content,'UTF8')),'hex'); new.updated_at:=now(); return new; end $function$
;

-- FUNCAO public.ai_prefetch_instagram_story
CREATE OR REPLACE FUNCTION public.ai_prefetch_instagram_story()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare
  request_id bigint;
begin
  if new.direction<>'inbound'
     or coalesce(new.raw_payload->>'importedHistory','false')='true'
     or new.raw_payload->>'channel'<>'instagram'
     or coalesce(new.raw_payload->'storyReference'->>'id','') !~ '^\d{5,40}$'
  then
    return new;
  end if;

  if not exists(
    select 1 from public.ai_settings
     where key='instagram_turn_policy' and value->>'enabled'='true'
  ) then
    return new;
  end if;

  if exists(
    select 1 from public.ai_story_products sp
     where sp.story_id=new.raw_payload->'storyReference'->>'id'
       and sp.account_id=coalesce(new.raw_payload->>'accountId','')
       and (sp.expires_at is null or sp.expires_at>clock_timestamp())
  ) then
    return new;
  end if;

  select net.http_post(
    url:='https://nailfzcujyxydqldktgg.supabase.co/functions/v1/instagram-story-prefetch',
    headers:=jsonb_build_object(
      'Content-Type','application/json',
      'x-ai-followup-token',(select secret from private.ai_followup_config where id=true)
    ),
    body:=jsonb_build_object('messageId',new.id,'conversationId',new.conversation_id),
    timeout_milliseconds:=10000
  ) into request_id;

  return new;
exception when others then
  insert into public.ai_logs(kind,level,channel,conversation_id,detail)
  values('error','warn','instagram',new.conversation_id,
    jsonb_build_object('stage','story_prefetch_dispatch','error',left(sqlerrm,120),'revision','instagram-story-prefetch-20260916-r1'));
  return new;
end
$function$
;

-- FUNCAO public.ai_requeue_story_context
CREATE OR REPLACE FUNCTION public.ai_requeue_story_context(p_story_id text)
 RETURNS integer
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare
  rec record;
  n integer := 0;
  target_due timestamptz;
  manual_recent boolean;
begin
  if p_story_id is null or p_story_id !~ '^\d{5,40}$' then return 0; end if;

  for rec in
    select c.id as conversation_id,
           c.status as conversation_status,
           c.metadata,
           w.last_inbound_id,
           w.inbound_at,
           w.last_human_at,
           w.category,
           w.state
      from public.ai_conversations c
      join public.ai_human_waits w on w.conversation_id=c.id
      join public.ai_messages lm on lm.id=w.last_inbound_id and lm.conversation_id=c.id
     where c.channel='instagram'
       and c.status<>'closed'
       and w.state='blocked'
       and coalesce(w.category,'') in ('unclear','missing_fact')
       and w.inbound_at>now()-interval '24 hours'
       and not (c.metadata ? 'aiProcessing')
       and (
         c.metadata->'aiContext'->'pendingVisualReference'->>'storyId'=p_story_id
         or c.metadata->'aiContext'->'referenceContext'->>'id'=p_story_id
         or lm.raw_payload->'storyReference'->>'id'=p_story_id
       )
       and not exists (
         select 1 from public.ai_optouts o
          where o.channel=c.channel and o.external_user_id=c.external_user_id
       )
     for update of c, w skip locked
  loop
    manual_recent := rec.last_human_at is not null
      and rec.metadata ? 'manualEchoObservedAt'
      and rec.last_human_at + interval '10 minutes' > clock_timestamp();
    target_due := case when manual_recent then rec.last_human_at + interval '10 minutes' else clock_timestamp() end;

    update public.ai_messages
       set raw_payload=coalesce(raw_payload,'{}'::jsonb)
         || jsonb_build_object(
              'processingStatus','pending',
              'storyIdentityRecoveredAt',clock_timestamp(),
              'storyIdentityRecovered',true
            )
     where id=rec.last_inbound_id
       and conversation_id=rec.conversation_id
       and direction='inbound'
       and coalesce(raw_payload->>'processingStatus','') in ('human_wait','failed','blocked');

    update public.ai_human_waits
       set state='waiting',
           due_at=target_due,
           waiting_since=least(coalesce(waiting_since,clock_timestamp()),clock_timestamp()),
           unread=true,
           category=null,
           reason=null,
           technical_attempts=0,
           generation=gen_random_uuid(),
           updated_at=clock_timestamp()
     where conversation_id=rec.conversation_id
       and last_inbound_id=rec.last_inbound_id
       and state='blocked'
       and coalesce(category,'') in ('unclear','missing_fact');

    if found then
      insert into public.ai_instagram_turn_queue(
        conversation_id,last_inbound_id,received_at,due_at,not_before,state,
        owner,lease_until,attempts,after_human_wait,updated_at
      ) values (
        rec.conversation_id,rec.last_inbound_id,clock_timestamp(),target_due,target_due,'queued',
        null,null,0,manual_recent,clock_timestamp()
      )
      on conflict(conversation_id) do update
         set last_inbound_id=excluded.last_inbound_id,
             received_at=excluded.received_at,
             due_at=excluded.due_at,
             not_before=excluded.not_before,
             state='queued',
             owner=null,
             lease_until=null,
             attempts=0,
             after_human_wait=excluded.after_human_wait,
             updated_at=excluded.updated_at;

      if not manual_recent then
        update public.ai_conversations
           set status='open',
               metadata=coalesce(metadata,'{}'::jsonb)-'aiIgAfterHumanWait',
               updated_at=clock_timestamp()
         where id=rec.conversation_id;
      end if;
      n := n + 1;
    end if;
  end loop;

  if n>0 then perform public.ai_ig_dispatch(); end if;
  return n;
end
$function$
;

-- FUNCAO public.ai_story_cache_expired_paths
CREATE OR REPLACE FUNCTION public.ai_story_cache_expired_paths()
 RETURNS TABLE(path text)
 LANGUAGE sql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
  select o.name::text as path
  from storage.objects o
  where o.bucket_id='ai-inbox-media'
    and o.name like 'instagram-story-cache/%'
    and o.created_at < clock_timestamp()-interval '72 hours'
  order by o.created_at
  limit 500
$function$
;

-- FUNCAO public.ai_story_cache_finalize_cleanup
CREATE OR REPLACE FUNCTION public.ai_story_cache_finalize_cleanup()
 RETURNS integer
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare n integer;
begin
  delete from public.ai_story_products
   where expires_at is not null
     and expires_at < clock_timestamp()-interval '7 days';
  get diagnostics n = row_count;
  return n;
end
$function$
;

-- FUNCAO public.ai_instagram_delivery_recover
CREATE OR REPLACE FUNCTION public.ai_instagram_delivery_recover()
 RETURNS integer
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare
  r record;
  recovered integer := 0;
begin
  for r in
    select c.id as conversation_id, w.last_inbound_id
    from public.ai_conversations c
    join public.ai_human_waits w on w.conversation_id = c.id
    join public.ai_instagram_turn_queue q on q.conversation_id = c.id and q.last_inbound_id = w.last_inbound_id
    where c.channel = 'instagram'
      and w.state = 'blocked'
      and coalesce(w.category,'') = 'technical'
      and w.inbound_at > now() - interval '24 hours'
      and exists (
        select 1 from public.ai_messages o
        where o.conversation_id = c.id
          and o.direction = 'outbound'
          and o.created_at >= w.inbound_at
          and o.raw_payload->>'enviado' = 'false'
          and o.raw_payload->>'erro' = 'meta_190'
      )
      and not exists (
        select 1 from public.ai_messages h
        where h.conversation_id = c.id
          and h.direction = 'outbound'
          and h.created_at >= w.inbound_at
          and coalesce(h.raw_payload->>'importedHistory','false') <> 'true'
          and (h.raw_payload->>'origem' in ('conta_da_loja','whatsapp_business_app') or h.raw_payload->>'coexistence'='true')
          and coalesce(h.raw_payload->>'enviado','true') <> 'false'
      )
      and not exists (
        select 1 from public.ai_optouts o
        where o.channel = c.channel and o.external_user_id = c.external_user_id
      )
      and not (c.metadata ? 'aiProcessing')
  loop
    update public.ai_messages
       set raw_payload = (coalesce(raw_payload,'{}'::jsonb) - 'needsHuman') || jsonb_build_object('processingStatus','pending','deliveryRecoveryRevision','instagram-delivery-auth-20260916-r1')
     where id = r.last_inbound_id
       and direction = 'inbound';

    update public.ai_human_waits
       set state='waiting', category=null, reason=null, due_at=null, technical_attempts=0,
           waiting_since=now(), generation=gen_random_uuid(), unread=true, updated_at=now()
     where conversation_id=r.conversation_id and last_inbound_id=r.last_inbound_id;

    update public.ai_instagram_turn_queue
       set state='queued', attempts=0, owner=null, lease_until=null, due_at=now(), not_before=now(), updated_at=now()
     where conversation_id=r.conversation_id and last_inbound_id=r.last_inbound_id;

    update public.ai_conversations
       set status='open', metadata=(coalesce(metadata,'{}'::jsonb)-'aiProcessing'-'aiFollowup')
     where id=r.conversation_id;

    recovered := recovered + 1;
  end loop;
  return recovered;
end
$function$
;

-- FUNCAO public.ai_meta_token_refresh_claim
CREATE OR REPLACE FUNCTION public.ai_meta_token_refresh_claim(p_token text)
 RETURNS boolean
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare
  claimed integer;
  checked_at timestamptz := clock_timestamp();
begin
  update private.instagram_runtime_credentials
  set metadata = coalesce(metadata, '{}'::jsonb) || jsonb_build_object(
    'refreshAttemptAt', checked_at,
    'nextRefreshAttemptAt', checked_at + interval '6 hours'
  )
  where id = true and access_token = p_token
    and expires_at > checked_at
    and expires_at <= checked_at + interval '14 days'
    and coalesce(nullif(metadata->>'issuedAt','')::timestamptz, updated_at) <= checked_at - interval '24 hours'
    and coalesce(metadata->>'validatedHost','') = 'graph.instagram.com'
    and coalesce(metadata->>'tokenType', case when token_source in ('instagram_refresh_access_token','instagram_exchange_token') then 'long_lived' end) = 'long_lived'
    and (metadata->>'nextRefreshAttemptAt' is null or (metadata->>'nextRefreshAttemptAt')::timestamptz <= checked_at);
  get diagnostics claimed = row_count;
  return claimed = 1;
end
$function$
;

-- FUNCAO public.ai_meta_token_refresh_commit
CREATE OR REPLACE FUNCTION public.ai_meta_token_refresh_commit(p_previous_token text, p_token text, p_expires_at timestamp with time zone, p_metadata jsonb)
 RETURNS boolean
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare
  saved integer;
begin
  if p_token is null or length(p_token) < 40 or length(p_token) > 4096
    or p_expires_at is null or p_expires_at <= clock_timestamp()
    or p_metadata->>'validatedHost' is distinct from 'graph.instagram.com'
    or p_metadata->>'tokenType' is distinct from 'long_lived'
    or p_metadata->>'accountMatch' is distinct from 'true'
    or nullif(p_metadata->>'issuedAt','') is null
  then return false; end if;
  update private.instagram_runtime_credentials
  set access_token = p_token, token_source = 'instagram_refresh_access_token',
      expires_at = p_expires_at, metadata = p_metadata, updated_at = clock_timestamp()
  where id = true and access_token = p_previous_token
    and metadata->>'refreshAttemptAt' is not null
    and (metadata->>'nextRefreshAttemptAt')::timestamptz > clock_timestamp();
  get diagnostics saved = row_count;
  return saved = 1;
end
$function$
;

-- FUNCAO public.ai_cost_cache_claim
CREATE OR REPLACE FUNCTION public.ai_cost_cache_claim(p_key text, p_owner uuid, p_lease_seconds integer DEFAULT 90)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare r private.ai_cost_cache; ts timestamptz:=clock_timestamp();
begin
  if p_key is null or p_key !~ '^[a-f0-9]{64}$' or p_owner is null then raise exception 'invalid_cache_key'; end if;
  insert into private.ai_cost_cache(cache_key,owner,state,expires_at)
  values(p_key,p_owner,'pending',ts+make_interval(secs=>greatest(30,least(300,p_lease_seconds))))
  on conflict do nothing;
  select * into r from private.ai_cost_cache where cache_key=p_key for update;
  if r.expires_at<=ts then
    update private.ai_cost_cache set owner=p_owner,state='pending',result=null,error=null,
      expires_at=ts+make_interval(secs=>greatest(30,least(300,p_lease_seconds))),updated_at=ts
      where cache_key=p_key returning * into r;
  end if;
  if r.state='ready' then return jsonb_build_object('state','ready','result',r.result); end if;
  if r.state='failed' then return jsonb_build_object('state','failed','error',r.error); end if;
  return jsonb_build_object('state',case when r.owner=p_owner then 'claimed' else 'pending' end);
end $function$
;

-- FUNCAO public.ai_cost_cache_finish
CREATE OR REPLACE FUNCTION public.ai_cost_cache_finish(p_key text, p_owner uuid, p_result jsonb, p_error text, p_ttl_seconds integer)
 RETURNS boolean
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare changed integer;
begin
  if octet_length(coalesce(p_result::text,''))>250000 then raise exception 'cache_result_large'; end if;
  if p_error is not null and p_error !~ '^model_(http_[0-9]{3}|incomplete|invalid_json|unavailable)$' then raise exception 'invalid_cache_error'; end if;
  update private.ai_cost_cache set state=case when p_error is null then 'ready' else 'failed' end,
    result=case when p_error is null then p_result else null end,error=p_error,
    expires_at=clock_timestamp()+make_interval(secs=>greatest(1,least(case when p_error is null then 604800 else 300 end,p_ttl_seconds))),
    updated_at=clock_timestamp()
    where cache_key=p_key and owner=p_owner and state='pending' and expires_at>clock_timestamp();
  get diagnostics changed=row_count;return changed=1;
end $function$
;

-- FUNCAO public.ai_cost_usage_record
CREATE OR REPLACE FUNCTION public.ai_cost_usage_record(p_service text, p_operation text, p_model text, p_outcome text, p_input_tokens bigint DEFAULT 0, p_output_tokens bigint DEFAULT 0, p_cached_tokens bigint DEFAULT 0, p_elapsed_ms bigint DEFAULT 0, p_images bigint DEFAULT 0)
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
begin
 if p_outcome not in ('api_success','api_error','api_429','cache_hit')
 or p_service !~ '^[a-z0-9_-]{1,80}$' or p_operation !~ '^[a-z0-9_-]{1,80}$'
 or p_model !~ '^[a-zA-Z0-9._:/-]{1,100}$' then raise exception 'invalid_usage_dimensions';end if;
 insert into private.ai_cost_usage_daily as current(day,service,operation,model,outcome,calls,input_tokens,output_tokens,cached_tokens,elapsed_ms,images)
 values((clock_timestamp() at time zone 'UTC')::date,p_service,p_operation,p_model,p_outcome,1,
 greatest(0,least(10000000,p_input_tokens)),greatest(0,least(10000000,p_output_tokens)),
 greatest(0,least(p_input_tokens,p_cached_tokens)),greatest(0,least(300000,p_elapsed_ms)),greatest(0,least(100,p_images)))
 on conflict(day,service,operation,model,outcome) do update set calls=current.calls+1,
 input_tokens=current.input_tokens+excluded.input_tokens,output_tokens=current.output_tokens+excluded.output_tokens,
 cached_tokens=current.cached_tokens+excluded.cached_tokens,elapsed_ms=current.elapsed_ms+excluded.elapsed_ms,images=current.images+excluded.images;
end $function$
;

-- FUNCAO public.ai_story_capture_store
CREATE OR REPLACE FUNCTION public.ai_story_capture_store(p_message uuid, p_account text, p_story text, p_prefetch jsonb, p_reference jsonb, p_path text)
 RETURNS boolean
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare changed integer;
begin
 if p_story !~ '^[0-9]{5,40}$' or p_account !~ '^[0-9]{5,40}$'
 or (p_path is not null and (p_path !~ '^instagram-story-cache/(image|video)/[0-9]{5,40}/[a-f0-9-]{36}\.(jpg|jpeg|png|webp|gif|mp4|mov|webm)$' or split_part(p_path,'/',3)<>p_story))
 or jsonb_typeof(p_prefetch)<>'object' or jsonb_typeof(p_reference)<>'object'
 then raise exception 'invalid_story_capture';end if;
 update public.ai_messages set raw_payload=jsonb_set(jsonb_set(raw_payload,'{storyPrefetch}',p_prefetch),'{storyReference}',
 coalesce(raw_payload->'storyReference','{}'::jsonb)||(p_reference-'id'-'url')),
 media_path=coalesce(p_path,media_path)
 where id=p_message and direction='inbound' and raw_payload->>'channel'='instagram'
 and raw_payload->>'accountId'=p_account and raw_payload->'storyReference'->>'id'=p_story;
 get diagnostics changed=row_count;return changed=1;
end $function$
;

-- INDICE ai_human_waits
CREATE UNIQUE INDEX ai_human_waits_pkey ON public.ai_human_waits USING btree (conversation_id);

-- INDICE ai_human_waits
CREATE INDEX ai_human_waits_due ON public.ai_human_waits USING btree (due_at) WHERE (state = 'waiting'::text);

-- INDICE ai_instagram_reviews
CREATE UNIQUE INDEX ai_instagram_reviews_pkey ON public.ai_instagram_reviews USING btree (run_id, page);

-- INDICE ai_instagram_turn_queue
CREATE UNIQUE INDEX ai_instagram_turn_queue_pkey ON public.ai_instagram_turn_queue USING btree (conversation_id);

-- INDICE ai_instagram_turn_queue
CREATE INDEX ai_instagram_turn_queue_due_idx ON public.ai_instagram_turn_queue USING btree (not_before) WHERE (state = 'queued'::text);

-- INDICE ai_story_products
CREATE UNIQUE INDEX ai_story_products_pkey ON public.ai_story_products USING btree (story_id);

-- INDICE ai_story_products
CREATE INDEX ai_story_products_product_idx ON public.ai_story_products USING btree (product_id);

-- INDICE ai_worker_sources
CREATE UNIQUE INDEX ai_worker_sources_pkey ON public.ai_worker_sources USING btree (bundle, name);

-- INDICE ai_settings
CREATE UNIQUE INDEX ai_settings_pkey ON public.ai_settings USING btree (key);

-- INDICE ai_conversations
CREATE UNIQUE INDEX ai_conversations_pkey ON public.ai_conversations USING btree (id);

-- INDICE ai_conversations
CREATE UNIQUE INDEX ai_conversations_channel_external_thread_id_key ON public.ai_conversations USING btree (channel, external_thread_id);

-- INDICE ai_conversations
CREATE INDEX ai_conversations_last_message_idx ON public.ai_conversations USING btree (last_message_at DESC);

-- INDICE ai_conversations
CREATE UNIQUE INDEX ai_conversations_channel_thread_key ON public.ai_conversations USING btree (channel, external_user_id, external_thread_id);

-- INDICE ai_conversations
CREATE INDEX ai_conversations_status_idx ON public.ai_conversations USING btree (status, last_message_at DESC);

-- INDICE ai_messages
CREATE UNIQUE INDEX ai_messages_pkey ON public.ai_messages USING btree (id);

-- INDICE ai_messages
CREATE UNIQUE INDEX ai_messages_external_message_id_uq ON public.ai_messages USING btree (external_message_id) WHERE (external_message_id IS NOT NULL);

-- INDICE ai_messages
CREATE INDEX ai_messages_conversation_created_idx ON public.ai_messages USING btree (conversation_id, created_at DESC);

-- INDICE ai_messages
CREATE UNIQUE INDEX ai_messages_external_id_key ON public.ai_messages USING btree (external_message_id) WHERE (external_message_id IS NOT NULL);

-- INDICE ai_messages
CREATE INDEX ai_messages_conversation_idx ON public.ai_messages USING btree (conversation_id, created_at DESC);

-- INDICE ai_handoffs
CREATE UNIQUE INDEX ai_handoffs_pkey ON public.ai_handoffs USING btree (id);

-- INDICE ai_handoffs
CREATE INDEX ai_handoffs_conversation_idx ON public.ai_handoffs USING btree (conversation_id, created_at DESC);

-- INDICE ai_product_matches
CREATE UNIQUE INDEX ai_product_matches_pkey ON public.ai_product_matches USING btree (id);

-- INDICE ai_product_matches
CREATE UNIQUE INDEX ai_product_matches_message_id_product_id_key ON public.ai_product_matches USING btree (message_id, product_id);

-- INDICE ai_product_matches
CREATE INDEX ai_product_matches_message_idx ON public.ai_product_matches USING btree (message_id);

-- INDICE ai_webhook_events
CREATE UNIQUE INDEX ai_webhook_events_pkey ON public.ai_webhook_events USING btree (id);

-- INDICE ai_webhook_events
CREATE UNIQUE INDEX ai_webhook_events_channel_event_key ON public.ai_webhook_events USING btree (channel, event_id);

-- INDICE ai_webhook_events
CREATE INDEX ai_webhook_events_created_idx ON public.ai_webhook_events USING btree (created_at DESC);

-- INDICE ai_optouts
CREATE UNIQUE INDEX ai_optouts_pkey ON public.ai_optouts USING btree (id);

-- INDICE ai_optouts
CREATE UNIQUE INDEX ai_optouts_channel_user_key ON public.ai_optouts USING btree (channel, external_user_id);

-- INDICE ai_logs
CREATE UNIQUE INDEX ai_logs_pkey ON public.ai_logs USING btree (id);

-- INDICE ai_logs
CREATE INDEX ai_logs_created_idx ON public.ai_logs USING btree (created_at DESC);

-- INDICE ai_logs
CREATE INDEX ai_logs_kind_idx ON public.ai_logs USING btree (kind, created_at DESC);

-- INDICE ai_logs
CREATE INDEX ai_logs_conv_idx ON public.ai_logs USING btree (conversation_id, created_at DESC);

-- CRON ferreira-instagram-quiet-worker [5 seconds]
select public.ai_ig_dispatch();

-- CRON ferreira-story-registry-learn [*/2 * * * *]
select public.ai_learn_story_products();

-- CRON ferreira-instagram-story-cache-cleanup [17 4 * * *]

      select net.http_post(
        url:='https://nailfzcujyxydqldktgg.supabase.co/functions/v1/instagram-story-cache-cleanup',
        headers:=jsonb_build_object(
          'Content-Type','application/json',
          'x-ai-followup-token',(select secret from private.ai_followup_config where id=true)
        ),
        body:='{}'::jsonb,
        timeout_milliseconds:=90000
      );
    

-- CRON ferreira-instagram-token-guardian [*/5 * * * *]

  select net.http_post(
    url:='https://nailfzcujyxydqldktgg.supabase.co/functions/v1/instagram-token-guardian',
    headers:=jsonb_build_object('Content-Type','application/json','x-ai-followup-token',(select secret from private.ai_followup_config where id=true)),
    body:='{}'::jsonb,
    timeout_milliseconds:=30000
  );
  

-- CRON ferreira-story-publisher [* * * * *]

 select net.http_post(url:='https://nailfzcujyxydqldktgg.supabase.co/functions/v1/story-studio',
 headers:=jsonb_build_object('Content-Type','application/json','x-story-worker-token',(select secret from private.story_worker_config where id=true)),
 body:='{"action":"tick"}'::jsonb,timeout_milliseconds:=90000)
 where not exists(select 1 from public.story_studio_state where key='connection')
 or exists(select 1 from public.story_studio_state where key='connection' and (value->>'refreshRequested'='true' or updated_at<now()-interval '6 hours'))
 or (exists(select 1 from public.story_sequences where archived=false and status in ('scheduled','publishing') and scheduled_at<=now() and (lock_until is null or lock_until<now()))
 and not exists(select 1 from public.story_sequences where archived=false and ((lock_until>now() and lock_owner is not null) or status='uncertain' or (status in ('failed','awaiting_manual') and items @> '[{"status":"published"}]'::jsonb))));
 

-- CRON ferreira-human-followup [* * * * *]

 select public.ai_recover_followups();
 select net.http_post(url:='https://nailfzcujyxydqldktgg.supabase.co/functions/v1/human-followup',
 headers:=jsonb_build_object('Content-Type','application/json','x-ai-followup-token',(select secret from private.ai_followup_config where id=true)),
 body:='{"action":"tick"}'::jsonb,timeout_milliseconds:=90000)
 where exists(select 1 from public.ai_conversations c0 join public.ai_human_waits w0 on w0.conversation_id=c0.id
 where not (c0.channel='instagram' and exists(select 1 from public.ai_settings where key='instagram_turn_policy' and value->>'enabled'='true' and value->>'workerFunction'='instagram-turn-worker-v6'))
 and w0.state='waiting' and ((c0.status='human' and w0.due_at<=now() and c0.metadata ? 'manualEchoObservedAt') or (c0.status='open' and (w0.updated_at<now()-interval '30 seconds' or c0.channel='instagram') and (w0.due_at is null or w0.due_at<=now())))
 and w0.inbound_at>now()-interval '24 hours'
 and not exists(select 1 from public.ai_instagram_turn_queue q where q.conversation_id=c0.id and (q.last_inbound_id<>w0.last_inbound_id or q.state<>'ready' or q.due_at>clock_timestamp() or q.not_before>clock_timestamp()))
 and not(c0.metadata ? 'aiProcessing')
 and not exists(select 1 from public.ai_optouts o where o.channel=c0.channel and o.external_user_id=c0.external_user_id));
 

-- CRON ferreira-ai-cost-cache-cleanup [31 4 * * *]

 delete from private.ai_cost_cache where expires_at<now()-interval '1 day';
 delete from private.ai_cost_usage_daily where day<current_date-180;


-- TABELA private.ai_cost_cache
cache_key text not null,
owner uuid not null,
state text not null,
result jsonb,
error text,
expires_at timestamp with time zone not null,
updated_at timestamp with time zone default clock_timestamp() not null

-- TABELA private.ai_cost_usage_daily
day date not null,
service text not null,
operation text not null,
model text not null,
outcome text not null,
calls bigint default 0 not null,
input_tokens bigint default 0 not null,
output_tokens bigint default 0 not null,
cached_tokens bigint default 0 not null,
elapsed_ms bigint default 0 not null,
images bigint default 0 not null

-- TABELA private.ai_followup_config
id boolean default true not null,
secret text not null

-- TABELA private.ai_instagram_release_backup
release text not null,
definitions jsonb not null,
saved_at timestamp with time zone default now() not null

-- TABELA private.instagram_runtime_credentials
id boolean default true not null,
access_token text not null,
token_source text default 'runtime_refresh'::text not null,
expires_at timestamp with time zone,
metadata jsonb default '{}'::jsonb not null,
updated_at timestamp with time zone default clock_timestamp() not null

-- TABELA public.ai_conversations
id uuid default gen_random_uuid() not null,
channel text not null,
external_user_id text not null,
external_thread_id text not null,
customer_name text,
status text default 'open'::text not null,
last_message_at timestamp with time zone default now() not null,
metadata jsonb default '{}'::jsonb not null,
created_at timestamp with time zone default now() not null,
updated_at timestamp with time zone default now() not null

-- TABELA public.ai_handoffs
id uuid default gen_random_uuid() not null,
conversation_id uuid not null,
reason text not null,
status text default 'open'::text not null,
created_at timestamp with time zone default now() not null,
resolved_at timestamp with time zone

-- TABELA public.ai_human_waits
conversation_id uuid not null,
last_inbound_id uuid not null,
inbound_at timestamp with time zone not null,
waiting_since timestamp with time zone not null,
due_at timestamp with time zone,
state text not null,
generation uuid default gen_random_uuid() not null,
unread boolean default true not null,
category text,
reason text,
policy_revision text,
last_human_at timestamp with time zone,
updated_at timestamp with time zone default now() not null,
technical_attempts integer default 0 not null

-- TABELA public.ai_instagram_reviews
run_id text not null,
page integer not null,
result jsonb not null,
created_at timestamp with time zone default now() not null

-- TABELA public.ai_instagram_turn_queue
conversation_id uuid not null,
last_inbound_id uuid not null,
received_at timestamp with time zone not null,
due_at timestamp with time zone not null,
not_before timestamp with time zone not null,
state text not null,
owner uuid,
lease_until timestamp with time zone,
attempts integer default 0 not null,
after_human_wait boolean default false not null,
updated_at timestamp with time zone default now() not null

-- TABELA public.ai_logs
id uuid default gen_random_uuid() not null,
level text default 'info'::text not null,
kind text not null,
channel text,
conversation_id uuid,
detail jsonb default '{}'::jsonb not null,
created_at timestamp with time zone default now() not null

-- TABELA public.ai_messages
id uuid default gen_random_uuid() not null,
conversation_id uuid not null,
direction text not null,
message_type text default 'text'::text not null,
external_message_id text,
text_content text,
media_path text,
image_analysis jsonb,
raw_payload jsonb,
created_at timestamp with time zone default now() not null

-- TABELA public.ai_optouts
id uuid default gen_random_uuid() not null,
channel text not null,
external_user_id text not null,
reason text,
created_at timestamp with time zone default now() not null

-- TABELA public.ai_product_matches
id uuid default gen_random_uuid() not null,
message_id uuid not null,
product_id uuid not null,
score numeric,
reason text,
created_at timestamp with time zone default now() not null

-- TABELA public.ai_settings
key text not null,
value jsonb default '{}'::jsonb not null,
updated_at timestamp with time zone default now() not null

-- TABELA public.ai_story_products
story_id text not null,
account_id text not null,
product_id uuid not null,
color text,
layout text,
method text not null,
image_hash text,
evidence jsonb default '{}'::jsonb not null,
verified_at timestamp with time zone default now() not null,
expires_at timestamp with time zone,
created_at timestamp with time zone default now() not null,
updated_at timestamp with time zone default now() not null

-- TABELA public.ai_webhook_events
id uuid default gen_random_uuid() not null,
channel text not null,
event_id text not null,
status text default 'received'::text not null,
attempts integer default 1 not null,
payload_digest text,
error_detail text,
created_at timestamp with time zone default now() not null,
processed_at timestamp with time zone

-- TABELA public.ai_worker_sources
bundle text not null,
name text not null,
content text not null,
updated_at timestamp with time zone default now() not null,
sha256 text

-- TABELA public.ig_analytics_account
id bigint default nextval('ig_analytics_account_id_seq'::regclass) not null,
snapshot_at timestamp with time zone default now() not null,
kind text not null,
params jsonb,
data jsonb,
error jsonb

-- TABELA public.ig_analytics_comments
comment_id text not null,
media_id text,
text text,
commented_at timestamp with time zone,
like_count integer,
fetched_at timestamp with time zone default now() not null

-- TABELA public.ig_analytics_media
media_id text not null,
media_type text,
media_product_type text,
caption text,
permalink text,
shortcode text,
posted_at timestamp with time zone,
like_count integer,
comments_count integer,
thumbnail_url text,
media_url text,
children jsonb,
insights jsonb,
insights_metrics ARRAY,
insights_error jsonb,
fetched_at timestamp with time zone default now() not null

-- TABELA public.product_variations
id uuid default gen_random_uuid() not null,
product_id uuid,
size text not null,
color text not null,
stock integer default 0,
created_at timestamp with time zone default now(),
updated_at timestamp with time zone default now()

-- TABELA public.products
id uuid default gen_random_uuid() not null,
name text not null,
sku text,
category text,
fabric text,
gender text default 'Feminino'::text,
sale_price numeric default 0,
cost_price numeric default 0,
status text default 'Ativo'::text,
notes text,
photo_url text,
created_at timestamp with time zone default now(),
updated_at timestamp with time zone default now(),
catalog_media jsonb default '{"colors": [], "version": 1}'::jsonb not null,
catalog_attributes jsonb default '{}'::jsonb not null,
search_aliases ARRAY default '{}'::text[] not null,
deleted_at timestamp with time zone,
deleted_by uuid,
deleted_reason text