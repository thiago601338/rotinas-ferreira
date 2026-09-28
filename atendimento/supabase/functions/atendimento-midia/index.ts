import { createAssetLoader } from "./core.ts";
import { createHandler } from "./handler.ts";
import { createRepository } from "./repository.ts";
import { renderSheet } from "./render.ts";

function env(name: string): string {
  const value = Deno.env.get(name);
  if (!value) throw new Error("Configuração de atendimento-midia incompleta.");
  return value;
}
if (import.meta.main) {
  const repository = createRepository(env("SUPABASE_DB_URL"));
  const loadAsset = createAssetLoader({
    url: env("SUPABASE_URL"),
    serviceKey: env("SUPABASE_SERVICE_ROLE_KEY"),
  });
  Deno.serve(
    createHandler({
      loadSheet: repository.load,
      render: (assets, title, page, pages) =>
        renderSheet(assets, title, page, pages, loadAsset),
    }),
  );
}
