# Controle de Estoque

Sistema de controle de estoque feito em **Python**, usando apenas a biblioteca padrão
(banco de dados **SQLite** + interface de linha de comando). Não precisa instalar nada além do Python 3.10+.

## Funcionalidades

- Cadastro, edição, busca e remoção de produtos
- Registro de **entradas** e **saídas** com histórico de movimentações
- Bloqueio de saída quando não há estoque suficiente
- Alerta de produtos no **estoque mínimo** ou abaixo dele
- Resumo geral: total de produtos, itens e valor do estoque

## Como usar

```bash
# Cadastrar produtos
python -m estoque cadastrar P001 "Caneta Azul" --categoria Papelaria --preco 2.50 --minimo 10
python -m estoque cadastrar P002 "Caderno 96 folhas" --categoria Papelaria --preco 15 --minimo 5

# Movimentar
python -m estoque entrada P001 50 --obs "Compra fornecedor"
python -m estoque saida P001 45 --obs "Entrega sala 3"

# Consultar
python -m estoque listar
python -m estoque listar papelaria      # filtra por nome, código ou categoria
python -m estoque historico P001
python -m estoque alertas
python -m estoque resumo
```

Os dados ficam no arquivo `estoque.db` (use `--banco outro.db` para escolher outro arquivo).
Veja todos os comandos com `python -m estoque --help`.

## Testes

```bash
python -m unittest -v
```

## Estrutura

```
controle-de-estoque/
├── estoque/
│   ├── banco.py     # conexão e criação das tabelas SQLite
│   ├── servico.py   # regras de negócio (produtos, movimentações, relatórios)
│   └── cli.py       # comandos de terminal
└── tests/
    └── test_estoque.py
```

## Banco de dados

| Tabela          | Campos principais                                                      |
|-----------------|------------------------------------------------------------------------|
| `produtos`      | código, nome, categoria, preço, quantidade, estoque mínimo             |
| `movimentacoes` | produto, tipo (ENTRADA/SAIDA), quantidade, observação, data e hora     |

## Próximos passos (ideias)

- Interface web (Flask) ou gráfica (Tkinter)
- Cadastro de fornecedores
- Exportar relatórios em CSV/PDF
