# Almoxarifado · página web

Página de entrada e saída de estoque ligada direto à planilha **CONTROLE DE ESTOQUES 2.0.xlsx** no SharePoint, via Microsoft Graph.

- Cada registro **acrescenta linhas** na tabela `movimentação`; nada é sobrescrito, então várias pessoas (aqui e no Excel) trabalham ao mesmo tempo.
- O login é o de cada pessoa na Microsoft (OAuth com PKCE). Não há senha, segredo ou chave neste repositório.
- `config.js` guarda o ID do aplicativo e do diretório (Microsoft Entra), que não são secretos.
