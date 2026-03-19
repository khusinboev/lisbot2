## Lisbot (aiogram + selenium)

Telegram bot: litsenziyalar bazasini yig‘ish, filtrlash va foydalanuvchilarga yuborish.

### Talablar
- **BOT token**: @BotFather’dan
- **ALLOWED_USERS**: ruxsat berilgan Telegram user ID’lar (vergul bilan)

`.env` namunasi `/.env.example` da.

---

## Docker bilan ishga tushirish (tavsiya)

### 1) Serverga tayyorlash (Ubuntu)

- Docker o‘rnatish:

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
$(. /etc/os-release && echo ${UBUNTU_CODENAME}) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
```

### 2) Loyihani yuklash

```bash
sudo mkdir -p /opt/lisbot
sudo chown -R $USER:$USER /opt/lisbot
cd /opt/lisbot
git clone <SIZNING_REPO_URL> .
```

### 3) `.env` sozlash

```bash
cp .env.example .env
nano .env
```

Minimal kerakli qiymatlar:
- `BOT_TOKEN=...`
- `ALLOWED_USERS=123,456`

### 4) Build va run

```bash
docker compose up -d --build
docker compose logs -f
```

To‘xtatish:

```bash
docker compose down
```

Restart:

```bash
docker compose restart
```

---

## Muhim eslatmalar (Docker/Selenium)

- Container ichida Chrome **headless** rejimda ishlaydi (`CHROME_HEADLESS=1`).
- `undetected-chromedriver` odatda Chrome major version’ni o‘zi topadi.
  Agar serverda moslash muammo bersa, `docker-compose.yml` ichida `CHROME_VERSION_MAIN` ni yoqib qo‘ying.

---

## Ubuntu'da qo'lda test (Docker'siz)

Ba'zan serverda browser ochiladi, lekin SPA jadval qatorlari kech chiqadi yoki umuman ko'rinmaydi.
API ham bot detected qo'linishi mumkin. Shu uchun test scriptda to'rt rejim bor:

- `TEST_MODE=api` — **eng barqaror**: curl_cffi + requests + playwright (API va browser hybrid)
- `TEST_MODE=api-only` — faqat API (curl_cffi + requests + playwright), browser yo'qotilgan
- `TEST_MODE=browser` — faqat Selenium yo'li
- `TEST_MODE=hybrid` — avval API, kerak bo'lsa browser (legacy fallback)

### Bot detection bypass strategiyalari:

Yangi `fetch_robust.py` moduli uchta yo'ldan urinadi (ketma-ket):
1. **curl_cffi** — 3 ta berbeda impersonate profili + header rotation (chrome124, chrome120, safari)
2. **requests** — standart requests bilan sophisticated header spoofing
3. **Playwright** — headless chromium (Selenium'dan mustaqil)

Ikhtar API blok qilinsa, avtomatik keyingi yo'lga o'tadi.

### 1) Kerakli paketlar

```bash
sudo apt-get update
sudo apt-get install -y git python3 python3-venv python3-pip wget unzip ca-certificates
```

### 2) Chrome o'rnatish

```bash
wget -q https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
sudo apt-get install -y ./google-chrome-stable_current_amd64.deb
rm -f google-chrome-stable_current_amd64.deb
```

### 3) Python environment

```bash
python3 -m venv venv
source venv/bin/activate
pip install -U pip
pip install -r requirements.txt
```

### 4) Env sozlash

```bash
cp .env.example .env
```

Qo'lda test uchun tavsiya qiymatlar:

```env
SCRAPER_BROWSER=chrome
CHROME_HEADLESS=true
TEST_MODE=hybrid
SKIP_WARMUP=true
WARMUP_MODE=adaptive
APP_BOOT_TIMEOUT_SECONDS=50
ROW_WAIT_TIMEOUT_SECONDS=90
```

### 5) Test run

```bash
# API yo'li orqali (barqaror)
python test_first_item.py

# Yoki aniq rejim bilan
TEST_MODE=api-only python test_first_item.py
TEST_MODE=api python test_first_item.py
TEST_MODE=browser python test_first_item.py
TEST_MODE=hybrid python test_first_item.py
```

Mahalliy vs datacenter IP:
- Datacenter IP bot detection kosha, `TEST_MODE=api` o'ng keladimi.
- Agar `api-only` muvaffaqiyatsiz bo'lsa, hybrid yoki browser sinovdan o'tkazing.

### 6) Browser oynasini ko'rib test qilish (xvfb)

```bash
sudo apt-get install -y xvfb
CHROME_HEADLESS=false TEST_MODE=browser xvfb-run -a python test_first_item.py
```

### 7) Serverda barqarorlik bo'yicha tavsiyalar

- Datacenter IP ba'zan JS/Selenium oqimini sekinlatadi: `TEST_MODE=api` yoki `TEST_MODE=api-only` ishlating.
- `api` yo'li muvaffaqiyatsiz bo'lsa, `api-only` rejimida `SKIP_WARMUP=false` + `WARMUP_MODE=always` bilan sinab ko'ring.
- Browser yo'lida osilib qolsa `_debug_artifacts/` dagi screenshot/html ni tahlil qiling.
- Chrome/driver moslashmasa `CHROME_VERSION_MAIN` ni qo'lda bering.
- Ko'p parallel run qilmang; bitta run tugaguncha keyingisini boshlamang.

---

## Turli API/Browser yo'llarini tezkor test qilish

Isimsiz bash script:

```bash
#!/bin/bash
set -e

source venv/bin/activate

echo "=== TEST MODE: API-ONLY ==="
timeout 60 python test_first_item.py || echo "API-ONLY muvaffaqiyatsiz"

echo -e "\n=== TEST MODE: API ==="
timeout 60 env TEST_MODE=api python test_first_item.py || echo "API muvaffaqiyatsiz"

echo -e "\n=== TEST MODE: HYBRID ==="
timeout 60 env TEST_MODE=hybrid python test_first_item.py || echo "HYBRID muvaffaqiyatsiz"

echo -e "\n=== Done ==="
```

