alter table atendimento.tratamentos add column ativo boolean not null default true;
alter table atendimento.tratamentos add column liberado_em timestamptz;
alter table atendimento.tratamentos add column liberacao_motivo text;
drop index atendimento.tratamentos_direct_idx;
drop index atendimento.tratamentos_comment_idx;
create unique index tratamentos_direct_ativo_idx on atendimento.tratamentos(conversation_id,last_inbound_id) where conversation_id is not null and ativo;
create unique index tratamentos_comment_ativo_idx on atendimento.tratamentos(comment_id) where comment_id is not null and ativo;

-- Mescla o hash sem regravar um raw_payload possivelmente alterado por outros gatilhos.
create or replace function public.ai_atendimento_registrar_midia(p_message uuid,p_path text,p_image_hash text default null) returns boolean
language plpgsql security definer set search_path = '' as $$
declare m record;
begin
  select msg.id,msg.conversation_id,msg.direction,msg.message_type,c.channel into m
    from public.ai_messages msg join public.ai_conversations c on c.id=msg.conversation_id
    where msg.id=p_message for update of msg;
  if not found or m.channel<>'instagram' or m.direction<>'inbound' then return false; end if;
  if p_path not like ('instagram/'||m.conversation_id::text||'/'||m.id::text||'.%')
     or p_path !~* '^instagram/[a-f0-9-]{36}/[a-f0-9-]{36}\.[a-z0-9]{2,12}$' then return false; end if;
  if p_image_hash is not null and (m.message_type<>'image' or p_image_hash !~ '^[a-f0-9]{64}$') then return false; end if;
  update public.ai_messages set media_path=p_path,
    raw_payload=case when p_image_hash is null then raw_payload
      else coalesce(raw_payload,'{}'::jsonb)||jsonb_build_object('imageHash',p_image_hash) end
    where id=p_message;
  return true;
end $$;
revoke all on function public.ai_atendimento_registrar_midia(uuid,text,text) from public,anon,authenticated;
grant execute on function public.ai_atendimento_registrar_midia(uuid,text,text) to service_role;

-- Áudio transcrito depois de um lote também pode conter pedido de parada.
-- O opt-out fica visível para a guarda de envio antes da próxima parte.
create or replace function private.ai_atendimento_audio_optout() returns trigger
language plpgsql security definer set search_path = '' as $$
declare cliente text;
begin
  if atendimento.modo_atual()<>'claude' or new.direction<>'inbound' or new.message_type<>'audio'
     or nullif(trim(coalesce(new.text_content,'')),'') is null
     or new.text_content is not distinct from old.text_content then return new; end if;
  if new.text_content !~* '(par(e|ar) de (me )?(mandar|enviar)|n[ãa]o quero (mais )?receber|descadastr|sair da lista|me remov|cancelar? (o )?recebimento|^[[:space:]]*(sair|parar|stop)[[:space:]]*$)' then return new; end if;
  select c.external_user_id into cliente from public.ai_conversations c
    where c.id=new.conversation_id and c.channel='instagram';
  if cliente is not null then
    insert into public.ai_optouts(channel,external_user_id,reason)
      values('instagram',cliente,'pedido explícito da cliente em áudio')
      on conflict(channel,external_user_id) do nothing;
  end if;
  return new;
end $$;
create trigger ai_atendimento_audio_optout_after_update after update of text_content on public.ai_messages
  for each row execute function private.ai_atendimento_audio_optout();

create or replace function atendimento.liberar_tratamento(p_lote text,p_n text,p_motivo text) returns boolean
language plpgsql security definer set search_path = '' as $$
begin
  if exists(select 1 from atendimento.envios e where e.lote=p_lote and e.n=p_n and e.status in ('enviado','enviado_instagram','enviando','incerto')) then return false; end if;
  update atendimento.tratamentos set ativo=false,liberado_em=now(),liberacao_motivo=p_motivo
    where lote=p_lote and n=p_n and ativo
      and not exists(select 1 from atendimento.pulos p where p.lote=p_lote and p.conversation_id is not distinct from tratamentos.conversation_id and p.comment_id is not distinct from tratamentos.comment_id);
  return found;
end $$;

-- Ao voltar para a IA, as respostas ainda na fila são canceladas. Itens sem
-- nenhuma parte entregue podem aparecer em um lote futuro se o modo mudar de novo.
create or replace function atendimento.modo(p_modo text default null) returns text
language plpgsql security definer set search_path = '' as $$
declare pendente record;
begin
  if p_modo is not null and p_modo not in ('claude','ia') then raise exception 'modo inválido'; end if;
  if p_modo is not null then
    insert into public.ai_settings(key,value) values('atendimento_modo',jsonb_build_object('instagram',p_modo))
      on conflict(key) do update set value=jsonb_build_object('instagram',p_modo),updated_at=now();
    insert into public.ai_logs(level,kind,channel,detail)
      values('info','atendimento_modo','instagram',jsonb_build_object('modo',p_modo));
    if p_modo='ia' then
      for pendente in select distinct lote,n from atendimento.envios where status='fila' loop
        update atendimento.envios set status='cancelado',erro='modo alterado para ia'
          where lote=pendente.lote and n=pendente.n and status='fila';
        perform atendimento.liberar_tratamento(pendente.lote,pendente.n,'modo_ia');
      end loop;
    end if;
  end if;
  return atendimento.modo_atual();
end $$;

create or replace function atendimento.claim_envio() returns jsonb
language plpgsql security definer set search_path = '' as $$
declare e atendimento.envios; li atendimento.lote_itens; c public.ai_conversations; last_inbound uuid; last_shop timestamptz;
  token_owner uuid:=gen_random_uuid(); row_count int:=0;
begin
  if atendimento.modo_atual()<>'claude' then return null; end if;
  perform pg_advisory_xact_lock(260927,1);
  update atendimento.envios set status='incerto',erro='lease expirado; conferir Meta antes de tentar novamente'
    where status='enviando' and lease_ate<now();
  if (select count(*) from atendimento.envios where status='enviando' and lease_ate>now())>=5 then return null; end if;
  update atendimento.envios q set status='cancelado',erro='parte anterior não enviada'
    where q.status='fila' and exists(select 1 from atendimento.envios prior
      where prior.lote=q.lote and prior.n=q.n and prior.parte<q.parte and prior.status not in ('enviado','fila','enviando'));
  for e in select * from atendimento.envios q
    where q.status='fila' and q.enviar_apos<=now()
      and not exists(select 1 from atendimento.envios prior where prior.lote=q.lote and prior.n=q.n and prior.parte<q.parte and prior.status<>'enviado')
    order by q.enviar_apos,q.criado_em for update skip locked limit 10
  loop
    select * into li from atendimento.lote_itens where lote=e.lote and n=e.n;
    if li.tipo='direct' then
      select * into c from public.ai_conversations where id=li.conversation_id for update;
      if exists(select 1 from atendimento.envios other_e
        join atendimento.lote_itens other_li on other_li.lote=other_e.lote and other_li.n=other_e.n
        where other_e.status='enviando' and (other_e.lote,other_e.n)<>(e.lote,e.n)
          and other_li.conversation_id=li.conversation_id) then continue; end if;
      select m.id into last_inbound from public.ai_messages m where m.conversation_id=c.id and m.direction='inbound' order by m.created_at desc,m.id desc limit 1;
      if last_inbound is distinct from li.last_inbound_id then
        update atendimento.envios set status='nova_mensagem' where lote=e.lote and n=e.n and status='fila';
        continue;
      end if;
      select max(m.created_at) into last_shop from public.ai_messages m where m.conversation_id=c.id and m.direction='outbound'
        and m.created_at>li.criado_em and coalesce(m.raw_payload->>'origem','')<>'claude';
      if last_shop is not null then
        update atendimento.envios set status='equipe_respondeu' where lote=e.lote and n=e.n and status='fila';
        continue;
      end if;
      if li.ultima_cliente_em<=now()-interval '24 hours' then
        update atendimento.envios set status='fora_da_janela' where lote=e.lote and n=e.n and status='fila';
        perform atendimento.liberar_tratamento(e.lote,e.n,'fora_da_janela');
        continue;
      end if;
      if exists(select 1 from public.ai_optouts o where o.channel='instagram' and o.external_user_id=c.external_user_id) then
        update atendimento.envios set status='cancelado',erro='opt-out' where lote=e.lote and n=e.n and status='fila';
        continue;
      end if;
      update public.ai_conversations set metadata=coalesce(metadata,'{}'::jsonb)||jsonb_build_object('aiProcessing',jsonb_build_object('owner',token_owner,'expiresAt',now()+interval '120 seconds','atendimentoLote',e.lote)) where id=c.id;
    elsif li.tipo='comentario' then
      perform 1 from atendimento.comentarios where id=li.comment_id for update;
      if exists(select 1 from atendimento.envios other_e
        join atendimento.lote_itens other_li on other_li.lote=other_e.lote and other_li.n=other_e.n
        where other_e.status='enviando' and (other_e.lote,other_e.n)<>(e.lote,e.n)
          and other_li.comment_id=li.comment_id) then continue; end if;
      if exists(select 1 from atendimento.comentarios where id=li.comment_id and loja_respondeu) then
        update atendimento.envios set status='equipe_respondeu' where lote=e.lote and n=e.n and status='fila';
        continue;
      end if;
    else
      update atendimento.envios set status='fora_da_janela' where lote=e.lote and n=e.n and status='fila';
      continue;
    end if;
    update atendimento.envios set status='enviando',owner=token_owner,lease_ate=now()+interval '120 seconds',tentativas=tentativas+1
      where lote=e.lote and n=e.n and parte=e.parte;
    return jsonb_build_object('lote',e.lote,'n',e.n,'parte',e.parte,'texto',e.texto,'tipo',li.tipo,
      'recipient',case when li.tipo='direct' then c.external_user_id else null end,
      'commentId',li.comment_id,'conversationId',li.conversation_id,'owner',token_owner,'enviarApos',e.enviar_apos);
  end loop;
  return null;
end $$;

create or replace function atendimento.envio_autorizado(p_lote text,p_n text,p_parte int,p_owner uuid) returns boolean
language plpgsql security definer set search_path = '' as $$
declare e atendimento.envios; li atendimento.lote_itens; latest uuid; manual_at timestamptz; why text;
begin
  select * into e from atendimento.envios where lote=p_lote and n=p_n and parte=p_parte for update;
  if not found or e.status<>'enviando' or e.owner is distinct from p_owner or e.lease_ate<=now() then return false; end if;
  select * into li from atendimento.lote_itens where lote=p_lote and n=p_n;
  if atendimento.modo_atual()<>'claude' then why:='cancelado';
  elsif li.tipo='direct' then
    select m.id into latest from public.ai_messages m where m.conversation_id=li.conversation_id and m.direction='inbound' order by m.created_at desc,m.id desc limit 1;
    select max(m.created_at) into manual_at from public.ai_messages m where m.conversation_id=li.conversation_id
      and m.direction='outbound' and m.created_at>li.criado_em and coalesce(m.raw_payload->>'origem','')<>'claude';
    if latest is distinct from li.last_inbound_id then why:='nova_mensagem';
    elsif manual_at is not null then why:='equipe_respondeu';
    elsif li.ultima_cliente_em<=now()-interval '24 hours' then why:='fora_da_janela';
    elsif exists(select 1 from public.ai_conversations c join public.ai_optouts o on o.channel='instagram' and o.external_user_id=c.external_user_id where c.id=li.conversation_id) then why:='cancelado'; end if;
  elsif li.tipo='comentario' and exists(select 1 from atendimento.comentarios where id=li.comment_id and (loja_respondeu or hidden)) then why:='equipe_respondeu'; end if;
  if why is not null then
    update atendimento.envios set status=why,erro=case when why='cancelado' then 'modo ia' else null end,lease_ate=null
      where lote=p_lote and n=p_n and parte>=p_parte and status in ('fila','enviando');
    if why in ('fora_da_janela','cancelado') then perform atendimento.liberar_tratamento(p_lote,p_n,why); end if;
    if li.conversation_id is not null then
      update public.ai_conversations set metadata=coalesce(metadata,'{}'::jsonb)-'aiProcessing'
        where id=li.conversation_id and metadata->'aiProcessing'->>'owner'=p_owner::text;
    end if;
    return false;
  end if;
  return true;
end $$;

create or replace function atendimento.concluir_envio(p_lote text,p_n text,p_parte int,p_owner uuid,p_message_id text default null,p_erro text default null) returns text
language plpgsql security definer set search_path = '' as $$
declare e atendimento.envios; li atendimento.lote_itens; existing uuid;
begin
  select * into e from atendimento.envios where lote=p_lote and n=p_n and parte=p_parte for update;
  if not found or e.owner is distinct from p_owner then return 'estado_invalido'; end if;
  if e.status='enviado' and e.message_id is not distinct from p_message_id then return 'enviado'; end if;
  if e.status in ('incerto','erro','cancelado') and p_message_id is null then return e.status; end if;
  if e.status<>'enviando' then return 'estado_invalido'; end if;
  select * into li from atendimento.lote_itens where lote=p_lote and n=p_n;
  if p_message_id is null then
    update atendimento.envios set status=case when coalesce(p_erro,'') like 'meta_delivery_unknown:%' then 'incerto' else 'erro' end,
      erro=left(coalesce(p_erro,'erro_desconhecido'),500),lease_ate=null where lote=p_lote and n=p_n and parte=p_parte;
    update atendimento.envios set status='cancelado',erro='parte anterior falhou' where lote=p_lote and n=p_n and parte>p_parte and status='fila';
    if coalesce(p_erro,'') not like 'meta_delivery_unknown:%' then perform atendimento.liberar_tratamento(p_lote,p_n,'erro_definitivo'); end if;
    if li.conversation_id is not null then update public.ai_conversations set metadata=coalesce(metadata,'{}'::jsonb)-'aiProcessing' where id=li.conversation_id and metadata->'aiProcessing'->>'owner'=p_owner::text; end if;
    return case when coalesce(p_erro,'') like 'meta_delivery_unknown:%' then 'incerto' else 'erro' end;
  end if;
  update atendimento.envios set status='enviado',message_id=p_message_id,erro=null,lease_ate=null,enviado_em=now() where lote=p_lote and n=p_n and parte=p_parte;
  update atendimento.envios set enviar_apos=greatest(enviar_apos,now()+interval '3 seconds')
    where lote=p_lote and n=p_n and parte=p_parte+1 and status='fila';
  if li.tipo='direct' then
    select id into existing from public.ai_messages where external_message_id=p_message_id limit 1;
    if existing is null then
      begin
        insert into public.ai_messages(conversation_id,direction,message_type,external_message_id,text_content,raw_payload)
          values(li.conversation_id,'outbound','text',p_message_id,e.texto,jsonb_build_object('origem','claude','lote',p_lote,'n',p_n,'parte',p_parte,'enviado',true));
      exception when unique_violation then null;
      end;
    end if;
    update public.ai_messages set raw_payload=coalesce(raw_payload,'{}'::jsonb)||jsonb_build_object('origem','claude','lote',p_lote,'n',p_n,'parte',p_parte,'enviado',true)
      where external_message_id=p_message_id and conversation_id=li.conversation_id;
    update public.ai_conversations set metadata=coalesce(metadata,'{}'::jsonb)-'aiProcessing',last_message_at=now(),updated_at=now()
      where id=li.conversation_id and metadata->'aiProcessing'->>'owner'=p_owner::text;
  elsif li.tipo='comentario' then
    update atendimento.comentarios set loja_respondeu=true,atualizado_em=now() where id=li.comment_id;
  end if;
  return 'enviado';
end $$;

create or replace function atendimento.registrar_story(p_story text,p_product_id uuid,p_cor text,p_letra text,p_evidence jsonb default '{}'::jsonb) returns boolean
language plpgsql security definer set search_path = '' as $$
begin
  if p_story !~ '^\d{5,40}$' or not exists(select 1 from public.products p where p.id=p_product_id and p.deleted_at is null and lower(p.status)='ativo') then return false; end if;
  if p_cor is not null and not exists(select 1 from public.product_variations v where v.product_id=p_product_id and public.ai_color_key(v.color)=public.ai_color_key(p_cor)) then return false; end if;
  insert into public.ai_story_products(story_id,account_id,product_id,color,method,verified_at,expires_at,evidence)
    values(p_story,'17841454587986765',p_product_id,p_cor,'postagem',now(),now()+interval '30 days',p_evidence||jsonb_build_object('letra',p_letra))
    on conflict(story_id) do nothing;
  return found;
end $$;

select cron.schedule('ferreira-atendimento-sync','*/10 * * * *',$$select atendimento.sincronizar() where atendimento.modo_atual()='claude'$$);
select cron.schedule('ferreira-atendimento-enviar','* * * * *',$$
  select net.http_post(url:='https://nailfzcujyxydqldktgg.supabase.co/functions/v1/atendimento-enviar',
    body:='{}'::jsonb,
    headers:=jsonb_build_object('Content-Type','application/json','x-ai-followup-token',(select secret from private.ai_followup_config where id=true)),
    timeout_milliseconds:=90000)
  where atendimento.modo_atual()='claude' and exists(select 1 from atendimento.envios where status='fila' and enviar_apos<=now())
$$);

revoke all on all functions in schema atendimento from public,anon,authenticated;
grant execute on all functions in schema atendimento to service_role;
