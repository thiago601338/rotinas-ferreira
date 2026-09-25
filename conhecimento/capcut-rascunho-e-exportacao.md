# CapCut 9.5: rascunho e exportação (detalhes para automação)

Complementa `edicao-video-capcut.md`. Origem: mapeamento feito no PC do usuário e pesquisa sobre o formato de rascunho, ambos de 25/09/2026. As coordenadas estão no quadro das capturas de tela (1456×819). Para a tela real de 1920×1080, multiplicar por ≈1,3187.

## Rascunho
- Pasta: `C:\Users\V15\AppData\Local\CapCut\User Data\Projects\com.lveditor.draft\<projeto>\`, com uma subpasta por projeto.
- Arquivos: `draft_content.json` (linha do tempo) e `draft_meta_info.json` (metadados). A partir da 8.7 aparecem também `draft_info.json`, como arquivo principal, e o espelho `template-2.tmp`. **Confirmar na 9.5 com o gabarito.**
- Chaves de topo de `draft_content.json`: `id`, `name`, `duration` (µs), `fps`, `canvas_config` (largura, altura, proporção), `platform` (`"cc"` = CapCut internacional; `"lv"` = JianYing), `tracks[]` (segmentos com tempos em µs que apontam para um `material_id`) e `materials` (vídeos, áudios, textos, efeitos, transições, máscaras, velocidades).
- Criptografia em set/2026: o JianYing 6.0–10.x criptografa (AES-256-GCM). Segundo quem testou em 2026, o **CapCut internacional 8.7 e 9.x segue em JSON aberto**. Teste rápido: o arquivo começa com `{` e dá para ler.
- O rascunho aponta para a mídia pelo caminho. Mover ou renomear a mídia depois gera "mídia offline".
- Gabarito disponível: o projeto de teste **"0925"**, com um clipe de estoque verde de 7 s ("coin rainy animation greenscreen") e um "Texto padrão".

| Ferramenta | O que faz | Limites |
|---|---|---|
| VectCutAPI (antiga CapCutAPI) | API HTTP e MCP: cria rascunhos com vídeo, áudio, texto, legendas SRT, efeitos, adesivos e keyframes; gera pastas `dfd_…` | cópia para a pasta de rascunhos é manual |
| pyCapCut (v0.0.3, 08/2025) | Python: modo modelo (troca mídia e texto), mídia, animações, efeitos, filtros, máscaras, keyframes, fades | só rascunho não criptografado; módulos "em migração" |
| pyJianYingDraft | o mesmo, para JianYing | foco no JianYing |
| capcut-mcp | lista rascunhos, lê a linha do tempo, adiciona, move, apara e divide clipes, texto e áudio; salva com backup `.mcpbak`; aceita `CAPCUT_DRAFTS_DIR` | CapCut fechado; efeitos e transições são "melhor esforço"; texto exige modelo com camada de texto |
| capcut-cli (v0.26.0 em 25/09/2026; era 0.17.x em 08/2026) | CLI determinística (Node): detecta criptografia, testada com 8.7 e 9.x, importa OpenTimelineIO, gera rascunhos em lote, registra no `root_meta_info.json`; tem `lint` | não descriptografa; duração do material errada (usa a do trecho) |
| capcut-ai-editor | remove silêncios e tomadas repetidas de vídeo falado e gera projeto | foco em vídeo de "cabeça falante" |

- **Nenhuma exporta MP4** e não existe API oficial.
- Avaliação rodada de cada uma e a decisão (gerador próprio sobre o gabarito "0925", `rotinas/video/rascunho.py`): `capcut-avaliacao-ferramentas.md`.
- Regras: CapCut fechado ao gravar, backup antes, validação antes de salvar. Depois, abrir no app, revisar e exportar.

## Exportação (modal "Exportar-<nome do projeto>", Ctrl+E)
- Campos: Nome · Exportar para (padrão `C:/Users/V15/AppData/Local/CapCut…`) · ☑ Vídeo: Resolução (480P · 720P · **1080P** · 2K · 4K · 8K), Taxa de bits (Abaixar · **Recomendado** · Superior · Personalizado), Codec (**H.264** · HEVC · HEVC Alpha · HEVC 422 · AV1 · RLE), Formato (mov · **mp4**), Taxa de quadros (24 · 25 · 29.97 · **30** · 50 · 59.94 · 60), Espaço de cores Rec.709 SDR (fixo) · ☑ "Sincronize os vídeos exportados com o espaço" · ☐ Áudio (MP3) · ☐ GIF · ☐ Legendas 💎 (SRT) · Verificar direitos autorais (desligado) · rodapé com o tamanho estimado e os botões **[Exportar]** e **[Cancelar]**.
- **Bloqueio:** se a linha do tempo tiver só material da Biblioteca sem edição, o Ctrl+E mostra "Não foi possível exportar — Para evitar violação de direitos autorais, não exporte materiais sem editá-los no CapCut." [OK]. Depois de adicionar um texto, abriu normalmente.
- O modal **não fecha com Esc**. Para cancelar sem clicar: Alt+Espaço → f.
- Menus suspensos às vezes pedem 2 cliques. Fechar clicando no próprio campo, porque a lista de fps cobre o botão Exportar. **[Exportar] e [Cancelar] ficam a ≈75 px um do outro.**
- Posições medidas com a janela do CapCut em x=256 e largura 1200: modal em 515–1196 × 73–700; coluna de menus em x≈954–1166 (Resolução y=316, Taxa de bits 352, Codec 388, Formato 424, Taxa de quadros 460); Exportar (1071,675), Cancelar (1146,675). Com a janela maximizada, o modal centraliza em x≈728: somar ≈ −128 em x.
- O alvo de volume do app é "Padrão (−23 LUFS)". A mixagem mira ≈ −14 LUFS (ver `edicao-video-capcut.md` §7).

## Obstáculos do PC para automação pela interface
- A janela do app Claude Desktop pode vir para a frente, no lado direito, por 3–15 s depois de ações. Automação por teclado precisa garantir o foco na janela do CapCut antes de cada atalho.
- Menus e submenus abrem por clique, não por passar o mouse. Não há dicas de ferramenta.
- Projeto novo pode abrir um tour de 5 passos que trava a janela. O passo 2 insere um clipe "Mídia perdida", que deve ser apagado.
- Zonas de perigo: Menu > Conta > **Excluir conta** (mesma altura de Ajuda > Atalhos), "Sair" logo abaixo de "Voltar à página inicial" e **Ctrl+Q fecha o CapCut**.
