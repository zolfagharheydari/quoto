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
sudo useradd --system --no-create-home --home-dir /var/lib/quoto --shell /usr/sbin/nologin quoto
sudo mkdir -p /opt/quoto
```

کد مال root است و ربات فقط می‌تواند بخواندش. چیزهایی که ربات می‌نویسد (`botdata.pkl` و
لاگ) در `/var/lib/quoto` هستند که systemd خودش می‌سازد. این‌طوری اگر روزی باگی در ربات
پیدا شود، با آن نمی‌شود کد یا فایل pickle را عوض کرد و ماندگار شد.

## ۳. کد و وابستگی‌ها

مخزن روی گیت‌هاب نیست، پس کد از همین سیستم فرستاده می‌شود. این را روی سیستم
خودت بزن (نه روی سرور)، با آی‌پی سرور به‌جای `IP`:

```bash
tar -czf - --exclude=.git --exclude=__pycache__ --exclude=preview_out   --exclude=.venv --exclude=botdata.pkl --exclude=.env --exclude='quotebot.log*'   --exclude=assets/demo . | ssh root@IP "tar -xzf - -C /opt/quoto --no-same-owner && chown -R root:root /opt/quoto && chown root:quoto /opt/quoto/.env 2>/dev/null; chmod 640 /opt/quoto/.env 2>/dev/null; true"
```

بعد روی سرور (با root):

```bash
cd /opt/quoto
python3 -m venv .venv
.venv/bin/pip install --require-hashes -r requirements.lock
.venv/bin/python download_fonts.py
.venv/bin/python -m compileall -q .
```

`requirements.lock` همهٔ بسته‌ها را با نسخهٔ دقیق و hash نگه می‌دارد؛ pip هر فایلی که
hash آن نخواند را نصب نمی‌کند. `download_fonts.py` هم هر فونت را با hash ثبت‌شده چک می‌کند.

اگر `requirements.txt` را عوض کردی، lock را روی سرور (همان پایتون 3.14) دوباره بساز:

```bash
python3 -m venv /tmp/lock && /tmp/lock/bin/pip install pip-tools
/tmp/lock/bin/pip-compile --generate-hashes --allow-unsafe --strip-extras --no-header   --output-file requirements.lock requirements.txt
```

### فایل‌های /fire

`/fire` («آتیشش کن») روی کلیپ Gunna می‌نویسد. کلیپ و دو فونت دست‌نویس در گیت نیستند
و باید دستی در `assets/fire/` گذاشته شوند (tar بالا اگر روی لپ‌تاپ باشند خودش می‌بردشان):

- `base.mp4` — با `python tools/make_fire_base.py <کلیپ اصلی>` ساخته می‌شود؛ متن قدیمی
  روی کاغذ از قبل پاک شده تا هر درخواست فقط متن را بنویسد
- `IranNastaliq.ttf` و `Cinderella.otf`
- `page.json` در گیت هست

بدون این‌ها ربات بالا می‌آید و `/fire` فقط می‌گوید فعلاً در دسترس نیست. نستعلیق به
libraqm نیاز دارد که Pillow روی اوبونتو دارد؛ روی ویندوز به‌جایش فونت خود ربات استفاده می‌شود.

## ۴. تنظیمات

```bash
sudo cp /opt/quoto/.env.example /opt/quoto/.env
sudo nano /opt/quoto/.env
```

`BOT_TOKEN` را بگذار. `OWNER_ID` را هم پر کن، وگرنه استیکرپک گروه‌ها ساخته نمی‌شود و
`/debug` هم کار نمی‌کند. اگر سرورت جایی است که تلگرام مستقیم باز است، `PROXY` را خالی
بگذار. دسترسی فایل را هم محدود کن تا توکن خواندنی عمومی نباشد:

```bash
sudo chown root:quoto /opt/quoto/.env
sudo chmod 640 /opt/quoto/.env
```

ربات می‌تواند بخواندش ولی نه عوضش کند؛ بقیهٔ کاربرهای سرور اصلاً نمی‌بینندش.

## ۴.۵ انتقال وضعیت کاربرها

اگر ربات قبلاً جای دیگری اجرا می‌شده، `botdata.pkl` را هم ببر — عکس‌های انتخابی،
سهمیه‌ها، زبان، قالب و اینکه چه کسی استارت کرده همه داخل آن است. بدون آن همه از صفر
شروع می‌کنند.

**اول ربات قبلی را تمیز ببند** (در پنجره‌اش Ctrl+C؛ کشتن با `/F` ممکن است وسط نوشتن
فایل باشد)، بعد:

```bash
cat botdata.pkl | ssh root@IP "mkdir -p /var/lib/quoto && umask 077 && cat > /var/lib/quoto/botdata.pkl && chown -R quoto:quoto /var/lib/quoto && chmod 700 /var/lib/quoto"
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

کد را با همان tar بخش ۳ بفرست، بعد روی سرور:

```bash
cd /opt/quoto && .venv/bin/pip install --require-hashes -r requirements.lock && .venv/bin/python -m compileall -q .
sudo systemctl restart quoto
```

## نکته‌ها

- **همزمان دو نسخه اجرا نکن.** اگر ربات روی سرور بالاست و همزمان روی لپ‌تاپ هم
  `start.bat` را بزنی، تلگرام آپدیت‌ها را بین این دو پخش می‌کند و ربات نصفه‌نیمه جواب
  می‌دهد. قبل از تست محلی، سرویس سرور را متوقف کن.
- `botdata.pkl` و `quotebot.log` در `/var/lib/quoto` هستند؛ در پشتیبان‌گیری فراموششان نکن.
- سرویس فقط در `/var/lib/quoto` می‌تواند بنویسد، حداکثر ۱۲۰۰ مگابایت رم و ۱.۷ هسته
  می‌گیرد، و دسترسی‌اش به بقیهٔ سیستم بسته است (فایل `quoto.service` را ببین). اگر
  رندری از حد بگذرد، فقط ربات ری‌استارت می‌شود، نه کل سرور.
