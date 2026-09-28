import {
  allowedMetaURL,
  type Asset,
  createAssetLoader,
  MAX_ASSET_BYTES,
  pageAssets,
  parseRequest,
  rasterFormat,
  readLimited,
  type Sheet,
  storageURL,
} from "./core.ts";
import { createHandler } from "./handler.ts";

function assert(
  condition: unknown,
  message = "assertion failed",
): asserts condition {
  if (!condition) throw new Error(message);
}
function throws(fn: () => unknown) {
  let threw = false;
  try {
    fn();
  } catch {
    threw = true;
  }
  assert(threw);
}
async function rejects(fn: () => Promise<unknown>) {
  let threw = false;
  try {
    await fn();
  } catch {
    threw = true;
  }
  assert(threw);
}
const TOKEN = "a".repeat(48);
const BASE = "https://nailfzcujyxydqldktgg.supabase.co";
const asset: Asset = {
  label: "s1",
  detail: "story",
  bucket: "ai-inbox-media",
  path: "instagram-story-cache/image/12/34.jpg",
};
const sheet: Sheet = { title: "LOTE", expiresAt: 10_000, assets: [asset] };

Deno.test("tokens: lote e produtos são capacidades distintas; não admite SKUs livres", () => {
  assert(
    parseRequest(new URL(`https://edge.test/?l=L0927-1930&t=${TOKEN}`)).kind ===
      "lote",
  );
  assert(
    parseRequest(new URL(`https://edge.test/?produtos=${TOKEN}&p=2`)).page ===
      2,
  );
  for (
    const query of [
      `l=L0927-1930&t=123`,
      `produtos=${TOKEN}&skus=FB-1`,
      `produtos=${TOKEN}&l=L0927-1930`,
      `produtos=${TOKEN}&p=0`,
      `produtos=${TOKEN}&p=1&p=2`,
    ]
  ) throws(() => parseRequest(new URL("https://edge.test/?" + query)));
});

Deno.test("paginação conserva ordem e limita 12 itens; validade e páginas inexistentes falham", () => {
  const many = {
    ...sheet,
    assets: Array.from(
      { length: 25 },
      (_, i) => ({ ...asset, label: `s${i + 1}` }),
    ),
  };
  assert(pageAssets(many, 2, 0).length === 12);
  assert(pageAssets(many, 2, 0)[0].label === "s13");
  assert(pageAssets(many, 3, 0)[0].label === "s25");
  throws(() => pageAssets(many, 4, 0));
  throws(() => pageAssets(many, 1, 10_000));
});

Deno.test("Storage é restrito ao projeto e bucket; traversal e URLs externas são rejeitados", () => {
  assert(
    storageURL(BASE, "ai-inbox-media", asset.path!).includes(
      "/storage/v1/object/ai-inbox-media/instagram-story-cache/",
    ),
  );
  assert(
    storageURL(
      BASE,
      "product-photos",
      BASE + "/storage/v1/object/public/product-photos/id/cor frente.jpg",
    ) === BASE + "/storage/v1/object/product-photos/id/cor%20frente.jpg",
  );
  for (
    const path of [
      "../segredo",
      "a/../segredo",
      "/absoluto",
      "a\\b",
      "a/%2e%2e/x",
      "https://evil.test/a",
      BASE + "/storage/v1/object/public/other/a",
    ]
  ) throws(() => storageURL(BASE, "ai-inbox-media", path));
});

Deno.test("mídia externa aceita só HTTPS dos CDNs Meta sem credenciais, portas ou sufixo impostor", () => {
  assert(
    allowedMetaURL("https://scontent.cdninstagram.com/a.jpg?sig=example")
      .startsWith("https://scontent."),
  );
  assert(
    allowedMetaURL("https://scontent.xx.fbcdn.net/a.jpg").includes("fbcdn.net"),
  );
  for (
    const url of [
      "http://scontent.cdninstagram.com/a",
      "https://fbcdn.net.evil.test/a",
      "https://evilfbcdn.net/a",
      "https://127.0.0.1/a",
      "https://169.254.169.254/a",
      "file:///a",
      "https://user:pass@cdninstagram.com/a",
      "https://cdninstagram.com:8443/a",
    ]
  ) throws(() => allowedMetaURL(url));
});

Deno.test("service key fica apenas no Storage; fetch nunca segue redirecionamento", async () => {
  const calls: { url: string; init?: RequestInit }[] = [];
  const fetcher: typeof fetch = (input, init) => {
    calls.push({ url: String(input), init });
    return Promise.resolve(new Response(new Uint8Array([255, 216, 255])));
  };
  const load = createAssetLoader(
    { url: BASE, serviceKey: "TEST_SECRET" },
    fetcher,
  );
  await load(asset);
  await load({
    ...asset,
    path: undefined,
    url: "https://scontent.fbcdn.net/p.jpg",
  });
  assert(
    new Headers(calls[0].init?.headers).get("Authorization") ===
      "Bearer TEST_SECRET",
  );
  assert(new Headers(calls[1].init?.headers).get("Authorization") === null);
  assert(!calls.some((c) => c.url.includes("TEST_SECRET")));
  assert(calls.every((c) => c.init?.redirect === "error"));
});

Deno.test("limite de bytes funciona mesmo sem Content-Length; documentos/vídeos não são decodificados", async () => {
  await rejects(() =>
    readLimited(new Response(new Uint8Array(MAX_ASSET_BYTES + 1)))
  );
  await rejects(() =>
    readLimited(new Response("<svg xmlns='http://www.w3.org/2000/svg'></svg>"))
  );
  throws(() => rasterFormat(new TextEncoder().encode("<svg/>")));
  throws(() => rasterFormat(new TextEncoder().encode("....ftypmp42")));
});

Deno.test("cópia privada indisponível tenta URL original sem reenviar service key", async () => {
  const calls: RequestInit[] = [];
  const fetcher: typeof fetch = (_input, init) => {
    calls.push(init!);
    return Promise.resolve(
      calls.length === 1
        ? new Response(null, { status: 404 })
        : new Response(new Uint8Array([255, 216, 255])),
    );
  };
  const bytes = await createAssetLoader(
    { url: BASE, serviceKey: "SECRET" },
    fetcher,
  )({ ...asset, url: "https://scontent.fbcdn.net/photo.jpg" });
  assert(bytes[0] === 255 && calls.length === 2);
  assert(new Headers(calls[1].headers).get("Authorization") === null);
});

Deno.test("handler retorna 404 antes de buscar mídia para token inválido; erros não expõem segredos", async () => {
  let renders = 0;
  const handle = createHandler({
    loadSheet: () => Promise.resolve(null),
    render: () => {
      renders++;
      throw new Error("secret database url");
    },
  });
  const response = await handle(
    new Request(`https://edge.test/?produtos=${TOKEN}`),
  );
  assert(response.status === 404 && renders === 0);
  assert(response.headers.get("Cache-Control")?.includes("no-store"));
  const broken = createHandler({
    loadSheet: () => {
      throw new Error("SECRET_DSN");
    },
    render: async () => ({ bytes: new Uint8Array(), missing: 0 }),
  });
  const error = await broken(
    new Request(`https://edge.test/?produtos=${TOKEN}`),
  );
  assert(error.status === 500 && !(await error.text()).includes("SECRET"));
});

Deno.test("HEAD valida o token sem render; expiração durante geração não entrega imagem", async () => {
  let now = 0, renders = 0;
  const handle = createHandler({
    loadSheet: () => Promise.resolve(sheet),
    now: () => now,
    render: async () => {
      renders++;
      now = 20_000;
      return { bytes: new Uint8Array([255, 216, 255]), missing: 0 };
    },
  });
  const head = await handle(
    new Request(`https://edge.test/?produtos=${TOKEN}`, { method: "HEAD" }),
  );
  assert(head.status === 200 && renders === 0);
  const expired = await handle(
    new Request(`https://edge.test/?produtos=${TOKEN}`),
  );
  assert(expired.status === 404 && Number(renders) === 1);
});

Deno.test("handler retorna JPEG e contagem de ausências sem nomes de clientes ou tokens", async () => {
  const handle = createHandler({
    loadSheet: () => Promise.resolve(sheet),
    now: () => 0,
    render: async () => ({
      bytes: new Uint8Array([255, 216, 255]),
      missing: 1,
    }),
  });
  const response = await handle(
    new Request(`https://edge.test/?produtos=${TOKEN}`),
  );
  assert(
    response.status === 200 &&
      response.headers.get("Content-Type") === "image/jpeg",
  );
  assert(response.headers.get("X-Atendimento-Sem-Imagem") === "1");
  assert(!JSON.stringify([...response.headers]).includes(TOKEN));
});
