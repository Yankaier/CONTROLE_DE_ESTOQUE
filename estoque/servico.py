"""Regras de negócio do almoxarifado.

As regras seguem o app "Movimentação do Almoxarifado":

- Saldo do item = soma dos lançamentos (Entrada soma, Saída subtrai,
  Saldo Inicial soma com sinal — é usado no cadastro e nos ajustes de contagem).
- Itens com serial: cada serial que entra fica em estoque e cada um que sai
  precisa estar em estoque. Unidades sem serial podem ir junto.
- Saída maior que o saldo é bloqueada, a não ser que se force ("lançar mesmo assim").
- Estoque mínimo: alerta quando mínimo > 0 e saldo <= mínimo.
- Empréstimo: saída com data para devolver; a devolução é uma entrada ligada a ela.
- Estorno: lançamento inverso ligado ao original.
- Pedidos da montagem: P-001, P-002…; pedido → separado → entregue (gera as saídas).
- Descartes: D-0001…; do estoque gera uma saída na área "Descarte".
"""

import sqlite3
from dataclasses import dataclass
from datetime import date

MOVIMENTOS = ("Entrada", "Saída", "Saldo Inicial")


class ErroEstoque(Exception):
    """Erro de regra de negócio (item inexistente, saldo insuficiente...)."""


@dataclass
class Item:
    id: int
    estante: str
    pt: str
    caixa: str
    sku: str
    descricao: str
    saldo: int
    minimo: int
    criado_em: str
    seriais: list[str]

    @property
    def local(self) -> str:
        texto = f"Estante {self.estante} · {self.pt}"
        return texto + (f" · Caixa {self.caixa}" if self.caixa not in ("", "-") else "")

    @property
    def abaixo_do_minimo(self) -> bool:
        return self.minimo > 0 and self.saldo <= self.minimo


def _txt(valor, padrao: str = "-") -> str:
    texto = str(valor if valor is not None else "").strip()
    return texto or padrao


def _lista_seriais(seriais) -> list[str]:
    if not seriais:
        return []
    if isinstance(seriais, str):
        seriais = seriais.replace("\n", ",").split(",")
    vistos, saida = set(), []
    for s in seriais:
        s = str(s).strip().upper()
        if s and s != "-" and s not in vistos:
            vistos.add(s)
            saida.append(s)
    return saida


def hoje() -> str:
    return date.today().isoformat()


class Almoxarifado:
    def __init__(self, conexao: sqlite3.Connection):
        self.db = conexao

    # ================= Itens =================

    def cadastrar_item(self, descricao: str, sku="-", estante="-", pt="-", caixa="-",
                       minimo: int = 0, saldo_inicial: int = 0, seriais=None) -> Item:
        descricao = _txt(descricao, "").upper()
        if not descricao:
            raise ErroEstoque("A descrição do item é obrigatória.")
        if minimo < 0 or saldo_inicial < 0:
            raise ErroEstoque("Mínimo e saldo inicial não podem ser negativos.")
        seriais = _lista_seriais(seriais)
        saldo_inicial = max(saldo_inicial, len(seriais))
        try:
            with self.db:
                cur = self.db.execute(
                    "INSERT INTO itens (estante, pt, caixa, sku, descricao, minimo) VALUES (?, ?, ?, ?, ?, ?)",
                    (_txt(estante), _txt(pt), _txt(caixa), _txt(sku), descricao, minimo),
                )
        except sqlite3.IntegrityError:
            raise ErroEstoque("Já existe esse item nesse mesmo local (estante/PT/caixa/SKU).") from None
        item_id = cur.lastrowid
        if saldo_inicial:
            self._lancar(item_id, "Saldo Inicial", saldo_inicial, seriais,
                         solicitante="Carga Inicial", area="Estoque Inicial", obs="Cadastro do item")
        return self.item(item_id)

    def item(self, ref) -> Item:
        """Acha um item pelo id, pelo SKU (se for único) ou por um serial em estoque."""
        texto = str(ref).strip()
        linha = None
        if texto.isdigit():
            linha = self.db.execute("SELECT * FROM itens WHERE id = ?", (int(texto),)).fetchone()
        if linha is None:
            achados = self.db.execute(
                "SELECT * FROM itens WHERE upper(sku) = upper(?) AND sku != '-'", (texto,)).fetchall()
            if len(achados) > 1:
                raise ErroEstoque(f"{len(achados)} itens com o SKU {texto}: use o número (id) do item.")
            linha = achados[0] if achados else None
        if linha is None:
            linha = self.db.execute(
                "SELECT i.* FROM itens i JOIN seriais s ON s.item_id = i.id WHERE s.serial = ?",
                (texto.upper(),)).fetchone()
        if linha is None:
            raise ErroEstoque(f"Item {texto} não encontrado.")
        return self._montar(linha)

    def _montar(self, linha) -> Item:
        seriais = [r[0] for r in self.db.execute(
            "SELECT serial FROM seriais WHERE item_id = ? ORDER BY serial", (linha["id"],))]
        return Item(**dict(linha), seriais=seriais)

    def buscar(self, termo: str = "") -> list[Item]:
        """Procura por descrição, SKU, serial ou estante (como a busca do app)."""
        t = f"%{termo.strip()}%"
        linhas = self.db.execute(
            "SELECT DISTINCT i.* FROM itens i LEFT JOIN seriais s ON s.item_id = i.id"
            " WHERE i.descricao LIKE ? OR i.sku LIKE ? OR s.serial LIKE ? OR i.estante LIKE ?"
            " ORDER BY i.estante, i.pt, i.caixa, i.descricao",
            (t, t, t, t)).fetchall()
        return [self._montar(l) for l in linhas]

    def corrigir_item(self, ref, **campos) -> Item:
        permitidos = {"descricao", "sku", "estante", "pt", "caixa", "minimo"}
        campos = {k: v for k, v in campos.items() if k in permitidos and v is not None}
        it = self.item(ref)
        if not campos:
            return it
        if campos.get("minimo", 0) < 0:
            raise ErroEstoque("O mínimo não pode ser negativo.")
        if "descricao" in campos:
            campos["descricao"] = _txt(campos["descricao"], it.descricao).upper()
        for k in ("sku", "estante", "pt", "caixa"):
            if k in campos:
                campos[k] = _txt(campos[k])
        sets = ", ".join(f"{k} = ?" for k in campos)
        with self.db:
            self.db.execute(f"UPDATE itens SET {sets} WHERE id = ?", (*campos.values(), it.id))
        return self.item(it.id)

    # ================= Lançamentos =================

    def entrada(self, ref, qtd: int | None = None, seriais=None, **dados) -> dict:
        return self._movimentar(ref, "Entrada", qtd, seriais, **dados)

    def saida(self, ref, qtd: int | None = None, seriais=None, forcar: bool = False,
              emprestimo: bool = False, devolver_ate: str | None = None, **dados) -> dict:
        if emprestimo and not devolver_ate:
            raise ErroEstoque("Empréstimo precisa da data para devolver.")
        return self._movimentar(ref, "Saída", qtd, seriais, forcar=forcar,
                                emprestimo=emprestimo, devolver_ate=devolver_ate, **dados)

    def ajustar_contagem(self, ref, contado: int, solicitante: str = "Inventário") -> dict | None:
        """Ajusta o saldo para o valor contado (lançamento Saldo Inicial com a diferença)."""
        it = self.item(ref)
        diferenca = contado - it.saldo
        if diferenca == 0:
            return None
        lid = self._lancar(it.id, "Saldo Inicial", diferenca, [], solicitante=solicitante,
                           area="Ajuste de inventário", obs=f"Contagem: {it.saldo} → {contado}")
        return self.lancamento(lid)

    def _movimentar(self, ref, movim, qtd, seriais, forcar=False, **dados) -> dict:
        it = self.item(ref)
        seriais = _lista_seriais(seriais)
        if movim == "Saída" and not seriais and str(ref).strip().upper() in it.seriais:
            seriais = [str(ref).strip().upper()]   # bipou o serial: é esse que sai
        if qtd is None:
            qtd = len(seriais) or 1
        if qtd <= 0:
            raise ErroEstoque("A quantidade deve ser maior que zero.")
        if qtd < len(seriais):
            raise ErroEstoque(f"Quantidade ({qtd}) menor que o número de seriais ({len(seriais)}).")
        if movim == "Saída" and not forcar:
            fora = [s for s in seriais if s not in it.seriais]
            if fora:
                raise ErroEstoque(f"Serial fora do estoque de {it.descricao}: {', '.join(fora)}.")
            if qtd > it.saldo:
                raise ErroEstoque(f"Saldo insuficiente de {it.descricao}: "
                                  f"disponível {it.saldo}, solicitado {qtd}.")
            sem_serial = it.saldo - len(it.seriais)
            if qtd - len(seriais) > max(sem_serial, 0):
                raise ErroEstoque(f"{it.descricao} tem seriais em estoque: informe quais saíram "
                                  f"({', '.join(it.seriais)}).")
        if movim == "Entrada" and not forcar:
            repetidos = [s for s in seriais if s in it.seriais]
            if repetidos:
                raise ErroEstoque(f"Serial já está em estoque: {', '.join(repetidos)}.")
        lid = self._lancar(it.id, movim, qtd, seriais, **dados)
        return self.lancamento(lid)

    def _lancar(self, item_id, movim, qtd, seriais, solicitante="", area="", os="", nf="",
                obs="", data=None, criado_em=None, status="pendente", emprestimo=False,
                devolver_ate=None, devolucao_de=None, estorno_de=None) -> int:
        """Grava o lançamento e atualiza saldo e seriais do item numa transação só."""
        delta = -qtd if movim == "Saída" else qtd
        nome = _txt(solicitante, "").upper()
        with self.db:
            cur = self.db.execute(
                "INSERT INTO lancamentos (criado_em, data, movim, item_id, qtd, seriais, solicitante,"
                " area, os, nf, obs, status, emprestimo, devolver_ate, devolucao_de, estorno_de)"
                " VALUES (COALESCE(?, datetime('now','localtime')), COALESCE(?, date('now','localtime')),"
                " ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (criado_em, data, movim, item_id, qtd, ", ".join(seriais), nome, area.strip(),
                 os.strip(), nf.strip(), obs.strip(), status, int(emprestimo), devolver_ate,
                 devolucao_de, estorno_de))
            self.db.execute("UPDATE itens SET saldo = saldo + ? WHERE id = ?", (delta, item_id))
            for s in seriais:
                if delta > 0:
                    self.db.execute("INSERT OR IGNORE INTO seriais VALUES (?, ?)", (item_id, s))
                else:
                    self.db.execute("DELETE FROM seriais WHERE item_id = ? AND serial = ?", (item_id, s))
            if nome and nome not in ("CARGA INICIAL", "INVENTÁRIO", "-"):
                self.db.execute("INSERT OR IGNORE INTO pessoas (nome, area) VALUES (?, ?)",
                                (nome, area.strip()))
            return cur.lastrowid

    def lancamento(self, lid: int) -> dict:
        linha = self.db.execute(
            "SELECT l.*, i.descricao, i.sku, i.estante, i.pt, i.caixa FROM lancamentos l"
            " JOIN itens i ON i.id = l.item_id WHERE l.id = ?", (lid,)).fetchone()
        if linha is None:
            raise ErroEstoque(f"Lançamento {lid} não encontrado.")
        return dict(linha)

    def historico(self, ref=None, limite: int = 50) -> list[dict]:
        sql = ("SELECT l.*, i.descricao, i.sku, i.estante, i.pt, i.caixa FROM lancamentos l"
               " JOIN itens i ON i.id = l.item_id")
        params: list = []
        if ref is not None:
            sql += " WHERE l.item_id = ?"
            params.append(self.item(ref).id)
        sql += " ORDER BY l.criado_em DESC, l.id DESC LIMIT ?"
        return [dict(r) for r in self.db.execute(sql, (*params, limite))]

    def estornar(self, lid: int, motivo: str) -> dict:
        l = self.lancamento(lid)
        if not motivo.strip():
            raise ErroEstoque("Informe o motivo do estorno.")
        if l["estornado_por"]:
            raise ErroEstoque("Esse lançamento já foi estornado.")
        seriais = _lista_seriais(l["seriais"])
        qtd, area = abs(l["qtd"]), l["area"]
        if l["movim"] == "Saída":
            movim = "Entrada"
        elif l["movim"] == "Entrada":
            movim = "Saída"
        elif seriais:
            movim, area = "Saída", "Ajuste de inventário"
        else:
            movim, qtd, area = "Saldo Inicial", -l["qtd"], "Ajuste de inventário"
        novo = self._lancar(l["item_id"], movim, qtd, seriais, solicitante=l["solicitante"], area=area,
                            os=l["os"], nf=l["nf"], estorno_de=lid,
                            obs=f"Estorno do registro de {l['data']}: {motivo.strip()}")
        with self.db:
            self.db.execute("UPDATE lancamentos SET estornado_por = ? WHERE id = ?", (novo, lid))
        return self.lancamento(novo)

    # ================= Empréstimos =================

    def emprestimos_abertos(self) -> list[dict]:
        return [dict(r) for r in self.db.execute(
            "SELECT l.*, i.descricao FROM lancamentos l JOIN itens i ON i.id = l.item_id"
            " WHERE l.emprestimo = 1 AND l.movim = 'Saída' AND l.devolvido_por IS NULL"
            " AND l.estornado_por IS NULL ORDER BY l.devolver_ate")]

    def emprestimos_atrasados(self, data_ref: str | None = None) -> list[dict]:
        ref = data_ref or hoje()
        return [e for e in self.emprestimos_abertos() if e["devolver_ate"] and e["devolver_ate"] < ref]

    def devolver(self, lid: int) -> dict:
        l = self.lancamento(lid)
        if not l["emprestimo"] or l["movim"] != "Saída":
            raise ErroEstoque("Esse lançamento não é um empréstimo.")
        if l["devolvido_por"]:
            raise ErroEstoque("Esse empréstimo já foi devolvido.")
        novo = self._lancar(l["item_id"], "Entrada", abs(l["qtd"]), _lista_seriais(l["seriais"]),
                            solicitante=l["solicitante"], area=l["area"], os=l["os"], devolucao_de=lid,
                            obs=f"Devolução do empréstimo de {l['data']}")
        with self.db:
            self.db.execute("UPDATE lancamentos SET devolvido_por = ? WHERE id = ?", (novo, lid))
        return self.lancamento(novo)

    # ================= Pedidos da montagem =================

    def _proximo_num(self, tabela: str, prefixo: str, digitos: int) -> str:
        nums = [int("".join(c for c in r[0] if c.isdigit()) or 0)
                for r in self.db.execute(f"SELECT num FROM {tabela}")]
        return f"{prefixo}-{(max(nums) if nums else 0) + 1:0{digitos}d}"

    def criar_pedido(self, solicitante: str, itens: list[tuple], area="", os="", obs="") -> dict:
        """itens: lista de (item, quantidade)."""
        if not _txt(solicitante, ""):
            raise ErroEstoque("O pedido precisa do solicitante.")
        if not itens:
            raise ErroEstoque("O pedido precisa de pelo menos um item.")
        linhas: dict[int, int] = {}
        for ref, qtd in itens:
            if qtd <= 0:
                raise ErroEstoque("A quantidade de cada item deve ser maior que zero.")
            iid = self.item(ref).id
            linhas[iid] = linhas.get(iid, 0) + qtd
        num = self._proximo_num("pedidos", "P", 3)
        with self.db:
            cur = self.db.execute(
                "INSERT INTO pedidos (num, solicitante, area, os, obs) VALUES (?, ?, ?, ?, ?)",
                (num, solicitante.strip().upper(), area.strip(), os.strip(), obs.strip()))
            self.db.executemany("INSERT INTO pedido_itens VALUES (?, ?, ?)",
                                [(cur.lastrowid, iid, q) for iid, q in linhas.items()])
        return self.pedido(num)

    def pedido(self, num: str) -> dict:
        p = self.db.execute("SELECT * FROM pedidos WHERE num = ?", (num.strip().upper(),)).fetchone()
        if p is None:
            raise ErroEstoque(f"Pedido {num} não encontrado.")
        p = dict(p)
        p["itens"] = [dict(r) for r in self.db.execute(
            "SELECT pi.item_id, pi.qtd, i.descricao, i.sku, i.saldo FROM pedido_itens pi"
            " JOIN itens i ON i.id = pi.item_id WHERE pi.pedido_id = ?", (p["id"],))]
        return p

    def pedidos(self, abertos: bool = False) -> list[dict]:
        sql = "SELECT num FROM pedidos"
        if abertos:
            sql += " WHERE status IN ('pedido', 'separado')"
        return [self.pedido(r[0]) for r in self.db.execute(sql + " ORDER BY id DESC")]

    def _mudar_pedido(self, num: str, de: tuple, para: str) -> dict:
        p = self.pedido(num)
        if p["status"] not in de:
            raise ErroEstoque(f"Pedido {p['num']} está {p['status']}; não dá para mudar para {para}.")
        with self.db:
            self.db.execute("UPDATE pedidos SET status = ? WHERE id = ?", (para, p["id"]))
        return self.pedido(num)

    def separar_pedido(self, num: str) -> dict:
        return self._mudar_pedido(num, ("pedido",), "separado")

    def cancelar_pedido(self, num: str) -> dict:
        return self._mudar_pedido(num, ("pedido", "separado"), "cancelado")

    def entregar_pedido(self, num: str) -> dict:
        """Gera uma saída por item. Itens sem saldo ficam em 'nao_entregues'."""
        p = self.pedido(num)
        if p["status"] not in ("pedido", "separado"):
            raise ErroEstoque(f"Pedido {p['num']} está {p['status']}.")
        entregues, nao = [], []
        for linha in p["itens"]:
            try:
                entregues.append(self.saida(linha["item_id"], linha["qtd"], solicitante=p["solicitante"],
                                            area=p["area"], os=p["os"], obs=f"Pedido {p['num']}"))
            except ErroEstoque as erro:
                nao.append({"descricao": linha["descricao"], "motivo": str(erro)})
        with self.db:
            self.db.execute("UPDATE pedidos SET status = 'entregue', entregue_em = datetime('now','localtime')"
                            " WHERE id = ?", (p["id"],))
        return {"pedido": self.pedido(num), "lancamentos": entregues, "nao_entregues": nao}

    # ================= Descartes =================

    def descartar(self, motivo: str, responsavel: str, qtd: int | None = None, ref=None,
                  material: str = "", sku: str = "-", seriais=None, destino: str = "") -> dict:
        """Com `ref` descarta do estoque (gera saída); sem `ref`, registra material de fora."""
        seriais = _lista_seriais(seriais)
        qtd = qtd if qtd is not None else (len(seriais) or 1)
        num = self._proximo_num("descartes", "D", 4)
        lid, item_id = None, None
        if ref is not None:
            it = self.item(ref)
            item_id, material, sku = it.id, it.descricao, it.sku
            obs = " · ".join(x for x in (f"Descarte {num}", motivo.strip(), destino.strip()) if x)
            lid = self.saida(it.id, qtd, seriais, solicitante=responsavel or "-", area="Descarte",
                             obs=obs)["id"]
        elif not _txt(material, ""):
            raise ErroEstoque("Informe o material descartado.")
        with self.db:
            self.db.execute(
                "INSERT INTO descartes (num, modo, item_id, sku, material, seriais, qtd, motivo, destino,"
                " responsavel, lancamento_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (num, "estoque" if item_id else "fora", item_id, _txt(sku), material.strip().upper(),
                 ", ".join(seriais), qtd, motivo.strip(), destino.strip(), responsavel.strip().upper(), lid))
        return dict(self.db.execute("SELECT * FROM descartes WHERE num = ?", (num,)).fetchone())

    # ================= Relatórios =================

    def abaixo_do_minimo(self) -> list[Item]:
        return [i for i in self.buscar() if i.abaixo_do_minimo]

    def movimento_do_dia(self, dia: str | None = None) -> list[dict]:
        return [dict(r) for r in self.db.execute(
            "SELECT l.*, i.descricao, i.sku, i.estante, i.pt, i.caixa FROM lancamentos l"
            " JOIN itens i ON i.id = l.item_id WHERE l.data = ? ORDER BY l.criado_em, l.id",
            (dia or hoje(),))]

    def consumo(self, inicio: str, fim: str) -> list[dict]:
        """Saídas por item no período (sem estornos), da maior para a menor."""
        return [dict(r) for r in self.db.execute(
            "SELECT i.id, i.descricao, i.sku, SUM(l.qtd) AS total FROM lancamentos l"
            " JOIN itens i ON i.id = l.item_id WHERE l.movim = 'Saída' AND l.estornado_por IS NULL"
            " AND l.estorno_de IS NULL AND l.data BETWEEN ? AND ? GROUP BY i.id ORDER BY total DESC",
            (inicio, fim))]

    def resumo(self) -> dict:
        itens = self.buscar()
        return {
            "itens": len(itens),
            "unidades": sum(i.saldo for i in itens),
            "zerados": sum(1 for i in itens if i.saldo <= 0),
            "abaixo_do_minimo": sum(1 for i in itens if i.abaixo_do_minimo),
            "pedidos_abertos": len(self.pedidos(abertos=True)),
            "emprestimos_atrasados": len(self.emprestimos_atrasados()),
        }
