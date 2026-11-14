"""Testes do sistema de estoque. Rode com:  python3 -m unittest discover -s tests"""
import http.client
import json
import os
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import servidor  # noqa: E402

IMEI_A = "356938035643809"  # IMEIs com dígito verificador válido
IMEI_B = "490154203237518"
IMEI_C = "353918052323454"


class Cliente:
    def __init__(self, porta):
        self.porta, self.cookie = porta, None

    def req(self, metodo, url, corpo=None):
        con = http.client.HTTPConnection("127.0.0.1", self.porta, timeout=10)
        h = {}
        dados = None
        if corpo is not None:
            dados = json.dumps(corpo).encode()
            h["Content-Type"] = "application/json"
        if self.cookie:
            h["Cookie"] = self.cookie
        con.request(metodo, url, body=dados, headers=h)
        r = con.getresponse()
        ck = r.getheader("Set-Cookie")
        if ck:
            self.cookie = ck.split(";")[0]
        bruto = r.read()
        con.close()
        try:
            return r.status, json.loads(bruto)
        except ValueError:
            return r.status, bruto


class TesteSistema(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db = os.path.join(cls.tmp.name, "teste.db")
        servidor.inicializar_banco(cls.db, avisar=False)
        cls.srv = servidor.Servidor(("127.0.0.1", 0), cls.db, silencioso=True)
        cls.porta = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.adm = Cliente(cls.porta)
        st, _ = cls.adm.req("POST", "/api/login", {"login": "admin", "senha": "admin123"})
        assert st == 200

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.tmp.cleanup()

    def produto(self, **kw):
        d = {"nome": "Produto", "categoria": "Acessório", "preco_custo": 10, "preco_venda": 25, "estoque_minimo": 2}
        d.update(kw)
        st, p = self.adm.req("POST", "/api/produtos", d)
        self.assertEqual(st, 200, p)
        return p

    def mov(self, cli=None, esperado=200, **corpo):
        st, r = (cli or self.adm).req("POST", "/api/movimentacoes", corpo)
        self.assertEqual(st, esperado, r)
        return r

    def estoque(self, pid):
        return self.adm.req("GET", f"/api/produtos/{pid}")[1]

    # ------------------------------------------------------------------

    def test_login_e_protecao(self):
        anon = Cliente(self.porta)
        self.assertEqual(anon.req("GET", "/api/produtos")[0], 401)
        self.assertEqual(anon.req("POST", "/api/login", {"login": "admin", "senha": "errada"})[0], 401)
        self.assertEqual(anon.req("GET", "/")[0], 200)

    def test_imei_luhn(self):
        self.assertTrue(servidor.imei_valido(IMEI_A))
        self.assertFalse(servidor.imei_valido("356938035643808"))
        self.assertFalse(servidor.imei_valido("123"))

    def test_entrada_venda_custo_medio_e_estoque(self):
        p = self.produto(nome="Capa teste", codigo="CAPA-T1")
        self.mov(tipo="entrada", motivo="Compra", itens=[{"produto_id": p["id"], "quantidade": 10, "valor_unitario": 10}])
        self.mov(tipo="entrada", motivo="Compra", itens=[{"produto_id": p["id"], "quantidade": 10, "valor_unitario": 20}])
        e = self.estoque(p["id"])
        self.assertEqual(e["estoque_atual"], 20)
        self.assertAlmostEqual(e["preco_custo"], 15.0)

        v = self.mov(tipo="saida", motivo="Venda", forma_pagamento="PIX", desconto=10,
                     itens=[{"produto_id": p["id"], "quantidade": 4, "valor_unitario": 25}])
        self.assertEqual(v["subtotal"], 100)
        self.assertEqual(v["total"], 90)
        self.assertEqual(v["itens"][0]["custo_unitario"], 15.0)
        self.assertEqual(self.estoque(p["id"])["estoque_atual"], 16)

        # estoque insuficiente não altera nada
        self.mov(esperado=400, tipo="saida", motivo="Venda", forma_pagamento="PIX",
                 itens=[{"produto_id": p["id"], "quantidade": 17}])
        # o mesmo produto em duas linhas também respeita o saldo
        self.mov(esperado=400, tipo="saida", motivo="Venda", forma_pagamento="PIX",
                 itens=[{"produto_id": p["id"], "quantidade": 10}, {"produto_id": p["id"], "quantidade": 7}])
        self.assertEqual(self.estoque(p["id"])["estoque_atual"], 16)

        # venda exige forma de pagamento
        self.mov(esperado=400, tipo="saida", motivo="Venda", itens=[{"produto_id": p["id"], "quantidade": 1}])

        # cancelar a venda devolve ao estoque
        st, c = self.adm.req("POST", f"/api/movimentacoes/{v['id']}/cancelar", {"motivo": "teste"})
        self.assertEqual(st, 200, c)
        self.assertEqual(self.estoque(p["id"])["estoque_atual"], 20)
        self.assertEqual(self.adm.req("POST", f"/api/movimentacoes/{v['id']}/cancelar", {"motivo": "x"})[0], 400)

    def test_fluxo_imei(self):
        p = self.produto(nome="Celular IMEI", categoria="Smartphone", controla_imei=True, preco_custo=1000, preco_venda=1500)
        # quantidade diferente do nº de IMEIs
        self.mov(esperado=400, tipo="entrada", motivo="Compra",
                 itens=[{"produto_id": p["id"], "quantidade": 2, "imeis": [IMEI_A]}])
        # IMEI inválido
        self.mov(esperado=400, tipo="entrada", motivo="Compra",
                 itens=[{"produto_id": p["id"], "quantidade": 1, "imeis": ["356938035643808"]}])
        ent = self.mov(tipo="entrada", motivo="Compra",
                       itens=[{"produto_id": p["id"], "quantidade": 2, "imeis": [IMEI_A, IMEI_B]}])
        self.assertEqual(self.estoque(p["id"])["imeis_disponiveis"], [IMEI_A, IMEI_B])
        # duplicado em estoque
        self.mov(esperado=400, tipo="entrada", motivo="Compra",
                 itens=[{"produto_id": p["id"], "quantidade": 1, "imeis": [IMEI_A]}])
        # vender IMEI que não está em estoque
        self.mov(esperado=400, tipo="saida", motivo="Venda", forma_pagamento="Dinheiro",
                 itens=[{"produto_id": p["id"], "quantidade": 1, "imeis": [IMEI_C]}])
        venda = self.mov(tipo="saida", motivo="Venda", forma_pagamento="Dinheiro",
                         itens=[{"produto_id": p["id"], "quantidade": 1, "imeis": [IMEI_A]}])
        e = self.estoque(p["id"])
        self.assertEqual(e["estoque_atual"], 1)
        self.assertEqual(e["imeis_disponiveis"], [IMEI_B])
        # não dá para cancelar a entrada: um aparelho já foi vendido
        self.assertEqual(self.adm.req("POST", f"/api/movimentacoes/{ent['id']}/cancelar", {"motivo": "x"})[0], 400)
        # rastreio
        st, r = self.adm.req("GET", f"/api/imeis/{IMEI_A}")
        self.assertEqual(st, 200)
        self.assertEqual(r["atual"]["status"], "vendido")
        self.assertEqual([h["id"] for h in r["historico"]], [ent["id"], venda["id"]])
        # devolução do cliente reativa o IMEI
        self.mov(tipo="entrada", motivo="Devolução de cliente",
                 itens=[{"produto_id": p["id"], "quantidade": 1, "imeis": [IMEI_A]}])
        self.assertEqual(sorted(self.estoque(p["id"])["imeis_disponiveis"]), sorted([IMEI_A, IMEI_B]))
        # não pode desligar o IMEI com estoque
        st, _ = self.adm.req("PUT", f"/api/produtos/{p['id']}", {**p, "controla_imei": False})
        self.assertEqual(st, 400)

    def test_permissoes_vendedor(self):
        st, _ = self.adm.req("POST", "/api/usuarios", {"nome": "Vend", "login": "vend1", "senha": "123456", "perfil": "vendedor"})
        self.assertEqual(st, 200)
        v = Cliente(self.porta)
        self.assertEqual(v.req("POST", "/api/login", {"login": "vend1", "senha": "123456"})[0], 200)
        self.assertEqual(v.req("POST", "/api/produtos", {"nome": "x", "categoria": "Outro"})[0], 403)
        self.assertEqual(v.req("GET", "/api/usuarios")[0], 403)
        self.assertEqual(v.req("GET", "/api/backup")[0], 403)
        p = self.produto(nome="Película vend")
        self.mov(tipo="entrada", motivo="Compra", itens=[{"produto_id": p["id"], "quantidade": 3, "valor_unitario": 5}])
        self.mov(v, esperado=403, tipo="saida", motivo="Ajuste de inventário",
                 itens=[{"produto_id": p["id"], "quantidade": 1}])
        m = self.mov(v, tipo="saida", motivo="Venda", forma_pagamento="PIX", itens=[{"produto_id": p["id"], "quantidade": 1}])
        self.assertEqual(v.req("POST", f"/api/movimentacoes/{m['id']}/cancelar", {"motivo": "x"})[0], 403)

    def test_relatorios_e_painel(self):
        p = self.produto(nome="Fone relatorio", preco_custo=50, preco_venda=100)
        self.mov(tipo="entrada", motivo="Compra", itens=[{"produto_id": p["id"], "quantidade": 5, "valor_unitario": 50}])
        self.mov(tipo="saida", motivo="Venda", forma_pagamento="Cartão de crédito", desconto=20,
                 itens=[{"produto_id": p["id"], "quantidade": 2, "valor_unitario": 100}])
        self.mov(tipo="saida", motivo="Perda/Avaria", itens=[{"produto_id": p["id"], "quantidade": 1}])
        st, r = self.adm.req("GET", "/api/relatorios/vendas")
        self.assertEqual(st, 200)
        linha = next(x for x in r["por_produto"] if x["chave"] == "Fone relatorio")
        self.assertEqual(linha["quantidade"], 2)
        self.assertAlmostEqual(linha["faturamento"], 180)  # desconto rateado
        self.assertAlmostEqual(linha["lucro"], 80)
        st, r = self.adm.req("GET", "/api/relatorios/movimentacoes")
        linha = next(x for x in r["por_produto"] if x["nome"] == "Fone relatorio")
        self.assertEqual((linha["entradas"], linha["vendidas"], linha["outras_saidas"]), (5, 2, 1))
        self.assertAlmostEqual(linha["custo_perdas"], 50)
        for url in ("/api/relatorios/estoque", "/api/painel", "/api/movimentacoes?q=Fone"):
            self.assertEqual(self.adm.req("GET", url)[0], 200, url)
        self.assertEqual(self.adm.req("GET", "/api/relatorios/vendas?inicio=2024-02-10&fim=2024-01-01")[0], 400)

    def test_cadastros_e_backup(self):
        st, c = self.adm.req("POST", "/api/clientes", {"nome": "Fulano", "telefone": "11999990000"})
        self.assertEqual(st, 200)
        st, lista = self.adm.req("GET", "/api/clientes?q=Fulano")
        self.assertEqual(len(lista), 1)
        self.assertEqual(self.adm.req("DELETE", f"/api/clientes/{c['id']}")[0], 200)
        self.assertEqual(self.adm.req("POST", "/api/produtos", {"nome": "Dup", "categoria": "Outro", "codigo": "DUP"})[0], 200)
        st, r = self.adm.req("POST", "/api/produtos", {"nome": "Dup2", "categoria": "Outro", "codigo": "DUP"})
        self.assertEqual(st, 400)
        st, bruto = self.adm.req("GET", "/api/backup")
        self.assertEqual(st, 200)
        self.assertTrue(bruto.startswith(b"SQLite format 3"))

    def test_estatico_sem_travessia(self):
        st, _ = self.adm.req("GET", "/../servidor.py")
        self.assertEqual(st, 404)
        st, _ = self.adm.req("GET", "/js/app.js")
        self.assertEqual(st, 200)


if __name__ == "__main__":
    unittest.main()
