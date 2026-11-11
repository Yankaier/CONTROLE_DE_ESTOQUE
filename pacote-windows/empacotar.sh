#!/usr/bin/env sh
# Monta EstoqueAlmoxarifado.zip: app + Python 3.12 para Windows (pacote oficial assinado
# da Python Software Foundation no NuGet) + Flask. O zip roda sem instalar nada.
set -e
AQUI="$(cd "$(dirname "$0")" && pwd)"; RAIZ="$(dirname "$AQUI")"
TMP="$(mktemp -d)"; B="$TMP/EstoqueAlmoxarifado"
mkdir -p "$B/python" "$B/app"
curl -sSfL -o "$TMP/python.nupkg" https://api.nuget.org/v3-flatcontainer/python/3.12.10/python.3.12.10.nupkg
unzip -q "$TMP/python.nupkg" 'tools/*' -d "$TMP/nup" && cp -r "$TMP/nup/tools/." "$B/python/"
(cd "$B/python/Lib" && rm -rf test idlelib tkinter turtledemo ensurepip lib2to3 venv pydoc_data)
rm -rf "$B/python/include" "$B/python/libs" "$B/python/tcl" "$B/python/DLLs/_tkinter.pyd" "$B"/python/DLLs/tcl*.dll "$B"/python/DLLs/tk*.dll
pip download -q --only-binary=:all: --platform win_amd64 --python-version 3.12 -d "$TMP/wheels" -r "$RAIZ/requirements.txt" colorama
mkdir -p "$B/python/Lib/site-packages"
for w in "$TMP"/wheels/*.whl; do unzip -qo "$w" -d "$B/python/Lib/site-packages"; done
(cd "$RAIZ" && git archive HEAD estoque requirements.txt README.md | tar -x -C "$B/app")
cp "$AQUI/abrir.py" "$B/app/"; cp "$AQUI"/*.bat "$AQUI/LEIA-ME.txt" "$B/"
(cd "$TMP" && zip -qr9 EstoqueAlmoxarifado.zip EstoqueAlmoxarifado)
mv "$TMP/EstoqueAlmoxarifado.zip" "$RAIZ/" && rm -rf "$TMP"
echo "Pronto: $RAIZ/EstoqueAlmoxarifado.zip"
