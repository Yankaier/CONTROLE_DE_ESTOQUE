"""Interface de linha de comando do controle de estoque."""

import argparse
import sys

from .banco import conectar
from .servico import ErroEstoque, Estoque


def moeda(valor: float) -> str:
    texto = f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {texto}"


def imprimir_produtos(produtos) -> None:
    if not produtos:
        print("Nenhum produto encontrado.")
        return
    print(f"{'CÓDIGO':<10} {'NOME':<25} {'CATEGORIA':<15} {'QTD':>6} {'MÍN':>5} {'PREÇO':>14}")
    print("-" * 80)
    for p in produtos:
        alerta = "  ⚠" if p.abaixo_do_minimo else ""
        print(f"{p.codigo:<10} {p.nome[:25]:<25} {p.categoria[:15]:<15} "
              f"{p.quantidade:>6} {p.estoque_minimo:>5} {moeda(p.preco):>14}{alerta}")


def criar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="estoque", description="Controle de Estoque")
    parser.add_argument("--banco", default="estoque.db", help="arquivo do banco SQLite")
    sub = parser.add_subparsers(dest="comando", required=True)

    p = sub.add_parser("cadastrar", help="cadastra um novo produto")
    p.add_argument("codigo")
    p.add_argument("nome")
    p.add_argument("--categoria", default="Geral")
    p.add_argument("--preco", type=float, default=0.0)
    p.add_argument("--minimo", type=int, default=0, help="estoque mínimo")

    p = sub.add_parser("listar", help="lista produtos")
    p.add_argument("filtro", nargs="?", default="")

    p = sub.add_parser("atualizar", help="altera dados de um produto")
    p.add_argument("codigo")
    p.add_argument("--nome")
    p.add_argument("--categoria")
    p.add_argument("--preco", type=float)
    p.add_argument("--minimo", type=int)

    p = sub.add_parser("remover", help="remove um produto")
    p.add_argument("codigo")

    for nome, ajuda in (("entrada", "registra entrada de itens"),
                        ("saida", "registra saída de itens")):
        p = sub.add_parser(nome, help=ajuda)
        p.add_argument("codigo")
        p.add_argument("quantidade", type=int)
        p.add_argument("--obs", default="", help="observação")

    p = sub.add_parser("historico", help="mostra as movimentações")
    p.add_argument("codigo", nargs="?")

    sub.add_parser("alertas", help="produtos abaixo do estoque mínimo")
    sub.add_parser("resumo", help="resumo geral do estoque")
    return parser


def main(argv=None) -> int:
    args = criar_parser().parse_args(argv)
    estoque = Estoque(conectar(args.banco))
    try:
        match args.comando:
            case "cadastrar":
                p = estoque.cadastrar(args.codigo, args.nome, args.categoria,
                                      args.preco, args.minimo)
                print(f"Produto {p.codigo} - {p.nome} cadastrado.")
            case "listar":
                imprimir_produtos(estoque.listar(args.filtro))
            case "atualizar":
                p = estoque.atualizar(args.codigo, nome=args.nome, categoria=args.categoria,
                                      preco=args.preco, estoque_minimo=args.minimo)
                print(f"Produto {p.codigo} atualizado.")
            case "remover":
                estoque.remover(args.codigo)
                print(f"Produto {args.codigo.upper()} removido.")
            case "entrada" | "saida":
                acao = estoque.entrada if args.comando == "entrada" else estoque.saida
                p = acao(args.codigo, args.quantidade, args.obs)
                rotulo = "Entrada" if args.comando == "entrada" else "Saída"
                print(f"{rotulo} registrada. {p.nome}: {p.quantidade} em estoque.")
                if p.abaixo_do_minimo:
                    print(f"⚠ Atenção: {p.nome} está no estoque mínimo ou abaixo dele.")
            case "historico":
                movs = estoque.historico(args.codigo)
                if not movs:
                    print("Nenhuma movimentação registrada.")
                for m in movs:
                    sinal = "+" if m["tipo"] == "ENTRADA" else "-"
                    obs = f"  ({m['observacao']})" if m["observacao"] else ""
                    print(f"{m['data_hora']}  {m['codigo']:<10} {m['nome'][:25]:<25} "
                          f"{sinal}{m['quantidade']}{obs}")
            case "alertas":
                imprimir_produtos(estoque.abaixo_do_minimo())
            case "resumo":
                r = estoque.resumo()
                print(f"Produtos cadastrados:   {r['total_produtos']}")
                print(f"Itens em estoque:       {r['total_itens']}")
                print(f"Valor total do estoque: {moeda(r['valor_total'])}")
                print(f"Abaixo do mínimo:       {r['abaixo_do_minimo']}")
    except ErroEstoque as erro:
        print(f"Erro: {erro}", file=sys.stderr)
        return 1
    return 0
