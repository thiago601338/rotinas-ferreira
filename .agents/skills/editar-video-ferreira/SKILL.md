---
name: editar-video-ferreira
description: Preparar, editar, revisar e conferir vídeos da Ferreira Boutique no CapCut por meio da rotina local. Use quando a tarefa no projeto envolver Reels, Stories ou TikTok da loja.
---

# Vídeo da Ferreira Boutique

Fonte de verdade: [`conhecimento/edicao-video-capcut.md`](../../../conhecimento/edicao-video-capcut.md), [`conhecimento/capcut-rascunho-e-exportacao.md`](../../../conhecimento/capcut-rascunho-e-exportacao.md), `receitas/`, `config/video.json`, `config/capcut.json` e [`fila/README.md`](../../../fila/README.md). A skill Claude em `.claude/skills/editar-video-ferreira/SKILL.md` contém detalhes da fila e incidentes; leia apenas o trecho pertinente. Preserve os arquivos originais e não leia ou divulgue `.env`.

## Julgamento criativo primeiro

O usuário avaliou a edição anterior como ruim, inclusive a fonte usada no primeiro teste, e rejeita cortes excessivos. As receitas e verificações do projeto ajudam a montar rascunhos, mas **não** são um padrão de qualidade aprovado. Não reaproveite essa tipografia por inércia. Examine a referência visual mais recente, o objetivo comercial, a peça e as tomadas reais antes de escolher estrutura. Revise o próprio rascunho e o arquivo exportado no formato de celular. Corrija ritmo, enquadramento, texto, transições, cor e áudio segundo a referência e o comentário do usuário. `video.conferir` verifica propriedades técnicas, não estética; `aprovado` ali não significa vídeo pronto para uso.

## Operação técnica quando servir ao pedido

1. Confira o bruto em `C:\Users\V15\Documents\Rotinas Ferreira\videos\bruto\<projeto>\` e o estado do vigia. `video.preparar` gera inventário, tomadas e folhas de contato; examine as folhas e os avisos.
2. Se uma receita ajudar, escolha as tomadas e textos à luz da referência, e use `video.planejar`. Leia `resultado.avisos` e o plano. Não aceite um arranjo tecnicamente válido se a montagem visual estiver ruim.
3. `video.rascunho` cria projeto novo com o CapCut fechado. Inspecione o rascunho no CapCut, faça o acabamento indicado e o acabamento adicional necessário para a qualidade pedida. O fluxo `video.exportar` escreve instruções e espera a exportação manual; enquanto espera, a fila fica ocupada.
4. Confira o MP4 em reprodução e, quando fizer sentido, execute `video.conferir` para duração, resolução, codec e áudio. Relate separadamente qualidade visual, conformidade técnica e etapas ainda dependentes do usuário.

Pedidos usam IDs únicos e o esquema de `fila/README.md`; no Codex, use `origem: "terminal"` se informar origem. Não sobrescreva projetos ou mídia existente. Se corrigir código ou descobrir uma regra nova, edite o repositório e registre a conclusão em `conhecimento/` e nesta skill.
