# deploy-windows.ps1
# Pull code from GitHub và restart Python server trên Windows VPS
# Chạy: PowerShell -ExecutionPolicy Bypass -File deploy-windows.ps1

$ErrorActionPreference = "Stop"

$REPO_DIR = "C:\ai-office"
$REPO_URL = "https://github.com/<YOUR_GITHUB_USERNAME>/claude-ai-trading-office.git"
$BRANCH = "main"
$PYTHON_EXE = "python"
$SERVICE_NAME = "AITradingOffice"

Write-Host "=== Deploy AI Trading Office on Windows VPS ===" -ForegroundColor Cyan

# 1. Clone hoặc pull repo
if (Test-Path "$REPO_DIR\.git") {
    Write-Host "Repo tồn tại -> git pull..." -ForegroundColor Yellow
    Set-Location $REPO_DIR
    git fetch origin
    git reset --hard origin/$BRANCH
    git clean -fd
} else {
    Write-Host "Chưa có repo -> git clone..." -ForegroundColor Yellow
    $parent = Split-Path $REPO_DIR -Parent
    if (-not (Test-Path $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    git clone -b $BRANCH $REPO_URL $REPO_DIR
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
    Write-Warning "CHÚ Ý: Cần sửa $envPath đặt OFFICE_ADMIN_PASSWORD và APP_PORT=18080"
}

# 3. Cài Python packages (nếu cần) - project này 100% stdlib nên bỏ qua
# python -m pip install --upgrade pip  # không cần

# 4. Restart service (NSSM) hoặc kill/restart process
$service = Get-Service -Name $SERVICE_NAME -ErrorAction SilentlyContinue
if ($service) {
    Write-Host "Restart Windows Service: $SERVICE_NAME" -ForegroundColor Yellow
    Restart-Service -Name $SERVICE_NAME -Force
    Start-Sleep 3
    $status = (Get-Service -Name $SERVICE_NAME).Status
    Write-Host "Service status: $status" -ForegroundColor Green
} else {
    Write-Host "Service $SERVICE_NAME chưa cài, chạy trực tiếp python server.py..." -ForegroundColor Yellow
    # Kill process cũ nếu có
    $old = Get-Process -Name "python" -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "*server.py*" }
    if ($old) { Stop-Process -Id $old.Id -Force }
    # Chạy background
    $cmd = "$PYTHON_EXE server.py"
    Start-Process $PYTHON_EXE -ArgumentList "server.py" -WorkingDirectory $REPO_DIR -WindowStyle Hidden
    Start-Sleep 3
}

# 5. Health check
Start-Sleep 2
$healthUrl = "http://127.0.0.1:18080/api/health"
try {
    $resp = Invoke-WebRequest -Uri $healthUrl -TimeoutSec 10 -UseBasicParsing
    if ($resp.StatusCode -eq 200) {
        Write-Host "✅ Health check OK: $healthUrl" -ForegroundColor Green
    } else {
        Write-Warning "Health check status: $($resp.StatusCode)"
    }
} catch {
    Write-Error "Health check thất bại: $_"
}

Write-Host "=== Deploy hoàn tất ===" -ForegroundColor Cyan