# Triển khai server trên CentOS 7 + mở cổng qua FortiGate cho VPS Exness

Mô hình:

```
VPS Exness (MT5 + EA) ──Internet──▶ <IP_PUBLIC>:18080 (FortiGate) ──VIP──▶ <IP_LAN>:8080 (CentOS, server)
Bạn (Mac, 4G, bất kỳ đâu) ──────────▶ http://<IP_PUBLIC>:18080  (đăng nhập admin / mật khẩu)
```

| Thông số | Giá trị |
|---|---|
| IP LAN CentOS | `<IP_LAN>` |
| IP public (FortiGate) | `<IP_PUBLIC>` |
| Cổng public | `18080` (khác 8080 để bớt bị dò cổng) |
| Cổng server trong LAN | `8080` |
| Thư mục cài | `/home/ai-office` |

Có 2 cách chạy, chọn **một**:

- **Cách A – Docker (khuyến nghị)**: dùng Python 3.11 trong container, không phụ thuộc Python 3.6 cũ của CentOS 7, nâng cấp chỉ cần build lại.
- **Cách B – systemd + Python 3.6 của CentOS**: không cần cài Docker, nhẹ hơn khoảng 100 MB RAM.

---

## Bước 1. Chép code từ Mac sang CentOS bằng FileZilla

1. FileZilla > **File > Site Manager > New site**:
   - Protocol: **SFTP – SSH File Transfer Protocol**
   - Host: `<IP_LAN>` (đang ở LAN) · Port: `22`
   - Logon Type: Normal · User: `root` (hoặc user của bạn) · Password
2. Bấm **Connect**. Bên phải (Remote site) gõ `/home` vào ô đường dẫn, chuột phải > **Create directory** > `ai-office`, rồi mở `/home/ai-office`.
3. Bên trái (Local site) mở `/Users/tuannm/CODE/claude-ai-trading-office`. Chọn và kéo sang phải:
   - `server.py`, `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `.env.example`, `README.md`
   - thư mục `static/`, `skills/`, `mt5/`
   - **Không** kéo thư mục `data/` (chứa DB và key của máy Mac; server tự tạo lại).
   - File bắt đầu bằng dấu chấm bị ẩn trên Mac: trong FileZilla chọn **Server > Force showing hidden files**; bên Local thì chúng vẫn hiện.
4. Muốn giữ cấu hình đã nhập trên Mac (key Gemini/Groq/Telegram, ngưỡng, EA...): tạo thư mục `/home/ai-office/data` rồi kéo riêng file `data/config.json` vào đó.

Lần sau cập nhật code: kéo đè các file đã sửa, chọn **Overwrite**, rồi restart (bước 6).

---

## Bước 2. SSH vào CentOS, sửa repo yum (CentOS 7 đã hết hỗ trợ)

Trên Mac mở Terminal:

```bash
ssh root@<IP_LAN>
```

Nếu `yum` báo `Could not resolve host: mirrorlist.centos.org`, trỏ sang vault:

```bash
sed -i -e 's|^mirrorlist=|#mirrorlist=|g' -e 's|^#baseurl=http://mirror.centos.org|baseurl=http://vault.centos.org|g' /etc/yum.repos.d/CentOS-*.repo && yum clean all
```

```bash
yum install -y ca-certificates && update-ca-trust
```

---

## Bước 3. Đặt mật khẩu dashboard

Dashboard có khoá đăng nhập (user `admin`) khi đặt biến `OFFICE_ADMIN_PASSWORD`. **Bắt buộc** đặt trước khi mở cổng ra Internet. EA trên VPS không dùng mật khẩu này mà dùng Bridge Token (bước 7).

```bash
cd /home/ai-office && cp .env.example .env && chmod 600 .env && vi .env
```

Sửa dòng `OFFICE_ADMIN_PASSWORD=` thành mật khẩu mạnh, ví dụ tạo bằng `openssl rand -base64 18`.

Cũng trong `.env`, đặt tên container theo ý bạn (chỉ chữ thường, số, gạch ngang):

| Biến | Tác dụng |
|---|---|
| `APP_NAME` | Tên container (`docker ps` sẽ hiện tên này), được dùng chữ hoa |
| `COMPOSE_PROJECT_NAME` | Tên project, tên image sẽ là `<project>-app`. **Bắt buộc chữ thường** |
| `APP_PORT` | Cổng **phía host** map vào cổng 8080 trong container (`${APP_PORT}:8080`). `.env.example` để `18080`; theo sơ đồ trên (firewalld + FortiGate map tới 8080) thì đặt `APP_PORT=8080`, đổi thì sửa luôn firewalld và FortiGate cho khớp. **Không** đặt `OFFICE_PORT` trong `.env` (server trong container sẽ nghe sai cổng) |

---

## Bước 4A. Chạy bằng Docker (khuyến nghị)

Cài Docker CE (bản cuối cùng còn hỗ trợ CentOS 7):

```bash
yum install -y yum-utils && yum-config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo && yum install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
```

```bash
systemctl enable --now docker && docker --version && docker compose version
```

Build và chạy:

```bash
cd /home/ai-office && mkdir -p data && docker compose up -d --build
```

Kiểm tra:

```bash
docker compose ps && curl -s http://127.0.0.1:8080/api/health
```

Lệnh hay dùng:

| Việc | Lệnh |
|---|---|
| Xem log realtime | `docker compose logs -f` (hoặc `docker logs -f <APP_NAME>`) |
| Restart | `docker compose restart` |
| Cập nhật sau khi chép `server.py` / `static/` mới | `docker compose restart` (code được gắn trực tiếp, không cần build lại) |
| Dừng | `docker compose down` |

Nếu `--build` báo lỗi `failed to fetch anonymous token ... EOF`: FortiGate đang chặn Docker Hub (thường do policy ra Internet bật proxy inspection / webfilter). Image đã build trước đó vẫn dùng được, chạy `docker compose up -d` không có `--build`.

Container tự chạy lại khi CentOS khởi động (`restart: unless-stopped`). Dữ liệu `data/` và `skills/` nằm ngoài container nên rebuild không mất kèo và bài học.

Nếu log báo `CERTIFICATE_VERIFY_FAILED`, bỏ dấu `#` trước dòng `OFFICE_INSECURE_SSL=1` trong `docker-compose.yml` rồi `docker compose up -d`.

## Bước 4B. Chạy bằng systemd (nếu không dùng Docker)

```bash
yum install -y python3 && python3 --version
```

```bash
cat > /etc/systemd/system/ai-office.service <<'EOF'
[Unit]
Description=AI Trading Office 2D
After=network-online.target
Wants=network-online.target

[Service]
WorkingDirectory=/home/ai-office
EnvironmentFile=/home/ai-office/.env
Environment=TZ=Asia/Ho_Chi_Minh
Environment=OFFICE_PORT=8080
Environment=OFFICE_STEP_DELAY=2.5
#Environment=OFFICE_INSECURE_SSL=1
ExecStart=/usr/bin/python3 /home/ai-office/server.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
```

```bash
systemctl daemon-reload && systemctl enable --now ai-office && systemctl status ai-office --no-pager
```

Log: `journalctl -u ai-office -f` · Restart: `systemctl restart ai-office`.

Nếu status báo `Permission denied` dù file đọc được, kiểm tra SELinux bằng `getenforce`; cách nhanh là `setenforce 0` và đặt `SELINUX=permissive` trong `/etc/selinux/config`.

---

## Bước 5. Mở cổng 8080 trên firewalld của CentOS

```bash
firewall-cmd --permanent --add-port=8080/tcp && firewall-cmd --reload && firewall-cmd --list-ports
```

Trên Mac mở `http://<IP_LAN>:8080`, trình duyệt hỏi user/mật khẩu: nhập `admin` và mật khẩu ở bước 3. Thấy văn phòng là xong phần server.

---

## Bước 6. FortiGate: Virtual IP + Firewall Policy

### 6.1 Virtual IP

GUI: **Policy & Objects > Virtual IPs > Create New > Virtual IP**

| Trường | Giá trị |
|---|---|
| Name | `VIP-AI-Office` |
| Interface | cổng WAN đang mang IP <IP_PUBLIC> (ví dụ `wan1`) |
| Type | Static NAT |
| External IP address/range | `<IP_PUBLIC>` |
| Map to IPv4 address/range | `<IP_LAN>` |
| Port Forwarding | Bật · Protocol **TCP** |
| External service port | `18080` |
| Map to IPv4 port | `8080` |

CLI tương đương:

```
config firewall vip
    edit "VIP-AI-Office"
        set extintf "wan1"
        set extip <IP_PUBLIC>
        set mappedip "<IP_LAN>"
        set portforward enable
        set protocol tcp
        set extport 18080
        set mappedport 8080
    next
end
```

### 6.2 Firewall Policy

**Policy & Objects > Firewall Policy > Create New**

| Trường | Giá trị |
|---|---|
| Name | `WAN-to-AI-Office` |
| Incoming Interface | `wan1` |
| Outgoing Interface | cổng LAN chứa <IP_LAN> (ví dụ `internal`) |
| Source | `all` (hoặc chỉ IP VPS, xem 6.3) |
| Destination | `VIP-AI-Office` |
| Schedule | always |
| Service | `ALL` (VIP đã giới hạn cổng 18080) |
| Action | ACCEPT |
| NAT | **Tắt** |
| Log Allowed Traffic | All Sessions |

```
config firewall policy
    edit 0
        set name "WAN-to-AI-Office"
        set srcintf "wan1"
        set dstintf "internal"
        set srcaddr "all"
        set dstaddr "VIP-AI-Office"
        set action accept
        set schedule "always"
        set service "ALL"
        set nat disable
        set logtraffic all
    next
end
```

Kéo policy lên trên các policy deny chung nếu có.

### 6.3 Có cần IP của VPS Exness không?

**Không bắt buộc**, vì dashboard đã có mật khẩu và EA dùng Bridge Token. Để Source `all` thì bạn xem được dashboard từ bất kỳ đâu.

**Nên thêm nếu chỉ cần VPS truy cập** (mạnh hơn, chặn cả việc bị dò mật khẩu). Lấy IP VPS: trong VPS mở PowerShell chạy `curl.exe ifconfig.me`. Tạo address `VPS-Exness` = `IP_VPS/32` và một address cho IP văn phòng/nhà của bạn, rồi đặt Source của policy là hai address đó thay cho `all`.

### 6.4 Kiểm tra từ ngoài Internet

Trên VPS Exness (PowerShell):

```powershell
curl.exe -s http://<IP_PUBLIC>:18080/api/health
```

Trả `{"ok": true, ...}` là thông. Nếu không:

- FortiGate **Log & Report > Forward Traffic**, lọc Destination Port `18080`, xem bị deny ở policy nào.
- Trên CentOS: `curl -s http://127.0.0.1:8080/api/health` (server sống?) và `firewall-cmd --list-ports` (8080 mở?).
- Thử từ 4G điện thoại: mở `http://<IP_PUBLIC>:18080`, phải hiện hộp đăng nhập.
- Mở từ máy trong LAN bằng IP public có thể không vào được (hairpin NAT); trong LAN cứ dùng `http://<IP_LAN>:8080`.

---

## Bước 7. Bridge Token và EA trên VPS

1. Dashboard > 🔑 Cài Đặt > mục "6. Cầu nối MT5 realtime" > nhập **Bridge Token** (chuỗi ngẫu nhiên, ví dụ `openssl rand -hex 16`) > Lưu.
2. MT5 trên VPS: **Tools > Options > Expert Advisors** > tick **Allow WebRequest for listed URL** > Add `http://<IP_PUBLIC>:18080` (không có `/` cuối).
3. Kéo EA `AITradingOffice` vào chart, input:
   - `ServerUrl` = `http://<IP_PUBLIC>:18080`
   - `BridgeToken` = token ở bước 7.1
4. Tab Experts hiện `Cấu hình từ server: gold=XAUUSDm ...`. Dashboard hiện **MT5 ✓** và **EA ✓ hh:mm**, thẻ vàng hiện **🟢 MT5 realtime** kèm Bid/Ask.

Các endpoint EA được phép đi bằng token thay mật khẩu: `/api/push_price`, `/api/ea/config`, `/api/signals`, `/api/execution`. Mọi trang và API khác cần mật khẩu admin.

---

## Checklist

- [ ] FileZilla chép code vào `/home/ai-office` (không chép `data/`, có thể chép riêng `data/config.json`)
- [ ] `.env` có `OFFICE_ADMIN_PASSWORD`
- [ ] Docker: `docker compose up -d --build` · hoặc systemd: `systemctl enable --now ai-office`
- [ ] `firewall-cmd --add-port=8080/tcp`
- [ ] LAN: `http://<IP_LAN>:8080` hỏi mật khẩu và vào được
- [ ] FortiGate: VIP `<IP_PUBLIC>:18080 → <IP_LAN>:8080`, policy NAT tắt
- [ ] VPS: `curl.exe http://<IP_PUBLIC>:18080/api/health` trả ok
- [ ] Đặt Bridge Token, MT5 Allow WebRequest, EA điền ServerUrl + BridgeToken
