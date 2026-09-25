# Fila de pedidos (ponte IA ↔ Windows)

A IA do Cowork só lê e grava arquivos nas pastas montadas do PC: não abre BlueStacks, CapCut nem ADB.
Para isso existe a fila: a IA grava um **pedido** (JSON), o **vigia** (programa sem janela que roda no
Windows desde o logon) executa e devolve o **resultado** (JSON + log + prints). Código: `rotinas/fila.py`.

## Onde fica

`C:\Users\V15\Documents\Rotinas Ferreira\fila\` (pasta `rotinas` de `config/pastas.json` + `\fila`).
Na VM do Cowork é a pasta montada equivalente.

```
fila\
  pendente\     <id>.json            a IA grava aqui
  andamento\    <id>.json + <id>\     o vigia está executando (não mexer)
  feito\        <id>.json + <id>\     terminou bem
  erro\         <id>.json + <id>\     terminou com erro (ou nem executou)
  vigia.vivo    último sinal de vida do vigia
  historico.jsonl   todo id já executado (não apagar: é o que impede repetir)
  vigia.lock    trava do vigia (não mexer)
  parar.flag    pedido de parada (só o atualizar.bat usa)
```

Estados: `pendente → andamento → feito | erro`. Um pedido por vez, do mais antigo para o mais novo
(pela hora de modificação do arquivo).

## Como pedir

| campo | obrigatório | o que é |
|---|---|---|
| `id` | sim | **igual ao nome do arquivo** sem `.json`. Só `A-Z a-z 0-9 . - _`, começa com letra ou número, até 121 caracteres. Sem espaço, acento, barra ou parênteses. Não terminar em ponto; não usar `con`, `nul`, `aux`, `prn`, `com1`…, `lpt1`… |
| `tipo` | sim | um dos tipos da tabela abaixo |
| `args` | sim | argumentos do tipo (`{}` se não tiver) |
| `ensaio` | não (`false`) | `true` = vai até o passo anterior a publicar; nada sai do PC |
| `diagnostico` | não (`false`) | `true` = salva XML da tela + print a cada passo |
| `criado_em` | recomendado | ISO 8601 com fuso, ex. `2026-09-25T14:30:00-03:00`. Serve para conferir que o resultado é do seu pedido |
| `origem` | recomendado | quem pediu: `"cowork"`, `"terminal"`, `"script"` |

Use booleanos JSON (`true`/`false`), não texto. Modelo de id: `aaaammdd-hhmmss-<tipo com hífen>[-detalhe]`,
ex. `20260925-143000-stories-preparar-2026-09-22`. **Nunca reutilize um id**, nem de pedido que deu erro:
antes de gravar, confira que não existe `<id>.json` em nenhuma das quatro pastas.

**Como gravar** (UTF-8):
1. Grave `fila\pendente\<id>.json.tmp` com o conteúdo completo.
2. Renomeie para `<id>.json`. O vigia só olha `*.json`, então ele nunca pega o arquivo pela metade.

Sem como renomear, grave `<id>.json` direto, de uma vez só (o vigia espera 5 s por um arquivo que ainda
não é JSON válido; depois disso, vai para `erro` como "JSON inválido").

Depois de gravado, não edite o arquivo. Cancelar só dá enquanto ele está em `pendente` (apague o arquivo);
em `andamento` não dá para cancelar pela fila.

No PC, pelo terminal (na pasta `sistema`, com a `.venv`):
`python -m rotinas fila criar <tipo> --args "{...}" [--id X] [--ensaio] [--diagnostico]`,
`python -m rotinas fila listar`, `python -m rotinas fila mostrar <id>`.

## Como esperar o resultado

- A cada ~10 s, veja se existe `fila\feito\<id>.json` **ou** `fila\erro\<id>.json`. Esse arquivo só aparece
  quando tudo terminou (é gravado de uma vez): pode ler assim que aparecer.
- Confira que `pedido.criado_em` do resultado é o do pedido que você gravou.
- Enquanto roda, dá para acompanhar `fila\andamento\<id>\log.txt` (só ler).
- A pasta do resultado (`feito\<id>\` ou `erro\<id>\`) tem `log.txt`, prints e o que a tarefa gravou.
  Use o nome da pasta que vem no campo `pasta` (se já existia uma pasta com esse nome, o vigia usa
  `<id>__hhmmss`). O campo `pasta` é caminho do Windows; na VM, use a pasta montada correspondente.

Formato do resultado:

| campo | quando | o que é |
|---|---|---|
| `id`, `tipo` | sempre | do pedido |
| `estado` | sempre | `"feito"` ou `"erro"` |
| `pedido` | sempre | cópia do pedido (no duplicado, com `id_original`) |
| `pasta` | sempre | pasta com log e prints (caminho do Windows) |
| `arquivos` | sempre | arquivos da pasta, relativos a ela, com `/` (ex. `prints/01.png`) |
| `resultado` | feito | o que a tarefa devolveu (formato por tipo) |
| `erro` | erro | mensagem em português |
| `tipo_erro`, `detalhe` | erro na execução | classe do erro e o fim do traceback |
| `resultado_parcial` | erro, se a tarefa informar | o que já foi feito antes do erro (ex.: letras que já subiram) |
| `inicio`, `fim`, `duracao_s` | se chegou a executar | horários ISO e duração em segundos |

Segredos (valores do `.env`, chaves, tokens) nunca aparecem: viram `***`.

## Garantias

- **Nunca executa duas vezes.** Todo id executado fica em `historico.jsonl`. Id repetido vai para
  `erro\<id>__duplicado-hhmmss.json` sem rodar (o resultado antigo `<id>.json` continua lá).
- **Pedido interrompido não é reexecutado.** Se o vigia parou no meio (PC desligou, vigia fechado), quando
  ele voltar o pedido vai para `erro` com "Interrompido". Antes de pedir de novo (com **outro** id), confira
  log e prints; em `stories.postar`, confira no Instagram o que já subiu.
- **Não executa pedido com problema:** JSON inválido, `id` diferente do nome do arquivo, id com caractere
  proibido ou tipo desconhecido vão direto para `erro`.
- **Config relida a cada pedido:** mudança em `config/*.json` vale no pedido seguinte, sem reiniciar o vigia.
- **Um vigia só.** A trava `vigia.lock` faz um segundo vigia sair sozinho.
- **`vigia.vivo`** = `{"pid", "em", "estado": "ocioso" | "executando", "pedido"}`.
  - `ocioso`: `em` é atualizado a cada ~2 s.
  - `executando`: `em` é atualizado a cada ~30 s enquanto o pedido roda (pedido longo, como postagem ou
    transcrição, é normal).
  - Vigia parado: o `em` não muda entre duas leituras com ~10 s de intervalo (`ocioso`) ou ~60 s
    (`executando`) — não compare com o relógio da VM, que pode estar diferente do PC —, ou pedido em
    `pendente` há mais de 1 min sem ir para `andamento`. Aí peça ao usuário: dois cliques em
    `C:\Users\V15\Documents\Rotinas Ferreira\sistema\atualizar.bat` (para, atualiza e religa o vigia).
    Só religar, sem atualizar: no Prompt de Comando,
    `cd /d "C:\Users\V15\Documents\Rotinas Ferreira\sistema" && .venv\Scripts\python.exe -m rotinas instalar --iniciar-vigia`.
    Se não voltar, os erros estão em `Rotinas Ferreira\logs\vigia-*.log` e `vigia-falha.txt`.
- **`parar.flag`**: o vigia sai quando está ocioso e encontra esse arquivo. É o `atualizar.bat` que usa;
  a IA não precisa criar.

## Tipos de pedido

| tipo | o que faz | args |
|---|---|---|
| `diagnostico` | versões, ADB, tela do Instagram, rascunho do CapCut, sem segredos | `{}`. Opcionais: `instagram`, `u2`, `supabase`, `verificar` (padrão `true`), `projeto` (projeto do CapCut) |
| `stories.preparar` | nomeia as mídias novas na próxima letra livre, converte `.mov` → `.mp4`, detecta vídeo sem áudio ou em silêncio, gera a folha de contato de cada letra; devolve o manifesto | `{"data": "2026-09-22"}`. Opcionais: `simular` (só mostra, não mexe na pasta), `grupos` (`[["IMG_1.MOV","IMG_2.JPG"], ...]`) |
| `stories.estoque` | produtos, cores e estoque (só leitura) | `{"consultas": [{"sku": "FB-0123"}, {"termo": "vestido midi"}]}`. `sku` é exato (maiúsculas como no cadastro); `termo` procura no **nome** (não na categoria) as palavras na ordem, com qualquer coisa entre elas (`"vestido festa"` acha "Vestido Longo Festa"); maiúsculas tanto faz, acento conta. Nada achado = `encontrados: 0`, sem erro |
| `stories.montar` | corta cores sem estoque e já postados, monta os links e grava o pedido `stories.postar` na fila; o resultado traz `pedido_postagem` (id desse pedido: espere por ele também) | `{"data", "identificacao": {letra: {"sku" ou "termo", "midias": {"A - 1": ["Verde"], ...}}}, "postar": true, "ensaio": true}`. Cores com o nome do cadastro (`estoque_por_cor`); nome parecido é aceito com aviso "cor aproximada", desconhecido dá erro sem gravar nada. Toda mídia da letra em `midias` ou `excluir`; letra fora de `identificacao` fica de fora (aviso). Opcionais: `ordem` (`"letras"` ou `"categorias"`), `permitir_repeticao` (`["B"]`), `diagnostico` (vale para o `stories.postar` gerado); sem `manifesto.json` (preparar real) dá erro; na letra: `excluir` (`{"A - 3": "motivo"}`), `musica` (índice de `audios_sem_som` ou objeto), `peca` (nome na mensagem) |
| `stories.postar` | posta pelo BlueStacks; em ensaio para antes de publicar e salva um print de cada mídia | `{"plano": {...}}` gerado pelo `stories.montar` (não escreva à mão). Opcional: `repostar` (`["A"]`, só quando o usuário mandar repetir) |
| `video.preparar` | inventário do bruto, tomadas, silêncios, transcrição, batidas, folhas de contato; grava `videos\trabalho\<projeto>\bruto.json` | `{"projeto": "nome"}` (pasta `videos\bruto\<projeto>`). Opcionais: `musica` (arquivo em `videos\musicas\` ou no bruto), `transcrever` (padrão `true`), `normalizar_vfr` |
| `video.planejar` | plano da linha do tempo a partir de receita + escolhas da IA; violação vira erro (lista em `erro`, causa em `resultado_parcial.avisos`). Plano sem violação substitui `plano.json`; o que viola vai para `plano-com-violacoes.json` (o bom fica). `escolhas.json` é sempre o último | `{"projeto", "receita": "r02", "escolhas": {...}}` (sem `escolhas`, usa `trabalho\<projeto>\escolhas.json`) |
| `video.rascunho` | gera o rascunho do CapCut a partir do `plano.json` (CapCut fechado); devolve `rascunho` (nome no CapCut), `resumo`, `manual` (acabamento à mão) | `{"projeto"}`. Opcionais: `nome` (nome no CapCut; padrão `"<projeto> <data>"`), `gabarito`. Com `"ensaio": true` grava só na pasta do pedido |
| `video.exportar` | grava `trabalho\<projeto>\instrucoes_exportacao.txt` e espera o `.mp4` em `videos\exportado` para conferir. O resultado só sai depois do arquivo (ou do `timeout_min`, padrão 30): leia as instruções com o pedido em `andamento`. A fila fica parada enquanto espera | `{"projeto", "destino": "reels" \| "stories" \| "tiktok" \| "feed"}`. Opcionais: `rascunho` (padrão: nome e duração do último rascunho do projeto), `nome_arquivo` (padrão `<projeto>_<destino>`), `duracao_esperada_s`, `esperar` (padrão `true`; `false` só grava as instruções), `timeout_min` |
| `video.conferir` | confere o arquivo exportado (duração, 1080×1920, fps, bitrate, áudio, loudness, tamanho); `resultado.aprovado` e `texto` com o que fazer | `{"arquivo" (nome em videos\exportado), "destino"}`. Opcionais: `duracao_esperada_s`, `som_esperado` (`"mudo"`, `"so_efeitos"`, `"com_som"`) ou `projeto` (deduz do `plano.json`) |

**Stories: ensaio é o padrão.** `stories.montar` monta o `stories.postar` em ensaio se `ensaio` for `true`
no pedido **ou** nos `args` (ou se faltar nos `args`). Postagem real só depois de um ensaio aprovado pelo
usuário, com `"ensaio": false` nos dois lugares.

**`stories.postar` com erro:** o resultado traz `resultado_parcial` com `letras` (estado de cada uma),
`publicadas`, `parou_em`, `relatorio` e `js_conferencia`. Para tentar de novo, resolva a causa e grave um
**novo `stories.montar`** (outro id): ele gera outro `stories.postar`. Não copie nem edite o plano à mão.

**Testar sem banco (só no PC/terminal, a IA não usa):** com `ROTINAS_ESTOQUE_FALSO=<arquivo.json>` no ambiente
do vigia, `stories.estoque` e `stories.montar` leem o estoque desse arquivo em vez do Supabase. Formato:
`{"produtos": [{"id": 1, "sku": "FB-0123", "name": "Vestido Midi Alça", "category": "Vestidos", "status": "Ativo",
"product_variations": [{"color": "Verde", "size": "M", "stock": 2}]}]}` (também aceita a lista sem `produtos`
e os nomes `nome`/`categoria`/`variacoes` com `cor`/`tamanho`/`estoque`). Produto com `deleted_at` ou
`status` diferente de `Ativo` é ignorado, como no banco.

## Exemplos de pedido

`fila\pendente\20260925-143000-diagnostico.json`
```json
{
  "id": "20260925-143000-diagnostico",
  "tipo": "diagnostico",
  "args": {},
  "ensaio": false,
  "diagnostico": false,
  "criado_em": "2026-09-25T14:30:00-03:00",
  "origem": "cowork"
}
```

`fila\pendente\20260925-143500-stories-preparar-2026-09-22.json`
```json
{
  "id": "20260925-143500-stories-preparar-2026-09-22",
  "tipo": "stories.preparar",
  "args": {"data": "2026-09-22"},
  "ensaio": false,
  "diagnostico": false,
  "criado_em": "2026-09-25T14:35:00-03:00",
  "origem": "cowork"
}
```

`fila\pendente\20260925-145000-stories-montar-2026-09-22.json` (ensaio)
```json
{
  "id": "20260925-145000-stories-montar-2026-09-22",
  "tipo": "stories.montar",
  "args": {
    "data": "2026-09-22",
    "identificacao": {
      "A": {"sku": "FB-0123", "midias": {"A - 1": ["Verde"], "A - 2": ["Verde"], "A - 3": ["Preto"]}},
      "B": {"termo": "vestido midi", "midias": {"B - 1": ["Azul"], "B - 2": ["Azul"]}}
    },
    "postar": true,
    "ensaio": true
  },
  "ensaio": true,
  "diagnostico": false,
  "criado_em": "2026-09-25T14:50:00-03:00",
  "origem": "cowork"
}
```

## Exemplos de resultado

`fila\feito\20260925-143500-stories-preparar-2026-09-22.json` (manifesto resumido a uma letra)
```json
{
  "id": "20260925-143500-stories-preparar-2026-09-22",
  "tipo": "stories.preparar",
  "estado": "feito",
  "pedido": {
    "id": "20260925-143500-stories-preparar-2026-09-22",
    "tipo": "stories.preparar",
    "args": {"data": "2026-09-22"},
    "ensaio": false,
    "diagnostico": false,
    "criado_em": "2026-09-25T14:35:00-03:00",
    "origem": "cowork"
  },
  "pasta": "C:\\Users\\V15\\Documents\\Rotinas Ferreira\\fila\\feito\\20260925-143500-stories-preparar-2026-09-22",
  "arquivos": ["log.txt"],
  "resultado": {
    "data": "2026-09-22",
    "pasta": "C:\\Users\\V15\\Documents\\Stories da Loja\\2026-09-22",
    "gerado_em": "2026-09-25T14:35:41-03:00",
    "simulado": false,
    "letras": {
      "A": {
        "nova": true,
        "folha": "C:\\Users\\V15\\Documents\\Rotinas Ferreira\\stories\\2026-09-22\\folhas\\A.jpg",
        "midias": [
          {"nome": "A - 1", "arquivo": "A - 1.mp4", "tipo": "video", "origem": "IMG_4501.MOV", "convertido": "remux", "audio": "sem_audio", "precisa_musica": true, "duracao_s": 12.4},
          {"nome": "A - 2", "arquivo": "A - 2.jpg", "tipo": "foto", "origem": "IMG_4502.JPG", "convertido": null, "audio": null, "precisa_musica": false, "duracao_s": null}
        ]
      }
    },
    "avisos": ["A - 1 é vídeo sem áudio: vai receber música do Instagram"]
  },
  "inicio": "2026-09-25T14:35:02-03:00",
  "fim": "2026-09-25T14:35:41-03:00",
  "duracao_s": 39.2
}
```

`fila\erro\20260925-150000-stories-preparar.json`
```json
{
  "id": "20260925-150000-stories-preparar",
  "tipo": "stories.preparar",
  "estado": "erro",
  "pedido": {
    "id": "20260925-150000-stories-preparar",
    "tipo": "stories.preparar",
    "args": {},
    "ensaio": false,
    "diagnostico": false,
    "criado_em": "2026-09-25T15:00:00-03:00",
    "origem": "cowork"
  },
  "pasta": "C:\\Users\\V15\\Documents\\Rotinas Ferreira\\fila\\erro\\20260925-150000-stories-preparar",
  "arquivos": ["log.txt"],
  "erro": "Pedido stories.preparar sem \"data\" (AAAA-MM-DD)",
  "tipo_erro": "ErroPasta",
  "detalhe": "Traceback (most recent call last):\n  ...\nrotinas.stories.pasta.ErroPasta: Pedido stories.preparar sem \"data\" (AAAA-MM-DD)\n",
  "inicio": "2026-09-25T15:00:02-03:00",
  "fim": "2026-09-25T15:00:02-03:00",
  "duracao_s": 0.0
}
```
