export const PAGE_SIZE = 12;
export const MAX_ASSET_BYTES = 5 * 1024 * 1024;
export const MAX_ITEMS = 1000;

export type SheetRequest =
  | { kind: "lote"; lote: string; token: string; page: number }
  | { kind: "produtos"; token: string; page: number };
export type Asset = {
  label: string;
  detail: string;
  path?: string;
  url?: string;
  bucket: "ai-inbox-media" | "product-photos";
};
export type Sheet = { title: string; expiresAt: number; assets: Asset[] };
export class PublicError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

/** Os SKUs autorizados vêm exclusivamente da linha criada por folha_produtos(). */
export function parseRequest(url: URL): SheetRequest {
  const q = url.searchParams;
  for (const key of q.keys()) {
    if (
      !["l", "t", "p", "produtos"].includes(key) || q.getAll(key).length !== 1
    ) {
      throw new PublicError(400, "Parâmetros inválidos.");
    }
  }
  const pageText = q.get("p") ?? "1";
  if (!/^[1-9]\d{0,2}$/.test(pageText)) {
    throw new PublicError(400, "Página inválida.");
  }
  const page = Number(pageText);
  const productToken = q.get("produtos");
  if (productToken !== null) {
    if (q.has("l") || q.has("t") || !/^[a-f0-9]{48}$/.test(productToken)) {
      throw new PublicError(400, "Parâmetros inválidos.");
    }
    return { kind: "produtos", token: productToken, page };
  }
  const lote = q.get("l") ?? "";
  const token = q.get("t") ?? "";
  if (
    !/^L[0-9]{4}-[0-9]{4}(?:-[a-zA-Z0-9]{1,16})?$/.test(lote) ||
    !/^[a-f0-9]{48}$/.test(token)
  ) {
    throw new PublicError(400, "Parâmetros inválidos.");
  }
  return { kind: "lote", lote, token, page };
}

export function pageAssets(
  sheet: Sheet,
  page: number,
  now = Date.now(),
): Asset[] {
  if (!Number.isFinite(sheet.expiresAt) || sheet.expiresAt <= now) {
    throw new PublicError(404, "Folha inexistente ou expirada.");
  }
  if (sheet.assets.length > MAX_ITEMS) {
    throw new PublicError(
      413,
      "Folha muito grande. Divida os SKUs em grupos menores.",
    );
  }
  if (sheet.assets.length === 0) {
    throw new PublicError(404, "Nenhuma mídia nesta folha.");
  }
  const assets = sheet.assets.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);
  if (!assets.length) throw new PublicError(404, "Página inexistente.");
  return assets;
}

/** Paths nunca são interpolados crus na URL. URLs de Storage devem ser deste projeto e bucket. */
export function storageURL(
  base: string,
  bucket: Asset["bucket"],
  ref: string,
): string {
  const origin = new URL(base);
  if (origin.protocol !== "https:" || origin.username || origin.password) {
    throw new Error("storage_config");
  }
  let path = ref;
  if (/^[a-z][a-z0-9+.-]*:/i.test(ref)) {
    const url = new URL(ref);
    if (url.origin !== origin.origin || url.username || url.password) {
      throw new Error("storage_origin");
    }
    const prefixes = [
      "/storage/v1/object/public/",
      "/storage/v1/object/authenticated/",
      "/storage/v1/object/sign/",
      "/storage/v1/object/",
    ];
    const prefix = prefixes.find((p) =>
      url.pathname.startsWith(p + bucket + "/")
    );
    if (!prefix) throw new Error("storage_bucket");
    path = decodeURIComponent(
      url.pathname.slice((prefix + bucket + "/").length),
    );
  } else if (path.startsWith(bucket + "/")) {
    path = path.slice(bucket.length + 1);
  }
  if (!path || path.length > 2048 || /[\\\x00-\x1f\x7f]/.test(path)) {
    throw new Error("storage_path");
  }
  const parts = path.split("/");
  if (
    parts.some((p) => !p || p === "." || p === ".." || /%2e|%2f|%5c/i.test(p))
  ) throw new Error("storage_path");
  return origin.origin + "/storage/v1/object/" + bucket + "/" +
    parts.map(encodeURIComponent).join("/");
}

/** Apenas mídias em CDN da Meta; links arbitrários e redirecionamentos nunca são seguidos. */
export function allowedMetaURL(ref: string): string {
  const url = new URL(ref);
  const host = url.hostname.toLowerCase();
  const allowed = ["cdninstagram.com", "fbcdn.net"].some((d) =>
    host === d || host.endsWith("." + d)
  );
  if (
    url.protocol !== "https:" || !allowed || url.port || url.username ||
    url.password || ref.length > 8192
  ) throw new Error("media_origin");
  url.hash = "";
  return url.href;
}

export function rasterFormat(
  bytes: Uint8Array,
): "Jpeg" | "Png" | "WebP" | "Gif" {
  if (
    bytes.length >= 3 && bytes[0] === 255 && bytes[1] === 216 &&
    bytes[2] === 255
  ) return "Jpeg";
  if (
    bytes.length >= 24 &&
    [137, 80, 78, 71, 13, 10, 26, 10].every((n, i) => bytes[i] === n)
  ) return "Png";
  const ascii = (from: number, to: number) =>
    String.fromCharCode(...bytes.slice(from, to));
  if (bytes.length >= 16 && ascii(0, 4) === "RIFF" && ascii(8, 12) === "WEBP") {
    return "WebP";
  }
  if (bytes.length >= 10 && ["GIF87a", "GIF89a"].includes(ascii(0, 6))) {
    return "Gif";
  }
  throw new Error("media_not_raster");
}

export async function readLimited(response: Response): Promise<Uint8Array> {
  if (!response.ok || !response.body) throw new Error("media_fetch");
  const announced = Number(response.headers.get("content-length") ?? "0");
  if (announced > MAX_ASSET_BYTES) {
    await response.body.cancel();
    throw new Error("media_size");
  }
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      size += value.length;
      if (size > MAX_ASSET_BYTES) {
        await reader.cancel();
        throw new Error("media_size");
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.length;
  }
  rasterFormat(bytes);
  return bytes;
}

export function createAssetLoader(
  config: { url: string; serviceKey: string },
  fetcher: typeof fetch = fetch,
) {
  return async (asset: Asset): Promise<Uint8Array> => {
    for (const privateSource of [true, false]) {
      if (privateSource ? !asset.path : !asset.url) continue;
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 8000);
      try {
        const url = privateSource
          ? storageURL(config.url, asset.bucket, asset.path!)
          : allowedMetaURL(asset.url!);
        const headers: Record<string, string> = {
          Accept: "image/jpeg,image/png,image/webp,image/gif",
        };
        if (privateSource) {
          headers.Authorization = `Bearer ${config.serviceKey}`;
          headers.apikey = config.serviceKey;
        }
        return await readLimited(
          await fetcher(url, {
            headers,
            redirect: "error",
            signal: controller.signal,
          }),
        );
      } catch {
        // Se a cópia privada falhou, tenta somente a CDN original autorizada.
      } finally {
        clearTimeout(timeout);
      }
    }
    throw new Error("media_unavailable");
  };
}
