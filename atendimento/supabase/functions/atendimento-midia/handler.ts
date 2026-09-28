import {
  type Asset,
  PAGE_SIZE,
  pageAssets,
  parseRequest,
  PublicError,
  type Sheet,
  type SheetRequest,
} from "./core.ts";

type Dependencies = {
  loadSheet(request: SheetRequest): Promise<Sheet | null>;
  render(
    assets: Asset[],
    title: string,
    page: number,
    pages: number,
  ): Promise<{ bytes: Uint8Array; missing: number }>;
  now?: () => number;
};
const HEADERS = {
  "Cache-Control": "private, no-store, max-age=0",
  "Referrer-Policy": "no-referrer",
  "X-Content-Type-Options": "nosniff",
  "Content-Security-Policy":
    "default-src 'none'; frame-ancestors 'none'; sandbox",
};

export function createHandler(deps: Dependencies) {
  return async (request: Request): Promise<Response> => {
    try {
      if (request.method !== "GET" && request.method !== "HEAD") {
        return new Response("Método não permitido.", {
          status: 405,
          headers: { ...HEADERS, Allow: "GET, HEAD" },
        });
      }
      const parsed = parseRequest(new URL(request.url));
      const sheet = await deps.loadSheet(parsed);
      if (!sheet) throw new PublicError(404, "Folha inexistente ou expirada.");
      const assets = pageAssets(sheet, parsed.page, deps.now?.());
      const pages = Math.ceil(sheet.assets.length / PAGE_SIZE);
      const headers = {
        ...HEADERS,
        "Content-Type": "image/jpeg",
        "Content-Disposition": "inline; filename=folha-atendimento.jpg",
        "X-Atendimento-Pagina": String(parsed.page),
        "X-Atendimento-Paginas": String(pages),
      };
      if (request.method === "HEAD") return new Response(null, { headers });
      const result = await deps.render(assets, sheet.title, parsed.page, pages);
      // Se a geração atravessou a validade, a imagem privada não é entregue.
      if (sheet.expiresAt <= (deps.now?.() ?? Date.now())) {
        throw new PublicError(404, "Folha inexistente ou expirada.");
      }
      return new Response(new Uint8Array(result.bytes), {
        headers: {
          ...headers,
          "X-Atendimento-Sem-Imagem": String(result.missing),
        },
      });
    } catch (error) {
      const known = error instanceof PublicError;
      return new Response(
        known ? error.message : "Não foi possível gerar a folha.",
        {
          status: known ? error.status : 500,
          headers: { ...HEADERS, "Content-Type": "text/plain; charset=utf-8" },
        },
      );
    }
  };
}
