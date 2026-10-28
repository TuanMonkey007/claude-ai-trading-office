# setup-windows-service.ps1
# Cài đặt AI Trading Office thành Windows Service (chạy 1 lần trên VPS)
# Chạy PowerShell as Administrator:
#   PowerShell -ExecutionPolicy Bypass -File setup-windows-service.ps1 [-Port 18080]
# Cần $REPO_DIR\.env có OFFICE_ADMIN_PASSWORD (đã đổi khỏi giá trị mẫu).
# Chạy lại script này mỗi khi đổi mật khẩu trong .env (NSSM giữ bản sao biến môi trường).

param(
    [int]$Port = 18080   # OFFICE_PORT của service native (không đặt trong .env dùng chung)
)

$ErrorActionPreference = "Stop"

$REPO_DIR = "C:\ai-office"
$SERVICE_NAME = "AITradingOffice"
$SCRIPT_PATH = "$REPO_DIR\server.py"
$ENV_PATH = "$REPO_DIR\.env"
$NSSM_URL = "https://nssm.cc/release/nssm-2.24.zip"
# SHA256 của nssm-2.24.zip (bản phát hành 2.24, 2014-08-31). nssm.cc không công bố checksum;
# kiểm lại một lần bằng: Get-FileHash nssm-2.24.zip -Algorithm SHA256
$NSSM_SHA256 = "727d1e42275c605e0f04aba98095c38a8e1e46def453cdffce42869428aa6743"
$NSSM_DIR = "$env:TEMP\nssm"

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

# Chạy nssm.exe và dừng ngay nếu lỗi.
function Invoke-Nssm {
    $ErrorActionPreference = "Continue"
    & $nssmExe @args
    if ($LASTEXITCODE -ne 0) { throw "nssm $($args[0]) $($args[1]) $($args[2]) thất bại (exit $LASTEXITCODE)" }
}

Write-Host "=== Cài đặt Windows Service cho AI Trading Office ===" -ForegroundColor Cyan

# 1. Kiểm tra Python
$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCmd -or -not (Test-Path $pythonCmd.Source) -or $pythonCmd.Source -like "*\WindowsApps\*") {
    # WindowsApps\python.exe là lối tắt mở Microsoft Store, không phải Python thật.
    Write-Error "Không tìm thấy python.exe thật trong PATH. Cài Python 3.11+ từ python.org (tick 'Add python.exe to PATH'), mở lại PowerShell rồi chạy lại."
    exit 1
}
$PYTHON_EXE = $pythonCmd.Source
Write-Host "Python: $PYTHON_EXE" -ForegroundColor Green

# 2. Kiểm tra repo
if (-not (Test-Path $SCRIPT_PATH)) {
    Write-Error "Không tìm thấy $SCRIPT_PATH. Clone repo trước."
    exit 1
}

# 3. Mật khẩu dashboard từ .env (server.py không tự đọc .env → phải đưa vào môi trường service)
$dotenv = Read-DotEnv $ENV_PATH
$adminUser = if ($dotenv["OFFICE_ADMIN_USER"]) { $dotenv["OFFICE_ADMIN_USER"] } else { "admin" }
$adminPass = $dotenv["OFFICE_ADMIN_PASSWORD"]
if (-not $adminPass -or $adminPass -eq "doi-mat-khau-nay") {
    Write-Error "Từ chối cài: $ENV_PATH chưa có OFFICE_ADMIN_PASSWORD (hoặc vẫn là giá trị mẫu). Đặt mật khẩu mạnh rồi chạy lại."
    exit 1
}
if ($adminPass -match "[`r`n`"]") {
    Write-Error "OFFICE_ADMIN_PASSWORD không được chứa xuống dòng hoặc dấu nháy kép."
    exit 1
}

# 4. Tải NSSM nếu chưa có (kiểm tra SHA256 trước khi giải nén)
$nssmExe = "$NSSM_DIR\nssm.exe"
if (-not (Test-Path $nssmExe)) {
    Write-Host "Tải NSSM..." -ForegroundColor Yellow
    New-Item -ItemType Directory -Path $NSSM_DIR -Force | Out-Null
    $zip = "$NSSM_DIR\nssm.zip"
    Invoke-WebRequest -Uri $NSSM_URL -OutFile $zip -UseBasicParsing
    $hash = (Get-FileHash -Path $zip -Algorithm SHA256).Hash
    if ($hash -ne $NSSM_SHA256.ToUpperInvariant()) {
        Remove-Item $zip -Force
        Write-Error "SHA256 của nssm.zip không khớp (được $hash, cần $NSSM_SHA256). Đã xoá file, dừng cài."
        exit 1
    }
    Expand-Archive -Path $zip -DestinationPath $NSSM_DIR -Force
    # nssm.exe nằm trong nssm-2.24\win64\
    $extracted = Get-Item "$NSSM_DIR\nssm-2.24\win64\nssm.exe" -ErrorAction SilentlyContinue
    if ($extracted) {
        Move-Item $extracted.FullName $nssmExe -Force
    }
    if (-not (Test-Path $nssmExe)) {
        Write-Error "Không tìm thấy nssm-2.24\win64\nssm.exe sau khi giải nén."
        exit 1
    }
}
Write-Host "NSSM: $nssmExe" -ForegroundColor Green

# 5. Cài service
Write-Host "Cài đặt service $SERVICE_NAME..." -ForegroundColor Yellow
$existing = Get-Service -Name $SERVICE_NAME -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Service đã tồn tại -> xoá và reinstall..." -ForegroundColor Yellow
    if ($existing.Status -ne "Stopped") { Stop-Service -Name $SERVICE_NAME -Force }
    Invoke-Nssm remove $SERVICE_NAME confirm
    Start-Sleep 2
}
Invoke-Nssm install $SERVICE_NAME "$PYTHON_EXE" "$SCRIPT_PATH"
Invoke-Nssm set $SERVICE_NAME AppDirectory $REPO_DIR
Invoke-Nssm set $SERVICE_NAME AppStdout "$REPO_DIR\server.log"
Invoke-Nssm set $SERVICE_NAME AppStderr "$REPO_DIR\server_err.log"
# Mỗi biến là một tham số riêng → NSSM lưu thành REG_MULTI_SZ (mật khẩu không hiện ra màn hình).
Invoke-Nssm set $SERVICE_NAME AppEnvironmentExtra "PYTHONIOENCODING=utf-8" "OFFICE_PORT=$Port" "OFFICE_ADMIN_USER=$adminUser" "OFFICE_ADMIN_PASSWORD=$adminPass"
Invoke-Nssm set $SERVICE_NAME Start SERVICE_AUTO_START
Invoke-Nssm set $SERVICE_NAME Description "AI Trading Office - Python Server (port $Port)"

# 6. Khởi động (lỗi thì dừng script, xem server_err.log)
Write-Host "Khởi động service..." -ForegroundColor Yellow
Start-Service $SERVICE_NAME
Start-Sleep 3

$status = (Get-Service $SERVICE_NAME).Status
Write-Host "Service status: $status" -ForegroundColor Green

# 7. Health check
Start-Sleep 2
$healthUrl = "http://127.0.0.1:$Port/api/health"
Write-Host "Health check: $healthUrl" -ForegroundColor Yellow
try {
    $resp = Invoke-WebRequest -Uri $healthUrl -TimeoutSec 10 -UseBasicParsing
    if ($resp.StatusCode -eq 200) { Write-Host "✅ Health check OK" -ForegroundColor Green }
    else { Write-Warning "Health check status: $($resp.StatusCode)" }
} catch { Write-Error "Health check thất bại: $_ (xem $REPO_DIR\server_err.log)" }

Write-Host "=== Cài đặt service hoàn tất ===" -ForegroundColor Cyan
Write-Host "Quản lý service: Start-Service/Stop-Service/Restart-Service -Name $SERVICE_NAME"
