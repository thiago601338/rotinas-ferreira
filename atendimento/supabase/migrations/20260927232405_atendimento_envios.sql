create or replace function atendimento.preco_valido(p_valor numeric) returns boolean
language sql stable security definer set search_path = '' as $$
  select exists(
    select 1 from public.products p
    where lower(p.status)='ativo' and p.deleted_at is null
      and (p.sale_price=p_valor or
        floor((round(p.sale_price*100)::bigint*(10000-coalesce((select (value->>'cashDiscountBps')::int from public.ai_settings where key='public_installment_policy'),0))+5000)/10000.0)/100.0=p_valor)
  )
$$;

-- Referências que a pessoa realmente viu no turno do lote. Mais de uma impede
-- aprender um SKU único por engano; mensagens de texto posteriores mantêm o vínculo.
create or replace function atendimento.referencias_turno(p_conversation uuid,p_inbound uuid,p_outbound uuid)
returns table(tipo text,referencia text)
language sql stable security definer set search_path = '' as $$
  with recentes as (
    select m.id,m.message_type,m.media_path,m.raw_payload from public.ai_messages m
    join public.ai_messages anchor on anchor.id=p_inbound
    left join public.ai_messages loja on loja.id=p_outbound
    where m.conversation_id=p_conversation and m.direction='inbound'
      and (m.created_at,m.id)<=(anchor.created_at,anchor.id)
      and (loja.id is null or m.created_at>loja.created_at)
    order by m.created_at desc,m.id desc limit 8
  ), referencias as (
    select case when jsonb_typeof(m.raw_payload->'storyReference')='object' then 'story'
      when jsonb_typeof(m.raw_payload->'postReference')='object' or nullif(m.raw_payload->>'sharedMediaId','') is not null then 'post'
      when m.raw_payload->>'mediaType'='video' then 'video'
      when m.message_type='image' or m.raw_payload->>'mediaType'='image' then 'foto' end tipo,
      coalesce(nullif(m.raw_payload->'storyReference'->>'id',''),nullif(m.raw_payload->>'sharedMediaId',''),
        nullif(m.raw_payload->'postReference'->>'id',''),nullif(m.raw_payload->>'imageHash',''),
        nullif(m.raw_payload->'mediaCache'->>'sha256',''),'sem-id:'||m.id::text) referencia
    from recentes m
  ) select distinct r.tipo,r.referencia from referencias r where r.tipo is not null
$$;

create or replace function atendimento.responder(p_lote text,p_itens jsonb,p_ensaio boolean default false) returns text
language plpgsql security definer set search_path = '' as $$
declare j jsonb; item atendimento.lote_itens; msg text; v_n text; msgs jsonb; i int; v_valor text; price numeric;
  v_sku text; cor text; produto_id uuid; motivo text; line text; out_text text:=''; j_text text:=''; count_msgs int; ref text; treatment_id bigint;
  ref_tipo text; ref_count int; aprendizado text; learned_rows int;
begin
  if atendimento.modo_atual()<>'claude' then return 'modo ia: envio indisponível'; end if;
  if jsonb_typeof(p_itens) is distinct from 'array' then return 'rejeitado: p_itens precisa ser uma lista'; end if;
  if not exists(select 1 from atendimento.lotes where id=p_lote and expira_em>now()) then return 'rejeitado: lote inexistente ou vencido'; end if;
  for j in select value from jsonb_array_elements(p_itens) loop
    v_n:=j->>'n';
    select * into item from atendimento.lote_itens li where li.lote=p_lote and li.n=v_n;
    if not found then out_text:=out_text||'#'||coalesce(v_n,'?')||' rejeitado: item não está no lote'||E'\n'; continue; end if;
    if exists(select 1 from atendimento.envios e where e.lote=p_lote and e.n=v_n) or exists(select 1 from atendimento.pulos p where p.lote=p_lote and ((item.conversation_id is not null and p.conversation_id=item.conversation_id and p.last_inbound_id=item.last_inbound_id) or (item.comment_id is not null and p.comment_id=item.comment_id))) then
      out_text:=out_text||'#'||v_n||' rejeitado: item já tratado'||E'\n'; continue;
    end if;
    if exists(select 1 from atendimento.tratamentos t where t.ativo and ((item.conversation_id is not null and t.conversation_id=item.conversation_id and t.last_inbound_id=item.last_inbound_id) or (item.comment_id is not null and t.comment_id=item.comment_id))) then
      out_text:=out_text||'#'||v_n||' rejeitado: mensagem já tratada em outro lote'||E'\n'; continue;
    end if;
    if j ? 'pular' then
      motivo:=j->>'pular';
      if motivo is null or motivo not in ('pagamento','entrega','reserva','troca','negociacao','identidade','reclamacao','pessoa','equipe_atendendo','audio','sem_peca','sem_dado','nao_entendi','cortesia') then
        out_text:=out_text||'#'||v_n||' rejeitado: motivo de pulo inválido'||E'\n'; continue;
      end if;
      if not p_ensaio then
        treatment_id:=null;
        insert into atendimento.tratamentos(conversation_id,comment_id,last_inbound_id,lote,n)
          values(item.conversation_id,item.comment_id,item.last_inbound_id,p_lote,v_n) on conflict do nothing returning id into treatment_id;
        if treatment_id is null then out_text:=out_text||'#'||v_n||' rejeitado: mensagem já tratada'||E'\n'; continue; end if;
        insert into atendimento.pulos(conversation_id,comment_id,last_inbound_id,motivo,lote)
        values(item.conversation_id,item.comment_id,item.last_inbound_id,motivo,p_lote)
        on conflict do nothing;
      end if;
      out_text:=out_text||'#'||v_n||case when p_ensaio then ' ensaio: pular ' else ' pulado ' end||motivo||E'\n';
      continue;
    end if;
    msgs:=j->'msgs'; count_msgs:=case when jsonb_typeof(msgs)='array' then jsonb_array_length(msgs) else 0 end;
    if count_msgs<1 or count_msgs>(case when item.tipo='comentario' then 1 else 6 end) then
      out_text:=out_text||'#'||v_n||' rejeitado: quantidade de mensagens inválida'||E'\n'; continue;
    end if;
    motivo:=null;
    for i in 0..count_msgs-1 loop
      if jsonb_typeof(msgs->i)<>'string' then motivo:='mensagem não é texto'; exit; end if;
      msg:=trim(msgs->>i);
      if msg='' or length(msg)>950 then motivo:='mensagem vazia ou acima de 950 caracteres'; exit; end if;
      if msg ~* '(op[çc][ãa]o[[:space:]]*[0-9]|(^|\n)[[:space:]]*[0-9]+[.)]|como posso ajudar|assistente|sou uma ia|me chamo|print|reenvi)' then motivo:='texto proibido ou com cara de robô'; exit; end if;
      if regexp_replace(msg,'R\$[[:space:]]*[0-9.]+,[0-9]{2}','','g') ~ 'R\$' then motivo:='valor monetário mal formatado'; exit; end if;
      for v_valor in select (regexp_matches(msg,'R\$[[:space:]]*([0-9.]+,[0-9]{2})','g'))[1] loop
        begin price:=replace(replace(v_valor,'.',''),',','.')::numeric;
        exception when others then motivo:='valor inválido'; exit; end;
        if not atendimento.preco_valido(price) then motivo:='preço não encontrado no catálogo ativo'; exit; end if;
      end loop;
      if motivo is not null then exit; end if;
    end loop;
    if motivo is not null then out_text:=out_text||'#'||v_n||' rejeitado: '||motivo||E'\n'; continue; end if;
    v_sku:=nullif(j->>'produto',''); cor:=nullif(j->>'cor',''); produto_id:=null;
    if v_sku is not null then
      select p.id into produto_id from public.products p where p.sku=v_sku and lower(p.status)='ativo' and p.deleted_at is null;
      if produto_id is null then out_text:=out_text||'#'||v_n||' rejeitado: SKU não ativo'||E'\n'; continue; end if;
      if cor is not null and not exists(select 1 from public.product_variations v where v.product_id=produto_id and public.ai_color_key(v.color)=public.ai_color_key(cor)) then
        out_text:=out_text||'#'||v_n||' rejeitado: cor inexistente no cadastro'||E'\n'; continue;
      end if;
    elsif cor is not null then out_text:=out_text||'#'||v_n||' rejeitado: cor sem produto'||E'\n'; continue;
    end if;
    if item.tipo='direct' and item.ultima_cliente_em<=now()-interval '24 hours' then
      out_text:=out_text||'#'||v_n||' rejeitado: fora da janela da API; peça novo lote'||E'\n'; continue;
    end if;
    if item.tipo='comentario' and exists(select 1 from atendimento.estado where chave='comentarios_permissao' and valor->>'status'='sem_permissao') then
      out_text:=out_text||'#'||v_n||' rejeitado: comentários sem permissão'||E'\n'; continue;
    end if;
    ref:=null; ref_tipo:=null; ref_count:=0; aprendizado:='';
    if produto_id is not null then
      if item.tipo='comentario' then
        select c.media_id into ref from atendimento.comentarios c where c.id=item.comment_id;
        ref_tipo:='post'; ref_count:=case when ref is null then 0 else 1 end;
      else
        select count(*),min(rt.tipo),min(rt.referencia) into ref_count,ref_tipo,ref
          from atendimento.referencias_turno(item.conversation_id,item.last_inbound_id,item.last_outbound_id) rt;
      end if;
      if ref_count>1 then aprendizado:=' · aprendizado não gravado: múltiplas mídias no turno';
      elsif ref_count=0 or (ref_tipo in ('story','post') and ref !~ '^\d{5,40}$') or (ref_tipo='foto' and ref !~ '^[a-f0-9]{64}$') or ref_tipo='video' then
        aprendizado:=' · aprendizado não gravado: referência sem identificador verificável';
      end if;
    end if;
    if not p_ensaio then
      treatment_id:=null;
      insert into atendimento.tratamentos(conversation_id,comment_id,last_inbound_id,lote,n)
        values(item.conversation_id,item.comment_id,item.last_inbound_id,p_lote,v_n) on conflict do nothing returning id into treatment_id;
      if treatment_id is null then out_text:=out_text||'#'||v_n||' rejeitado: mensagem já tratada'||E'\n'; continue; end if;
      if produto_id is not null and ref_count=1 and aprendizado='' then
        if ref_tipo='story' then
          insert into public.ai_story_products(story_id,account_id,product_id,color,method,verified_at,expires_at,evidence)
          values(ref,'17841454587986765',produto_id,cor,'claude_verificado',now(),now()+interval '30 days',jsonb_build_object('lote',p_lote,'item',v_n))
          on conflict(story_id) do update set color=coalesce(excluded.color,ai_story_products.color),method='claude_verificado',verified_at=now(),expires_at=excluded.expires_at
            where ai_story_products.product_id=excluded.product_id;
          get diagnostics learned_rows=row_count;
          if learned_rows=0 then aprendizado:=' · aprendizado não gravado: story já vinculado a outro SKU'; end if;
        elsif ref_tipo='post' then
          insert into atendimento.midia_produto(media_id,product_id,cor,metodo)
          values(ref,produto_id,cor,'claude_verificado')
          on conflict(media_id) do update set cor=excluded.cor,metodo=excluded.metodo
            where midia_produto.product_id=excluded.product_id;
          get diagnostics learned_rows=row_count;
          if learned_rows=0 then aprendizado:=' · aprendizado não gravado: post já vinculado a outro SKU'; end if;
        elsif ref_tipo='foto' then
          insert into public.ai_settings(key,value)
          values('ig_verified_image:17841454587986765:atendimento:'||ref,
            jsonb_build_object('schemaVersion',1,'account','17841454587986765','imageHash',ref,
              'productId',produto_id,'color',cor,'method','claude_verificado','verifiedAt',
              to_char(now() at time zone 'UTC','YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'),'revision','atendimento-20260927-r1'))
          on conflict(key) do update set value=excluded.value,updated_at=now()
            where ai_settings.value->>'productId'=excluded.value->>'productId';
          get diagnostics learned_rows=row_count;
          if learned_rows=0 then aprendizado:=' · aprendizado não gravado: foto já vinculada a outro SKU'; end if;
        end if;
      end if;
      for i in 0..count_msgs-1 loop
        insert into atendimento.envios(lote,n,parte,texto,status,enviar_apos)
        values(p_lote,v_n,i+1,trim(msgs->>i),case when item.tipo='fora' then 'pelo_instagram' else 'fila' end,now()+((i)*interval '3 seconds'));
      end loop;
    end if;
    line:='#'||v_n||case when p_ensaio then ' ensaio: ' else ' aceito: ' end||count_msgs||' mensagem(ns)'||aprendizado;
    if item.tipo='fora' then
      j_text:=j_text||'#'||v_n||' @'||coalesce(item.username,'usuario_indisponivel')||' → ';
      for i in 0..count_msgs-1 loop if i>0 then j_text:=j_text||' | '; end if; j_text:=j_text||'"'||replace(msgs->>i,E'\n','\n')||'"'; end loop;
      j_text:=j_text||E'\n';
    end if;
    out_text:=out_text||line||E'\n';
  end loop;
  if not p_ensaio and exists(select 1 from atendimento.envios e where e.lote=p_lote and e.status='fila') then
    perform net.http_post(url:='https://nailfzcujyxydqldktgg.supabase.co/functions/v1/atendimento-enviar',
      body:='{}'::jsonb,
      headers:=jsonb_build_object('Content-Type','application/json','x-ai-followup-token',(select secret from private.ai_followup_config where id=true)),
      timeout_milliseconds:=90000);
  end if;
  return trim(trailing E'\n' from out_text||j_text);
end $$;

create or replace function atendimento.status(p_lote text) returns text
language sql stable security definer set search_path = '' as $$
  select coalesce(string_agg('#'||x.n||' '||x.estado,' · ' order by x.ord), 'lote sem itens') from (
    select li.n,case when p.motivo is not null then 'pulado '||p.motivo
      when count(e.parte)=0 then 'sem envio'
      when bool_and(e.status='enviado_instagram') then 'enviado_instagram'
      when bool_or(e.status='erro') then 'erro '||coalesce(max(e.erro) filter(where e.status='erro'),'sem detalhe')
      when bool_or(e.status='incerto') then 'incerto'
      when bool_or(e.status='nova_mensagem') then 'nova_mensagem'
      when bool_or(e.status='equipe_respondeu') then 'equipe_respondeu'
      when bool_or(e.status='fora_da_janela') then 'fora_da_janela'
      when bool_or(e.status='cancelado') then 'cancelado · confirmado '||count(*) filter(where e.status in ('enviado','enviado_instagram'))||'/'||count(e.parte)
      when bool_or(e.status='pelo_instagram') then 'pelo_instagram · confirmado '||count(*) filter(where e.status='enviado_instagram')||'/'||count(e.parte)
      when bool_or(e.status='enviando') then 'enviando · confirmado '||count(*) filter(where e.status='enviado')||'/'||count(e.parte)
      when bool_or(e.status='fila') then 'fila · confirmado '||count(*) filter(where e.status='enviado')||'/'||count(e.parte)
      else 'enviado '||count(*) filter(where e.status='enviado')||'/'||count(e.parte) end as estado,
      case when li.n ~ '^\d+$' then li.n::int when li.n like 'c%' then 100+substring(li.n from 2)::int else 200+substring(li.n from 2)::int end ord
    from atendimento.lote_itens li left join atendimento.envios e on e.lote=li.lote and e.n=li.n
    left join atendimento.pulos p on p.lote=li.lote and ((li.conversation_id is not null and p.conversation_id=li.conversation_id and p.last_inbound_id=li.last_inbound_id) or (li.comment_id is not null and p.comment_id=li.comment_id))
    where li.lote=p_lote group by li.n,p.motivo
  ) x
$$;

-- Apenas o webhook com service_role pode usar este teste de eco.
create or replace function public.ai_atendimento_echo_previsto(p_conversation uuid,p_texto text) returns boolean
language sql stable security definer set search_path = '' as $$
  select exists(select 1 from atendimento.envios e join atendimento.lote_itens li on li.lote=e.lote and li.n=e.n
    where li.conversation_id=p_conversation and e.texto=p_texto and e.status in ('pelo_instagram','enviando')
      and e.criado_em>now()-interval '2 hours')
$$;
revoke all on function public.ai_atendimento_echo_previsto(uuid,text) from public,anon,authenticated;
grant execute on function public.ai_atendimento_echo_previsto(uuid,text) to service_role;

create or replace function atendimento.marcar_echo() returns trigger
language plpgsql security definer set search_path = '' as $$
declare hit record;
begin
  if new.direction<>'outbound' or new.text_content is null then return new; end if;
  select e.lote,e.n,e.parte into hit from atendimento.envios e
    join atendimento.lote_itens li on li.lote=e.lote and li.n=e.n
    where li.conversation_id=new.conversation_id and e.texto=new.text_content
      and e.status='pelo_instagram' and e.criado_em>now()-interval '2 hours'
      and new.created_at>=e.criado_em and new.created_at<=e.criado_em+interval '2 hours'
    order by e.criado_em,e.parte for update of e skip locked limit 1;
  if found then
    update atendimento.envios set status='enviado_instagram',message_id=new.external_message_id,enviado_em=now()
      where lote=hit.lote and n=hit.n and parte=hit.parte;
    update public.ai_messages set raw_payload=coalesce(raw_payload,'{}'::jsonb)||jsonb_build_object('origem','claude','lote',hit.lote,'n',hit.n,'parte',hit.parte,'enviado',true)
      where id=new.id;
  end if;
  return new;
end $$;
create trigger atendimento_echo_after_message after insert on public.ai_messages
  for each row execute function atendimento.marcar_echo();

revoke all on all functions in schema atendimento from public,anon,authenticated;
grant execute on all functions in schema atendimento to service_role;
