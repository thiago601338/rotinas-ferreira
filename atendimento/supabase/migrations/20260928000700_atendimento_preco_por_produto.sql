-- Corrige a associação entre preço e produto.
-- A assinatura pública de responder não muda. Respostas com R$ exigem SKU
-- explícito ou contexto inequivocamente vinculado; preço e à vista usam catálogo atual.
create or replace function atendimento.preco_do_produto(p_valor numeric,p_produto uuid) returns boolean
language sql stable security definer set search_path = '' as $$
  select exists(select 1 from public.products p
    where p.id=p_produto and lower(p.status)='ativo' and p.deleted_at is null
      and (round(p.sale_price,2)=p_valor or
        floor((round(p.sale_price*100)::bigint*(10000-coalesce((select (value->>'cashDiscountBps')::int from public.ai_settings where key='public_installment_policy'),0))+5000)/10000.0)/100.0=p_valor))
$$;

create or replace function atendimento.produto_para_preco(p_lote text,p_n text) returns uuid
language plpgsql stable security definer set search_path = '' as $$
declare v_item atendimento.lote_itens; v_count int; v_tipo text; v_ref text; v_product uuid;
begin
  select * into v_item from atendimento.lote_itens li where li.lote=p_lote and li.n=p_n;
  if not found then return null; end if;
  if v_item.tipo='comentario' then
    select mp.product_id into v_product from atendimento.comentarios c
      join atendimento.midia_produto mp on mp.media_id=c.media_id
      join public.products p on p.id=mp.product_id and lower(p.status)='ativo' and p.deleted_at is null
      where c.id=v_item.comment_id;
    return v_product;
  end if;
  select count(*),min(rt.tipo),min(rt.referencia) into v_count,v_tipo,v_ref
    from atendimento.referencias_turno(v_item.conversation_id,v_item.last_inbound_id,v_item.last_outbound_id) rt;
  if v_count>1 then return null; end if;
  if v_count=1 and v_tipo='story' then
    select sp.product_id into v_product from public.ai_story_products sp
      join public.products p on p.id=sp.product_id and lower(p.status)='ativo' and p.deleted_at is null
      where sp.story_id=v_ref and sp.account_id='17841454587986765' and (sp.expires_at is null or sp.expires_at>now());
  elsif v_count=1 and v_tipo='post' then
    select mp.product_id into v_product from atendimento.midia_produto mp
      join public.products p on p.id=mp.product_id and lower(p.status)='ativo' and p.deleted_at is null
      where mp.media_id=v_ref;
  elsif v_count=1 and v_tipo='foto' and v_ref ~ '^[a-f0-9]{64}$' then
    -- Mais de um cache recente para o mesmo hash precisa concordar no produto.
    select min(p.id::text)::uuid into v_product from public.ai_settings s
      left join public.products p on p.id::text=s.value->>'productId' and lower(p.status)='ativo' and p.deleted_at is null
      where s.key like 'ig_verified_image:%' and s.value->>'account'='17841454587986765'
        and s.value->>'imageHash'=v_ref and s.value->>'method' in ('exact_file','visual_verified','claude_verificado')
        and s.value->>'verifiedAt'>to_char((now()-interval '7 days') at time zone 'UTC','YYYY-MM-DD"T"HH24:MI:SS')
      having count(distinct p.id)=1 and count(*) filter(where p.id is null)=0;
  elsif v_count=0 then
    -- O último story sozinho não prova a peça: todos os stories das 48h
    -- precisam resolver para exatamente um produto ativo distinto.
    select min(p.id::text)::uuid into v_product from public.ai_messages m
      left join public.ai_story_products sp on sp.story_id=m.raw_payload->'storyReference'->>'id'
        and sp.account_id='17841454587986765' and (sp.expires_at is null or sp.expires_at>now())
      left join public.products p on p.id=sp.product_id and lower(p.status)='ativo' and p.deleted_at is null
      where m.conversation_id=v_item.conversation_id and m.direction='inbound'
        and jsonb_typeof(m.raw_payload->'storyReference')='object'
        and m.created_at>now()-interval '48 hours' and m.created_at<=v_item.ultima_cliente_em
      having count(distinct p.id)=1 and count(*) filter(where p.id is null)=0;
  end if;
  return v_product;
end $$;

-- SKU informado não pode substituir um vínculo existente, mesmo em ensaio
-- ou sem citar preço. Verifica todas as referências, inclusive turnos com várias mídias.
create or replace function atendimento.produto_conflita_contexto(p_lote text,p_n text,p_produto uuid) returns boolean
language sql stable security definer set search_path = '' as $$
  with item as (
    select li.* from atendimento.lote_itens li where li.lote=p_lote and li.n=p_n
  ), referencias as (
    select 'post'::text tipo,c.media_id referencia from item i
      join atendimento.comentarios c on c.id=i.comment_id where i.tipo='comentario'
    union all
    select rt.tipo,rt.referencia from item i
      cross join lateral atendimento.referencias_turno(i.conversation_id,i.last_inbound_id,i.last_outbound_id) rt
      where i.tipo<>'comentario'
  ), vinculos as (
    select sp.product_id from referencias r join public.ai_story_products sp
      on r.tipo='story' and sp.story_id=r.referencia and sp.account_id='17841454587986765'
    union all
    select mp.product_id from referencias r join atendimento.midia_produto mp
      on r.tipo='post' and mp.media_id=r.referencia
    union all
    select p.id from referencias r join public.ai_settings s
      on r.tipo='foto' and r.referencia ~ '^[a-f0-9]{64}$'
        and s.key like 'ig_verified_image:%' and s.value->>'account'='17841454587986765'
        and s.value->>'imageHash'=r.referencia and s.value->>'method' in ('exact_file','visual_verified','claude_verificado')
        and s.value->>'verifiedAt'>to_char((now()-interval '7 days') at time zone 'UTC','YYYY-MM-DD"T"HH24:MI:SS')
      join public.products p on p.id::text=s.value->>'productId'
    union all
    select sp.product_id from item i join public.ai_messages m on m.conversation_id=i.conversation_id
      join public.ai_story_products sp on sp.story_id=m.raw_payload->'storyReference'->>'id'
        and sp.account_id='17841454587986765'
      where i.tipo<>'comentario' and not exists(select 1 from referencias)
        and m.direction='inbound' and jsonb_typeof(m.raw_payload->'storyReference')='object'
        and m.created_at>now()-interval '48 hours' and m.created_at<=i.ultima_cliente_em
  ) select exists(select 1 from vinculos v where v.product_id<>p_produto)
$$;

create or replace function atendimento.responder(p_lote text,p_itens jsonb,p_ensaio boolean default false) returns text
language plpgsql security definer set search_path = '' as $$
declare j jsonb; item atendimento.lote_itens; msg text; v_n text; msgs jsonb; i int; v_valor text; price numeric;
  v_sku text; cor text; produto_id uuid; motivo text; line text; out_text text:=''; j_text text:=''; count_msgs int; ref text; treatment_id bigint;
  ref_tipo text; ref_count int; aprendizado text; learned_rows int; produto_preco_id uuid;
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
    v_sku:=nullif(j->>'produto',''); cor:=nullif(j->>'cor',''); produto_id:=null;
    if v_sku is not null then
      select p.id into produto_id from public.products p where p.sku=v_sku and lower(p.status)='ativo' and p.deleted_at is null;
      if produto_id is null then out_text:=out_text||'#'||v_n||' rejeitado: SKU não ativo'||E'\n'; continue; end if;
      if cor is not null and not exists(select 1 from public.product_variations v where v.product_id=produto_id and public.ai_color_key(v.color)=public.ai_color_key(cor)) then
        out_text:=out_text||'#'||v_n||' rejeitado: cor inexistente no cadastro'||E'\n'; continue;
      end if;
    elsif cor is not null then out_text:=out_text||'#'||v_n||' rejeitado: cor sem produto'||E'\n'; continue;
    end if;
    if produto_id is not null and atendimento.produto_conflita_contexto(p_lote,v_n,produto_id) then
      out_text:=out_text||'#'||v_n||' rejeitado: SKU informado conflita com produto já vinculado ao contexto'||E'\n'; continue;
    end if;
    produto_preco_id:=coalesce(produto_id,atendimento.produto_para_preco(p_lote,v_n));
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
        if produto_preco_id is null then motivo:='produto não identificado; informe o SKU para validar o preço'; exit;
        elsif not atendimento.preco_do_produto(price,produto_preco_id) then motivo:='preço não corresponde ao produto identificado'; exit; end if;
      end loop;
      if motivo is not null then exit; end if;
    end loop;
    if motivo is not null then out_text:=out_text||'#'||v_n||' rejeitado: '||motivo||E'\n'; continue; end if;
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

revoke all on function atendimento.preco_do_produto(numeric,uuid) from public,anon,authenticated;
revoke all on function atendimento.produto_para_preco(text,text) from public,anon,authenticated;
revoke all on function atendimento.produto_conflita_contexto(text,text,uuid) from public,anon,authenticated;
revoke all on function atendimento.responder(text,jsonb,boolean) from public,anon,authenticated;
grant execute on function atendimento.preco_do_produto(numeric,uuid) to service_role;
grant execute on function atendimento.produto_para_preco(text,text) to service_role;
grant execute on function atendimento.produto_conflita_contexto(text,text,uuid) to service_role;
grant execute on function atendimento.responder(text,jsonb,boolean) to service_role;
