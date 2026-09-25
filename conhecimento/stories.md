# Stories da Ferreira Boutique — regras

Regras ditadas pelo usuário entre 22 e 25/09/2026 e o que foi comprovado nas postagens feitas até agora. **Tudo aqui é obrigatório.**

## O que é
- É **story**, não post no feed.
- Postagem só pelo **BlueStacks** no PC. O LDPlayer não é mais usado.

## Pastas e nomes
- Fonte das mídias, sempre: `C:\Users\V15\Documents\Stories da Loja\<data>\` (ex.: `2026-09-22`).
- Uma letra por modelo (peça). Dentro da letra, `A - 1` é o vídeo e `A - 2`, `A - 3`… são as fotos, na sequência. Depois vêm B, C, D…
- Numa pasta que já tem letras, continuar da próxima letra livre. Nunca sobrescrever.
- A pasta antiga do LDPlayer (`Documents\XuanZhi14\Pictures`) não é mais usada.

## Regra fixa 1 — só entra o que tem estoque
Toda rotina de stories começa pela conferência de estoque: postagem, compilação de modelos e repost de destaque. Não tem exceção.

```sql
select p.sku, p.name, p.category, v.color, v.size, v.stock
from products p join product_variations v on v.product_id = p.id
where p.status = 'Ativo' and p.deleted_at is null
  and (p.sku = 'FB-0000' or p.name ilike '%termo da peça%')
order by v.color, v.size;
```

- Cor com estoque 0 não vai para o story. Cortar na hora, montar a letra só com as cores que têm estoque e **avisar depois** quais ficaram de fora, para ele decidir se reposta. Só volta se houver reposição.
- Modelo sem nenhuma peça não entra.

Esquema lido em 25/09/2026 (projeto Supabase `nailfzcujyxydqldktgg`, schema `public`):
- `products`: id, name, sku, category, fabric, gender, sale_price, cost_price (**não ler**), status, notes, photo_url, created_at, updated_at, catalog_media (jsonb), catalog_attributes (jsonb), search_aliases (text[]), deleted_at, deleted_by, deleted_reason.
- `product_variations`: id, product_id, size, color, stock, created_at, updated_at.

## Regra fixa 2 — não repetir
Antes de postar, sempre verificar se o modelo já não foi postado antes (letras já existentes nas pastas de data e stories recentes).

## Formato das mídias
- `.mov` não aparece na galeria do Instagram no emulador. Converter para `.mp4` antes.
- Importação atual: Gerenciador de Mídia do BlueStacks → Importar do Windows. É confiável só até ~5 arquivos por vez: em dois lotes de 6, um arquivo ficou de fora sem aviso. Sempre conferir a lista depois.

## No Instagram
1. + → Story → galeria → "Selecionar" → tocar nas mídias na ordem → Avançar.
2. Vídeo sem áudio recebe trilha pela música do Instagram, escolhendo entre:
   - "I know what you want" (Madison Beer/Calley)
   - Áudio original (petermarkoski)
   - Áudio original (neetunomusic)
   - Clocks – Coldplay (leveviolao)
   - Áudio original (enfermeira_vitoria0)
3. Figurinha de link **só na última mídia de cada letra**.
4. Publicar em "Seu story" → Concluir. Não compartilhar no Facebook.

## Figurinha de link (botão de comprar)
- Destino: WhatsApp da loja, (82) 98874-8649, com a mensagem de compra já escrita.
- Formato escolhido pelo usuário: `wa.me/5582988748649?text=…` (com o 55 e a mensagem preenchida), no lugar do formato com hífens que ele usava antes.
- **Digitar sem `https://`.** Com `https://` a figurinha aparece na imagem, mas sai sem link.
- A mensagem tem que nomear a peça identificada naquela letra, nunca um nome genérico. Ex.: `wa.me/5582988748649?text=Quero+comprar+o+<peça>`.
- O texto da figurinha pode variar: "Comprar", "Comprar agora", "Comprar pelo Whatsapp".
- Confirmar o texto da figurinha no ✓ do teclado antes de "Concluir".

Evidência da armadilha do `https://` (22/09, API `/api/v1/feed/reels_media/` do próprio perfil, campo `story_link_stickers`):

| Story | URL digitada | Resultado |
|---|---|---|
| 18:38 (letra A, verde) | `wa.me/5582988748649?text=…` | link OK |
| 21:32 (verde) | `https://wa.me/5582988748649?text=…` | **sem link**, só o desenho do botão |
| 21:36 (verde) | `wa.me/5582988748649?text=…` | link OK, aponta para wa.me/5582988748649 com a mensagem |

## Conferência obrigatória depois de postar
Não dá para confiar no visual do editor. Conferir pelo navegador logado no Instagram:

```js
const uid='54614123599', appId='936619743392459';
const j=await fetch('/api/v1/feed/reels_media/?reel_ids='+uid,{headers:{'X-IG-App-ID':appId}}).then(r=>r.json());
(j.reels_media[0].items||[]).slice(-6).map(it=>new Date(it.taken_at*1000).toLocaleTimeString('pt-BR')
  + ((it.story_link_stickers||[]).length?' LINK':' sem link'));
```

Isso também mostra quantos itens subiram de verdade. Foi assim que se descobriu que a letra B subiu com 5 de 6 mídias, e a que ficou de fora era justamente a que levava a figurinha.

## Compilação de modelos (pedido de 25/09/2026)
- Dividir por letras, um modelo por letra, para postar depois na ordem.
- Ordem das letras: **conjuntos → vestidos casuais → macacões → vestidos de festa**.
- Categorias do sistema em cada grupo:
  - Conjuntos: `Conjuntos`.
  - Vestidos casuais: `Vestidos` e `Vestidos Casuais`.
  - Macacões: `Macacões` e `Macacão`.
  - Vestidos de festa: `Vestidos de Festa` e `VESTIDO DE FESTA`.
- Só entram modelos e cores com estoque (regra fixa 1).
- Primeira compilação: `Documents\Stories da Loja\2026-09-22`.

## Ponto a confirmar com o usuário antes de automatizar
- Um registro de 22/09 anotou a letra C (só 2 vídeos, C-1 e C-2, sem fotos; "vestido com duas argolas laterais") como "vestido comum, recebe link — não é de festa". Não está claro se vestido de festa leva figurinha de link. **Perguntar ao usuário** antes de o script decidir isso.
