# dismiss_lockscreen.ps1
# Intenta descartar el lock screen de Windows 10 al despertar.
# Se ejecuta como SYSTEM via Tarea Programada.

$ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
$logPath = "C:\Users\USER\Documents\Proyectos-Ingenieria-Sistemas\Personales\jarvis\logs\dismiss_lockscreen.log"
$lockFile = "C:\Users\USER\Documents\Proyectos-Ingenieria-Sistemas\Personales\jarvis\logs\dismiss_lockscreen.lock"

# Cooldown: no ejecutar si se ejecuto hace menos de 30 segundos
if (Test-Path $lockFile) {
    $lastRun = [DateTime]::Parse((Get-Content $lockFile -Raw).Trim())
    if ((Get-Date) - $lastRun -lt [TimeSpan]::FromSeconds(30)) {
        # Ya se ejecuto recientemente, salir sin hacer nada
        exit 0
    }
}
# Registrar timestamp de esta ejecucion
(Get-Date).ToString("yyyy-MM-dd HH:mm:ss") | Set-Content -Path $lockFile -NoNewline

# Esperar un poco por si LockApp tarda en arrancar
Start-Sleep -Seconds 2

# Metodo 1: Intentar matar LockApp.exe (el proceso del lock screen)
try {
    $lockApp = Get-Process -Name "LockApp" -ErrorAction SilentlyContinue
    if ($lockApp) {
        Stop-Process -Name "LockApp" -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 1
        Add-Content -Path $logPath -Value "[$ts] LockApp.exe terminado"
    } else {
        Add-Content -Path $logPath -Value "[$ts] LockApp.exe no encontrado"
    }
} catch {
    Add-Content -Path $logPath -Value "[$ts] Error terminando LockApp: $_"
}

# Metodo 2: SendKeys desactivado (el lock screen ya no aparece con los cambios de registro)
# Se mantiene comentado como respaldo por si acaso
# try {
#     Add-Type -AssemblyName System.Windows.Forms
#     [System.Windows.Forms.SendKeys]::SendWait("{ENTER}")
#     Add-Content -Path $logPath -Value "[$ts] SendKeys ejecutado (respaldo)"
# } catch {
#     Add-Content -Path $logPath -Value "[$ts] Error en SendKeys: $_"
# }

# Metodo 3: tscon desactivado (puede desconectar la sesion, no es seguro)
# Se mantiene comentado por si acaso

Add-Content -Path $logPath -Value "[$ts] Script completado (sin teclas, lock screen desactivado por registro)"