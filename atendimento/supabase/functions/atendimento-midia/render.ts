import * as magick from "npm:@imagemagick/magick-wasm@0.0.43";
import { type Asset, PAGE_SIZE, PublicError, rasterFormat } from "./core.ts";

const W = 256, H = 456, GAP = 12, LABEL_H = 48, HEADER_H = 44;
let initialized: Promise<void> | undefined;
let rendering = false;

export async function initializeRenderer() {
  initialized ??= (async () => {
    // Arquivo incluído no pacote npm; não baixa código nem WASM por rede durante a chamada.
    const wasm = await Deno.readFile(
      new URL(
        "x86/magick.wasm",
        import.meta.resolve("npm:@imagemagick/magick-wasm@0.0.43"),
      ),
    );
    await magick.initializeImageMagick(wasm);
    magick.ResourceLimits.memory = 112n * 1024n * 1024n;
    magick.ResourceLimits.disk = 0n;
    magick.ResourceLimits.width = 8192n;
    magick.ResourceLimits.height = 8192n;
    magick.ResourceLimits.area = 8_000_000n;
    // O limite inclui imagens temporárias internas; frameCount=1 restringe a entrada.
    magick.ResourceLimits.listLength = 16n;
    magick.ResourceLimits.maxProfileSize = 1024n * 1024n;
  })().catch((e) => {
    initialized = undefined;
    throw e;
  });
  await initialized;
}

// Fonte bitmap própria. Rótulos não dependem de fontes do sistema ou arquivos externos.
const FONT: Record<string, string> = {
  A: "01110/10001/10001/11111/10001/10001/10001",
  B: "11110/10001/10001/11110/10001/10001/11110",
  C: "01111/10000/10000/10000/10000/10000/01111",
  D: "11110/10001/10001/10001/10001/10001/11110",
  E: "11111/10000/10000/11110/10000/10000/11111",
  F: "11111/10000/10000/11110/10000/10000/10000",
  G: "01111/10000/10000/10111/10001/10001/01110",
  H: "10001/10001/10001/11111/10001/10001/10001",
  I: "11111/00100/00100/00100/00100/00100/11111",
  J: "00111/00010/00010/00010/10010/10010/01100",
  K: "10001/10010/10100/11000/10100/10010/10001",
  L: "10000/10000/10000/10000/10000/10000/11111",
  M: "10001/11011/10101/10101/10001/10001/10001",
  N: "10001/11001/10101/10011/10001/10001/10001",
  O: "01110/10001/10001/10001/10001/10001/01110",
  P: "11110/10001/10001/11110/10000/10000/10000",
  Q: "01110/10001/10001/10001/10101/10010/01101",
  R: "11110/10001/10001/11110/10100/10010/10001",
  S: "01111/10000/10000/01110/00001/00001/11110",
  T: "11111/00100/00100/00100/00100/00100/00100",
  U: "10001/10001/10001/10001/10001/10001/01110",
  V: "10001/10001/10001/10001/10001/01010/00100",
  W: "10001/10001/10001/10101/10101/11011/10001",
  X: "10001/10001/01010/00100/01010/10001/10001",
  Y: "10001/10001/01010/00100/00100/00100/00100",
  Z: "11111/00001/00010/00100/01000/10000/11111",
  "0": "01110/10001/10011/10101/11001/10001/01110",
  "1": "00100/01100/00100/00100/00100/00100/01110",
  "2": "01110/10001/00001/00010/00100/01000/11111",
  "3": "11110/00001/00001/01110/00001/00001/11110",
  "4": "00010/00110/01010/10010/11111/00010/00010",
  "5": "11111/10000/10000/11110/00001/00001/11110",
  "6": "01110/10000/10000/11110/10001/10001/01110",
  "7": "11111/00001/00010/00100/01000/01000/01000",
  "8": "01110/10001/10001/01110/10001/10001/01110",
  "9": "01110/10001/10001/01111/00001/00001/01110",
  "-": "00000/00000/00000/11111/00000/00000/00000",
  "/": "00001/00001/00010/00100/01000/10000/10000",
  ".": "00000/00000/00000/00000/00000/00100/00100",
  ":": "00000/00100/00100/00000/00100/00100/00000",
  "?": "01110/10001/00001/00010/00100/00000/00100",
};

function textPixels(
  pixels: Uint8Array,
  width: number,
  x: number,
  y: number,
  text: string,
  maxChars: number,
  scale = 2,
) {
  const clean = text.normalize("NFD").replace(/[\u0300-\u036f]/g, "")
    .toUpperCase();
  const clipped = clean.length > maxChars
    ? clean.slice(0, maxChars - 3) + "..."
    : clean;
  for (const [index, char] of [...clipped].entries()) {
    if (char === " ") continue;
    const rows = (FONT[char] ?? FONT["?"]).split("/");
    for (let row = 0; row < 7; row++) {
      for (let col = 0; col < 5; col++) {
        if (rows[row][col] !== "1") continue;
        for (let dy = 0; dy < scale; dy++) {
          for (let dx = 0; dx < scale; dx++) {
            const at = ((y + row * scale + dy) * width + x + index * 6 * scale +
              col * scale + dx) * 3;
            if (at >= 0 && at + 2 < pixels.length) pixels.set([30, 33, 41], at);
          }
        }
      }
    }
  }
}

function ppm(width: number, height: number, pixels: Uint8Array): Uint8Array {
  const header = new TextEncoder().encode(`P6\n${width} ${height}\n255\n`);
  const data = new Uint8Array(header.length + pixels.length);
  data.set(header);
  data.set(pixels, header.length);
  return data;
}

/** Uma página por vez, original inteiro contido na miniatura, sem corte da peça. */
export async function renderSheet(
  assets: Asset[],
  title: string,
  page: number,
  pages: number,
  load: (asset: Asset) => Promise<Uint8Array>,
): Promise<{ bytes: Uint8Array; missing: number }> {
  if (!assets.length || assets.length > PAGE_SIZE) {
    throw new Error("render_page_size");
  }
  if (rendering) {
    throw new PublicError(
      503,
      "Gerando outra folha. Tente novamente em instantes.",
    );
  }
  rendering = true;
  try {
    await initializeRenderer();
    const columns = Math.min(3, assets.length),
      rows = Math.ceil(assets.length / columns);
    const width = GAP + columns * (W + GAP),
      height = HEADER_H + rows * (H + LABEL_H + GAP) + GAP;
    const pixels = new Uint8Array(width * height * 3).fill(247);
    textPixels(
      pixels,
      width,
      GAP,
      12,
      `${title} - ${page}/${pages}`,
      Math.floor((width - GAP * 2) / 12),
    );
    assets.forEach((asset, i) => {
      const x = GAP + (i % columns) * (W + GAP),
        y = HEADER_H + Math.floor(i / columns) * (H + LABEL_H + GAP);
      textPixels(pixels, width, x + 4, y + H + 8, asset.label, 21);
      textPixels(pixels, width, x + 4, y + H + 28, asset.detail, 21);
    });
    let missing = 0;
    const deadline = Date.now() + 65_000;
    const bytes = await magick.ImageMagick.read(
      ppm(width, height, pixels),
      magick.MagickFormat.Ppm,
      async (sheet) => {
        for (const [i, asset] of assets.entries()) {
          const x = GAP + (i % columns) * (W + GAP),
            y = HEADER_H + Math.floor(i / columns) * (H + LABEL_H + GAP);
          try {
            if (Date.now() >= deadline) throw new Error("page_deadline");
            const data = await load(asset);
            const settings = new magick.MagickReadSettings({
              format: magick.MagickFormat[rasterFormat(data)],
              frameIndex: 0,
              frameCount: 1,
            });
            const info = magick.MagickImageInfo.create(data, settings);
            if (
              info.width < 1 || info.height < 1 ||
              info.width * info.height > 8_000_000
            ) throw new Error("image_dimensions");
            magick.ImageMagick.read(data, settings, (image) => {
              image.autoOrient();
              const scale = Math.min(1, W / image.width, H / image.height);
              image.resize(
                Math.max(1, Math.round(image.width * scale)),
                Math.max(1, Math.round(image.height * scale)),
              );
              image.strip();
              sheet.composite(
                image,
                new magick.Point(
                  x + Math.floor((W - image.width) / 2),
                  y + Math.floor((H - image.height) / 2),
                ),
              );
            });
          } catch {
            missing++;
            const placeholder = new Uint8Array(W * H * 3).fill(230);
            textPixels(placeholder, W, 14, H / 2 - 22, "SEM IMAGEM", 19);
            textPixels(
              placeholder,
              W,
              14,
              H / 2 + 2,
              asset.bucket === "product-photos"
                ? "FOTO INDISPONIVEL"
                : "ABRIR INSTAGRAM",
              19,
            );
            magick.ImageMagick.read(
              ppm(W, H, placeholder),
              magick.MagickFormat.Ppm,
              (image) => sheet.composite(image, new magick.Point(x, y)),
            );
          }
        }
        sheet.strip();
        sheet.quality = 82;
        return sheet.write(
          magick.MagickFormat.Jpeg,
          (data) => new Uint8Array(data),
        );
      },
    );
    return { bytes, missing };
  } finally {
    rendering = false;
  }
}
