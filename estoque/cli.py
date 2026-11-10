"""Interface de linha de comando do almoxarifado."""

import argparse
import sys

from .banco import conectar
from .planilha import exportar_dia, importar_dia
from .servico import Almoxarifado, ErroEstoque, hoje


def imprimir_itens(itens) -> None:
    if not itens:
        print("Nenhum item encontrado.")
        return
    print(f"{'ID':>4}  {'LOCAL':<24} {'SKU':<12} {'DESCRIÇÃO':<32} {'SALDO':>6} {'MÍN':>4}")
    print("-" * 90)
    for i in itens:
        local = f"{i.estante} · {i.pt}" + (f" · cx {i.caixa}" if i.caixa != "-" else "")
        alerta = "  ⚠" if i.abaixo_do_minimo else ""
        print(f"{i.id:>4}  {local[:24]:<24} {i.sku[:12]:<12} {i.descricao[:32]:<32} {i.saldo:>6} {i.minimo:>4}{alerta}")
        if i.seriais:
            print(f"{'':6}seriais: {', '.join(i.seriais)}")


def imprimir_lancamentos(lancs) -> None:
    if not lancs:
        print("Nenhum lançamento.")
        return
    for l in lancs:
        sinal = "-" if l["movim"] == "Saída" or l["qtd"] < 0 else "+"
        extra = []
        if l["seriais"]:
            extra.append(l["seriais"])
        if l["emprestimo"]:
            extra.append("empréstimo devolvido" if l["devolvido_por"] else f"empréstimo até {l['devolver_ate']}")
        if l["estornado_por"]:
            extra.append("ESTORNADO")
        quem = " · ".join(x for x in (l["solicitante"], l["area"]) if x)
        print(f"#{l['id']:<5} {l['criado_em'][:16]}  {sinal}{abs(l['qtd']):<5} {l['descricao'][:30]:<30} "
              f"{quem}{'  (' + '; '.join(extra) + ')' if extra else ''}")


def _dados_lanc(p: argparse.ArgumentParser) -> None:
    p.add_argument("item", help="id, SKU ou serial do item")
    p.add_argument("qtd", type=int, nargs="?", help="quantidade (padrão: nº de seriais ou 1)")
    p.add_argument("--serial", action="append", default=[], help="serial/lote (pode repetir)")
    p.add_argument("--solic", default="", help="solicitante / origem")
    p.add_argument("--area", default="")
    p.add_argument("--os", default="", help="ordem de serviço")
    p.add_argument("--nf", default="", help="nota fiscal / documento")
    p.add_argument("--obs", default="")
    p.add_argument("--data", help="AAAA-MM-DD (padrão: hoje)")


def criar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="estoque", description="Controle de Estoque — Almoxarifado")
    parser.add_argument("--banco", default="estoque.db", help="arquivo do banco SQLite")
    sub = parser.add_subparsers(dest="comando", required=True)

    p = sub.add_parser("cadastrar", help="cadastra um item novo")
    p.add_argument("descricao")
    p.add_argument("--sku", default="-")
    p.add_argument("--estante", default="-")
    p.add_argument("--pt", default="-", help="prateleira")
    p.add_argument("--caixa", default="-")
    p.add_argument("--minimo", type=int, default=0)
    p.add_argument("--saldo", type=int, default=0, help="saldo inicial")
    p.add_argument("--serial", action="append", default=[])

    p = sub.add_parser("buscar", help="procura por descrição, SKU, serial ou estante")
    p.add_argument("termo", nargs="?", default="")

    p = sub.add_parser("corrigir", help="corrige local, nome, SKU ou mínimo de um item")
    p.add_argument("item")
    for c in ("descricao", "sku", "estante", "pt", "caixa"):
        p.add_argument(f"--{c}")
    p.add_argument("--minimo", type=int)

    _dados_lanc(sub.add_parser("entrada", help="registra entrada"))
    p = sub.add_parser("saida", help="registra saída")
    _dados_lanc(p)
    p.add_argument("--forcar", action="store_true", help="lançar mesmo sem saldo")
    p.add_argument("--emprestimo", metavar="DEVOLVER_ATE", help="empréstimo: data para devolver (AAAA-MM-DD)")

    p = sub.add_parser("contagem", help="ajusta o saldo para o valor contado")
    p.add_argument("item")
    p.add_argument("contado", type=int)

    p = sub.add_parser("estornar", help="estorna um lançamento")
    p.add_argument("lancamento", type=int)
    p.add_argument("motivo")

    p = sub.add_parser("historico", help="últimos lançamentos")
    p.add_argument("item", nargs="?")

    sub.add_parser("emprestimos", help="empréstimos em aberto")
    p = sub.add_parser("devolver", help="registra a devolução de um empréstimo")
    p.add_argument("lancamento", type=int)

    p = sub.add_parser("pedido", help="pedidos da montagem")
    ps = p.add_subparsers(dest="acao", required=True)
    pn = ps.add_parser("novo", help="cria pedido: estoque pedido novo LUAN 12:2 SKU-X:1")
    pn.add_argument("solicitante")
    pn.add_argument("itens", nargs="+", metavar="ITEM:QTD")
    pn.add_argument("--area", default="Montagem")
    pn.add_argument("--os", default="")
    pn.add_argument("--obs", default="")
    ps.add_parser("listar", help="pedidos em aberto")
    for acao in ("separar", "entregar", "cancelar"):
        ps.add_parser(acao).add_argument("num", help="ex.: P-001")

    p = sub.add_parser("descarte", help="registra descarte")
    p.add_argument("motivo")
    p.add_argument("--item", help="item do estoque (id, SKU ou serial); sem ele, é material de fora")
    p.add_argument("--material", default="")
    p.add_argument("--qtd", type=int)
    p.add_argument("--serial", action="append", default=[])
    p.add_argument("--resp", default="", help="responsável")
    p.add_argument("--destino", default="")

    p = sub.add_parser("dia", help="movimento do dia")
    p.add_argument("data", nargs="?", help="AAAA-MM-DD (padrão: hoje)")
    p.add_argument("--csv", help="salva no formato do app (Movimento do dia .csv)")

    p = sub.add_parser("importar", help="importa o CSV 'Movimento do dia' baixado do app")
    p.add_argument("arquivo", nargs="+")

    sub.add_parser("alertas", help="itens no mínimo ou abaixo e empréstimos atrasados")
    sub.add_parser("resumo", help="resumo geral")
    return parser


def _parse_itens(textos):
    itens = []
    for t in textos:
        ref, _, q = t.rpartition(":")
        if not ref:
            ref, q = q, "1"
        try:
            itens.append((ref, int(q)))
        except ValueError:
            raise ErroEstoque(f"Use ITEM:QTD (ex.: 12:3). Recebido: {t}") from None
    return itens


def executar(alm: Almoxarifado, a) -> None:
    dados = lambda: dict(solicitante=a.solic, area=a.area, os=a.os, nf=a.nf, obs=a.obs, data=a.data)
    match a.comando:
        case "cadastrar":
            i = alm.cadastrar_item(a.descricao, a.sku, a.estante, a.pt, a.caixa, a.minimo, a.saldo, a.serial)
            print(f"Item #{i.id} {i.descricao} cadastrado em {i.local} com saldo {i.saldo}.")
        case "buscar":
            imprimir_itens(alm.buscar(a.termo))
        case "corrigir":
            i = alm.corrigir_item(a.item, descricao=a.descricao, sku=a.sku, estante=a.estante,
                                  pt=a.pt, caixa=a.caixa, minimo=a.minimo)
            print(f"Item #{i.id} corrigido: {i.descricao} · {i.local} · mínimo {i.minimo}.")
        case "entrada" | "saida":
            if a.comando == "entrada":
                l = alm.entrada(a.item, a.qtd, a.serial, **dados())
            else:
                l = alm.saida(a.item, a.qtd, a.serial, forcar=a.forcar, emprestimo=bool(a.emprestimo),
                              devolver_ate=a.emprestimo, **dados())
            i = alm.item(l["item_id"])
            print(f"{l['movim']} #{l['id']} registrada: {l['qtd']} un de {i.descricao}. Saldo: {i.saldo}.")
            if i.abaixo_do_minimo:
                print(f"⚠ {i.descricao} está no mínimo ou abaixo ({i.saldo}/{i.minimo}).")
        case "contagem":
            l = alm.ajustar_contagem(a.item, a.contado)
            print("Saldo já confere com a contagem." if l is None else f"Ajuste #{l['id']}: {l['obs']}.")
        case "estornar":
            l = alm.estornar(a.lancamento, a.motivo)
            print(f"Estorno #{l['id']} registrado ({l['movim']} de {abs(l['qtd'])} un).")
        case "historico":
            imprimir_lancamentos(alm.historico(a.item))
        case "emprestimos":
            imprimir_lancamentos(alm.emprestimos_abertos())
        case "devolver":
            l = alm.devolver(a.lancamento)
            print(f"Devolução #{l['id']} registrada.")
        case "pedido":
            if a.acao == "novo":
                p = alm.criar_pedido(a.solicitante, _parse_itens(a.itens), a.area, a.os, a.obs)
                print(f"Pedido {p['num']} de {p['solicitante']} criado com {len(p['itens'])} item(ns).")
            elif a.acao == "listar":
                ps = alm.pedidos(abertos=True)
                if not ps:
                    print("Nenhum pedido em aberto.")
                for p in ps:
                    print(f"{p['num']}  {p['data']}  {p['solicitante']:<15} {p['status']}")
                    for it in p["itens"]:
                        print(f"        {it['qtd']:>4} × {it['descricao']}  (saldo {it['saldo']})")
            elif a.acao == "entregar":
                r = alm.entregar_pedido(a.num)
                print(f"Pedido {r['pedido']['num']} entregue: {len(r['lancamentos'])} saída(s).")
                for n in r["nao_entregues"]:
                    print(f"  Não entregue: {n['descricao']} — {n['motivo']}")
            else:
                p = alm.separar_pedido(a.num) if a.acao == "separar" else alm.cancelar_pedido(a.num)
                print(f"Pedido {p['num']}: {p['status']}.")
        case "descarte":
            d = alm.descartar(a.motivo, a.resp, a.qtd, a.item, a.material, seriais=a.serial, destino=a.destino)
            print(f"Descarte {d['num']} registrado: {d['qtd']} un de {d['material']}.")
        case "dia":
            dia = a.data or hoje()
            if a.csv:
                n = exportar_dia(alm, dia, a.csv)
                print(f"{n} lançamento(s) de {dia} salvos em {a.csv}.")
            else:
                imprimir_lancamentos(alm.movimento_do_dia(dia))
        case "importar":
            for arq in a.arquivo:
                r = importar_dia(alm, arq)
                print(f"{arq}: {r['importados']} importado(s), {r['repetidos']} já existiam, "
                      f"{r['itens_novos']} item(ns) novo(s).")
        case "alertas":
            print("== No estoque mínimo ou abaixo ==")
            imprimir_itens(alm.abaixo_do_minimo())
            print("\n== Empréstimos atrasados ==")
            imprimir_lancamentos(alm.emprestimos_atrasados())
        case "resumo":
            r = alm.resumo()
            print(f"Itens cadastrados:      {r['itens']}")
            print(f"Unidades em estoque:    {r['unidades']}")
            print(f"Itens zerados:          {r['zerados']}")
            print(f"No mínimo ou abaixo:    {r['abaixo_do_minimo']}")
            print(f"Pedidos em aberto:      {r['pedidos_abertos']}")
            print(f"Empréstimos atrasados:  {r['emprestimos_atrasados']}")


def main(argv=None) -> int:
    args = criar_parser().parse_args(argv)
    conexao = conectar(args.banco)
    try:
        executar(Almoxarifado(conexao), args)
    except ErroEstoque as erro:
        print(f"Erro: {erro}", file=sys.stderr)
        return 1
    finally:
        conexao.close()
    return 0
