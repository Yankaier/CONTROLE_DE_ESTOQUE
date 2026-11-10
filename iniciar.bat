@echo off
rem Abre o Controle de Estoque (versao web) neste computador.
rem Na primeira vez cria o ambiente e instala o Flask; depois so abre.
cd /d "%~dp0"
if not exist .venv (
  echo Preparando na primeira vez...
  py -3 -m venv .venv || python -m venv .venv
  .venv\Scripts\python -m pip install -q -r requirements.txt
)
rem O banco fica fora do OneDrive (sincronizar o arquivo do banco pode corrompe-lo)
if not exist "%LOCALAPPDATA%\EstoqueAlmoxarifado" mkdir "%LOCALAPPDATA%\EstoqueAlmoxarifado"
start "" http://127.0.0.1:5000
.venv\Scripts\python -m estoque --banco "%LOCALAPPDATA%\EstoqueAlmoxarifado\estoque.db" web
pause
