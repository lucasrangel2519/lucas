# Autopost: TikTok + Instagram do Lucas (vendedor VW Autobel)

Este sistema **posta sozinho** no seu TikTok e no seu Instagram, nos horários da agenda.
Ele roda de graça no GitHub Actions: a cada 15 minutos confere a agenda e publica o que estiver na hora.

**Rotina diária** (arquivo `agenda/semana-01.yaml`):

| Horário | Onde | O quê |
|---|---|---|
| 09:00 | Instagram | Post 1: carrossel (3 fotos) |
| 12:30 | Instagram | Post 2: foto |
| 17:30 | Instagram | Stories (vídeo) |
| 19:00 | TikTok | Vídeo do dia |
| 20:00 | Instagram | Post 3: Reels (mesmo vídeo do TikTok) |

**O seu trabalho:** gravar ou fotografar e colocar os arquivos na pasta do dia.
As ideias e roteiros de cada dia estão em [`conteudo/plano-de-conteudo.md`](conteudo/plano-de-conteudo.md).

---

## Passo 1: preparar as contas (5 min)

- **Instagram:** no app, vá em *Configurações → Tipo de conta e ferramentas → Mudar para conta profissional* e escolha **Criador de conteúdo** ou **Empresa**. A API do Instagram não publica em conta pessoal.
- **TikTok:** qualquer conta funciona.

## Passo 2: criar o app do Instagram (Meta), uma vez só

1. Entre em <https://developers.facebook.com/apps>, clique em **Criar app** e escolha o caso de uso **"Gerenciar mensagens e conteúdo no Instagram"**.
2. No painel do app: **Instagram → Configuração da API com login do Instagram**.
3. Em *Configurar login comercial do Instagram*, coloque em **URIs de redirecionamento OAuth**: `https://github.com/`
4. Copie o **ID do app do Instagram** e a **Chave secreta do app do Instagram**.
5. Em **Funções do app → Funções**, adicione a sua conta @lucas_volkswagenautobel como **Testador do Instagram** e aceite o convite no Instagram (*Configurações → Apps e sites → Convites de testador*).
   Com o app em modo de desenvolvimento, você já consegue postar **na sua própria conta**, sem revisão da Meta.

## Passo 3: criar o app do TikTok, uma vez só

1. Entre em <https://developers.tiktok.com/>, faça login e vá em **Manage apps → Connect an app**.
2. Adicione os produtos **Login Kit** e **Content Posting API**. Dentro do Content Posting API, ligue o **Direct Post**.
3. Em *Scopes*, marque `user.info.basic` e `video.publish`.
4. Em *Login Kit → Redirect URI*, coloque `https://github.com/`
5. Preencha os dados do app (nome, ícone, descrição, links de termos e privacidade; pode ser o link deste repositório) e clique em **Submit for review**.
6. Copie o **Client key** e o **Client secret**.

> ⚠️ **Importante sobre o TikTok:** até o TikTok **aprovar (auditar)** o app, os vídeos postados pela API ficam como **"Só eu"** (privados).
> O sistema já trata isso: posta como privado e, depois da aprovação, basta mudar `TIKTOK_PRIVACY_LEVEL` para `PUBLIC_TO_EVERYONE`.
> Enquanto a aprovação não sai, você pode abrir o vídeo no app e mudar para público com 2 toques.

## Passo 4: conectar as contas (no computador, uma vez só)

```bash
git clone https://github.com/lucasrangel2519/lucas.git && cd lucas
pip install -r requirements.txt
cp .env.example .env      # abra o .env e preencha IG_APP_ID, IG_APP_SECRET, TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET

python -m autopost auth-instagram   # abre um link: autorize e cole o endereço de volta
python -m autopost auth-tiktok      # mesma coisa
python -m autopost testar           # confere se as duas contas estão conectadas
```

Cada comando `auth-*` mostra no final os valores que você deve guardar (`IG_USER_ID`, `IG_ACCESS_TOKEN`, `TIKTOK_REFRESH_TOKEN`).

## Passo 5: ligar o piloto automático no GitHub

No repositório, vá em **Settings → Secrets and variables → Actions**.

**Secrets** (aba *Secrets*, botão *New repository secret*):

| Nome | Valor |
|---|---|
| `IG_USER_ID` | gerado no passo 4 |
| `IG_ACCESS_TOKEN` | gerado no passo 4 |
| `TIKTOK_CLIENT_KEY` | do app do TikTok |
| `TIKTOK_CLIENT_SECRET` | do app do TikTok |
| `TIKTOK_REFRESH_TOKEN` | gerado no passo 4 |
| `GH_PAT` | um [token do GitHub](https://github.com/settings/personal-access-tokens/new) com acesso só a este repositório e a permissão **Secrets: Read and write**. Serve para o sistema renovar os tokens sozinho. |

**Variables** (aba *Variables*), todas opcionais:

| Nome | Para quê |
|---|---|
| `MEDIA_BASE_URL` | Endereço público das fotos (veja abaixo) |
| `TIKTOK_PRIVACY_LEVEL` | `SELF_ONLY` (padrão) ou `PUBLIC_TO_EVERYONE` depois da aprovação |
| `TIKTOK_BRAND_ORGANIC` | `true` para marcar os vídeos como "promovendo meu negócio" |
| `DRY_RUN` | `true` para testar sem postar de verdade |

Depois, junte este branch na `main` (o GitHub só roda agendamentos na branch principal) e pronto.
Para testar na hora: **Actions → Postagem automatica → Run workflow**, com comando `testar`.

### Sobre as fotos (MEDIA_BASE_URL)

- **Vídeos** (Reels, Stories, TikTok): o sistema envia direto do repositório. Não precisa configurar nada.
- **Fotos** do Instagram: a Meta só aceita foto por **link público**.
  - Se o repositório for **público**, já funciona sozinho (usa o link `raw.githubusercontent.com`).
  - Se for **privado**, hospede as fotos em algum lugar público (Cloudflare R2, Google Cloud Storage etc.) e coloque o endereço em `MEDIA_BASE_URL`, ou escreva o link `https://...` direto no campo `arquivo` da agenda.

---

## Dia a dia: como usar

1. Grave e fotografe seguindo o plano do dia.
2. Coloque os arquivos em `media/AAAA-MM-DD/` com estes nomes:
   - `carrossel-1.jpg`, `carrossel-2.jpg`, `carrossel-3.jpg`
   - `post.jpg`
   - `stories.mp4` (vertical 9:16, até 60 s)
   - `tiktok.mp4` (vertical 9:16; o Reels usa o mesmo vídeo)
3. Envie para o GitHub. Pelo celular dá pelo site do GitHub: *Add file → Upload files*.

Se o arquivo não estiver lá na hora marcada, o post **espera** e sai assim que o arquivo chegar (até 12 h de atraso).
O que já foi postado fica registrado em `agenda/publicados.json`, então nada é postado duas vezes.
Se der erro, o sistema tenta 3 vezes e o GitHub te avisa por e-mail.

Para mudar horários e legendas, edite `agenda/semana-01.yaml`. Para a próxima semana, crie um `agenda/semana-02.yaml` no mesmo formato.
Quer conferir se está tudo certo? Rode `python -m autopost validar`.

### Formato de um item da agenda

```yaml
- id: 2026-11-12-tiktok          # único
  quando: 2026-11-12 19:00       # horário de Brasília
  plataforma: tiktok             # tiktok | instagram
  tipo: video                    # tiktok: video | instagram: post, carrossel, reels, stories
  arquivo: media/2026-11-12/tiktok.mp4   # ou "arquivos:" (lista) no carrossel
  legenda: "Texto + #hashtags"
```

## Limites das plataformas

- Instagram: até 100 posts pela API a cada 24 h, com Stories incluídos. Nossa rotina usa 4.
- Stories pela API **não aceitam** figurinhas, enquetes, links nem texto. Coloque o texto já no próprio vídeo. Para enquete e caixinha de perguntas, poste o Stories pelo app.
- TikTok: vídeos privados até a aprovação do app. O TikTok também limita quantos posts por dia uma conta pode fazer pela API (o limite varia por conta).
- Música em alta do TikTok não entra por API. Para usar um som viral, coloque a música no vídeo antes (CapCut) ou poste aquele vídeo pelo app.

## Desenvolvimento

```bash
pip install pytest && python -m pytest -q
```

Código em `autopost/`: `instagram.py` (API do Instagram), `tiktok.py` (Content Posting API), `scheduler.py` (agenda) e `cli.py` (comandos).
