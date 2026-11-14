#!/usr/bin/env python3
"""Sistema de controle de estoque para loja de celulares.

Sem dependências externas: usa só a biblioteca padrão do Python 3.9+.

    python3 servidor.py                 # abre em http://127.0.0.1:8080
    python3 servidor.py --host 0.0.0.0  # libera para outros computadores da rede da loja
    python3 servidor.py --demo          # cria dados de exemplo (só se o banco estiver vazio)
"""
import argparse
import datetime as dt
import hashlib
import hmac
import json
import mimetypes
import os
import re
import secrets
import sqlite3
import sys
import tempfile
import threading
import time
import traceback
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
DB_PADRAO = os.path.join(BASE_DIR, "dados", "estoque.db")
SESSAO_HORAS = 12
COOKIE = "sessao_estoque"

CATEGORIAS = ["Smartphone", "Acessório", "Peça", "Tablet", "Smartwatch", "Outro"]
CONDICOES = ["Novo", "Seminovo", "Vitrine", "Recondicionado"]
MOTIVOS = {
    "entrada": ["Compra", "Devolução de cliente", "Troca (aparelho recebido)",
                "Retorno de garantia", "Ajuste de inventário", "Outro"],
    "saida": ["Venda", "Devolução ao fornecedor", "Perda/Avaria", "Envio para garantia",
              "Uso interno", "Ajuste de inventário", "Ordem de serviço", "Outro"],
}
MOTIVOS_ADMIN = ["Ajuste de inventário"]
MOTIVOS_INTERNOS = ["Ordem de serviço"]  # gerados pelo sistema, não lançados à mão
CATEGORIAS_FIN = {
    "receber": ["Venda de produtos", "Serviços (OS)", "Outras receitas"],
    "pagar": ["Compra de mercadorias", "Aluguel", "Energia / água / internet", "Salários e comissões",
              "Impostos e taxas", "Taxas de cartão", "Marketing", "Manutenção", "Outras despesas"],
}
STATUS_OS = ["Aberta", "Em análise", "Aguardando aprovação", "Aprovada", "Aguardando peça", "Em reparo",
             "Pronta para retirada", "Entregue", "Cancelada"]
STATUS_OS_FINAIS = ["Entregue", "Cancelada"]
STATUS_ORC = ["aberto", "aprovado", "recusado", "convertido"]
PAGAMENTOS = ["Dinheiro", "PIX", "Cartão de débito", "Cartão de crédito", "Crediário", "Outro"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS usuarios (
    id INTEGER PRIMARY KEY,
    nome TEXT NOT NULL,
    login TEXT NOT NULL UNIQUE COLLATE NOCASE,
    senha_hash TEXT NOT NULL,
    perfil TEXT NOT NULL CHECK (perfil IN ('admin', 'vendedor')),
    ativo INTEGER NOT NULL DEFAULT 1,
    criado_em TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessoes (
    token TEXT PRIMARY KEY,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    expira_em TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS config (chave TEXT PRIMARY KEY, valor TEXT);
CREATE TABLE IF NOT EXISTS fornecedores (
    id INTEGER PRIMARY KEY,
    nome TEXT NOT NULL,
    documento TEXT, telefone TEXT, email TEXT, observacao TEXT,
    criado_em TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS clientes (
    id INTEGER PRIMARY KEY,
    nome TEXT NOT NULL,
    documento TEXT, telefone TEXT, email TEXT, observacao TEXT,
    criado_em TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS produtos (
    id INTEGER PRIMARY KEY,
    codigo TEXT UNIQUE,
    nome TEXT NOT NULL,
    marca TEXT, modelo TEXT,
    categoria TEXT NOT NULL,
    cor TEXT, armazenamento TEXT,
    condicao TEXT NOT NULL DEFAULT 'Novo',
    controla_imei INTEGER NOT NULL DEFAULT 0,
    preco_custo REAL NOT NULL DEFAULT 0,
    preco_venda REAL NOT NULL DEFAULT 0,
    estoque_minimo INTEGER NOT NULL DEFAULT 0,
    estoque_atual INTEGER NOT NULL DEFAULT 0 CHECK (estoque_atual >= 0),
    ativo INTEGER NOT NULL DEFAULT 1,
    criado_em TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS movimentacoes (
    id INTEGER PRIMARY KEY,
    tipo TEXT NOT NULL CHECK (tipo IN ('entrada', 'saida')),
    motivo TEXT NOT NULL,
    data TEXT NOT NULL,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    fornecedor_id INTEGER REFERENCES fornecedores(id),
    cliente_id INTEGER REFERENCES clientes(id),
    forma_pagamento TEXT,
    documento TEXT,
    subtotal REAL NOT NULL DEFAULT 0,
    desconto REAL NOT NULL DEFAULT 0,
    total REAL NOT NULL DEFAULT 0,
    observacao TEXT,
    cancelada INTEGER NOT NULL DEFAULT 0,
    cancelada_em TEXT,
    cancelada_por INTEGER REFERENCES usuarios(id),
    motivo_cancelamento TEXT
);
CREATE INDEX IF NOT EXISTS idx_mov_data ON movimentacoes(data);
CREATE TABLE IF NOT EXISTS itens (
    id INTEGER PRIMARY KEY,
    movimentacao_id INTEGER NOT NULL REFERENCES movimentacoes(id),
    produto_id INTEGER NOT NULL REFERENCES produtos(id),
    quantidade INTEGER NOT NULL CHECK (quantidade > 0),
    valor_unitario REAL NOT NULL,
    custo_unitario REAL NOT NULL,
    imeis TEXT NOT NULL DEFAULT '[]',
    custo_total REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_itens_mov ON itens(movimentacao_id);
CREATE INDEX IF NOT EXISTS idx_itens_prod ON itens(produto_id);
CREATE TABLE IF NOT EXISTS imeis (
    imei TEXT PRIMARY KEY,
    produto_id INTEGER NOT NULL REFERENCES produtos(id),
    status TEXT NOT NULL CHECK (status IN ('disponivel', 'vendido', 'baixado', 'cancelado')),
    entrada_id INTEGER REFERENCES movimentacoes(id),
    saida_id INTEGER REFERENCES movimentacoes(id),
    atualizado_em TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_imeis_prod ON imeis(produto_id, status);
CREATE TABLE IF NOT EXISTS ordens_servico (
    id INTEGER PRIMARY KEY,
    cliente_id INTEGER NOT NULL REFERENCES clientes(id),
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    tecnico TEXT,
    aparelho TEXT NOT NULL,
    imei TEXT, cor TEXT, senha_desbloqueio TEXT, acessorios TEXT,
    defeito TEXT NOT NULL,
    laudo TEXT,
    status TEXT NOT NULL DEFAULT 'Aberta',
    previsao TEXT,
    garantia_dias INTEGER NOT NULL DEFAULT 90,
    valor_servicos REAL NOT NULL DEFAULT 0,
    valor_pecas REAL NOT NULL DEFAULT 0,
    desconto REAL NOT NULL DEFAULT 0,
    total REAL NOT NULL DEFAULT 0,
    forma_pagamento TEXT,
    observacao TEXT,
    entrada_em TEXT NOT NULL,
    atualizado_em TEXT NOT NULL,
    entregue_em TEXT,
    movimentacao_id INTEGER REFERENCES movimentacoes(id)
);
CREATE INDEX IF NOT EXISTS idx_os_status ON ordens_servico(status);
CREATE TABLE IF NOT EXISTS os_servicos (
    id INTEGER PRIMARY KEY,
    os_id INTEGER NOT NULL REFERENCES ordens_servico(id),
    descricao TEXT NOT NULL,
    valor REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS os_pecas (
    id INTEGER PRIMARY KEY,
    os_id INTEGER NOT NULL REFERENCES ordens_servico(id),
    produto_id INTEGER NOT NULL REFERENCES produtos(id),
    quantidade INTEGER NOT NULL CHECK (quantidade > 0),
    valor_unitario REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS os_historico (
    id INTEGER PRIMARY KEY,
    os_id INTEGER NOT NULL REFERENCES ordens_servico(id),
    data TEXT NOT NULL,
    status TEXT NOT NULL,
    nota TEXT,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id)
);
CREATE TABLE IF NOT EXISTS orcamentos (
    id INTEGER PRIMARY KEY,
    cliente_id INTEGER REFERENCES clientes(id),
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    data TEXT NOT NULL,
    validade TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'aberto',
    subtotal REAL NOT NULL DEFAULT 0,
    desconto REAL NOT NULL DEFAULT 0,
    total REAL NOT NULL DEFAULT 0,
    observacao TEXT,
    movimentacao_id INTEGER REFERENCES movimentacoes(id)
);
CREATE TABLE IF NOT EXISTS orcamento_itens (
    id INTEGER PRIMARY KEY,
    orcamento_id INTEGER NOT NULL REFERENCES orcamentos(id),
    produto_id INTEGER NOT NULL REFERENCES produtos(id),
    quantidade INTEGER NOT NULL CHECK (quantidade > 0),
    valor_unitario REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS financeiro (
    id INTEGER PRIMARY KEY,
    tipo TEXT NOT NULL CHECK (tipo IN ('receber', 'pagar')),
    descricao TEXT NOT NULL,
    categoria TEXT NOT NULL,
    valor REAL NOT NULL CHECK (valor > 0),
    vencimento TEXT NOT NULL,
    pago_em TEXT,
    forma_pagamento TEXT,
    parcela TEXT,
    cliente_id INTEGER REFERENCES clientes(id),
    fornecedor_id INTEGER REFERENCES fornecedores(id),
    movimentacao_id INTEGER REFERENCES movimentacoes(id),
    os_id INTEGER REFERENCES ordens_servico(id),
    observacao TEXT,
    cancelado INTEGER NOT NULL DEFAULT 0,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    criado_em TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fin_venc ON financeiro(tipo, vencimento);
CREATE INDEX IF NOT EXISTS idx_fin_pago ON financeiro(pago_em);
CREATE TABLE IF NOT EXISTS caixas (
    id INTEGER PRIMARY KEY,
    aberto_em TEXT NOT NULL,
    aberto_por INTEGER NOT NULL REFERENCES usuarios(id),
    saldo_inicial REAL NOT NULL DEFAULT 0,
    fechado_em TEXT,
    fechado_por INTEGER REFERENCES usuarios(id),
    saldo_esperado REAL,
    saldo_informado REAL,
    observacao TEXT
);
CREATE TABLE IF NOT EXISTS inventarios (
    id INTEGER PRIMARY KEY,
    criado_em TEXT NOT NULL,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    categoria TEXT,
    status TEXT NOT NULL DEFAULT 'aberto' CHECK (status IN ('aberto', 'finalizado', 'cancelado')),
    observacao TEXT,
    finalizado_em TEXT,
    finalizado_por INTEGER REFERENCES usuarios(id),
    entrada_id INTEGER REFERENCES movimentacoes(id),
    saida_id INTEGER REFERENCES movimentacoes(id)
);
CREATE TABLE IF NOT EXISTS inventario_itens (
    id INTEGER PRIMARY KEY,
    inventario_id INTEGER NOT NULL REFERENCES inventarios(id),
    produto_id INTEGER NOT NULL REFERENCES produtos(id),
    esperado INTEGER NOT NULL,
    contado INTEGER,
    imeis_esperados TEXT NOT NULL DEFAULT '[]',
    imeis_contados TEXT NOT NULL DEFAULT '[]',
    custo REAL NOT NULL DEFAULT 0,
    UNIQUE (inventario_id, produto_id)
);
CREATE TABLE IF NOT EXISTS caixa_movimentos (
    id INTEGER PRIMARY KEY,
    caixa_id INTEGER NOT NULL REFERENCES caixas(id),
    tipo TEXT NOT NULL CHECK (tipo IN ('suprimento', 'sangria')),
    valor REAL NOT NULL CHECK (valor > 0),
    descricao TEXT,
    data TEXT NOT NULL,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id)
);
"""

CONFIG_PADRAO = {
    "nome_loja": "Minha Loja de Celulares",
    "documento": "",
    "endereco": "",
    "telefone": "",
    "rodape_recibo": "Obrigado pela preferência! Garantia conforme termo do produto.",
    "exigir_caixa": "0",
    "saldo_inicial": "0",
    "garantia_os_dias": "90",
    "validade_orcamento_dias": "7",
    "termo_os": ("A garantia cobre apenas o serviço executado e as peças trocadas. Aparelhos não retirados "
                 "em 90 dias após o aviso de conclusão poderão ser descartados. A loja não se responsabiliza "
                 "por dados do aparelho; faça backup antes de deixar o aparelho."),
}

ESCRITA = threading.Lock()  # SQLite aceita um escritor por vez


# --------------------------------------------------------------------------- utilidades

class Erro(Exception):
    def __init__(self, msg, status=400):
        super().__init__(msg)
        self.msg = msg
        self.status = status


class Resposta:
    def __init__(self, dados=None, status=200, headers=None, bruto=None, tipo=None):
        self.dados, self.status, self.headers = dados, status, headers or []
        self.bruto, self.tipo = bruto, tipo


def agora():
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def conectar(caminho):
    con = sqlite3.connect(caminho, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def dicts(cur):
    return [dict(r) for r in cur]


def um(db, sql, args=()):
    r = db.execute(sql, args).fetchone()
    return dict(r) if r else None


def hash_senha(senha, sal=None, iteracoes=200_000):
    sal = sal or secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", senha.encode(), sal.encode(), iteracoes).hex()
    return f"pbkdf2${iteracoes}${sal}${h}"


def conferir_senha(senha, guardado):
    try:
        _, it, sal, h = guardado.split("$")
        return hmac.compare_digest(hash_senha(senha, sal, int(it)).split("$")[3], h)
    except (ValueError, AttributeError):
        return False


def texto(v, campo, obrigatorio=False, maximo=200):
    v = "" if v is None else str(v).strip()
    if obrigatorio and not v:
        raise Erro(f"Preencha o campo {campo}.")
    if len(v) > maximo:
        raise Erro(f"O campo {campo} aceita no máximo {maximo} caracteres.")
    return v


def dinheiro(v, campo):
    try:
        n = round(float(str(v).replace(",", ".")) if v not in (None, "") else 0.0, 2)
    except ValueError:
        raise Erro(f"Valor inválido em {campo}.")
    if n < 0 or n > 10_000_000:
        raise Erro(f"Valor fora do limite em {campo}.")
    return n


def inteiro(v, campo, minimo=0, maximo=1_000_000):
    try:
        n = int(v if v not in (None, "") else 0)
    except (TypeError, ValueError):
        raise Erro(f"Número inválido em {campo}.")
    if n < minimo or n > maximo:
        raise Erro(f"{campo} deve estar entre {minimo} e {maximo}.")
    return n


def opcao(v, campo, opcoes):
    if v not in opcoes:
        raise Erro(f"Escolha uma opção válida em {campo}.")
    return v


def data_iso(v, campo):
    try:
        return dt.date.fromisoformat(str(v)).isoformat()
    except ValueError:
        raise Erro(f"Data inválida em {campo} (use AAAA-MM-DD).")


def imei_valido(imei):
    """IMEI tem 15 dígitos e o último é dígito verificador (Luhn)."""
    if not re.fullmatch(r"\d{15}", imei):
        return False
    soma = 0
    for i, ch in enumerate(imei[:14]):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            d = d - 9 if d > 9 else d
        soma += d
    return (10 - soma % 10) % 10 == int(imei[14])


def periodo(c):
    hoje = dt.date.today()
    inicio = data_iso(c.q("inicio") or hoje.replace(day=1).isoformat(), "início")
    fim = data_iso(c.q("fim") or hoje.isoformat(), "fim")
    if fim < inicio:
        raise Erro("A data final é anterior à inicial.")
    return inicio, fim


# --------------------------------------------------------------------------- banco

def inicializar_banco(caminho, avisar=True):
    os.makedirs(os.path.dirname(os.path.abspath(caminho)), exist_ok=True)
    con = conectar(caminho)
    con.execute("PRAGMA journal_mode = WAL")
    con.executescript(SCHEMA)
    cols = {r[1] for r in con.execute("PRAGMA table_info(movimentacoes)")}
    if "parcelas" not in cols:  # migração de bancos criados em versões anteriores
        con.execute("ALTER TABLE movimentacoes ADD COLUMN parcelas INTEGER NOT NULL DEFAULT 1")
    if "custo_total" not in {r[1] for r in con.execute("PRAGMA table_info(itens)")}:
        con.execute("ALTER TABLE itens ADD COLUMN custo_total REAL NOT NULL DEFAULT 0")
        con.execute("UPDATE itens SET custo_total = ROUND(quantidade * custo_unitario, 2)")
    if "custo" not in {r[1] for r in con.execute("PRAGMA table_info(imeis)")}:
        con.execute("ALTER TABLE imeis ADD COLUMN custo REAL NOT NULL DEFAULT 0")
        con.execute("""UPDATE imeis SET custo = COALESCE((SELECT i.custo_unitario FROM itens i
                       WHERE i.movimentacao_id = imeis.entrada_id AND i.produto_id = imeis.produto_id LIMIT 1), 0)""")
    if "localizacao" not in {r[1] for r in con.execute("PRAGMA table_info(produtos)")}:
        con.execute("ALTER TABLE produtos ADD COLUMN localizacao TEXT")
    for k, v in CONFIG_PADRAO.items():
        con.execute("INSERT OR IGNORE INTO config (chave, valor) VALUES (?, ?)", (k, v))
    if not con.execute("SELECT 1 FROM usuarios").fetchone():
        con.execute(
            "INSERT INTO usuarios (nome, login, senha_hash, perfil, criado_em) VALUES (?,?,?,?,?)",
            ("Administrador", "admin", hash_senha("admin123"), "admin", agora()))
        if avisar:
            print("\n  Primeiro acesso -> usuário: admin   senha: admin123")
            print("  Troque a senha em 'Minha conta' logo após entrar.\n")
    con.execute("DELETE FROM sessoes WHERE expira_em < ?", (agora(),))
    con.commit()
    con.close()


# --------------------------------------------------------------------------- rotas

ROTAS = []


def rota(metodo, padrao, acesso="logado"):
    """acesso: 'publico', 'logado' ou 'admin'."""
    def deco(f):
        ROTAS.append((metodo, re.compile("^" + padrao + "$"), acesso, f))
        return f
    return deco


class Req:
    def __init__(self, db, usuario, corpo, query, params, ip, caminho_db):
        self.db, self.usuario, self.corpo = db, usuario, corpo
        self.query, self.params, self.ip, self.caminho_db = query, params, ip, caminho_db

    def q(self, nome, padrao=None):
        v = self.query.get(nome, [padrao])[0]
        return v.strip() if isinstance(v, str) else v

    @property
    def admin(self):
        return bool(self.usuario) and self.usuario["perfil"] == "admin"


# ---- sessão

TENTATIVAS = {}


@rota("POST", "/api/login", "publico")
def login(c):
    agora_s = time.time()
    falhas = [t for t in TENTATIVAS.get(c.ip, []) if agora_s - t < 300]
    if len(falhas) >= 10:
        raise Erro("Muitas tentativas. Aguarde alguns minutos.", 429)
    u = um(c.db, "SELECT * FROM usuarios WHERE login = ? AND ativo = 1",
           (texto(c.corpo.get("login"), "usuário", True),))
    if not u or not conferir_senha(str(c.corpo.get("senha", "")), u["senha_hash"]):
        falhas.append(agora_s)
        TENTATIVAS[c.ip] = falhas
        raise Erro("Usuário ou senha incorretos.", 401)
    TENTATIVAS.pop(c.ip, None)
    token = secrets.token_urlsafe(32)
    expira = (dt.datetime.now() + dt.timedelta(hours=SESSAO_HORAS)).strftime("%Y-%m-%d %H:%M:%S")
    with ESCRITA:
        c.db.execute("INSERT INTO sessoes VALUES (?, ?, ?)", (token, u["id"], expira))
        c.db.commit()
    ck = f"{COOKIE}={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={SESSAO_HORAS * 3600}"
    return Resposta(usuario_publico(u), headers=[("Set-Cookie", ck)])


@rota("POST", "/api/logout", "publico")
def logout(c):
    if c.usuario:
        with ESCRITA:
            c.db.execute("DELETE FROM sessoes WHERE token = ?", (c.usuario["_token"],))
            c.db.commit()
    return Resposta({"ok": True}, headers=[("Set-Cookie", f"{COOKIE}=; Path=/; Max-Age=0")])


def usuario_publico(u):
    return {k: u[k] for k in ("id", "nome", "login", "perfil", "ativo", "criado_em")}


@rota("GET", "/api/me")
def me(c):
    return usuario_publico(c.usuario)


@rota("POST", "/api/me/senha")
def trocar_minha_senha(c):
    if not conferir_senha(str(c.corpo.get("atual", "")), c.usuario["senha_hash"]):
        raise Erro("Senha atual incorreta.")
    nova = str(c.corpo.get("nova", ""))
    if len(nova) < 6:
        raise Erro("A nova senha precisa ter pelo menos 6 caracteres.")
    with ESCRITA:
        c.db.execute("UPDATE usuarios SET senha_hash = ? WHERE id = ?", (hash_senha(nova), c.usuario["id"]))
        c.db.execute("DELETE FROM sessoes WHERE usuario_id = ? AND token <> ?",
                     (c.usuario["id"], c.usuario["_token"]))
        c.db.commit()
    return {"ok": True}


@rota("GET", "/api/meta")
def meta(c):
    cfg = {r["chave"]: r["valor"] for r in c.db.execute("SELECT * FROM config")}
    caixa = um(c.db, "SELECT id, aberto_em FROM caixas WHERE fechado_em IS NULL")
    return {"categorias": CATEGORIAS, "condicoes": CONDICOES, "motivos": MOTIVOS,
            "motivos_admin": MOTIVOS_ADMIN, "motivos_internos": MOTIVOS_INTERNOS, "pagamentos": PAGAMENTOS,
            "categorias_fin": CATEGORIAS_FIN, "status_os": STATUS_OS, "config": cfg, "caixa": caixa}


@rota("PUT", "/api/config", "admin")
def salvar_config(c):
    with ESCRITA:
        for k in CONFIG_PADRAO:
            if k in c.corpo:
                c.db.execute("INSERT OR REPLACE INTO config VALUES (?, ?)",
                             (k, texto(c.corpo[k], k, maximo=500)))
        c.db.commit()
    return meta(c)["config"]


# ---- usuários

@rota("GET", "/api/usuarios", "admin")
def listar_usuarios(c):
    return [usuario_publico(u) for u in c.db.execute("SELECT * FROM usuarios ORDER BY nome")]


@rota("POST", "/api/usuarios", "admin")
def criar_usuario(c):
    b = c.corpo
    senha = str(b.get("senha", ""))
    if len(senha) < 6:
        raise Erro("A senha precisa ter pelo menos 6 caracteres.")
    login_ = texto(b.get("login"), "usuário", True, 40)
    if not re.fullmatch(r"[A-Za-z0-9._-]+", login_):
        raise Erro("O usuário aceita apenas letras, números, ponto, hífen e sublinhado.")
    with ESCRITA:
        cur = c.db.execute(
            "INSERT INTO usuarios (nome, login, senha_hash, perfil, criado_em) VALUES (?,?,?,?,?)",
            (texto(b.get("nome"), "nome", True), login_, hash_senha(senha),
             opcao(b.get("perfil"), "perfil", ["admin", "vendedor"]), agora()))
        c.db.commit()
    return usuario_publico(um(c.db, "SELECT * FROM usuarios WHERE id = ?", (cur.lastrowid,)))


@rota("PUT", r"/api/usuarios/(\d+)", "admin")
def editar_usuario(c):
    uid = int(c.params[0])
    u = um(c.db, "SELECT * FROM usuarios WHERE id = ?", (uid,))
    if not u:
        raise Erro("Usuário não encontrado.", 404)
    b = c.corpo
    perfil = opcao(b.get("perfil", u["perfil"]), "perfil", ["admin", "vendedor"])
    ativo = 1 if b.get("ativo", u["ativo"]) in (1, True, "1", "true") else 0
    if uid == c.usuario["id"] and (not ativo or perfil != "admin"):
        raise Erro("Você não pode desativar nem rebaixar o seu próprio usuário.")
    with ESCRITA:
        c.db.execute("UPDATE usuarios SET nome = ?, perfil = ?, ativo = ? WHERE id = ?",
                     (texto(b.get("nome", u["nome"]), "nome", True), perfil, ativo, uid))
        senha = str(b.get("senha") or "")
        if senha:
            if len(senha) < 6:
                raise Erro("A senha precisa ter pelo menos 6 caracteres.")
            c.db.execute("UPDATE usuarios SET senha_hash = ? WHERE id = ?", (hash_senha(senha), uid))
        if senha or not ativo:
            c.db.execute("DELETE FROM sessoes WHERE usuario_id = ?", (uid,))
        c.db.commit()
    return usuario_publico(um(c.db, "SELECT * FROM usuarios WHERE id = ?", (uid,)))


# ---- clientes e fornecedores

def registrar_cadastro(tabela, rotulo):
    def ler(b):
        return (texto(b.get("nome"), "nome", True), texto(b.get("documento"), "CPF/CNPJ", maximo=30),
                texto(b.get("telefone"), "telefone", maximo=30), texto(b.get("email"), "e-mail", maximo=120),
                texto(b.get("observacao"), "observação", maximo=1000))

    def listar(c):
        q = c.q("q")
        if q:
            like = f"%{q}%"
            return dicts(c.db.execute(
                f"SELECT * FROM {tabela} WHERE nome LIKE ? OR documento LIKE ? OR telefone LIKE ? "
                f"ORDER BY nome LIMIT 500", (like, like, like)))
        return dicts(c.db.execute(f"SELECT * FROM {tabela} ORDER BY nome LIMIT 2000"))

    def detalhe(c):
        r = um(c.db, f"SELECT * FROM {tabela} WHERE id = ?", (int(c.params[0]),))
        if not r:
            raise Erro(f"{rotulo} não encontrado.", 404)
        col = "cliente_id" if tabela == "clientes" else "fornecedor_id"
        r["movimentacoes"] = dicts(c.db.execute(
            f"SELECT id, tipo, motivo, data, total, cancelada FROM movimentacoes WHERE {col} = ? "
            f"ORDER BY data DESC LIMIT 200", (r["id"],)))
        return r

    def criar(c):
        with ESCRITA:
            cur = c.db.execute(
                f"INSERT INTO {tabela} (nome, documento, telefone, email, observacao, criado_em) "
                f"VALUES (?,?,?,?,?,?)", (*ler(c.corpo), agora()))
            c.db.commit()
        return um(c.db, f"SELECT * FROM {tabela} WHERE id = ?", (cur.lastrowid,))

    def editar(c):
        rid = int(c.params[0])
        with ESCRITA:
            cur = c.db.execute(
                f"UPDATE {tabela} SET nome=?, documento=?, telefone=?, email=?, observacao=? WHERE id=?",
                (*ler(c.corpo), rid))
            c.db.commit()
        if not cur.rowcount:
            raise Erro(f"{rotulo} não encontrado.", 404)
        return um(c.db, f"SELECT * FROM {tabela} WHERE id = ?", (rid,))

    def excluir(c):
        rid = int(c.params[0])
        col = "cliente_id" if tabela == "clientes" else "fornecedor_id"
        if c.db.execute(f"SELECT 1 FROM movimentacoes WHERE {col} = ? LIMIT 1", (rid,)).fetchone():
            raise Erro(f"Este {rotulo.lower()} tem movimentações e não pode ser excluído.")
        with ESCRITA:
            c.db.execute(f"DELETE FROM {tabela} WHERE id = ?", (rid,))
            c.db.commit()
        return {"ok": True}

    rota("GET", f"/api/{tabela}")(listar)
    rota("GET", rf"/api/{tabela}/(\d+)")(detalhe)
    rota("POST", f"/api/{tabela}")(criar)
    rota("PUT", rf"/api/{tabela}/(\d+)")(editar)
    rota("DELETE", rf"/api/{tabela}/(\d+)", "admin")(excluir)


registrar_cadastro("clientes", "Cliente")
registrar_cadastro("fornecedores", "Fornecedor")


# ---- produtos

def ler_produto(b):
    return {
        "codigo": texto(b.get("codigo"), "código", maximo=60) or None,
        "nome": texto(b.get("nome"), "nome", True),
        "marca": texto(b.get("marca"), "marca", maximo=60),
        "modelo": texto(b.get("modelo"), "modelo", maximo=80),
        "categoria": opcao(b.get("categoria"), "categoria", CATEGORIAS),
        "cor": texto(b.get("cor"), "cor", maximo=40),
        "armazenamento": texto(b.get("armazenamento"), "armazenamento", maximo=40),
        "condicao": opcao(b.get("condicao") or "Novo", "condição", CONDICOES),
        "controla_imei": 1 if b.get("controla_imei") in (1, True, "1", "true") else 0,
        "preco_custo": dinheiro(b.get("preco_custo"), "preço de custo"),
        "preco_venda": dinheiro(b.get("preco_venda"), "preço de venda"),
        "estoque_minimo": inteiro(b.get("estoque_minimo"), "estoque mínimo"),
        "localizacao": texto(b.get("localizacao"), "localização", maximo=60),
    }


@rota("GET", "/api/produtos")
def listar_produtos(c):
    where, args = [], []
    if c.q("todos") != "1":
        where.append("ativo = 1")
    if c.q("q"):
        q = c.q("q")
        like = f"%{q}%"
        where.append("(nome LIKE ? OR marca LIKE ? OR modelo LIKE ? OR codigo = ? "
                     "OR id IN (SELECT produto_id FROM imeis WHERE imei = ?))")
        args += [like, like, like, q, q]
    if c.q("categoria"):
        where.append("categoria = ?")
        args.append(c.q("categoria"))
    if c.q("baixo") == "1":
        where.append("estoque_atual <= estoque_minimo")
    if c.q("com_estoque") == "1":
        where.append("estoque_atual > 0")
    sql = (f"SELECT p.*, ROUND({VALOR_CUSTO}, 2) AS valor_custo, ROUND(p.estoque_atual * p.preco_venda, 2) AS valor_venda "
           f"FROM produtos p" + (" WHERE " + " AND ".join(where) if where else ""))
    return dicts(c.db.execute(sql + " ORDER BY p.nome LIMIT 2000", args))


@rota("GET", r"/api/produtos/(\d+)")
def detalhe_produto(c):
    p = um(c.db, f"SELECT p.*, ROUND({VALOR_CUSTO}, 2) AS valor_custo FROM produtos p WHERE p.id = ?",
           (int(c.params[0]),))
    if not p:
        raise Erro("Produto não encontrado.", 404)
    p["imeis_disponiveis"] = [r["imei"] for r in c.db.execute(
        "SELECT imei FROM imeis WHERE produto_id = ? AND status = 'disponivel' ORDER BY atualizado_em",
        (p["id"],))]
    p["movimentacoes"] = dicts(c.db.execute(
        """SELECT m.id, m.tipo, m.motivo, m.data, m.cancelada, i.quantidade, i.valor_unitario, i.imeis
           FROM itens i JOIN movimentacoes m ON m.id = i.movimentacao_id
           WHERE i.produto_id = ? ORDER BY m.data DESC, m.id DESC LIMIT 100""", (p["id"],)))
    return p


@rota("POST", "/api/produtos", "admin")
def criar_produto(c):
    d = ler_produto(c.corpo)
    with ESCRITA:
        cur = c.db.execute(
            f"INSERT INTO produtos ({', '.join(d)}, criado_em) VALUES ({', '.join('?' * len(d))}, ?)",
            (*d.values(), agora()))
        c.db.commit()
    return um(c.db, "SELECT * FROM produtos WHERE id = ?", (cur.lastrowid,))


@rota("PUT", r"/api/produtos/(\d+)", "admin")
def editar_produto(c):
    pid = int(c.params[0])
    atual = um(c.db, "SELECT * FROM produtos WHERE id = ?", (pid,))
    if not atual:
        raise Erro("Produto não encontrado.", 404)
    d = ler_produto(c.corpo)
    if d["controla_imei"] != atual["controla_imei"] and atual["estoque_atual"] > 0:
        raise Erro("Só é possível mudar o controle de IMEI com o estoque zerado.")
    d["ativo"] = 0 if c.corpo.get("ativo") in (0, False, "0", "false") else 1
    with ESCRITA:
        c.db.execute(f"UPDATE produtos SET {', '.join(k + ' = ?' for k in d)} WHERE id = ?",
                     (*d.values(), pid))
        c.db.commit()
    return um(c.db, "SELECT * FROM produtos WHERE id = ?", (pid,))


@rota("DELETE", r"/api/produtos/(\d+)", "admin")
def excluir_produto(c):
    pid = int(c.params[0])
    with ESCRITA:
        if c.db.execute("SELECT 1 FROM itens WHERE produto_id = ? LIMIT 1", (pid,)).fetchone():
            c.db.execute("UPDATE produtos SET ativo = 0 WHERE id = ?", (pid,))
            c.db.commit()
            return {"ok": True, "desativado": True}
        c.db.execute("DELETE FROM imeis WHERE produto_id = ?", (pid,))
        c.db.execute("DELETE FROM produtos WHERE id = ?", (pid,))
        c.db.commit()
    return {"ok": True, "desativado": False}


@rota("GET", r"/api/imeis/(\d{15})")
def rastrear_imei(c):
    imei = c.params[0]
    r = um(c.db, """SELECT i.*, p.nome AS produto_nome FROM imeis i
                    JOIN produtos p ON p.id = i.produto_id WHERE i.imei = ?""", (imei,))
    hist = dicts(c.db.execute(
        """SELECT m.id, m.tipo, m.motivo, m.data, m.cancelada, p.nome AS produto_nome,
                  c.nome AS cliente_nome, f.nome AS fornecedor_nome, i.valor_unitario
           FROM itens i JOIN movimentacoes m ON m.id = i.movimentacao_id
           JOIN produtos p ON p.id = i.produto_id
           LEFT JOIN clientes c ON c.id = m.cliente_id
           LEFT JOIN fornecedores f ON f.id = m.fornecedor_id
           WHERE i.imeis LIKE ? ORDER BY m.data, m.id""", (f'%"{imei}"%',)))
    if not r and not hist:
        raise Erro("IMEI não encontrado no sistema.", 404)
    return {"imei": imei, "atual": r, "historico": hist}


# ---- movimentações (entradas e saídas)

def somar_meses(d, n):
    m = d.month - 1 + n
    ano, mes = d.year + m // 12, m % 12 + 1
    ultimo = (dt.date(ano + (mes == 12), mes % 12 + 1, 1) - dt.timedelta(days=1)).day
    return dt.date(ano, mes, min(d.day, ultimo))


def gerar_financeiro(db, usuario, tipo, descricao, categoria, total, forma, parcelas, primeiro, pago_em,
                     cliente_id=None, fornecedor_id=None, movimentacao_id=None, os_id=None, observacao=""):
    """Cria o lançamento (ou as parcelas) em contas a receber / a pagar."""
    base = round(total / parcelas, 2)
    for n in range(parcelas):
        valor = round(total - base * (parcelas - 1), 2) if n == parcelas - 1 else base
        db.execute(
            """INSERT INTO financeiro (tipo, descricao, categoria, valor, vencimento, pago_em, forma_pagamento,
               parcela, cliente_id, fornecedor_id, movimentacao_id, os_id, observacao, usuario_id, criado_em)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (tipo, descricao, categoria, valor, somar_meses(primeiro, n).isoformat(), pago_em, forma,
             f"{n + 1}/{parcelas}" if parcelas > 1 else None, cliente_id, fornecedor_id, movimentacao_id,
             os_id, observacao, usuario["id"], agora()))


def ler_condicao(b, data_base, a_prazo):
    """Parcelas e 1º vencimento de uma venda a prazo ou compra a prazo."""
    parcelas = inteiro(b.get("parcelas") or 1, "parcelas", 1, 48)
    if not a_prazo:
        return parcelas, data_base
    primeiro = b.get("primeiro_vencimento")
    primeiro = dt.date.fromisoformat(data_iso(primeiro, "1º vencimento")) if primeiro else data_base + dt.timedelta(days=30)
    return parcelas, primeiro


def caixa_aberto(db):
    return um(db, "SELECT * FROM caixas WHERE fechado_em IS NULL ORDER BY id DESC LIMIT 1")


def config(db, chave):
    r = db.execute("SELECT valor FROM config WHERE chave = ?", (chave,)).fetchone()
    return r[0] if r else CONFIG_PADRAO.get(chave, "")


def recalcular_custo_imei(db, pid):
    """Em produtos com IMEI o custo médio é a média do custo real dos aparelhos em estoque."""
    r = db.execute("SELECT AVG(custo) FROM imeis WHERE produto_id = ? AND status = 'disponivel'", (pid,)).fetchone()[0]
    if r is not None:
        db.execute("UPDATE produtos SET preco_custo = ? WHERE id = ?", (round(r, 2), pid))


# valor de estoque de um produto (alias p): aparelhos com IMEI somam o custo real de cada unidade
VALOR_CUSTO = """(CASE WHEN p.controla_imei = 1 THEN (SELECT COALESCE(SUM(x.custo), 0) FROM imeis x
                  WHERE x.produto_id = p.id AND x.status = 'disponivel') ELSE p.estoque_atual * p.preco_custo END)"""


def registrar_movimentacao(db, usuario, b, data=None, interno=False, depois=None):
    """Grava entrada/saída, atualiza estoque, IMEIs e financeiro numa única transação.
    `depois(db, mid, total)` roda dentro da mesma transação (usado por OS e orçamentos)."""
    tipo = opcao(b.get("tipo"), "tipo", list(MOTIVOS))
    motivo = opcao(b.get("motivo"), "motivo", MOTIVOS[tipo])
    if motivo in MOTIVOS_INTERNOS and not interno:
        raise Erro("Este motivo é gerado automaticamente pelo sistema.")
    if motivo in MOTIVOS_ADMIN and usuario["perfil"] != "admin":
        raise Erro("Apenas administradores podem lançar ajustes de inventário.", 403)
    venda = tipo == "saida" and motivo == "Venda"
    itens = b.get("itens")
    if not isinstance(itens, list) or not itens:
        raise Erro("Adicione pelo menos um produto.")
    if len(itens) > 300:
        raise Erro("Máximo de 300 itens por lançamento.")

    fornecedor_id = inteiro(b.get("fornecedor_id"), "fornecedor") or None
    cliente_id = inteiro(b.get("cliente_id"), "cliente") or None
    if fornecedor_id and not db.execute("SELECT 1 FROM fornecedores WHERE id = ?", (fornecedor_id,)).fetchone():
        raise Erro("Fornecedor não encontrado.")
    if cliente_id and not db.execute("SELECT 1 FROM clientes WHERE id = ?", (cliente_id,)).fetchone():
        raise Erro("Cliente não encontrado.")
    forma = opcao(b.get("forma_pagamento"), "forma de pagamento", PAGAMENTOS) if venda else None
    documento = texto(b.get("documento"), "documento/nota", maximo=60)
    observacao = texto(b.get("observacao"), "observação", maximo=1000)
    momento = data or agora()
    dia_base = dt.date.fromisoformat(momento[:10])
    compra = tipo == "entrada" and motivo == "Compra"
    compra_a_prazo = compra and b.get("condicao_pagamento") == "a_prazo"
    parcelas, primeiro = ler_condicao(b, dia_base, forma == "Crediário" or compra_a_prazo)
    forma_compra = opcao(b.get("forma_pagamento") or "Outro", "forma de pagamento", PAGAMENTOS) if compra else None
    if forma == "Crediário" and not cliente_id:
        raise Erro("Venda no crediário precisa de um cliente identificado.")
    if venda and not data and config(db, "exigir_caixa") == "1" and not caixa_aberto(db):
        raise Erro("Abra o caixa antes de registrar vendas (menu Financeiro → Caixa).")

    with ESCRITA:
        db.execute("BEGIN IMMEDIATE")
        try:
            prontos, usados, retirada = [], set(), {}
            for n, it in enumerate(itens, 1):
                p = um(db, "SELECT * FROM produtos WHERE id = ?", (inteiro(it.get("produto_id"), "produto"),))
                if not p or not p["ativo"]:
                    raise Erro(f"Item {n}: produto não encontrado ou inativo.")
                qtd = inteiro(it.get("quantidade"), f"quantidade ({p['nome']})", 1, 100_000)
                padrao = p["preco_venda"] if tipo == "saida" else p["preco_custo"]
                valor = dinheiro(it.get("valor_unitario", padrao), f"valor ({p['nome']})")
                lista, custos = [], []
                if p["controla_imei"]:
                    lista = [re.sub(r"\D", "", str(x)) for x in (it.get("imeis") or []) if str(x).strip()]
                    if len(lista) != qtd:
                        raise Erro(f"{p['nome']}: informe {qtd} IMEI(s) (um por aparelho); recebido {len(lista)}.")
                    for imei in lista:
                        if not imei_valido(imei):
                            raise Erro(f"IMEI inválido: {imei}. Confira os 15 dígitos.")
                        if imei in usados:
                            raise Erro(f"IMEI repetido no lançamento: {imei}.")
                        usados.add(imei)
                        reg = um(db, "SELECT * FROM imeis WHERE imei = ?", (imei,))
                        if tipo == "entrada" and reg and reg["status"] == "disponivel":
                            raise Erro(f"O IMEI {imei} já está no estoque.")
                        if tipo == "saida" and (not reg or reg["status"] != "disponivel"
                                                or reg["produto_id"] != p["id"]):
                            raise Erro(f"O IMEI {imei} não está disponível no estoque de {p['nome']}.")
                    if tipo == "entrada":
                        bruto = it.get("custos")
                        if isinstance(bruto, list) and bruto:
                            if len(bruto) != qtd:
                                raise Erro(f"{p['nome']}: informe um custo para cada IMEI.")
                            custos = [dinheiro(x, f"custo do IMEI {lista[k]}") for k, x in enumerate(bruto)]
                        elif motivo == "Compra":
                            custos = [valor] * qtd
                        else:  # devolução/troca: o aparelho volta com o custo que tinha
                            for imei in lista:
                                reg = um(db, "SELECT custo FROM imeis WHERE imei = ?", (imei,))
                                custos.append(reg["custo"] if reg and reg["custo"] else p["preco_custo"])
                if tipo == "saida":
                    retirada[p["id"]] = retirada.get(p["id"], 0) + qtd
                    if retirada[p["id"]] > p["estoque_atual"]:
                        raise Erro(f"Estoque insuficiente de {p['nome']}: disponível {p['estoque_atual']}.")
                linha = round(sum(custos), 2) if (custos and tipo == "entrada" and motivo == "Compra") else round(qtd * valor, 2)
                if custos and motivo == "Compra":
                    valor = round(linha / qtd, 2)
                prontos.append((p, qtd, valor, lista, custos, linha))

            subtotal = round(sum(x[5] for x in prontos), 2)
            desconto = dinheiro(b.get("desconto"), "desconto") if venda else 0.0
            if desconto > subtotal:
                raise Erro("O desconto não pode ser maior que o subtotal.")
            total = round(subtotal - desconto, 2)
            cur = db.execute(
                """INSERT INTO movimentacoes (tipo, motivo, data, usuario_id, fornecedor_id, cliente_id,
                   forma_pagamento, documento, subtotal, desconto, total, observacao, parcelas)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (tipo, motivo, momento, usuario["id"], fornecedor_id, cliente_id, forma or forma_compra, documento,
                 subtotal, desconto, total, observacao, parcelas))
            mid = cur.lastrowid
            for p, qtd, valor, lista, custos, _linha in prontos:
                atual = um(db, "SELECT estoque_atual, preco_custo FROM produtos WHERE id = ?", (p["id"],))
                if tipo == "entrada":
                    custo = valor if motivo == "Compra" else atual["preco_custo"]
                    custo_total = round(sum(custos), 2) if custos else round(qtd * custo, 2)
                    if custos:
                        custo = round(sum(custos) / qtd, 2)
                    novo_custo = atual["preco_custo"]
                    if motivo == "Compra" and valor > 0:  # custo médio ponderado
                        e = atual["estoque_atual"]
                        novo_custo = round((e * atual["preco_custo"] + qtd * valor) / (e + qtd), 2) if e else valor
                    db.execute("UPDATE produtos SET estoque_atual = estoque_atual + ?, preco_custo = ? WHERE id = ?",
                               (qtd, novo_custo, p["id"]))
                    for imei, cu in zip(lista, custos):
                        db.execute(
                            """INSERT INTO imeis (imei, produto_id, status, entrada_id, saida_id, atualizado_em, custo)
                               VALUES (?, ?, 'disponivel', ?, NULL, ?, ?)
                               ON CONFLICT(imei) DO UPDATE SET produto_id = excluded.produto_id,
                               status = 'disponivel', entrada_id = excluded.entrada_id, saida_id = NULL,
                               atualizado_em = excluded.atualizado_em, custo = excluded.custo""",
                            (imei, p["id"], mid, momento, cu))
                else:
                    custo = atual["preco_custo"]
                    custo_total = round(qtd * custo, 2)
                    if lista:  # custo real dos aparelhos que estão saindo
                        custo_total = round(db.execute(
                            f"SELECT SUM(custo) FROM imeis WHERE imei IN ({','.join('?' * len(lista))})", lista).fetchone()[0] or 0, 2)
                        custo = round(custo_total / qtd, 2)
                    db.execute("UPDATE produtos SET estoque_atual = estoque_atual - ? WHERE id = ?", (qtd, p["id"]))
                    for imei in lista:
                        db.execute("UPDATE imeis SET status = ?, saida_id = ?, atualizado_em = ? WHERE imei = ?",
                                   ("vendido" if venda else "baixado", mid, momento, imei))
                if p["controla_imei"]:
                    recalcular_custo_imei(db, p["id"])
                db.execute(
                    """INSERT INTO itens (movimentacao_id, produto_id, quantidade, valor_unitario, custo_unitario, imeis,
                       custo_total) VALUES (?,?,?,?,?,?,?)""", (mid, p["id"], qtd, valor, custo, json.dumps(lista), custo_total))
            if venda and total > 0:
                crediario = forma == "Crediário"
                gerar_financeiro(db, usuario, "receber", f"Venda #{mid}", "Venda de produtos", total, forma,
                                 parcelas if crediario else 1, primeiro, None if crediario else momento,
                                 cliente_id=cliente_id, movimentacao_id=mid)
            elif compra and total > 0 and b.get("gerar_financeiro", True) is not False:
                gerar_financeiro(db, usuario, "pagar", f"Compra #{mid}" + (f" ({documento})" if documento else ""),
                                 "Compra de mercadorias", total, forma_compra, parcelas if compra_a_prazo else 1,
                                 primeiro, None if compra_a_prazo else momento,
                                 fornecedor_id=fornecedor_id, movimentacao_id=mid)
            if depois:
                depois(db, mid, total)
            db.commit()
        except Exception:
            db.rollback()
            raise
    return mid


def carregar_movimentacao(db, mid):
    m = um(db, """SELECT m.*, u.nome AS usuario_nome, c.nome AS cliente_nome, c.documento AS cliente_documento,
                         c.telefone AS cliente_telefone, f.nome AS fornecedor_nome, uc.nome AS cancelada_por_nome
                  FROM movimentacoes m JOIN usuarios u ON u.id = m.usuario_id
                  LEFT JOIN clientes c ON c.id = m.cliente_id
                  LEFT JOIN fornecedores f ON f.id = m.fornecedor_id
                  LEFT JOIN usuarios uc ON uc.id = m.cancelada_por WHERE m.id = ?""", (mid,))
    if not m:
        raise Erro("Movimentação não encontrada.", 404)
    m["itens"] = dicts(db.execute(
        """SELECT i.*, p.nome AS produto_nome, p.codigo AS produto_codigo FROM itens i
           JOIN produtos p ON p.id = i.produto_id WHERE i.movimentacao_id = ? ORDER BY i.id""", (mid,)))
    for i in m["itens"]:
        i["imeis"] = json.loads(i["imeis"])
    m["financeiro"] = dicts(db.execute(
        "SELECT id, tipo, valor, vencimento, pago_em, parcela, forma_pagamento, cancelado FROM financeiro "
        "WHERE movimentacao_id = ? ORDER BY vencimento, id", (mid,)))
    return m


@rota("POST", "/api/movimentacoes")
def criar_movimentacao(c):
    depois = None
    oid = inteiro(c.corpo.get("orcamento_id"), "orçamento") or None
    if oid:
        o = um(c.db, "SELECT * FROM orcamentos WHERE id = ?", (oid,))
        if not o or o["status"] in ("convertido", "recusado"):
            raise Erro("Orçamento não encontrado, já convertido ou recusado.")

        def depois(db, mid, total):
            db.execute("UPDATE orcamentos SET status = 'convertido', movimentacao_id = ? WHERE id = ?", (mid, oid))
    return carregar_movimentacao(c.db, registrar_movimentacao(c.db, c.usuario, c.corpo, depois=depois))


@rota("GET", "/api/movimentacoes")
def listar_movimentacoes(c):
    inicio, fim = periodo(c)
    where, args = ["date(m.data) BETWEEN ? AND ?"], [inicio, fim]
    if c.q("tipo"):
        where.append("m.tipo = ?")
        args.append(c.q("tipo"))
    if c.q("motivo"):
        where.append("m.motivo = ?")
        args.append(c.q("motivo"))
    if c.q("canceladas") != "1":
        where.append("m.cancelada = 0")
    if c.q("q"):
        like = f"%{c.q('q')}%"
        where.append("""(c.nome LIKE ? OR f.nome LIKE ? OR m.documento LIKE ? OR CAST(m.id AS TEXT) = ?
                        OR m.id IN (SELECT i.movimentacao_id FROM itens i JOIN produtos p ON p.id = i.produto_id
                                    WHERE p.nome LIKE ? OR i.imeis LIKE ?))""")
        args += [like, like, like, c.q("q"), like, like]
    return dicts(c.db.execute(
        f"""SELECT m.id, m.tipo, m.motivo, m.data, m.total, m.desconto, m.forma_pagamento, m.documento,
                   m.cancelada, u.nome AS usuario_nome, c.nome AS cliente_nome, f.nome AS fornecedor_nome,
                   (SELECT SUM(quantidade) FROM itens WHERE movimentacao_id = m.id) AS quantidade,
                   (SELECT GROUP_CONCAT(p.nome, ', ') FROM itens i JOIN produtos p ON p.id = i.produto_id
                    WHERE i.movimentacao_id = m.id) AS produtos
            FROM movimentacoes m JOIN usuarios u ON u.id = m.usuario_id
            LEFT JOIN clientes c ON c.id = m.cliente_id LEFT JOIN fornecedores f ON f.id = m.fornecedor_id
            WHERE {' AND '.join(where)} ORDER BY m.data DESC, m.id DESC LIMIT 1000""", args))


@rota("GET", r"/api/movimentacoes/(\d+)")
def detalhe_movimentacao(c):
    return carregar_movimentacao(c.db, int(c.params[0]))


@rota("POST", r"/api/movimentacoes/(\d+)/cancelar", "admin")
def cancelar_movimentacao(c):
    mid = int(c.params[0])
    justificativa = texto(c.corpo.get("motivo"), "motivo do cancelamento", True, 300)
    m = carregar_movimentacao(c.db, mid)
    if m["motivo"] in MOTIVOS_INTERNOS:
        raise Erro("Esta saída veio de uma ordem de serviço: cancele pela própria OS.")
    with ESCRITA:
        c.db.execute("BEGIN IMMEDIATE")
        try:
            estornar_movimentacao(c.db, c.usuario, m, justificativa)
            c.db.commit()
        except Exception:
            c.db.rollback()
            raise
    return carregar_movimentacao(c.db, mid)


def estornar_movimentacao(db, usuario, m, justificativa):
    """Desfaz estoque, IMEIs e financeiro de uma movimentação. Roda dentro de uma transação aberta."""
    mid = m["id"]
    if m["cancelada"]:
        raise Erro("Esta movimentação já foi cancelada.")
    for i in m["itens"]:
        if m["tipo"] == "entrada":
            p = um(db, "SELECT estoque_atual FROM produtos WHERE id = ?", (i["produto_id"],))
            if p["estoque_atual"] < i["quantidade"]:
                raise Erro(f"Não dá para cancelar: parte de {i['produto_nome']} já saiu do estoque.")
            for imei in i["imeis"]:
                reg = um(db, "SELECT * FROM imeis WHERE imei = ?", (imei,))
                if not reg or reg["status"] != "disponivel" or reg["entrada_id"] != mid:
                    raise Erro(f"Não dá para cancelar: o IMEI {imei} já saiu do estoque.")
                db.execute("UPDATE imeis SET status = 'cancelado', atualizado_em = ? WHERE imei = ?",
                           (agora(), imei))
            db.execute("UPDATE produtos SET estoque_atual = estoque_atual - ? WHERE id = ?",
                       (i["quantidade"], i["produto_id"]))
        else:
            for imei in i["imeis"]:
                reg = um(db, "SELECT * FROM imeis WHERE imei = ?", (imei,))
                if not reg or reg["saida_id"] != mid or reg["status"] == "disponivel":
                    raise Erro(f"Não dá para cancelar: o IMEI {imei} teve movimentação posterior.")
                db.execute("UPDATE imeis SET status = 'disponivel', saida_id = NULL, atualizado_em = ? "
                           "WHERE imei = ?", (agora(), imei))
            db.execute("UPDATE produtos SET estoque_atual = estoque_atual + ? WHERE id = ?",
                       (i["quantidade"], i["produto_id"]))
    for i in m["itens"]:
        if i["imeis"]:
            recalcular_custo_imei(db, i["produto_id"])
    db.execute("""UPDATE movimentacoes SET cancelada = 1, cancelada_em = ?, cancelada_por = ?,
                  motivo_cancelamento = ? WHERE id = ?""", (agora(), usuario["id"], justificativa, mid))
    db.execute("UPDATE financeiro SET cancelado = 1 WHERE movimentacao_id = ?", (mid,))
    db.execute("UPDATE orcamentos SET status = 'aprovado', movimentacao_id = NULL WHERE movimentacao_id = ?",
               (mid,))


# ---- ordens de serviço (assistência técnica)

def carregar_os(db, oid):
    o = um(db, """SELECT o.*, c.nome AS cliente_nome, c.telefone AS cliente_telefone, c.documento AS cliente_documento,
                         u.nome AS usuario_nome
                  FROM ordens_servico o JOIN clientes c ON c.id = o.cliente_id
                  JOIN usuarios u ON u.id = o.usuario_id WHERE o.id = ?""", (oid,))
    if not o:
        raise Erro("Ordem de serviço não encontrada.", 404)
    o["servicos"] = dicts(db.execute("SELECT * FROM os_servicos WHERE os_id = ? ORDER BY id", (oid,)))
    o["pecas"] = dicts(db.execute(
        """SELECT op.*, p.nome AS produto_nome, p.estoque_atual FROM os_pecas op
           JOIN produtos p ON p.id = op.produto_id WHERE op.os_id = ? ORDER BY op.id""", (oid,)))
    o["historico"] = dicts(db.execute(
        """SELECT h.*, u.nome AS usuario_nome FROM os_historico h JOIN usuarios u ON u.id = h.usuario_id
           WHERE h.os_id = ? ORDER BY h.id""", (oid,)))
    o["financeiro"] = dicts(db.execute("SELECT * FROM financeiro WHERE os_id = ? ORDER BY vencimento", (oid,)))
    return o


def ler_os(db, b):
    cliente_id = inteiro(b.get("cliente_id"), "cliente")
    if not db.execute("SELECT 1 FROM clientes WHERE id = ?", (cliente_id,)).fetchone():
        raise Erro("Escolha o cliente da ordem de serviço.")
    imei = re.sub(r"\D", "", str(b.get("imei") or ""))
    if imei and not imei_valido(imei):
        raise Erro("IMEI inválido. Confira os 15 dígitos (ou deixe em branco).")
    previsao = b.get("previsao")
    servicos = []
    for s_ in b.get("servicos") or []:
        desc = texto(s_.get("descricao"), "descrição do serviço", maximo=200)
        if desc:
            servicos.append((desc, dinheiro(s_.get("valor"), f"valor de {desc}")))
    pecas = []
    for p_ in b.get("pecas") or []:
        p = um(db, "SELECT * FROM produtos WHERE id = ?", (inteiro(p_.get("produto_id"), "peça"),))
        if not p:
            raise Erro("Peça não encontrada.")
        if p["controla_imei"]:
            raise Erro(f"{p['nome']} é controlado por IMEI e não pode ser usado como peça.")
        pecas.append((p["id"], inteiro(p_.get("quantidade") or 1, f"quantidade de {p['nome']}", 1, 1000),
                      dinheiro(p_.get("valor_unitario", p["preco_venda"]), f"valor de {p['nome']}")))
    v_serv = round(sum(v for _, v in servicos), 2)
    v_pecas = round(sum(q * v for _, q, v in pecas), 2)
    desconto = dinheiro(b.get("desconto"), "desconto")
    if desconto > v_serv + v_pecas:
        raise Erro("O desconto não pode ser maior que o total da OS.")
    dados = {
        "cliente_id": cliente_id,
        "tecnico": texto(b.get("tecnico"), "técnico", maximo=80),
        "aparelho": texto(b.get("aparelho"), "aparelho", True, 120),
        "imei": imei, "cor": texto(b.get("cor"), "cor", maximo=40),
        "senha_desbloqueio": texto(b.get("senha_desbloqueio"), "senha/padrão", maximo=60),
        "acessorios": texto(b.get("acessorios"), "acessórios", maximo=300),
        "defeito": texto(b.get("defeito"), "defeito relatado", True, 1000),
        "laudo": texto(b.get("laudo"), "laudo técnico", maximo=2000),
        "previsao": data_iso(previsao, "previsão") if previsao else None,
        "garantia_dias": inteiro(b.get("garantia_dias") if b.get("garantia_dias") not in (None, "") else 90,
                                 "garantia (dias)", 0, 3650),
        "observacao": texto(b.get("observacao"), "observação", maximo=1000),
        "valor_servicos": v_serv, "valor_pecas": v_pecas, "desconto": desconto,
        "total": round(v_serv + v_pecas - desconto, 2),
    }
    return dados, servicos, pecas


def salvar_itens_os(db, oid, servicos, pecas):
    db.execute("DELETE FROM os_servicos WHERE os_id = ?", (oid,))
    db.execute("DELETE FROM os_pecas WHERE os_id = ?", (oid,))
    db.executemany("INSERT INTO os_servicos (os_id, descricao, valor) VALUES (?,?,?)",
                   [(oid, d, v) for d, v in servicos])
    db.executemany("INSERT INTO os_pecas (os_id, produto_id, quantidade, valor_unitario) VALUES (?,?,?,?)",
                   [(oid, p, q, v) for p, q, v in pecas])


@rota("GET", "/api/os")
def listar_os(c):
    where, args = [], []
    st = c.q("status")
    if st == "abertas":
        where.append("o.status NOT IN ('Entregue', 'Cancelada')")
    elif st:
        where.append("o.status = ?")
        args.append(st)
    if c.q("inicio") or c.q("fim"):
        inicio, fim = periodo(c)
        where.append("date(o.entrada_em) BETWEEN ? AND ?")
        args += [inicio, fim]
    if c.q("q"):
        like = f"%{c.q('q')}%"
        where.append("(c.nome LIKE ? OR o.aparelho LIKE ? OR o.imei LIKE ? OR CAST(o.id AS TEXT) = ? OR c.telefone LIKE ?)")
        args += [like, like, like, c.q("q"), like]
    return dicts(c.db.execute(
        f"""SELECT o.id, o.status, o.aparelho, o.imei, o.defeito, o.tecnico, o.previsao, o.total, o.entrada_em,
                   o.entregue_em, c.nome AS cliente_nome, c.telefone AS cliente_telefone
            FROM ordens_servico o JOIN clientes c ON c.id = o.cliente_id
            {"WHERE " + " AND ".join(where) if where else ""} ORDER BY o.id DESC LIMIT 1000""", args))


@rota("GET", r"/api/os/(\d+)")
def detalhe_os(c):
    return carregar_os(c.db, int(c.params[0]))


@rota("POST", "/api/os")
def criar_os(c):
    dados, servicos, pecas = ler_os(c.db, c.corpo)
    with ESCRITA:
        try:
            cur = c.db.execute(
                f"""INSERT INTO ordens_servico ({", ".join(dados)}, usuario_id, status, entrada_em, atualizado_em)
                    VALUES ({", ".join("?" * len(dados))}, ?, 'Aberta', ?, ?)""",
                (*dados.values(), c.usuario["id"], agora(), agora()))
            oid = cur.lastrowid
            salvar_itens_os(c.db, oid, servicos, pecas)
            c.db.execute("INSERT INTO os_historico (os_id, data, status, nota, usuario_id) VALUES (?,?,?,?,?)",
                         (oid, agora(), "Aberta", "Aparelho recebido", c.usuario["id"]))
            c.db.commit()
        except Exception:
            c.db.rollback()
            raise
    return carregar_os(c.db, oid)


@rota("PUT", r"/api/os/(\d+)")
def editar_os(c):
    oid = int(c.params[0])
    atual = carregar_os(c.db, oid)
    if atual["status"] in STATUS_OS_FINAIS:
        raise Erro(f"OS {atual['status'].lower()} não pode ser alterada.")
    dados, servicos, pecas = ler_os(c.db, c.corpo)
    with ESCRITA:
        try:
            c.db.execute(f"UPDATE ordens_servico SET {', '.join(k + ' = ?' for k in dados)}, atualizado_em = ? "
                         f"WHERE id = ?", (*dados.values(), agora(), oid))
            salvar_itens_os(c.db, oid, servicos, pecas)
            c.db.commit()
        except Exception:
            c.db.rollback()
            raise
    return carregar_os(c.db, oid)


@rota("POST", r"/api/os/(\d+)/status")
def status_os(c):
    oid = int(c.params[0])
    atual = carregar_os(c.db, oid)
    if atual["status"] in STATUS_OS_FINAIS:
        raise Erro(f"OS {atual['status'].lower()} não pode mudar de situação.")
    novo = opcao(c.corpo.get("status"), "situação", [s for s in STATUS_OS if s not in STATUS_OS_FINAIS])
    nota = texto(c.corpo.get("nota"), "anotação", maximo=500)
    with ESCRITA:
        c.db.execute("UPDATE ordens_servico SET status = ?, atualizado_em = ? WHERE id = ?", (novo, agora(), oid))
        c.db.execute("INSERT INTO os_historico (os_id, data, status, nota, usuario_id) VALUES (?,?,?,?,?)",
                     (oid, agora(), novo, nota, c.usuario["id"]))
        c.db.commit()
    return carregar_os(c.db, oid)


@rota("POST", r"/api/os/(\d+)/entregar")
def entregar_os(c):
    """Entrega o aparelho: baixa as peças do estoque e lança o valor em contas a receber."""
    oid = int(c.params[0])
    o = carregar_os(c.db, oid)
    if o["status"] in STATUS_OS_FINAIS:
        raise Erro(f"Esta OS já está {o['status'].lower()}.")
    b = c.corpo
    forma = opcao(b.get("forma_pagamento"), "forma de pagamento", PAGAMENTOS) if o["total"] > 0 else None
    momento = agora()
    parcelas, primeiro = ler_condicao(b, dt.date.today(), forma == "Crediário")
    if o["total"] > 0 and config(c.db, "exigir_caixa") == "1" and not caixa_aberto(c.db):
        raise Erro("Abra o caixa antes de receber (menu Financeiro → Caixa).")
    nota = texto(b.get("nota"), "anotação", maximo=500)

    def finalizar(db, mid, _total):
        if o["total"] > 0:
            cred = forma == "Crediário"
            gerar_financeiro(db, c.usuario, "receber", f"OS #{oid} — {o['aparelho']}", "Serviços (OS)", o["total"],
                             forma, parcelas if cred else 1, primeiro, None if cred else momento,
                             cliente_id=o["cliente_id"], movimentacao_id=mid, os_id=oid)
        db.execute("""UPDATE ordens_servico SET status = 'Entregue', entregue_em = ?, forma_pagamento = ?,
                      movimentacao_id = ?, atualizado_em = ? WHERE id = ?""", (momento, forma, mid, momento, oid))
        db.execute("INSERT INTO os_historico (os_id, data, status, nota, usuario_id) VALUES (?,?,?,?,?)",
                   (oid, momento, "Entregue", nota or "Aparelho entregue ao cliente", c.usuario["id"]))

    if o["pecas"]:
        registrar_movimentacao(c.db, c.usuario, {
            "tipo": "saida", "motivo": "Ordem de serviço", "cliente_id": o["cliente_id"], "documento": f"OS #{oid}",
            "itens": [{"produto_id": p["produto_id"], "quantidade": p["quantidade"],
                       "valor_unitario": p["valor_unitario"]} for p in o["pecas"]]},
            interno=True, depois=finalizar)
    else:
        with ESCRITA:
            c.db.execute("BEGIN IMMEDIATE")
            try:
                finalizar(c.db, None, 0)
                c.db.commit()
            except Exception:
                c.db.rollback()
                raise
    return carregar_os(c.db, oid)


@rota("POST", r"/api/os/(\d+)/cancelar")
def cancelar_os(c):
    oid = int(c.params[0])
    o = carregar_os(c.db, oid)
    motivo = texto(c.corpo.get("motivo"), "motivo do cancelamento", True, 300)
    if o["status"] == "Cancelada":
        raise Erro("Esta OS já está cancelada.")
    if o["status"] == "Entregue" and not c.admin:
        raise Erro("Apenas administradores podem cancelar uma OS já entregue.", 403)
    with ESCRITA:
        c.db.execute("BEGIN IMMEDIATE")
        try:
            if o["movimentacao_id"]:
                estornar_movimentacao(c.db, c.usuario, carregar_movimentacao(c.db, o["movimentacao_id"]),
                                      f"Cancelamento da OS #{oid}: {motivo}")
            c.db.execute("UPDATE financeiro SET cancelado = 1 WHERE os_id = ?", (oid,))
            c.db.execute("UPDATE ordens_servico SET status = 'Cancelada', atualizado_em = ? WHERE id = ?",
                         (agora(), oid))
            c.db.execute("INSERT INTO os_historico (os_id, data, status, nota, usuario_id) VALUES (?,?,?,?,?)",
                         (oid, agora(), "Cancelada", motivo, c.usuario["id"]))
            c.db.commit()
        except Exception:
            c.db.rollback()
            raise
    return carregar_os(c.db, oid)


# ---- orçamentos

def carregar_orcamento(db, oid):
    o = um(db, """SELECT o.*, c.nome AS cliente_nome, c.telefone AS cliente_telefone, c.documento AS cliente_documento,
                         u.nome AS usuario_nome FROM orcamentos o JOIN usuarios u ON u.id = o.usuario_id
                  LEFT JOIN clientes c ON c.id = o.cliente_id WHERE o.id = ?""", (oid,))
    if not o:
        raise Erro("Orçamento não encontrado.", 404)
    o["itens"] = dicts(db.execute(
        """SELECT i.*, p.nome AS produto_nome, p.estoque_atual, p.controla_imei FROM orcamento_itens i
           JOIN produtos p ON p.id = i.produto_id WHERE i.orcamento_id = ? ORDER BY i.id""", (oid,)))
    return o


def ler_orcamento(db, b):
    cliente_id = inteiro(b.get("cliente_id"), "cliente") or None
    if cliente_id and not db.execute("SELECT 1 FROM clientes WHERE id = ?", (cliente_id,)).fetchone():
        raise Erro("Cliente não encontrado.")
    itens = []
    for it in b.get("itens") or []:
        p = um(db, "SELECT * FROM produtos WHERE id = ?", (inteiro(it.get("produto_id"), "produto"),))
        if not p:
            raise Erro("Produto não encontrado.")
        itens.append((p["id"], inteiro(it.get("quantidade") or 1, f"quantidade de {p['nome']}", 1, 100_000),
                      dinheiro(it.get("valor_unitario", p["preco_venda"]), f"valor de {p['nome']}")))
    if not itens:
        raise Erro("Adicione pelo menos um produto ao orçamento.")
    subtotal = round(sum(q * v for _, q, v in itens), 2)
    desconto = dinheiro(b.get("desconto"), "desconto")
    if desconto > subtotal:
        raise Erro("O desconto não pode ser maior que o subtotal.")
    dias = inteiro(config(db, "validade_orcamento_dias") or 7, "validade", 0, 3650)
    validade = data_iso(b.get("validade") or (dt.date.today() + dt.timedelta(days=dias)).isoformat(), "validade")
    return {"cliente_id": cliente_id, "validade": validade, "subtotal": subtotal, "desconto": desconto,
            "total": round(subtotal - desconto, 2),
            "observacao": texto(b.get("observacao"), "observação", maximo=1000)}, itens


@rota("GET", "/api/orcamentos")
def listar_orcamentos(c):
    where, args = [], []
    if c.q("status"):
        where.append("o.status = ?")
        args.append(c.q("status"))
    if c.q("q"):
        like = f"%{c.q('q')}%"
        where.append("(c.nome LIKE ? OR CAST(o.id AS TEXT) = ?)")
        args += [like, c.q("q")]
    return dicts(c.db.execute(
        f"""SELECT o.id, o.data, o.validade, o.status, o.total, o.movimentacao_id, c.nome AS cliente_nome,
                   u.nome AS usuario_nome,
                   (SELECT GROUP_CONCAT(p.nome, ', ') FROM orcamento_itens i JOIN produtos p ON p.id = i.produto_id
                    WHERE i.orcamento_id = o.id) AS produtos
            FROM orcamentos o JOIN usuarios u ON u.id = o.usuario_id LEFT JOIN clientes c ON c.id = o.cliente_id
            {"WHERE " + " AND ".join(where) if where else ""} ORDER BY o.id DESC LIMIT 1000""", args))


@rota("GET", r"/api/orcamentos/(\d+)")
def detalhe_orcamento(c):
    return carregar_orcamento(c.db, int(c.params[0]))


@rota("POST", "/api/orcamentos")
def criar_orcamento(c):
    d, itens = ler_orcamento(c.db, c.corpo)
    with ESCRITA:
        cur = c.db.execute(
            f"""INSERT INTO orcamentos ({", ".join(d)}, usuario_id, data, status)
                VALUES ({", ".join("?" * len(d))}, ?, ?, 'aberto')""", (*d.values(), c.usuario["id"], agora()))
        c.db.executemany("INSERT INTO orcamento_itens (orcamento_id, produto_id, quantidade, valor_unitario) "
                         "VALUES (?,?,?,?)", [(cur.lastrowid, *i) for i in itens])
        c.db.commit()
    return carregar_orcamento(c.db, cur.lastrowid)


@rota("PUT", r"/api/orcamentos/(\d+)")
def editar_orcamento(c):
    oid = int(c.params[0])
    if carregar_orcamento(c.db, oid)["status"] == "convertido":
        raise Erro("Orçamento já convertido em venda não pode ser alterado.")
    d, itens = ler_orcamento(c.db, c.corpo)
    with ESCRITA:
        c.db.execute(f"UPDATE orcamentos SET {', '.join(k + ' = ?' for k in d)} WHERE id = ?", (*d.values(), oid))
        c.db.execute("DELETE FROM orcamento_itens WHERE orcamento_id = ?", (oid,))
        c.db.executemany("INSERT INTO orcamento_itens (orcamento_id, produto_id, quantidade, valor_unitario) "
                         "VALUES (?,?,?,?)", [(oid, *i) for i in itens])
        c.db.commit()
    return carregar_orcamento(c.db, oid)


@rota("POST", r"/api/orcamentos/(\d+)/status")
def status_orcamento(c):
    oid = int(c.params[0])
    if carregar_orcamento(c.db, oid)["status"] == "convertido":
        raise Erro("Orçamento já convertido em venda.")
    novo = opcao(c.corpo.get("status"), "situação", ["aberto", "aprovado", "recusado"])
    with ESCRITA:
        c.db.execute("UPDATE orcamentos SET status = ? WHERE id = ?", (novo, oid))
        c.db.commit()
    return carregar_orcamento(c.db, oid)


# ---- financeiro: contas a pagar e a receber

FIN_SELECT = """SELECT f.*, c.nome AS cliente_nome, fo.nome AS fornecedor_nome,
                       CASE WHEN f.pago_em IS NOT NULL THEN 'pago'
                            WHEN f.vencimento < date('now', 'localtime') THEN 'vencido' ELSE 'pendente' END AS situacao
                FROM financeiro f LEFT JOIN clientes c ON c.id = f.cliente_id
                LEFT JOIN fornecedores fo ON fo.id = f.fornecedor_id"""


@rota("GET", "/api/financeiro", "admin")
def listar_financeiro(c):
    where, args = ["f.cancelado = 0"], []
    if c.q("tipo"):
        where.append("f.tipo = ?")
        args.append(opcao(c.q("tipo"), "tipo", ["receber", "pagar"]))
    st = c.q("situacao") or "abertos"
    inicio, fim = periodo(c) if (c.q("inicio") or c.q("fim")) else (None, None)
    if st == "pagos":
        where.append("f.pago_em IS NOT NULL")
        if inicio:
            where.append("date(f.pago_em) BETWEEN ? AND ?")
            args += [inicio, fim]
    else:
        if st == "abertos":
            where.append("f.pago_em IS NULL")
        elif st == "vencidos":
            where.append("f.pago_em IS NULL AND f.vencimento < date('now', 'localtime')")
        if inicio:
            where.append("f.vencimento BETWEEN ? AND ?")
            args += [inicio, fim]
    if c.q("q"):
        like = f"%{c.q('q')}%"
        where.append("(f.descricao LIKE ? OR c.nome LIKE ? OR fo.nome LIKE ? OR f.categoria LIKE ?)")
        args += [like] * 4
    return dicts(c.db.execute(f"{FIN_SELECT} WHERE {' AND '.join(where)} ORDER BY "
                              f"{'f.pago_em DESC' if st == 'pagos' else 'f.vencimento, f.id'} LIMIT 2000", args))


@rota("POST", "/api/financeiro", "admin")
def criar_financeiro(c):
    b = c.corpo
    tipo = opcao(b.get("tipo"), "tipo", ["receber", "pagar"])
    valor = dinheiro(b.get("valor"), "valor")
    if valor <= 0:
        raise Erro("Informe o valor.")
    venc = dt.date.fromisoformat(data_iso(b.get("vencimento") or dt.date.today().isoformat(), "vencimento"))
    parcelas = inteiro(b.get("parcelas") or 1, "parcelas", 1, 120)
    pago = b.get("pago") in (True, 1, "1", "true")
    forma = opcao(b.get("forma_pagamento"), "forma de pagamento", PAGAMENTOS) if b.get("forma_pagamento") else None
    cliente_id = inteiro(b.get("cliente_id"), "cliente") or None
    fornecedor_id = inteiro(b.get("fornecedor_id"), "fornecedor") or None
    total = round(valor * parcelas, 2) if b.get("repetir") in (True, 1, "1", "true") else valor
    with ESCRITA:
        gerar_financeiro(c.db, c.usuario, tipo, texto(b.get("descricao"), "descrição", True),
                         opcao(b.get("categoria"), "categoria", CATEGORIAS_FIN[tipo]), total, forma, parcelas, venc,
                         agora() if pago and parcelas == 1 else None, cliente_id=cliente_id,
                         fornecedor_id=fornecedor_id, observacao=texto(b.get("observacao"), "observação", maximo=500))
        c.db.commit()
    return {"ok": True}


def fin_editavel(db, fid):
    f = um(db, "SELECT * FROM financeiro WHERE id = ?", (fid,))
    if not f or f["cancelado"]:
        raise Erro("Lançamento não encontrado.", 404)
    return f


@rota("PUT", r"/api/financeiro/(\d+)", "admin")
def editar_financeiro(c):
    fid = int(c.params[0])
    f = fin_editavel(c.db, fid)
    if f["pago_em"]:
        raise Erro("Estorne a baixa antes de editar este lançamento.")
    b = c.corpo
    valor = dinheiro(b.get("valor", f["valor"]), "valor")
    if valor <= 0:
        raise Erro("Informe o valor.")
    with ESCRITA:
        c.db.execute("""UPDATE financeiro SET descricao = ?, categoria = ?, valor = ?, vencimento = ?, observacao = ?
                        WHERE id = ?""",
                     (texto(b.get("descricao", f["descricao"]), "descrição", True),
                      opcao(b.get("categoria", f["categoria"]), "categoria", CATEGORIAS_FIN[f["tipo"]]), valor,
                      data_iso(b.get("vencimento", f["vencimento"]), "vencimento"),
                      texto(b.get("observacao", f["observacao"]), "observação", maximo=500), fid))
        c.db.commit()
    return um(c.db, f"{FIN_SELECT} WHERE f.id = ?", (fid,))


@rota("POST", r"/api/financeiro/(\d+)/baixar", "admin")
def baixar_financeiro(c):
    fid = int(c.params[0])
    f = fin_editavel(c.db, fid)
    if f["pago_em"]:
        raise Erro("Este lançamento já está quitado.")
    dia = data_iso(c.corpo.get("data") or dt.date.today().isoformat(), "data do pagamento")
    momento = agora() if dia == dt.date.today().isoformat() else f"{dia} 12:00:00"
    forma = opcao(c.corpo.get("forma_pagamento") or f["forma_pagamento"] or "Dinheiro", "forma de pagamento",
                  PAGAMENTOS)
    with ESCRITA:
        c.db.execute("UPDATE financeiro SET pago_em = ?, forma_pagamento = ? WHERE id = ?", (momento, forma, fid))
        c.db.commit()
    return um(c.db, f"{FIN_SELECT} WHERE f.id = ?", (fid,))


@rota("POST", r"/api/financeiro/(\d+)/estornar", "admin")
def estornar_financeiro(c):
    fid = int(c.params[0])
    fin_editavel(c.db, fid)
    with ESCRITA:
        c.db.execute("UPDATE financeiro SET pago_em = NULL WHERE id = ?", (fid,))
        c.db.commit()
    return um(c.db, f"{FIN_SELECT} WHERE f.id = ?", (fid,))


@rota("DELETE", r"/api/financeiro/(\d+)", "admin")
def excluir_financeiro(c):
    f = fin_editavel(c.db, int(c.params[0]))
    if f["movimentacao_id"] or f["os_id"]:
        raise Erro("Este lançamento veio de uma venda, compra ou OS: cancele pela origem.")
    with ESCRITA:
        c.db.execute("UPDATE financeiro SET cancelado = 1 WHERE id = ?", (f["id"],))
        c.db.commit()
    return {"ok": True}


@rota("GET", "/api/relatorios/financeiro", "admin")
def relatorio_financeiro(c):
    inicio, fim = periodo(c)
    args = (inicio, fim)
    realizado = {r["dia"]: r for r in c.db.execute(
        """SELECT date(pago_em) AS dia, SUM(CASE WHEN tipo = 'receber' THEN valor ELSE 0 END) AS entradas,
                  SUM(CASE WHEN tipo = 'pagar' THEN valor ELSE 0 END) AS saidas
           FROM financeiro WHERE cancelado = 0 AND pago_em IS NOT NULL AND date(pago_em) BETWEEN ? AND ?
           GROUP BY dia""", args)}
    previsto = {r["dia"]: r for r in c.db.execute(
        """SELECT vencimento AS dia, SUM(CASE WHEN tipo = 'receber' THEN valor ELSE 0 END) AS entradas,
                  SUM(CASE WHEN tipo = 'pagar' THEN valor ELSE 0 END) AS saidas
           FROM financeiro WHERE cancelado = 0 AND pago_em IS NULL AND vencimento BETWEEN ? AND ?
           GROUP BY dia""", args)}
    saldo_anterior = um(c.db, """SELECT COALESCE(SUM(CASE WHEN tipo = 'receber' THEN valor ELSE -valor END), 0) AS s
                                 FROM financeiro WHERE cancelado = 0 AND pago_em IS NOT NULL
                                 AND date(pago_em) < ?""", (inicio,))["s"]
    try:
        saldo_anterior += float(config(c.db, "saldo_inicial") or 0)
    except ValueError:
        pass
    dias, saldo, d = [], saldo_anterior, dt.date.fromisoformat(inicio)
    while d <= dt.date.fromisoformat(fim) and len(dias) < 1000:
        k = d.isoformat()
        r, p = realizado.get(k), previsto.get(k)
        ent, sai = (r["entradas"], r["saidas"]) if r else (0, 0)
        saldo += ent - sai
        dias.append({"dia": k, "entradas": round(ent, 2), "saidas": round(sai, 2), "saldo": round(saldo, 2),
                     "a_receber": round(p["entradas"], 2) if p else 0, "a_pagar": round(p["saidas"], 2) if p else 0})
        d += dt.timedelta(days=1)
    categorias = dicts(c.db.execute(
        """SELECT tipo, categoria AS chave, COUNT(*) AS lancamentos, ROUND(SUM(valor), 2) AS valor
           FROM financeiro WHERE cancelado = 0 AND pago_em IS NOT NULL AND date(pago_em) BETWEEN ? AND ?
           GROUP BY tipo, categoria ORDER BY tipo DESC, valor DESC""", args))
    receitas = sum(x["valor"] for x in categorias if x["tipo"] == "receber")
    despesas = sum(x["valor"] for x in categorias if x["tipo"] == "pagar")
    abertos = um(c.db, """SELECT
            ROUND(COALESCE(SUM(CASE WHEN tipo = 'receber' THEN valor END), 0), 2) AS a_receber,
            ROUND(COALESCE(SUM(CASE WHEN tipo = 'pagar' THEN valor END), 0), 2) AS a_pagar,
            ROUND(COALESCE(SUM(CASE WHEN tipo = 'receber' AND vencimento < date('now','localtime') THEN valor END), 0), 2)
              AS receber_vencido,
            ROUND(COALESCE(SUM(CASE WHEN tipo = 'pagar' AND vencimento < date('now','localtime') THEN valor END), 0), 2)
              AS pagar_vencido
        FROM financeiro WHERE cancelado = 0 AND pago_em IS NULL""")
    # DRE simplificado (regime de competência das vendas + despesas pagas no período)
    vendas = resumo_vendas(c.db, inicio, fim)
    os_ = um(c.db, """SELECT COUNT(*) AS qtd, COALESCE(SUM(total), 0) AS receita FROM ordens_servico
                      WHERE status = 'Entregue' AND date(entregue_em) BETWEEN ? AND ?""", args)
    custo_pecas = um(c.db, """SELECT COALESCE(SUM(i.custo_total), 0) AS c FROM itens i
                              JOIN movimentacoes m ON m.id = i.movimentacao_id
                              WHERE m.motivo = 'Ordem de serviço' AND m.cancelada = 0
                              AND date(m.data) BETWEEN ? AND ?""", args)["c"]
    desp_operacionais = sum(x["valor"] for x in categorias
                            if x["tipo"] == "pagar" and x["chave"] != "Compra de mercadorias")
    receita_bruta = vendas["faturamento"] + os_["receita"]
    lucro_bruto = receita_bruta - vendas["custo"] - custo_pecas
    dre = [
        {"linha": "Receita com vendas de produtos", "valor": vendas["faturamento"]},
        {"linha": "Receita com serviços (OS entregues)", "valor": os_["receita"]},
        {"linha": "(−) Custo das mercadorias vendidas", "valor": -vendas["custo"]},
        {"linha": "(−) Custo das peças usadas em OS", "valor": -custo_pecas},
        {"linha": "= Lucro bruto", "valor": lucro_bruto, "total": True},
        {"linha": "(−) Despesas operacionais pagas", "valor": -desp_operacionais},
        {"linha": "= Resultado do período", "valor": lucro_bruto - desp_operacionais, "total": True},
    ]
    for l_ in dre:
        l_["valor"] = round(l_["valor"], 2)
    return {"inicio": inicio, "fim": fim, "saldo_anterior": round(saldo_anterior, 2), "dias": dias,
            "categorias": categorias, "receitas": round(receitas, 2), "despesas": round(despesas, 2),
            "saldo_final": round(saldo, 2), "abertos": abertos, "dre": dre}


@rota("GET", "/api/relatorios/os")
def relatorio_os(c):
    inicio, fim = periodo(c)
    args = (inicio, fim)
    return {
        "inicio": inicio, "fim": fim,
        "resumo": um(c.db, """SELECT COUNT(*) AS abertas_periodo,
                SUM(CASE WHEN status = 'Entregue' THEN 1 ELSE 0 END) AS entregues,
                SUM(CASE WHEN status = 'Cancelada' THEN 1 ELSE 0 END) AS canceladas
                FROM ordens_servico WHERE date(entrada_em) BETWEEN ? AND ?""", args),
        "faturamento": um(c.db, """SELECT COUNT(*) AS qtd, ROUND(COALESCE(SUM(total), 0), 2) AS total,
                ROUND(COALESCE(SUM(valor_servicos), 0), 2) AS servicos, ROUND(COALESCE(SUM(valor_pecas), 0), 2) AS pecas,
                ROUND(AVG(julianday(entregue_em) - julianday(entrada_em)), 1) AS prazo_medio
                FROM ordens_servico WHERE status = 'Entregue' AND date(entregue_em) BETWEEN ? AND ?""", args),
        "por_status": dicts(c.db.execute(
            """SELECT status AS chave, COUNT(*) AS quantidade FROM ordens_servico
               WHERE status NOT IN ('Entregue', 'Cancelada') GROUP BY status ORDER BY quantidade DESC""")),
        "por_tecnico": dicts(c.db.execute(
            """SELECT COALESCE(NULLIF(tecnico, ''), 'Sem técnico') AS chave, COUNT(*) AS quantidade,
                      ROUND(SUM(total), 2) AS faturamento FROM ordens_servico
               WHERE status = 'Entregue' AND date(entregue_em) BETWEEN ? AND ? GROUP BY chave
               ORDER BY faturamento DESC""", args)),
        "servicos": dicts(c.db.execute(
            """SELECT s.descricao AS chave, COUNT(*) AS quantidade, ROUND(SUM(s.valor), 2) AS faturamento
               FROM os_servicos s JOIN ordens_servico o ON o.id = s.os_id
               WHERE o.status = 'Entregue' AND date(o.entregue_em) BETWEEN ? AND ?
               GROUP BY s.descricao ORDER BY faturamento DESC LIMIT 50""", args)),
    }


# ---- caixa (abertura, sangria, suprimento e fechamento)

def resumo_caixa(db, cx):
    fim = cx["fechado_em"] or "9999-12-31"
    args = (cx["aberto_em"], fim)
    formas = dicts(db.execute(
        """SELECT forma_pagamento AS chave,
                  ROUND(SUM(CASE WHEN tipo = 'receber' THEN valor ELSE 0 END), 2) AS recebido,
                  ROUND(SUM(CASE WHEN tipo = 'pagar' THEN valor ELSE 0 END), 2) AS pago
           FROM financeiro WHERE cancelado = 0 AND pago_em >= ? AND pago_em <= ?
           GROUP BY forma_pagamento ORDER BY recebido DESC""", args))
    movs = dicts(db.execute(
        """SELECT cm.*, u.nome AS usuario_nome FROM caixa_movimentos cm JOIN usuarios u ON u.id = cm.usuario_id
           WHERE cm.caixa_id = ? ORDER BY cm.id""", (cx["id"],)))
    din = next((f for f in formas if f["chave"] == "Dinheiro"), {"recebido": 0, "pago": 0})
    sup = sum(m["valor"] for m in movs if m["tipo"] == "suprimento")
    san = sum(m["valor"] for m in movs if m["tipo"] == "sangria")
    esperado = round(cx["saldo_inicial"] + din["recebido"] - din["pago"] + sup - san, 2)
    lanc = dicts(db.execute(
        f"""{FIN_SELECT} WHERE f.cancelado = 0 AND f.pago_em >= ? AND f.pago_em <= ? ORDER BY f.pago_em""", args))
    return {**cx, "formas": formas, "movimentos": movs, "suprimentos": round(sup, 2), "sangrias": round(san, 2),
            "dinheiro_recebido": din["recebido"], "dinheiro_pago": din["pago"], "esperado_dinheiro": esperado,
            "total_recebido": round(sum(f["recebido"] for f in formas), 2), "lancamentos": lanc}


@rota("GET", "/api/caixa")
def ver_caixa(c):
    cx = caixa_aberto(c.db)
    return {"atual": resumo_caixa(c.db, cx) if cx else None,
            "historico": dicts(c.db.execute(
                """SELECT cx.*, ua.nome AS aberto_por_nome, uf.nome AS fechado_por_nome FROM caixas cx
                   JOIN usuarios ua ON ua.id = cx.aberto_por LEFT JOIN usuarios uf ON uf.id = cx.fechado_por
                   ORDER BY cx.id DESC LIMIT 60"""))}


@rota("GET", r"/api/caixa/(\d+)")
def ver_caixa_id(c):
    cx = um(c.db, "SELECT * FROM caixas WHERE id = ?", (int(c.params[0]),))
    if not cx:
        raise Erro("Caixa não encontrado.", 404)
    return resumo_caixa(c.db, cx)


@rota("POST", "/api/caixa/abrir")
def abrir_caixa(c):
    with ESCRITA:
        if caixa_aberto(c.db):
            raise Erro("Já existe um caixa aberto.")
        c.db.execute("INSERT INTO caixas (aberto_em, aberto_por, saldo_inicial) VALUES (?,?,?)",
                     (agora(), c.usuario["id"], dinheiro(c.corpo.get("saldo_inicial"), "troco inicial")))
        c.db.commit()
    return ver_caixa(c)


@rota("POST", "/api/caixa/movimento")
def movimento_caixa(c):
    cx = caixa_aberto(c.db)
    if not cx:
        raise Erro("Não há caixa aberto.")
    valor = dinheiro(c.corpo.get("valor"), "valor")
    if valor <= 0:
        raise Erro("Informe o valor.")
    with ESCRITA:
        c.db.execute("INSERT INTO caixa_movimentos (caixa_id, tipo, valor, descricao, data, usuario_id) "
                     "VALUES (?,?,?,?,?,?)",
                     (cx["id"], opcao(c.corpo.get("tipo"), "tipo", ["suprimento", "sangria"]), valor,
                      texto(c.corpo.get("descricao"), "descrição", maximo=200), agora(), c.usuario["id"]))
        c.db.commit()
    return ver_caixa(c)


@rota("POST", "/api/caixa/fechar")
def fechar_caixa(c):
    cx = caixa_aberto(c.db)
    if not cx:
        raise Erro("Não há caixa aberto.")
    r = resumo_caixa(c.db, cx)
    with ESCRITA:
        c.db.execute("""UPDATE caixas SET fechado_em = ?, fechado_por = ?, saldo_esperado = ?, saldo_informado = ?,
                        observacao = ? WHERE id = ?""",
                     (agora(), c.usuario["id"], r["esperado_dinheiro"],
                      dinheiro(c.corpo.get("saldo_informado"), "valor contado"),
                      texto(c.corpo.get("observacao"), "observação", maximo=500), cx["id"]))
        c.db.commit()
    return ver_caixa_id(Req(c.db, c.usuario, {}, {}, (str(cx["id"]),), c.ip, c.caminho_db))


# ---- estoque: valor investido, idade, curva ABC, ficha (kardex) e inventário

FAIXAS_IDADE = [(0, 30, "Até 30 dias"), (31, 60, "31 a 60 dias"), (61, 90, "61 a 90 dias"),
                (91, 180, "91 a 180 dias"), (181, 10 ** 6, "Mais de 180 dias")]


def camadas_estoque(db, p):
    """De onde vem o saldo atual: cada aparelho (IMEI) ou lote de compra que ainda está na loja (PEPS)."""
    if p["controla_imei"]:
        return [{"quantidade": 1, "data": r["data"], "custo": r["custo"], "imei": r["imei"],
                 "entrada_id": r["entrada_id"], "fornecedor": r["fornecedor"]}
                for r in db.execute(
                    """SELECT x.imei, x.custo, x.entrada_id, COALESCE(m.data, x.atualizado_em) AS data,
                              f.nome AS fornecedor FROM imeis x
                       LEFT JOIN movimentacoes m ON m.id = x.entrada_id
                       LEFT JOIN fornecedores f ON f.id = m.fornecedor_id
                       WHERE x.produto_id = ? AND x.status = 'disponivel' ORDER BY data""", (p["id"],))]
    falta, camadas = p["estoque_atual"], []
    for r in db.execute(
            """SELECT i.quantidade, i.custo_unitario, m.data, m.id, f.nome AS fornecedor FROM itens i
               JOIN movimentacoes m ON m.id = i.movimentacao_id LEFT JOIN fornecedores f ON f.id = m.fornecedor_id
               WHERE i.produto_id = ? AND m.tipo = 'entrada' AND m.cancelada = 0
               ORDER BY m.data DESC, m.id DESC""", (p["id"],)):
        if falta <= 0:
            break
        q = min(falta, r["quantidade"])
        camadas.append({"quantidade": q, "data": r["data"], "custo": r["custo_unitario"], "imei": None,
                        "entrada_id": r["id"], "fornecedor": r["fornecedor"]})
        falta -= q
    if falta > 0:
        camadas.append({"quantidade": falta, "data": None, "custo": p["preco_custo"], "imei": None,
                        "entrada_id": None, "fornecedor": None})
    return list(reversed(camadas))


def dias_desde(data, hoje):
    return (hoje - dt.date.fromisoformat(data[:10])).days if data else None


@rota("GET", "/api/estoque/painel", "admin")
def painel_estoque(c):
    hoje = dt.date.today()
    h90 = (hoje - dt.timedelta(days=89)).isoformat()
    vendidos = {r[0]: (r[1], r[2]) for r in c.db.execute(
        """SELECT i.produto_id, SUM(i.quantidade), SUM(i.custo_total) FROM itens i
           JOIN movimentacoes m ON m.id = i.movimentacao_id
           WHERE m.tipo = 'saida' AND m.motivo IN ('Venda', 'Ordem de serviço') AND m.cancelada = 0
           AND date(m.data) >= ? GROUP BY i.produto_id""", (h90,))}
    ultima = {r[0]: r[1] for r in c.db.execute(
        """SELECT i.produto_id, MAX(m.data) FROM itens i JOIN movimentacoes m ON m.id = i.movimentacao_id
           WHERE m.tipo = 'saida' AND m.motivo IN ('Venda', 'Ordem de serviço') AND m.cancelada = 0
           GROUP BY i.produto_id""")}
    produtos = dicts(c.db.execute(
        f"""SELECT p.*, ROUND({VALOR_CUSTO}, 2) AS valor_custo FROM produtos p WHERE p.ativo = 1 ORDER BY p.nome"""))
    faixas = [{"faixa": f[2], "unidades": 0, "valor": 0.0} for f in FAIXAS_IDADE]
    for p in produtos:
        p["valor_venda"] = round(p["estoque_atual"] * p["preco_venda"], 2)
        p["lucro_potencial"] = round(p["valor_venda"] - p["valor_custo"], 2)
        p["margem"] = round(100 * p["lucro_potencial"] / p["valor_venda"], 1) if p["valor_venda"] else None
        q90, cmv90 = vendidos.get(p["id"], (0, 0))
        p["vendidos_90d"] = q90
        p["cobertura_dias"] = round(p["estoque_atual"] / (q90 / 90)) if q90 and p["estoque_atual"] else None
        p["giro_90d"] = round(cmv90 / p["valor_custo"], 2) if p["valor_custo"] else None
        p["ultima_venda"] = ultima.get(p["id"])
        p["dias_sem_venda"] = dias_desde(p["ultima_venda"], hoje)
        idade_total, mais_antiga = 0, None
        for cm in camadas_estoque(c.db, p) if p["estoque_atual"] else []:
            dias = dias_desde(cm["data"], hoje) or 0
            idade_total += dias * cm["quantidade"]
            mais_antiga = max(mais_antiga or 0, dias)
            valor = cm["custo"] * cm["quantidade"] if p["controla_imei"] else p["preco_custo"] * cm["quantidade"]
            for f, (ini, fim, _) in zip(faixas, FAIXAS_IDADE):
                if ini <= dias <= fim:
                    f["unidades"] += cm["quantidade"]
                    f["valor"] += valor
        p["idade_media"] = round(idade_total / p["estoque_atual"]) if p["estoque_atual"] else None
        p["idade_maxima"] = mais_antiga
        # parado: está na loja há mais de 90 dias e não vendeu nada nesse tempo
        p["parado"] = bool(p["estoque_atual"] and (p["idade_media"] or 0) > 90
                           and (p["dias_sem_venda"] is None or p["dias_sem_venda"] > 90))
    for f in faixas:
        f["valor"] = round(f["valor"], 2)

    total = sum(p["valor_custo"] for p in produtos) or 0
    acumulado = 0
    for p in sorted(produtos, key=lambda x: -x["valor_custo"]):
        if p["valor_custo"] <= 0:
            p["classe"], p["pct"], p["pct_acumulado"] = None, 0, None
            continue
        acumulado += p["valor_custo"]
        p["pct"] = round(100 * p["valor_custo"] / total, 2)
        p["pct_acumulado"] = round(100 * acumulado / total, 2)
        anterior = p["pct_acumulado"] - p["pct"]
        p["classe"] = "A" if anterior < 80 else "B" if anterior < 95 else "C"

    def agrupar(campo):
        g = {}
        for p in produtos:
            k = p[campo] or "Não informado"
            x = g.setdefault(k, {"chave": k, "produtos": 0, "unidades": 0, "valor_custo": 0.0, "valor_venda": 0.0})
            x["produtos"] += 1
            x["unidades"] += p["estoque_atual"]
            x["valor_custo"] += p["valor_custo"]
            x["valor_venda"] += p["valor_venda"]
        lista = sorted(g.values(), key=lambda x: -x["valor_custo"])
        for x in lista:
            x["valor_custo"], x["valor_venda"] = round(x["valor_custo"], 2), round(x["valor_venda"], 2)
            x["pct"] = round(100 * x["valor_custo"] / total, 1) if total else 0
        return lista

    # evolução do valor investido: soma das entradas menos o custo das saídas, dia a dia
    deltas = dicts(c.db.execute(
        """SELECT date(m.data) AS dia,
                  SUM(CASE WHEN m.tipo = 'entrada' THEN i.custo_total
                           ELSE -i.custo_total END) AS valor,
                  SUM(CASE WHEN m.tipo = 'entrada' THEN i.quantidade ELSE -i.quantidade END) AS unidades
           FROM itens i JOIN movimentacoes m ON m.id = i.movimentacao_id
           WHERE m.cancelada = 0 GROUP BY dia ORDER BY dia"""))
    inicio_hist = hoje - dt.timedelta(days=89)
    valor = sum(d["valor"] for d in deltas if d["dia"] < inicio_hist.isoformat())
    unid = sum(d["unidades"] for d in deltas if d["dia"] < inicio_hist.isoformat())
    por_dia = {d["dia"]: d for d in deltas}
    historico, d = [], inicio_hist
    while d <= hoje:
        k = d.isoformat()
        if k in por_dia:
            valor += por_dia[k]["valor"]
            unid += por_dia[k]["unidades"]
        historico.append({"dia": k, "valor": round(valor, 2), "unidades": unid})
        d += dt.timedelta(days=1)

    mes = hoje.replace(day=1).isoformat()
    fluxo_mes = um(c.db, """SELECT
            ROUND(COALESCE(SUM(CASE WHEN m.tipo = 'entrada' AND m.motivo = 'Compra' THEN i.custo_total END), 0), 2) AS comprado,
            ROUND(COALESCE(SUM(CASE WHEN m.tipo = 'saida' AND m.motivo IN ('Venda', 'Ordem de serviço') THEN i.custo_total END), 0), 2) AS vendido_custo,
            ROUND(COALESCE(SUM(CASE WHEN m.tipo = 'saida' AND m.motivo NOT IN ('Venda', 'Ordem de serviço') THEN i.custo_total END), 0), 2) AS baixas_custo
        FROM itens i JOIN movimentacoes m ON m.id = i.movimentacao_id
        WHERE m.cancelada = 0 AND date(m.data) >= ?""", (mes,))
    com_estoque = [p for p in produtos if p["estoque_atual"] > 0]
    cmv_90 = sum(v[1] for v in vendidos.values())
    resumo = {
        "valor_custo": round(total, 2),
        "valor_venda": round(sum(p["valor_venda"] for p in produtos), 2),
        "unidades": sum(p["estoque_atual"] for p in produtos),
        "produtos": len(produtos), "com_estoque": len(com_estoque),
        "zerados": len(produtos) - len(com_estoque),
        "abaixo_minimo": sum(1 for p in produtos if p["estoque_minimo"] > 0 and p["estoque_atual"] <= p["estoque_minimo"]),
        "parado_90_valor": round(sum(p["valor_custo"] for p in com_estoque if p["parado"]), 2),
        "idade_media": round(sum((p["idade_media"] or 0) * p["valor_custo"] for p in com_estoque) / total) if total else 0,
        "cobertura_dias": round(total / (cmv_90 / 90)) if cmv_90 else None,
    }
    resumo["lucro_potencial"] = round(resumo["valor_venda"] - resumo["valor_custo"], 2)
    resumo["margem"] = round(100 * resumo["lucro_potencial"] / resumo["valor_venda"], 1) if resumo["valor_venda"] else 0
    return {"resumo": resumo, "produtos": produtos, "faixas": faixas, "historico": historico,
            "fluxo_mes": fluxo_mes, "por_categoria": agrupar("categoria"), "por_marca": agrupar("marca"),
            "por_condicao": agrupar("condicao"),
            "classes": [{"classe": k,
                         "produtos": sum(1 for p in produtos if p["classe"] == k),
                         "valor": round(sum(p["valor_custo"] for p in produtos if p["classe"] == k), 2)}
                        for k in "ABC"]}


@rota("GET", r"/api/produtos/(\d+)/ficha", "admin")
def ficha_estoque(c):
    """Kardex: cada entrada e saída do produto com o saldo em quantidade e em valor depois dela."""
    p = um(c.db, f"SELECT p.*, ROUND({VALOR_CUSTO}, 2) AS valor_custo FROM produtos p WHERE p.id = ?",
           (int(c.params[0]),))
    if not p:
        raise Erro("Produto não encontrado.", 404)
    linhas, saldo_q, saldo_v = [], 0, 0.0
    for r in c.db.execute(
            """SELECT m.id, m.tipo, m.motivo, m.data, m.documento, i.quantidade, i.custo_unitario, i.custo_total, i.valor_unitario,
                      i.imeis, COALESCE(c.nome, f.nome) AS parceiro
               FROM itens i JOIN movimentacoes m ON m.id = i.movimentacao_id
               LEFT JOIN clientes c ON c.id = m.cliente_id LEFT JOIN fornecedores f ON f.id = m.fornecedor_id
               WHERE i.produto_id = ? AND m.cancelada = 0 ORDER BY m.data, m.id""", (p["id"],)):
        r = dict(r)
        sinal = 1 if r["tipo"] == "entrada" else -1
        saldo_q += sinal * r["quantidade"]
        saldo_v += sinal * r["custo_total"]
        r.update(saldo_qtd=saldo_q, saldo_valor=round(saldo_v, 2),
                 custo_medio=round(saldo_v / saldo_q, 2) if saldo_q else 0,
                 valor_mov=round(r["custo_total"], 2), imeis=json.loads(r["imeis"]))
        linhas.append(r)
    hoje = dt.date.today()
    camadas = camadas_estoque(c.db, p)
    for cm in camadas:
        cm["dias"] = dias_desde(cm["data"], hoje)
        cm["preco_venda"] = p["preco_venda"]
    return {"produto": p, "kardex": linhas, "camadas": camadas}


# ---- inventário (contagem física)

def carregar_inventario(db, iid):
    inv = um(db, """SELECT v.*, u.nome AS usuario_nome, uf.nome AS finalizado_por_nome FROM inventarios v
                    JOIN usuarios u ON u.id = v.usuario_id LEFT JOIN usuarios uf ON uf.id = v.finalizado_por
                    WHERE v.id = ?""", (iid,))
    if not inv:
        raise Erro("Inventário não encontrado.", 404)
    itens = dicts(db.execute(
        """SELECT ii.*, p.nome, p.codigo, p.categoria, p.localizacao, p.controla_imei, p.estoque_atual
           FROM inventario_itens ii JOIN produtos p ON p.id = ii.produto_id
           WHERE ii.inventario_id = ? ORDER BY COALESCE(p.localizacao, ''), p.nome""", (iid,)))
    for i in itens:
        i["imeis_esperados"] = json.loads(i["imeis_esperados"])
        i["imeis_contados"] = json.loads(i["imeis_contados"])
        i["diferenca"] = None if i["contado"] is None else i["contado"] - i["esperado"]
        if i["controla_imei"] and i["contado"] is not None:
            i["imeis_faltando"] = [x for x in i["imeis_esperados"] if x not in i["imeis_contados"]]
            i["imeis_sobrando"] = [x for x in i["imeis_contados"] if x not in i["imeis_esperados"]]
        i["valor_diferenca"] = round((i["diferenca"] or 0) * i["custo"], 2)
    inv["itens"] = itens
    inv["resumo"] = {
        "produtos": len(itens), "contados": sum(1 for i in itens if i["contado"] is not None),
        "com_diferenca": sum(1 for i in itens if i["diferenca"]),
        "falta_unidades": -sum(i["diferenca"] for i in itens if i["diferenca"] and i["diferenca"] < 0),
        "sobra_unidades": sum(i["diferenca"] for i in itens if i["diferenca"] and i["diferenca"] > 0),
        "falta_valor": round(-sum(i["valor_diferenca"] for i in itens if i["valor_diferenca"] < 0), 2),
        "sobra_valor": round(sum(i["valor_diferenca"] for i in itens if i["valor_diferenca"] > 0), 2),
        "valor_esperado": round(sum(i["esperado"] * i["custo"] for i in itens), 2),
    }
    return inv


@rota("GET", "/api/inventarios", "admin")
def listar_inventarios(c):
    lista = dicts(c.db.execute(
        """SELECT v.id, v.criado_em, v.status, v.categoria, v.observacao, v.finalizado_em, u.nome AS usuario_nome
           FROM inventarios v JOIN usuarios u ON u.id = v.usuario_id ORDER BY v.id DESC LIMIT 200"""))
    for v in lista:
        v["resumo"] = carregar_inventario(c.db, v["id"])["resumo"]
    return lista


@rota("POST", "/api/inventarios", "admin")
def criar_inventario(c):
    if c.db.execute("SELECT 1 FROM inventarios WHERE status = 'aberto'").fetchone():
        raise Erro("Já existe um inventário em andamento. Finalize ou cancele antes de abrir outro.")
    categoria = c.corpo.get("categoria") or None
    if categoria:
        opcao(categoria, "categoria", CATEGORIAS)
    with ESCRITA:
        cur = c.db.execute("INSERT INTO inventarios (criado_em, usuario_id, categoria, observacao) VALUES (?,?,?,?)",
                           (agora(), c.usuario["id"], categoria, texto(c.corpo.get("observacao"), "observação", maximo=300)))
        iid = cur.lastrowid
        for p in dicts(c.db.execute("SELECT * FROM produtos WHERE ativo = 1" + (" AND categoria = ?" if categoria else ""),
                                    (categoria,) if categoria else ())):
            imeis = [r[0] for r in c.db.execute(
                "SELECT imei FROM imeis WHERE produto_id = ? AND status = 'disponivel' ORDER BY imei", (p["id"],))]
            c.db.execute("""INSERT INTO inventario_itens (inventario_id, produto_id, esperado, imeis_esperados, custo)
                            VALUES (?,?,?,?,?)""", (iid, p["id"], p["estoque_atual"], json.dumps(imeis), p["preco_custo"]))
        c.db.commit()
    return carregar_inventario(c.db, iid)


@rota("GET", r"/api/inventarios/(\d+)", "admin")
def detalhe_inventario(c):
    return carregar_inventario(c.db, int(c.params[0]))


@rota("PUT", r"/api/inventarios/(\d+)/contagem", "admin")
def salvar_contagem(c):
    iid = int(c.params[0])
    inv = carregar_inventario(c.db, iid)
    if inv["status"] != "aberto":
        raise Erro("Este inventário já foi encerrado.")
    por_produto = {i["produto_id"]: i for i in inv["itens"]}
    with ESCRITA:
        for it in c.corpo.get("itens") or []:
            i = por_produto.get(inteiro(it.get("produto_id"), "produto"))
            if not i:
                continue
            if i["controla_imei"]:
                imeis = sorted({re.sub(r"\D", "", str(x)) for x in (it.get("imeis") or []) if str(x).strip()})
                for x in imeis:
                    if not imei_valido(x):
                        raise Erro(f"IMEI inválido na contagem de {i['nome']}: {x}")
                contado = len(imeis) if it.get("contado") not in (None, "") or imeis else None
                c.db.execute("UPDATE inventario_itens SET contado = ?, imeis_contados = ? WHERE id = ?",
                             (contado, json.dumps(imeis), i["id"]))
            else:
                v = it.get("contado")
                contado = None if v in (None, "") else inteiro(v, f"contagem de {i['nome']}")
                c.db.execute("UPDATE inventario_itens SET contado = ? WHERE id = ?", (contado, i["id"]))
        c.db.commit()
    return carregar_inventario(c.db, iid)


@rota("POST", r"/api/inventarios/(\d+)/finalizar", "admin")
def finalizar_inventario(c):
    """Aplica as diferenças contadas como ajustes de inventário (entrada para sobras, saída para faltas)."""
    iid = int(c.params[0])
    inv = carregar_inventario(c.db, iid)
    if inv["status"] != "aberto":
        raise Erro("Este inventário já foi encerrado.")
    entradas, saidas = [], []
    for i in inv["itens"]:
        if i["contado"] is None or not (i["diferenca"] or i.get("imeis_faltando") or i.get("imeis_sobrando")):
            continue
        if i["controla_imei"]:
            faltando = [x for x in i["imeis_faltando"]
                        if c.db.execute("SELECT 1 FROM imeis WHERE imei = ? AND status = 'disponivel' AND produto_id = ?",
                                        (x, i["produto_id"])).fetchone()]
            sobrando = [x for x in i["imeis_sobrando"]
                        if not c.db.execute("SELECT 1 FROM imeis WHERE imei = ? AND status = 'disponivel'", (x,)).fetchone()]
            if faltando:
                saidas.append({"produto_id": i["produto_id"], "quantidade": len(faltando), "imeis": faltando})
            if sobrando:
                entradas.append({"produto_id": i["produto_id"], "quantidade": len(sobrando), "imeis": sobrando,
                                 "valor_unitario": i["custo"]})
        elif i["diferenca"] < 0:
            atual = um(c.db, "SELECT estoque_atual FROM produtos WHERE id = ?", (i["produto_id"],))["estoque_atual"]
            saidas.append({"produto_id": i["produto_id"], "quantidade": min(-i["diferenca"], atual)})
        else:
            entradas.append({"produto_id": i["produto_id"], "quantidade": i["diferenca"], "valor_unitario": i["custo"]})
    saidas = [s_ for s_ in saidas if s_["quantidade"] > 0]
    # confere tudo antes de gravar, para não aplicar só metade dos ajustes
    for it in saidas + entradas:
        if not c.db.execute("SELECT 1 FROM produtos WHERE id = ? AND ativo = 1", (it["produto_id"],)).fetchone():
            raise Erro("Há produto inativo com diferença na contagem: reative-o ou zere a contagem dele.")
    doc = f"Inventário #{iid}"
    ids = {"entrada_id": None, "saida_id": None}

    def fechar(db, mid=None, _t=0, campo=None):
        if campo:
            ids[campo] = mid
        db.execute("""UPDATE inventarios SET status = 'finalizado', finalizado_em = ?, finalizado_por = ?,
                      entrada_id = ?, saida_id = ? WHERE id = ?""",
                   (agora(), c.usuario["id"], ids["entrada_id"], ids["saida_id"], iid))
    if saidas:
        ids["saida_id"] = registrar_movimentacao(c.db, c.usuario, {
            "tipo": "saida", "motivo": "Ajuste de inventário", "documento": doc,
            "observacao": "Faltas encontradas na contagem", "itens": saidas},
            depois=None if entradas else (lambda db, mid, t: fechar(db, mid, t, "saida_id")))
    if entradas:
        registrar_movimentacao(c.db, c.usuario, {
            "tipo": "entrada", "motivo": "Ajuste de inventário", "documento": doc,
            "observacao": "Sobras encontradas na contagem", "itens": entradas},
            depois=lambda db, mid, t: fechar(db, mid, t, "entrada_id"))
    if not saidas and not entradas:
        with ESCRITA:
            fechar(c.db)
            c.db.commit()
    return carregar_inventario(c.db, iid)


@rota("POST", r"/api/inventarios/(\d+)/cancelar", "admin")
def cancelar_inventario(c):
    iid = int(c.params[0])
    if carregar_inventario(c.db, iid)["status"] != "aberto":
        raise Erro("Este inventário já foi encerrado.")
    with ESCRITA:
        c.db.execute("UPDATE inventarios SET status = 'cancelado', finalizado_em = ?, finalizado_por = ? WHERE id = ?",
                     (agora(), c.usuario["id"], iid))
        c.db.commit()
    return carregar_inventario(c.db, iid)


# ---- painel e relatórios

VENDAS = "m.tipo = 'saida' AND m.motivo = 'Venda' AND m.cancelada = 0"
# receita do item já com o desconto da venda rateado proporcionalmente
RECEITA_ITEM = "i.quantidade * i.valor_unitario * (CASE WHEN m.subtotal > 0 THEN m.total / m.subtotal ELSE 0 END)"
CUSTO_ITEM = "i.custo_total"


def resumo_vendas(db, inicio, fim):
    r = um(db, f"""SELECT COUNT(*) AS vendas, COALESCE(SUM(m.total), 0) AS faturamento,
                          COALESCE(SUM(m.desconto), 0) AS descontos
                   FROM movimentacoes m WHERE {VENDAS} AND date(m.data) BETWEEN ? AND ?""", (inicio, fim))
    r2 = um(db, f"""SELECT COALESCE(SUM({CUSTO_ITEM}), 0) AS custo, COALESCE(SUM(i.quantidade), 0) AS itens
                    FROM itens i JOIN movimentacoes m ON m.id = i.movimentacao_id
                    WHERE {VENDAS} AND date(m.data) BETWEEN ? AND ?""", (inicio, fim))
    r.update(r2)
    r["lucro"] = round(r["faturamento"] - r["custo"], 2)
    r["margem"] = round(100 * r["lucro"] / r["faturamento"], 1) if r["faturamento"] else 0
    r["ticket_medio"] = round(r["faturamento"] / r["vendas"], 2) if r["vendas"] else 0
    return r


def vendas_por_dia(db, inicio, fim):
    dados = {r["dia"]: r for r in db.execute(
        f"""SELECT date(m.data) AS dia, COUNT(*) AS vendas, SUM(m.total) AS faturamento
            FROM movimentacoes m WHERE {VENDAS} AND date(m.data) BETWEEN ? AND ? GROUP BY dia""", (inicio, fim))}
    lucro = {r["dia"]: r["custo"] for r in db.execute(
        f"""SELECT date(m.data) AS dia, SUM({CUSTO_ITEM}) AS custo FROM itens i
            JOIN movimentacoes m ON m.id = i.movimentacao_id
            WHERE {VENDAS} AND date(m.data) BETWEEN ? AND ? GROUP BY dia""", (inicio, fim))}
    saida, d, ultimo = [], dt.date.fromisoformat(inicio), dt.date.fromisoformat(fim)
    while d <= ultimo and len(saida) < 1000:
        k = d.isoformat()
        fat = round(dados[k]["faturamento"], 2) if k in dados else 0
        saida.append({"dia": k, "vendas": dados[k]["vendas"] if k in dados else 0, "faturamento": fat,
                      "lucro": round(fat - lucro.get(k, 0), 2)})
        d += dt.timedelta(days=1)
    return saida


def vendas_agrupadas(db, inicio, fim, campo, limite=1000):
    return dicts(db.execute(
        f"""SELECT {campo} AS chave, SUM(i.quantidade) AS quantidade, ROUND(SUM({RECEITA_ITEM}), 2) AS faturamento,
                   ROUND(SUM({RECEITA_ITEM}) - SUM({CUSTO_ITEM}), 2) AS lucro, COUNT(DISTINCT m.id) AS vendas
            FROM itens i JOIN movimentacoes m ON m.id = i.movimentacao_id
            JOIN produtos p ON p.id = i.produto_id JOIN usuarios u ON u.id = m.usuario_id
            WHERE {VENDAS} AND date(m.data) BETWEEN ? AND ?
            GROUP BY chave ORDER BY faturamento DESC LIMIT {int(limite)}""", (inicio, fim)))


def resumo_estoque(db):
    return um(db, f"""SELECT COUNT(*) AS produtos, COALESCE(SUM(p.estoque_atual), 0) AS unidades,
                            ROUND(COALESCE(SUM({VALOR_CUSTO}), 0), 2) AS valor_custo,
                            ROUND(COALESCE(SUM(p.estoque_atual * p.preco_venda), 0), 2) AS valor_venda,
                            SUM(CASE WHEN p.estoque_atual <= p.estoque_minimo AND p.estoque_minimo > 0 THEN 1 ELSE 0 END)
                              AS abaixo_minimo,
                            SUM(CASE WHEN p.estoque_atual = 0 THEN 1 ELSE 0 END) AS zerados
                     FROM produtos p WHERE p.ativo = 1""")


@rota("GET", "/api/painel")
def painel(c):
    hoje = dt.date.today()
    h, mes = hoje.isoformat(), hoje.replace(day=1).isoformat()
    return {
        "hoje": resumo_vendas(c.db, h, h),
        "mes": resumo_vendas(c.db, mes, h),
        "estoque": resumo_estoque(c.db),
        "grafico": vendas_por_dia(c.db, (hoje - dt.timedelta(days=29)).isoformat(), h),
        "top_produtos": vendas_agrupadas(c.db, mes, h, "p.nome", 5),
        "estoque_baixo": dicts(c.db.execute(
            """SELECT id, nome, estoque_atual, estoque_minimo FROM produtos
               WHERE ativo = 1 AND estoque_minimo > 0 AND estoque_atual <= estoque_minimo
               ORDER BY estoque_atual - estoque_minimo, nome LIMIT 10""")),
        "ultimas": dicts(c.db.execute(
            """SELECT m.id, m.tipo, m.motivo, m.data, m.total, c.nome AS cliente_nome, f.nome AS fornecedor_nome
               FROM movimentacoes m LEFT JOIN clientes c ON c.id = m.cliente_id
               LEFT JOIN fornecedores f ON f.id = m.fornecedor_id
               WHERE m.cancelada = 0 ORDER BY m.data DESC, m.id DESC LIMIT 8""")),
        "os": {
            "em_andamento": c.db.execute("SELECT COUNT(*) FROM ordens_servico WHERE status NOT IN "
                                         "('Entregue', 'Cancelada')").fetchone()[0],
            "prontas": c.db.execute("SELECT COUNT(*) FROM ordens_servico WHERE status = 'Pronta para retirada'"
                                    ).fetchone()[0],
            "atrasadas": c.db.execute("SELECT COUNT(*) FROM ordens_servico WHERE status NOT IN ('Entregue', "
                                      "'Cancelada', 'Pronta para retirada') AND previsao < ?", (h,)).fetchone()[0],
            "receita_mes": c.db.execute("SELECT COALESCE(SUM(total), 0) FROM ordens_servico WHERE status = 'Entregue' "
                                        "AND date(entregue_em) BETWEEN ? AND ?", (mes, h)).fetchone()[0],
        },
        "financeiro": um(c.db, """SELECT
            ROUND(COALESCE(SUM(CASE WHEN tipo = 'receber' AND vencimento < ? THEN valor END), 0), 2) AS receber_vencido,
            ROUND(COALESCE(SUM(CASE WHEN tipo = 'receber' AND vencimento BETWEEN ? AND ? THEN valor END), 0), 2)
              AS receber_7d,
            ROUND(COALESCE(SUM(CASE WHEN tipo = 'pagar' AND vencimento < ? THEN valor END), 0), 2) AS pagar_vencido,
            ROUND(COALESCE(SUM(CASE WHEN tipo = 'pagar' AND vencimento BETWEEN ? AND ? THEN valor END), 0), 2)
              AS pagar_7d
            FROM financeiro WHERE cancelado = 0 AND pago_em IS NULL""",
                         (h, h, (hoje + dt.timedelta(days=7)).isoformat(), h, h,
                          (hoje + dt.timedelta(days=7)).isoformat())) if c.admin else None,
        "caixa": caixa_aberto(c.db),
    }


@rota("GET", "/api/relatorios/vendas")
def relatorio_vendas(c):
    inicio, fim = periodo(c)
    return {
        "inicio": inicio, "fim": fim,
        "resumo": resumo_vendas(c.db, inicio, fim),
        "por_dia": vendas_por_dia(c.db, inicio, fim),
        "por_pagamento": dicts(c.db.execute(
            f"""SELECT m.forma_pagamento AS chave, COUNT(*) AS vendas, ROUND(SUM(m.total), 2) AS faturamento
                FROM movimentacoes m WHERE {VENDAS} AND date(m.data) BETWEEN ? AND ?
                GROUP BY chave ORDER BY faturamento DESC""", (inicio, fim))),
        "por_vendedor": vendas_agrupadas(c.db, inicio, fim, "u.nome"),
        "por_categoria": vendas_agrupadas(c.db, inicio, fim, "p.categoria"),
        "por_marca": vendas_agrupadas(c.db, inicio, fim, "COALESCE(NULLIF(p.marca, ''), 'Sem marca')"),
        "por_produto": vendas_agrupadas(c.db, inicio, fim, "p.nome"),
    }


@rota("GET", "/api/relatorios/estoque")
def relatorio_estoque(c):
    return {
        "resumo": resumo_estoque(c.db),
        "por_categoria": dicts(c.db.execute(
            f"""SELECT p.categoria AS chave, COUNT(*) AS produtos, SUM(p.estoque_atual) AS unidades,
                      ROUND(SUM({VALOR_CUSTO}), 2) AS valor_custo,
                      ROUND(SUM(p.estoque_atual * p.preco_venda), 2) AS valor_venda
               FROM produtos p WHERE p.ativo = 1 GROUP BY p.categoria ORDER BY valor_custo DESC""")),
        "produtos": dicts(c.db.execute(
            f"""SELECT p.id, p.codigo, p.nome, p.marca, p.categoria, p.condicao, p.estoque_atual, p.estoque_minimo,
                      p.preco_custo, p.preco_venda, ROUND({VALOR_CUSTO}, 2) AS valor_custo,
                      ROUND(p.estoque_atual * p.preco_venda, 2) AS valor_venda,
                      (SELECT MAX(m.data) FROM itens i JOIN movimentacoes m ON m.id = i.movimentacao_id
                       WHERE i.produto_id = p.id AND m.tipo = 'saida' AND m.cancelada = 0) AS ultima_saida
               FROM produtos p WHERE p.ativo = 1 ORDER BY p.nome""")),
    }


@rota("GET", "/api/relatorios/movimentacoes")
def relatorio_movimentacoes(c):
    inicio, fim = periodo(c)
    args = (inicio, fim)
    return {
        "inicio": inicio, "fim": fim,
        "por_motivo": dicts(c.db.execute(
            """SELECT m.tipo, m.motivo, COUNT(DISTINCT m.id) AS lancamentos, SUM(i.quantidade) AS quantidade,
                      ROUND(SUM(i.quantidade * i.valor_unitario), 2) AS valor,
                      ROUND(SUM(i.custo_total), 2) AS custo
               FROM movimentacoes m JOIN itens i ON i.movimentacao_id = m.id
               WHERE m.cancelada = 0 AND date(m.data) BETWEEN ? AND ?
               GROUP BY m.tipo, m.motivo ORDER BY m.tipo, quantidade DESC""", args)),
        "por_produto": dicts(c.db.execute(
            """SELECT p.id, p.nome, p.estoque_atual,
                      SUM(CASE WHEN m.tipo = 'entrada' THEN i.quantidade ELSE 0 END) AS entradas,
                      SUM(CASE WHEN m.tipo = 'saida' AND m.motivo = 'Venda' THEN i.quantidade ELSE 0 END) AS vendidas,
                      SUM(CASE WHEN m.tipo = 'saida' AND m.motivo <> 'Venda' THEN i.quantidade ELSE 0 END)
                        AS outras_saidas,
                      ROUND(SUM(CASE WHEN m.tipo = 'saida' AND m.motivo IN ('Perda/Avaria')
                                     THEN i.custo_total ELSE 0 END), 2) AS custo_perdas
               FROM itens i JOIN movimentacoes m ON m.id = i.movimentacao_id
               JOIN produtos p ON p.id = i.produto_id
               WHERE m.cancelada = 0 AND date(m.data) BETWEEN ? AND ?
               GROUP BY p.id ORDER BY p.nome""", args)),
        "parados": dicts(c.db.execute(
            """SELECT p.id, p.nome, p.estoque_atual, ROUND(p.estoque_atual * p.preco_custo, 2) AS valor_custo,
                      (SELECT MAX(m.data) FROM itens i JOIN movimentacoes m ON m.id = i.movimentacao_id
                       WHERE i.produto_id = p.id AND m.tipo = 'saida' AND m.cancelada = 0) AS ultima_saida
               FROM produtos p WHERE p.ativo = 1 AND p.estoque_atual > 0 AND p.id NOT IN (
                   SELECT i.produto_id FROM itens i JOIN movimentacoes m ON m.id = i.movimentacao_id
                   WHERE m.tipo = 'saida' AND m.cancelada = 0 AND date(m.data) BETWEEN ? AND ?)
               ORDER BY valor_custo DESC""", args)),
    }


@rota("GET", "/api/backup", "admin")
def backup(c):
    fd, tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        dest = sqlite3.connect(tmp)
        c.db.backup(dest)
        dest.close()
        with open(tmp, "rb") as f:
            conteudo = f.read()
    finally:
        os.remove(tmp)
    nome = f"backup-estoque-{dt.datetime.now():%Y%m%d-%H%M}.db"
    return Resposta(bruto=conteudo, tipo="application/octet-stream",
                    headers=[("Content-Disposition", f'attachment; filename="{nome}"')])


# --------------------------------------------------------------------------- HTTP

class Servidor(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, endereco, caminho_db, silencioso=False):
        super().__init__(endereco, Handler)
        self.caminho_db, self.silencioso = caminho_db, silencioso


class Handler(BaseHTTPRequestHandler):
    server_version = "EstoqueCelulares/1.0"
    sys_version = ""

    def log_message(self, fmt, *args):
        if not self.server.silencioso:
            sys.stderr.write("%s - %s\n" % (self.log_date_time_string(), fmt % args))

    def do_GET(self):
        self.tratar("GET")

    def do_POST(self):
        self.tratar("POST")

    def do_PUT(self):
        self.tratar("PUT")

    def do_DELETE(self):
        self.tratar("DELETE")

    def cabecalhos_seguranca(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:")

    def enviar(self, status, corpo, tipo, extras=()):
        self.send_response(status)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.cabecalhos_seguranca()
        for k, v in extras:
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(corpo)

    def json(self, status, dados, extras=()):
        self.enviar(status, json.dumps(dados, ensure_ascii=False).encode(), "application/json; charset=utf-8", extras)

    def servir_estatico(self, caminho):
        rel = "index.html" if caminho in ("", "/") else caminho.lstrip("/")
        alvo = os.path.realpath(os.path.join(STATIC_DIR, rel))
        if not alvo.startswith(os.path.realpath(STATIC_DIR) + os.sep) or not os.path.isfile(alvo):
            return self.enviar(404, b"Nao encontrado", "text/plain; charset=utf-8")
        tipo = mimetypes.guess_type(alvo)[0] or "application/octet-stream"
        if tipo.startswith("text/") or tipo in ("application/javascript",):
            tipo += "; charset=utf-8"
        with open(alvo, "rb") as f:
            self.enviar(200, f.read(), tipo)

    def sessao(self, db):
        ck = cookies.SimpleCookie(self.headers.get("Cookie", ""))
        if COOKIE not in ck:
            return None
        token = ck[COOKIE].value
        u = um(db, """SELECT u.* FROM sessoes s JOIN usuarios u ON u.id = s.usuario_id
                      WHERE s.token = ? AND s.expira_em > ? AND u.ativo = 1""", (token, agora()))
        if u:
            u["_token"] = token
        return u

    def ler_corpo(self):
        tamanho = int(self.headers.get("Content-Length") or 0)
        if tamanho > 2_000_000:
            raise Erro("Requisição muito grande.", 413)
        if not tamanho:
            return {}
        if "application/json" not in self.headers.get("Content-Type", ""):
            raise Erro("Envie os dados em JSON.", 415)
        try:
            corpo = json.loads(self.rfile.read(tamanho).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise Erro("JSON inválido.")
        if not isinstance(corpo, dict):
            raise Erro("JSON inválido.")
        return corpo

    def tratar(self, metodo):
        url = urlparse(self.path)
        if not url.path.startswith("/api/"):
            if metodo == "GET":
                return self.servir_estatico(url.path)
            return self.json(405, {"erro": "Método não permitido."})
        alvo = None
        for m, rx, acesso, f in ROTAS:
            achou = rx.match(url.path)
            if achou and m == metodo:
                alvo = (acesso, f, achou.groups())
                break
        if not alvo:
            return self.json(404, {"erro": "Rota não encontrada."})
        acesso, f, params = alvo
        db = conectar(self.server.caminho_db)
        try:
            usuario = self.sessao(db)
            if acesso != "publico" and not usuario:
                raise Erro("Sua sessão expirou. Entre novamente.", 401)
            if acesso == "admin" and usuario["perfil"] != "admin":
                raise Erro("Apenas administradores podem fazer isso.", 403)
            corpo = self.ler_corpo() if metodo in ("POST", "PUT") else {}
            res = f(Req(db, usuario, corpo, parse_qs(url.query), params, self.client_address[0],
                        self.server.caminho_db))
            if not isinstance(res, Resposta):
                res = Resposta(res)
            if res.bruto is not None:
                return self.enviar(res.status, res.bruto, res.tipo, res.headers)
            self.json(res.status, res.dados, res.headers)
        except Erro as e:
            self.json(e.status, {"erro": e.msg})
        except sqlite3.IntegrityError as e:
            msg = "Já existe um registro com esse código." if "UNIQUE" in str(e) else "Operação inválida para os dados atuais."
            self.json(400, {"erro": msg})
        except Exception:
            traceback.print_exc()
            self.json(500, {"erro": "Erro interno no servidor."})
        finally:
            db.close()


# --------------------------------------------------------------------------- dados de exemplo

def gerar_demo(caminho):
    import random
    db = conectar(caminho)
    if db.execute("SELECT 1 FROM produtos").fetchone():
        print("  O banco já tem produtos; dados de exemplo não foram criados.")
        db.close()
        return
    random.seed(7)
    admin = um(db, "SELECT * FROM usuarios WHERE perfil = 'admin' ORDER BY id LIMIT 1")
    db.execute("INSERT INTO usuarios (nome, login, senha_hash, perfil, criado_em) VALUES (?,?,?,?,?)",
               ("Vendedor Exemplo", "vendedor", hash_senha("vendedor123"), "vendedor", agora()))
    vendedor = um(db, "SELECT * FROM usuarios WHERE login = 'vendedor'")
    fornecedores = [("Distribuidora Mobile Brasil", "12.345.678/0001-90"),
                    ("Acessórios Express", "98.765.432/0001-10")]
    for nome, doc in fornecedores:
        db.execute("INSERT INTO fornecedores (nome, documento, telefone, criado_em) VALUES (?,?,?,?)",
                   (nome, doc, "(11) 4000-0000", agora()))
    for nome in ["Ana Souza", "Bruno Lima", "Carla Mendes", "Diego Santos", "Eduarda Rocha"]:
        db.execute("INSERT INTO clientes (nome, telefone, criado_em) VALUES (?,?,?)", (nome, "(11) 90000-0000", agora()))
    produtos = [
        ("SAM-A15-128-PT", "Samsung Galaxy A15 128GB Preto", "Samsung", "Galaxy A15", "Smartphone", "Preto", "128GB", 1, 820, 1199, 3),
        ("SAM-S24-256-CZ", "Samsung Galaxy S24 256GB Cinza", "Samsung", "Galaxy S24", "Smartphone", "Cinza", "256GB", 1, 3900, 5299, 2),
        ("APL-IP15-128-AZ", "iPhone 15 128GB Azul", "Apple", "iPhone 15", "Smartphone", "Azul", "128GB", 1, 4700, 5999, 2),
        ("MOT-G54-256-VD", "Motorola Moto G54 256GB Verde", "Motorola", "Moto G54", "Smartphone", "Verde", "256GB", 1, 980, 1399, 3),
        ("XIA-RN13-256-PT", "Xiaomi Redmi Note 13 256GB Preto", "Xiaomi", "Redmi Note 13", "Smartphone", "Preto", "256GB", 1, 1050, 1499, 3),
        ("ACC-CAPA-A15", "Capa silicone Galaxy A15", "Genérica", "", "Acessório", "", "", 0, 9, 39.9, 10),
        ("ACC-PELIC-3D", "Película 3D vidro (universal)", "Genérica", "", "Acessório", "", "", 0, 4, 29.9, 20),
        ("ACC-CARR-25W", "Carregador USB-C 25W", "Samsung", "EP-TA800", "Acessório", "Branco", "", 0, 45, 99.9, 5),
        ("ACC-FONE-BT", "Fone Bluetooth TWS", "QCY", "T13", "Acessório", "Preto", "", 0, 60, 149.9, 4),
        ("PEC-TELA-A15", "Tela frontal Galaxy A15", "Samsung", "Galaxy A15", "Peça", "", "", 0, 180, 350, 2),
    ]
    for cod, nome, marca, modelo, cat, cor, arm, imei, custo, venda, minimo in produtos:
        db.execute("""INSERT INTO produtos (codigo, nome, marca, modelo, categoria, cor, armazenamento,
                      controla_imei, preco_custo, preco_venda, estoque_minimo, criado_em)
                      VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                   (cod, nome, marca, modelo, cat, cor, arm, imei, custo, venda, minimo, agora()))
    db.commit()

    def gerar_imei():
        base = "35" + "".join(random.choice("0123456789") for _ in range(12))
        for d in range(10):
            if imei_valido(base + str(d)):
                return base + str(d)

    lista = dicts(db.execute("SELECT * FROM produtos"))
    hoje = dt.datetime.now().replace(hour=10, minute=0, second=0)
    inicio = hoje - dt.timedelta(days=45)
    itens = []
    for p in lista:
        q = 8 if p["controla_imei"] else 40
        itens.append({"produto_id": p["id"], "quantidade": q, "valor_unitario": p["preco_custo"],
                      "imeis": [gerar_imei() for _ in range(q)] if p["controla_imei"] else []})
    registrar_movimentacao(db, admin, {"tipo": "entrada", "motivo": "Compra", "fornecedor_id": 1,
                                       "documento": "NF 1001", "itens": itens},
                           inicio.strftime("%Y-%m-%d %H:%M:%S"))
    for dia in range(44, -1, -1):
        if dia in (30, 12):  # reposição de aparelhos ao longo do mês
            repo = [{"produto_id": p["id"], "quantidade": 5, "valor_unitario": p["preco_custo"],
                     "imeis": [gerar_imei() for _ in range(5)]} for p in lista if p["controla_imei"]]
            registrar_movimentacao(db, admin, {"tipo": "entrada", "motivo": "Compra", "fornecedor_id": 1,
                                               "documento": f"NF {1100 + dia}", "itens": repo},
                                   (hoje - dt.timedelta(days=dia, hours=2)).strftime("%Y-%m-%d %H:%M:%S"))
        for _ in range(random.randint(0, 3)):
            momento = (hoje - dt.timedelta(days=dia, hours=random.randint(-1, 8))).strftime("%Y-%m-%d %H:%M:%S")
            p = um(db, "SELECT * FROM produtos WHERE estoque_atual > 0 ORDER BY RANDOM() LIMIT 1")
            if not p:
                break
            q = 1 if p["controla_imei"] else random.randint(1, 3)
            q = min(q, p["estoque_atual"])
            imeis = [r["imei"] for r in db.execute(
                "SELECT imei FROM imeis WHERE produto_id = ? AND status = 'disponivel' LIMIT ?", (p["id"], q))]
            registrar_movimentacao(db, random.choice([admin, vendedor]), {
                "tipo": "saida", "motivo": "Venda", "cliente_id": random.randint(1, 5),
                "forma_pagamento": random.choice(PAGAMENTOS[:4]),
                "desconto": random.choice([0, 0, 0, 10, 50]) if p["preco_venda"] > 100 else 0,
                "itens": [{"produto_id": p["id"], "quantidade": q, "imeis": imeis}]}, momento)
    capa = um(db, "SELECT id FROM produtos WHERE codigo = 'ACC-PELIC-3D'")
    registrar_movimentacao(db, admin, {"tipo": "saida", "motivo": "Perda/Avaria", "observacao": "Quebrou na aplicação",
                                       "itens": [{"produto_id": capa["id"], "quantidade": 2}]})

    # localização na loja
    for cod, local in [("SAM-A15-128-PT", "Vitrine 1"), ("SAM-S24-256-CZ", "Cofre"), ("APL-IP15-128-AZ", "Cofre"),
                       ("MOT-G54-256-VD", "Vitrine 1"), ("XIA-RN13-256-PT", "Vitrine 2"), ("ACC-CAPA-A15", "Parede A"),
                       ("ACC-PELIC-3D", "Gaveta 1"), ("ACC-CARR-25W", "Parede B"), ("ACC-FONE-BT", "Parede B"),
                       ("PEC-TELA-A15", "Bancada técnica")]:
        db.execute("UPDATE produtos SET localizacao = ? WHERE codigo = ?", (local, cod))
    # seminovos: cada aparelho com o seu custo
    db.execute("""INSERT INTO produtos (codigo, nome, marca, modelo, categoria, cor, armazenamento, condicao, controla_imei,
                  preco_custo, preco_venda, estoque_minimo, localizacao, criado_em)
                  VALUES ('SN-IP13-128', 'iPhone 13 128GB Seminovo', 'Apple', 'iPhone 13', 'Smartphone', 'Variadas', '128GB',
                  'Seminovo', 1, 0, 3299, 1, 'Cofre', ?)""", (agora(),))
    db.execute("""INSERT INTO produtos (codigo, nome, marca, categoria, condicao, preco_custo, preco_venda, estoque_minimo,
                  localizacao, criado_em) VALUES ('ACC-CAPA-IP8', 'Capa couro iPhone 8', 'Genérica', 'Acessório', 'Novo',
                  18, 59.9, 0, 'Estoque fundo', ?)""", (agora(),))
    db.commit()
    sn = um(db, "SELECT id FROM produtos WHERE codigo = 'SN-IP13-128'")
    registrar_movimentacao(db, admin, {"tipo": "entrada", "motivo": "Compra", "documento": "Compra de clientes",
                                       "itens": [{"produto_id": sn["id"], "quantidade": 3,
                                                  "imeis": [gerar_imei() for _ in range(3)], "custos": [2150, 2400, 1980]}]},
                           (hoje - dt.timedelta(days=20)).strftime("%Y-%m-%d %H:%M:%S"))
    cp8 = um(db, "SELECT id FROM produtos WHERE codigo = 'ACC-CAPA-IP8'")
    registrar_movimentacao(db, admin, {"tipo": "entrada", "motivo": "Compra", "fornecedor_id": 2, "documento": "NF 880",
                                       "itens": [{"produto_id": cp8["id"], "quantidade": 25, "valor_unitario": 18}]},
                           (hoje - dt.timedelta(days=210)).strftime("%Y-%m-%d %H:%M:%S"))

    # financeiro: despesas fixas do mês passado (pagas) e deste mês (em aberto)
    hoje_d = dt.date.today()
    for desc, cat, valor, dia_v in [("Aluguel da loja", "Aluguel", 2500, 5), ("Energia elétrica", "Energia / água / internet", 380, 10),
                                    ("Internet", "Energia / água / internet", 120, 12), ("Salário vendedor", "Salários e comissões", 2100, 5),
                                    ("Simples Nacional", "Impostos e taxas", 640, 20)]:
        anterior = somar_meses(hoje_d.replace(day=dia_v), -1)
        gerar_financeiro(db, admin, "pagar", desc, cat, valor, "PIX", 1, anterior, f"{anterior} 10:00:00")
        gerar_financeiro(db, admin, "pagar", desc, cat, valor, None, 1, hoje_d.replace(day=dia_v), None)
    db.commit()
    # venda no crediário (3x) com primeira parcela vencida
    a15 = um(db, "SELECT * FROM produtos WHERE codigo = 'SAM-A15-128-PT'")
    imei = um(db, "SELECT imei FROM imeis WHERE produto_id = ? AND status = 'disponivel'", (a15["id"],))
    registrar_movimentacao(db, vendedor, {
        "tipo": "saida", "motivo": "Venda", "cliente_id": 3, "forma_pagamento": "Crediário", "parcelas": 3,
        "primeiro_vencimento": (hoje_d - dt.timedelta(days=3)).isoformat(),
        "itens": [{"produto_id": a15["id"], "quantidade": 1, "imeis": [imei["imei"]]}]},
        (dt.datetime.now() - dt.timedelta(days=33)).strftime("%Y-%m-%d %H:%M:%S"))
    # ordens de serviço em várias etapas
    tela = um(db, "SELECT id, preco_venda FROM produtos WHERE codigo = 'PEC-TELA-A15'")
    exemplos = [
        (1, "Samsung Galaxy A15", "Tela quebrada após queda", "Em reparo", [("Troca de tela", 120)], [(tela["id"], 1, tela["preco_venda"])], "Carlos"),
        (2, "iPhone 11 128GB", "Não carrega", "Aguardando aprovação", [("Troca do conector de carga", 280)], [], "Carlos"),
        (4, "Motorola Moto G32", "Bateria descarregando rápido", "Pronta para retirada", [("Troca de bateria", 180)], [], "Júlia"),
        (5, "Xiaomi Redmi Note 11", "Caiu na água", "Em análise", [], [], "Júlia"),
    ]
    for cli, aparelho, defeito, status, servs, pecas, tec in exemplos:
        entrada = (dt.datetime.now() - dt.timedelta(days=random.randint(1, 6))).strftime("%Y-%m-%d %H:%M:%S")
        vs = sum(v for _, v in servs)
        vp = sum(q * v for _, q, v in pecas)
        cur = db.execute("""INSERT INTO ordens_servico (cliente_id, usuario_id, tecnico, aparelho, defeito, status, previsao,
                            valor_servicos, valor_pecas, total, entrada_em, atualizado_em)
                            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                         (cli, admin["id"], tec, aparelho, defeito, status, (hoje_d + dt.timedelta(days=2)).isoformat(),
                          vs, vp, vs + vp, entrada, entrada))
        for d_, v in servs:
            db.execute("INSERT INTO os_servicos (os_id, descricao, valor) VALUES (?,?,?)", (cur.lastrowid, d_, v))
        for p_, q, v in pecas:
            db.execute("INSERT INTO os_pecas (os_id, produto_id, quantidade, valor_unitario) VALUES (?,?,?,?)",
                       (cur.lastrowid, p_, q, v))
        db.execute("INSERT INTO os_historico (os_id, data, status, nota, usuario_id) VALUES (?,?,?,?,?)",
                   (cur.lastrowid, entrada, "Aberta", "Aparelho recebido", admin["id"]))
        if status != "Aberta":
            db.execute("INSERT INTO os_historico (os_id, data, status, usuario_id) VALUES (?,?,?,?)",
                       (cur.lastrowid, agora(), status, admin["id"]))
    # orçamento em aberto
    s24 = um(db, "SELECT id, preco_venda FROM produtos WHERE codigo = 'SAM-S24-256-CZ'")
    fone = um(db, "SELECT id, preco_venda FROM produtos WHERE codigo = 'ACC-FONE-BT'")
    cur = db.execute("""INSERT INTO orcamentos (cliente_id, usuario_id, data, validade, status, subtotal, desconto, total, observacao)
                        VALUES (2, ?, ?, ?, 'aberto', ?, 100, ?, 'Pagamento em até 10x sem juros no cartão')""",
                     (vendedor["id"], agora(), (hoje_d + dt.timedelta(days=7)).isoformat(),
                      s24["preco_venda"] + fone["preco_venda"], s24["preco_venda"] + fone["preco_venda"] - 100))
    db.executemany("INSERT INTO orcamento_itens (orcamento_id, produto_id, quantidade, valor_unitario) VALUES (?,?,1,?)",
                   [(cur.lastrowid, s24["id"], s24["preco_venda"]), (cur.lastrowid, fone["id"], fone["preco_venda"])])
    db.execute("UPDATE config SET valor = '160000' WHERE chave = 'saldo_inicial'")
    db.execute("INSERT INTO caixas (aberto_em, aberto_por, saldo_inicial) VALUES (?,?,200)",
               (dt.datetime.now().replace(hour=8, minute=0, second=0).strftime("%Y-%m-%d %H:%M:%S"), admin["id"]))
    db.commit()
    db.close()
    print("  Dados de exemplo criados (usuário extra: vendedor / vendedor123).")


def main():
    ap = argparse.ArgumentParser(description="Sistema de estoque para loja de celulares")
    ap.add_argument("--host", default="127.0.0.1",
                    help="use 0.0.0.0 para acessar de outros computadores da rede (padrão: 127.0.0.1)")
    ap.add_argument("--porta", type=int, default=8080)
    ap.add_argument("--banco", default=os.environ.get("ESTOQUE_DB", DB_PADRAO), help="arquivo do banco SQLite")
    ap.add_argument("--demo", action="store_true", help="cria dados de exemplo se o banco estiver vazio")
    a = ap.parse_args()
    inicializar_banco(a.banco)
    if a.demo:
        gerar_demo(a.banco)
    srv = Servidor((a.host, a.porta), a.banco)
    exibir = "localhost" if a.host in ("127.0.0.1", "0.0.0.0") else a.host
    print(f"  Sistema no ar: http://{exibir}:{a.porta}   (Ctrl+C para parar)")
    print(f"  Banco de dados: {os.path.abspath(a.banco)}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n  Servidor encerrado.")


if __name__ == "__main__":
    main()
