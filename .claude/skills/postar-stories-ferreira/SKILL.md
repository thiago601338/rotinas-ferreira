---
name: postar-stories-ferreira
description: Postar stories da Ferreira Boutique pelo BlueStacks a partir da pasta do dia (Stories da Loja\<data>), com estoque, bloqueio de repetição e figurinha de link do WhatsApp.
---

# Postar stories — Ferreira Boutique

> Esboço. O passo a passo com os comandos exatos entra quando os scripts estiverem prontos (BRIEFING §9, etapa 5).
> As regras abaixo já valem.

## Regras fixas do usuário (obrigatórias; detalhes em `conhecimento/stories.md`)
- É story, não feed. Postagem só pelo BlueStacks.
- Só entra o que tem estoque: cor com estoque 0 sai do story (avisar depois quais ficaram de fora); modelo sem nenhuma peça não entra.
- Não repetir: modelo já postado não entra de novo (dizer quando e onde saiu).
- Uma letra por modelo: `A - 1` é o vídeo, `A - 2`, `A - 3`… as fotos. Nunca sobrescrever mídia.
- `.mov` vira `.mp4` antes de ir para a galeria do emulador.
- Vídeo sem áudio recebe música do Instagram da lista de `config/stories.json` (`audios_sem_som`).
- Figurinha de link **só na última mídia de cada letra**, com `wa.me/5582988748649?text=<mensagem com o nome da peça>`, **sem `https://`**. Texto da figurinha: "Comprar", "Comprar agora" ou "Comprar pelo Whatsapp". Confirmar no ✓ do teclado.
- **Vestido de festa não leva figurinha de link** (confirmado em 25/09/2026). Vale a categoria do cadastro: `Vestidos de Festa` / `VESTIDO DE FESTA`.
- Publicar em "Seu story" → Concluir. Nunca compartilhar no Facebook.
- Conferir depois pelo JS no navegador logado (quantidade de itens e `LINK` na última mídia de cada letra que leva link).
