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
              "Uso interno", "Ajuste de inventário", "Outro"],
}
MOTIVOS_ADMIN = ["Ajuste de inventário"]
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
    imeis TEXT NOT NULL DEFAULT '[]'
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
"""

CONFIG_PADRAO = {
    "nome_loja": "Minha Loja de Celulares",
    "documento": "",
    "endereco": "",
    "telefone": "",
    "rodape_recibo": "Obrigado pela preferência! Garantia conforme termo do produto.",
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
    return {"categorias": CATEGORIAS, "condicoes": CONDICOES, "motivos": MOTIVOS,
            "motivos_admin": MOTIVOS_ADMIN, "pagamentos": PAGAMENTOS, "config": cfg}


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
    sql = "SELECT * FROM produtos" + (" WHERE " + " AND ".join(where) if where else "")
    return dicts(c.db.execute(sql + " ORDER BY nome LIMIT 2000", args))


@rota("GET", r"/api/produtos/(\d+)")
def detalhe_produto(c):
    p = um(c.db, "SELECT * FROM produtos WHERE id = ?", (int(c.params[0]),))
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

def registrar_movimentacao(db, usuario, b, data=None):
    tipo = opcao(b.get("tipo"), "tipo", list(MOTIVOS))
    motivo = opcao(b.get("motivo"), "motivo", MOTIVOS[tipo])
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
                lista = []
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
                if tipo == "saida":
                    retirada[p["id"]] = retirada.get(p["id"], 0) + qtd
                    if retirada[p["id"]] > p["estoque_atual"]:
                        raise Erro(f"Estoque insuficiente de {p['nome']}: disponível {p['estoque_atual']}.")
                prontos.append((p, qtd, valor, lista))

            subtotal = round(sum(q * v for _, q, v, _ in prontos), 2)
            desconto = dinheiro(b.get("desconto"), "desconto") if venda else 0.0
            if desconto > subtotal:
                raise Erro("O desconto não pode ser maior que o subtotal.")
            total = round(subtotal - desconto, 2)
            momento = data or agora()
            cur = db.execute(
                """INSERT INTO movimentacoes (tipo, motivo, data, usuario_id, fornecedor_id, cliente_id,
                   forma_pagamento, documento, subtotal, desconto, total, observacao)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (tipo, motivo, momento, usuario["id"], fornecedor_id, cliente_id, forma, documento,
                 subtotal, desconto, total, observacao))
            mid = cur.lastrowid
            for p, qtd, valor, lista in prontos:
                atual = um(db, "SELECT estoque_atual, preco_custo FROM produtos WHERE id = ?", (p["id"],))
                if tipo == "entrada":
                    custo = valor if motivo == "Compra" else atual["preco_custo"]
                    novo_custo = atual["preco_custo"]
                    if motivo == "Compra" and valor > 0:  # custo médio ponderado
                        e = atual["estoque_atual"]
                        novo_custo = round((e * atual["preco_custo"] + qtd * valor) / (e + qtd), 2) if e else valor
                    db.execute("UPDATE produtos SET estoque_atual = estoque_atual + ?, preco_custo = ? WHERE id = ?",
                               (qtd, novo_custo, p["id"]))
                    for imei in lista:
                        db.execute(
                            """INSERT INTO imeis (imei, produto_id, status, entrada_id, saida_id, atualizado_em)
                               VALUES (?, ?, 'disponivel', ?, NULL, ?)
                               ON CONFLICT(imei) DO UPDATE SET produto_id = excluded.produto_id,
                               status = 'disponivel', entrada_id = excluded.entrada_id, saida_id = NULL,
                               atualizado_em = excluded.atualizado_em""", (imei, p["id"], mid, momento))
                else:
                    custo = atual["preco_custo"]
                    db.execute("UPDATE produtos SET estoque_atual = estoque_atual - ? WHERE id = ?", (qtd, p["id"]))
                    for imei in lista:
                        db.execute("UPDATE imeis SET status = ?, saida_id = ?, atualizado_em = ? WHERE imei = ?",
                                   ("vendido" if venda else "baixado", mid, momento, imei))
                db.execute(
                    """INSERT INTO itens (movimentacao_id, produto_id, quantidade, valor_unitario, custo_unitario, imeis)
                       VALUES (?,?,?,?,?,?)""", (mid, p["id"], qtd, valor, custo, json.dumps(lista)))
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
    return m


@rota("POST", "/api/movimentacoes")
def criar_movimentacao(c):
    return carregar_movimentacao(c.db, registrar_movimentacao(c.db, c.usuario, c.corpo))


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
    if m["cancelada"]:
        raise Erro("Esta movimentação já foi cancelada.")
    db = c.db
    with ESCRITA:
        db.execute("BEGIN IMMEDIATE")
        try:
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
            db.execute("""UPDATE movimentacoes SET cancelada = 1, cancelada_em = ?, cancelada_por = ?,
                          motivo_cancelamento = ? WHERE id = ?""", (agora(), c.usuario["id"], justificativa, mid))
            db.commit()
        except Exception:
            db.rollback()
            raise
    return carregar_movimentacao(db, mid)


# ---- painel e relatórios

VENDAS = "m.tipo = 'saida' AND m.motivo = 'Venda' AND m.cancelada = 0"
# receita do item já com o desconto da venda rateado proporcionalmente
RECEITA_ITEM = "i.quantidade * i.valor_unitario * (CASE WHEN m.subtotal > 0 THEN m.total / m.subtotal ELSE 0 END)"
CUSTO_ITEM = "i.quantidade * i.custo_unitario"


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
    return um(db, """SELECT COUNT(*) AS produtos, COALESCE(SUM(estoque_atual), 0) AS unidades,
                            ROUND(COALESCE(SUM(estoque_atual * preco_custo), 0), 2) AS valor_custo,
                            ROUND(COALESCE(SUM(estoque_atual * preco_venda), 0), 2) AS valor_venda,
                            SUM(CASE WHEN estoque_atual <= estoque_minimo AND estoque_minimo > 0 THEN 1 ELSE 0 END)
                              AS abaixo_minimo,
                            SUM(CASE WHEN estoque_atual = 0 THEN 1 ELSE 0 END) AS zerados
                     FROM produtos WHERE ativo = 1""")


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
            """SELECT categoria AS chave, COUNT(*) AS produtos, SUM(estoque_atual) AS unidades,
                      ROUND(SUM(estoque_atual * preco_custo), 2) AS valor_custo,
                      ROUND(SUM(estoque_atual * preco_venda), 2) AS valor_venda
               FROM produtos WHERE ativo = 1 GROUP BY categoria ORDER BY valor_custo DESC""")),
        "produtos": dicts(c.db.execute(
            """SELECT id, codigo, nome, marca, categoria, condicao, estoque_atual, estoque_minimo, preco_custo,
                      preco_venda, ROUND(estoque_atual * preco_custo, 2) AS valor_custo,
                      ROUND(estoque_atual * preco_venda, 2) AS valor_venda,
                      (SELECT MAX(m.data) FROM itens i JOIN movimentacoes m ON m.id = i.movimentacao_id
                       WHERE i.produto_id = produtos.id AND m.tipo = 'saida' AND m.cancelada = 0) AS ultima_saida
               FROM produtos WHERE ativo = 1 ORDER BY nome""")),
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
                      ROUND(SUM(i.quantidade * i.custo_unitario), 2) AS custo
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
                                     THEN i.quantidade * i.custo_unitario ELSE 0 END), 2) AS custo_perdas
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
