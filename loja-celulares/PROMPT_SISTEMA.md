# Prompt completo do sistema

Copie **todo o texto abaixo da linha** e cole no Claude (ou em outra IA de programação) para que ela construa o sistema completo, do zero, igual ao que está nesta pasta.

---

Você é um desenvolvedor sênior. Construa um **sistema de gestão (ERP) completo para uma loja de celulares, acessórios e assistência técnica no Brasil**. O foco principal do dono é **controle de estoque e valor do estoque**: quanto dinheiro está investido em cada produto, onde está e há quanto tempo está parado. Toda a interface, mensagens, relatórios e documentação devem estar em **português do Brasil**, com valores em **R$** (formato `R$ 1.234,56`) e datas no formato `dd/mm/aaaa`.

## 1. Requisitos técnicos

- **Backend:** Python 3.9+ usando **somente a biblioteca padrão** (sem Flask, sem pip install). Banco **SQLite** num único arquivo `dados/estoque.db`, que fica fora do git.
- **Dois modos de execução, com a mesma lógica:**
  - `python3 servidor.py` usa o servidor embutido (`http.server`, com threads) em `http://127.0.0.1:8080`. Opções: `--host 0.0.0.0` (rede da loja), `--porta`, `--banco`, `--demo` (cria dados de exemplo).
  - `wsgi.py` expõe `application`, para hospedar na internet (PythonAnywhere). Atrás do proxy, o IP real do cliente vem de `X-Real-IP` ou `X-Forwarded-For`, e o HTTPS é detectado por `X-Forwarded-Proto`.
- **Frontend:** HTML, CSS e JavaScript puros (sem frameworks e sem CDN, para funcionar offline), como página única com rotas por `#hash`. Arquivos: `static/index.html`, `static/css/estilo.css`, `static/js/app.js`, `static/js/modulos.js`, `static/js/estoque.js`.
- **API JSON** em `/api/...`. POST e PUT exigem `Content-Type: application/json`. Corpo de no máximo 2 MB. Erros vêm como `{"erro": "mensagem em português"}` com o status HTTP correto.
- **Migração automática:** ao iniciar, criar as tabelas que faltarem e adicionar colunas novas com `ALTER TABLE`, sem perder dados de versões anteriores.
- **Atalhos:** `iniciar-windows.bat` (abre o navegador e roda `py` ou `python`) e `iniciar.sh`.
- **Testes:** `tests/test_servidor.py` com `unittest`, sobe o servidor numa porta livre e cobre todos os fluxos abaixo.

## 2. Segurança

- Senhas com **PBKDF2-SHA256**, 200 mil iterações e sal aleatório.
- No primeiro uso, criar o usuário `admin` com senha `admin123` e **obrigar a troca no primeiro login**. Enquanto a senha não for trocada, toda a API responde 403, exceto `/api/me`, `/api/me/senha`, `/api/logout`, `/api/meta` e `/api/login`. A nova senha precisa ter **pelo menos 8 caracteres**, não pode ser igual à atual e não pode ser uma senha óbvia (admin123, 12345678...).
- Usuário criado pelo admin, ou com senha redefinida pelo admin, também é obrigado a trocar a senha no primeiro acesso.
- **Sessão** por cookie `HttpOnly; SameSite=Strict`, válida por 12 horas. No banco, guardar **apenas o hash SHA-256 do token**. Sob HTTPS, o cookie recebe `Secure` e a resposta envia `Strict-Transport-Security`.
- Bloquear o login por 5 minutos depois de 10 tentativas erradas do mesmo IP.
- Cabeçalhos em todas as respostas: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: same-origin` e CSP `default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:`.
- Arquivos estáticos protegidos contra *path traversal*.
- No frontend, escapar todo texto antes de inserir no HTML.
- **Perfis:**
  - **Administrador:** acesso total. Vê custos, lucro, financeiro e valor do estoque. Cadastra e edita produtos, cancela lançamentos, faz ajustes e inventário, gerencia usuários, configurações e backup.
  - **Vendedor:** vendas, orçamentos, ordens de serviço, entradas, caixa e clientes. **Nunca vê custo, lucro, contas a pagar nem valor do estoque.**

## 3. Cadastros

- **Produtos:**
  - Campos: código/código de barras (SKU, único e opcional), nome, marca, modelo, categoria (Smartphone, Acessório, Peça, Tablet, Smartwatch, Outro), cor, armazenamento, condição (Novo, Seminovo, Vitrine, Recondicionado), **controla IMEI** (sim/não), preço de custo (custo médio, atualizado pelo sistema), preço de venda, estoque mínimo, **localização na loja** (ex.: "Vitrine 1", "Cofre"), ativo/inativo.
  - O nome é sugerido automaticamente a partir de marca + modelo + armazenamento + cor.
  - Ao escolher Smartphone, Tablet ou Smartwatch, "controla IMEI" vem marcado.
  - Não permitir mudar "controla IMEI" com estoque maior que zero.
  - Excluir produto que já tem movimentação apenas o **desativa**.
  - O estoque **nunca** é editado direto: só muda por movimentações.
- **Clientes** e **fornecedores:** nome, CPF/CNPJ, telefone/WhatsApp, e-mail e observação. Busca por nome, documento ou telefone. A ficha mostra o histórico de compras ou fornecimentos e o total. Não excluir quem tem movimentações.
- **Usuários:** nome, login (letras, números, ponto, hífen, sublinhado), perfil e ativo. O admin não pode desativar nem rebaixar a si mesmo.
- **Configurações:**
  - Dados da loja: nome, CNPJ, endereço, telefone, rodapé do comprovante.
  - Garantia padrão da OS em dias (90).
  - Validade do orçamento em dias (7).
  - Termo de garantia impresso na OS.
  - **Saldo inicial do financeiro** (dinheiro + banco quando começou a usar o sistema).
  - Opção **"exigir caixa aberto para vender e receber"**.
  - Botão de **backup** que baixa uma cópia do SQLite (`backup-estoque-AAAAMMDD-HHMM.db`).

## 4. Controle de IMEI (celulares)

- IMEI tem 15 dígitos, com validação do **dígito verificador (Luhn)**.
- Cada aparelho tem status: disponível, vendido, baixado ou cancelado.
- **Cada aparelho guarda o seu próprio custo** (tabela `imeis` com a coluna `custo`). Isso é essencial para seminovos comprados de clientes, em que cada unidade custa diferente.
- **Entrada:** a quantidade é igual ao número de IMEIs informados. Não aceitar IMEI que já está disponível em estoque nem IMEI repetido no mesmo lançamento. IMEI que já saiu (devolução ou troca) volta a ficar disponível e mantém o custo que tinha.
- **Saída:** só IMEIs disponíveis daquele produto. O custo da saída é a **soma do custo real dos aparelhos escolhidos**.
- O custo médio de um produto com IMEI é a média do custo dos aparelhos disponíveis.
- O valor em estoque de um produto com IMEI é a **soma exata do custo de cada aparelho disponível**.
- **Rastreio de IMEI:** situação atual, produto, e a linha do tempo de todas as movimentações (de qual fornecedor veio, para qual cliente foi vendido, datas e valores).

## 5. Movimentações de estoque (entradas e saídas)

- **Motivos de entrada:** Compra, Devolução de cliente, Troca (aparelho recebido), Retorno de garantia, Ajuste de inventário (só admin), Outro.
- **Motivos de saída:** Venda, Devolução ao fornecedor, Perda/Avaria, Envio para garantia, Uso interno, Ajuste de inventário (só admin), Ordem de serviço (gerado só pelo sistema, nunca lançado à mão), Outro.
- Cada movimentação tem: data/hora, usuário, cliente ou fornecedor, forma de pagamento, nº do documento ou nota, subtotal, desconto (só em venda), total, observação, nº de parcelas e itens.
- Cada item guarda: produto, quantidade, valor unitário, **custo unitário**, **custo total exato da linha** e a lista de IMEIs.
- **Tudo numa única transação** (`BEGIN IMMEDIATE`): validar, gravar a movimentação, atualizar o estoque, os IMEIs, o custo médio e gerar o financeiro. Se algo falhar, nada é gravado.
- **Nunca deixar o estoque ficar negativo.** Ao validar o saldo, considerar o mesmo produto repetido em mais de uma linha.
- **Custo médio ponderado** a cada Compra, nos produtos sem IMEI: `(estoque × custo atual + qtd × valor) / (estoque + qtd)`.
- Na compra de produtos com IMEI, é possível informar um **custo diferente para cada aparelho**.
- **Cancelamento** (só admin, com justificativa obrigatória): estorna o estoque, os IMEIs, o custo médio e o financeiro, e registra quem cancelou, quando e por quê.
  - Bloquear o cancelamento de uma entrada se parte dela já saiu do estoque.
  - Bloquear o cancelamento de uma saída se o IMEI teve movimentação depois.
  - Saída gerada por OS só pode ser cancelada pela própria OS.
- **Comprovante imprimível:** dados da loja, nº, data, motivo, cliente, itens com IMEI, desconto, total, forma de pagamento, parcelas, quem atendeu e rodapé.

## 6. Vendas (PDV)

- Tela de venda rápida:
  - Campo de busca grande que aceita **nome, código de barras ou IMEI**. Enter adiciona o produto, e funciona com leitor de código de barras. A busca tem autocompletar navegável pelas setas.
  - Buscar por IMEI já adiciona o produto com aquele aparelho marcado.
  - Itens com quantidade e valor editáveis. Para celulares, uma lista de IMEIs disponíveis para marcar, com filtro.
- Campos laterais: motivo, cliente (com botão para cadastrar na hora), forma de pagamento (Dinheiro, PIX, Cartão de débito, Cartão de crédito, Crediário, Outro), desconto em R$, documento e observação.
- Totais ao vivo: itens, subtotal, desconto, total e **lucro estimado (só admin)**.
- **Crediário:** exige cliente identificado. Pede nº de parcelas e 1º vencimento, e gera as parcelas em contas a receber.
- Venda à vista gera um lançamento já recebido.
- Depois de finalizar, abre o comprovante, com opção de imprimir ou fazer nova venda.
- Pode carregar os itens, o cliente e o desconto de um orçamento (`#/saida?orcamento=ID`). Ao finalizar, marca o orçamento como convertido.

## 7. Orçamentos

- Cliente (opcional), itens, desconto, validade (padrão das configurações) e condições.
- Situações: em aberto, aprovado, recusado, virou venda.
- Imprimir, **enviar pelo WhatsApp** (link `wa.me` com o texto dos itens e o total) e **converter em venda**.
- Orçamento convertido não pode ser editado. Se a venda for cancelada, o orçamento volta para "aprovado".

## 8. Ordens de serviço (assistência técnica)

- **Campos:** cliente (obrigatório), aparelho, cor, IMEI (opcional, validado), senha ou padrão de desbloqueio (não sai na impressão), acessórios deixados, defeito relatado, laudo técnico, técnico, previsão, garantia (dias), observação interna.
- **Serviços:** descrição + valor.
- **Peças do estoque:** produtos sem IMEI. As peças **só saem do estoque na entrega**.
- Desconto e total.
- **Situações:** Aberta, Em análise, Aguardando aprovação, Aprovada, Aguardando peça, Em reparo, Pronta para retirada, Entregue, Cancelada. Cada mudança fica no histórico com data, usuário e anotação.
- **Entregar e receber:** pede a forma de pagamento (crediário com parcelas). Gera a saída das peças (motivo "Ordem de serviço") e o lançamento em contas a receber (categoria "Serviços (OS)"), tudo na mesma transação.
- **Cancelar:** qualquer usuário cancela uma OS ainda não entregue. Só o admin cancela uma OS entregue, e nesse caso as peças voltam ao estoque e o financeiro é cancelado.
- Botão **"Avisar no WhatsApp"** quando a OS fica pronta.
- **Via impressa:** dados da loja, cliente, aparelho, defeito, laudo, serviços, peças, total, termo de garantia e linhas de assinatura.
- Destacar as OS atrasadas (previsão vencida).

## 9. Financeiro (só admin, exceto o caixa)

- **Contas a receber e a pagar** (tabela `financeiro`): descrição, categoria, valor, vencimento, data do pagamento, forma, parcela ("2/3"), cliente ou fornecedor, ligação com a movimentação ou OS, observação, cancelado.
  - Categorias a receber: Venda de produtos, Serviços (OS), Outras receitas.
  - Categorias a pagar: Compra de mercadorias, Aluguel, Energia / água / internet, Salários e comissões, Impostos e taxas, Taxas de cartão, Marketing, Manutenção, Outras despesas.
- **Lançamentos gerados automaticamente:**
  - Venda gera a receber (crediário em parcelas mensais).
  - Compra à vista gera a pagar já paga.
  - Compra **a prazo** gera parcelas a pagar.
  - Entrega de OS gera a receber.
  - As parcelas dividem o valor com o ajuste dos centavos na última, e os meses são somados sem pular data (31/01 vira 28/02).
- **Lançamentos manuais** (despesas e receitas), com opção de dividir em parcelas ou **repetir o mesmo valor todo mês** (despesa fixa).
- Ações: baixar (data + forma), estornar a baixa, editar (só em aberto), excluir (só os manuais).
- Lista com abas A receber / A pagar e filtros Em aberto, Vencidos, Pagos e Todos, período de vencimento e busca. Totais de vencido e do que vence em 7 dias. Exportar CSV.
- **Caixa** (todos os usuários):
  - Abertura com troco inicial. Um caixa aberto por vez.
  - Sangria e suprimento com motivo.
  - Resumo: recebido por forma de pagamento e **dinheiro esperado na gaveta** = troco + recebido em dinheiro − pago em dinheiro + suprimentos − sangrias.
  - Fechamento informando o valor contado. Mostra a diferença (sobra ou falta) ao vivo.
  - Histórico dos caixas.
  - Indicador "Caixa aberto/fechado" no menu.

## 10. Valor do estoque (tela principal de estoque, só admin)

- **Indicadores:**
  - Valor investido (custo).
  - Valor de venda.
  - Lucro potencial e margem.
  - **Dinheiro parado há mais de 90 dias:** produtos com idade média acima de 90 dias e sem venda nos últimos 90 dias.
  - **Idade média do estoque**, ponderada pelo valor.
  - **Cobertura em dias:** valor em estoque ÷ custo vendido por dia nos últimos 90 dias.
  - Comprado no mês, custo do que saiu em vendas e perdas/baixas do mês.
- **Gráfico de linha** da evolução do valor investido nos últimos 90 dias. Calculado pelo histórico: entradas (custo) − saídas (custo), acumulado dia a dia.
- **Onde está o dinheiro:** valor e % por categoria, por marca e por condição (novo × seminovo).
- **Idade do estoque** por faixas (até 30, 31 a 60, 61 a 90, 91 a 180, mais de 180 dias), com unidades e valor. A idade de cada unidade vem da sua entrada: para IMEI, a entrada exata; para os demais, pelo método PEPS (as compras mais recentes formam o saldo atual).
- **Curva ABC** pelo valor investido: A até 80% acumulado, B até 95%, C o restante.
- **Tabela detalhada por produto:** classe ABC, quantidade, custo médio, valor investido, % do estoque, valor de venda, lucro potencial, margem, idade média, dias sem vender, vendidos em 90 dias e cobertura.
  - Filtros: com estoque, parados há mais de 90 dias, classe A, abaixo do mínimo, zerados, todos.
  - Filtro por categoria e várias ordenações.
  - Linha de totais, exportação CSV e impressão.

## 11. Ficha do produto

- Indicadores: em estoque × mínimo, preço de venda e margem, **valor investido** e **lucro potencial**.
- Dados do produto e IMEIs em estoque.
- **Unidades em estoque:**
  - Para celulares: cada IMEI com a data de entrada (link para a nota), o fornecedor, há quantos dias está na loja, o **custo daquele aparelho** e o lucro se for vendido pelo preço atual.
  - Para os demais produtos: os lotes de compra (PEPS) que formam o saldo.
- **Ficha de estoque (kardex):** cada movimentação com entrada, saída, saldo em quantidade, custo unitário, valor do movimento, **saldo em R$** e custo médio depois do movimento. Exportar CSV.
- O vendedor vê apenas o histórico simples, sem valores de custo.

## 12. Inventário (contagem física, só admin)

- Iniciar com abrangência de todo o estoque ou de uma categoria. Um inventário aberto por vez.
- Ao iniciar, guardar uma fotografia do esperado de cada produto (quantidade, IMEIs e custo).
- **Tela de contagem:**
  - Campo para o **leitor de código de barras**: cada leitura do código soma 1. Para celulares, cada IMEI lido marca o aparelho como encontrado. IMEI de fora do inventário gera aviso.
  - Também dá para digitar a quantidade ou marcar e desmarcar IMEIs. Salva a cada alteração.
  - Ordenada pela localização. Filtros: todos, não contados, com diferença, conferidos.
  - Diferença por produto em unidades e em R$.
  - Indicadores: contados x de y, faltas (un. e R$), sobras (un. e R$) e resultado.
- **Finalizar:** validar tudo antes de gravar. Lançar uma saída "Ajuste de inventário" com as faltas (inclusive os IMEIs não encontrados) e uma entrada com as sobras, com o documento "Inventário #N". Produtos não contados ficam como estão. Depois disso, o inventário não pode ser alterado.
- Cancelar inventário aberto sem mexer no estoque.
- Folha de contagem pronta para imprimir.

## 13. Painel (tela inicial)

- Indicadores:
  - Vendas de hoje.
  - Faturamento do mês e ticket médio.
  - Lucro bruto do mês e margem (admin).
  - Unidades em estoque.
  - Valor investido em estoque, com link para a análise (admin).
  - Abaixo do mínimo e zerados.
  - OS em andamento, prontas e atrasadas.
  - Serviços entregues no mês.
  - A receber e a pagar vencidos e dos próximos 7 dias (admin).
  - Situação do caixa.
- Gráfico de barras das vendas dos últimos 30 dias.
- Mais vendidos do mês, últimas movimentações e lista de reposição.

## 14. Relatórios (todos com exportação CSV e impressão)

Seletor de período com atalhos: hoje, 7 dias, 30 dias, este mês, mês passado, este ano, e datas livres.

- **Vendas:**
  - Faturamento, nº de vendas, ticket médio, itens, lucro bruto, margem e descontos.
  - Gráfico por dia e barras por forma de pagamento.
  - Tabelas por produto, vendedor, categoria, marca e dia.
  - A receita de cada item tem o **desconto da venda rateado proporcionalmente**, e o lucro usa o **custo real** de cada item.
- **Financeiro e DRE (admin):**
  - Recebido, pago, saldo do período, saldo acumulado (a partir do saldo inicial), em aberto a receber e a pagar.
  - Gráfico de barras duplas de entradas × saídas por dia.
  - **DRE simplificado:** receita de vendas + receita de OS − custo das mercadorias vendidas − custo das peças das OS = lucro bruto, − despesas operacionais pagas (sem compra de mercadoria) = resultado.
  - Valores por categoria e fluxo diário com o previsto a receber e a pagar.
- **Ordens de serviço:** abertas no período, entregues, faturamento (serviços e peças), prazo médio de entrega, em andamento por situação, por técnico e serviços mais realizados.
- **Estoque:** posição valorizada por produto e por categoria, e lista de reposição com sugestão de compra (2× o mínimo − o atual).
- **Entradas e saídas:** resumo por motivo, giro por produto (entradas, vendidas, outras saídas, custo das perdas, estoque atual) e estoque parado no período.
- **Rastrear IMEI.**

## 15. Interface

- Layout com menu lateral escuro agrupado por área:
  - Painel; **Nova venda (PDV)** em destaque.
  - Vendas e serviços: Orçamentos, Ordens de serviço.
  - Estoque: Valor do estoque, Produtos, Entrada/compra, Movimentações, Inventário.
  - Financeiro: Caixa, Contas a pagar e receber, Relatórios.
  - Cadastros: Clientes, Fornecedores, Usuários, Configurações.
  - Itens só de admin ficam escondidos para o vendedor.
- Visual limpo com cartões, cores por variáveis CSS e **tema claro e escuro automático**. Indicadores com valores tabulares, etiquetas coloridas por tipo e situação, avisos ("toasts") e janelas modais para formulários.
- **Responsivo:**
  - No celular, o menu vira gaveta e não pode haver rolagem horizontal na página (só dentro das tabelas).
  - Campos com fonte de 16px em telas de toque, para o Safari não dar zoom.
  - Respeitar as áreas seguras do iPhone (`env(safe-area-inset-*)`).
- **Instalável como app (PWA):** `manifest.webmanifest`, ícones PNG de 180, 192 e 512 px, `apple-touch-icon` e meta tags `apple-mobile-web-app-*`, para abrir em tela cheia pela tela de início do iPhone e como app no Chrome do computador.
- **Impressão:** esconder menu e botões. Comprovantes, OS, orçamentos e relatórios saem limpos.
- Tela de login e tela obrigatória de **"Crie sua senha"** no primeiro acesso.

## 16. Dados de exemplo (`--demo`)

Criar dados para demonstrar todas as telas:
- 2 fornecedores e 5 clientes.
- 12 produtos com localização, incluindo um **iPhone seminovo com 3 aparelhos de custos diferentes** e uma capa parada há 210 dias.
- Compras ao longo de 45 dias com reposições e vendas aleatórias diárias.
- Uma perda, despesas fixas pagas no mês passado e em aberto neste mês, uma venda no crediário com parcela vencida, 4 OS em situações diferentes, um orçamento em aberto, um caixa aberto e saldo inicial no financeiro.
- Usuário extra: `vendedor` / `vendedor123`.

## 17. Hospedagem e documentação

- `README.md` explicando como iniciar no Windows, Linux e macOS, as funcionalidades e o backup.
- `HOSPEDAGEM.md` com o passo a passo para **PythonAnywhere** (plano gratuito):
  - criar a conta;
  - `git clone` no console Bash;
  - criar o web app em *Manual configuration*;
  - arquivo WSGI de 3 linhas importando `wsgi.application`;
  - Force HTTPS e Reload;
  - renovar todo mês com "Run until 1 month from today";
  - instalar no iPhone pelo Safari (Compartilhar → Adicionar à Tela de Início);
  - cadastrar funcionários, atualizar com `git pull` e fazer backup;
  - tabela de problemas comuns, com o comando para redefinir a senha do admin.

## 18. Critérios de aceite

1. `python3 -m unittest discover -s tests` passa, cobrindo: login e proteção, Luhn, venda e custo médio, estoque insuficiente, fluxo de IMEI, permissões do vendedor, relatórios, cadastros e backup, financeiro gerado por venda e compra, OS, orçamento convertido, caixa, custo por aparelho e valor do estoque, inventário, senha obrigatória, modo WSGI e arquivos estáticos sem travessia.
2. Num navegador, sem erros no console: fazer uma venda com IMEI e desconto, uma compra a prazo, abrir e entregar uma OS no crediário, converter um orçamento, abrir e fechar o caixa, contar um inventário com o leitor e finalizar. Tudo também numa tela de 390 px de largura, sem rolagem horizontal.
3. Um banco criado por uma versão anterior abre sem perder dados.
