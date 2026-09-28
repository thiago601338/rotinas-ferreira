create or replace function atendimento.sincronizar() returns text
language plpgsql security definer set search_path = '' as $$
begin
  if atendimento.modo_atual()<>'claude' then return 'modo ia: sincronização não iniciada'; end if;
  perform net.http_post(
    url:='https://nailfzcujyxydqldktgg.supabase.co/functions/v1/atendimento-sync',
    body:='{}'::jsonb,
    headers:=jsonb_build_object('Content-Type','application/json','x-ai-followup-token',(select secret from private.ai_followup_config where id=true)),
    timeout_milliseconds:=90000
  );
  return 'sincronização pedida';
end $$;

create or replace function atendimento.pendentes(p_max_direct int default 20,p_max_comentarios int default 10,p_max_fora int default 10) returns text
language plpgsql security definer set search_path = '' as $$
declare
  r record; msg record; last_shop record; known record; ctx record;
  lote_id text; token text; out_text text:=''; direct_text text:=''; comment_text text:=''; outside_text text:=''; folha_ordem text:='';
  item_text text; context_text text; client_text text; media_list jsonb; media_path text; media_url text; kind text; label text;
  n_direct int:=0; n_comment int:=0; n_out int:=0; n_s int:=0; n_f int:=0; n_v int:=0; n_p int:=0;
  n_equipe int:=0; n_cortesia int:=0; n_audio int:=0; n_velho int:=0; n_pulado int:=0;
  sync_at timestamptz; sync_age text; last_outbound_id uuid; last_inbound_id uuid; username text;
  ref_id text; prod_id uuid; prod_cor text; elapsed numeric; age_h int; preview text; risk text;
  offset_minutes int; comments_permission text; media_hash text;
  n_mais int:=0; ordem_antes text; s_antes int; f_antes int; v_antes int; p_antes int;
begin
  select (valor->>'at')::timestamptz into sync_at from atendimento.estado where chave='ultima_sync';
  sync_age:=case when sync_at is null then 'nunca' else floor(extract(epoch from now()-sync_at)/60)::int||' min' end;
  if atendimento.modo_atual()<>'claude' then return 'LOTE — nada pendente · sinc. há '||sync_age||' · modo ia'; end if;
  -- Serializa apenas a numeração dos lotes; não disputa o lock da fila de envios.
  perform pg_advisory_xact_lock(260927,2);
  select valor->>'status' into comments_permission from atendimento.estado where chave='comentarios_permissao';
  p_max_direct:=greatest(0,least(coalesce(p_max_direct,20),50));
  p_max_comentarios:=greatest(0,least(coalesce(p_max_comentarios,10),30));
  p_max_fora:=greatest(0,least(coalesce(p_max_fora,10),30));
  -- A composição usa a última mensagem efetiva de cada conversa, em ordem de espera.
  for r in
    select c.id as conversation_id,c.external_user_id,c.metadata,c.status,m.id as message_id,m.created_at as inbound_at,
           m.text_content,m.message_type,m.raw_payload
    from public.ai_conversations c
    join lateral (select * from public.ai_messages z where z.conversation_id=c.id and z.direction in ('inbound','outbound') order by z.created_at desc,z.id desc limit 1) m on true
    where c.channel='instagram' and m.direction='inbound'
      and not exists(select 1 from public.ai_optouts o where o.channel='instagram' and o.external_user_id=c.external_user_id)
    order by m.created_at,c.id
  loop
    if r.inbound_at < now()-interval '7 days' then n_velho:=n_velho+1; continue; end if;
    if exists(select 1 from atendimento.tratamentos t where t.conversation_id=r.conversation_id and t.last_inbound_id=r.message_id and t.ativo) then n_pulado:=n_pulado+1; continue; end if;
    select z.id,z.created_at,z.text_content into last_shop from public.ai_messages z
      where z.conversation_id=r.conversation_id and z.direction='outbound' order by z.created_at desc,z.id desc limit 1;
    last_outbound_id:=last_shop.id;
    select coalesce(string_agg(coalesce(z.text_content,''),' ' order by z.created_at),'') into client_text
      from (select text_content,created_at from public.ai_messages where conversation_id=r.conversation_id and direction='inbound'
        and (last_shop.id is null or created_at>last_shop.created_at) order by created_at desc limit 8) z;
    if r.message_type='audio' and nullif(trim(client_text),'') is null
      and not exists(select 1 from public.ai_messages a where a.conversation_id=r.conversation_id and a.direction='inbound'
        and (last_shop.id is null or a.created_at>last_shop.created_at) and a.message_type<>'audio')
    then n_audio:=n_audio+1; continue; end if;
    -- Inclui pedidos de parada que chegam pela transcrição, antes de qualquer resposta.
    if client_text ~* '(par(e|ar) de (me )?(mandar|enviar)|n[ãa]o quero (mais )?receber|descadastr|sair da lista|me remov|cancelar? (o )?recebimento)'
      or trim(client_text) ~* '^(sair|parar|stop)[.! ]*$'
    then n_equipe:=n_equipe+1; continue; end if;
    if trim(lower(coalesce(client_text,''))) ~ '^(ok|t[aá] bom|entendi|obrigad[ao]|valeu|👍|❤️|❤|😍|😊|👏|🙏|\.)[.! ]*$'
      and last_shop.id is not null then n_cortesia:=n_cortesia+1; continue; end if;
    if client_text ~* '(comprovante|j[aá] paguei|vou pagar agora|[ée] rob[oô]|quem (est[aá] )?falando|atendente|pessoa de verdade|reclama[çc][ãa]o|procon|horr[ií]vel|absurdo)'
      or coalesce(last_shop.text_content,'') ~* '(https?://|chave (do )?pix|me (passe|mande) (seu )?(endere[çc]o|cpf)|qual (seu )?(endere[çc]o|cpf))'
    then n_equipe:=n_equipe+1; continue; end if;
    if r.inbound_at > now()-interval '24 hours' then
      if n_direct>=p_max_direct then n_mais:=n_mais+1; continue; end if;
      n_direct:=n_direct+1; label:=n_direct::text;
    else
      if n_out>=p_max_fora then n_mais:=n_mais+1; continue; end if;
      n_out:=n_out+1; label:='j'||n_out::text;
    end if;
    ordem_antes:=folha_ordem; s_antes:=n_s; f_antes:=n_f; v_antes:=n_v; p_antes:=n_p;
    username:=nullif(r.metadata->>'username','');
    elapsed:=extract(epoch from now()-r.inbound_at)/60;
    age_h:=floor(elapsed/60)::int;
    item_text:='#'||label||' · '||case when elapsed<60 then floor(elapsed)::int||' min' else age_h||' h' end;
    if label !~ '^j' then item_text:=item_text||' · janela '||greatest(0,23-age_h)||'h';
    else item_text:=item_text||' · @'||coalesce(username,'usuario_indisponivel'); end if;
    if last_shop.created_at is null or last_shop.created_at<now()-interval '6 hours' then item_text:=item_text||' · saudar';
    elsif last_shop.created_at>now()-interval '30 minutes' then item_text:=item_text||' · equipe há '||floor(extract(epoch from now()-last_shop.created_at)/60)::int||' min'; end if;
    risk:=case when client_text ~* '(entrega|frete|envio|retirada|reserva|separ(a|ar)|troca|devolu[çc][ãa]o|desconto|pix|cart[ãa]o)' then '⚠ assunto da equipe?' else null end;
    if risk is not null then item_text:=item_text||' · '||risk; end if;
    item_text:=item_text||E'\n';
    for msg in select text_content,created_at from public.ai_messages where conversation_id=r.conversation_id and direction='outbound'
      and (last_shop.id is null or created_at<=last_shop.created_at) order by created_at desc limit 2
    loop item_text:=item_text||'  '||to_char(msg.created_at at time zone 'America/Maceio','HH24:MI')||' L: '||left(regexp_replace(coalesce(msg.text_content,''),'[\r\n]+',' ','g'),200)||E'\n'; end loop;
    media_list:='[]'::jsonb;
    for msg in select * from (select a.id,a.created_at,a.text_content,a.message_type,a.media_path,a.raw_payload from public.ai_messages a
      where a.conversation_id=r.conversation_id and a.direction='inbound' and (last_shop.id is null or a.created_at>last_shop.created_at)
      order by a.created_at desc limit 8) recent order by recent.created_at,recent.id
    loop
      ref_id:=nullif(msg.raw_payload->'storyReference'->>'id','');
      kind:=case when ref_id is not null or jsonb_typeof(msg.raw_payload->'storyReference')='object' then 'story' when msg.message_type='audio' then 'audio'
        when coalesce(msg.raw_payload->>'mediaType','')='video' then 'video'
        when nullif(msg.raw_payload->>'sharedMediaId','') is not null or jsonb_typeof(msg.raw_payload->'postReference')='object' then 'post'
        when msg.media_path is not null or msg.raw_payload->>'mediaUrl' is not null then 'foto' else null end;
      prod_id:=null; prod_cor:=null;
      if ref_id is not null then
        select sp.product_id,sp.color into prod_id,prod_cor from public.ai_story_products sp
          where sp.story_id=ref_id and (sp.expires_at is null or sp.expires_at>now()) limit 1;
      elsif kind='post' then
        select mp.product_id,mp.cor into prod_id,prod_cor from atendimento.midia_produto mp where mp.media_id=coalesce(msg.raw_payload->>'sharedMediaId',msg.raw_payload->'postReference'->>'id');
      elsif kind='foto' then
        media_hash:=coalesce(msg.raw_payload->>'imageHash',msg.raw_payload->'mediaCache'->>'sha256');
        if media_hash ~ '^[a-f0-9]{64}$' then
          select p.id,s.value->>'color' into prod_id,prod_cor from public.ai_settings s
          join public.products p on p.id::text=s.value->>'productId' and lower(p.status)='ativo' and p.deleted_at is null
          where s.key like 'ig_verified_image:%' and s.value->>'account'='17841454587986765'
            and s.value->>'imageHash'=media_hash and s.value->>'method' in ('exact_file','visual_verified','claude_verificado')
            and s.value->>'verifiedAt'>to_char((now()-interval '7 days') at time zone 'UTC','YYYY-MM-DD"T"HH24:MI:SS')
          order by s.value->>'verifiedAt' desc limit 1;
        end if;
      end if;
      context_text:=case when prod_id is not null then atendimento.fatos(prod_id,prod_cor) else null end;
      if context_text is null then prod_id:=null; end if;
      if kind='audio' then
        item_text:=item_text||'  [áudio'||case when msg.text_content is null then ' sem transcrição]' else '] '||left(msg.text_content,200) end||E'\n';
      elsif kind is not null and prod_id is not null then
        item_text:=item_text||'  ['||kind||'] '||context_text||E'\n';
      elsif kind is not null then
        if kind='story' then n_s:=n_s+1; preview:='s'||n_s;
        elsif kind='video' then n_v:=n_v+1; preview:='v'||n_v;
        elsif kind='post' then n_p:=n_p+1; preview:='p'||n_p;
        else n_f:=n_f+1; preview:='f'||n_f; end if;
        media_path:=coalesce(nullif(msg.raw_payload->'storyPrefetch'->>'imagePath',''),nullif(msg.raw_payload->>'videoFramePath',''),nullif(msg.media_path,''));
        if media_path ~* '\.(mp4|mov|webm|m4v)$' then media_path:=null; end if;
        media_url:=case when kind in ('post','video') then nullif(msg.raw_payload->'postReference'->>'thumbnailUrl','')
          when kind='story' then nullif(msg.raw_payload->'storyReference'->>'url','')
          when kind='foto' then nullif(msg.raw_payload->>'mediaUrl','') else null end;
        if media_url !~* '^https://([a-z0-9-]+\.)*(fbcdn\.net|fbsbx\.com|cdninstagram\.com|facebook\.com)/'
          or media_url ~* '\.(mp4|mov|webm|m4v)(\?|$)' then media_url:=null; end if;
        if media_path is null and media_url is null then item_text:=item_text||'  ['||kind||' '||preview||' sem imagem · @'||coalesce(username,'usuario_indisponivel')||' · '||to_char(msg.created_at at time zone 'America/Maceio','DD/MM HH24:MI')||']'||E'\n';
        else
          item_text:=item_text||'  ['||kind||' '||preview||' sem peça]'||E'\n';
          media_list:=media_list||jsonb_build_array(jsonb_strip_nulls(jsonb_build_object('label',preview,'path',media_path,'url',media_url,'kind',kind,'messageId',msg.id)));
          folha_ordem:=concat_ws(', ',nullif(folha_ordem,''),preview);
        end if;
      end if;
      if msg.text_content is not null and trim(msg.text_content)<>'' then
        item_text:=item_text||'  '||to_char(msg.created_at at time zone 'America/Maceio','HH24:MI')||' C: '||left(regexp_replace(msg.text_content,'[\r\n]+',' ','g'),200)||E'\n';
      end if;
    end loop;
    if media_list='[]'::jsonb and ref_id is null then
      select sp.product_id,sp.color into prod_id,prod_cor
      from public.ai_messages m join public.ai_story_products sp on sp.story_id=m.raw_payload->'storyReference'->>'id'
      where m.conversation_id=r.conversation_id and m.direction='inbound' and m.created_at>now()-interval '48 hours'
      order by m.created_at desc limit 1;
      context_text:=case when prod_id is not null then atendimento.fatos(prod_id,prod_cor) else null end;
      if context_text is not null then item_text:=item_text||'  [contexto] '||context_text||E'\n'; end if;
    end if;
    -- Reserva 1.100 caracteres para cabeçalho, URL, contadores e aviso de continuação.
    -- Um item que não cabe permanece pendente e não é persistido neste lote.
    if length(direct_text||comment_text||outside_text||item_text)+length(folha_ordem)>9900 then
      n_mais:=n_mais+1;
      if label like 'j%' then n_out:=n_out-1; else n_direct:=n_direct-1; end if;
      folha_ordem:=ordem_antes; n_s:=s_antes; n_f:=f_antes; n_v:=v_antes; n_p:=p_antes;
      continue;
    end if;
    if lote_id is null then
      offset_minutes:=0;
      loop
        lote_id:='L'||to_char((clock_timestamp()+offset_minutes*interval '1 minute') at time zone 'America/Maceio','MMDD-HH24MI');
        exit when not exists(select 1 from atendimento.lotes where id=lote_id);
        offset_minutes:=offset_minutes+1;
      end loop;
      insert into atendimento.lotes(id) values(lote_id) returning atendimento.lotes.token into token;
    end if;
    insert into atendimento.lote_itens(lote,n,tipo,conversation_id,last_inbound_id,last_outbound_id,ultima_cliente_em,username,midias)
      values(lote_id,label,case when label like 'j%' then 'fora' else 'direct' end,r.conversation_id,r.message_id,last_outbound_id,r.inbound_at,username,media_list);
    if label like 'j%' then outside_text:=outside_text||item_text; else direct_text:=direct_text||item_text; end if;
  end loop;
  for r in select cm.* from atendimento.comentarios cm
    where not cm.hidden and not cm.loja_respondeu and cm.criado_em>now()-interval '7 days'
      and trim(cm.texto) !~ '^(@[[:alnum:]_.]+|[[:punct:] ]+)$'
      and not exists(select 1 from atendimento.tratamentos t where t.comment_id=cm.id and t.ativo)
      and comments_permission is distinct from 'sem_permissao'
    order by cm.criado_em
  loop
    if n_comment>=p_max_comentarios then n_mais:=n_mais+1; continue; end if;
    n_comment:=n_comment+1; label:='c'||n_comment::text;
    ordem_antes:=folha_ordem; p_antes:=n_p;
    select mp.product_id,mp.cor into prod_id,prod_cor from atendimento.midia_produto mp where mp.media_id=r.media_id;
    context_text:=case when prod_id is not null then atendimento.fatos(prod_id,prod_cor) else null end;
    item_text:='#'||label||' · comentário · '||floor(extract(epoch from now()-r.criado_em)/60)::int||' min · '
      ||left(coalesce(r.media_caption,''),80)||E'\n';
    media_list:='[]'::jsonb;
    if context_text is not null then item_text:=item_text||'  [post] '||context_text||E'\n';
    else
      n_p:=n_p+1; preview:='p'||n_p;
      item_text:=item_text||'  [post '||preview||' sem peça]'||E'\n';
      if r.media_url is not null then media_list:=jsonb_build_array(jsonb_build_object('label',preview,'url',r.media_url,'kind','post','mediaId',r.media_id)); folha_ordem:=concat_ws(', ',nullif(folha_ordem,''),preview); end if;
    end if;
    item_text:=item_text||'  '||to_char(r.criado_em at time zone 'America/Maceio','HH24:MI')||' C: '||left(regexp_replace(r.texto,'[\r\n]+',' ','g'),200)||E'\n';
    if length(direct_text||comment_text||outside_text||item_text)+length(folha_ordem)>9900 then
      n_mais:=n_mais+1; n_comment:=n_comment-1; folha_ordem:=ordem_antes; n_p:=p_antes;
      continue;
    end if;
    if lote_id is null then
      offset_minutes:=0;
      loop
        lote_id:='L'||to_char((clock_timestamp()+offset_minutes*interval '1 minute') at time zone 'America/Maceio','MMDD-HH24MI');
        exit when not exists(select 1 from atendimento.lotes where id=lote_id);
        offset_minutes:=offset_minutes+1;
      end loop;
      insert into atendimento.lotes(id) values(lote_id) returning atendimento.lotes.token into token;
    end if;
    insert into atendimento.lote_itens(lote,n,tipo,comment_id,ultima_cliente_em,midias) values(lote_id,label,'comentario',r.id,r.criado_em,media_list);
    comment_text:=comment_text||item_text;
  end loop;
  if lote_id is null then return 'LOTE — '||case when n_mais>0 then 'nenhum item nos limites pedidos · outros pendentes '||n_mais else 'nada pendente' end||' · sinc. há '||sync_age
    ||case when comments_permission='sem_permissao' then ' · comentários: sem permissão' else '' end; end if;
  out_text:='LOTE '||lote_id||' · direct '||n_direct||' · comentários '||case when comments_permission='sem_permissao' then 'sem permissão' else n_comment::text end||' · sinc. há '||sync_age||' · modo claude'||E'\n';
  if folha_ordem<>'' then out_text:=out_text||'folha: https://nailfzcujyxydqldktgg.supabase.co/functions/v1/atendimento-midia?l='||lote_id||'&t='||token||' · ordem: '||folha_ordem||E'\n'; end if;
  out_text:=out_text||direct_text||comment_text;
  if n_out>0 then out_text:=out_text||'FORA DA JANELA (pelo Instagram)'||E'\n'||outside_text; end if;
  out_text:=out_text||'fora da lista: equipe '||n_equipe||' · cortesia '||n_cortesia||' · áudio '||n_audio||' · mais de 7 dias '||n_velho||' · pulados antes '||n_pulado;
  if n_mais>0 then out_text:=out_text||E'\n'||'mais pendentes: '||n_mais||' · peça novo lote depois de tratar estes'; end if;
  return out_text;
end $$;

revoke all on function atendimento.sincronizar() from public,anon,authenticated;
revoke all on function atendimento.pendentes(int,int,int) from public,anon,authenticated;
grant execute on function atendimento.sincronizar() to service_role;
grant execute on function atendimento.pendentes(int,int,int) to service_role;
