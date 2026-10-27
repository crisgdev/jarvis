Option Explicit
' JARVIS: cierra la instancia que corre main.py y la vuelve a lanzar.
' Sirve tras cambiar codigo: reinicio limpio sin compilar nada.
Dim sh, ps
Set sh = CreateObject("WScript.Shell")
ps = "powershell -NoProfile -Command ""Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'pythonw.exe' -and $_.CommandLine -like '*main.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"""
sh.Run ps, 0, True
WScript.Sleep 2000
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = "C:\Users\USER\Documents\Proyectos-Ingenieria-Sistemas\Personales\jarvis"
sh.Run "venv\Scripts\pythonw.exe main.py --background", 0, False