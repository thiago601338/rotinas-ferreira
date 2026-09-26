# Rascunho do CapCut: avaliação das ferramentas e decisão (B3)

Avaliação feita na nuvem em 25/09/2026. Complementa `capcut-rascunho-e-exportacao.md`. Legenda: **[rodado]** = verificado aqui, gerando um rascunho mínimo (1 vídeo + 1 texto + 1 áudio, mídia sintética) e lendo o JSON; **[doc]** = só da documentação, do código ou de relatos das próprias ferramentas (não conferido no CapCut). Nada aqui foi aberto num CapCut de verdade.

## Ferramentas

| | pyCapCut | VectCutAPI | capcut-cli | capcut-mcp |
|---|---|---|---|---|
| Onde / versão | PyPI `pycapcut` 0.0.3 (só existem 0.0.1–0.0.3); GitHub GuanYixuan/pyCapCut, commit de 25/09/2026, API do GitHub já diferente da 0.0.3 | GitHub sun-guannan/VectCutAPI, commit de 24/09/2026 | npm `capcut-cli` 0.26.0 (25/09/2026); GitHub renezander030/capcut-cli | Não está no npm/PyPI. GitHub JmsLdrn/capcut-mcp (original) e o fork alexkhomyakov/capcut-mcp (13/09/2026, com correções) |
| Licença | Não tem LICENSE no repositório [rodado: clone] | LICENSE Apache-2.0, mas o pyproject diz MIT (inconsistente) | MIT | MIT |
| Dependências no Windows | Python ≥ 3.8, pymediainfo, imageio, uiautomation | Python ≥ 3.10, flask, requests, oss2, psutil, json5 (+ fastapi/opencv no pyproject); servidor HTTP ou MCP | Node.js (não está no instalar.bat); ffprobe | Node 18+, @modelcontextprotocol/sdk, zod; ffprobe |
| Versão do CapCut do modelo | 6.7.0 Windows (`new_version` 140.0.0, `version` 360000) [rodado] | 6.5.0 **Mac** (perfil padrão `capcut_legacy`); o apelido "capcut" aponta para um modelo do JianYing 10.2 [rodado] | 6.5.0 Mac no modelo embutido; da v0.23 em diante clona o projeto mais novo da pasta de rascunhos [rodado + doc] | Não tem modelo: clona um rascunho que já existe (`CAPCUT_TEMPLATE_DRAFT`) [rodado] |
| Arquivos que grava | `draft_content.json` + `draft_meta_info.json` (cópia fixa do modelo: sem nome, sem pasta, `draft_materials` vazio) [rodado] | Copia a pasta-modelo inteira e só reescreve `draft_info.json`; `template-2.tmp` e `.bak` ficam com o conteúdo velho do modelo; meta não atualizado [rodado] | `draft_content.json` e `draft_info.json` iguais, `.bak`, `.capcut-cli-history/`, `draft_meta_info.json` com `draft_materials` preenchido [rodado] | Só o arquivo de linha do tempo que achar (`draft_content.json` ou `draft_info.json`) + `.mcpbak`; regrava o meta sem mudar nome/id [rodado] |
| `root_meta_info.json` | Não mexe [rodado] | Não mexe [rodado] | Registra (cria se não existir, `.bak` antes) [rodado] | Não mexe [rodado] |
| Mídia local | Caminho absoluto; duração do arquivo lida pelo pymediainfo (certa) [rodado] | **Copia** o arquivo para `<rascunho>/assets/` [rodado]; no deploy automático **apaga** projeto de mesmo nome na pasta do CapCut (`rmtree`) [doc: código] | **Copia** para `<rascunho>/assets/`; duração do material = duração do trecho (3 s num arquivo de 5 s) [rodado] | Caminho absoluto, duração pelo ffprobe [rodado]; zera `local_material_id` [doc: código] |
| `local_material_id` ligado ao meta | Não (vazio no vídeo) [rodado] | Não [rodado] | Sim [rodado] | Não [doc: código] |
| Texto | JSON com `styles` + `text`; y positivo = para cima (legenda importada ≈ −0,8) [rodado + doc] | Igual (usa um fork do pyJianYingDraft) [rodado] | Igual; `range` em unidades UTF-16 [rodado + doc #85] | Exige texto no rascunho-base [doc] |
| Áudio, velocidade, volume, keyframes | Sim / material `speeds` / linear (0,6 ≈ −4,4 dB) / sim [rodado + doc] | Sim / sim / linear / sim [doc] | Sim / sim / linear / não | Sim / sim / linear / só por "patch" cru [doc] |
| Defeitos vistos rodando | Segmento de texto aponta para um material de velocidade que não é gravado | O mesmo do texto; cria uma faixa de vídeo vazia a mais | Duração do material errada (acima) | Áudio montado com o protótipo de VÍDEO quando o áudio do rascunho-base é `extract_music` (ficou com `crop`, `width`…) |
| Segurança [doc: código] | Nenhuma (sem checar CapCut aberto, sem backup) | Nenhuma; apaga pasta existente | CapCut aberto (tasklist), gravação atômica, backup, trava de versão (> 9.x recusa) | CapCut aberto e `.locked`, `.mcpbak`, validação |
| Manutenção [doc] | Ativa, "módulos em migração" | Ativa | Muito ativa (0.17 em 08/2026 → 0.26 em 25/09/2026) | Fork avaliado: último commit em 13/09/2026, com correções locais; o original não foi conferido |

## Comparação das estruturas geradas [rodado]
- Chaves de topo em comum nas 4: `canvas_config, duration, extra_info, fps, id, materials, name, platform, tracks`. pyCapCut e capcut-mcp: 31 chaves; VectCutAPI: 28; capcut-cli: só 9.
- `materials`: 45 listas (pyCapCut, VectCutAPI, capcut-mcp) contra 18 (capcut-cli). Vídeo, áudio e texto em `videos`, `audios` (tipo `extract_music` para arquivo importado) e `texts`.
- Segmento de vídeo: 25 chaves (as três primeiras: `enable_*`, `hdr_settings`, `uniform_scale`…) contra 16 no capcut-cli (tem `raw_segment_id`). Tempos `target_timerange`/`source_timerange` `{start, duration}` em µs inteiros; `speed`, `volume` linear, `clip` com `scale` e `transform` (−1..1, meia tela; y para cima).
- `extra_material_refs`: só `speeds` (pyCapCut, VectCutAPI, capcut-mcp) contra `speeds, placeholder_infos, sound_channel_mappings, vocal_separations` (+ `canvases`, `material_colors` no vídeo) no capcut-cli. O CapCut real: confirmar com o gabarito.
- Ids: hex minúsculo (pyCapCut, VectCutAPI), UUID minúsculo (capcut-cli), UUID maiúsculo (capcut-mcp).
- Todas carimbam CapCut 6.5/6.7. Nenhuma tem marcadores da 9.x.

## Relatos que valem para a 9.x [doc, não confirmados aqui]
- 8.7 Windows: rascunho feito do modelo 6.5.0 foi **recusado** ("caminho incomum"); o mesmo fluxo clonando um projeto criado pelo app abriu na 9.3.0 (capcut-cli #111, #67).
- 8.7: edição só no `draft_content.json` pode ser ignorada em favor de `template-2.tmp`/`draft_meta_info.json` (capcut-cli #35). 9.2.8 Mac lê `Timelines/<id>/draft_info.json`; na 8.4 e 9.3 o app monta `Timelines/` sozinho quando ela não vem (capcut-cli #50).
- 9.1/9.3: mídia sem entrada em `draft_meta_info.json › draft_materials` ou com `local_material_id` vazio aparece como inacessível e o "Vincular mídia" não conserta (pyCapCut #13, JmsLdrn/capcut-mcp #1).
- Duração do material errada faz o CapCut mandar o início do trecho para 0 (capcut-mcp). Fade clonado de modelo vira fade indesejado (capcut-mcp).
- A lista de projetos vem do `root_meta_info.json` (capcut-cli). O pyCapCut diz que às vezes basta reabrir o CapCut. Confirmar no PC.

## Decisão
**Gerador próprio sobre o gabarito** (`rotinas/video/rascunho.py` + `capcut.py`, só biblioteca padrão). Motivos:
1. Nenhuma ferramenta foi feita ou testada para a 9.5, e todos os modelos são 6.5/6.7, justamente o que foi recusado na 8.7. O caminho que funcionou nos relatos é clonar um projeto criado pelo próprio app, e é isso que o gerador faz com o "0925".
2. As regras da loja: a VectCutAPI apaga projeto de mesmo nome. A VectCutAPI e o capcut-cli copiam o bruto (GBs) para dentro da pasta do CapCut. O pyCapCut e a VectCutAPI não fazem backup nem checam se o CapCut está aberto.
3. Cada uma erra uma peça: o pyCapCut não grava `draft_info.json` nem liga a mídia ao meta; a VectCutAPI deixa espelhos velhos; o capcut-cli erra a duração do material; o capcut-mcp precisa de um rascunho pronto e monta mal o áudio.
4. Dependências: capcut-cli e capcut-mcp exigem Node; a VectCutAPI traz um servidor inteiro.

O gerador já incorpora esses relatos: grava a mesma linha do tempo em todos os arquivos que o gabarito tiver (`draft_info.json`, `draft_content.json`, `template-2.tmp`, inclusive dentro de "envelope"); não leva `Timelines/` (`config/capcut.json › timelines`: `omitir` | `espelhar`); liga `local_material_id` ↔ `draft_materials`; usa a duração real do arquivo; grava áudio local como `extract_music`; zera fades e animações clonados; não copia efeito/transição da biblioteca (vão para o relatório); usa UUID maiúsculo e `range` em UTF-16; registra no `root_meta_info.json` clonando uma entrada existente (modo `auto`); recusa com o CapCut aberto ou com o gabarito criptografado; faz backup; valida antes de gravar. Conferência cruzada [rodado]: o `capcut lint` (capcut-cli 0.26) no rascunho gerado dá 0 erro e 0 aviso, só 2 informativos ("mídia fora da pasta do rascunho", que é de propósito: o bruto é referenciado onde está).

## Cuidados do gerador achados na revisão (valem para qualquer gabarito)
- Protótipo clonado do gabarito carrega arquivos derivados da mídia DELE (`reverse_path`, `intensifies_path`, `stable.matrix_path`…) e o `reverse` do segmento: o gerador zera todo campo `*_path` do material (menos o `path`) e põe `reverse: false`.
- Troca de caminho do gabarito nos auxiliares é feita no texto cru do JSON: caminho com `\` aparece escapado (`C:\\Users…`); o gerador troca as duas formas.
- `root_meta_info.json › draft_ids`: significado não confirmado; o gerador só aumenta (nunca volta para o tamanho da lista).
- Pasta de rascunhos inexistente = config errada: recusa (só o ensaio cria a pasta dele).
- Carimbos `tm_*` na unidade que o gabarito/índice usa (s, ms ou µs); sem referência, µs.

## O que falta confirmar com o gabarito real "0925"
**Atualização de 25/09/2026:** o gabarito real chegou (`gabaritos/capcut-9.5/0925/`) e confirmou os itens 1 e 3 abaixo — ver "Formato confirmado no PC" em `capcut-rascunho-e-exportacao.md`. Continuam abertos: protótipo de áudio local (item 2), calibração do texto (item 4) e o teste de abrir no app.

Enquanto ele não chega, os testes usam `tests/dados/gabarito_provisorio/` (saída do pyCapCut 0.0.3 com caminhos falsos). Onde o gerador procura o gabarito, nesta ordem: `gabaritos/capcut-9.5/0925/` no repositório (é lá que o gabarito conferido deve ficar), a cópia mais nova do diagnóstico (`execucoes/*/capcut_0925/`) e o projeto "0925" do PC (só leitura). Para ver o que o gabarito tem: `python -m rotinas video-rascunho --inspecionar <pasta>`.
1. Quais arquivos existem e estão em JSON aberto (`draft_info.json`, `draft_content.json`, `template-2.tmp` puro ou em envelope, `Timelines/`), qual é o principal (`draft_json_file` no `root_meta_info.json`) e quais são os marcadores (`app_version`, `new_version`, `version`).
2. Protótipos: o "0925" só tem um clipe **da Biblioteca** e um "Texto padrão". Falta vídeo **local** e **áudio**. Hoje o áudio usa o protótipo de reserva (pyCapCut, 6.7) e o vídeo usa o clipe da Biblioteca com os campos de origem limpos por suposição.
3. `extra_material_refs` obrigatórios de cada tipo de segmento na 9.5, formato do `draft_meta_info.json` (`draft_materials`, unidades de `tm_*`) e do `root_meta_info.json` (`all_draft_store`, `draft_ids`), estilo de caminho (`/` ou `\`) e caixa dos ids.
4. Texto: unidade do `size` em relação aos pixels (fator provisório 3,0 em `config/capcut.json`; calibrar com a régua da §5 de `edicao-video-capcut.md`), largura do contorno, fonte, sinal do y.
5. Proporção gravada para 9:16 (`"9:16"` ou `"original"`) e o que mais existe na pasta do projeto que não deve ser clonado.
6. Teste final: `testar.bat capcut-rascunho` gera "Teste Rotinas <carimbo>" e o usuário diz se abriu sem "mídia perdida".
