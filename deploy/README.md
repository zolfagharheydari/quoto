# اجرای دائمی روی سرور لینوکس

این مسیر ربات را ۲۴ ساعته بالا نگه می‌دارد: بعد از ری‌استارت سرور خودش روشن می‌شود و
اگر کرش کند دوباره بالا می‌آید.

فرض: یک سرور اوبونتو (۲۲.۰۴ یا بالاتر) و دسترسی SSH.

## ۱. آماده‌سازی سرور

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git ffmpeg fonts-dejavu-core
```

`ffmpeg` برای گیف و استیکر ویدیویی لازم است. `fonts-dejavu-core` فونت سریفِ متن‌های
انگلیسی را می‌دهد؛ فونت فارسی جداگانه دانلود می‌شود.

## ۲. کاربر و پوشه

ربات با کاربر جدا اجرا می‌شود، نه با root:

```bash
sudo useradd --system --create-home --home-dir /opt/quoto quoto
```

## ۳. کد و وابستگی‌ها

```bash
sudo -u quoto -H bash
cd /opt/quoto
git clone <آدرس مخزن> .        # یا فایل‌ها را با scp بالا بفرست
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python download_fonts.py
.venv/bin/python download_emoji.py
exit
```

## ۴. تنظیمات

```bash
sudo -u quoto cp /opt/quoto/.env.example /opt/quoto/.env
sudo -u quoto nano /opt/quoto/.env
```

`BOT_TOKEN` را بگذار. اگر سرورت جایی است که تلگرام مستقیم باز است، `PROXY` را خالی
بگذار. دسترسی فایل را هم محدود کن تا توکن خواندنی عمومی نباشد:

```bash
sudo chmod 600 /opt/quoto/.env
```

## ۵. سرویس

```bash
sudo cp /opt/quoto/deploy/quoto.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now quoto
```

## ۶. بررسی

```bash
systemctl status quoto
journalctl -u quoto -f        # لاگ زنده؛ با Ctrl+C خارج شو
```

اگر بالا آمده باشد، در لاگ خط `bot is up` را می‌بینی.

## کارهای روزمره

| کار | دستور |
|---|---|
| توقف | `sudo systemctl stop quoto` |
| شروع | `sudo systemctl start quoto` |
| ری‌استارت بعد از تغییر کد | `sudo systemctl restart quoto` |
| دیدن لاگ | `journalctl -u quoto -n 100` |

## به‌روزرسانی

```bash
sudo -u quoto -H bash -c 'cd /opt/quoto && git pull && .venv/bin/pip install -r requirements.txt'
sudo systemctl restart quoto
```

## نکته‌ها

- **همزمان دو نسخه اجرا نکن.** اگر ربات روی سرور بالاست و همزمان روی لپ‌تاپ هم
  `start.bat` را بزنی، تلگرام آپدیت‌ها را بین این دو پخش می‌کند و ربات نصفه‌نیمه جواب
  می‌دهد. قبل از تست محلی، سرویس سرور را متوقف کن.
- `botdata.pkl` (زبانِ انتخابی کاربرها) کنار کد در `/opt/quoto` ساخته می‌شود؛ در
  پشتیبان‌گیری فراموشش نکن.
- سرویس با `ProtectSystem=strict` اجرا می‌شود و فقط به `/opt/quoto` اجازه‌ی نوشتن دارد.
