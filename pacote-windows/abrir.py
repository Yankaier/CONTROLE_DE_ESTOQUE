"""Abre o Controle de Estoque: liga o servidor só neste computador e abre o navegador."""

import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

PORTA = 5000
URL = f"http://127.0.0.1:{PORTA}"


def ja_aberto() -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", PORTA)) == 0


def main() -> int:
    if ja_aberto():
        print("O Controle de Estoque já está aberto. Abrindo o navegador...")
        webbrowser.open(URL)
        time.sleep(2)
        return 0
    dados = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "EstoqueAlmoxarifado"
    dados.mkdir(parents=True, exist_ok=True)

    from werkzeug.serving import make_server
    from estoque.web import criar_app

    app = criar_app(str(dados / "estoque.db"))
    servidor = make_server("127.0.0.1", PORTA, app, threaded=True)
    threading.Timer(1.0, lambda: webbrowser.open(URL)).start()
    print("=" * 60)
    print(" CONTROLE DE ESTOQUE - ALMOXARIFADO")
    print("=" * 60)
    print(f" Aberto em: {URL}")
    print(f" Seus dados ficam em: {dados}")
    rede = app.extensions["rede"]
    if rede.ativo:
        print(f" Celular (mesmo Wi-Fi): {rede.endereco}")
    print(" Para usar no celular: no app, Gestão > Aparelhos.")
    print()
    print(" Deixe esta janela aberta enquanto usa o app.")
    print(" Para fechar o app, feche esta janela.")
    print("=" * 60)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as erro:  # mostra o erro em português e não fecha a janela de repente
        print(f"\nNão foi possível abrir o app: {erro}")
        sys.exit(1)
