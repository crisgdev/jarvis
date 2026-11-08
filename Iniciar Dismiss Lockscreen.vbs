' Iniciar Dismiss Lockscreen.vbs
' Arranca dismiss_lockscreen.py en segundo plano (sin ventana de consola).

Set sh = CreateObject("WScript.Shell")
sh.Run """C:\Users\USER\Documents\Proyectos-Ingenieria-Sistemas\Personales\jarvis\venv\Scripts\pythonw.exe"" ""C:\Users\USER\Documents\Proyectos-Ingenieria-Sistemas\Personales\jarvis\dismiss_lockscreen.py""", 0, False
Set sh = Nothing