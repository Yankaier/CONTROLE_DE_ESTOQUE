# Controle de Estoque — Almoxarifado

Sistema de controle de estoque em **Python** (só biblioteca padrão: **SQLite** + linha de comando).
Não precisa instalar nada além do Python 3.10+.

O projeto segue o mesmo modelo de dados e as mesmas regras do app **Movimentação do Almoxarifado**
(artefato do Claude usado no balcão, que lança na planilha *CONTROLE DE ESTOQUES 2.0* do SharePoint).
Ele lê o arquivo **Movimento do dia** baixado do app e gera arquivos no mesmo formato.

## Como o projeto se liga ao app

| No app (Movimentação do Almoxarifado)        | Neste projeto                                   |
|----------------------------------------------|-------------------------------------------------|
| Item: estante, PT, caixa, SKU, descrição     | tabela `itens`                                  |
| Seriais / lotes em estoque                   | tabela `seriais`                                |
| Entrada, Saída, Saldo Inicial                | tabela `lancamentos` (`movim`)                  |
| Solicitante, Área, OS, NF, Observação        | colunas de `lancamentos`                        |
| Pendente / Na planilha                       | `lancamentos.status` (`pendente` / `lancado`)   |
| Empréstimo ("devolver até") e devolução      | `emprestimo`, `devolver_ate`, `devolvido_por`   |
| Estorno                                      | `estorno_de`, `estornado_por`                   |
| Pedidos da montagem (P-001)                  | tabelas `pedidos` e `pedido_itens`              |
| Descarte (D-0001)                            | tabela `descartes`                              |
| Pessoas (quem retira e de qual área)         | tabela `pessoas`                                |
| Estoque mínimo                               | `itens.minimo`                                  |
| Botão "Baixar" do Movimento do dia (.csv)    | `estoque importar` e `estoque dia --csv`        |

### Regras iguais às do app

- **Saldo** = soma dos lançamentos. *Saldo Inicial* é usado no cadastro e nos ajustes de contagem.
- **Seriais**: o serial que entra fica em estoque e o que sai precisa estar em estoque. Num item com
  seriais, é preciso dizer quais saíram. Bipar o serial já identifica o item e o serial.
- **Saída maior que o saldo** é bloqueada, a não ser que se use `--forcar` ("lançar mesmo assim").
- **Estoque mínimo**: alerta quando o mínimo é maior que 0 e o saldo está no mínimo ou abaixo.
- **Empréstimo**: saída com data para devolver. Passou da data, aparece como atrasado.
- **Estorno**: lança o movimento contrário e marca o original como estornado.
- **Pedidos**: `pedido → separado → entregue` (a entrega gera as saídas) ou `cancelado`.
- **Descarte do estoque** gera uma saída na área "Descarte".

## Como usar

```bash
# Cadastrar itens (com saldo inicial e seriais)
python -m estoque cadastrar "Cabo de rede cat6" --sku CB-06 --estante 3 --pt PT2 --caixa 12 --minimo 5 --saldo 10
python -m estoque cadastrar "Leitor de cartão" --sku LT-01 --estante 1 --pt PT1 --serial 818EZ001 --serial 818EZ002

# Movimentar (o item pode ser o id, o SKU ou um serial)
python -m estoque saida CB-06 6 --solic LUAN --area Montagem --os 0042/26
python -m estoque entrada CB-06 20 --solic "Fornecedor X" --area Fornecedor --nf 123
python -m estoque saida 818EZ001 --solic ANA --emprestimo 2026-11-20
python -m estoque devolver 4                  # nº do lançamento do empréstimo
python -m estoque estornar 3 "lançado errado"
python -m estoque contagem CB-06 23           # ajusta o saldo para o valor contado

# Pedidos da montagem
python -m estoque pedido novo LUAN CB-06:2 LT-01:1
python -m estoque pedido listar
python -m estoque pedido entregar P-001

# Descarte
python -m estoque descarte "queimado" --item LT-01 --serial 818EZ002 --resp JOAO

# Consultas
python -m estoque buscar cabo
python -m estoque historico CB-06
python -m estoque emprestimos
python -m estoque alertas
python -m estoque resumo
```

### Trocar dados com o app

```bash
# No app: Mais ▸ Movimento do dia ▸ Baixar  →  "Movimento do dia 2026-11-10.csv"
python -m estoque importar "Movimento do dia 2026-11-10.csv"

# Gerar o mesmo arquivo a partir deste banco (abre no Excel)
python -m estoque dia 2026-11-10 --csv "Movimento do dia 2026-11-10.csv"
```

A importação cria os itens que ainda não existem (pela estante, PT, caixa, SKU e descrição) e pula
as linhas já importadas, então dá para importar o mesmo arquivo mais de uma vez.

Os dados ficam em `estoque.db` (use `--banco outro.db` para escolher outro arquivo). O `.gitignore`
não deixa o banco nem os CSVs irem para o GitHub, para que dados reais do almoxarifado não fiquem públicos.

## Testes

```bash
python -m unittest -v
```

## Estrutura

```
controle-de-estoque/
├── estoque/
│   ├── banco.py      # tabelas SQLite (mesmo modelo do app)
│   ├── servico.py    # regras: itens, lançamentos, empréstimos, pedidos, descartes, relatórios
│   ├── planilha.py   # importa/exporta o CSV "Movimento do dia" do app
│   └── cli.py        # comandos de terminal
└── tests/
    └── test_estoque.py
```

## Próximos passos (ideias)

- Interface web (Flask) com as mesmas abas do app
- Ler direto a planilha CONTROLE DE ESTOQUES 2.0 (.xlsx)
- Inventário por estante e relatório de consumo/compras
