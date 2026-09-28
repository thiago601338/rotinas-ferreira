import postgres from 'postgres';
import { createHandler } from './core.mjs';
import { createDatabase } from './database.mjs';

// verify_jwt=false no config.toml; createHandler valida x-ai-followup-token no banco.
const handler = createHandler({
  env: (name: string) => Deno.env.get(name),
  openDatabase: async () => {
    const url = Deno.env.get('SUPABASE_DB_URL');
    if (!url) throw new Error('database_not_configured');
    const sql = postgres(url, {
      prepare: false, ssl: 'require', max: 5, connect_timeout: 10, idle_timeout: 20,
      connection: { application_name: 'atendimento-enviar', statement_timeout: 10000 },
      onnotice: () => {},
    });
    return createDatabase(sql);
  },
});

Deno.serve(handler);
