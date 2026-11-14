# Sistema de estoque para loja de celulares

Controle de **estoque**, **entradas**, **saídas/vendas** e **relatórios** para loja de celulares e acessórios.
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

### Relatórios (com exportação para Excel/CSV e impressão)
- **Vendas:** faturamento, ticket médio, lucro bruto, margem e descontos, com quebras por dia, por produto, por forma de pagamento, por vendedor, por categoria e por marca.
- **Estoque:** posição atual valorizada a preço de custo e de venda, por categoria, e lista de reposição.
- **Entradas e saídas:** resumo por motivo, giro por produto, custo das perdas e estoque parado.
- **Rastrear IMEI:** mostra de qual fornecedor o aparelho veio, para quem foi vendido e quando. Útil para garantia.

### Usuários e segurança
- **Administrador:** acesso total, vê custo e lucro, cadastra produtos, cancela lançamentos e faz ajustes.
- **Vendedor:** registra vendas, entradas e clientes, mas não vê custo nem lucro.
- Senhas guardadas com hash (PBKDF2). A sessão expira em 12 horas. Depois de várias senhas erradas, o login é bloqueado por alguns minutos.

### Backup
Em **Configurações → Baixar backup agora**. Guarde a cópia fora do computador (pen drive ou nuvem).
Para restaurar, pare o sistema, substitua `dados/estoque.db` pela cópia e inicie de novo.

## Testes

```bash
python3 -m unittest discover -s tests -v
```

## Estrutura

```
servidor.py           servidor web + API + banco SQLite (Python puro)
static/index.html     interface
static/js/app.js      telas: painel, venda, entrada, produtos, relatórios...
static/css/estilo.css visual (tema claro/escuro, celular e impressão)
tests/                testes automatizados
dados/estoque.db      seu banco de dados (criado no primeiro uso, fora do git)
```
