# Rotinas Ferreira — orientações para Codex

Este projeto automatiza rotinas da Ferreira Boutique. Siga o pedido do usuário e as regras atuais deste repositório. A postagem de Stories foi aprovada pelo usuário; a qualidade da edição de vídeo anterior foi rejeitada. Não trate uma exportação tecnicamente correta como aprovação visual.

## Leia conforme a tarefa

- `CLAUDE.md`: convenções gerais, limites de dados e mapa do projeto.
- `BRIEFING.md`: fase atual, arquitetura, critérios de aceite e ciclo de teste.
- Stories: `.agents/skills/postar-stories-ferreira/SKILL.md`, `conhecimento/stories.md`, `fila/README.md` e o código/configuração atuais em `rotinas/stories/` e `config/`.
- Vídeo: `.agents/skills/editar-video-ferreira/SKILL.md`, `conhecimento/edicao-video-capcut.md`, `conhecimento/capcut-rascunho-e-exportacao.md` e o material visual mais recente fornecido pelo usuário.

Os arquivos em `.claude/skills/` são referências de processo; instruções para ferramentas exclusivas do Claude devem ser adaptadas aos recursos realmente disponíveis. Consulte a versão atual dos arquivos do projeto antes de usar o snapshot em `C:\Users\V15\.codex\claude-reference\2026-09-27`.

## Regras operacionais

- Stories usam BlueStacks. Antes de montar/postar, confira o que já está no ar e o estoque atual. Preserve a ordem de cada letra; ponha o link de compra somente na última mídia da peça e nenhum link em vestido de festa. Consulte `conhecimento/stories.md` para exceções e para a conferência da publicação real.
- Banco da loja: somente leitura nas tabelas e colunas previstas pelo projeto; nunca leia `products.cost_price`. Credenciais permanecem no `.env` local e não entram em código, log, resposta ou commit.
- Preserve as mídias originais. As rotinas que publicam devem passar pelo ensaio aplicável, registrar o resultado e confirmar no Instagram o que foi de fato publicado antes de reportar sucesso.
- Erro resolvido ou regra nova confirmada do usuário deve ser incorporado ao arquivo de `conhecimento/` e à skill da rotina correspondente, conforme `CLAUDE.md`.
