<#
m2kira — "PC kapalıyken de bildirim" kurulumu (GitHub Actions)

Ne yapar:
  1. GitHub CLI (gh) yoksa winget ile kurar, GitHub hesabınla giriş yaptırır (tarayıcı açılır).
  2. Telegram bot token'ını sorar (BotFather'dan), bota /start yazmanı bekleyip chat id'yi bulur, .env'e yazar.
  3. Bu klasörü git deposu yapar, GitHub'da "m2kira" reposunu oluşturup kodu gönderir.
     .env, data/ (sahibinden oturumun dahil) asla gönderilmez (.gitignore).
  4. Telegram (ve varsa IMAP) bilgilerini repo "secrets" olarak kaydeder.
  5. İlk taramayı başlatır. Sonrası 30 dakikada bir ve her sabah 09:00'da kendiliğinden çalışır.

Çalıştırma (proje klasöründe PowerShell):
  powershell -ExecutionPolicy Bypass -File deploy\kurulum.ps1            # public repo (sınırsız ücretsiz dakika)
  powershell -ExecutionPolicy Bypass -File deploy\kurulum.ps1 -Private   # private repo (ayda 2000 dk -> 5 saatte bir tarama)
#>
param(
    [switch]$Private,
    [string]$RepoName = "m2kira"
)

$ErrorActionPreference = "Continue"   # PS 5.1: yönlendirilen stderr "Stop" ile betiği keser; hatalar elle kontrol ediliyor
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

function Quiet([scriptblock]$sb) { & $sb *> $null; return ($LASTEXITCODE -eq 0) }
function Step($msg) { Write-Host ""; Write-Host "==> $msg" -ForegroundColor Cyan }
function Fail($msg) { Write-Host "HATA: $msg" -ForegroundColor Red; exit 1 }

# Not: -cmatch kullanılıyor; Türkçe kültürde -match + [A-Z] 'I' harfini (CHAT_ID, IMAP_*) kaçırıyor.
function Read-DotEnv {
    $map = @{}
    if (Test-Path .env) {
        foreach ($line in Get-Content .env -Encoding UTF8) {
            if ($line -cmatch '^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$') { $map[$Matches[1]] = $Matches[2] }
        }
    }
    return $map
}

function Write-DotEnv($map) {
    $lines = @()
    if (Test-Path .env.example) {
        foreach ($line in Get-Content .env.example -Encoding UTF8) {
            if ($line -cmatch '^\s*#?\s*([A-Z0-9_]+)\s*=') {
                $k = $Matches[1]
                if ($map.ContainsKey($k) -and $map[$k]) { $lines += "$k=$($map[$k])"; continue }
            }
            $lines += $line
        }
    }
    foreach ($k in $map.Keys) {
        if ($map[$k] -and -not ($lines -cmatch "^$k=")) { $lines += "$k=$($map[$k])" }
    }
    [System.IO.File]::WriteAllLines((Join-Path $root ".env"), $lines, (New-Object System.Text.UTF8Encoding($false)))
}

# ------------------------------------------------------------------ 1. GitHub CLI
Step "GitHub CLI kontrol ediliyor"
function Refresh-Path { $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User") }
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) { Refresh-Path }
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) { Fail "winget yok. GitHub CLI'yi https://cli.github.com adresinden kurup betiği tekrar çalıştır." }
    winget install --id GitHub.cli -e --accept-source-agreements --accept-package-agreements
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
    if (-not (Get-Command gh -ErrorAction SilentlyContinue)) { Fail "gh kuruldu ama bulunamadı; PowerShell'i kapatıp açıp betiği tekrar çalıştır." }
}
if (-not (Quiet { gh auth status })) {
    Write-Host "GitHub'a giriş: tarayıcı açılacak, ekrandaki kodu gir (hesabın yoksa orada oluşturabilirsin)."
    gh auth login --hostname github.com --git-protocol https --web
    if ($LASTEXITCODE -ne 0) { Fail "GitHub girişi tamamlanmadı." }
}
$login = "$(gh api user --jq .login)".Trim()
if (-not $login) { Fail "GitHub kullanıcı adı alınamadı." }
Write-Host "GitHub kullanıcısı: $login"

# ------------------------------------------------------------------ 2. Telegram
Step "Telegram botu"
$envMap = Read-DotEnv
$token = $envMap["TELEGRAM_BOT_TOKEN"]
while (-not $token) {
    Write-Host "Telegram'da @BotFather'a /newbot yaz, bota bir ad ver; verdiği token'ı buraya yapıştır."
    $token = (Read-Host "Bot token").Trim()
}
try {
    $me = Invoke-RestMethod "https://api.telegram.org/bot$token/getMe" -ErrorAction Stop
} catch { Fail "Token geçersiz görünüyor: $($_.Exception.Message)" }
$botName = $me.result.username
Write-Host "Bot: @$botName"

$chatId = $envMap["TELEGRAM_CHAT_ID"]
$tries = 0
while (-not $chatId -and $tries -lt 5) {
    $tries++
    try { $upd = Invoke-RestMethod "https://api.telegram.org/bot$token/getUpdates" -ErrorAction Stop } catch { Fail "getUpdates başarısız: $($_.Exception.Message)" }
    $msg = $upd.result | Where-Object { $_.message -and $_.message.chat.type -eq "private" } | Select-Object -Last 1
    if ($msg) { $chatId = [string]$msg.message.chat.id; break }
    Write-Host "Telegram'da @$botName botunu aç ve /start yaz, sonra Enter'a bas."
    [void](Read-Host)
}
if (-not $chatId) { Fail "Bota gelen mesaj bulunamadı. /start yazdıktan sonra betiği tekrar çalıştır." }
Write-Host "Chat id: $chatId"
$envMap["TELEGRAM_BOT_TOKEN"] = $token
$envMap["TELEGRAM_CHAT_ID"] = $chatId
Write-DotEnv $envMap
try { Invoke-RestMethod "https://api.telegram.org/bot$token/sendMessage" -ErrorAction Stop -Method Post -ContentType "application/json; charset=utf-8" `
    -Body ([System.Text.Encoding]::UTF8.GetBytes((@{ chat_id = $chatId; text = "✅ m2kira bağlandı. Kurulum bitince ilk tarama sonuçları buraya gelecek." } | ConvertTo-Json))) | Out-Null } catch { Write-Host "Uyarı: test mesajı gönderilemedi: $($_.Exception.Message)" }

# ------------------------------------------------------------------ 3. Git deposu
Step "Git deposu hazırlanıyor"
if ($Private) {
    # 2000 dk/ay sınırına sığmak için 5 saatte bir tarama
    $wf = ".github/workflows/scan.yml"
    $text = [System.IO.File]::ReadAllText((Join-Path $root $wf))
    $text = $text.Replace('cron: "7 */2 * * *"', 'cron: "7 */5 * * *"')
    [System.IO.File]::WriteAllText((Join-Path $root $wf), $text, (New-Object System.Text.UTF8Encoding($false)))
}
if (-not (Test-Path .git)) { git init -b main | Out-Null }
if (-not (git config user.name)) { git config user.name $login }
if (-not (git config user.email)) {
    $uid = "$(gh api user --jq .id)".Trim()
    git config user.email "$uid+$login@users.noreply.github.com"
}
git add -A
$tracked = git ls-files
# .env tam adıyla (".env.example" serbest), data/ ise klasör olarak yasak
if ($tracked | Where-Object { $_ -ceq ".env" -or $_.StartsWith("data/") }) { Fail ".env ya da data/ depoya eklenmiş olmamalı (.gitignore kontrol et)." }
if (-not (Quiet { git diff --cached --quiet })) {
    git commit -q -m "m2kira: Ankara M2 eşyalı kiralık ilan takipçisi" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
}

# ------------------------------------------------------------------ 4. GitHub reposu
Step "GitHub reposu"
if (-not (Quiet { gh repo view "$login/$RepoName" })) {
    $vis = if ($Private) { "--private" } else { "--public" }
    gh repo create $RepoName $vis --source . --remote origin --push --description "Ankara M2 hattı eşyalı kiralık ilan takipçisi"
    if ($LASTEXITCODE -ne 0) { Fail "Repo oluşturulamadı." }
} else {
    if (-not (git remote 2>$null | Select-String -SimpleMatch "origin")) { git remote add origin "https://github.com/$login/$RepoName.git" }
    git push -u origin HEAD
    if ($LASTEXITCODE -ne 0) { Fail "git push başarısız." }
}

# ------------------------------------------------------------------ 5. Secrets
Step "Secrets kaydediliyor"
gh secret set TELEGRAM_BOT_TOKEN --repo "$login/$RepoName" --body $token
if ($LASTEXITCODE -ne 0) { Fail "Secret kaydedilemedi." }
gh secret set TELEGRAM_CHAT_ID --repo "$login/$RepoName" --body $chatId
foreach ($k in @("IMAP_HOST", "IMAP_USER", "IMAP_PASSWORD")) {
    if ($envMap[$k]) { gh secret set $k --repo "$login/$RepoName" --body $envMap[$k] }
}

# ------------------------------------------------------------------ 6. İlk çalıştırma
Step "İlk tarama başlatılıyor"
# Filtre sayfası: GitHub Pages (kaynak: Actions). Zaten açıksa hata verir, sorun değil.
[void](Quiet { gh api -X POST "repos/$login/$RepoName/pages" -f build_type=workflow })
[void](Quiet { gh workflow enable scan.yml --repo "$login/$RepoName" })
Start-Sleep -Seconds 3
gh workflow run scan.yml --repo "$login/$RepoName"
if ($LASTEXITCODE -ne 0) { Write-Host "İlk çalıştırma tetiklenemedi; Actions sekmesinden 'Run workflow' ile başlat." -ForegroundColor Yellow }
Write-Host ""
Write-Host "Tamam. İlk tarama ~15-25 dk sürer; sonuçlar Telegram'a tek liste halinde gelir." -ForegroundColor Green
Write-Host "Sonrası 30 dakikada bir ve her sabah 09:00'da özet. PC'nin açık olması gerekmez."
Write-Host "İzleme: https://github.com/$login/$RepoName/actions"
Write-Host "Filtre sayfası (ilk çalıştırmadan sonra): https://$($login.ToLower()).github.io/$RepoName/"
