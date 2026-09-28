-- Base: fonte-atual/sql/estado-do-banco.sql, public.ai_claim_followup, 27/09/2026.
-- Única mudança de comportamento: Instagram no modo claude nunca é reclamado
-- pelo human-followup, mesmo se a política do quiet-worker for alterada.
-- As condições de WhatsApp, bloqueios, leases, retorno e permissões são preservadas.
-- O cron existente permanece ativo. Voltar para ia desativa esta guarda adicional.
CREATE OR REPLACE FUNCTION public.ai_claim_followup(p_owner uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
declare c public.ai_conversations; w public.ai_human_waits; m public.ai_messages;
begin
 -- Lock conversations first, matching the inbound/manual-message trigger order.
 select c0.* into c from public.ai_conversations c0 join public.ai_human_waits w0 on w0.conversation_id=c0.id
 where not (c0.channel='instagram' and atendimento.modo_atual()='claude')
  and not (c0.channel='instagram' and exists(select 1 from public.ai_settings where key='instagram_turn_policy' and value->>'enabled'='true' and value->>'workerFunction'='instagram-turn-worker-v6')) and w0.state='waiting' and ((c0.status='human' and w0.due_at<=now() and c0.metadata ? 'manualEchoObservedAt') or (c0.status='open' and (w0.updated_at<now()-interval '30 seconds' or c0.channel='instagram') and (w0.due_at is null or w0.due_at<=now()))) and w0.inbound_at>now()-interval '24 hours'
 and not exists(select 1 from public.ai_instagram_turn_queue q where q.conversation_id=c0.id and (q.last_inbound_id<>w0.last_inbound_id or q.state<>'ready' or q.due_at>clock_timestamp() or q.not_before>clock_timestamp()))
 and not(c0.metadata ? 'aiProcessing')
 and not exists(select 1 from public.ai_optouts o where o.channel=c0.channel and o.external_user_id=c0.external_user_id)
 order by w0.due_at for update of c0 skip locked limit 1;
 if not found then return null; end if;
 select * into w from public.ai_human_waits where conversation_id=c.id for update;
 if w.state<>'waiting' or w.due_at>now() then return null; end if;
 select * into m from public.ai_messages where id=w.last_inbound_id;
 if not found then return null; end if;
 update public.ai_human_waits set state='evaluating',updated_at=now() where conversation_id=c.id;
 update public.ai_conversations set status='open',metadata=coalesce(metadata,'{}'::jsonb)||jsonb_build_object(
  'aiProcessing',jsonb_build_object('owner',p_owner,'expiresAt',now()+interval '180 seconds','recoverySafe',true,'lastInboundId',(select last_inbound_id from public.ai_human_waits where conversation_id=c.id)),
  'aiFollowup',jsonb_build_object('owner',p_owner,'lastInboundId',w.last_inbound_id,'generation',w.generation,'startedAt',now(),'afterHumanWait',(c.status='human' or coalesce((c.metadata->>'aiIgAfterHumanWait')::boolean,false))))
 where id=c.id returning * into c;
 return jsonb_build_object('conversation',to_jsonb(c),'message',m.raw_payload,'lastInboundId',w.last_inbound_id,'owner',p_owner,'afterHumanWait',c.metadata->'aiFollowup'->'afterHumanWait');
end $function$
;
