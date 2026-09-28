-- Igualdade de texto só é evidência no fluxo manual pelo Instagram.
-- Uma parte da API ainda em envio não tem identidade confirmada: a equipe pode
-- ter enviado a mesma saudação. O webhook verifica external_message_id e
-- concluir_envio reconcilia apenas o ID devolvido pela Meta, preservando outros ecos.
create or replace function public.ai_atendimento_echo_previsto(p_conversation uuid,p_texto text) returns boolean
language sql stable security definer set search_path = '' as $$
  select exists(select 1 from atendimento.envios e
    join atendimento.lote_itens li on li.lote=e.lote and li.n=e.n
    where li.conversation_id=p_conversation and e.texto=p_texto
      and e.status='pelo_instagram' and e.criado_em>now()-interval '2 hours')
$$;
revoke all on function public.ai_atendimento_echo_previsto(uuid,text) from public,anon,authenticated;
grant execute on function public.ai_atendimento_echo_previsto(uuid,text) to service_role;
