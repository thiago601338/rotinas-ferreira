---
name: editar-video-ferreira
description: Editar vídeo da Ferreira Boutique (Reels, Stories, TikTok) com rascunho do CapCut gerado por script a partir de receitas — prepara o bruto, a IA escolhe receita, tomadas e textos, o script monta o rascunho e confere o arquivo exportado. Usar quando o usuário pedir para editar, montar ou conferir um vídeo da loja no CapCut.
---

# Editar vídeo — Ferreira Boutique (CapCut 9.5)

Você (IA no Cowork) só lê e grava arquivos nas pastas do PC; quem executa é o **vigia** no Windows. Pedido JSON em
`C:\Users\V15\Documents\Rotinas Ferreira\fila\pendente\`, resultado em `fila\feito\` ou `fila\erro\` — formato e
exemplos em `...\Rotinas Ferreira\sistema\fila\README.md`. Guia completo de edição (vale por inteiro):
`...\sistema\conhecimento\edicao-video-capcut.md`; rascunho e exportação: `capcut-rascunho-e-exportacao.md` e
`capcut-avaliacao-ferramentas.md` na mesma pasta.

## Quando usar
"Edita esse vídeo do vestido verde para Reels", "monta um provador com preço", "confere o vídeo exportado".

## Pré-requisitos (pedir ao usuário UMA coisa por vez, com o passo exato)
- Vigia vivo (`fila\vigia.vivo` muda entre duas leituras); parado → dois cliques em `...\sistema\atualizar.bat`.
- Bruto copiado **sem compressão** (cabo, Drive, Quick Share; nunca WhatsApp) para
  `C:\Users\V15\Documents\Rotinas Ferreira\videos\bruto\<projeto>\` (projeto = nome curto, ex. `vestido-verde`).
- Faixa-guia (se a receita corta na batida) em `...\videos\musicas\` ou no próprio bruto.
- **CapCut fechado** quando for gerar o rascunho.

## Como pedir e esperar
Gravar `fila\pendente\<id>.json.tmp` e renomear para `<id>.json`: `{"id", "tipo", "args", "ensaio": false,
"diagnostico": false, "criado_em": "<ISO com fuso>", "origem": "cowork"}` (`id` = nome do arquivo, nunca reutilizar).
Ler `fila\feito\<id>.json` ou `fila\erro\<id>.json` a cada ~10 s (só aparece quando terminou).

## Passo a passo (o que é script e o que você decide)
**1. Preparar o bruto** — `tipo: "video.preparar"`, `args: {"projeto": "vestido-verde", "musica": "guia.mp3"}`
   (`musica` = nome do arquivo em `videos\musicas\` ou no bruto, .mp3/.wav, só se houver faixa-guia; fps variável →
   `"normalizar_vfr": true`).
   - Script: inventário com avisos (HDR, fps variável, 25/50 fps, horizontal, baixa resolução, sem áudio), tomadas
     `T01…`, silêncios, transcrição local + legendas `.srt`, batidas, folhas de contato.
   - Você lê `videos\trabalho\<projeto>\bruto.json` (`tomadas`: id, arquivo, `ini_s`/`fim_s` no arquivo, `dur_s`;
     `musica.bpm`) e olha SÓ as folhas `videos\trabalho\<projeto>\folhas\tomadas-NN.jpg`.
   - Aviso grave do bruto (HDR, peça com cor errada, sem a tomada que a receita exige) → dizer ao usuário em uma linha.
**2. Escolher receita, tomadas e textos** — **você decide** (objetivo, destino, duração; guia §3–§5 e §4.4):
   | receita | para | duração |
   |---|---|---|
   | r01 troca de look na batida · r02 provador com preço · r04 detalhe que vende · r07 antes e depois · r09 congela e recorta | vender | 6–25 s |
   | r03 uma peça, três formas | ensinar | 20–35 s |
   | r05 photo dump · r06 vitrine cinematográfica · r10 velocity de passarela · r11 embalando seu pedido | inspirar | 8–30 s |
   | r08 clone indecisa · r12 escolha o look | divertir | 10–15 s |
   Papéis e durações de cada bloco: `...\sistema\receitas\r02-provador-com-preco.json` (`r01-…` a `r12-…`), campo
   `estrutura` (`papel`, `dur_s` [mín, máx], `repete` [mín, máx], `texto`). No pedido, `receita` é só `"r02"`.
   Preço: `stories.estoque` com o SKU (`args: {"consultas": [{"sku": "FB-0123"}]}`) → número `preco` do produto
   (o `texto` do resultado escreve "R$ 229,99" com espaço; o plano formata sozinho). Só cores com estoque.
   - Escolha tomadas com `dur_s` dentro do `dur_s` do papel: sem `ini_s/fim_s` o script usa a tomada inteira (até o
     máximo). Tomada curta no `preco` (< 2,5 s) derruba o tempo do CTA, que entra 0,5 s depois do preço.
   - R1: o contador "LOOK n/total" é automático e conta `look` + `look_final` (4 looks + final = "LOOK 5/5"): o número
     do gancho tem que bater. `look_final` é câmera lenta 0,5x: bruto a 30 fps só gera aviso (fica travado).
   - Vídeo > 15 s: dê `texto` (re-gancho) a um bloco do meio que tenha texto na receita (R2: `prova`).
**3. Planejar** — `tipo: "video.planejar"`, `args`:
   ```json
   {"projeto": "vestido-verde", "receita": "r02",
    "escolhas": {"destino": "reels", "sku": "FB-0123", "preco": 229.99, "cta": "Chama no WhatsApp", "legendas": true,
      "blocos": [
        {"papel": "gancho", "tomada": "T03", "ini_s": 0.4, "fim_s": 1.6, "texto": "Esse verde esgota rápido"},
        {"papel": "prova", "tomada": "T05", "texto": "Olha esse caimento"}, {"papel": "prova", "tomadas": ["T07", "T08"]},
        {"papel": "detalhe", "tomada": "T10"}, {"papel": "bolso", "tomada": "T11", "texto": "bolso embutido"},
        {"papel": "preco", "tomada": "T02"}]}}
   ```
   - `ini_s/fim_s` são tempos **do arquivo** dentro da tomada; `"tomadas": [...]` seguidas juntam uma tomada picotada.
   - Script: monta a linha do tempo, corta na batida, põe textos na zona segura, preço "R$229,99" + "3x sem juros",
     legendas retimadas, volumes; **valida** (gancho no quadro 1, ritmo 1–3 s, zona segura, tempo e tamanho de texto,
     orçamento de efeitos, ≤ 3 flashes/s, duração do destino). Violação → erro com a lista: corrigir as escolhas e repetir.
   - Leia sempre `resultado.avisos` (ou `resultado_parcial.avisos` no erro): a causa da violação costuma estar lá
     (ex.: "bloco 7 (preco) ficou com 2,00 s … escolher um trecho mais longo"). `acabamento` = o que fica à mão.
   - `plano.json` é um por projeto: cada `video.planejar` **sem violação** o substitui (o que viola vai para
     `plano-com-violacoes.json` e não apaga o bom); o `escolhas.json` é sempre o último. Mande sempre `escolhas` e gere
     o rascunho de cada receita logo depois do plano bom dela.
   - Sem transcrição (faster-whisper ausente): a voz só fica nos blocos que a receita marca como fala; nos outros o som
     entra mudo (−60 dB) e `"legendas": true` dá 0 legendas — os dois vêm como aviso. Diga ao usuário em uma linha
     (subir o volume do clipe e legendas automáticas no CapCut) ou peça o `atualizar.bat` e prepare de novo.
**4. Gerar o rascunho** — `tipo: "video.rascunho"`, `args: {"projeto": "vestido-verde", "nome": "Vestido verde – R02"}`
   (CapCut fechado; sem `nome` vira "vestido-verde 2026-09-25"). Script: backup, rascunho novo (nunca sobrescreve; nome
   repetido vira "(2)") e `videos\trabalho\<projeto>\relatorio_rascunho.txt`. Resultado: `rascunho` (nome real no
   CapCut), `resumo.duracao_s` e `manual` (lista completa do acabamento à mão — transições, efeitos que o rascunho não
   aplica, cor, loop, legendas, faixa-guia: use esta no aviso final). Com `"ensaio": true` grava só na pasta do pedido
   (nem o relatório do projeto muda; bom para testar sem mexer no CapCut).
**5. Acabamento e exportação** — `tipo: "video.exportar"`, `args: {"projeto": "vestido-verde", "destino": "reels",
   "rascunho": "Vestido verde – R02"}` (`rascunho` = nome do passo 4; sem ele vale o último rascunho do projeto).
   O script grava `videos\trabalho\<projeto>\instrucoes_exportacao.txt` (projeto a abrir, preset, nome
   `<projeto>_<destino>` e pasta `videos\exportado`) e **espera** o `.mp4` (até 30 min; `timeout_min` muda). O
   resultado só sai depois do arquivo: com o pedido em `fila\andamento\`, leia as instruções (1ª linha = rascunho
   certo) e passe ao usuário + a lista `manual`. Ele abre o projeto no CapCut, faz o acabamento e exporta (Ctrl+E).
   - Enquanto espera, a fila fica parada (um pedido por vez): não grave outro pedido esperando resposta rápida.
   - Duas receitas do mesmo projeto: `"nome_arquivo": "vestido-verde-r02_reels"` para não sair o mesmo nome.
**6. Conferir** — o próprio `video.exportar` confere quando o arquivo chega (ou `tipo: "video.conferir"`,
   `args: {"arquivo": "<nome>.mp4", "destino": "reels", "duracao_esperada_s": 18.5}`): duração, 1080×1920, fps,
   H.264, taxa de bits, áudio, −14 LUFS, pico ≤ −1 dBTP, tamanho (stories ~100 MB), SDR. `aprovado` + relatório em
   `texto`, com o "Fazer:" de cada item reprovado (repasse em uma linha). `arquivo` = nome dentro de `videos\exportado`.
   - Som: o `video.exportar` deduz do plano se o arquivo sai **mudo** (música pelo Instagram, sem fala) ou só com efeitos;
     aí áudio/volume não reprovam. No `video.conferir` avulso, passe `"projeto"` (deduz) ou `"som_esperado": "mudo"`.

## Regras fixas (resumo; detalhes no guia)
- O produto manda: nada cobre a peça nem muda cor/caimento; um plano com cor real; cor fiel ao cadastro.
- Gancho no quadro 1 (texto 3–7 palavras em y 300–700); mudança visual a cada 1–3 s; CTA ≤ 2 s.
- Texto e figurinhas no retângulo seguro x 80–920, y 280–1400 (stories: nada nos 270 px de cima nem nos 380 de baixo).
- Preço "R$229,99" (cifrão colado), igual ao cadastro; parcelas: até R$149,99 em 2x, até R$319,98 em 3x, acima em 5x,
  sem juros. Só cores e tamanhos com estoque.
- Música: exportar sem música do CapCut e pôr no Instagram (ou faixa licenciada). Item da biblioteca do CapCut só com
  marca "comercial" — um item não comercial restringe o vídeo inteiro. Decisão final é do dono.
- Mix ≈ −14 LUFS. O CapCut exporta a mistura exata da linha do tempo (não normaliza; medido em 26/09); o alvo −23 LUFS
  do app só age em "Normalizar volume" no clipe. Volume baixo → subir os clipes com som. Exportar `.mp4` H.264
  1080×1920 30 fps ("Personalizado 16.000" deu 14.636 kbps reais: passa).
- Não mudar configurações do CapCut sem o dono pedir. Nunca Ctrl+Q nem Menu > Conta.
- Não dar conselho de SEO nem sugerir mudança de escopo.

## Aviso final ao usuário (curto)
```
Rascunho "Vestido verde – R02" pronto no CapCut (18,5 s, Reels).
Falta à mão: lupa no tecido (0:07), seta no bolso (0:10). Exportar: Personalizado 16.000 Kbps, H.264, mp4, 30 fps,
nome "vestido-verde_reels.mp4" em Rotinas Ferreira\videos\exportado.
Conferência: APROVADO (ou: volume −22 LUFS → subir ~8 dB no clipe e exportar de novo).
```

## Erros conhecidos e solução
| Erro | Solução |
|---|---|
| "CapCut aberto" | Pedir para fechar o CapCut (Menu ▾ > Sair, não Ctrl+Q no meio da edição sem salvar) e repetir com outro id. |
| "Gabarito do CapCut não encontrado" | O projeto "0925" não está nos rascunhos do CapCut: perguntar ao usuário se existe ou qual projeto usar e repetir com `"gabarito": "<pasta do projeto>"`. |
| Violação no plano | Corrigir as escolhas (tomada mais curta/longa, texto menor, outro papel) e planejar de novo. |
| "ini_s fora da tomada" | Os tempos são do arquivo: conferir `ini_s`/`fim_s` da tomada no `bruto.json`. |
| "Música … não encontrada" | Pôr a faixa em `videos\musicas\` ou passar o caminho completo. |
| Violação só do CTA ("fica 1,5 s na tela") | Bloco `preco` curto: tomada/trecho de ≥ 2,5 s (ver `avisos`). |
| "Plano não encontrado" / "O plano tem violação" no rascunho | Planejar de novo (o `plano.json` é o do último planejar sem violação). |
| `video.exportar` parado em `andamento` | Normal: espera o `.mp4`. Erro "Nenhum .mp4 novo" = passou o tempo: pedir de novo. |
| Sem transcrição (faster-whisper/modelo) | Seguir sem legendas ou pedir `atualizar.bat`; o modelo baixa no primeiro uso (~480 MB). |
| Conferência: "áudio" reprovado num plano mudo | O arquivo saiu com som: a faixa-guia não foi desligada (V) no CapCut; exportar de novo. |
| Mídia perdida ao abrir o rascunho | Não mover/renomear o bruto depois do rascunho; se aconteceu, avisar e gerar de novo. |
| Rascunho abre com o clipe verde da Biblioteca no lugar do vídeo | Material herdou `material_id`/`source` do gabarito: conferir `limpar_campos_origem` e `zerar_campos_origem` em `config/capcut.json` (resolvido em 26/09). |
