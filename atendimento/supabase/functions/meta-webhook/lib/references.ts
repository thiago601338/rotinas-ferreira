/** A visual reply is a new product reference, never permission to reuse an unrelated focus. */
export const STORY_REFERENCE_REVISION='v6.0-story-reference-20260910-r1';
export type StoryReference={kind:'story';id:string|null;url:string|null};
const value=(x:any,max=8192)=>typeof x==='string'&&x.length<=max&&x.trim()?x.trim():null;
export function instagramStoryReference(message:any):StoryReference|null{
 const reply=message?.reply_to;
 if(reply&&Object.prototype.hasOwnProperty.call(reply,'story')){
  return {kind:'story',id:value(reply.story?.id,200),url:value(reply.story?.url)};
 }
 const story=(message?.attachments??[]).find((a:any)=>['story_mention','story','ig_story'].includes(a?.type));
 if(story)return {kind:'story',id:value(story.payload?.id,200),url:value(story.payload?.url)};
 return null;
}
export function referencedTurn(pending:any[]){
 const refs=pending.flatMap((row,index)=>{
  const m=row.raw_payload??row;
  if(m.storyReference)return [{index,row,story:m.storyReference,replyTo:null,key:'story:'+(m.storyReference.id??m.storyReference.url??m.externalMessageId??index)}];
  if(m.replyTo)return [{index,row,story:null,replyTo:m.replyTo,key:'message:'+m.replyTo}];
  return [];
 });
 return {reference:refs.at(-1)??null,ambiguous:new Set(refs.map(r=>r.key)).size>1};
}
export function referenceHistory(rows:any[],anchor:any){
 if(!anchor?.since)return rows;
 const since=Date.parse(anchor.since);
 return Number.isFinite(since)?rows.filter(row=>Date.parse(row.created_at)>=since):[];
}
export function unresolvedReference(anchor:any){
 return {productId:null,mode:'focus',color:null,size:null,referenceContext:{...anchor,awaitingImage:true}};
}
export function attachReferenceContext(result:any,anchor:any){
 if(!anchor)return result.contextoProduto;
 if(result.contextoProduto?.productId)return {...result.contextoProduto,referenceContext:{...anchor,awaitingImage:false}};
 const choices=(result.candidatosConfirmaveis??[]).filter((id:string)=>(result.fotos??[]).some((f:any)=>f.id===id));
 if(choices.length){
  // Only the products compared with THIS image can be selected in the next turn.
  return {productId:null,mode:'browse',color:result.interpretacao?.cor??null,size:result.interpretacao?.tamanho??null,
   search:{kind:result.fotos[0]?.nome,color:result.interpretacao?.cor??null,size:result.interpretacao?.tamanho??null,exclude:[],shown:[],choices},
   recognizedProducts:choices,referenceContext:{...anchor,awaitingImage:false,awaitingConfirmation:true}};
 }
 return result.contextoProduto?{...result.contextoProduto,referenceContext:anchor}:unresolvedReference(anchor);
}
