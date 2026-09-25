# Rotinas Ferreira

Este repositório transforma as rotinas repetidas da Ferreira Boutique em **scripts** (rodam sem IA) e **skills** (receitas curtas para a IA fazer só o que exige julgamento). Objetivo: cada repetição futura sair mais rápida e mais barata, com a mesma qualidade.

O que construir agora está em `BRIEFING.md`. O conhecimento acumulado está em `conhecimento/`.

## Como trabalhar com o usuário
- Executar o que foi pedido, direto. Não sugerir mudança de escopo nem dar conselho que ele não pediu — principalmente de SEO (ele é especialista).
- Português do Brasil. Relatórios curtos: o que ficou pronto, o que ele precisa fazer, o que falta.
- Quando precisar dele (rodar algo no PC, confirmar uma regra), pedir uma coisa por vez, com o comando exato, e seguir no que não depende disso.

## Ambiente onde as rotinas rodam
- PC Windows 11 do usuário (usuário do Windows `V15`, tela 1920×1080).
- Instagram da loja no emulador **BlueStacks** (não usar LDPlayer).
- Edição de vídeo no **CapCut desktop 9.5 PT-BR, conta Pro**.
- Banco do sistema da loja: Supabase `nailfzcujyxydqldktgg` (tabelas `products` e `product_variations`).
- Esta sessão na nuvem **não enxerga o PC**. Teste aqui tudo o que der (mídia sintética, mocks); o resto passa pelo ciclo de teste do `BRIEFING.md` §6.

## Regras fixas do código
- Credenciais só no `.env` do PC do usuário. Nunca no repositório, nunca em log, nunca no chat. Manter `.env.example` só com os nomes das variáveis.
- Banco: só leitura. Não ler nem gravar `products.cost_price`.
- Nunca sobrescrever nem apagar mídia do usuário: converter e copiar para arquivo novo.
- Tudo que publica algo fora do PC (Instagram) tem **modo ensaio** (vai até o passo anterior a publicar) e registra log + prints.
- Configuração (pastas, WhatsApp, lista de áudios, textos da figurinha, presets de exportação) fica em `config/*.json`, não espalhada no código.
- Python 3 no Windows; mensagens e logs em português; `pytest` para tudo o que der para testar na nuvem.
- Commits pequenos, mensagens em português.

## Regra do conhecimento
Todo erro resolvido e toda regra nova do usuário entram, **no mesmo commit**, no arquivo de `conhecimento/` e na skill da rotina. A próxima sessão não pode ter que redescobrir nada.

## Mapa
- `BRIEFING.md` — o que construir nesta fase, arquitetura, critérios de aceite, ordem de trabalho.
- `conhecimento/stories.md` — todas as regras de postagem de stories (obrigatórias).
- `conhecimento/edicao-video-capcut.md` — guia de edição no CapCut do usuário: mapa real da interface, atalhos, receitas de moda, cor, áudio, exportação, checklist, zonas seguras, rascunho em JSON (§11).
- `conhecimento/capcut-rascunho-e-exportacao.md` — formato do rascunho da 9.x, ferramentas comunitárias e seus limites, modal de exportação com posições e bloqueios.
- `conhecimento/capcut-avaliacao-ferramentas.md` — avaliação rodada de pyCapCut, VectCutAPI, capcut-cli e capcut-mcp, decisão pelo gerador próprio e o que falta confirmar com o gabarito real.
- `conhecimento/pc-instalacao-e-fila.md` — instalação no Windows, vigia, fila e ciclo de teste (armadilhas do PC).
- `README.md` — instalação e uso em uma página. `fila/README.md` — formato dos pedidos da fila, com exemplos.
- `rotinas/` — código (`stories/`, `video/`, fila, núcleo). `config/*.json` — configuração. `receitas/` — R1–R12 em JSON.
- `.claude/skills/postar-stories-ferreira/` e `.claude/skills/editar-video-ferreira/` — skills das rotinas.
- `execucoes/` — resultados do `testar.bat`/`diagnostico.bat` enviados pelo PC (dar `git pull` para ver).
