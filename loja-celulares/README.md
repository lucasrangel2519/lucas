# Sistema de gestão para loja de celulares

Sistema de gestão (ERP) para loja de celulares, acessórios e assistência técnica. Cobre **vendas (PDV)**, **orçamentos**, **ordens de serviço**, **estoque**, **compras**, **financeiro** (contas a pagar e a receber, caixa, fluxo de caixa e DRE) e **relatórios**.
Funciona no navegador, no computador do balcão e também no celular ou tablet da loja.

- Não precisa instalar nada além do **Python 3.9+**: não tem dependências nem mensalidade.
- Os dados ficam num único arquivo no seu computador (`dados/estoque.db`).
- Funciona sem internet.

## Como iniciar

**Windows:** instale o Python em <https://www.python.org/downloads/> (marque *Add Python to PATH*) e dê dois cliques em `iniciar-windows.bat`.

**Linux / macOS:**

```bash
python3 servidor.py
```

Abra **http://localhost:8080** e entre com:

| Usuário | Senha |
|---|---|
| `admin` | `admin123` |

> Troque a senha logo no primeiro acesso, em **Minha conta** (canto inferior esquerdo).

Opções:

```bash
python3 servidor.py --demo            # cria produtos, vendas e clientes de exemplo para conhecer o sistema
python3 servidor.py --host 0.0.0.0    # libera o acesso para outros computadores/celulares da rede da loja
python3 servidor.py --porta 9000      # usa outra porta
python3 servidor.py --banco loja.db   # usa outro arquivo de banco
```

Com `--host 0.0.0.0`, os outros aparelhos da mesma rede Wi-Fi acessam por `http://IP-DO-COMPUTADOR:8080`.
Não exponha o sistema direto na internet.

## O que o sistema faz

### Valor do estoque (foco principal)
- **Valor investido** (quanto dinheiro está parado em produtos, a preço de custo), **valor de venda** e **lucro potencial** do estoque inteiro e de cada produto.
- **Custo real de cada aparelho**: em celulares, o custo é guardado por IMEI. Isso vale principalmente para seminovos comprados de clientes, em que cada unidade custa diferente. O valor do estoque e o lucro de cada venda usam o custo daquele aparelho, não uma média.
- **Onde está o dinheiro**: valor por categoria, por marca e por condição (novo ou seminovo), com a % de cada um.
- **Curva ABC**: os poucos produtos que concentram 80% do dinheiro (A), os seguintes (B) e os de pouco valor (C).
- **Idade do estoque**: quanto tempo cada unidade está na loja (até 30, 31 a 60, 61 a 90, 91 a 180 e mais de 180 dias). Também mostra quanto dinheiro está **parado há mais de 90 dias** sem venda.
- **Cobertura**: quantos dias o estoque dura no ritmo de vendas dos últimos 90 dias.
- **Evolução do valor investido** nos últimos 90 dias, além do que foi comprado, do custo do que saiu em vendas e das perdas do mês.
- Tabela detalhada por produto com filtros (parados, classe A, abaixo do mínimo, zerados), várias ordenações e exportação para Excel.

### Ficha do produto
- **Kardex**: cada entrada e saída com o saldo em quantidade, o saldo em R$ e o custo médio depois de cada movimento.
- **Unidades em estoque**: para celulares, cada IMEI com a data de entrada, o fornecedor, há quantos dias está na loja, quanto custou e quanto dá de lucro se for vendido pelo preço atual. Para os demais produtos, mostra os lotes de compra que formam o saldo.

### Inventário (contagem física)
- Conte todo o estoque ou só uma categoria por vez.
- Use o **leitor de código de barras**: cada leitura soma 1. Nos celulares, cada IMEI lido marca o aparelho como encontrado, e o sistema avisa se aparecer um IMEI que não estava cadastrado.
- Faltas e sobras aparecem na hora, em unidades e em R$.
- Ao finalizar, o sistema lança os **ajustes de inventário** e o estoque fica igual ao contado.
- Folha de contagem pronta para imprimir, ordenada pela **localização** dos produtos na loja.

### Produtos e estoque
- Cadastro com marca, modelo, armazenamento, cor, condição (novo, seminovo, vitrine, recondicionado), categoria, código de barras/SKU, preço de custo, preço de venda e estoque mínimo.
- **Controle por IMEI** para aparelhos: cada celular entra e sai com o seu IMEI. O sistema confere os 15 dígitos e o dígito verificador, então pega erro de digitação.
- **Custo médio** atualizado automaticamente a cada compra.
- Alerta de estoque abaixo do mínimo e lista de reposição.
- A busca aceita nome, marca, código de barras ou IMEI. Funciona com leitor de código de barras.

### Entradas
Compra de fornecedor (com número da nota), devolução de cliente, troca (aparelho recebido), retorno de garantia e ajuste de inventário.

### Saídas e vendas
- Tela de venda rápida: busca o produto, escolhe o IMEI, aplica desconto, escolhe a forma de pagamento (dinheiro, PIX, débito, crédito, crediário) e finaliza.
- Outras saídas: devolução ao fornecedor, perda/avaria, envio para garantia, uso interno e ajuste.
- **Não deixa vender o que não tem em estoque** nem vender o mesmo IMEI duas vezes.
- Comprovante pronto para imprimir, com os dados da loja.
- Cancelamento com justificativa: o estoque é estornado automaticamente e fica registrado quem cancelou e por quê.

### Orçamentos
- Monte o orçamento com os produtos, o desconto, a validade e as condições.
- Imprima ou envie pelo WhatsApp com um clique.
- Marque como aprovado ou recusado.
- **Converta em venda**: os itens, o cliente e o desconto já vêm preenchidos no PDV.

### Ordens de serviço (assistência técnica)
- Abertura com cliente, aparelho, IMEI, senha/padrão, acessórios deixados, defeito relatado, técnico e previsão.
- Laudo técnico, serviços e **peças do estoque**. As peças só saem do estoque quando o aparelho é entregue.
- Andamento por situação: aberta, em análise, aguardando aprovação, aguardando peça, em reparo, pronta e entregue. Cada mudança fica registrada no histórico.
- Botão **Avisar no WhatsApp** quando o aparelho fica pronto.
- Via impressa com termo de garantia e espaço para assinatura.
- Na entrega, o valor vai para o financeiro, à vista ou no crediário.

### Financeiro
- **Contas a receber**:
  - Toda venda gera o lançamento automaticamente.
  - No **crediário**, a venda é dividida em parcelas mensais.
  - Tem baixa e estorno de pagamentos e alerta de vencidos.
- **Contas a pagar**:
  - Compras a prazo geram as parcelas.
  - Despesas fixas (aluguel, energia, salários...) podem se repetir todo mês.
- **Caixa**:
  - Abertura com troco, sangria e suprimento.
  - No fechamento, você informa o dinheiro contado e o sistema mostra a diferença.
  - Opcionalmente, o sistema pode exigir caixa aberto para vender.
- **Fluxo de caixa** diário (realizado e previsto) e **DRE simplificado**: receita de vendas e serviços, custo das mercadorias e peças, despesas e resultado.

### Relatórios (com exportação para Excel/CSV e impressão)
- **Financeiro e DRE:** recebido, pago, saldo, contas em aberto, fluxo diário e despesas por categoria.
- **Ordens de serviço:** faturamento, prazo médio de entrega, OS em andamento por situação, por técnico e serviços mais feitos.
- **Vendas:** faturamento, ticket médio, lucro bruto, margem e descontos, com quebras por dia, por produto, por forma de pagamento, por vendedor, por categoria e por marca.
- **Estoque:** posição atual valorizada a preço de custo e de venda, por categoria, e lista de reposição.
- **Entradas e saídas:** resumo por motivo, giro por produto, custo das perdas e estoque parado.
- **Rastrear IMEI:** mostra de qual fornecedor o aparelho veio, para quem foi vendido e quando. Útil para garantia.

### Usuários e segurança
- **Administrador:** acesso total. Vê custo, lucro e o financeiro, cadastra produtos, cancela lançamentos e faz ajustes.
- **Vendedor:** faz vendas, orçamentos, ordens de serviço, entradas, caixa e clientes. Não vê custo, lucro nem contas a pagar.
- Senhas guardadas com hash (PBKDF2). A sessão expira em 12 horas. Depois de várias senhas erradas, o login é bloqueado por alguns minutos.

### Backup
Em **Configurações → Baixar backup agora**. Lá também ficam o saldo inicial do financeiro, a garantia padrão da OS, a validade dos orçamentos e o termo impresso na OS. Guarde a cópia fora do computador (pen drive ou nuvem).
Para restaurar, pare o sistema, substitua `dados/estoque.db` pela cópia e inicie de novo.

## Testes

```bash
python3 -m unittest discover -s tests -v
```

## Estrutura

```
servidor.py           servidor web + API + banco SQLite (Python puro)
static/index.html     interface
static/js/app.js      telas: painel, PDV, entrada, produtos, relatórios...
static/js/modulos.js  telas: orçamentos, ordens de serviço, financeiro e caixa
static/js/estoque.js  telas: valor do estoque, ficha (kardex) e inventário
static/css/estilo.css visual (tema claro/escuro, celular e impressão)
tests/                testes automatizados
dados/estoque.db      seu banco de dados (criado no primeiro uso, fora do git)
```
