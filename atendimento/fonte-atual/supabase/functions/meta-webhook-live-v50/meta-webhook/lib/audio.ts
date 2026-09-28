import {boundedBytes} from '../../ai-test/services.ts';

export const AUDIO_REVISION='v6.1-audio-20260910-r1';
export const MAX_AUDIO_BYTES=16*1024*1024;
export const MAX_AUDIO_TEXT=1900;
const types:Record<string,string>={'audio/ogg':'ogg','application/ogg':'ogg','audio/opus':'ogg','audio/mpeg':'mp3','audio/mp3':'mp3','audio/mp4':'m4a','audio/x-m4a':'m4a','video/mp4':'mp4','audio/wav':'wav','audio/x-wav':'wav','audio/wave':'wav','audio/webm':'webm','video/webm':'webm','audio/flac':'flac','audio/x-flac':'flac'};
export function audioFormat(bytes:Uint8Array,declared:string):{mime:string;ext:string}{
 const type=declared.split(';')[0].trim().toLowerCase();
 const s=new TextDecoder('latin1').decode(bytes.slice(0,16));
 if(bytes.length<16)throw Error('audio_empty');
 if(s.startsWith('OggS'))return {mime:'audio/ogg',ext:'ogg'};
 if(s.startsWith('RIFF')&&s.slice(8,12)==='WAVE')return {mime:'audio/wav',ext:'wav'};
 if(s.startsWith('fLaC'))return {mime:'audio/flac',ext:'flac'};
 if(s.slice(4,8)==='ftyp')return {mime:'audio/mp4',ext:'m4a'};
 if(bytes[0]===0x1a&&bytes[1]===0x45&&bytes[2]===0xdf&&bytes[3]===0xa3)return {mime:'audio/webm',ext:'webm'};
 if(s.startsWith('ID3')||(bytes[0]===255&&(bytes[1]&0xe0)===0xe0))return {mime:'audio/mpeg',ext:'mp3'};
 // Do not accept HTML/error pages or arbitrary files based on a forged MIME.
 throw Error(types[type]?'audio_invalid':'audio_type_unsupported');
}
export type AudioTranscript={text:string;model:string;revision:string;needsClarification:boolean;reason:string|null;bytes:number};
export async function transcribeAudio(bytes:ArrayBuffer|Uint8Array,declared:string,key:string,model='gpt-4o-transcribe',fetcher:typeof fetch=fetch):Promise<AudioTranscript>{
 const data=bytes instanceof Uint8Array?bytes:new Uint8Array(bytes);
 if(!key)throw Error('audio_not_configured');
 if(data.byteLength>MAX_AUDIO_BYTES)throw Error('audio_too_large');
 const format=audioFormat(data,declared);
 const form=new FormData();form.append('file',new Blob([data as BlobPart],{type:format.mime}),'mensagem.'+format.ext);
 form.append('model',model);form.append('language','pt');form.append('response_format','json');
 form.append('prompt','Conversa em português brasileiro com uma loja de roupas. Transcreva somente a fala audível, preservando perguntas, negações, correções, cores e tamanhos.');
 if(/^gpt-4o(?:-mini)?-transcribe(?:-\d{4}-\d{2}-\d{2})?$/.test(model))form.append('include[]','logprobs');
 const response=await fetcher('https://api.openai.com/v1/audio/transcriptions',{method:'POST',headers:{Authorization:`Bearer ${key}`},body:form,signal:AbortSignal.timeout(45000),redirect:'error'});
 if(!response.ok){await response.body?.cancel();throw Error('audio_service_'+response.status);}
 const result=JSON.parse(new TextDecoder().decode(await boundedBytes(response,250000)));
 const text=typeof result.text==='string'?result.text.trim():'';
 const probs=(Array.isArray(result.logprobs)?result.logprobs:[]).map((p:any)=>p.logprob).filter((p:any)=>typeof p==='number'&&Number.isFinite(p));
 // Log probabilities are an uncertainty signal, not a calibrated accuracy score.
 const poor=probs.length>0&&(probs.reduce((a:number,b:number)=>a+b,0)/probs.length < -1.0 || probs.filter((p:number)=>p < -2.5).length/probs.length>0.18);
 const reason=!text?'no_speech':text.length>MAX_AUDIO_TEXT?'audio_too_long':poor?'unclear_speech':null;
 return {text,model,revision:AUDIO_REVISION,needsClarification:!!reason,reason,bytes:data.byteLength};
}

