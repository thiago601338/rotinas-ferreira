import {decodeImage} from '../../ai-test/core.ts';
let magick:any,ready:Promise<void>|null=null;
async function initialize(){
  magick=await import('npm:@imagemagick/magick-wasm@0.0.43');
  const d=(globalThis as any).Deno;
  const bytes=await d.readFile(new URL('x86/magick.wasm',import.meta.resolve('npm:@imagemagick/magick-wasm@0.0.43')));
  await magick.initializeImageMagick(bytes);
}
export async function jpegForMeta(dataUrl:string):Promise<Uint8Array>{
  if(!ready)ready=initialize().catch(e=>{ready=null;throw e;});await ready;
  return convertWithMagick(dataUrl,magick);
}
export function convertWithMagick(dataUrl:string,magick:any):Uint8Array{
  const input=decodeImage(dataUrl);
  return magick.ImageMagick.read(input.bytes,(img:any)=>{
    if(img.width*img.height>24_000_000)throw Error('image_dimensions_too_large');
    img.autoOrient();
    const scale=Math.min(1,1600/Math.max(img.width,img.height));
    if(scale<1)img.resize(Math.max(1,Math.round(img.width*scale)),Math.max(1,Math.round(img.height*scale)));
    img.strip();img.quality=85;
    return img.write(magick.MagickFormat.Jpeg,(bytes:Uint8Array)=>{
      if(bytes.length>5*1024*1024||bytes[0]!==255||bytes[1]!==216)throw Error('meta_image_invalid');
      return new Uint8Array(bytes);
    });
  });
}
