"""Camada de acesso ao banco de dados SQLite."""

import sqlite3
from pathlib import Path

ESQUEMA = """
CREATE TABLE IF NOT EXISTS produtos (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo          TEXT    NOT NULL UNIQUE,
    nome            TEXT    NOT NULL,
    categoria       TEXT    NOT NULL DEFAULT 'Geral',
    preco           REAL    NOT NULL DEFAULT 0 CHECK (preco >= 0),
    quantidade      INTEGER NOT NULL DEFAULT 0 CHECK (quantidade >= 0),
    estoque_minimo  INTEGER NOT NULL DEFAULT 0 CHECK (estoque_minimo >= 0)
);

CREATE TABLE IF NOT EXISTS movimentacoes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    produto_id  INTEGER NOT NULL REFERENCES produtos(id) ON DELETE CASCADE,
    tipo        TEXT    NOT NULL CHECK (tipo IN ('ENTRADA', 'SAIDA')),
    quantidade  INTEGER NOT NULL CHECK (quantidade > 0),
    observacao  TEXT    NOT NULL DEFAULT '',
    data_hora   TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);
"""


def conectar(caminho: str | Path = "estoque.db") -> sqlite3.Connection:
    """Abre (ou cria) o banco e garante que as tabelas existam."""
    conexao = sqlite3.connect(str(caminho))
    conexao.row_factory = sqlite3.Row
    conexao.execute("PRAGMA foreign_keys = ON")
    conexao.executescript(ESQUEMA)
    return conexao
