Option Explicit
' JARVIS: lanzador silencioso (sin ventana de consola).
' Doble clic para iniciar. Corregir codigo = cerrar y volver a abrir; nada que recompilar.
Dim sh
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = "C:\Users\USER\Documents\Proyectos-Ingenieria-Sistemas\Personales\jarvis"
sh.Run "venv\Scripts\pythonw.exe main.py --background", 0, False