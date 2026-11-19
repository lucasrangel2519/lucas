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
        st, r = cls.adm.req("POST", "/api/me/senha", {"atual": "admin123", "nova": "Loja@Forte2026"})
        assert st == 200, r

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
        # usuário criado pelo administrador precisa criar a própria senha no primeiro acesso
        self.assertEqual(v.req("GET", "/api/produtos")[0], 403)
        self.assertEqual(v.req("POST", "/api/me/senha", {"atual": "123456", "nova": "Vendas#2026x"})[0], 200)
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

    def test_financeiro_gerado_por_venda_e_compra(self):
        st, cli = self.adm.req("POST", "/api/clientes", {"nome": "Cliente Crediário"})
        p = self.produto(nome="Carregador fin", preco_custo=40, preco_venda=100)
        compra = self.mov(tipo="entrada", motivo="Compra", condicao_pagamento="a_prazo", forma_pagamento="Outro",
                          parcelas=2, primeiro_vencimento="2030-01-31",
                          itens=[{"produto_id": p["id"], "quantidade": 5, "valor_unitario": 40}])
        self.assertEqual([(f["valor"], f["vencimento"], f["pago_em"]) for f in compra["financeiro"]],
                         [(100, "2030-01-31", None), (100, "2030-02-28", None)])
        # crediário sem cliente é recusado
        self.mov(esperado=400, tipo="saida", motivo="Venda", forma_pagamento="Crediário",
                 itens=[{"produto_id": p["id"], "quantidade": 1}])
        v = self.mov(tipo="saida", motivo="Venda", forma_pagamento="Crediário", cliente_id=cli["id"], parcelas=3,
                     itens=[{"produto_id": p["id"], "quantidade": 1, "valor_unitario": 100}])
        self.assertEqual([f["valor"] for f in v["financeiro"]], [33.33, 33.33, 33.34])
        self.assertTrue(all(f["pago_em"] is None for f in v["financeiro"]))
        avista = self.mov(tipo="saida", motivo="Venda", forma_pagamento="PIX",
                          itens=[{"produto_id": p["id"], "quantidade": 1, "valor_unitario": 100}])
        self.assertIsNotNone(avista["financeiro"][0]["pago_em"])
        # baixa de parcela e cancelamento da venda cancela o financeiro
        fid = v["financeiro"][0]["id"]
        st, r = self.adm.req("POST", f"/api/financeiro/{fid}/baixar", {"forma_pagamento": "Dinheiro"})
        self.assertEqual((st, r["situacao"]), (200, "pago"))
        self.assertEqual(self.adm.req("DELETE", f"/api/financeiro/{fid}")[0], 400)  # veio de venda
        self.adm.req("POST", f"/api/movimentacoes/{v['id']}/cancelar", {"motivo": "teste"})
        st, lista = self.adm.req("GET", "/api/financeiro?tipo=receber&situacao=todos&q=Venda")
        self.assertNotIn(v["id"], [f["movimentacao_id"] for f in lista])
        # despesa fixa repetida 3 meses
        st, _ = self.adm.req("POST", "/api/financeiro", {"tipo": "pagar", "descricao": "Aluguel teste", "categoria": "Aluguel",
                                                         "valor": 1000, "vencimento": "2031-01-10", "parcelas": 3, "repetir": True})
        st, lista = self.adm.req("GET", "/api/financeiro?tipo=pagar&q=Aluguel+teste")
        self.assertEqual([(f["valor"], f["vencimento"]) for f in lista],
                         [(1000, "2031-01-10"), (1000, "2031-02-10"), (1000, "2031-03-10")])
        st, r = self.adm.req("GET", "/api/relatorios/financeiro")
        self.assertEqual(st, 200)
        self.assertIn("dre", r)

    def test_ordem_de_servico(self):
        st, cli = self.adm.req("POST", "/api/clientes", {"nome": "Cliente OS", "telefone": "11988887777"})
        peca = self.produto(nome="Bateria peça", categoria="Peça", preco_custo=50, preco_venda=120)
        self.mov(tipo="entrada", motivo="Compra", itens=[{"produto_id": peca["id"], "quantidade": 2, "valor_unitario": 50}])
        st, o = self.adm.req("POST", "/api/os", {"cliente_id": cli["id"], "aparelho": "Moto G", "defeito": "Bateria",
                                                 "servicos": [{"descricao": "Troca de bateria", "valor": 80}],
                                                 "pecas": [{"produto_id": peca["id"], "quantidade": 1, "valor_unitario": 120}],
                                                 "desconto": 10})
        self.assertEqual(st, 200, o)
        self.assertEqual((o["status"], o["total"]), ("Aberta", 190))
        self.assertEqual(self.estoque(peca["id"])["estoque_atual"], 2)  # peça só sai na entrega
        st, o = self.adm.req("POST", f"/api/os/{o['id']}/status", {"status": "Pronta para retirada"})
        self.assertEqual(o["status"], "Pronta para retirada")
        self.assertEqual(self.adm.req("POST", f"/api/os/{o['id']}/status", {"status": "Entregue"})[0], 400)
        st, o = self.adm.req("POST", f"/api/os/{o['id']}/entregar", {"forma_pagamento": "PIX"})
        self.assertEqual((st, o["status"]), (200, "Entregue"))
        self.assertEqual(self.estoque(peca["id"])["estoque_atual"], 1)
        self.assertEqual(o["financeiro"][0]["valor"], 190)
        # a saída da OS não pode ser cancelada por fora
        self.assertEqual(self.adm.req("POST", f"/api/movimentacoes/{o['movimentacao_id']}/cancelar", {"motivo": "x"})[0], 400)
        self.assertEqual(self.adm.req("PUT", f"/api/os/{o['id']}", {"cliente_id": cli["id"], "aparelho": "x", "defeito": "y"})[0], 400)
        st, o = self.adm.req("POST", f"/api/os/{o['id']}/cancelar", {"motivo": "garantia"})
        self.assertEqual(o["status"], "Cancelada")
        self.assertEqual(self.estoque(peca["id"])["estoque_atual"], 2)
        self.assertTrue(all(f["cancelado"] for f in o["financeiro"]))

    def test_orcamento_convertido_em_venda(self):
        p = self.produto(nome="Capa orçamento", preco_venda=50)
        self.mov(tipo="entrada", motivo="Compra", itens=[{"produto_id": p["id"], "quantidade": 3, "valor_unitario": 10}])
        st, o = self.adm.req("POST", "/api/orcamentos", {"itens": [{"produto_id": p["id"], "quantidade": 2}], "desconto": 5})
        self.assertEqual((st, o["total"], o["status"]), (200, 95, "aberto"))
        v = self.mov(tipo="saida", motivo="Venda", forma_pagamento="PIX", orcamento_id=o["id"], desconto=5,
                     itens=[{"produto_id": p["id"], "quantidade": 2, "valor_unitario": 50}])
        st, o2 = self.adm.req("GET", f"/api/orcamentos/{o['id']}")
        self.assertEqual((o2["status"], o2["movimentacao_id"]), ("convertido", v["id"]))
        self.mov(esperado=400, tipo="saida", motivo="Venda", forma_pagamento="PIX", orcamento_id=o["id"],
                 itens=[{"produto_id": p["id"], "quantidade": 1}])

    def test_caixa(self):
        self.adm.req("POST", "/api/caixa/fechar", {"saldo_informado": 0})  # garante caixa fechado
        st, r = self.adm.req("POST", "/api/caixa/abrir", {"saldo_inicial": 100})
        self.assertEqual(st, 200)
        self.assertEqual(self.adm.req("POST", "/api/caixa/abrir", {"saldo_inicial": 1})[0], 400)
        p = self.produto(nome="Item caixa", preco_venda=30)
        self.mov(tipo="entrada", motivo="Compra", itens=[{"produto_id": p["id"], "quantidade": 2, "valor_unitario": 10}])
        self.mov(tipo="saida", motivo="Venda", forma_pagamento="Dinheiro", itens=[{"produto_id": p["id"], "quantidade": 2}])
        self.adm.req("POST", "/api/caixa/movimento", {"tipo": "sangria", "valor": 50})
        st, r = self.adm.req("GET", "/api/caixa")
        # 100 de troco + 60 vendidos - 20 da compra paga em "Outro" (não conta) - 50 de sangria
        self.assertAlmostEqual(r["atual"]["esperado_dinheiro"], 110)
        st, fechado = self.adm.req("POST", "/api/caixa/fechar", {"saldo_informado": 105})
        self.assertEqual((fechado["saldo_esperado"], fechado["saldo_informado"]), (110, 105))
        # com caixa obrigatório, venda sem caixa aberto é recusada
        self.adm.req("PUT", "/api/config", {"exigir_caixa": "1"})
        self.mov(esperado=400, tipo="saida", motivo="Venda", forma_pagamento="PIX",
                 itens=[{"produto_id": p["id"], "quantidade": 1}])
        self.adm.req("PUT", "/api/config", {"exigir_caixa": "0"})

    def test_custo_por_aparelho_e_valor_do_estoque(self):
        p = self.produto(nome="iPhone 12 seminovo", categoria="Smartphone", condicao="Seminovo", controla_imei=True,
                         preco_venda=2500)
        imeis = ["352099001761481", "356938035643817", "490154203237526"]
        imeis = [i for i in imeis if servidor.imei_valido(i)] or imeis
        validos = []
        base = 35209900176148
        while len(validos) < 3:  # gera IMEIs válidos
            for d in range(10):
                if servidor.imei_valido(f"{base}{d}"):
                    validos.append(f"{base}{d}")
            base += 1
        ent = self.mov(tipo="entrada", motivo="Compra",
                       itens=[{"produto_id": p["id"], "quantidade": 3, "imeis": validos, "custos": [1500, 1700, 2000]}])
        self.assertEqual(ent["total"], 5200)
        e = self.estoque(p["id"])
        self.assertAlmostEqual(e["preco_custo"], 1733.33)
        st, lista = self.adm.req("GET", "/api/produtos?q=iPhone+12+seminovo")
        self.assertEqual(lista[0]["valor_custo"], 5200)  # soma exata do custo de cada aparelho
        v = self.mov(tipo="saida", motivo="Venda", forma_pagamento="PIX",
                     itens=[{"produto_id": p["id"], "quantidade": 1, "imeis": [validos[2]], "valor_unitario": 2500}])
        self.assertEqual(v["itens"][0]["custo_unitario"], 2000)  # lucro real deste aparelho: 500
        st, lista = self.adm.req("GET", "/api/produtos?q=iPhone+12+seminovo")
        self.assertEqual(lista[0]["valor_custo"], 3200)
        self.assertAlmostEqual(self.estoque(p["id"])["preco_custo"], 1600)
        st, f = self.adm.req("GET", f"/api/produtos/{p['id']}/ficha")
        self.assertEqual([(k["saldo_qtd"], k["saldo_valor"]) for k in f["kardex"]], [(3, 5200), (2, 3200)])
        self.assertEqual(sorted(cm["custo"] for cm in f["camadas"]), [1500, 1700])
        st, painel = self.adm.req("GET", "/api/estoque/painel")
        self.assertEqual(st, 200)
        linha = next(x for x in painel["produtos"] if x["id"] == p["id"])
        self.assertEqual((linha["valor_custo"], linha["valor_venda"], linha["lucro_potencial"]), (3200, 5000, 1800))
        self.assertIn(linha["classe"], ("A", "B", "C"))
        self.assertAlmostEqual(sum(f_["valor"] for f_ in painel["faixas"]), painel["resumo"]["valor_custo"], places=1)
        self.assertEqual(self.adm.req("GET", "/api/estoque/painel")[0], 200)

    def test_inventario(self):
        a = self.produto(nome="Capinha inventário", categoria="Outro", preco_custo=10)
        b = self.produto(nome="Fone inventário", categoria="Outro", preco_custo=30)
        cel = self.produto(nome="Cel inventário", categoria="Outro", controla_imei=True, preco_custo=500)
        self.mov(tipo="entrada", motivo="Compra", itens=[{"produto_id": a["id"], "quantidade": 10, "valor_unitario": 10},
                                                         {"produto_id": b["id"], "quantidade": 5, "valor_unitario": 30}])
        im = []
        base = 35391805232345
        while len(im) < 2:
            for d in range(10):
                if servidor.imei_valido(f"{base}{d}") and len(im) < 2:
                    im.append(f"{base}{d}")
            base += 7
        self.mov(tipo="entrada", motivo="Compra", itens=[{"produto_id": cel["id"], "quantidade": 2, "imeis": im, "valor_unitario": 500}])
        self.adm.req("POST", "/api/inventarios/0/cancelar", {})
        st, abertos = self.adm.req("GET", "/api/inventarios")
        for v in abertos:
            if v["status"] == "aberto":
                self.adm.req("POST", f"/api/inventarios/{v['id']}/cancelar", {})
        st, inv = self.adm.req("POST", "/api/inventarios", {"categoria": "Outro"})
        self.assertEqual(st, 200, inv)
        self.assertEqual(self.adm.req("POST", "/api/inventarios", {})[0], 400)  # só um aberto por vez
        st, inv = self.adm.req("PUT", f"/api/inventarios/{inv['id']}/contagem", {"itens": [
            {"produto_id": a["id"], "contado": 8}, {"produto_id": b["id"], "contado": 6},
            {"produto_id": cel["id"], "imeis": [im[0]]}]})
        r = inv["resumo"]
        self.assertEqual((r["falta_unidades"], r["sobra_unidades"]), (3, 1))
        self.assertAlmostEqual(r["falta_valor"], 520)  # 2 capinhas (20) + 1 celular (500)
        self.assertAlmostEqual(r["sobra_valor"], 30)
        st, inv = self.adm.req("POST", f"/api/inventarios/{inv['id']}/finalizar", {})
        self.assertEqual((st, inv["status"]), (200, "finalizado"), inv)
        self.assertEqual(self.estoque(a["id"])["estoque_atual"], 8)
        self.assertEqual(self.estoque(b["id"])["estoque_atual"], 6)
        self.assertEqual(self.estoque(cel["id"])["imeis_disponiveis"], [im[0]])
        self.assertEqual(self.adm.req("POST", f"/api/inventarios/{inv['id']}/finalizar", {})[0], 400)

    def test_senha_padrao_obrigatoria(self):
        tmp = os.path.join(self.tmp.name, "novo.db")
        servidor.inicializar_banco(tmp, avisar=False)
        srv = servidor.Servidor(("127.0.0.1", 0), tmp, silencioso=True)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            c = Cliente(srv.server_address[1])
            st, u = c.req("POST", "/api/login", {"login": "admin", "senha": "admin123"})
            self.assertEqual((st, u["trocar_senha"]), (200, 1))
            self.assertEqual(c.req("GET", "/api/painel")[0], 403)
            self.assertEqual(c.req("GET", "/api/me")[0], 200)
            self.assertEqual(c.req("POST", "/api/me/senha", {"atual": "admin123", "nova": "admin123"})[0], 400)
            self.assertEqual(c.req("POST", "/api/me/senha", {"atual": "admin123", "nova": "curta"})[0], 400)
            self.assertEqual(c.req("POST", "/api/me/senha", {"atual": "admin123", "nova": "Minha$Loja99"})[0], 200)
            self.assertEqual(c.req("GET", "/api/painel")[0], 200)
            # o token da sessão não fica gravado em texto no banco
            token = c.cookie.split("=", 1)[1]
            con = servidor.conectar(tmp)
            self.assertIsNone(con.execute("SELECT 1 FROM sessoes WHERE token = ?", (token,)).fetchone())
            con.close()
        finally:
            srv.shutdown()
            srv.server_close()

    def test_wsgi_para_hospedagem(self):
        import io
        tmp = os.path.join(self.tmp.name, "wsgi.db")
        app = servidor.criar_app(tmp)

        def chamar(metodo, caminho, corpo=None, cookie=None):
            dados = json.dumps(corpo).encode() if corpo is not None else b""
            env = {"REQUEST_METHOD": metodo, "PATH_INFO": caminho, "QUERY_STRING": "", "wsgi.url_scheme": "http",
                   "HTTP_X_FORWARDED_PROTO": "https", "HTTP_X_REAL_IP": "200.1.2.3", "CONTENT_LENGTH": str(len(dados)),
                   "CONTENT_TYPE": "application/json", "wsgi.input": io.BytesIO(dados)}
            if cookie:
                env["HTTP_COOKIE"] = cookie
            saida = {}

            def start(status, hs):
                saida["status"], saida["hs"] = int(status.split()[0]), hs
            corpo_r = b"".join(app(env, start))
            return saida["status"], dict(saida["hs"]), corpo_r
        st, hs, corpo = chamar("GET", "/")
        self.assertEqual(st, 200)
        self.assertIn(b"<html", corpo)
        self.assertIn("Strict-Transport-Security", hs)
        st, hs, _ = chamar("POST", "/api/login", {"login": "admin", "senha": "admin123"})
        self.assertEqual(st, 200)
        self.assertIn("Secure", hs["Set-Cookie"])
        cookie = hs["Set-Cookie"].split(";")[0]
        self.assertEqual(chamar("GET", "/api/me", cookie=cookie)[0], 200)
        self.assertEqual(chamar("GET", "/manifest.webmanifest")[0], 200)

    def test_estatico_sem_travessia(self):
        st, _ = self.adm.req("GET", "/../servidor.py")
        self.assertEqual(st, 404)
        st, _ = self.adm.req("GET", "/js/app.js")
        self.assertEqual(st, 200)


if __name__ == "__main__":
    unittest.main()
