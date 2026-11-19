"""Ponto de entrada para hospedar o sistema na internet (PythonAnywhere e servidores WSGI).

No PythonAnywhere, o arquivo WSGI do site deve conter apenas:

    import sys
    sys.path.insert(0, "/home/SEU_USUARIO/lucas/loja-celulares")
    from wsgi import application
"""
import os
import sys

PASTA = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PASTA)

from servidor import criar_app  # noqa: E402

# o banco fica em dados/estoque.db, fora do git: atualizar o código nunca apaga os dados
application = criar_app(os.environ.get("ESTOQUE_DB", os.path.join(PASTA, "dados", "estoque.db")))
