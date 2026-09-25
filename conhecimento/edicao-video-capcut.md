
# Edição de vídeo no CapCut desktop (nível especialista)

Base: pesquisa de 25/09/2026 (manual oficial do CapCut, tutoriais 2025–2026, dados de plataforma) + mapeamento real do CapCut instalado no PC do usuário. Para ideias, ganchos e roteiros use também a skill `conteudo-viral-redes-sociais`; para capas, artes e stories estáticos, `design-redes-sociais`.

Detalhes para automação (formato do rascunho, ferramentas, modal de exportação): `capcut-rascunho-e-exportacao.md`, nesta mesma pasta.

## 0. Postura e fluxo

- Executar o que foi pedido, direto. O conhecimento abaixo serve para editar melhor, não para dar aula nem sugerir mudança de escopo. Só apontar problema concreto e grave (cor da peça errada, texto sob a interface, música que vai silenciar o vídeo, peça sem estoque, link quebrado), em uma linha.
- O usuário é especialista em SEO: não dar conselho de SEO.
- Fluxo de uma edição:
  1. Entender objetivo (vender, alcance, ensinar, inspirar), destino (Reels, Stories, TikTok, Feed), duração-alvo e se tem fala.
  2. Conferir o bruto: resolução, fps, HDR, orientação. `.mov` do iPhone (HEVC) abre no CapCut; para a galeria do Instagram no emulador (BlueStacks) o arquivo final precisa ser `.mp4`.
  3. Montar a espinha na faixa principal → ritmo → gancho no quadro 1.
  4. Acabamento: texto e legendas → efeitos (dentro do orçamento, §4.1) → cor fiel → áudio.
  5. Checklist (§9) → exportar (§8) → abrir o arquivo exportado e conferir.

## 1. O CapCut do usuário (verificado em 25/09/2026)

| Item | Valor |
|---|---|
| Versão | CapCut 9.5.0 (build 9.5.0.4050), Português (Brasil), conta Pro (renova 24/10/2026) |
| PC | Windows 11, notebook Acer, tela 1920×1080. Capturas do controle de tela chegam em 1456×819 (fator ≈1,3187). Coordenadas abaixo nesse quadro, com a janela maximizada; são aproximadas, confirmar com captura |
| Executáveis | `C:\Users\V15\AppData\Local\CapCut\Apps\CapCut.exe` (lançador) e `...\Apps\9.5.0.4050\CapCut.exe` (processo real). Os dois precisam de permissão no controle de tela |
| Rascunhos | `C:\Users\V15\AppData\Local\CapCut\User Data\Projects\com.lveditor.draft\<projeto>` |
| Configurações atuais | Proxy desligado; cache 16,7 GB sem limpeza automática; fps padrão 30; "Nível de volume desejado: Padrão (−23 LUFS)"; aceleração de hardware ligada; sincronização automática ligada (itens: vídeos exportados) |
| Projeto de teste | "0925" (primeira miniatura verde em Projetos). Pode apagar se o dono pedir |

Se a versão mudar (Menu ▾ > Mais > Versão), refazer o mapa: rótulos e posições mudam a cada atualização.

### 1.1 Mapa da interface (rótulos exatos)

**Tela inicial:** banner ciano "+ Criar projeto" no topo (clicar em qualquer ponto cria um projeto em branco com a data como nome, ex. "0925"). Barra lateral: Início, Modelos, "Criar com IA" (Estúdio de vídeo, Estúdio de design, Mais ferramentas), Biblioteca. ⚙ no canto superior direito (Configurações, Cobrança, Versão…). Em "Projetos", o mais recente é o primeiro da grade.

**Editor:**
- Barra superior (y≈16): Menu ▾ (106,16) · "Salvo automaticamente" · nome do projeto (centro) · layout · ⌨ atalhos (1096,16) · 💎Pro · Compartilhar (1215,16) · **Exportar** (1307,16; Ctrl+E).
- Abas (y≈55): Mídia (30) · Áudio (77) · Texto (123) · Stickers (170) · Efeitos (216) · Transições (268) · Legendas (322) · Filtros (371) · Ajuste (417) · Modelos (461) · › (486) revela Avatar de IA. Cada aba tem busca: é o jeito mais confiável de achar um item.
- Player (x≈505–990): "Reprodutor-Linha do tempo 01", menu ≡ (970,53). Controles (y≈407): timecode, ▶, "Preenchimento", zoom, **Proporção** (≈930,407), tela cheia.
- Painel de propriedades (x≈999–1447): abas em y≈53, sub-abas em y≈97. Cada seção tem ☐ ligar, ▾ expandir, ↺ redefinir, ◇ quadro-chave.
- Barra da timeline (y≈449): + · Selecionar/Dividir (A/B) · ↶ ↷ · ][ dividir (≈196) · [ excluir à esquerda (≈230) · ] excluir à direita (≈264) · 🗑 (≈298) · ⚑ marcador (≈332) · ícones de IA. À direita: 🎤 locução (1039), ímã (P), encaixe (N), vinculação (~), eixo (S), zoom da timeline (≈1296–1432). Os ícones não mostram dica ao passar o mouse.
- Faixas: principal (vídeo) em y≈623 com botão "Capa" (147,623); texto e efeitos acima; áudio abaixo. Timeline vazia: "Arraste o material aqui e comece a criar".

**Sub-abas úteis:**
- Mídia: Importar (Mídia, Subprojetos) · Seus (Favoritos, Minhas predefinições, Ativos de marca) · Gerar (Imagem de IA, Vídeo de IA…) · Biblioteca (mídia de estoque: Populares, Tela verde, Plano de fundo, Transições, Atmosfera…) · Dreamina.
- Áudio: Importar · Seus · Música (Sucessos, Trending, Vlog, Phonk, Marketing, Festa, Beleza, Romântico, Funk…) · Efeitos sonoros (Populares, ASMR, Assobios, Ding, Comemoração, Vinhetas…) · Direitos autorais.
- Texto: Adicionar texto ("Texto padrão") · Seus (Favoritos, Predefinições) · Efeitos de texto · Modelo de texto (Gerado por IA, Mídias sociais, Título, Anúncio, Legenda…) · Legendas automáticas · Legendas locais.
- Stickers: Seus · Adesivos (Ênfase, Oferta, Contagem regressiva, Emoji, Etiqueta, Colagem…) · Formas · GIPHY.
- Efeitos: Efeitos de vídeo (Populares, Clássico, ✨Recorte mágico, Intro e Outro, Festa, Movimento, 3D, Edições, Luz, Retrô, Falha, Distorção, Tela, Brilho, Dividir…) · Efeitos corpo (Clonagem, Linhas brilhantes, Traço, Retrato, Mascarar, Plano de fundo…).
- Transições: Populares, Clássico, NOVO, Êxitos, Camada, Luz, Câmera, 3D, Desfocar, Básico, Mascarar, Deslizar, Falha, Distorção.
- Legendas: Legendas automáticas ("Idioma de origem: Detectar automaticamente ▾", "Legendas bilíngues 💎") · Modelos (Palavra, Brilho, Letras…) · Letras automáticas · Adicionar legendas.
- Filtros: Em destaque, Vida, Retrato, Mono, Filmes, Retrô, Cremoso, Filme, Pôr do sol, Praia, Flash…
- Ajuste: Adicionar ajuste ("Ajuste personalizado" = camada de ajuste sobre vários clipes) · Seus · LUT.
- Modelos: Para você, Marketing, Moda&Beleza… com filtros de orientação, número de clipes e duração.

**Painel de propriedades:**
- Nada selecionado: **Projeto** (Sugestões inteligentes > Analisar; "Edições global 💎": Melhorar as cores, Uniformizar as cores, Uniformizar o volume, Tornar a voz mais clara) | **Detalhes** (Nome, Caminho, Proxy, Nome da linha do tempo, Proporção de aspecto, Resolução, Taxa de quadros; botão **Modificar**, cujo diálogo não foi mapeado).
- Clipe de vídeo: **Vídeo | Velocidade | Animação | Ajuste | Estilização de IA**.
  - Vídeo > Básico: Transformar (Escala, Escala uniforme, Posição X/Y, Girar, alinhamentos) · Mistura (modo, Opacidade) · Estabilização 💎 · Aprimorar qualidade 💎 · Reduzir ruído de imagem 💎 · Fluxo óptico 💎 · Remoção de IA 💎 · Expansão por IA · Remix de IA · Contato visual · Sincronização labial · Iluminação 💎 · Reenquadramento automático 💎 · Remover cintilações 💎 · Movimento de IA 💎 · Rastreio de câmera 💎 · Borrão de movimento 💎 · Tela (fundo: desfoque, cor, imagem).
  - Vídeo > Remover plano de fundo: Remoção automática 💎 · Remoção personalizada (pincel) · Chroma key ◇. Vídeo > Mascarar (+ Adicionar máscara, formas). Vídeo > Retoque (Rosto, Corpo, Cabelo, predefinições).
  - Velocidade: Padrão (multiplicador, duração, "Alterar tom do áudio", "Câmera lenta suave 💎") | Curvo | Efeitos de velocidade.
  - Animação: Entrada | Saída | Combinação.
- Texto: **Texto (Básico | Balão | Efeitos) | Animação | Rastreamento | Conversão de texto em fala | ›**. Básico: caixa de texto, Fonte, Tamanho, B U I, Caixa (TT tt Tt), Cor, Transformar, Mistura, Traço, Plano de fundo, Brilho, Sombra, Curvo; "Salvar como predefinição".
- Efeito: abas Básico | Máscara; em Básico > Detalhes ficam Nome, Velocidade e Força (com ◇).
- Clique direito no clipe: Copiar/Colar atributos · **Editar >** (Congelar, Reverso, Espelhar, Girar, Recortar) · Dividir cenas · Transcrição 💎 · Extrair áudio (selo "[1 uso]" nesta conta: conferir antes de usar) · Criar clipe composto (Alt+G) · Agrupar · Exportar clipes selecionados · Desativar clipe (V) · Substituir clipe · Renderizar >. A aba Velocidade também mostra um selo "[2 usos]".
- **Não conferidos na 9.5.0** (vieram de tutoriais; localizar na tela ou pela busca antes de agir): nomes dos presets do Curvo, nomes das formas de Mascarar, modos de Mistura, conteúdo das abas Ajuste e Estilização de IA do clipe, conteúdo da aba Rastreamento do texto, propriedades de clipe de áudio, menu ≡ do player (qualidade de pré-visualização) e a posição exata de ímã/encaixe/vinculação/eixo na barra da timeline.
- **EditPilot** (botão flutuante ≈1377,738): assistente de IA do CapCut; seleciona clipes ou área da prévia e descreve a edição em texto.
- Menu ▾: Arquivo (Novo projeto, Nova linha do tempo, Importar, Exportar) · Editar · Layout · Mais (Versão) · Ajuda (Atalhos, Sobre) · **Conta (contém "Excluir conta": nunca clicar)** · Configurações · Voltar à página inicial · **Sair (fecha o app)**. Submenus abrem por clique, não por hover.

**Janela Exportar (modal):** Nome · Exportar para · Vídeo: Resolução 480P/720P/**1080P**/2K/4K/8K · Taxa de bits Abaixar/**Recomendado**/Superior/Personalizado · Codec **H.264**/HEVC/HEVC (Alpha)/HEVC (422)/AV1/RLE · Formato mov/**mp4** · Taxa de quadros 24/25/29.97/**30**/50/59.94/60 · Espaço de cores Rec. 709 SDR (fixo, cinza) · ☑ "Sincronize os vídeos exportados com o espaço" (vem marcado; sobe o vídeo para a nuvem do CapCut, sob a licença ampla dos Termos) · Áudio (MP3) · Exportar GIF · Legendas 💎 (SRT, UTF-8) · Verificar direitos autorais · botões **Exportar** e **Cancelar** lado a lado (≈75 px). Material da Biblioteca sem nenhuma edição é bloqueado ("Não foi possível exportar…"). Não mudar configurações do app sem o dono pedir.

### 1.2 Atalhos (conferidos no painel Menu > Ajuda > Atalhos, predefinição "Atalho 1")

| Ação | Atalho | Ação | Atalho |
|---|---|---|---|
| Dividir | Ctrl+B | Dividir todas as faixas | Ctrl+Shift+B |
| Modo Selecionar / Dividir | A / B | Selecionar tudo à esquerda / direita | [ / ] |
| Excluir à esquerda / direita do cursor | Q / W | Excluir | Backspace ou Delete |
| Ímã da faixa principal | P | Encaixe automático | N |
| Vinculação | ~ | Eixo de pré-visualização | S |
| Zoom da timeline | Ctrl + "+" / Ctrl + "−", Ctrl+roda | Ajustar timeline à tela | Shift+Z |
| Rolar horizontal | Alt+roda | Desativar clipe | V |
| Extrair/restaurar áudio | Ctrl+Shift+S | Marcador / nova cor | M / Alt+M |
| Próximo / anterior marcador | Shift+M / Alt+Shift+M | Quadro a quadro | ← / → |
| 10 quadros | Shift+← / Shift+→ | Início / fim | Home / End |
| Corte anterior / próximo | ↑ / ↓ | Entrada / saída | I / O |
| Selecionar por clipe / desmarcar | Shift+X / Alt+X | Agrupar / desagrupar | Ctrl+G / Ctrl+Shift+G |
| Painel de velocidade | Ctrl+R | Velocidade em curva | Shift+B |
| Clipe composto / desfazer | Alt+G / Alt+Shift+G | Volume ±0,1 dB | Ctrl+. / Ctrl+, |
| J-K-L | J / K / L | Painel de quadros-chave | Alt+K |
| Adicionar quadro-chave | Shift+Alt+K (Shift+clique no painel) | Play/pausa | Espaço |
| Tela cheia do player | Ctrl+Shift+F | Réguas / guias | Ctrl+Alt+R / Ctrl+; |
| Cancelar alinhamento no player | segurar Ctrl | Copiar/colar atributos | Ctrl+Shift+C / Ctrl+Shift+V |
| Importar | Ctrl+I | **Exportar** | **Ctrl+E** |
| Novo projeto | Ctrl+N | Desfazer / refazer | Ctrl+Z / Ctrl+Shift+Z |
| **Fecha o CapCut (não usar)** | **Ctrl+Q** | Texto: redimensionar pelo centro | Alt+arrastar |

Sem atalho, mas atribuíveis: Congelar, Reverso, Espelhar, Girar, Recortar, Gerar legendas, Remover voz, Locução. Listas da internet divergem; vale o painel do app.

### 1.3 Operar por controle de tela

- **Confiabilidade:** atalho > campo numérico do painel (clicar, Ctrl+A, digitar, Enter) > menu com rótulo ou clique direito > busca da aba > arrastar (último recurso: dar zoom antes e fazer arrastos curtos).
- **Foco:** antes de atalho, clicar numa área vazia da timeline. Se houver caixa de texto em edição, Esc antes.
- **Selecionar o clipe certo** (borda destacada) antes de mexer: o painel direito muda conforme a seleção. Q/W no clipe errado → Ctrl+Z.
- **Ímã (P)** empurra clipes: desligar para arrastos delicados e religar depois. **Vinculação (~)** arrasta textos junto.
- **Sem dicas de ferramenta:** passar o mouse não mostra nome de ícone nem abre submenu. Clicar no item pai; para saber o que um ícone faz, usar o clique direito ou a lista de atalhos.
- **Modais** (Exportar, Configurações) não fecham com Esc. Cancelar sem clicar: Alt+Espaço → f. Menus suspensos do Exportar às vezes pedem 2 cliques; fechar clicando no próprio campo (a lista de fps cobre o botão Exportar).
- **Cliques em abas às vezes não pegam:** confirmar com captura e repetir.
- **Balões amarelos de dica** aparecem sobre a interface: fechar em "Entendi" ou "Fechar".
- **Janela do Claude Desktop** pode vir para a frente no lado direito (x≈944–1440) por 3–15 s depois de ações e cobrir painel, Exportar e modais. Esperar ~8–10 s e confirmar que o CapCut está visível antes de clicar ali. Clicar na barra de título do CapCut (≈560,8) traz o CapCut de volta. Alt+Espaço às vezes abre a janela do Claude.
- **Áreas mascaradas:** na sessão de mapeamento duas regiões apareceram cinza nas capturas (x≈170–908, y≈170–728 e x≈643–810, y≈15–136); os cliques passam, mas não se vê. Se voltar a acontecer: restaurar a janela (▢ em 1409,16) e arrastar a barra de título para a direita; a ferramenta recusa arrastes que terminam na área de trabalho.
- **Projeto novo** pode abrir um tour de 5 passos que trava a janela: avançar pelos botões; o passo 2 insere um clipe "Mídia perdida", que deve ser apagado.
- **Zonas de perigo:** Menu > Conta > Excluir conta (na mesma altura de Ajuda > Atalhos); "Sair" logo abaixo de "Voltar à página inicial"; Ctrl+Q; Exportar e Cancelar lado a lado; "remover recursos Pro" na exportação (apaga elementos).
- **Processos longos** (legendas, remover fundo, reverso, exportação): esperar a barra de progresso e conferir a cada 5–10 s, sem clicar.
- **Importar:** no diálogo do Windows, colar o caminho completo no campo "Nome". Não mover nem renomear mídia depois de importar (vira "mídia offline").
- O CapCut salva sozinho; esperar alguns segundos após a última ação antes de fechar.

## 2. Captação: o bruto decide a edição

- **Formato:** vertical 9:16, câmera nativa do celular. 4K a 30 fps como padrão (permite zoom de até 2x num projeto 1080×1920). 4K a 60 fps só nas tomadas que vão virar câmera lenta.
- **Brasil = 60 Hz:** gravar a 30 ou 60 fps. Evitar 25, 50 e 100 fps sob lâmpadas (cintila). Se aparecerem faixas: obturador 1/60 (30 fps) ou 1/120 (60 fps) no modo Pro ou no app Blackmagic Camera. LED com dimmer em 100%.
- **HDR desligado** ("Vídeo HDR" no iPhone, "HDR10+" no Samsung) em tudo que passa pelo CapCut; projeto e exportação em SDR Rec.709. FPS automático desligado.
- **Travar foco e exposição** com toque longo até "BLOQUEIO AE/AF" (isso não trava o branco). **Balanço de branco** travado à parte: "Bloquear Equilíbrio de Branco" no iPhone (se existir na versão) ou Kelvin manual no Vídeo Pro (Samsung) ou no app Blackmagic Camera (5.600 K para LED luz do dia; 5.000–6.500 K para janela). Peça branca, cetim ou paetê: −0,3 a −0,7. O balanço automático "pula" quando muda a cor da roupa.
- **Lente e ângulo:** 1x como padrão; **2x a 3–4 m com a câmera na altura da cintura/quadril** é a vista de corpo mais fiel; 0,5x só em espaço apertado com a pessoa no centro. Lente reta, pés perto da borda de baixo, nunca de cima para baixo. Leve contra-plongée (câmera 60–80 cm, 5–10° para cima) alonga as pernas. Mesma altura, distância e lente ao comparar tamanhos.
- **Luz:** janela difusa ou softbox de 5.600 K (CRI ≥ 95) a 45°, rebatedor branco do lado oposto; apagar lâmpadas quentes do canto de gravação; nunca misturar temperaturas. Ring light só para fala (reflete em cetim, paetê e espelho).
- **Espelho do provador:** câmera a 30–45° do espelho, espelho limpo, luzes fora do reflexo. O espelho inverte letras e estampas → Espelhar no CapCut.
- **Lista de tomadas por peça (~40 s de bruto, 1 movimento por tomada, 1 s parado no início e no fim):** corpo inteiro de frente · giro 360° (4K60) · costas · perfil · caminhando até a câmera · sentada (comprimento/transparência) · meio corpo · texturas com luz lateral · botões, zíper, forro, bolso, etiqueta · contra a luz (transparência) · **tomada de cor fiel** (peça + cartão cinza ou folha branca, luz do dia, 5 s) · 2–3 combinações de styling · fala da vendedora com lapela (preço, tamanhos, chamada para o WhatsApp) · embalagem.
- **Tomadas para transição de look:** tripé fixo, fita no chão marcando pés e tripé, mesma luz e lente, AE/AF e branco travados, 2 s de sobra antes e depois, gesto repetido igual. Obturador acima de 1/250 deixa giro e chicote "picotados"; 1/60 a 30 fps dá borrão natural.
- **Som:** lapela a um palmo do queixo, fora de paetê/renda/colar; música ambiente da loja **desligada** (direito autoral e impede trocar a trilha); ar-condicionado e ventilador desligados nas falas; teste de 10 s no fone.
- **Transferência sem perda:** cabo (iPhone: Ajustes > Apps > Fotos > Transferir para Mac ou PC > Manter Originais; app Dispositivos Apple no Windows), Google Drive, Quick Share, Google Fotos em "Qualidade original". WhatsApp comprime (se inevitável, enviar como Documento). AirDrop pode converter.
- **Taxa de quadros variável** (áudio escorregando ao longo do clipe): HandBrake → 30 fps, "Constant Framerate", RF 18–20, e reimportar. Conferir com MediaInfo.

## 3. Montagem e ritmo

**Regras de retenção aplicadas à edição**
- Gancho no **quadro 1**: começar pelo momento mais forte (resultado, peça girando, preço, reação). Nada de logo, vinheta ou "oi, gente". Texto do gancho já no primeiro quadro, sem animação lenta de entrada.
- Mudança visual a cada **1–3 s** (corte, punch-in de 110–120%, ângulo, B-roll, texto novo). Exceção: fala emocional segura planos de 4–6 s.
- Re-gancho a cada **5–8 s** em vídeos acima de 15 s ("mas o 3º é o que esgota"). Primeira micro-recompensa até ~5 s. Payoff antes de 90% do vídeo.
- CTA de até 2 s ou sobreposto ao payoff. Sempre que der, final que emenda no início (loop gera replay).
- Fala: cortar silêncios acima de ~0,3 s e muletas ("é…", "tipo"); disfarçar o corte alternando escala 100% e 110–115%. Ritmo de ~2,5–3 palavras/s: 15 s ≈ 35–45 palavras; 30 s ≈ 75–90; 60 s ≈ 150–170.
- Batida: segundos por batida = 60 ÷ BPM (100 BPM = 0,6 s; 120 BPM = 0,5 s = 15 quadros a 30 fps; 128 BPM ≈ 0,47 s). Troca de look a cada 2 batidas (≈1 s) ou a cada compasso (4 batidas). Cortar no transiente ou 1 quadro antes. Trocas rápidas: 100–128 BPM; peças elegantes/festa: 70–90 BPM.
- Duração por objetivo: loop/trend 7–15 s · produto 15–30 s · provador narrado 30–60 s (faixa de maior alcance nos dados de 2026) · ensinar 30–90 s · teto de 3 min quando o objetivo é alcance.
- Moda: cortar "na ação" (giro, passo); ordem que vende: peça no corpo em movimento → detalhe → costas → cores → preço/CTA.

**Procedimento no CapCut**
1. Criar projeto (banner "+ Criar projeto" ou Ctrl+N). Definir 9:16 pelo botão **Proporção** sob o player, ou clicando numa área vazia da timeline → painel Detalhes → Modificar (diálogo não mapeado: conferir na tela) com Proporção de aspecto 9:16 (1080×1920) e 30 fps (ou o fps da captação). A exportação já sai em Rec. 709 SDR.
2. Ctrl+I (ou Mídia > Importar) e colar o caminho da pasta.
3. Arrastar os clipes para a faixa principal (ímã P ligado na montagem), na ordem do roteiro. Shift+Z para ver tudo.
4. Em cada clipe: cursor no início útil → Q; no fim útil → W. ↑/↓ saltam entre cortes; ←/→ quadro a quadro; Shift+←/→ 10 quadros.
5. Ctrl+B divide; ] seleciona tudo à direita do cursor para abrir espaço; V desativa um clipe sem apagar (testar versões).
6. Marcadores (M; Alt+M muda a cor) para gancho, re-ganchos e CTA.
7. Duas passadas: primeiro só a faixa principal (história e ritmo); depois sobreposições, texto, cor e áudio.
8. Clipe horizontal num projeto 9:16: Vídeo > Básico > Tela (fundo desfocado ou cor) ou Escala ≈316% para preencher; ou Reenquadramento automático 💎.

## 4. Efeitos e transições

### 4.1 Orçamento e regras de ouro

| Duração | Efeito-assinatura | Efeitos de apoio | Transições de biblioteca | Efeitos sonoros |
|---|---|---|---|---|
| 7–15 s | 1 | 1 | 0–1 | 2–4 |
| 15–30 s | 1 | 2 | 1–2 | 3–6 |
| 30–60 s | 1 | 2–3 (repetidos, não novos) | 2–3 | 4–8 |

1. Um efeito-assinatura por vídeo; o resto é corte seco. Em vídeo falado, 1–2 transições por minuto. Troca de look na batida é corte seco, não transição de biblioteca.
2. Um reforço por corte de troca de look: flash **ou** tremor **ou** whoosh, não os três.
3. **O produto manda:** nada cobre a peça nem muda sua cor ou caimento; pelo menos um plano com cor real; sem retocar corpo em vídeo de caimento.
4. Intensidades baixas: glitch 20–40%, tremor ~30%, filtros 20–40%, grão 10–30%.
5. Zoom digital até 120–130% em material 1080p; para lupa ou zoom forte, gravar em 4K.
6. No máximo 3 flashes por segundo (fotossensibilidade).
7. Consistência de série: 1–2 fontes, uma cor de destaque, um filtro, uma assinatura sonora, texto sempre no mesmo lugar.
8. Excesso de transições e cor mudando a cada palavra já soam datados; câmera na mão e cara de UGC estão em alta, com corte preciso e texto legível.

### 4.2 Catálogo (como fazer no CapCut 9.5)

Nomes de presets do Curvo, formas de máscara, modos de Mistura e itens da biblioteca vêm de tutoriais e variam por versão: localizar na tela ou pela busca antes de agir. Itens da biblioteca exigem a marca "comercial" para uso da loja (§7); os feitos com ferramentas não.

Procedimentos-base: **quadro-chave** = selecionar clipe → Vídeo > Básico → cursor no início → clicar ◇ do parâmetro → mover cursor → mudar valor (o CapCut cria o 2º quadro-chave); suavizar no painel de quadros-chave (Alt+K). **Efeito** = aba Efeitos → buscar → arrastar para a timeline sobre o trecho → ajustar duração pelas bordas e Força/Velocidade no painel. **Transição** = aba Transições → arrastar para a junção de dois clipes → Duração no painel (deixar sobra de 5–10 quadros nas pontas). **Camada** = arrastar mídia para a faixa acima da principal → Escala/Posição → Mistura (Tela, Sobrepor, Multiplicar) e Opacidade.

| # | Técnica | Quando (moda) | Como / parâmetros |
|---|---|---|---|
| 1 | Punch-in (zoom seco) | Batida, palavra-chave, preço | Ctrl+B na batida e Escala 110–120% no 2º trecho; ou ◇ 100→115% em 3–6 quadros |
| 2 | Zoom lento (Ken Burns) | Luxo, vitrine, tecido, foto | ◇ Escala 100→108–115% em 2–6 s + leve deslocamento para a peça |
| 3 | Zoom 3D / paralaxe de foto | Fotos de ensaio, photo dump | Efeitos: buscar "3D zoom"; manual: foto duplicada, cópia de cima com Remoção automática 100→112%, fundo 100→104% + desfoque leve. Evitar tule, franja, cabelo solto |
| 4 | Transição de zoom | Ligar looks com energia | Transições (buscar "zoom"/"blur") 0,2–0,4 s; manual: A 100→180% nos 5 últimos quadros, B 180→100% nos 5 primeiros + borrão de movimento + whoosh. Máx. 2 por vídeo |
| 5 | Tremor de câmera | Aterrissagem do pulo, drop | Efeito "shake" ~30% por 4–10 quadros; manual: ◇ Posição ±15–30 px a cada 2 quadros + Escala 105% |
| 6 | Rastreio de câmera | Desfile, vídeo horizontal no 9:16 | Vídeo > Básico > Rastreio de câmera 💎 (rosto/corpo) |
| 7 | Texto que segue a peça | Preço acompanhando a saia | Texto selecionado → aba Rastreamento → caixa sobre a peça → iniciar |
| 8 | Speed ramp (velocity) | Giro, desfile, caminhada | Velocidade > Curvo (Montagem, Herói, Bala, Corte de salto, Flash in/out ou Personalizado): aproximação 2–4x, pico 0,3–0,5x, saída 2–3x; pico na batida; travar a rampa antes dos efeitos |
| 9 | Câmera lenta suave | Chiffon, paetê, cabelo, giro | Bruto a 60 fps; Velocidade 0,5x (até 0,25x); "Câmera lenta suave 💎" / Fluxo óptico 💎; exportar a 60 fps. Evitar fala e estampas finas |
| 10 | Reverso / rewind / boomerang | Peça "voando" para a mão, laço que se dá sozinho | Clique direito > Editar > Reverso; rewind = 3x + efeito VHS + som; boomerang = cópia invertida em seguida |
| 11 | Congelar + recorte com contorno | Apresentar o look, fechar com preço | Clique direito > Editar > Congelar (~3 s) → Remover plano de fundo > Remoção automática → contorno branco (Efeitos corpo > Traço, ou efeito "outline") → Entrada "pop" 0,2–0,3 s + obturador |
| 12 | Timelapse | Vitrine, arara, chegada de mercadoria | Velocidade 8–20x, som do clipe desligado, música; Estabilização se foi na mão |
| 13 | Loop perfeito | Reels de 5–12 s, giro | Começar e terminar na mesma pose; cortar no quadro mais parecido (comparar com opacidade 50%); se precisar, fusão de 6–10 quadros |
| 14 | Corte na batida | Trocas de look, novidades | Marcar batidas (M no ritmo, ou marcação automática da música se aparecer) + encaixe N + Ctrl+B em cada marca |
| 15 | Jump cut | Dona falando, dicas | Ctrl+B no início e fim das pausas + Delete; alternar Escala 100%/110% a cada 2–3 cortes; legendas |
| 16 | J-cut / L-cut | Narração sobre B-roll, depoimento | Ctrl+Shift+S (extrair/restaurar áudio) separa o som; puxar o áudio da próxima cena 0,5–1 s para antes do corte (J) ou estender o anterior (L); fade 3–5 quadros. O "Extrair áudio" do clique direito tem selo "[1 uso]" nesta conta: conferir antes |
| 17 | B-roll rápido | Fala cita forro, bolso, etiqueta | Clipes de 1–2 s na faixa de cima, cortados na palavra; som desligado |
| 18 | Match cut | Troca "invisível" de look | B sobre A com opacidade 50% para alinhar escala/posição; voltar a 100% e cortar no meio do movimento |
| 19 | Smash cut | Humor, expectativa × realidade | Ctrl+B; trecho A com Saturação −100 e som baixo; B com o drop da música |
| 20 | Photo dump na batida | Lookbook, "tudo que chegou" | 0,4–0,5 s por foto (120–128 BPM), zoom lento ou 3D em algumas, obturador |
| 21 | Abertura pelo clímax | Quase todo vídeo de venda | Copiar o melhor 0,7–1 s do final para o início + texto grande + flash de 2 quadros ao voltar |
| 22 | Troca de look: pulo | Novidades, "4 looks com 1 saia" | Achar o ápice nos dois clipes (quadro a quadro), Ctrl+B nos dois, juntar; flash 2 quadros + whoosh + tremor de 6 quadros na aterrissagem |
| 23 | Troca: estalo de dedos | Cores e tamanhos disponíveis | Corte no quadro do estalo (pico da onda) + som "pop" + punch-in ou flash |
| 24 | Troca: mão ou peça na lente | Provador, iniciantes | A cortado no 1º quadro todo coberto, B no último coberto; whoosh; tela escura ≤ 3 quadros |
| 25 | Troca: giro | Vestidos, saias, macacões | Corte de costas (~180°), velocidade 1,5–2x no giro, borrão de movimento, whoosh |
| 26 | Troca: jogar a roupa | Trend jovem | Como o #24 usando a peça; ou gravar jogando a peça e aplicar Reverso |
| 27 | Troca: cortina/porta | Provador da loja | Corte quando o corpo some; se não sumir, Mascarar > Linear na borda (pena 3–8) animada com ◇ + som de cortina |
| 28 | Troca estilo game | "Qual look? 1, 2 ou 3" | Fundo + recortes numerados + figurinha de cursor animada + clique + troca (#22/#24) |
| 29 | Chicote (whip pan) | Troca de ambiente/look | Gravado: cortar no meio do borrão; sem gravação: Transições > Deslizar/Desfocar 0,2–0,3 s |
| 30 | Objeto passando (máscara) | Troca sem pulo | Corte quando o objeto cobre 100%; avançado: Mascarar > Linear com ◇ a cada 1–2 quadros, pena 5–15 |
| 31 | Flash / strobe | Drops, trocas, "sessão de fotos" | Transições: buscar "flash" (2 quadros a 0,2 s); manual: Exposição +100 por 2 quadros; ≤ 3/s |
| 32 | Glitch / RGB | Jovem, Y2K, "PROMO", contagem | Efeitos > Falha a 20–40% por 4–8 quadros; nunca em luxo/festa elegante |
| 33 | Borrão de movimento | Sobre giros, chicotes, rampas | Vídeo > Básico > Borrão de movimento 💎 ou efeito; 4–10 quadros, nunca em close de estampa |
| 34 | Giro 3D / cubo | Frente → costas da peça | Transições > 3D (~0,3 s); 1 vez por vídeo |
| 35 | Fusão / fade | Luxo, noiva, finais | Transições > Básico, 0,4–0,8 s |
| 36 | Desfoque in/out | Clean girl, "sonho" | Transições > Desfocar ~0,3 s |
| 37 | Tela dividida 2×2 | "1 peça, 4 looks", cores | Clipes em faixas; Escala 50% e Posições (±270, ±480); respiro: Escala 48–49% sobre Tela de cor |
| 38 | Antes e depois (cortina) | Styling básico → completo (nunca corpo) | "Depois" em cima; Mascarar > Linear girada 90°, pena 0–3; ◇ da borda esquerda à direita em 1–1,5 s + linha branca + whoosh + rótulos |
| 39 | Clone | "3 cores, 1 vestido", "eu indecisa" | Tripé e exposição travados; tomadas empilhadas; Mascarar > Linear/Retângulo com borda em área calma, pena 10–20 |
| 40 | Texto atrás da pessoa | Capas, "FESTA", "VERÃO" | Vídeo (faixa 1) + texto (faixa 2) → selecionar os dois → Criar clipe composto (Alt+G) → importar o vídeo de novo acima → Remoção automática; silenciar a cópia |
| 41 | PiP / reação | Dona reage, detalhe + plano geral | Escala 30–40%, alto à esquerda (base e direita ficam sob a interface), máscara retangular arredondada |
| 42 | Troca de fundo | Fundo liso de catálogo | Remoção automática ou Chroma key + fundo na faixa de baixo; igualar temperatura/exposição |
| 43 | Barras de cinema, polaroid, revista | Editorial, photo dump | Efeitos/Stickers: buscar "cinema", "polaroid", "revista"; ou formas + ◇ |
| 44 | Scrapbook / colagem recortada | "Monte seu look" jovem | Fundo de papel + recortes com contorno + Entrada "pop" na batida (0,15–0,25 s) + fita/rabisco + som de papel |
| 45 | Grão / vintage / VHS | Bastidores nostálgicos, retrô | Efeitos > Retrô a 10–30% + filtro Retrô 20–40%; evitar em vídeo que vende pela cor |
| 46 | Vazamento de luz / bokeh | Verão, festa, transição suave | Efeitos > Luz, ou vídeo de overlay com Mistura "Tela" 50–80% |
| 47 | Desfoque de fundo | Cliente com a loja cheia atrás | Tela > Desfoque (preenchimento) ou cópia de baixo desfocada + cópia de cima recortada |
| 48 | Spotlight / vinheta | Destacar a peça na arara | Ajuste > Vinheta leve; ou cópia com Exposição −40 + Mascarar > Círculo (pena 30–50) seguindo a peça |
| 49 | Color pop | "O vermelho da estação" | Ajuste > HSL: Saturação −100 em todas as cores menos a da peça (não serve para peça laranja/nude/marrom) |
| 50 | Brilho / sparkle | Paetê, strass, formatura | Efeitos > Brilho, ou figurinha animada com rastreamento; nunca sobre o rosto |
| 51 | Efeitos corpo (contorno neon) | Festa, Carnaval | Efeitos corpo > Linhas brilhantes/Traço; evitar em luxo e vídeo de caimento |
| 52 | Tipografia cinética | Listas, títulos, CTA | 1–4 palavras por tela, Animação > Entrada (máquina de escrever, pop, subir); máx. 2 tipos de animação |
| 53 | Preço surgindo | Depois de mostrar a peça inteira | Texto com fundo ou figurinha de etiqueta; Entrada "pop" 0,2–0,3 s; 2–3 s na tela; som "pop"; nunca sobre a peça |
| 54 | Setas e círculos | Bolso, fenda, zíper invisível | Stickers > Ênfase (ou buscar "arrow", "circle"); 1–2 s + clique |
| 55 | Lupa no tecido | Renda, bordado, costura | Cópia do clipe em cima com Escala 200–250% + Mascarar > Círculo (pena 0–5) sobre o detalhe + anel de lupa; gravar em 4K |
| 56 | Contador "LOOK 1/4" | Listas e séries | Texto que muda a cada look, no alto à esquerda; barra de progresso = retângulo com ◇ de escala horizontal 0→100% |
| 57 | Efeitos sonoros | Transições, preço, detalhes | Áudio > Efeitos sonoros (buscar em inglês: "whoosh", "pop", "click", "camera shutter", "riser"); pico no 1º quadro do evento; fade de 2–3 quadros. Para o Instagram da loja: SFX com marca "comercial" ou de fora (Meta Sound Collection, Pixabay, Epidemic) — ver §7 |
| 58 | ASMR / som do produto | Embalagem, textura, zíper | Gravar a 20–30 cm; som do objeto +3 a +6 dB, música −15 a −25 dB ou nenhuma |

### 4.3 Estilos por objetivo e por estética

| Objetivo | Estrutura | Ritmo | Técnicas-base | Sinal de sucesso |
|---|---|---|---|---|
| Vender | Peça no corpo + benefício ou preço (0–1,5 s) → prova (movimento, caimento, detalhe) → oferta (preço, parcelas, tamanhos) → CTA WhatsApp | corte a cada 1–2 s; 15–30 s | 1, 7, 17, 21, 53–55, 57 | Conversas, envios, salvamentos |
| Inspirar | Imagem forte → sequência estética na música → assinatura | 1–3 s por plano; 10–25 s | 2, 9, 35, 43, 45–46 | Salvamentos, compartilhamentos |
| Divertir | Situação reconhecível em 0,5 s ("POV:") → virada → payoff | muito rápido; 7–15 s | 10, 15, 19, 39, 57 | Envios por DM, comentários |
| Ensinar | Promessa ("3 jeitos de…") → passos numerados → resumo + "salva" | 2–4 s por passo; 20–60 s | 15–17, 37, 54, 56 | Salvamentos, retenção até o fim |

| Estética | Cor | Tipografia | Transições | Peças |
|---|---|---|---|---|
| Luxo/minimalista | neutra, pretos ricos, leve dessaturação | serifada fina ou sans espaçada; pouco texto | corte lento, fusão, match cut | festa, alfaiataria, acessórios |
| Jovem/trend | saturada, contraste alto | sans pesada em caixa alta | velocity, flash, glitch, chicote, 3D | croppeds, shorts, saias, jeans |
| Clean girl | bege, branco, rosado, luz natural | sans minimal em caixa baixa | desfoque in/out, fusão curta | linho, camisas, pantalonas, neutros |
| Festa/brilho | preto, dourado, tons joia | serifada dourada ou sans condensada | strobe na batida, flash dourado, giro | vestidos de festa, macacões, bijuterias |
| Casual/dia a dia | natural e quente | sans simples + legenda | corte seco, jump cut, mão na lente | conjuntos, blusas, jeans |

### 4.4 Receitas prontas para moda

- **R1 Troca de look na batida** (12–20 s): cold open com o último look + "4 looks com 1 saia" → 4 trocas (pulo/estalo) a cada 2 batidas com "LOOK 1/4" e punch-in → último look em câmera lenta → preço.
- **R2 Provador com preço** (15–25 s): cortina abre → giro → lupa no tecido → seta no bolso → "R$229,99 · 3x sem juros" + legenda com destaques + CTA WhatsApp.
- **R3 Uma peça, três formas** (20–35 s): grade 2×2 com a peça e os 3 looks → cada look com jump cuts, legenda e contador → grade de novo + "salva para lembrar".
- **R4 Detalhe que vende** (10–15 s): zoom lento + câmera lenta no tecido + ASMR → lupa + texto mínimo "forrado · não amassa · P ao GG" → fusão para a peça inteira + preço discreto.
- **R5 Photo dump da coleção** (8–12 s): 15–20 fotos na batida, zoom 3D em 3, polaroid, obturador em cada foto, flash nas fotos-chave.
- **R6 Vitrine cinematográfica** (10–20 s): timelapse da montagem → barras de cinema + zoom lento → grão 10% + vazamento de luz → "NOVA COLEÇÃO" atrás da modelo.
- **R7 Antes e depois do styling** (8–12 s): básico → cortina → completo + whoosh → lista das peças com preço.
- **R8 Clone indecisa** (10–15 s): 3 clones, um em cada cor, "conversando" com J/L-cut → "qual eu levo? comenta 1, 2 ou 3".
- **R9 Congela e recorta** (6–10 s): desfile → congela no melhor ângulo → recorte com contorno sobre papel → preço com pop e obturador.
- **R10 Velocity de passarela** (8–15 s): caminhada com speed ramp + borrão → tremor no pico → strobe + brilho no drop.
- **R11 Embalando seu pedido** (15–30 s): ASMR com jump cuts, close do laço e do adesivo, texto mínimo, loop.
- **R12 Escolha o look** (10–15 s): tela de game → cursor com clique → troca → "comenta o número".

## 5. Texto e legendas

- **Legendas automáticas:** aba Legendas > Legendas automáticas → Idioma de origem: Português (ou Detectar) → gerar (processa na nuvem). Corrigir nomes de peça, preços, tamanhos e "Maceió"; estilizar uma e aplicar a todas; modelos com destaque de palavra em Legendas > Modelos > Palavra. Exportar SRT é 💎 (conta é Pro).
- **Parâmetros de legenda:** 2–4 palavras por bloco, até 2 linhas, ≤ 32–42 caracteres por linha, ≤ 17 caracteres por segundo (tempo mínimo = caracteres ÷ 17); não separar artigo e substantivo nem nome e sobrenome. Sans bold 56–72 px, branco com contorno preto de 4–8 px ou caixa preta a 60–80%; palavra-chave na cor de destaque (contraste ≥ 3:1). Posição centro-baixo, acima da faixa da interface (y≈950–1250 no Reels).
- **Estilo Hormozi:** Montserrat Black / The Bold Font, caixa alta, branco com contorno preto 5–8 px, destaque amarelo #F7C204 (ou verde), 3–5 palavras por linha, 3–5 destaques e 2–3 emojis por vídeo. No Reels, versões mais contidas (pílula colorida, minimalista em caixa baixa) tendem a render melhor que no TikTok.
- **Gancho na tela:** 3–7 palavras, sans bold de 80–110 px, em y 300–700, entra em ≤ 0,5 s e fica ≥ 1,5–2 s.
- **Legibilidade:** peso 700–900; contraste ≥ 4,5:1 (medir no pior ponto do fundo); tempo na tela ≈ 1 s + 0,3 s por palavra (mínimo 1,5 s); nada abaixo de ~42 px no quadro 1080×1920.
- **Preço na tela:** formato da loja **"R$229,99"** (cifrão colado) + parcelas pela regra da Ferreira: até R$149,99 em 2x; até R$319,98 em 3x; acima disso em 5x, sem juros. À vista (3% de desconto) só quando a cliente pergunta. Preço sempre igual ao do cadastro.
- **Texto para fala:** selecionar um texto → aba "Conversão de texto em fala" → voz em português → gerar (cria faixa de áudio sincronizada). Voz real da vendedora costuma convencer mais; TTS serve para rascunho e chamadas curtas.
- **Tamanho de fonte** no CapCut é escala relativa: calibrar com um PNG-régua 1080×1920 (textos de 44/66/99/148 px + faixas de zona segura) numa faixa de cima com opacidade 50%, desligado antes de exportar.
- Salvar os estilos da marca em "Salvar como predefinição" (Texto > Seus > Predefinições).

## 6. Cor (fidelidade da peça é regra de venda)

- **Ordem:** exposição e contraste → balanço de branco (Temperatura azul↔amarelo, Matiz verde↔magenta) → saturação → HSL só na cor que desviou → look/LUT a 30–60% → conferir pele e peça.
- **No CapCut:** aba Ajuste do clipe, ou "Ajuste personalizado" (aba Ajuste > Adicionar ajuste) como camada sobre todos os clipes; LUT em Ajuste > LUT (.cube/.3dl); salvar a predefinição da marca.
- **Regras:** nunca filtro que mude o matiz da peça; filtros a 20–40%; uma tomada neutra (cor real) quando o look for estilizado; comparar a tela com a peça sob luz do dia antes de exportar; nome exato da cor na legenda ("verde-oliva", "terracota"); aviso quando a luz engana ("pessoalmente é mais fechado").
- LED barato puxa para o verde → Matiz +3 a +8 (magenta). Pele: não saturar o laranja além de +5/+10; pele acinzentada → só luminância do laranja +3 a +8.
- Clipe HDR num projeto SDR fica lavado: manter SDR Rec.709, baixar realces/exposição e exportar um teste.

| Look | Quando | Valores iniciais |
|---|---|---|
| Clean / luminoso | Produto, provador, lançamento | Exposição +3 a +8, Contraste −5, Realces −10, Sombras +8, Brancos +5, Saturação 0 a +5, Temperatura 0 a +3, Nitidez +5 |
| Quente / dourado | Linho, praia, terrosos | Temperatura +8 a +15, Matiz +2, Saturação +3, HSL Laranja S −5, Azul S −10, Esmaecer +5 |
| Editorial | Alfaiataria, P&B, festa | Contraste +12 a +20, Saturação −10 a −20, Clareza +10, Pretos −10, Realces −15, HSL Verde S −30, Amarelo S −15 (não usar na tomada de cor fiel) |
| Filme | Campanha, bastidores | Esmaecer +10 a +20, Granulação 10–20, Saturação −10, ponto preto 0→10 na curva, Vinheta 10–15 |

## 7. Áudio

- **Ordem no clipe de voz:** Reduzir ruído → Melhorar/aprimorar voz → Normalizar volume → (equalização) → música → efeitos sonoros. Se a voz ficar robótica, voltar a redução um pouco.
- **Níveis:** voz com picos de −6 a −3 dB; música 12–18 dB abaixo da voz (clipe de música a −15/−20 dB durante a fala, −6/−8 dB nos trechos só de música); mix final ≈ −14 LUFS (algumas fontes: −16), pico real ≤ −1 dBTP. **Atenção:** o CapCut do usuário está com "Nível de volume desejado: Padrão (−23 LUFS)" em Configurações > Editar; normalizar com esse alvo deixa o áudio ~9 dB abaixo de −14. Subir o ganho do clipe (ou trocar o alvo, se o dono quiser; opções não verificadas) e medir o arquivo exportado (ex.: Youlean Loudness Meter).
- **Ducking:** quadros-chave de volume na música, 4 pontos por fala (descidas/subidas de 0,3–0,5 s).
- **Equalização de voz** (se disponível): corte abaixo de 80–100 Hz; −2 a −4 dB em 200–400 Hz se soar "caixa"; +2 a +3 dB em 2–5 kHz para presença; −2 a −4 dB em 5–8 kHz se o "s" agredir.
- **Efeitos sonoros:** whoosh (pico no corte), pop (1–2 quadros antes do texto), obturador (congelar), swish de tecido (giro), clique (detalhe), riser + impacto (revelação); 10–20 dB abaixo da voz; no máximo um a cada 2–3 s; uma "assinatura sonora" fixa por série.
- **Silêncio estratégico:** cortar a música 0,5–1 s antes de revelar look, preço ou promoção e voltar no impacto.
- **Licença dos itens da biblioteca do CapCut** (Contrato de Licença de Materiais, 22/01/2026): músicas, efeitos sonoros, efeitos, transições, figurinhas, fontes e modelos **sem** a marca "comercial"/"uso comercial" são só para uso pessoal; os marcados como "uso duplo" permitem marketing online limitado; **um único item não comercial restringe o vídeo inteiro** a uso pessoal. Músicas "Sons" = pessoal; "Sons comerciais" valem só em CapCut, TikTok e TikTok for Business (não no Instagram). O Pro não amplia direito comercial. Ferramentas de edição (cortes, quadros-chave, máscaras, velocidade, ajustes de cor, texto com fonte própria ou do Google Fonts) não dependem dessa licença: quando der o mesmo resultado, preferir o efeito feito à mão. Decisão final sobre usar itens da biblioteca é do dono.
- **Música no Instagram da loja:** exportar sem música do CapCut e colocar o áudio pelo próprio Instagram, ou usar faixa baixada da Meta Sound Collection (Meta Business Suite) ou licenciada (Epidemic Pro, Pixabay). Para sincronia perfeita, editar com uma faixa-guia de mesmo BPM. Quando o dono já definiu os áudios (ex.: lista de áudios dos stories), seguir o padrão dele; o risco conhecido de "áudio original" de terceiros com música famosa é o post ficar sem som — mencionar em uma linha só se for relevante. Reel com "Áudio indisponível": opção "Substituir áudio" mantém as visualizações. Instagram e TikTok com músicas diferentes → exportar `_IG` e `_TT`.

## 8. Exportação

| Destino | Resolução | fps | Codec / formato | Taxa de bits (Personalizado) |
|---|---|---|---|---|
| Reels | 1080P (1080×1920) | 30 (ou o da captação; 60 só se captado a 60 com câmera lenta) | H.264 / mp4 | 16.000 Kbps (faixa 12.000–20.000; teto da API da Meta: 25 Mbps) |
| Stories (até 60 s por story) | 1080P | 30 | H.264 / mp4 | 10.000–12.000 Kbps (limite ~100 MB) |
| TikTok | 1080P | 30 ou 60 | H.264 / mp4 | Superior ou 20.000–30.000 |
| Feed 4:5 / vídeo em carrossel | 1080×1350 | 30 | H.264 / mp4 | 12.000–16.000 |
| Master interno | resolução do projeto | igual à captação | HEVC / mp4 | Superior |

- Espaço de cores Rec.709 SDR. Áudio AAC 48 kHz quando houver opção.
- Tamanho: Mbps ≤ (limite em MB × 8) ÷ duração em s, com margem para o áudio.
- **Emulador (BlueStacks):** entregar `.mp4` (o `.mov` não aparece na galeria do Instagram no emulador).
- Sem marca d'água, sem clipe final de modelo, sem logo de outra rede; nunca baixar vídeo publicado para repostar. Não aceitar "remover recursos Pro" sem revisar.
- Exportar também um master limpo (sem texto e sem música) quando o vídeo puder virar versões (TikTok, stories, carrossel).
- Depois: abrir o arquivo exportado e conferir duração, sincronia, som e tamanho; ver no celular com e sem som.

## 9. Checklist antes de exportar

- [ ] Gancho no quadro 1 (visual + texto + fala contam a mesma promessa); nada de logo ou saudação.
- [ ] Mudança visual a cada 1–3 s; sem silêncio morto; re-gancho a cada 5–8 s se > 15 s.
- [ ] Texto, rosto e produto dentro do retângulo seguro (x 80–920, y 280–1400); nada sob os botões da direita.
- [ ] Legendas revisadas (acentos, nome da peça, preço, tamanhos, código); ≤ 2 linhas.
- [ ] Preço e parcelas conferidos com o cadastro; só cores e tamanhos com estoque.
- [ ] Cor da peça fiel (comparada com a peça real); nenhum efeito sobre a peça.
- [ ] Efeitos dentro do orçamento; ≤ 3 flashes/s.
- [ ] Voz limpa e acima da música; música com direito de uso no destino (ou nenhuma, para colocar no app).
- [ ] Itens da biblioteca do CapCut (efeitos, SFX, figurinhas, fontes, modelos) com marca "comercial", ou efeito equivalente feito com ferramentas.
- [ ] Volume final conferido (o alvo padrão do app é −23 LUFS; mirar ≈ −14).
- [ ] Final em loop ou CTA claro de até 2 s.
- [ ] Preset de exportação correto; arquivo aberto e conferido depois.

## 10. Especificações e zonas seguras (quadro 1080×1920)

- **Retângulo universal seguro** (Reels, Stories e TikTok orgânicos): **x 80–920, y 280–1400**. Para anúncio Meta, baixar o limite inferior para y 1250.
- **Reels:** topo ~250–270 px; base ~480 px no orgânico (anúncio Meta: ~670 px, 35%); coluna de botões à direita ~130–180 px; esquerda ~60 px. Legendas embutidas em y≈950–1250.
- **Stories:** evitar os 270 px de cima e os 380 px de baixo para texto e figurinhas (as fontes variam de 250 a 380 na base; usar 380). Figurinha de link num espaço reservado em y≈1380–1530, ou no terço central quando não cobrir a peça.
- **TikTok:** topo ~160 px; base 270–480 px (conservador 420–480); direita ~100–140 px.
- **Capa na grade do perfil (3:4):** só aparece y 240–1680; título em y 850–1250, x 90–990, 110–160 px.
- **Plataforma:** Reels de 3 s a 3 min (acima de 3 min não há recomendação a não seguidores); stories de até 60 s por item. Recebem menos distribuição: marca d'água de outro app, baixa resolução, bordas, vídeo sem som, vídeo só de texto e conteúdo duplicado.

## 11. Automação de rascunho (só informação)

O CapCut internacional 9.x ainda salva o rascunho em JSON aberto (`draft_info.json`/`draft_content.json`, tempos em microssegundos). Ferramentas comunitárias (capcut-mcp, VectCutAPI, pyCapCut, capcut-cli) montam esqueletos de rascunho com o CapCut fechado; nenhuma exporta MP4 e não há API oficial. Uso possível: lotes repetitivos (mesma estrutura, mídia diferente), com backup da pasta do projeto antes; acabamento e exportação sempre pela interface.
