-- Corrige contexto do unaccent legado sem ampliar search_path das funções privadas.
create or replace function atendimento.fatos(p_produto uuid,p_cor text default null) returns text
language plpgsql stable security definer set search_path = '' as $$
declare p record; cents bigint; a_vista bigint; parcelas int; v_cor text; tamanhos text; outras text;
begin
  select id,sku,name,fabric,sale_price into p from public.products
  where id=p_produto and lower(status)='ativo' and deleted_at is null;
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

create or replace function atendimento.folha_produtos(p_skus text) returns text
language plpgsql security definer set search_path = '' as $$
declare t text; a text[];
begin
  select array_agg(distinct p.sku order by p.sku) into a from public.products p
  where p.sku=any(regexp_split_to_array(upper(coalesce(p_skus,'')),'\s*,\s*'))
    and lower(p.status)='ativo' and p.deleted_at is null;
  if a is null then return 'Nenhum SKU ativo encontrado'; end if;
  insert into atendimento.folhas_produtos(skus) values(a) returning token into t;
  return 'https://nailfzcujyxydqldktgg.supabase.co/functions/v1/atendimento-midia?produtos='||t;
end $$;


