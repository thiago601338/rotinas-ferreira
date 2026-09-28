-- Rotina de atendimento humano assistido. O schema fica fora da Data API.
create schema if not exists atendimento;
revoke all on schema atendimento from public, anon, authenticated;
grant usage on schema atendimento to service_role;

create table atendimento.estado (
  chave text primary key,
  valor jsonb not null default '{}'::jsonb,
  atualizado_em timestamptz not null default now()
);
create table atendimento.lotes (
  id text primary key,
  criado_em timestamptz not null default now(),
  token text not null unique default encode(gen_random_bytes(24),'hex'),
  expira_em timestamptz not null default now()+interval '6 hours'
);
create table atendimento.lote_itens (
  lote text not null references atendimento.lotes(id),
  n text not null,
  tipo text not null check (tipo in ('direct','comentario','fora')),
  conversation_id uuid references public.ai_conversations(id),
  comment_id text,
  last_inbound_id uuid,
  last_outbound_id uuid,
  ultima_cliente_em timestamptz,
  username text,
  midias jsonb not null default '[]'::jsonb,
  criado_em timestamptz not null default now(),
  primary key (lote,n)
);
create index lote_itens_conversa_idx on atendimento.lote_itens(conversation_id,criado_em desc);
create table atendimento.envios (
  lote text not null,
  n text not null,
  parte int not null,
  texto text not null,
  status text not null check (status in ('fila','enviando','enviado','pelo_instagram','enviado_instagram','nova_mensagem','equipe_respondeu','fora_da_janela','erro','incerto','cancelado')),
  message_id text,
  erro text,
  tentativas int not null default 0,
  enviar_apos timestamptz not null default now(),
  owner uuid,
  lease_ate timestamptz,
  enviado_em timestamptz,
  criado_em timestamptz not null default now(),
  primary key(lote,n,parte),
  foreign key(lote,n) references atendimento.lote_itens(lote,n)
);
create index envios_fila_idx on atendimento.envios(status,enviar_apos) where status in ('fila','enviando');
create table atendimento.pulos (
  id bigint generated always as identity primary key,
  conversation_id uuid,
  comment_id text,
  last_inbound_id uuid,
  motivo text not null,
  lote text not null,
  criado_em timestamptz not null default now(),
  check ((conversation_id is null) <> (comment_id is null))
);
create unique index pulos_direct_idx on atendimento.pulos(conversation_id,last_inbound_id) where conversation_id is not null;
create unique index pulos_comment_idx on atendimento.pulos(comment_id) where comment_id is not null;
create table atendimento.tratamentos (
  id bigint generated always as identity primary key,
  conversation_id uuid,
  comment_id text,
  last_inbound_id uuid,
  lote text not null,
  n text not null,
  criado_em timestamptz not null default now(),
  check ((conversation_id is null) <> (comment_id is null))
);
create unique index tratamentos_direct_idx on atendimento.tratamentos(conversation_id,last_inbound_id) where conversation_id is not null;
create unique index tratamentos_comment_idx on atendimento.tratamentos(comment_id) where comment_id is not null;
create table atendimento.comentarios (
  id text primary key,
  media_id text not null,
  media_caption text,
  media_url text,
  media_type text,
  texto text not null,
  username text,
  criado_em timestamptz not null,
  hidden boolean not null default false,
  loja_respondeu boolean not null default false,
  atualizado_em timestamptz not null default now()
);
create index comentarios_pendentes_idx on atendimento.comentarios(criado_em) where not hidden and not loja_respondeu;
create table atendimento.midia_produto (
  media_id text primary key,
  product_id uuid not null references public.products(id),
  cor text,
  metodo text not null,
  criado_em timestamptz not null default now()
);
create table atendimento.folhas_produtos (
  token text primary key default encode(gen_random_bytes(24),'hex'),
  skus text[] not null,
  expira_em timestamptz not null default now()+interval '6 hours'
);
-- Os dois métodos novos preservam os métodos já usados pela loja.
alter table public.ai_story_products drop constraint ai_story_products_method_check;
alter table public.ai_story_products add constraint ai_story_products_method_check
  check (method in ('visual_verified','exact_file','human_price_match','owner','claude_verificado','postagem'));
alter table atendimento.estado enable row level security;
alter table atendimento.lotes enable row level security;
alter table atendimento.lote_itens enable row level security;
alter table atendimento.envios enable row level security;
alter table atendimento.pulos enable row level security;
alter table atendimento.tratamentos enable row level security;
alter table atendimento.comentarios enable row level security;
alter table atendimento.midia_produto enable row level security;
alter table atendimento.folhas_produtos enable row level security;
revoke all on all tables in schema atendimento from public, anon, authenticated;
grant select, insert, update, delete on all tables in schema atendimento to service_role;
grant usage, select on all sequences in schema atendimento to service_role;
alter default privileges in schema atendimento revoke all on tables from public, anon, authenticated;
alter default privileges in schema atendimento revoke all on functions from public, anon, authenticated;

create or replace function atendimento.modo_atual() returns text
language sql stable security definer set search_path = '' as $$
  select case when s.value->>'instagram'='claude' then 'claude' else 'ia' end
  from (select 1) d left join public.ai_settings s on s.key='atendimento_modo'
$$;
create or replace function atendimento.modo(p_modo text default null) returns text
language plpgsql security definer set search_path = '' as $$
declare atual text;
begin
  if p_modo is not null and p_modo not in ('claude','ia') then raise exception 'modo inválido'; end if;
  if p_modo is not null then
    insert into public.ai_settings(key,value) values('atendimento_modo',jsonb_build_object('instagram',p_modo))
    on conflict(key) do update set value=jsonb_build_object('instagram',p_modo),updated_at=now();
    insert into public.ai_logs(level,kind,channel,detail) values('info','atendimento_modo','instagram',jsonb_build_object('modo',p_modo));
    if p_modo='ia' then
      update atendimento.envios set status='cancelado',erro='modo alterado para ia'
        where status='fila';
    end if;
  end if;
  atual:=atendimento.modo_atual();
  return atual;
end $$;

create or replace function atendimento.moeda(p_valor numeric) returns text
language sql immutable set search_path = '' as $$
  select 'R$'||replace(to_char(round(p_valor,2),'FM999999990.00'),'.',',')
$$;
create or replace function atendimento.fatos(p_produto uuid,p_cor text default null) returns text
language plpgsql stable security definer set search_path = '' as $$
declare p record; cents bigint; a_vista bigint; parcelas int; v_cor text; tamanhos text; outras text;
begin
  select id,sku,name,fabric,sale_price into p from public.products
  where id=p_produto and public.ferreira_text_key(status)='ativo' and deleted_at is null;
  if not found then return null; end if;
  cents:=round(p.sale_price*100)::bigint;
  select coalesce((t->>'maxInstallments')::int,1) into parcelas
  from public.ai_settings s cross join lateral jsonb_array_elements(s.value->'tiers') t
  where s.key='public_installment_policy' and cents >= (t->>'minCents')::bigint
    and (t->>'maxCents' is null or cents <= (t->>'maxCents')::bigint)
  limit 1;
  parcelas:=coalesce(parcelas,1);
  a_vista:=floor((cents*(10000-coalesce((select (value->>'cashDiscountBps')::int from public.ai_settings where key='public_installment_policy'),0))+5000)/10000.0)::bigint;
  select public.ferreira_color_display(v.color), string_agg(distinct v.size,' ' order by v.size)
    into v_cor,tamanhos from public.product_variations v
  where v.product_id=p_produto and v.stock>0 and (p_cor is null or public.ai_color_key(v.color)=public.ai_color_key(p_cor))
  group by public.ferreira_color_display(v.color) order by 1 limit 1;
  select string_agg(x.cor||': '||x.tam,'; ' order by x.cor) into outras from (
    select public.ferreira_color_display(v.color) cor,string_agg(distinct v.size,' ' order by v.size) tam
    from public.product_variations v where v.product_id=p_produto and v.stock>0
      and (v_cor is null or public.ai_color_key(v.color)<>public.ai_color_key(v_cor))
    group by public.ferreira_color_display(v.color)
  ) x;
  return p.sku||' '||p.name||coalesce(' · '||coalesce(v_cor,p_cor),'')||' · '||atendimento.moeda(p.sale_price)||' · '||parcelas||'x · à vista '||atendimento.moeda(a_vista/100.0)
    ||' · '||case when tamanhos is null and p_cor is not null then p_cor||': acabou' when tamanhos is null then 'sem estoque' else v_cor||': '||tamanhos end
    ||coalesce(' · outras: '||outras,'')||coalesce(' · tecido: '||nullif(p.fabric,''),'');
end $$;
create or replace function atendimento.produto(p_termos text,p_cor text default null,p_tamanho text default null) returns text
language sql stable security definer set search_path = '' as $$
  select coalesce(string_agg(atendimento.fatos(x.id,p_cor),E'\n' order by x.score desc), 'Nenhum produto ativo encontrado')
  from public.ai_search_products(regexp_split_to_array(trim(coalesce(p_termos,'')),'\s+'),p_cor,p_tamanho,5) x
  join public.products p on p.id=x.id and p.deleted_at is null
  where (p_cor is null or p_tamanho is null or x.matched_stock>0)
$$;
create or replace function atendimento.folha_produtos(p_skus text) returns text
language plpgsql security definer set search_path = '' as $$
declare t text; a text[];
begin
  select array_agg(distinct p.sku order by p.sku) into a from public.products p
  where p.sku=any(regexp_split_to_array(upper(coalesce(p_skus,'')),'\s*,\s*'))
    and public.ferreira_text_key(p.status)='ativo' and p.deleted_at is null;
  if a is null then return 'Nenhum SKU ativo encontrado'; end if;
  insert into atendimento.folhas_produtos(skus) values(a) returning token into t;
  return 'https://nailfzcujyxydqldktgg.supabase.co/functions/v1/atendimento-midia?produtos='||t;
end $$;

revoke all on all functions in schema atendimento from public, anon, authenticated;
grant execute on all functions in schema atendimento to service_role;
