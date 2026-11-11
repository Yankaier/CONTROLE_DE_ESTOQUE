@echo off
rem Cria um atalho na Area de Trabalho para abrir o Controle de Estoque.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\Controle de Estoque.lnk'); $s.TargetPath='%~dp0Abrir Controle de Estoque.bat'; $s.WorkingDirectory='%~dp0'; $s.IconLocation='%~dp0python\python.exe,0'; $s.Save()"
echo Atalho "Controle de Estoque" criado na Area de Trabalho.
pause
