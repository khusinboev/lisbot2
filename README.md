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

