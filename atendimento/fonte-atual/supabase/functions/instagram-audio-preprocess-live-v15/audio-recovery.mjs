export const AUDIO_RECOVERY_REVISION='instagram-audio-confident-only-20260912-r1';
const confident=t=>t?.clear===true&&Number.isFinite(t.avgLogprob)&&t.avgLogprob>=-.55&&Number.isFinite(t.lowRatio)&&t.lowRatio<=.06;
export async function recoverAudio(original,token,{transcribe,clean,critical}){
 let first=null;
 try{first=await transcribe(original);}catch(e){if(e.message==='audio_service_failed')throw e;}
 if(confident(first))return {...first,source:'original',cleanupAttempted:false};
 let cleaned;
 try{cleaned=await clean(original,token);}catch{throw Error('audio_cleanup_unresolved');}
 let second;
 try{second=await transcribe(cleaned.bytes);}catch{throw Error('audio_unclear');}
 if(!confident(second))throw Error('audio_unclear');
 if(first?.clear&&critical(first.text)!==critical(second.text))throw Error('audio_cleanup_conflict');
 return {...second,source:'cleaned',cleanupAttempted:true,cleanupRevision:cleaned.revision,cleanupMetrics:cleaned.metrics};
}

