// Postgres direto preserva o schema atendimento fora da Data API.
// Todos os parâmetros passam pelo template seguro do postgres.js.
export function createDatabase(sql) {
  return {
    async authorize(token) {
      const rows = await sql`select public.ai_followup_valid(${token}) as valid`;
      return rows[0]?.valid === true;
    },
    async metaToken() {
      const rows = await sql`select public.ai_meta_token_get() as token`;
      return rows[0]?.token ?? null;
    },
    async mode() {
      const rows = await sql`select atendimento.modo_atual() as mode`;
      return rows[0]?.mode ?? null;
    },
    async claim() {
      const rows = await sql`select atendimento.claim_envio() as job`;
      return rows[0]?.job ?? null;
    },
    async deliveryAllowed(job) {
      const rows = await sql`select atendimento.envio_autorizado(
        ${job.lote}::text, ${job.n}::text, ${job.parte}::int, ${job.owner}::uuid
      ) as allowed`;
      return rows[0]?.allowed === true;
    },
    async status(job) {
      const rows = await sql`select status from atendimento.envios
        where lote=${job.lote} and n=${job.n} and parte=${job.parte} and owner=${job.owner}::uuid`;
      return rows[0]?.status ?? 'bloqueado';
    },
    async complete(job, outcome) {
      const rows = await sql`select atendimento.concluir_envio(
        ${job.lote}::text, ${job.n}::text, ${job.parte}::int, ${job.owner}::uuid,
        ${outcome.messageId}::text, ${outcome.error}::text
      ) as status`;
      return rows[0]?.status ?? 'estado_invalido';
    },
    async close() { await sql.end({ timeout: 1 }); },
  };
}
