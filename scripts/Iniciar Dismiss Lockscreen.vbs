' Iniciar Dismiss Lockscreen.vbs
' Arranca dismiss_lockscreen.py en segundo plano (sin ventana de consola).

Dim fso, sh, scriptDir, projectDir
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
projectDir = fso.GetParentFolderName(scriptDir)
Set sh = CreateObject("WScript.Shell")
sh.Run """" & projectDir & "\venv\Scripts\pythonw.exe"" """ & projectDir & "\scripts\dismiss_lockscreen.py""", 0, False
Set sh = Nothing
Set fso = Nothing
