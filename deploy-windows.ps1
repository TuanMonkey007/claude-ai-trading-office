# deploy-windows.ps1
# Pull code from GitHub và restart Python server trên Windows VPS
# Chạy: PowerShell -ExecutionPolicy Bypass -File deploy-windows.ps1 [-Port 18080] [-SyncSkills]
#   -Port       : cổng health check khi KHÔNG đọc được OFFICE_PORT từ service NSSM
#   -SyncSkills : lấy skills/ từ GitHub (GHI ĐÈ nhật ký tự học Hermes trên VPS)

param(
    [int]$Port = 18080,
    [switch]$SyncSkills
)

$ErrorActionPreference = "Stop"

$REPO_DIR = "C:\ai-office"
$REPO_URL = "https://github.com/TuanMonkey007/claude-ai-trading-office.git"
$BRANCH = "main"
$PYTHON_EXE = "python"
$SERVICE_NAME = "AITradingOffice"

# Chạy git và dừng ngay nếu lỗi. Không để stderr của git (progress) bị coi là lỗi PowerShell.
function Invoke-Git {
    $ErrorActionPreference = "Continue"
    & git @args
    if ($LASTEXITCODE -ne 0) { throw "git $($args -join ' ') thất bại (exit $LASTEXITCODE)" }
}

# Đọc file .env (KEY=VALUE) thành hashtable, bỏ dòng trống / chú thích / dấu nháy bao ngoài.
function Read-DotEnv([string]$Path) {
    $vars = @{}
    if (-not (Test-Path $Path)) { return $vars }
    foreach ($line in Get-Content -Path $Path -Encoding UTF8) {
        $t = $line.Trim()
        if (-not $t -or $t.StartsWith("#") -or -not $t.Contains("=")) { continue }
        $k, $v = $t.Split("=", 2)
        $vars[$k.Trim()] = $v.Trim().Trim('"').Trim("'")
    }
    return $vars
}

Write-Host "=== Deploy AI Trading Office on Windows VPS ===" -ForegroundColor Cyan

# 1. Clone hoặc pull repo (giữ nguyên skills/, data/, .env trên VPS)
if (Test-Path "$REPO_DIR\.git") {
    Write-Host "Repo tồn tại -> git pull..." -ForegroundColor Yellow
    Set-Location $REPO_DIR
    Invoke-Git fetch origin

    # Sao lưu skills/ (nhật ký tự học Hermes) trước khi reset, khôi phục sau đó.
    $skillsBackup = $null
    if (-not $SyncSkills -and (Test-Path "$REPO_DIR\skills")) {
        $skillsBackup = Join-Path $env:TEMP ("aito-skills-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
        Copy-Item "$REPO_DIR\skills" $skillsBackup -Recurse -Force
        Write-Host "Đã sao lưu skills/ -> $skillsBackup" -ForegroundColor Yellow
    }

    Invoke-Git reset --hard "origin/$BRANCH"
    Invoke-Git clean -fd -e skills/

    if ($skillsBackup) {
        Copy-Item "$skillsBackup\*" "$REPO_DIR\skills" -Recurse -Force
        Remove-Item $skillsBackup -Recurse -Force
        Write-Host "Đã khôi phục skills/ của VPS (dùng -SyncSkills để lấy bản GitHub)." -ForegroundColor Yellow
    }
} else {
    Write-Host "Chưa có repo -> git clone..." -ForegroundColor Yellow
    $parent = Split-Path $REPO_DIR -Parent
    if (-not (Test-Path $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    Invoke-Git clone -b $BRANCH $REPO_URL $REPO_DIR
    Set-Location $REPO_DIR
}

# 2. Tạo thư mục data/skills nếu chưa có
New-Item -ItemType Directory -Path "$REPO_DIR\data" -Force | Out-Null
New-Item -ItemType Directory -Path "$REPO_DIR\skills" -Force | Out-Null

# 3. Tạo .env nếu chưa có
$envPath = "$REPO_DIR\.env"
if (-not (Test-Path $envPath)) {
    Write-Host "Tạo .env từ template..." -ForegroundColor Yellow
    Copy-Item "$REPO_DIR\.env.example" $envPath
    Write-Warning "CHÚ Ý: Cần sửa $envPath đặt OFFICE_ADMIN_PASSWORD rồi chạy lại setup-windows-service.ps1 (cổng native đặt bằng OFFICE_PORT trong service NSSM)."
}

# 3b. Cài Python packages (nếu cần) - project này 100% stdlib nên bỏ qua
# python -m pip install --upgrade pip  # không cần

# 4. Restart service (NSSM) hoặc kill/restart process
$service = Get-Service -Name $SERVICE_NAME -ErrorAction SilentlyContinue
if ($service) {
    # Lấy OFFICE_PORT từ AppEnvironmentExtra của service để health check đúng cổng.
    $svcParams = "HKLM:\SYSTEM\CurrentControlSet\Services\$SERVICE_NAME\Parameters"
    $extra = (Get-ItemProperty -Path $svcParams -Name AppEnvironmentExtra -ErrorAction SilentlyContinue).AppEnvironmentExtra
    $portLine = @($extra) | Where-Object { $_ -match '^OFFICE_PORT=\d+$' } | Select-Object -First 1
    if ($portLine) { $Port = [int]($portLine.Split("=", 2)[1]) }

    Write-Host "Restart Windows Service: $SERVICE_NAME" -ForegroundColor Yellow
    Restart-Service -Name $SERVICE_NAME -Force
    Start-Sleep 3
    $status = (Get-Service -Name $SERVICE_NAME).Status
    Write-Host "Service status: $status" -ForegroundColor Green
} else {
    Write-Host "Service $SERVICE_NAME chưa cài, chạy trực tiếp python server.py..." -ForegroundColor Yellow
    # Kill process cũ: Path chỉ là python.exe, phải lọc theo CommandLine mới thấy server.py
    $old = Get-CimInstance Win32_Process -Filter "Name LIKE 'python%.exe'" |
        Where-Object { $_.CommandLine -match 'server\.py' }
    foreach ($p in $old) {
        Write-Host "Dừng python cũ PID $($p.ProcessId): $($p.CommandLine)" -ForegroundColor Yellow
        Stop-Process -Id $p.ProcessId -Force
    }
    # server.py không tự đọc .env: nạp vào môi trường tiến trình con (mật khẩu dashboard, ...)
    $dotenv = Read-DotEnv $envPath
    foreach ($k in @("OFFICE_ADMIN_USER", "OFFICE_ADMIN_PASSWORD")) {
        if ($dotenv.ContainsKey($k)) { Set-Item -Path "Env:$k" -Value $dotenv[$k] }
    }
    if (-not $env:OFFICE_ADMIN_PASSWORD) { Write-Warning "Chưa có OFFICE_ADMIN_PASSWORD: dashboard KHÔNG có mật khẩu." }
    $env:OFFICE_PORT = "$Port"
    $env:PYTHONIOENCODING = "utf-8"
    # Chạy background
    Start-Process $PYTHON_EXE -ArgumentList "server.py" -WorkingDirectory $REPO_DIR -WindowStyle Hidden
    Start-Sleep 3
}

# 5. Health check
Start-Sleep 2
$healthUrl = "http://127.0.0.1:$Port/api/health"
try {
    $resp = Invoke-WebRequest -Uri $healthUrl -TimeoutSec 10 -UseBasicParsing
    if ($resp.StatusCode -eq 200) {
        Write-Host "✅ Health check OK: $healthUrl" -ForegroundColor Green
    } else {
        Write-Warning "Health check status: $($resp.StatusCode)"
    }
} catch {
    Write-Error "Health check thất bại ($healthUrl): $_"
}

Write-Host "=== Deploy hoàn tất ===" -ForegroundColor Cyan
