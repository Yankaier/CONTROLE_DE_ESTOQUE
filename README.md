# Controle de Estoque — Almoxarifado

Sistema de controle de estoque em **Python** (só biblioteca padrão: **SQLite** + linha de comando).
Não precisa instalar nada além do Python 3.10+.

O projeto segue o mesmo modelo de dados e as mesmas regras do app **Movimentação do Almoxarifado**
(artefato do Claude usado no balcão, que lança na planilha *CONTROLE DE ESTOQUES 2.0* do SharePoint).
Ele lê o arquivo **Movimento do dia** baixado do app e gera arquivos no mesmo formato.

## Versão web (privada)

Uma versão web com as **mesmas abas do app**: Início, Movimentação, Pedidos, Inventário e, em
**Mais**, Descarte, Movimento do dia, Terminais, Relatórios e Pessoas. Ela grava direto na planilha
**CONTROLE DE ESTOQUES 2.0** do mesmo jeito que o app grava.

### Abrir

**Sem instalar nada (Windows):** baixe o `EstoqueAlmoxarifado.zip`, extraia e dê dois cliques em
**Abrir Controle de Estoque.bat**. O Python já vem dentro da pasta. Para gerar o zip de novo com o
código atual: `pacote-windows/empacotar.sh`.

Com Python instalado: no Windows, dê dois cliques em **`iniciar.bat`**. Na primeira vez ele prepara tudo (precisa do
Python instalado) e abre o navegador em `http://127.0.0.1:5000`. No Linux ou Mac, use `./iniciar.sh`.

Pelo terminal:

```bash
pip install -r requirements.txt
python -m estoque web
```

### Privado

- **Só o seu computador acessa:** o app só aceita conexões da própria máquina.
- **Tudo pede senha:** no primeiro acesso você cria a senha (8 caracteres ou mais), e todas as páginas pedem login.
- **Proteções de login:** a sessão expira em 12 horas e, depois de 8 tentativas erradas, o login fica bloqueado por 15 minutos.
- **Formulários protegidos:** os formulários têm proteção contra envio forjado (CSRF).
- **Senha guardada com segurança:** a senha fica guardada com hash. Para trocar, use **Mais ▸ Trocar senha**.
- **Dados fora do GitHub:** banco, planilhas, cópias de segurança e CSVs não vão para o repositório (`.gitignore`).
- **Uso no celular (opcional):** para usar no celular ou tablet na mesma rede Wi-Fi, rode
  `python -m estoque web --rede`. Mesmo assim, continua pedindo senha.

### Integração com a planilha

Em **Mais ▸ Planilha** escolha uma das duas formas:

1. **Pasta sincronizada (recomendado):**
   - No SharePoint, abra a biblioteca da planilha e clique em **Sincronizar**. O OneDrive cria uma pasta no seu computador.
   - Cole no app o caminho do `.xlsx` dessa pasta.
   - Marque **Enviar à planilha automaticamente a cada registro**.
   - Pronto: cada saída, entrada, pedido entregue, descarte ou item novo vai direto para a planilha, e o OneDrive sobe para o SharePoint.
2. **Enviar o arquivo:**
   - Carregue o `.xlsx` baixado do SharePoint.
   - Trabalhe normalmente.
   - No fim, use **Baixar cópia** e suba de volta no SharePoint.

**Botões da tela Planilha:**

- **Enviar** grava os lançamentos pendentes na aba **Movimentação**. Cada serial vira uma linha, e as unidades sem serial entram numa linha com lote "-".
- O mesmo envio também grava:
  - os itens novos na aba **Contagem**, copiando as fórmulas da última linha;
  - as correções de cadastro;
  - a aba **DESCARTES** inteira.
- Antes de gravar, uma cópia do arquivo vai para `backups-estoque/` (ficam as 30 últimas).
- **Trazer** lê o que foi lançado direto na planilha: linhas novas da Movimentação, itens da Contagem e descartes. Pode rodar sempre que quiser, porque nada é duplicado.
- A planilha é editada no XML de dentro do `.xlsx`, igual ao app. Por isso fórmulas, tabela, filtros e formatação continuam como estão.
- Feche a planilha no Excel antes de enviar.
- Não apague linhas da Movimentação: para corrigir um lançamento, use **Estornar**.

### Usar no celular e no notebook ao mesmo tempo

- **Como funciona:** o notebook é o "servidor". O celular abre o app do notebook pela rede Wi-Fi. Os dois usam **o mesmo banco ao mesmo tempo**, sem precisar sincronizar.
- **Como ligar:** em **Gestão ▸ Aparelhos**, clique em **Ligar acesso pelo celular** e depois em **Conectar um celular**. Leia o QR code com o celular, que precisa estar no mesmo Wi-Fi.
- **Segurança:**
  - Conexão **HTTPS**, com certificado criado no próprio notebook.
  - Só entra **aparelho autorizado** pelo QR code. O QR vale 10 minutos e serve para um aparelho só. Além disso, a senha continua sendo pedida.
  - Aparelhos podem ser **desconectados** a qualquer momento.
  - Apagar dados, testar, restaurar e trocar a planilha **só funcionam no notebook**.
  - Cada lançamento guarda **de qual aparelho veio**.
- **Uso simultâneo:**
  - As gravações acontecem **uma de cada vez**, então dois aparelhos não conseguem tirar mais do que o saldo.
  - Formulário enviado duas vezes (toque duplo ou Wi-Fi lento) **não registra em dobro**.
- **Planilha:**
  - O app relê a planilha sozinho quando ela muda e antes de cada envio.
  - Avisa quando ela está aberta no Excel ou quando o OneDrive criou uma cópia em conflito.
- **Limitações:**
  - O notebook precisa estar ligado, com o app aberto.
  - Redes que isolam os aparelhos (comum em Wi-Fi de visitante ou de empresa) impedem a conexão. Nesse caso, use o roteador do celular (hotspot) do notebook.

### Dados e teste (testar antes de usar a planilha real)

Em **Gestão ▸ Dados e teste**:

- **Testar com uma planilha de teste:**
  - Envie uma cópia da planilha. O app passa a trabalhar numa cópia separada, guardada na pasta `teste`.
  - Tudo o que você registrar e enviar vai só para essa cópia; a planilha real da nuvem não é tocada.
  - Uma faixa "Modo teste" aparece em todas as telas enquanto o teste estiver ligado.
- **Encerrar teste:** apaga os dados do teste (opcional), volta para a planilha real e traz os dados dela.
- **Apagar dados do app:** pede para digitar APAGAR e a sua senha. Senha, nome e configuração da planilha continuam.
- **Cópias de segurança do banco:**
  - São feitas sozinhas antes de apagar, restaurar, começar ou encerrar um teste. Também dá para fazer na hora.
  - Ficam as 30 últimas, que você pode baixar ou restaurar.

### O que dá para fazer em cada aba

| Aba | O que faz |
|---|---|
| Início | Busca (aceita leitor de código de barras), atalhos e alertas: mínimo, empréstimos atrasados, pedidos, pendentes |
| Movimentação | Saída/entrada com seriais, OS, NF, empréstimo, "lançar mesmo assim"; receber NF com vários itens; cadastrar e corrigir itens; estornar e excluir pendentes |
| Pedidos | Pedido → separado → entregue (dá baixa), cancelar; empréstimos em aberto e devolução |
| Inventário | Contar uma estante e ajustar o saldo só onde há diferença |
| Descarte | Do estoque (gera saída na área Descarte) ou de fora; numeração D-0001 |
| Movimento do dia | Tudo do dia, totais, imprimir e baixar `.csv` |
| Terminais | Checklist de entrada/saída com OK/Defeito/N/A |
| Relatórios | Consumo por área/pessoa/item/mês, previsão de falta, mínimo sugerido (aplicar com um clique), lista de compras em `.csv` |
| Pessoas | Quem retira e de qual área |

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

# Direto com a planilha .xlsx
python -m estoque planilha trazer "CONTROLE DE ESTOQUES 2.0.xlsx"
python -m estoque planilha enviar "CONTROLE DE ESTOQUES 2.0.xlsx"
```

A importação cria os itens que ainda não existem (pela estante, PT, caixa, SKU e descrição) e pula
as linhas já importadas, então dá para importar o mesmo arquivo mais de uma vez.

Os dados ficam em `estoque.db` (use `--banco outro.db` para escolher outro arquivo). O `.gitignore`
não deixa o banco nem os CSVs irem para o GitHub, para que dados reais do almoxarifado não fiquem públicos.

## Testes

```bash
python -m unittest discover -s tests -t . -v
```

Os testes da versão web rodam quando o Flask está instalado. Sem ele, são pulados.

## Estrutura

```
controle-de-estoque/
├── estoque/
│   ├── banco.py      # tabelas SQLite (mesmo modelo do app)
│   ├── servico.py    # regras: itens, lançamentos, empréstimos, pedidos, descartes, relatórios
│   ├── planilha.py   # importa/exporta o CSV "Movimento do dia" do app
│   ├── xlsx.py       # lê e grava a planilha CONTROLE DE ESTOQUES 2.0 (.xlsx)
│   ├── sincronizar.py# trazer da planilha / enviar para a planilha
│   ├── cli.py        # comandos de terminal
│   └── web/          # versão web (Flask): telas, estilo e login
├── iniciar.bat       # abre a versão web no Windows
├── iniciar.sh        # abre a versão web no Linux/Mac
└── tests/
```

## Próximos passos (ideias)

- Comprovante de entrega com assinatura na tela (como no app)
- Fotos no checklist de terminais
