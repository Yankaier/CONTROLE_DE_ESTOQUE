"""Camada de acesso ao banco de dados SQLite.

O modelo segue o app "Movimentação do Almoxarifado" (artefato do Claude), que
grava na planilha CONTROLE DE ESTOQUES 2.0 do SharePoint:

- itens:        estante, PT (prateleira), caixa, SKU, descrição, saldo, mínimo
- seriais:      seriais/lotes em estoque de cada item
- lancamentos:  Entrada, Saída ou Saldo Inicial, com solicitante, área, OS, NF,
                empréstimo (devolver até), estorno e devolução
- pedidos:      pedidos da montagem (P-001), com itens; pedido → separado → entregue
- descartes:    descartes numerados (D-0001), do estoque ou de fora dele
- pessoas:      quem retira material e de qual área
- terminais:    checklist de entrada e saída de terminais
- inventarios:  contagens por estante
- config:       senha do app web, caminho da planilha etc.
"""

import sqlite3
from pathlib import Path

ESQUEMA = """
CREATE TABLE IF NOT EXISTS itens (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    estante    TEXT    NOT NULL DEFAULT '-',
    pt         TEXT    NOT NULL DEFAULT '-',
    caixa      TEXT    NOT NULL DEFAULT '-',
    sku        TEXT    NOT NULL DEFAULT '-',
    descricao  TEXT    NOT NULL,
    saldo      INTEGER NOT NULL DEFAULT 0,
    minimo     INTEGER NOT NULL DEFAULT 0 CHECK (minimo >= 0),
    criado_em  TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    na_planilha     INTEGER NOT NULL DEFAULT 0,   -- 1 = já existe na aba Contagem
    linha_contagem  INTEGER,
    UNIQUE (estante, pt, caixa, sku, descricao)
);

CREATE TABLE IF NOT EXISTS seriais (
    item_id  INTEGER NOT NULL REFERENCES itens(id) ON DELETE CASCADE,
    serial   TEXT    NOT NULL,
    PRIMARY KEY (item_id, serial)
);

CREATE TABLE IF NOT EXISTS pessoas (
    nome  TEXT PRIMARY KEY,
    area  TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS lancamentos (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    criado_em      TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    data           TEXT    NOT NULL DEFAULT (date('now', 'localtime')),
    movim          TEXT    NOT NULL CHECK (movim IN ('Entrada', 'Saída', 'Saldo Inicial')),
    item_id        INTEGER NOT NULL REFERENCES itens(id) ON DELETE CASCADE,
    qtd            INTEGER NOT NULL,
    seriais        TEXT    NOT NULL DEFAULT '',   -- separados por vírgula
    solicitante    TEXT    NOT NULL DEFAULT '',
    area           TEXT    NOT NULL DEFAULT '',
    os             TEXT    NOT NULL DEFAULT '',
    nf             TEXT    NOT NULL DEFAULT '',
    obs            TEXT    NOT NULL DEFAULT '',
    status         TEXT    NOT NULL DEFAULT 'pendente' CHECK (status IN ('pendente', 'lancado')),
    emprestimo     INTEGER NOT NULL DEFAULT 0,
    devolver_ate   TEXT,
    devolucao_de   INTEGER REFERENCES lancamentos(id),
    devolvido_por  INTEGER REFERENCES lancamentos(id),
    estorno_de     INTEGER REFERENCES lancamentos(id),
    estornado_por  INTEGER REFERENCES lancamentos(id),
    linhas         TEXT    NOT NULL DEFAULT ''   -- linhas na aba Movimentação, ex.: "812,813"
);

CREATE TABLE IF NOT EXISTS pedidos (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    num          TEXT    NOT NULL UNIQUE,
    criado_em    TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    data         TEXT    NOT NULL DEFAULT (date('now', 'localtime')),
    solicitante  TEXT    NOT NULL,
    area         TEXT    NOT NULL DEFAULT '',
    os           TEXT    NOT NULL DEFAULT '',
    obs          TEXT    NOT NULL DEFAULT '',
    status       TEXT    NOT NULL DEFAULT 'pedido'
                 CHECK (status IN ('pedido', 'separado', 'entregue', 'cancelado')),
    entregue_em  TEXT
);

CREATE TABLE IF NOT EXISTS pedido_itens (
    pedido_id  INTEGER NOT NULL REFERENCES pedidos(id) ON DELETE CASCADE,
    item_id    INTEGER NOT NULL REFERENCES itens(id),
    qtd        INTEGER NOT NULL CHECK (qtd > 0),
    PRIMARY KEY (pedido_id, item_id)
);

CREATE TABLE IF NOT EXISTS descartes (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    num            TEXT    NOT NULL UNIQUE,
    criado_em      TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    data           TEXT    NOT NULL DEFAULT (date('now', 'localtime')),
    modo           TEXT    NOT NULL CHECK (modo IN ('estoque', 'fora')),
    item_id        INTEGER REFERENCES itens(id),
    sku            TEXT    NOT NULL DEFAULT '-',
    material       TEXT    NOT NULL,
    seriais        TEXT    NOT NULL DEFAULT '',
    qtd            INTEGER NOT NULL CHECK (qtd > 0),
    motivo         TEXT    NOT NULL DEFAULT '',
    destino        TEXT    NOT NULL DEFAULT '',
    responsavel    TEXT    NOT NULL DEFAULT '',
    origem         TEXT    NOT NULL DEFAULT '',
    autorizado     TEXT    NOT NULL DEFAULT '',
    documento      TEXT    NOT NULL DEFAULT '',
    obs            TEXT    NOT NULL DEFAULT '',
    baixa          TEXT    NOT NULL DEFAULT '',   -- texto vindo da planilha (descartes importados)
    lancamento_id  INTEGER REFERENCES lancamentos(id)
);

CREATE TABLE IF NOT EXISTS terminais (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    criado_em    TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    data         TEXT    NOT NULL DEFAULT (date('now', 'localtime')),
    tipo         TEXT    NOT NULL CHECK (tipo IN ('Entrada', 'Saída')),
    serial       TEXT    NOT NULL,
    modelo       TEXT    NOT NULL DEFAULT '',
    local        TEXT    NOT NULL DEFAULT '',
    responsavel  TEXT    NOT NULL DEFAULT '',
    obs          TEXT    NOT NULL DEFAULT '',
    checklist    TEXT    NOT NULL DEFAULT '{}',   -- JSON {"Fonte": "OK", ...}
    defeitos     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS inventarios (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    criado_em  TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    local      TEXT    NOT NULL,
    contados   INTEGER NOT NULL,
    total      INTEGER NOT NULL,
    ajustes    INTEGER NOT NULL
);

-- correções de cadastro de itens que já estão na planilha (aplicadas no próximo envio)
CREATE TABLE IF NOT EXISTS correcoes (
    item_id  INTEGER PRIMARY KEY REFERENCES itens(id) ON DELETE CASCADE,
    de       TEXT    NOT NULL   -- JSON com estante/pt/caixa/sku/descricao como estão na planilha
);

CREATE TABLE IF NOT EXISTS config (
    chave  TEXT PRIMARY KEY,
    valor  TEXT NOT NULL
);
"""


def conectar(caminho: str | Path = "estoque.db") -> sqlite3.Connection:
    """Abre (ou cria) o banco e garante que as tabelas existam."""
    conexao = sqlite3.connect(str(caminho))
    conexao.row_factory = sqlite3.Row
    conexao.execute("PRAGMA foreign_keys = ON")
    conexao.executescript(ESQUEMA)
    _migrar(conexao)
    return conexao


# colunas acrescentadas depois da primeira versão (bancos antigos ganham as colunas)
_COLUNAS_NOVAS = {
    "itens": {"na_planilha": "INTEGER NOT NULL DEFAULT 0", "linha_contagem": "INTEGER"},
    "lancamentos": {"linhas": "TEXT NOT NULL DEFAULT ''"},
    "descartes": {c: "TEXT NOT NULL DEFAULT ''" for c in ("origem", "autorizado", "documento", "obs", "baixa")},
}


def _migrar(conexao: sqlite3.Connection) -> None:
    for tabela, colunas in _COLUNAS_NOVAS.items():
        existentes = {r[1] for r in conexao.execute(f"PRAGMA table_info({tabela})")}
        for nome, tipo in colunas.items():
            if nome not in existentes:
                conexao.execute(f"ALTER TABLE {tabela} ADD COLUMN {nome} {tipo}")
    conexao.commit()
