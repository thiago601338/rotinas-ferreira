---
name: postar-stories-ferreira
description: Preparar, montar, publicar e conferir Stories da Ferreira Boutique pelo BlueStacks e pela fila local. Use quando a tarefa no projeto pedir operação ou correção da rotina de Stories.
---

# Stories da Ferreira Boutique

Fonte de verdade: [`conhecimento/stories.md`](../../../conhecimento/stories.md), [`fila/README.md`](../../../fila/README.md), `config/stories.json`, `config/bluestacks.json` e código em `rotinas/stories/`. Leia a seção pertinente antes de operar e confira mudanças no projeto atual. A skill Claude em `.claude/skills/postar-stories-ferreira/SKILL.md` guarda incidentes e exemplos mais longos; consulte-a só se necessário. Não ler ou divulgar valores de `.env`.

## Operação

1. Confira primeiro **todos** os Stories ainda no ar, inclusive os publicados à mão; `postados.csv` não os cobre. Antes de montar, confira também estoque vivo e a pasta `C:\Users\V15\Documents\Stories da Loja\<data>\`. Não repita uma peça sem pedido expresso; se o usuário excluiu um Story, não o republique por conta própria.
2. Prepare a pasta em simulação (`stories.preparar`, `simular: true`), revise as folhas de contato e ajuste grupos se necessário. Execute o preparo real para gerar `manifesto.json` antes de montar. Uma letra representa uma peça: vídeo `A - 1`, fotos seguintes na ordem recebida. Preserve os originais.
3. Identifique SKU e cores de **cada mídia** pela folha e pelo resultado de `stories.estoque`; use os nomes exatos do cadastro. Cor zerada não entra. Se uma foto mostrar várias cores e uma estiver zerada, siga o fluxo `stories.recriar` da documentação e confira a comparação visual antes de aprová-la.
4. Monte **ensaio** por `stories.montar` com todas as letras novas. O próprio montar enfileira `stories.postar`; não escreva um pedido `stories.postar` à mão. Confira o relatório, a ordem, as exclusões, a música em vídeo sem som e os prints. Figurinha de compra apenas na última mídia elegível de cada letra; vestido de festa não leva link. O link da figurinha é digitado sem `https://`, conforme a configuração atual. Publique só depois do ensaio aprovado, respeitando uma instrução posterior explícita do usuário que altere esse fluxo.
5. Para postar de verdade, repita `stories.montar` com `ensaio: false` no pedido e nos args. Aguarde o pedido derivado e confira no Instagram os itens e os links reais com o procedimento atual de `conhecimento/stories.md`. Resultado da fila sozinho não prova publicação.

A memória do projeto Claude registra **uma letra por cor para vestidos de festa**, enquanto `conhecimento/stories.md` descreve uma letra por modelo como regra geral. Ao preparar vestidos de festa, confira a pasta, o código e a instrução mais recente do usuário antes de definir os grupos.

Pedidos usam IDs únicos e a estrutura de `fila/README.md`; no Codex, use `origem: "terminal"` se informar a origem. O vigia escreve resultados em `fila/feito` ou `fila/erro`. Em interrupção ou erro após toque de publicação, examine `resultado_parcial`, prints e Stories no ar antes de qualquer nova tentativa. A rotina é pelo BlueStacks, sem compartilhar no Facebook. Se desenvolver a rotina, altere o repositório, não a cópia instalada, e registre novas regras ou erros resolvidos em `conhecimento/` e nesta skill.

Após publicação real, o publicador associa SKU/cor aos Stories pela Edge `atendimento-registrar-stories`. Confira `atendimento_stories` por letra; `pendente` não autoriza republicar. O pedido exato fica em `atendimento_stories_<LETRA>.json`, sem segredos, e pode ser repetido apenas para a associação com `python -m rotinas.stories.atendimento --arquivo "<arquivo>"`. Cores ou modelos diferentes usam manifesto por mídia; vários modelos sem SKU individual ficam pendentes. Contagem/ordem ambígua exige conferência real. A configuração está em `config/atendimento.json`, com `ROTINAS_SEGREDO_ATENDIMENTO` somente no `.env`. Esta integração foi verificada localmente com simulações; o registro remoto deve ser validado após publicar a Edge.
