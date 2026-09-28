# atendimento-midia

Gera uma folha JPEG, sem IA, a partir das mídias autorizadas por um token de lote ou de produtos. Não envia mensagens, não grava no banco e não grava no Storage.

## Contrato

- `GET ?l=L0927-1930&t=<48 caracteres hexadecimais>&p=1`: consulta `atendimento.lotes` e `lote_itens.midias`.
- `GET ?produtos=<48 caracteres hexadecimais>&p=1`: consulta `atendimento.folhas_produtos`; a lista de SKUs vem somente dessa linha.
- `HEAD` aceita os mesmos parâmetros e valida token/página sem gerar a imagem.
- Tokens são criados no SQL, válidos por 6 horas. A função rejeita token expirado antes e depois de gerar a imagem. `p=2` avança 12 itens; a ordem é da composição do lote.
- Retorno: `image/jpeg`, `Cache-Control: private, no-store`, `Referrer-Policy: no-referrer`.
- Cabeçalhos: `X-Atendimento-Pagina`, `X-Atendimento-Paginas` e, no GET, `X-Atendimento-Sem-Imagem`.
- 400: parâmetros inválidos; 404: token/página inexistente ou expirada; 413: mais de 1.000 imagens; 503: renderer ocupado no mesmo isolate. Erros internos retornam mensagem genérica sem URL, token ou DSN.

Cada mídia de lote usa `{label,path|url,kind}`. `path` identifica objeto do bucket privado `ai-inbox-media`; `url` só aceita CDNs HTTPS `*.cdninstagram.com` ou `*.fbcdn.net`. A função preserva a posição de falhas com `SEM IMAGEM / ABRIR INSTAGRAM`. Produtos usam somente cores com `stock>0`; foto de frente por cor, ou `photo_url` quando `cover_color` comprova a cor. Ausência de imagem aparece como `FOTO INDISPONIVEL` e nunca recebe foto de outra cor.

## Runtime e configuração

Requer `SUPABASE_DB_URL`, `SUPABASE_URL` e `SUPABASE_SERVICE_ROLE_KEY` da Edge Function. Não colocar valores no repositório. A conexão Postgres permite somente leitura e usa consultas parametrizadas: o schema `atendimento` continua fora da Data API. A service key é usada exclusivamente no host de Storage configurado, nunca em CDN.

Na configuração central do Supabase:

```toml
[functions.atendimento-midia]
verify_jwt = false
```

A autorização é o token aleatório da folha, e não JWT público. Compartilhar a URL dá acesso às imagens até ela expirar. A função não aceita URLs ou SKUs extras na requisição.

Dependências fixadas: `npm:postgres@3.4.7` e `npm:@imagemagick/magick-wasm@0.0.43`, com `deno.lock`. O WASM vem do pacote npm, via `Deno.readFile` e `import.meta.resolve`, seguindo a integração oficial Supabase/ImageMagick. Os rótulos usam fonte bitmap embutida: não há fonte do sistema, Sharp ou processo nativo.

## Limites e mídia de vídeo

- 12 posições por página, em até 3 colunas; cada foto cabe inteira em 256 × 456 px, preservando proporção.
- Entrada: JPEG, PNG, WebP ou primeiro quadro de GIF; até 5 MiB e 8 milhões de pixels por objeto. SVG, HTML, PDF, URLs arbitrárias e vídeos brutos não são interpretados.
- Cada download tem 8 segundos; a página tem orçamento de 65 segundos antes de iniciar mais downloads. A decodificação acontece sequencialmente para limitar memória. O conteúdo recebido é validado por assinatura e formato explícito.
- Quadros de story/vídeo precisam estar salvos como imagem por prefetch/sync. Se `media_path` apontar a MP4, aparece o marcador de imagem indisponível; esta função não usa FFmpeg nem inventa uma capa. O responsável pela coleta deve gravar `storyPrefetch.imagePath` ou outro caminho de quadro na mídia do lote.
- Redirecionamentos de rede são rejeitados. Uma CDN expirada aparece como imagem indisponível; renovar e persistir a mídia pertence a prefetch/sync.
- A ausência de foto não desaparece da folha e não muda os rótulos das posições seguintes.

## Verificação local

Na pasta desta função, executar `deno task check` e `deno task test`. Não requer conexão ao banco ou à Meta. São cobertos tokens, paginação, expiração durante geração, bloqueio de SSRF, segregação da service key, limite de download e geração de JPEG real com 12 posições no WASM.

O teste de 12 imagens sintéticas 1080 × 1920 concluiu localmente. A validação hospedada ainda precisa confirmar o empacotamento do WASM e a CPU de imagens representativas dentro dos limites da Edge Function. Nenhum deploy foi executado por esta implementação.

Referências oficiais consultadas em 27/09/2026: [WASM](https://supabase.com/docs/guides/functions/wasm), [ImageMagick no Edge](https://supabase.com/docs/guides/functions/examples/image-manipulation), [limites](https://supabase.com/docs/guides/functions/limits). A plataforma informa limite de CPU por requisição; não confundir tempo de download com tempo de processamento.
