# setup-windows-service.ps1
# Cài đặt AI Trading Office thành Windows Service (chạy 1 lần trên VPS)
# Chạy PowerShell as Administrator

$ErrorActionPreference = "Stop"

$REPO_DIR = "C:\ai-office"
$SERVICE_NAME = "AITradingOffice"
$PYTHON_EXE = (Get-Command python).Source  # đường dẫn python.exe
$SCRIPT_PATH = "$REPO_DIR\server.py"
$NSSM_URL = "https://nssm.cc/release/nssm-2.24.zip"
$NSSM_DIR = "$env:TEMP\nssm"

Write-Host "=== Cài đặt Windows Service cho AI Trading Office ===" -ForegroundColor Cyan

# 1. Kiểm tra Python
if (-not (Test-Path $PYTHON_EXE)) {
    Write-Error "Không tìm thấy python.exe trong PATH. Cài Python 3.11+ trước."
    exit 1
}
Write-Host "Python: $PYTHON_EXE" -ForegroundColor Green

# 2. Kiểm tra repo
if (-not (Test-Path "$REPO_DIR\server.py")) {
    Write-Error "Không tìm thấy $REPO_DIR\server.py. Clone repo trước."
    exit 1
}

# 3. Tải NSSM nếu chưa có
$nssmExe = "$NSSM_DIR\nssm.exe"
if (-not (Test-Path $nssmExe)) {
    Write-Host "Tải NSSM..." -ForegroundColor Yellow
    New-Item -ItemType Directory -Path $NSSM_DIR -Force | Out-Null
    Invoke-WebRequest -Uri $NSSM_URL -OutFile "$NSSM_DIR\nssm.zip"
    Expand-Archive -Path "$NSSM_DIR\nssm.zip" -DestinationPath $NSSM_DIR -Force
    # nssm.exe nằm trong nssm-2.24\win64\
    $extracted = Get-ChildItem "$NSSM_DIR\nssm-2.24\win64\nssm.exe" -ErrorAction SilentlyContinue
    if ($extracted) {
        Move-Item $extracted.FullName $nssmExe -Force
    } else {
        # fallback: tìm file nssm.exe bất kỳ
        $found = Get-ChildItem $NSSM_DIR -Recurse -Filter nssm.exe | Select-Object -First 1
        if ($found) { Move-Item $found.FullName $nssmExe -Force }
    }
    if (-not (Test-Path $nssmExe)) {
        Write-Error "Không tìm thấy nssm.exe sau khi giải nén."
        exit 1
    }
}
Write-Host "NSSM: $nssmExe" -ForegroundColor Green

# 4. Cài service
Write-Host "Cài đặt service $SERVICE_NAME..." -ForegroundColor Yellow
$existing = Get-Service -Name $SERVICE_NAME -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Service đã tồn tại -> xoá và reinstall..." -ForegroundColor Yellow
    Stop-Service -Name $SERVICE_NAME -Force -ErrorAction SilentlyContinue
    & $nssmExe remove $SERVICE_NAME -y 2>$null | Out-Null
    Start-Sleep 2
}
& $nssmExe install $SERVICE_NAME "$PYTHON_EXE" "$SCRIPT_PATH"
& $nssmExe set $SERVICE_NAME AppDirectory $REPO_DIR
& $nssmExe set $SERVICE_NAME AppStdout "$REPO_DIR\server.log"
& $nssmExe set $SERVICE_NAME AppStderr "$REPO_DIR\server_err.log"
& $nssmExe set $SERVICE_NAME AppEnvironmentExtra "PYTHONIOENCODING=utf-8`nOFFICE_PORT=18080"
& $nssmExe set $SERVICE_NAME Start SERVICE_AUTO_START
& $nssmExe set $SERVICE_NAME Description "AI Trading Office - Python Server (port 18080)"

# 5. Khởi động
Write-Host "Khởi động service..." -ForegroundColor Yellow
Start-Service $SERVICE_NAME -ErrorAction SilentlyContinue
Start-Sleep 3

$status = (Get-Service $SERVICE_NAME).Status
Write-Host "Service status: $status" -ForegroundColor Green

# 6. Health check
Start-Sleep 2
$healthUrl = "http://127.0.0.1:18080/api/health"
Write-Host "Health check: $healthUrl" -ForegroundColor Yellow
try {
    $resp = Invoke-WebRequest -Uri $healthUrl -TimeoutSec 10 -UseBasicParsing
    if ($resp.StatusCode -eq 200) { Write-Host "✅ Health check OK" -ForegroundColor Green }
    else { Write-Warning "Health check status: $($resp.StatusCode)" }
} catch { Write-Error "Health check thất bại: $_" }

Write-Host "=== Cài đặt service hoàn tất ===" -ForegroundColor Cyan
Write-Host "Quản lý service: Start-Service/Stop-Service/Restart-Service -Name $SERVICE_NAME"