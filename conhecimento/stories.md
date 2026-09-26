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

### Como o script lê o estoque (decidido em 25/09/2026)
- `products` e `product_variations` têm RLS: só o papel `authenticated` lê (a chave pública sozinha recebe lista vazia, sem erro). As mesmas políticas deixam qualquer usuário logado também inserir, alterar e (nas variações) apagar.
- O script entra com um **usuário próprio das rotinas** (Supabase Auth, e-mail e senha) e usa o token dele; nunca a chave de serviço. Código em `rotinas/banco.py`: login pelo `/auth/v1/token?grant_type=password`, token em memória até perto de expirar, só **GET** e só nessas duas tabelas, colunas explícitas (nunca `cost_price`).
- `.env`: `SUPABASE_URL`, `SUPABASE_KEY` (chave pública: "Publishable key" `sb_publishable_…` ou a legada "anon"), `SUPABASE_EMAIL`, `SUPABASE_SENHA`.
- O teste do `verificar`/diagnóstico só dá verde com login aceito **e** pelo menos 1 produto lido (lista vazia = RLS barrou).

## Regra fixa 2 — não repetir
Antes de postar, sempre verificar se o modelo já não foi postado antes (letras já existentes nas pastas de data e stories recentes).

## Formato das mídias
- `.mov` não aparece na galeria do Instagram no emulador. Converter para `.mp4` antes.
- Importação atual: Gerenciador de Mídia do BlueStacks → Importar do Windows. É confiável só até ~5 arquivos por vez: em dois lotes de 6, um arquivo ficou de fora sem aviso. Sempre conferir a lista depois.

## No Instagram
1. + → Story → galeria → "Selecionar" → tocar nas mídias na ordem → Avançar.
2. Vídeo sem áudio recebe trilha pela música do Instagram: **buscar "fashion" e escolher ao acaso qualquer uma das faixas** que aparecem (regra do usuário de 25/09/2026, `musica_sem_som` em `config/stories.json`). Substituiu a lista fixa antiga ("I know what you want" – Madison Beer/Calley, Áudio original de petermarkoski/neetunomusic/enfermeira_vitoria0, Clocks – leveviolao), que a busca da conta no BlueStacks não encontrava (só traz faixas "sem royalties").
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

## Vestido de festa não leva figurinha de link (confirmado em 25/09/2026)
- Letra de **vestido de festa** (categorias `Vestidos de Festa` e `VESTIDO DE FESTA`) é postada **sem** figurinha de link. As demais peças levam o link na última mídia da letra.
- Origem: um registro de 22/09 anotou a letra C ("vestido com duas argolas laterais") como "vestido comum, recebe link — não é de festa"; o usuário confirmou a regra em 25/09.
- No código: `config/stories.json` → `link_em_vestido_de_festa: false` e `categorias_vestido_de_festa`. A categoria vem do cadastro (`products.category`), não da aparência da peça: se o cadastro disser `Vestidos` ou `Vestidos Casuais`, leva link.

## Como a automação aplica estas regras (Fase 1, 25/09/2026)
Scripts em `rotinas/stories/`; formato dos pedidos em `fila/README.md`. O que a próxima sessão precisa saber:
- **Preparar a pasta (`stories.preparar`):** mídia nova = arquivo que não segue `<LETRA> - <n>`. Cada subpasta vira uma letra; arquivos soltos são agrupados por data de captura (nova letra quando passa de `agrupamento_intervalo_min` ou quando aparece um vídeo depois de uma foto). A IA pode passar `grupos` explícitos se a heurística errar. `.mov/.m4v/.3gp` → `.mp4` (só troca o contêiner quando já é H.264; senão H.264 CRF 17) e `.heic` → `.jpg` 95, sempre em arquivo novo. O original vai para `<pasta do dia>\_originais\` depois do arquivo final pronto (registro em `_originais\renomeados.json`; rodar de novo não duplica nada). `simular` gera folhas sem mexer na pasta. Letra em minúscula (`b - 1.jpg`) não é renomeada: gera aviso.
- **Live Photos / mídia sem data de captura** (WhatsApp, cópia por cabo) podem bagunçar o agrupamento automático: conferir as folhas e usar `grupos`.
- **Estoque (`stories.estoque`/`stories.montar`):** a IA usa o nome da cor como está no cadastro; nome de cor desconhecido ou ambíguo **não corta nada**, dá erro com a lista de cores válidas. Mídia que mostra qualquer cor com estoque 0 é cortada; modelo com total 0 corta a letra. Se a última mídia foi cortada, a figurinha vai para a nova última. Nome parecido que casa com uma cor só (ex.: "verde" → "Verde Bandeira") é aceito com aviso "cor aproximada" no relatório. Busca: `sku` exato (maiúsculas); `termo` procura no nome (não na categoria) as palavras na ordem, com qualquer coisa entre elas — o teste da skill (25/09/2026) mostrou que "vestido festa" não achava "Vestido Longo Festa"; corrigido (espaço vira curinga). Letra que já existia na pasta e não foi identificada sai como aviso "sem identificação", sem erro.
- **Já postado:** bloqueia pelo SKU (em qualquer data anterior ou outra letra), pelo hash do arquivo final e do original, e pela varredura das outras pastas de data (mesma mídia em outro dia). O mesmo SKU em duas letras do mesmo pedido corta a segunda. `permitir_repeticao` só quando o usuário mandar repetir. `postados.csv` só recebe linha depois de publicar de verdade.
- **Pedido de postagem:** o padrão é **ensaio**; postagem real exige pedir explicitamente. Dois pedidos reais das mesmas letras na fila são recusados. Música do vídeo sem áudio: busca "fashion" e sorteio de uma das faixas na tela, pelo script (a IA não escolhe; `musica` na identificação é recusada); texto da figurinha em rodízio pelas letras que levam link.
- **`postados.csv`** abre no Excel (`;`, UTF-8 com BOM). Com ele aberto no Excel o Windows trava o arquivo: fechar antes de postar.

## Postagem pelo BlueStacks automatizada (A5, código de 25/09/2026 — seletores ainda a confirmar no PC)
- **Galeria sem o Gerenciador de Mídia:** as mídias da letra vão por ADB para `/sdcard/Pictures/RotinasFerreira/<data>_<letra>/` (o nome da pasta vira o álbum), em ordem inversa, com data de modificação decrescente e varredura do MediaStore arquivo a arquivo; depois o script confere no MediaStore que **todas** apareceram e na ordem certa, antes de abrir o Instagram.
- **Seletores só em `config/bluestacks.json` → `seletores`:** cada passo tem alternativas por texto/descrição/resource-id; coordenada relativa só como plano B, registrada no log, e **nunca** tocada com botão de publicar na tela.
- **Travas de segurança:** ensaio é o padrão e nunca toca em "Seu story"/"Compartilhar"; a seleção precisa mostrar exatamente 1…N; o editor precisa ter exatamente N miniaturas; só publica com o editor na tela; interruptor do Facebook desligado antes de concluir; primeira falha para tudo (letra inteira ou nada) e o erro traz o que já subiu; letra já registrada em `postados.csv` no dia é pulada (repetir exige `repostar`); falha depois de tocar em "Seu story" marca a letra como **incerta** — rodar o JS antes de repetir.
- **Diagnóstico:** `--diagnostico` grava XML + print de cada passo (`passo_NNN_<letra>_<passo>`); ensaio grava `ensaio_<letra>_<n>.png` de cada mídia montada.
- **Confirmado no diagnóstico de 25/09/2026** (BlueStacks 5.22, Android 9, Instagram 448.0.0.52.84, tela 900×1600 em pé, ADB `HD-Adb.exe` em 127.0.0.1:5555 — o mesmo aparelho também aparece como `emulator-5554`): a barra de baixo tem Página inicial (`feed_tab`), Reels, Mensagem, Pesquisar e Perfil — **não há aba "Criar"**. O story abre pelo botão "Adicionar ao story" (`reel_empty_badge`) no "Seu story" do topo do feed, que já leva à câmera de story; o fluxo só toca na aba "Story" se a galeria não aparecer. No feed, o texto "Seu story" é o rótulo do próprio avatar (por isso só se publica com o editor na tela).
- **`testar.bat bluestacks` de 25/09/2026 (ok):** "Adicionar ao story" abre **direto a galeria** (título "Adicionar ao story", atalhos Modelos/Música/Colagem, "Recentes ▾", "Selecionar"). "Selecionar" = `gallery_menu_multi_select_button`; ligado, o mesmo botão vira "Cancelar" (tocar de novo **desliga** a seleção — o fluxo confere antes). "Recentes ▾" (`gallery_folder_menu_tv`) abre Recentes/Fotos/Vídeos/**Todos os álbuns**/Dos apps da Meta: a pasta da letra fica em "Todos os álbuns". Miniaturas = `gallery_grid_item_thumbnail`, com descrição "Não selecionado Miniatura de foto/vídeo com criação em…"; o círculo `gallery_grid_item_selection_circle` existe em todas (marcadas ou não), então a contagem usa número visível, contador ou a descrição. O emulador tem "Mostrar local do ponteiro" ligado (faixa no topo dos prints; não atrapalha).
- **Ensaio sintético de 25/09/2026 (parou na seleção, como devia):** o envio à galeria funcionou (varredura por `broadcast`, 3 de 3 na ordem, álbum `2000-01-01_T` achado em "Todos os álbuns"). O 1º toque no **vídeo recém-enviado não pegou** (miniatura ainda carregando, quadro cinza) e as fotos viraram 1 e 2 — a conferência pegou 2 de 3 e não seguiu. Miniatura marcada tem descrição "**Número da mídia selecionada N** Miniatura de…": agora cada toque é conferido na hora pela descrição (espera até 4 s e toca de novo só se ainda estiver "Não selecionado"; um toque a mais desmarcaria), e a contagem final exige 1…N em ordem.
- **Ensaio sintético de 25/09/2026 18:51 (parou em `abrir_story`):** o toque em "Adicionar ao story" caiu com o feed **ainda carregando** (print do passo `criar` com o feed em esqueleto e a bandeja de stories sendo trocada) e foi ignorado: a tela seguiu no feed, o fluxo esperou só 2 s pela galeria e foi procurar a aba "Story", que não existe no 448. Agora, depois de tocar "criar", o fluxo espera até `espera_abrir_story_s` (8 s) pela aba "Story" (conferida primeiro, para versões com "Criar" não caírem no modo publicação), pela galeria ou pela câmera; se continuar no feed, toca de novo (até `tentativas_criar` = 3) e, se nunca abrir, para com "toquei N vez(es) em 'Adicionar ao story'…". No 448 nenhum print/XML capturado tem aba "Story".
- **Ensaio sintético de 25/09/2026 18:59 (parou em `tocar_midias`):** a entrada no story funcionou (galeria direto, álbum `2000-01-01_T`, "Selecionar" ligado; ao ligar, a faixa Modelos/Música/Colagem some e a grade sobe ~208 px — o fluxo relê a grade a cada toque, então não afeta). O **vídeo de teste ficou cinza** (sem miniatura, só "0:05") nos dois ensaios (18:45 e 18:59) e 3 toques não o selecionaram; as fotos selecionam no 1º toque, e os vídeos reais da loja na galeria têm miniatura. O vídeo de teste era H.264 **High com B-frames e sem áudio**; vídeo de celular costuma ser sem B-frames e sempre com áudio. Agora o vídeo sintético vem de `sintetico_video_ffmpeg` (config): H.264 Main sem B-frames, áudio AAC em silêncio, faststart. **Hipótese a confirmar no próximo ensaio**; se continuar cinza, o problema não é o formato. Também: com diagnóstico, cada toque que não seleciona gera `selecao_<letra>_<n>_toque<k>.png/.xml` logo depois do toque (pega aviso passageiro do Instagram), e vídeo que não seleciona para com "(vídeo) … o Instagram do BlueStacks não leu o vídeo".
- **Ensaio sintético de 25/09/2026 19:08 (parou em `musica_1`):** **confirmado — era o formato**: com o vídeo H.264 Main sem B-frames + AAC, as 3 mídias selecionaram (número na descrição) e o "Avançar" abriu o editor. Editor do 448 (XML): `music_button` (descrição "Músicas"), `asset_button` ("Figurinhas"), `add_text_button` ("Texto"), "Silenciar", `cancel_button` ("Cancelar", seta de voltar), faixa de miniaturas `thumbnail_image` com descrição "Vídeo selecionado"/"Foto selecionada", botão `media_thumbnail_tray_button` "Avançar" (não há "Seu story" no editor: publicar vem depois do "Avançar"). Busca de música: campo `row_search_edit_text`, botão "Filtro", linhas `audio_browser_track_*` com descrição "Selecionar faixa <título> de <autor>,sem royalties,<duração>", título `song_title`, autor `artist_name` ("LAVLO • 0:56"), selo "SR" = sem royalties. Com "I know what you want Madison Beer" digitado, a lista **só mostrou faixas "sem royalties" sem relação com a busca** (I Like That/LAVLO, The Distance/GEEZ…) por 15 s. Agora, depois de digitar, o fluxo aperta a tecla de busca do teclado (`enviar_busca_musica` = Enter) e, se a música da vez não aparece, tenta as outras de `audios_sem_som` na ordem da lista (regra do usuário: vídeo mudo leva uma música **dessa lista**), com aviso no relatório; se nenhuma aparece, para mostrando as faixas que a busca trouxe (e, com diagnóstico, `busca_musica_<letra>_<n>.png/.xml` de cada tentativa). **Resolvido pelo usuário (ver o item de 19:25).**
- **Ensaio sintético de 25/09/2026 19:25 (parou em `musica_1`):** com a tecla de busca, a lista **muda** conforme a busca ("petermarkoski" trouxe outras faixas), mas **só faixas "sem royalties"** e nenhuma da lista antiga: a conta no BlueStacks só acha a biblioteca sem royalties. **Regra nova do usuário:** buscar "fashion" e escolher ao acaso qualquer uma das faixas. O fluxo agora: abre a música, **limpa o campo** ("Limpar texto") — na 3ª busca, digitar sobre a palavra sublinhada que estava no campo abriu o **balão de correção do teclado** ("Netuno music…/ADICIONAR AO DICIONÁRIO/EXCLUIR"), que cobre a busca e esconde o campo do XML (a 4ª busca parou com "Não achei o campo 'buscar_musica'") —, digita "fashion", fecha o balão se ele aparecer (Voltar fecha só o balão), aperta a tecla de busca, espera a lista mudar e sorteia entre as `musica_aleatoria_entre` (6) primeiras faixas (as que cabem acima do teclado); o nome sorteado ("<título> de <autor>", da descrição "Selecionar faixa …") vai para o resultado. No mesmo ensaio, o **álbum `2000-01-01_T` não apareceu** em "Todos os álbuns" (10 s de espera; na execução das 19:08 aparecia): o menu é um balão (`context_menu_item`, x 24–434) e a pasta devia estar abaixo da parte visível. Agora espera `espera_lista_albuns_s` (4 s) e rola a lista **arrastando dentro dos itens do menu** (arrastar fora fecharia o balão), até `max_rolagens_album` (4) vezes; se não achar, com diagnóstico salva `album_<letra>_nao_achado.png/.xml` antes de fechar o menu (ensaio segue por "Recentes"; real para).
- **Ensaios de 25/09/2026 19:42 e 19:44:** às 19:44 o álbum apareceu (sem rolar), a busca "fashion" trouxe faixas e o sorteio escolheu "Free Fall de Giulio Cercato"; parou porque, no 448, **tocar na faixa só toca a prévia** e abre uma barra embaixo com a faixa e uma seta: o botão da seta é `audio_bar_select_tap_target` (descrição "Selecionar faixa <título> de <autor>" — igual à das linhas da lista, por isso `faixas_musica` agora é só `resourceIdMatches` `audio_browser_track_*`). Fluxo: faixa → `usar_musica` (seta) → se aparecer "Concluído" (`concluir_musica`) toca → espera o editor. **Às 19:42 uma notificação flutuante do Android** (mensagem de cliente no Direct: foto, nome, texto, CURTIR/RESPONDER; nós `android:id/message_name`/`message_text`/`action0` do pacote `com.android.systemui`, faixa y≈64–352) apareceu no topo; o toque no "X" da busca (y≈97) caiu nela e o ensaio foi parar na **conversa do Direct** — print e XML da conversa foram para o GitHub (tirados; ver `pc-instalacao-e-fila.md`). Proteções: (1) antes de tocar num ponto embaixo da notificação (`notificacao_flutuante`), a `Tela` espera ela sumir (até `espera_notificacao_s` = 15 s) e, se não sumir, não toca; (2) todo print espera a notificação sumir e, se não sumir, sai com a faixa coberta; (3) o campo da busca é apagado sem tocar no "X" (texto vazio pelo uiautomator); (4) tela do Direct (`tela_privada`: `direct_thread_header`, `row_thread_composer_edittext`, `thread_fragment_container`) → para a postagem no começo de cada passo, antes de digitar e antes do Enter, e nunca é salva; (5) `buscar_musica` perdeu os seletores genéricos (EditText qualquer, "contém Pesquisar"), que podiam achar a caixa de mensagem. `campo_url`, `campo_texto_figurinha` e `buscar_figurinha` ainda têm EditText genérico (a tela da figurinha ainda não foi vista): a guarda do Direct vale para eles.
- **Ensaio de 26/09/2026 00:17 (parou em `musica_1`, "não trouxe nenhuma faixa" com a lista na tela):** as telas novas do 448 feitas em **Compose** têm `resource-id` **sem o prefixo** `com.instagram.android:id/` (`audio_browser_track_0_…`, `music_button`, `asset_button`, `audio_bar_select_tap_target`, `audio_bar`), e o seletor das faixas exigia o prefixo. As telas antigas (galeria, feed, Direct: `gallery_*`, `feed_tab`, `direct_thread_header`) têm prefixo. Correção: `faixas_musica` aceita os dois (`^(com\.instagram\.android:id/)?audio_browser_track_.*`); `usar_musica`, `musica`, `editor` e `figurinhas` usam o id sem prefixo primeiro; `tela_privada` e os marcadores de privacidade aceitam os dois. **Regra:** todo seletor novo é conferido em `tests/test_seletores_448.py` contra o XML real da tela (cópias limpas em `tests/dados/telas_448/`), antes de pedir teste no PC.
- **Ensaio de 26/09/2026 00:26 (parou em `musica_1`, "o editor não voltou"):** a busca "fashion" trouxe as faixas, o sorteio pegou "Peach Skies (feat. Avenham)" e a seta da barra abriu a **tela de ajuste da música** (`music_editor`): "Cancelar" (`music_editor_cancel_button`), capa ("Voltar para a Pesquisa de música"), cor, **✓ = `music_editor_done_button`, descrição "Concluir"**; estilos "Somente música" (padrão, selecionado), "Arte de álbum pequena/grande", "Vinil"; "Clipe de 5 segundos"; trecho da música (`music_scrubber`). O `concluir_musica` não tinha nem o id nem a descrição "Concluir": agora tem os dois primeiro (conferido em `tests/test_seletores_448.py`, tela `editor_da_musica.xml`). O estilo fica o padrão ("Somente música").
- **Afinar o editor sem a rodada completa:** `testar.bat stories-ensaio --sintetico` monta uma letra de teste (1 vídeo sem som + 2 fotos geradas em `Rotinas Ferreira\stories\_teste\`, álbum `2000-01-01_T`) com música e figurinha, em ensaio + diagnóstico; nunca publica.
- Ordem do ciclo real: `testar.bat bluestacks` (vai até a galeria, sem publicar) → ajustar seletores → `testar.bat stories-ensaio --data <data>` → aprovação do usuário → postagem real.
- **Seletor que falhou numa letra:** `testar.bat bluestacks` só percorre feed → Criar → Story → galeria → Selecionar → menu de álbuns. Falha em abrir_instagram, criar, abrir_story, abrir_galeria ou selecionar_varios → `testar.bat bluestacks`; falha depois disso (música, figurinha, seu_story, facebook…) → `testar.bat stories-ensaio --data <data>` (XML + print de cada passo, sem publicar). O ajuste de `config/bluestacks.json` é feito no repositório, nunca à mão em `sistema\` no PC (arquivo versionado mudado à mão trava o `git pull` do `atualizar.bat`).

## Proteções acrescentadas na auditoria de 25/09/2026
- **Letra incerta** (falhou depois de tocar em "Seu story") entra no JS de conferência; rodar o JS antes de repetir.
- **`postados.csv` travado:** a postagem real testa a gravação antes de começar (nada é publicado se o Excel estiver com o arquivo aberto). Se o registro falhar **depois** de publicar, a letra fica em `registros\postados_pendentes\`, conta como já postada no próximo montar/postar e entra no CSV no próximo registro que der certo; a execução para antes da próxima letra.
- **Álbum que não abre:** na postagem real, nunca publicar pela grade "Recentes" (tem mídias de outras letras); só o ensaio segue por lá, com aviso.
- **Um uso do BlueStacks por vez** (`fila\bluestacks.lock`): vigia, `stories-postar` e `testar.bat` não disputam o emulador.
- **Pedido interrompido** (vigia caiu no meio da postagem): o relatório diz que não sabe o que subiu e dá o JS de todas as letras.
- **O montar nunca prepara a pasta sozinho:** sem `manifesto.json` (só simulação) ele para sem mexer em nada.
- `"diagnostico": true` no montar vale para o postar gerado; o relatório do postar mostra "Avisos da postagem".
- Ajuste de seletores e de regras vai para `config/*.json` **no repositório** (o vigia relê a config a cada pedido); não editar arquivos de `sistema\` à mão no PC.
