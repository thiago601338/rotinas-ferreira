import postgres from "npm:postgres@3.4.7";
import {
  type Asset,
  MAX_ITEMS,
  type Sheet,
  type SheetRequest,
} from "./core.ts";

export function createRepository(databaseUrl: string) {
  const sql = postgres(databaseUrl, {
    max: 1,
    ssl: "require",
    prepare: false,
    idle_timeout: 15,
    connect_timeout: 10,
    connection: {
      application_name: "atendimento-midia",
      statement_timeout: 8000,
      default_transaction_read_only: true,
    },
  });
  return {
    async load(request: SheetRequest): Promise<Sheet | null> {
      // O token só é comparado no servidor. Não entra em logs, títulos ou cabeçalhos.
      if (request.kind === "lote") {
        const access =
          await sql`select expira_em from atendimento.lotes where id=${request.lote} and token=${request.token} and expira_em>now() and criado_em>now()-interval '6 hours'`;
        if (!access.length) return null;
        const rows = await sql`
          select x.media->>'label' as label, x.media->>'kind' as kind,
                 x.media->>'path' as path, x.media->>'url' as url
          from atendimento.lote_itens li
          cross join lateral jsonb_array_elements(li.midias) with ordinality x(media, idx)
          where li.lote=${request.lote}
          order by case when li.tipo='comentario' then 1 else 0 end,
            case when li.tipo<>'comentario' then li.ultima_cliente_em end,
            case when li.tipo<>'comentario' then li.conversation_id end,
            length(li.n), li.n, x.idx
          limit ${MAX_ITEMS + 1}`;
        return {
          title: `LOTE ${request.lote}`,
          expiresAt: new Date(access[0].expira_em).getTime(),
          assets: rows.map((r) => ({
            label: String(r.label ?? "MIDIA"),
            detail: String(r.kind ?? ""),
            path: r.path || undefined,
            url: r.url || undefined,
            bucket: "ai-inbox-media",
          })),
        };
      }
      const access =
        await sql`select skus,expira_em from atendimento.folhas_produtos where token=${request.token} and expira_em>now()`;
      if (!access.length) return null;
      const rows = await sql`
        select p.sku, v.cor,
          coalesce(
            (select c->'front'->>'path' from jsonb_array_elements(coalesce(p.catalog_media->'colors','[]'::jsonb)) c
             where public.ai_color_key(c->>'color')=v.cor_key and nullif(c->'front'->>'path','') is not null limit 1),
            case when public.ai_color_key(p.catalog_media->>'cover_color')=v.cor_key then nullif(p.photo_url,'') end
          ) as path
        from public.products p
        cross join lateral (
          select public.ai_color_key(pv.color) as cor_key, min(public.ferreira_color_display(pv.color)) as cor
          from public.product_variations pv where pv.product_id=p.id and pv.stock>0
          group by public.ai_color_key(pv.color)
        ) v
        where p.sku=any(${access[0]
        .skus as string[]}) and p.deleted_at is null and public.ferreira_text_key(p.status)='ativo'
        order by p.sku,v.cor
        limit ${MAX_ITEMS + 1}`;
      return {
        title: "FOTOS DO CADASTRO",
        expiresAt: new Date(access[0].expira_em).getTime(),
        assets: rows.map((r): Asset => ({
          label: String(r.sku),
          detail: String(r.cor ?? "SEM COR"),
          path: r.path || undefined,
          bucket: "product-photos",
        })),
      };
    },
    close: () => sql.end({ timeout: 2 }),
  };
}
