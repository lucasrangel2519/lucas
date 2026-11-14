# Colocar o sistema na internet e usar no iPhone

Com este passo a passo o sistema fica num endereço como **https://seunome.pythonanywhere.com**. Você abre esse endereço no Safari do iPhone e ele vira um ícone na tela de início, como um app. O mesmo endereço funciona no computador e no celular de quem trabalha com você.

Usamos o **PythonAnywhere**:
- **Plano gratuito:** é preciso clicar em um botão uma vez por mês para manter o site ligado (passo 6).
- **Plano pago (Developer, US$ 10 por mês):** dispensa esse cuidado.

> Dica: faça os passos 1 a 5 **no computador** se puder. É possível fazer pelo iPhone, mas a tela é pequena. Depois de pronto, o uso no dia a dia é todo pelo iPhone.

---

## 1. Criar a conta (2 min)

1. Acesse **https://www.pythonanywhere.com** e toque em **Pricing & signup**.
2. Escolha **Create a Beginner account** (gratuita).
3. Escolha um **nome de usuário**. Ele vira o endereço do sistema. Por exemplo, `lojadolucas` gera `https://lojadolucas.pythonanywhere.com`.
4. Confirme o e-mail que o PythonAnywhere enviar.

## 2. Copiar o sistema para o servidor (2 min)

1. No painel, abra a aba **Consoles** e clique em **Bash**.
2. Na tela preta, cole este comando e tecle Enter:

```bash
git clone -b claude/kind-darwin-u0dqys https://github.com/lucasrangel2519/lucas.git
```

3. Quando terminar, digite `exit` e feche o console.

## 3. Criar o site (3 min)

1. Abra a aba **Web** e clique em **Add a new web app**. Depois clique em **Next**.
2. Escolha **Manual configuration** (não escolha Flask nem Django).
3. Escolha a versão do Python **mais nova** da lista. Depois clique em **Next**.
4. Na página do site, procure a seção **Code** e clique no link do **WSGI configuration file**. Ele termina em `_wsgi.py`.
5. **Apague todo o conteúdo** desse arquivo e cole no lugar o texto abaixo, **trocando `SEU_USUARIO` pelo seu nome de usuário**:

```python
import sys
sys.path.insert(0, "/home/SEU_USUARIO/lucas/loja-celulares")
from wsgi import application
```

6. Clique em **Save**, que fica no canto de cima.

## 4. Ativar o HTTPS (1 min)

Ainda na aba **Web**, procure a seção **Security** e ligue **Force HTTPS**. Assim tudo trafega com cadeado, inclusive a sua senha.

## 5. Ligar o site

1. Na aba **Web**, clique no botão verde **Reload**.
2. Abra **https://SEU_USUARIO.pythonanywhere.com**.
3. Entre com o usuário **admin** e a senha **admin123**.
4. O sistema pede na hora uma **senha nova**, com pelo menos 8 caracteres. Anote essa senha num lugar seguro.

Pronto, o sistema está no ar.

## 6. Manter o site ligado (plano gratuito)

No plano gratuito, o site desliga sozinho depois de **1 mês** se não for renovado. **Seus dados não são apagados**: o site só para até você religar.

Para renovar:
1. Uma vez por mês, entre em **pythonanywhere.com**.
2. Na aba **Web**, clique em **Run until 1 month from today**.

Para não esquecer, crie um lembrete mensal no iPhone. Se preferir não se preocupar com isso, troque para o plano **Developer** (US$ 10 por mês) em *Account*.

---

## Instalar no iPhone (como app)

1. Abra o endereço do sistema no **Safari**. Precisa ser o Safari, não o Chrome.
2. Toque no botão **Compartilhar** (o quadrado com a seta para cima).
3. Role para baixo e toque em **Adicionar à Tela de Início**. Depois toque em **Adicionar**.
4. O ícone **Estoque** aparece na tela do iPhone. Ele abre em tela cheia, sem a barra do Safari.

O login fica salvo por 12 horas. Depois disso, o sistema pede a senha de novo.

## Cadastrar funcionários

Em **Usuários**, crie um login para cada pessoa com o perfil **Vendedor**. O vendedor não vê custos, lucro nem o financeiro. Cada um cria a própria senha no primeiro acesso. **Não compartilhe a senha do administrador.**

## Atualizar o sistema quando houver melhorias

1. Abra **Consoles → Bash** e rode:

```bash
cd ~/lucas && git pull
```

2. Na aba **Web**, clique em **Reload**.

Os dados da loja ficam em `lucas/loja-celulares/dados/estoque.db` e **não são afetados** pela atualização.

## Backup (importante)

O banco de dados fica no servidor. Pelo menos uma vez por semana:
1. Entre como administrador e vá em **Configurações → Baixar backup agora**.
2. No iPhone, o arquivo vai para o app **Arquivos**. Guarde também uma cópia no iCloud ou no Google Drive.

Se um dia precisar restaurar, peça ajuda: basta enviar o arquivo `.db` de volta para a pasta `dados` pelo menu **Files** do PythonAnywhere.

## Problemas comuns

| O que aparece | O que fazer |
|---|---|
| "Something went wrong" / erro 500 | Na aba **Web**, abra o **Error log** e confira se o `SEU_USUARIO` no arquivo WSGI está certo. Depois clique em **Reload**. |
| "Coming soon" / site desligado | O mês expirou. Clique em **Run until 1 month from today** e em **Reload**. |
| Esqueci a senha do admin | Abra **Consoles → Bash** e rode o comando abaixo. A senha volta a ser `admin123` e o sistema pede uma nova no próximo login. |

```bash
cd ~/lucas/loja-celulares && python3 -c "import servidor as s; c=s.conectar('dados/estoque.db'); c.execute(\"UPDATE usuarios SET senha_hash=?, trocar_senha=1, ativo=1 WHERE login='admin'\", (s.hash_senha('admin123'),)); c.commit(); print('ok')"
```
