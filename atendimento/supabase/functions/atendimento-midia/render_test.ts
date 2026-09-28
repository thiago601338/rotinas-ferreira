import * as magick from "npm:@imagemagick/magick-wasm@0.0.43";
import { type Asset } from "./core.ts";
import { initializeRenderer, renderSheet } from "./render.ts";

function assert(
  condition: unknown,
  message = "assertion failed",
): asserts condition {
  if (!condition) throw new Error(message);
}

Deno.test("WASM real gera JPEG de 12 posições e mantém ausência no lugar correto", async () => {
  await initializeRenderer();
  const image = magick.ImageMagick.read(
    new magick.MagickColor("#b6bfd8"),
    1080,
    1920,
    (i) => i.write(magick.MagickFormat.Jpeg, (b) => new Uint8Array(b)),
  );
  const assets = Array.from(
    { length: 12 },
    (_, i): Asset => ({
      label: `FB-${String(i + 1).padStart(4, "0")}`,
      detail: i % 2 ? "amarelo manteiga" : "azul marinho",
      bucket: "product-photos",
      path: String(i),
    }),
  );
  const order: string[] = [];
  const result = await renderSheet(
    assets,
    "FOTOS DO CADASTRO",
    1,
    2,
    (asset) => {
      order.push(asset.label);
      if (asset.path === "4") throw new Error("missing");
      return Promise.resolve(image);
    },
  );
  assert(result.bytes[0] === 255 && result.bytes[1] === 216);
  assert(result.missing === 1);
  assert(order.join(",") === assets.map((a) => a.label).join(","));
  const info = magick.MagickImageInfo.create(result.bytes);
  assert(info.width === 816 && info.height === 2120);
});

Deno.test("cabeçalho/rotulo de mídia ausente continua legível em página de um item", async () => {
  const result = await renderSheet(
    [{ label: "s1", detail: "story", bucket: "ai-inbox-media" }],
    "LOTE L0927-1930",
    2,
    2,
    () => {
      throw new Error("no_image");
    },
  );
  assert(result.missing === 1 && result.bytes.length > 3000);
});

Deno.test("fotos WebP do cadastro e imagens PNG/GIF entram no JPEG sem perda de posição", async () => {
  await initializeRenderer();
  const formats = [
    magick.MagickFormat.WebP,
    magick.MagickFormat.Png,
    magick.MagickFormat.Gif,
  ];
  const sources = formats.map((format) =>
    magick.ImageMagick.read(
      new magick.MagickColor("#abc9a2"),
      320,
      500,
      (image) => image.write(format, (bytes) => new Uint8Array(bytes)),
    )
  );
  const result = await renderSheet(
    formats.map((format, i) => ({
      label: "f" + (i + 1),
      detail: format,
      bucket: "ai-inbox-media" as const,
      path: String(i),
    })),
    "FORMATOS",
    1,
    1,
    (asset) => Promise.resolve(sources[Number(asset.path)]),
  );
  assert(result.missing === 0);
  assert(result.bytes[0] === 255 && result.bytes[1] === 216);
});
