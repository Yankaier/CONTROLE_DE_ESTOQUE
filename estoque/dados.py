"""Apagar dados, cópias de segurança do banco e modo teste com planilha de teste.

- Antes de apagar ou restaurar, sempre é feita uma cópia do banco atual
  (pasta `copias-dados`, ficam as 30 mais recentes).
- Apagar remove itens, lançamentos, pedidos, descartes, terminais, inventários e pessoas.
  Senha, nome e configurações continuam.
- Modo teste: o app passa a gravar numa CÓPIA da planilha (pasta `teste`). O caminho da
  planilha real fica guardado e só volta a ser usado quando o teste é encerrado.
"""

import re
import sqlite3
import time
from pathlib import Path

from .servico import Almoxarifado, ErroEstoque

TABELAS_DADOS = ("descartes", "pedido_itens", "pedidos", "lancamentos", "seriais", "correcoes",
                 "inventarios", "terminais", "pessoas", "itens")
CONFIG_MANTIDA = ("senha_hash", "segredo", "usuario")
MAX_COPIAS = 30


def pasta_copias(banco: str | Path) -> Path:
    return Path(banco).resolve().parent / "copias-dados"


def pasta_teste(banco: str | Path) -> Path:
    return Path(banco).resolve().parent / "teste"


def contar(alm: Almoxarifado) -> dict:
    um = lambda t: alm.db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    return {"itens": um("itens"), "lancamentos": um("lancamentos"), "pedidos": um("pedidos"),
            "descartes": um("descartes"), "terminais": um("terminais"), "pessoas": um("pessoas"),
            "inventarios": um("inventarios")}


def salvar_copia(alm: Almoxarifado, banco: str | Path, motivo: str = "manual") -> Path:
    """Copia o banco inteiro (mesmo aberto) para a pasta de cópias."""
    pasta = pasta_copias(banco)
    pasta.mkdir(parents=True, exist_ok=True)
    motivo = re.sub(r"[^a-z0-9-]+", "-", motivo.lower()).strip("-") or "manual"
    destino = pasta / f"estoque {time.strftime('%Y-%m-%d_%H%M%S')} {motivo}.db"
    n = 1
    while destino.exists():
        destino = destino.with_name(f"{destino.stem}-{n}.db")
        n += 1
    alvo = sqlite3.connect(destino)
    try:
        alm.db.commit()
        alm.db.backup(alvo)
    finally:
        alvo.close()
    for velho in listar_copias(banco)[MAX_COPIAS:]:
        velho["caminho"].unlink(missing_ok=True)
    return destino


def listar_copias(banco: str | Path) -> list[dict]:
    pasta = pasta_copias(banco)
    if not pasta.is_dir():
        return []
    copias = []
    for p in sorted(pasta.glob("estoque *.db"), key=lambda x: x.stat().st_mtime, reverse=True):
        partes = p.stem.split(" ", 2)
        copias.append({"nome": p.name, "caminho": p, "tamanho": f"{p.stat().st_size / 1024:.0f} KB",
                       "quando": time.strftime("%d/%m/%Y %H:%M:%S", time.localtime(p.stat().st_mtime)),
                       "motivo": partes[2].replace("-", " ") if len(partes) > 2 else ""})
    return copias


def apagar_dados(alm: Almoxarifado) -> dict:
    """Apaga os dados do estoque. Senha e configurações ficam."""
    antes = contar(alm)
    with alm.db:
        for t in TABELAS_DADOS:
            alm.db.execute(f"DELETE FROM {t}")
        alm.db.execute(f"DELETE FROM sqlite_sequence WHERE name IN ({','.join('?' * len(TABELAS_DADOS))})",
                       TABELAS_DADOS)
    return antes


def restaurar_copia(alm: Almoxarifado, banco: str | Path, nome: str) -> Path:
    """Volta o banco para uma cópia. A senha, o nome e a planilha configurados agora são mantidos."""
    arquivo = pasta_copias(banco) / Path(nome).name   # só aceita arquivos da pasta de cópias
    if not arquivo.is_file() or arquivo.suffix != ".db":
        raise ErroEstoque("Cópia não encontrada.")
    manter = {k: alm.config(k) for k in CONFIG_MANTIDA + ("planilha", "auto_enviar", "modo_teste",
                                                           "planilha_real", "auto_enviar_real")}
    seguranca = salvar_copia(alm, banco, "antes de restaurar")
    origem = sqlite3.connect(arquivo)
    try:
        origem.backup(alm.db)
    finally:
        origem.close()
    alm.db.execute("PRAGMA foreign_keys = ON")
    from .banco import ESQUEMA, _migrar          # cópias antigas ganham as tabelas/colunas novas
    alm.db.executescript(ESQUEMA)
    _migrar(alm.db)
    for k, v in manter.items():
        alm.definir_config(k, v)
    return seguranca


# ---------------- modo teste ----------------

def em_teste(alm: Almoxarifado) -> bool:
    return alm.config("modo_teste") == "1"


def iniciar_teste(alm: Almoxarifado, banco: str | Path, nome_arquivo: str, dados: bytes,
                  apagar: bool = True) -> dict:
    """Guarda a planilha de teste numa pasta separada e passa a usar ela."""
    from .sincronizar import gravar_arquivo, trazer_da_planilha
    from .xlsx import Planilha

    Planilha(dados).ler()                                    # recusa arquivo que não é a planilha
    copia = salvar_copia(alm, banco, "antes do teste")
    if apagar:
        apagar_dados(alm)
    pasta = pasta_teste(banco)
    pasta.mkdir(parents=True, exist_ok=True)
    nome = re.sub(r'[\\/:*?"<>|]+', "_", Path(nome_arquivo).name) or "planilha.xlsx"
    destino = pasta / f"TESTE {time.strftime('%Y-%m-%d_%H%M%S')} {nome}"
    gravar_arquivo(destino, dados)
    if not em_teste(alm):                                    # guarda a configuração real só uma vez
        alm.definir_config("planilha_real", alm.config("planilha"))
        alm.definir_config("auto_enviar_real", alm.config("auto_enviar"))
    alm.definir_config("planilha", str(destino.resolve()))
    alm.definir_config("modo_teste", "1")
    r = trazer_da_planilha(alm, dados)
    return dict(r, arquivo=destino, copia=copia)


def encerrar_teste(alm: Almoxarifado, banco: str | Path, apagar: bool = True, trazer_real: bool = True) -> dict:
    """Sai do modo teste: (opcional) apaga os dados do teste e volta para a planilha real."""
    from .sincronizar import trazer_da_planilha

    if not em_teste(alm):
        raise ErroEstoque("O app não está em modo teste.")
    copia = salvar_copia(alm, banco, "fim do teste")
    if apagar:
        apagar_dados(alm)
    real = alm.config("planilha_real")
    alm.definir_config("planilha", real)
    alm.definir_config("auto_enviar", alm.config("auto_enviar_real") or "0")
    for k in ("modo_teste", "planilha_real", "auto_enviar_real"):
        alm.definir_config(k, None)
    r = None
    if real and trazer_real and Path(real).is_file():
        r = trazer_da_planilha(alm, Path(real).read_bytes())
    return {"copia": copia, "planilha": real, "trazido": r}
