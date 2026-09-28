# Associar stories às peças publicadas

POST protegido por `x-ai-followup-token` e `ai_followup_valid`, com `verify_jwt=false`. Usa os mesmos secrets de banco/token da sincronização. A função registra a peça e não publica nem responde ao Instagram. Pode operar nos dois modos de atendimento, pois seu objetivo é preencher o cadastro de stories.

Antes de consultar stories, valida o token comparando os IDs canônicos retornados por `/me?fields=id` e `/17841454587986765?fields=id`. O cadastro permanece com `account_id=17841454587986765`, conforme as mensagens e registros existentes; o ID de `/me` pode ser diferente e não é comparado diretamente com esse valor configurado.

Contrato básico após confirmar a publicação:

```json
{
  "letra": "A",
  "sku": "FB-0001",
  "cor": "preto",
  "n_midias": 2,
  "publicado_de": "2026-09-27T12:00:00-03:00",
  "publicado_ate": "2026-09-27T12:05:00-03:00"
}
```

Aceita `product_id` no lugar de `sku`; se ambos forem fornecidos, devem identificar o mesmo produto ativo. Cor informada precisa existir no cadastro. A janela exige timezone explícito, no máximo 24 horas, e não pode terminar no futuro. A API só disponibiliza stories ainda acessíveis.

Para uma letra com peças diferentes, fornecer `varios_modelos:true` e `midias` com SKU/produto e cor de **cada arquivo**, na ordem em que foram publicados. O manifesto precisa ter exatamente `n_midias` registros. Quando dois stories têm o mesmo timestamp, incluir `story_id` em todos os itens para remover a ambiguidade.

```json
{
  "letra": "F",
  "varios_modelos": true,
  "n_midias": 2,
  "publicado_de": "2026-09-27T12:00:00-03:00",
  "publicado_ate": "2026-09-27T12:05:00-03:00",
  "midias": [
    {"sku": "FB-0001", "cor": "preto", "story_id": "10000001"},
    {"sku": "FB-0002", "cor": "rosa", "story_id": "10000002"}
  ]
}
```

Apenas stories na janela e ainda sem cadastro entram na comparação. Se a contagem divergir ou a ordem for ambígua, responde 409 e registra o motivo sem associar nenhuma peça. Produto, cor e lote são validados novamente dentro de uma transação; falha em qualquer item desfaz todos. `atendimento.registrar_story()` grava método `postagem`. O hash do pedido na evidência permite repetir com segurança exatamente o mesmo corpo após timeout: resposta `ja_registrado:true` confirma o lote completo, mesmo que os stories já tenham expirado.

A rotina do PC deve chamar esta função somente após confirmar publicação. Para vestido de festa com vários modelos, não enviar um único SKU para a letra inteira; sem manifesto por arquivo, deixar a associação pendente. Esta Edge não altera o vigia nem os arquivos de mídia.
