import {rpc} from './supabase.ts';
import {ANSWER_POLICY_REVISION,type AnswerVerdict} from './answer-policy.ts';

export async function blockForHuman(conversationId:string,lastInboundId:string,verdict:AnswerVerdict){
 return await rpc('ai_wait_finish',{p_conversation:conversationId,p_last_inbound:lastInboundId,p_state:'blocked',p_category:verdict.category,p_reason:verdict.reason,p_revision:ANSWER_POLICY_REVISION});
}
export async function resolveHumanWait(conversationId:string,lastInboundId:string){
 return await rpc('ai_wait_finish',{p_conversation:conversationId,p_last_inbound:lastInboundId,p_state:'answered',p_category:null,p_reason:null,p_revision:ANSWER_POLICY_REVISION});
}
export async function deliveryStillAllowed(conversationId:string,lastInboundId:string,owner:string){
 return await rpc<boolean>('ai_delivery_allowed',{p_conversation:conversationId,p_last_inbound:lastInboundId,p_owner:owner});
}

