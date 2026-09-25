---
name: postar-stories-ferreira
description: Postar stories da Ferreira Boutique pelo BlueStacks a partir da pasta do dia (Stories da Loja\<data>) — prepara as mídias, confere estoque e repetição, põe o link do WhatsApp e publica pela fila de pedidos do PC. Usar sempre que o usuário pedir para postar, montar ou conferir stories da loja.
---

# Postar stories — Ferreira Boutique

Você (IA no Cowork) só lê e grava arquivos nas pastas do PC. Quem executa é o **vigia** no Windows: você grava um pedido
JSON na fila e lê o resultado. Detalhes da fila: `C:\Users\V15\Documents\Rotinas Ferreira\sistema\fila\README.md`.
Regras completas: `...\sistema\conhecimento\stories.md` (obrigatórias).

## Quando usar
"Posta os stories de hoje", "monta a pasta 2026-09-22", "sobe a compilação de modelos", "confere se subiu".

## Pré-requisitos (conferir antes; se faltar, pedir ao usuário UMA coisa por vez, com o passo exato)
- Vigia vivo: `Rotinas Ferreira\fila\vigia.vivo` muda entre duas leituras (~10 s ocioso, ~60 s executando). Parado →
  pedir: dois cliques em `C:\Users\V15\Documents\Rotinas Ferreira\sistema\atualizar.bat`.
- Mídias do dia em `C:\Users\V15\Documents\Stories da Loja\<AAAA-MM-DD>\`.
- Para publicar: BlueStacks aberto, Instagram logado, ADB ligado (BlueStacks → Configurações → Avançado → Android
  Debug Bridge) e `Rotinas Ferreira\registros\postados.csv` **fechado** no Excel.

## Como pedir e esperar
1. Gravar `Rotinas Ferreira\fila\pendente\<id>.json.tmp` e renomear para `<id>.json` (ou gravar `<id>.json` de uma vez).
   Campos: `id` (= nome do arquivo; modelo `aaaammdd-hhmmss-<tipo-com-hífen>-<detalhe>`, nunca reutilizar), `tipo`,
   `args`, `ensaio`, `diagnostico`, `criado_em` (ISO com fuso), `origem: "cowork"`.
2. A cada ~10 s, ler `fila\feito\<id>.json` ou `fila\erro\<id>.json` (só aparece quando terminou). Conferir `pedido.criado_em`.
3. Prints, XML e log ficam na pasta indicada em `pasta` do resultado.

## Passo a passo (o que é script e o que você decide)
**1. Preparar a pasta** — `tipo: "stories.preparar"`, `args: {"data": "2026-09-22", "simular": true}`.
   - Script: agrupa as mídias novas em letras (subpasta = letra; soltas por data de captura), gera folhas de contato.
   - **Você decide:** olhando SÓ as folhas `Rotinas Ferreira\stories\<data>\folhas\<L>.jpg`, se cada letra é um modelo
     só. Errado → refazer com `"grupos": [["IMG_1.MOV","IMG_2.JPG"], ["IMG_3.JPG"]]` (nomes originais).
   - Certo → mesmo pedido sem `simular` (com `grupos` se usou). O script renomeia (`A - 1` vídeo, `A - 2`… fotos, na
     próxima letra livre), converte `.mov`→`.mp4`, guarda originais em `_originais` e marca vídeo sem áudio.
**2. Identificar peça e cor** — **você decide**, pelas folhas: qual peça é cada letra e qual cor aparece em cada mídia.
   - Confirmar no cadastro: `tipo: "stories.estoque"`, `args: {"consultas": [{"sku": "FB-0123"}, {"termo": "vestido midi"}]}`.
     Use o SKU e os **nomes de cor exatamente como vêm no resultado**.
**3. Montar em ensaio** — `tipo: "stories.montar"`, `"ensaio": true`, `args`:
   ```json
   {"data": "2026-09-22", "postar": true, "ensaio": true,
    "identificacao": {
      "A": {"sku": "FB-0123", "midias": {"A - 1": ["Verde"], "A - 2": ["Verde"], "A - 3": ["Preto"]}},
      "B": {"sku": "FB-0456", "midias": {"B - 1": ["Azul"], "B - 2": ["Azul", "Branco"]}, "excluir": {"B - 3": "outra peça"}}
    }}
   ```
   - Toda mídia da letra entra em `midias` (≥ 1 cor) ou em `excluir` (com motivo). Compilação de modelos: `"ordem": "categorias"`.
   - Script: corta cor sem estoque e modelo zerado, bloqueia já postado, monta o link, escolhe a música dos vídeos sem som
     e grava o pedido `stories.postar`. O resultado traz `relatorio` e `pedido_postagem` (id): espere por esse também.
   - O `stories.postar` de ensaio monta cada letra no Instagram e **para antes de publicar**; prints `ensaio_<L>_<n>.png`.
**4. Aprovação** — mostrar ao usuário o relatório do ensaio (e os prints, se ele quiser ver). Só publicar com o "pode postar" dele.
**5. Publicar** — repetir o passo 3 com `"ensaio": false` **no pedido e nos args**. Esperar o `stories.postar` real.
**6. Conferir no Instagram (obrigatório)** — o resultado do `stories.postar` traz `resultado.relatorio` (aviso pronto)
   e `resultado.js_conferencia` (em erro, dentro de `resultado_parcial`). Rodar o JS no console do navegador logado no
   Instagram: ele lista os itens, mostra onde está o `LINK` e termina em **CONFERE** ou **NÃO CONFERE**. Não confiar no
   visual do editor. NÃO CONFERE → dizer ao usuário o que falta, sem repostar por conta própria.

## Regras fixas do usuário (valem sempre)
- É **story**, não feed. Só pelo BlueStacks. Nunca compartilhar no Facebook.
- **Estoque primeiro:** cor com estoque 0 não vai; modelo sem nenhuma peça não entra; avisar depois o que ficou de fora.
- **Não repetir:** modelo já postado não entra de novo (o script diz quando e onde saiu). Só repetir se o usuário mandar
  (`"permitir_repeticao": ["B"]`).
- Uma letra por modelo; `A - 1` é o vídeo, depois as fotos. Nunca sobrescrever nem apagar mídia do usuário.
- Vídeo sem áudio recebe música do Instagram da lista de `config\stories.json` (`audios_sem_som`).
- Figurinha de link **só na última mídia de cada letra**: `wa.me/5582988748649?text=<mensagem com o nome da peça>`,
  **sem `https://`** (com https a figurinha sai sem link). Texto: "Comprar", "Comprar agora" ou "Comprar pelo Whatsapp".
- **Vestido de festa não leva link** (categorias `Vestidos de Festa` / `VESTIDO DE FESTA` do cadastro).
- Compilação de modelos: ordem conjuntos → vestidos casuais → macacões → vestidos de festa.
- Postagem real só depois de ensaio aprovado.

## Aviso final ao usuário (curto)
```
Subiu: A (Vestido Midi Alça) 3 mídias, link na A - 3 · F (Vestido Longo Festa) 2 mídias, sem link (festa).
Ficou de fora: A - 4 (Preto sem estoque — avise se repor) · C inteira (já postada em 18/09, letra B).
Conferência no Instagram: CONFERE (5 itens, LINK na A - 3).
Você precisa: nada.   (ou: repor Preto / aprovar o ensaio / fechar o postados.csv…)
```

## Erros conhecidos e solução
| Erro | Solução |
|---|---|
| `ErroEstoque` "cor … não encontrada" / ambígua | Usar o nome da cor como vem em `stories.estoque`. Nada foi cortado. |
| "termo ambíguo: N produtos" | Passar o `sku`. |
| `ErroRegra` sobre vestido de festa | `link_em_vestido_de_festa` voltou a `null` na config: não decidir; perguntar ao usuário. |
| Pedido em `pendente` há mais de 1 min | Vigia parado → `atualizar.bat`. |
| "ADB do BlueStacks desligado" / sem dispositivo | Pedir para ligar o ADB (caminho acima) com o BlueStacks aberto. |
| "a galeria não mostrou …" | Envio pelo ADB falhou para algum arquivo; pedir de novo com outro id. |
| Letra `falhou` em um passo (`parou_em`) | Nada daquela letra foi publicado; as anteriores sim (ver `resultado_parcial`). Se for seletor da tela, pedir ao usuário `testar.bat bluestacks` e ajustar `config\bluestacks.json`. |
| Letra `incerta` | Pode ter subido: rodar o JS **antes** de repetir; repetir só o que não subiu. |
| `postados.csv` em uso / PermissionError | Pedir para fechar o Excel e pedir de novo com outro id. |
| "Já existe um pedido stories.postar real…" | Esperar o pedido anterior terminar; não criar outro. |
| "Interrompido" em `erro` | O vigia caiu no meio: conferir no Instagram (JS) o que já subiu antes de pedir de novo. |
