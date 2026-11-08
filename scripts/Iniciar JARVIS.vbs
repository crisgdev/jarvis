Option Explicit
' JARVIS: lanzador silencioso (sin ventana de consola).
' Doble clic para iniciar. Corregir codigo = cerrar y volver a abrir; nada que recompilar.
Dim fso, sh, scriptDir, projectDir
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
projectDir = fso.GetParentFolderName(scriptDir)
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = projectDir
sh.Run "venv\Scripts\pythonw.exe main.py --background", 0, False
Set sh = Nothing
Set fso = Nothing
