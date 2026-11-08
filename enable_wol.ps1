# enable_wol.ps1
# Habilita Wake-on-LAN en el adaptador Ethernet de la laptop (modo reversible).
#
# Uso (pide elevacion de administrador automaticamente):
#   powershell -ExecutionPolicy Bypass -File .\enable_wol.ps1        -> habilita WOL
#   powershell -ExecutionPolicy Bypass -File .\enable_wol.ps1 -Status -> solo muestra el estado actual
#   powershell -ExecutionPolicy Bypass -File .\enable_wol.ps1 -Undo   -> revierte TODO lo que hizo
#
# Antes de tocar nada guarda una copia de seguridad en .\wol_backup\
# (exportacion del registro + valores originales en JSON).

param(
    [switch]$Status,
    [switch]$Undo
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$TargetMac = '00:00:00:00:00:00'  # Reemplaza con la MAC de tu adaptador (ver ipconfig /all)
$ClassKey = 'HKLM:\SYSTEM\CurrentControlSet\Control\Class\{4d36e972-e325-11ce-bfc1-08002be10318}'
$BackupDir = Join-Path $PSScriptRoot 'wol_backup'
$BackupFile = Join-Path $BackupDir 'wol_backup.json'
$RunLog = Join-Path $BackupDir 'wol_last_run.log'

function Say([string]$msg, [string]$color = '') {
    if ($color) { Write-Host $msg -ForegroundColor $color } else { Write-Host $msg }
    Add-Content -Path $RunLog -Value $msg -Encoding UTF8
}

function Test-Admin {
    return ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).
        IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-Hiberboot {
    $hp = Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Power' -ErrorAction SilentlyContinue
    if (-not $hp) { return $null }
    $prop = $hp.PSObject.Properties['HiberbootEnabled']
    if ($prop) { return "$($prop.Value)" }
    return $null
}

# Re-eleva el script con permisos de administrador si no lo esta, espera a que
# termine (-Wait) y muestra el resultado en esta misma consola (via RunLog).
if (-not (Test-Admin)) {
    $argList = '-NoProfile -ExecutionPolicy Bypass -File "{0}"' -f $MyInvocation.MyCommand.Path
    if ($Status) { $argList += ' -Status' }
    if ($Undo) { $argList += ' -Undo' }
    New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null
    Remove-Item $RunLog -ErrorAction SilentlyContinue
    try {
        $p = Start-Process powershell.exe -Verb RunAs -ArgumentList $argList -Wait -PassThru
        Start-Sleep -Milliseconds 300
        if ($p.ExitCode -ne 0) {
            Write-Host "[ERROR] La ventana elevada termino con error (codigo $($p.ExitCode))." -ForegroundColor Red
            if (Test-Path $RunLog) { Write-Host (Get-Content $RunLog -Raw -Encoding UTF8) }
            exit $p.ExitCode
        }
        if (Test-Path $RunLog) {
            Write-Host (Get-Content $RunLog -Raw -Encoding UTF8)
            Remove-Item $RunLog -ErrorAction SilentlyContinue
        }
        exit 0
    } catch {
        Write-Host "[ERROR] No se pudo abrir como administrador (UAC cancelado?)." -ForegroundColor Red
        exit 1
    }
    exit 0
}

function Normalize-Mac([string]$m) {
    return (($m -replace '[^0-9a-fA-F]', '').ToUpper())
}

function Find-Adapter {
    $nic = Get-NetAdapter -ErrorAction SilentlyContinue |
        Where-Object { (Normalize-Mac $_.MacAddress) -eq (Normalize-Mac $TargetMac) } |
        Select-Object -First 1
    if (-not $nic) { $nic = Get-NetAdapter -Name 'Ethernet 3' -ErrorAction SilentlyContinue }
    if (-not $nic) { throw 'No se encontro el adaptador Ethernet. Ajusta $TargetMac o el nombre del adaptador.' }
    return $nic
}

function Find-InstanceKey([string]$guid) {
    if ($guid) {
        foreach ($k in Get-ChildItem $ClassKey -ErrorAction SilentlyContinue) {
            $p = Get-ItemProperty $k.PSPath -ErrorAction SilentlyContinue
            if (-not $p) { continue }
            $nc = $p.PSObject.Properties['NetCfgInstanceId']
            if ($nc -and "$($nc.Value)" -eq $guid) { return $k.PSPath }
        }
    }
    # Fallback: unica clave Realtek visible.
    foreach ($k in Get-ChildItem $ClassKey -ErrorAction SilentlyContinue) {
        $p = Get-ItemProperty $k.PSPath -ErrorAction SilentlyContinue
        if (-not $p) { continue }
        $dd = $p.PSObject.Properties['DriverDesc']
        if ($dd -and "$($dd.Value)" -match 'Realtek') { return $k.PSPath }
    }
    return $null
}

function Save-Backup($nic, $instancePath) {
    New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null
    $regFile = Join-Path $BackupDir 'nic_instance.reg'
    $vals = @{}
    if ($instancePath) {
        $item = Get-Item $instancePath
        foreach ($p in @('*WakeOnMagicPacket', 'EnablePME', '*WakeOnPattern', '*WakeOnLink', 'WakeOnLink')) {
            if ($null -ne $item.GetValue($p)) { $vals[$p] = "$($item.GetValue($p))" }
        }
        reg.exe export ($instancePath -replace '^HKLM:', 'HKLM') $regFile /y | Out-Null
    }
    $backup = [ordered]@{
        timestamp     = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
        adapter       = $nic.Name
        instancePath  = $instancePath
        regFile       = $regFile
        values        = $vals
        hiberboot     = Get-Hiberboot
    }
    $backup | ConvertTo-Json -Depth 5 | Set-Content -Path $BackupFile -Encoding UTF8
    Say "[WOL] Backup guardado en $BackupFile" 'Green'
}

function Get-NicStatus($nic, $instanceKey) {
    Say "Adaptador: $($nic.Name) ($($nic.InterfaceDescription))" 'Cyan'
    try {
        Get-NetAdapterPowerManagement -Name $nic.Name |
            Format-List WakeOnMagicPacket, WakeOnPattern, WakeOnLinkChange, DeviceSleepOnDisconnect
    } catch {
        Say "  (Get-NetAdapterPowerManagement no disponible: $($_.Exception.Message))"
    }
    if ($instanceKey) {
        $item = Get-Item $instanceKey
        Say "  Registro: *WakeOnMagicPacket = $($item.GetValue('*WakeOnMagicPacket'))"
        Say "  Registro: EnablePME          = $($item.GetValue('EnablePME'))"
    }
    Say "  Fast Startup (HiberbootEnabled) = $(Get-Hiberboot)"
}

function Apply-Wol($nic, $instanceKey) {
    Save-Backup $nic $instanceKey

    if ($instanceKey) {
        $item = Get-Item $instanceKey
        $item.SetValue('*WakeOnMagicPacket', '1')       # Despertar por paquete magico
        $item.SetValue('EnablePME', 1)                  # Power Management Events (permitir despertar)
        $item.SetValue('*WakeOnPattern', '0')           # No despertar por patrones (menos falsos positivos)
        $item.SetValue('*WakeOnLink', '0')              # No despertar por cambio de enlace
        $item.SetValue('WakeOnLink', 0)
        Say "[WOL] Registro del adaptador actualizado en $instanceKey" 'Green'
        Say "[WOL]   *WakeOnMagicPacket = $($item.GetValue('*WakeOnMagicPacket')) | EnablePME = $($item.GetValue('EnablePME'))" 'Green'
    } else {
        Say "[WOL] NO se localizo la clave de registro del adaptador; se usara el cmdlet solamente." 'Yellow'
    }

    try {
        Set-NetAdapterPowerManagement -Name $nic.Name `
            -WakeOnMagicPacket Enabled `
            -WakeOnPattern Disabled `
            -WakeOnLinkChange Disabled -ErrorAction Stop | Out-Null
        Say "[WOL] Cmdlet Set-NetAdapterPowerManagement aplicado." 'Green'
    } catch {
        Say "[WOL] Cmdlet no aplicado (se aplico por registro en su lugar): $($_.Exception.Message)" 'Yellow'
    }

    # Desactivar Fast Startup -> apagar = apagado total real (S5), necesario para WOL desde apagado.
    if ($null -ne (Get-Hiberboot)) {
        Set-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Power' -Name HiberbootEnabled -Value 0
        Say "[WOL] Fast Startup DESACTIVADO (shutdown ahora es apagado real S5)." 'Green'
    }

    Say ""
    Say "LISTO. El cambio total aplica tras REINICIAR la laptop." 'Green'
    Say "Despues: laptop enchufada a la corriente, apagala y mandale 'prende la pc' desde el celular."
}

function Undo-Changes {
    $b = Read-Backup
    Say "[WOL] Revertiendo cambios del $($b.timestamp) en adaptador '$($b.adapter)'..."

    if ($b.instancePath -and (Test-Path $b.instancePath)) {
        $item = Get-Item $b.instancePath
        foreach ($p in @('*WakeOnMagicPacket', 'EnablePME', '*WakeOnPattern', '*WakeOnLink', 'WakeOnLink')) {
            if ($b.values.PSObject.Properties[$p]) {
                $orig = "$($b.values.PSObject.Properties[$p].Value)"
                if ($p -in @('*WakeOnMagicPacket', '*WakeOnPattern', '*WakeOnLink')) {
                    $item.SetValue($p, $orig)          # REG_SZ
                } else {
                    $item.SetValue($p, [int]$orig)     # DWORD
                }
            } else {
                if ($null -ne $item.GetValue($p)) { $item.SetValue($p, $null) }  # no existia: borrar
            }
        }
        Say "[WOL] Registro del adaptador restaurado." 'Green'
    }
    if ($b.regFile -and (Test-Path $b.regFile)) {
        reg.exe import $b.regFile | Out-Null
        Say "[WOL] Exportacion del registro reimportada ($($b.regFile))." 'Green'
    }
    $origHiberboot = Get-Hiberboot
    if ($b.hiberboot -and $b.hiberboot -ne '') {
        if ($null -eq $origHiberboot) {
            New-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Power' -Name HiberbootEnabled -Value ([int]$b.hiberboot) -PropertyType DWord -Force | Out-Null
        } else {
            Set-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Power' -Name HiberbootEnabled -Value ([int]$b.hiberboot)
        }
    } elseif ($null -ne $origHiberboot) {
        Remove-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Power' -Name HiberbootEnabled -ErrorAction SilentlyContinue
    }
    Say "[WOL] Fast Startup restaurado."
    try { Set-NetAdapterPowerManagement -Name $b.adapter -WakeOnMagicPacket Disabled -ErrorAction Stop | Out-Null } catch {}
    Say "Deshacer completado. Reinicia la laptop para volver a la normalidad." 'Green'
}

function Read-Backup {
    if (-not (Test-Path $BackupFile)) { throw "No hay copia de seguridad en $BackupFile. Nada que revertir." }
    return (Get-Content $BackupFile -Raw | ConvertFrom-Json)
}

# ── Ejecucion principal ──
$nic = Find-Adapter
$instanceKey = Find-InstanceKey $nic.InterfaceGuid

if ($Status) {
    Get-NicStatus $nic $instanceKey
    exit 0
}
if ($Undo) {
    Undo-Changes
    exit 0
}

Apply-Wol $nic $instanceKey