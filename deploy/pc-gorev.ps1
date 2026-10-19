<#
m2kira — PC görevi: hepsiemlak'ı PC açıkken 2 saatte bir tarayıp GitHub'a besleme olarak gönderir.
(hepsiemlak, GitHub sunucularının IP'lerini Cloudflare doğrulamasında engelliyor; ev interneti gerekiyor.)

  powershell -ExecutionPolicy Bypass -File deploy\pc-gorev.ps1            # kur / güncelle
  powershell -ExecutionPolicy Bypass -File deploy\pc-gorev.ps1 -Kaldir    # kaldır

Görev yalnızca oturum açıkken çalışır, pencere açmaz (pythonw), kaçırılan çalışmayı PC açılınca yapar.
Kayıt: data\m2kira.log
#>
param([switch]$Kaldir, [int]$Saat = 2)

$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
$name = "m2kira hepsiemlak"

if ($Kaldir) {
    Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Görev kaldırıldı: $name"
    exit 0
}

$pyw = (Get-Command pythonw -ErrorAction SilentlyContinue).Source
if (-not $pyw) { $pyw = Join-Path $env:LOCALAPPDATA "Microsoft\WindowsApps\pythonw.exe" }
if (-not (Test-Path $pyw)) { Write-Host "pythonw.exe bulunamadı" -ForegroundColor Red; exit 1 }

$action = New-ScheduledTaskAction -Execute $pyw -Argument ('"' + (Join-Path $root "main.py") + '" feed-push') -WorkingDirectory $root
$t1 = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(10) -RepetitionInterval (New-TimeSpan -Hours $Saat) -RepetitionDuration (New-TimeSpan -Days 3650)
$t2 = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$set = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 40) -MultipleInstances IgnoreNew
$pr = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $name -Action $action -Trigger @($t1, $t2) -Settings $set -Principal $pr `
    -Description "m2kira: hepsiemlak'ı tarar, GitHub'a besleme gönderir (deploy\pc-gorev.ps1)" -Force | Out-Null

$task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
if ($task) {
    $info = Get-ScheduledTaskInfo -TaskName $name
    Write-Host "Görev kuruldu: $name  (her $Saat saatte bir + oturum açılışında)" -ForegroundColor Green
    Write-Host "Sonraki çalışma: $($info.NextRunTime)"
} else {
    Write-Host "Görev kurulamadı." -ForegroundColor Red; exit 1
}
