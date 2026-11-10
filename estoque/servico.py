"""Regras de negócio do controle de estoque."""

import sqlite3
from dataclasses import dataclass


class ErroEstoque(Exception):
    """Erro de regra de negócio (produto inexistente, estoque insuficiente...)."""


@dataclass
class Produto:
    id: int
    codigo: str
    nome: str
    categoria: str
    preco: float
    quantidade: int
    estoque_minimo: int

    @property
    def valor_total(self) -> float:
        return self.preco * self.quantidade

    @property
    def abaixo_do_minimo(self) -> bool:
        return self.quantidade <= self.estoque_minimo


class Estoque:
    def __init__(self, conexao: sqlite3.Connection):
        self.db = conexao

    # ---------- Produtos ----------

    def cadastrar(self, codigo: str, nome: str, categoria: str = "Geral",
                  preco: float = 0.0, estoque_minimo: int = 0) -> Produto:
        codigo, nome = codigo.strip().upper(), nome.strip()
        if not codigo or not nome:
            raise ErroEstoque("Código e nome são obrigatórios.")
        if preco < 0 or estoque_minimo < 0:
            raise ErroEstoque("Preço e estoque mínimo não podem ser negativos.")
        try:
            with self.db:
                self.db.execute(
                    "INSERT INTO produtos (codigo, nome, categoria, preco, estoque_minimo)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (codigo, nome, categoria.strip() or "Geral", preco, estoque_minimo),
                )
        except sqlite3.IntegrityError:
            raise ErroEstoque(f"Já existe um produto com o código {codigo}.") from None
        return self.buscar(codigo)

    def buscar(self, codigo: str) -> Produto:
        linha = self.db.execute(
            "SELECT * FROM produtos WHERE codigo = ?", (codigo.strip().upper(),)
        ).fetchone()
        if linha is None:
            raise ErroEstoque(f"Produto {codigo} não encontrado.")
        return Produto(**dict(linha))

    def listar(self, filtro: str = "") -> list[Produto]:
        termo = f"%{filtro.strip()}%"
        linhas = self.db.execute(
            "SELECT * FROM produtos WHERE nome LIKE ? OR codigo LIKE ? OR categoria LIKE ?"
            " ORDER BY nome",
            (termo, termo, termo),
        ).fetchall()
        return [Produto(**dict(l)) for l in linhas]

    def atualizar(self, codigo: str, **campos) -> Produto:
        permitidos = {"nome", "categoria", "preco", "estoque_minimo"}
        campos = {k: v for k, v in campos.items() if k in permitidos and v is not None}
        produto = self.buscar(codigo)
        if not campos:
            return produto
        if campos.get("preco", 0) < 0 or campos.get("estoque_minimo", 0) < 0:
            raise ErroEstoque("Preço e estoque mínimo não podem ser negativos.")
        sets = ", ".join(f"{k} = ?" for k in campos)
        with self.db:
            self.db.execute(f"UPDATE produtos SET {sets} WHERE id = ?",
                            (*campos.values(), produto.id))
        return self.buscar(codigo)

    def remover(self, codigo: str) -> None:
        produto = self.buscar(codigo)
        with self.db:
            self.db.execute("DELETE FROM produtos WHERE id = ?", (produto.id,))

    # ---------- Movimentações ----------

    def entrada(self, codigo: str, quantidade: int, observacao: str = "") -> Produto:
        return self._movimentar(codigo, "ENTRADA", quantidade, observacao)

    def saida(self, codigo: str, quantidade: int, observacao: str = "") -> Produto:
        return self._movimentar(codigo, "SAIDA", quantidade, observacao)

    def _movimentar(self, codigo, tipo, quantidade, observacao) -> Produto:
        if quantidade <= 0:
            raise ErroEstoque("A quantidade deve ser maior que zero.")
        produto = self.buscar(codigo)
        if tipo == "SAIDA" and quantidade > produto.quantidade:
            raise ErroEstoque(
                f"Estoque insuficiente de {produto.nome}: "
                f"disponível {produto.quantidade}, solicitado {quantidade}."
            )
        delta = quantidade if tipo == "ENTRADA" else -quantidade
        with self.db:
            self.db.execute("UPDATE produtos SET quantidade = quantidade + ? WHERE id = ?",
                            (delta, produto.id))
            self.db.execute(
                "INSERT INTO movimentacoes (produto_id, tipo, quantidade, observacao)"
                " VALUES (?, ?, ?, ?)",
                (produto.id, tipo, quantidade, observacao),
            )
        return self.buscar(codigo)

    def historico(self, codigo: str | None = None, limite: int = 50) -> list[dict]:
        sql = ("SELECT m.id, p.codigo, p.nome, m.tipo, m.quantidade, m.observacao, m.data_hora"
               " FROM movimentacoes m JOIN produtos p ON p.id = m.produto_id")
        params: tuple = ()
        if codigo:
            sql += " WHERE p.codigo = ?"
            params = (codigo.strip().upper(),)
        sql += " ORDER BY m.id DESC LIMIT ?"
        return [dict(l) for l in self.db.execute(sql, (*params, limite)).fetchall()]

    # ---------- Relatórios ----------

    def abaixo_do_minimo(self) -> list[Produto]:
        return [p for p in self.listar() if p.abaixo_do_minimo]

    def resumo(self) -> dict:
        produtos = self.listar()
        return {
            "total_produtos": len(produtos),
            "total_itens": sum(p.quantidade for p in produtos),
            "valor_total": round(sum(p.valor_total for p in produtos), 2),
            "abaixo_do_minimo": sum(1 for p in produtos if p.abaixo_do_minimo),
        }
