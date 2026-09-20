# اجرای دائمی روی سرور لینوکس

این مسیر ربات را ۲۴ ساعته بالا نگه می‌دارد: بعد از ری‌استارت سرور خودش روشن می‌شود و
اگر کرش کند دوباره بالا می‌آید.

فرض: یک سرور اوبونتو (۲۲.۰۴ یا بالاتر) و دسترسی SSH.

روی اوبونتو ۲۶.۰۴ که پایتون ۳.۱۴ دارد هم تست شده و کار می‌کند.

## ۱. آماده‌سازی سرور

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git ffmpeg fonts-dejavu-core \
  fonts-noto-core fonts-noto-cjk fonts-noto-color-emoji
```

`ffmpeg` برای `/gif` لازم است؛ بدون آن هم کار می‌کند ولی خروجی چند برابر سنگین‌تر
می‌شود. `fonts-dejavu-core` فونت سریفِ متن‌های انگلیسی را می‌دهد؛ فونت فارسی جداگانه
دانلود می‌شود.

دو بستهٔ `fonts-noto-*` برای زبان‌های دیگر است: بدونشان یک پیام چینی یا کره‌ای روی کارت به مربع خالی تبدیل می‌شود. ربات موقع بالا آمدن تعداد فونت‌هایی را که پیدا کرده در لاگ می‌نویسد (`fallback fonts available`). `fonts-noto-color-emoji` برای ریکشن‌های زیر اسکرین‌شات لازم است؛ بدون آن ریکشن‌ها اصلاً کشیده نمی‌شوند.

## ۲. کاربر و پوشه

ربات با کاربر جدا اجرا می‌شود، نه با root:

```bash
sudo useradd --system --create-home --home-dir /opt/quoto quoto
```

## ۳. کد و وابستگی‌ها

مخزن روی گیت‌هاب نیست، پس کد از همین سیستم فرستاده می‌شود. این را روی سیستم
خودت بزن (نه روی سرور)، با آی‌پی سرور به‌جای `IP`:

```bash
tar -czf - --exclude=.git --exclude=__pycache__ --exclude=preview_out   --exclude=.venv --exclude=botdata.pkl --exclude=.env --exclude='quotebot.log*'   --exclude=assets/demo . | ssh root@IP "tar -xzf - -C /opt/quoto && chown -R quoto:quoto /opt/quoto"
```

بعد روی سرور:

```bash
sudo -u quoto -H bash
cd /opt/quoto
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python download_fonts.py
exit
```

## ۴. تنظیمات

```bash
sudo -u quoto cp /opt/quoto/.env.example /opt/quoto/.env
sudo -u quoto nano /opt/quoto/.env
```

`BOT_TOKEN` را بگذار. `OWNER_ID` را هم پر کن، وگرنه استیکرپک گروه‌ها ساخته نمی‌شود و
`/debug` هم کار نمی‌کند. اگر سرورت جایی است که تلگرام مستقیم باز است، `PROXY` را خالی
بگذار. دسترسی فایل را هم محدود کن تا توکن خواندنی عمومی نباشد:

```bash
sudo chmod 600 /opt/quoto/.env
```

## ۴.۵ انتقال وضعیت کاربرها

اگر ربات قبلاً جای دیگری اجرا می‌شده، `botdata.pkl` را هم ببر — عکس‌های انتخابی،
سهمیه‌ها، زبان، قالب و اینکه چه کسی استارت کرده همه داخل آن است. بدون آن همه از صفر
شروع می‌کنند.

**اول ربات قبلی را تمیز ببند** (در پنجره‌اش Ctrl+C؛ کشتن با `/F` ممکن است وسط نوشتن
فایل باشد)، بعد:

```bash
cat botdata.pkl | ssh root@IP "umask 077; cat > /opt/quoto/botdata.pkl && chown quoto:quoto /opt/quoto/botdata.pkl"
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
