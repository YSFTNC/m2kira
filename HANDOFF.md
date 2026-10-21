# m2kira — Devir notu (21 Ekim 2026, 17:30)

Bu not, projeyi devralacak geliştirici ya da yapay zekâ asistanı içindir. Kurulum ve komut ayrıntıları
[README.md](README.md)'de; burada sistemin bugünkü durumu, verilmiş kararlar ve açık işler var.

## 1. Ne yapıyor

Ankara M2 metro hattında (Kızılay–Koru) durağa yürüme mesafesindeki **eşyalı kiralık** daireleri üç siteden
toplar, yeni ilan / fiyat değişimi / yayından kalkma olunca Telegram'dan bildirir ve her şeyi bir web sitesinde
durak durak gösterir.

- Kullanıcı: Yusuf (GitHub `YSFTNC`). Arayüz ve tüm iletişim **Türkçe**. Kullanıcı soru sorulmasını sevmiyor
  ("bana sorma"); makul varsayımla ilerle, yalnız gerçekten kendi hesabıyla yapılması gereken adımları iste.
- Kriterler (site Ayarlar'dan değişir, `feed/settings.json`): bütçe 37.000 TL, +%5 "pazarlıkla"; oda tipi şu an
  yalnız **1+1** seçili; eşya: eşyalı / kısmi / eşyalı-eşyasız; durağa ≤1000 m (1000–1500 "sınırda").
- İşe ulaşım süresi iki hedef için hesaplanır: Milli Kütüphane, Bilkent Şehir Hastanesi (Tarım Bakanlığı durağı + otobüs).

## 2. Nerede ne çalışıyor

| Bileşen | Yer | Sıklık | Not |
|---|---|---|---|
| GitHub Actions `scan.yml` | public repo `YSFTNC/m2kira` | her tetiklemede | Telegram komutları → tarama (emlakjet + PC beslemeleri) → bildirim → site yayını. Veritabanı `data/m2kira.sqlite` actions/cache ile taşınır. |
| Google Apps Script | kullanıcının Google hesabı | 30 dk | `deploy/google-apps-script.gs`; `workflow_dispatch` çağırır. **PC kapalıyken asıl tetikleyici bu.** 21.10'da kuruldu, 16:21'de ikinci tetikleme doğrulandı. |
| GitHub cron | `8,23,38,53 * * * *` + `0 6 * * *` | düzensiz | GitHub zamanlamaları çok düşüyor (19 saatte 6). Yedek olarak duruyor. |
| PC görevi "m2kira hepsiemlak" | kullanıcının dizüstüsü (HP Victus 16, Win 11, Modern Standby) | 30 dk | `pythonw main.py feed-push`; WakeToRun açık (şarjda uyandırır), süre sınırı 29 dk. hepsiemlak ve sahibinden'i tarar, `feed` dalına yazar, GitHub'ı tetikler. |
| Site | https://ysftnc.github.io/m2kira/ | her çalıştırmada | Tek dosya `m2kira/web/index.html` + `data.json`. Açık sayfa 5 dk'da bir yeni veriyi kendisi yükler. |
| Telegram botu | @Iremev_bot | çalıştırma başına | Sahip `TELEGRAM_CHAT_ID`; `/davet` + `/katil KOD` ile üye eklenir (henüz eklenmedi). |

Önemli: GitHub'ın veritabanı ile PC'nin `data/m2kira.sqlite`'ı **ayrıdır**. PC'deki yalnız besleme
durumunu, detay önbelleğini ve PC uyarı sayaçlarını tutar.

## 3. Kaynaklar ve erişim durumu

| Kaynak | Nereden | Sıklık sınırı | Durum (21.10.2026 17:30) |
|---|---|---|---|
| emlakjet | GitHub, düz HTTP | ≥25 dk (`M2KIRA_MIN_INTERVAL_MIN`, sitedeki "Şimdi tara" `force=1` ile atlar) | Sorunsuz. Görselleri başka siteden gösterilemiyor (Cloudflare `Sec-Fetch-Site: cross-site` → 403), sitede gösterilmez; Telegram kartında çalışır. |
| hepsiemlak | **yalnız PC** (ev IP'si) | ≥55 dk (`hepsiemlak_feed.min_interval_min`), 15 sn sayfa aralığı | 30 dk aralıkta bir gün sonra HTTP 429 aldı → saatte bire çekildi. Engel gelirse sonraki tarama takıldığı mahalleden başlar. Son başarılı: 15:48. |
| sahibinden | **yalnız PC**, giriş yapılmış Chrome profili `data/chrome-profile` | ≥115 dk (`sahibinden_feed.min_interval_min`), tarama başına 5 detay | **Duraklatıldı: 22.10.2026 05:12 TR'ye kadar.** 30 dk aralıkta "olağan dışı erişim" sayfası, 21.10 17:09'da PerimeterX "Access to this page has been denied" (görünmez ve ekran dışı görünür Chrome). Kullanıcının elle girişi sorunsuz. `apply_block_backoff`: engelde 12 sa, 48 sa içinde tekrarında 24 sa. Son başarılı tarama: 21.10 01:09. |

Denenmiş ve **tekrar denenmemesi gereken** yollar:
- GitHub sunucusundan hepsiemlak/sahibinden: Cloudflare "Bir dakika lütfen" doğrulamasında kalıyor; Cloudflare WARP
  (proxy modu, headless ve xvfb'de görünür gerçek Chrome) de geçmedi.
- Giriş yapılmamış yeni Chrome profiliyle sahibinden: ev IP'sinden bile `/cs/checkLoading` döngüsü.
- sahibinden kayıtlı arama e-postaları: hesabın Gmail'ine (ysftnctnc@gmail.com) hiç gelmedi; `sahibinden_mail`
  kaynağı kullanılmıyor (GitHub'da yalnız `IMAP_HOST` sırrı var, kullanıcı adı/şifre yok).
- cron-job.org: 21.10'da konsolu bakımdaydı; yerine Apps Script kuruldu.

**Karar:** bot korumalarını (Cloudflare, PerimeterX, CAPTCHA) atlatan araçlar kurulmayacak. Hem sitelerin bilinçli
engeli hem kullanıcının sahibinden hesabı için risk. Engel gelince geri çekil, aralığı aç.

## 4. Bildirim mantığı (Telegram)

- **Kart:** kriterlere uyan yeni / yeniden yayında / artık uyan / fiyatı düşen ilan → fotoğraflı kart (sendPhoto,
  olmazsa düz mesaj). 12'den fazla kart varsa tek kompakt liste.
- **Değişiklik özeti** (`notify_all_changes`, sitede açılıp kapanır): kart olmayan tüm değişiklikler tek mesajda,
  kriter dışı nedeniyle ("bütçe üstü", "2+1 (seçili oda tipi: 1+1)", "eşyasız"…), en fazla 20 satır.
- **Sessizlik mesajı** (`heartbeat_quiet_hours: 3`, `M2KIRA_HEARTBEAT=1`): 08–23 arası 3 saat hiç mesaj gitmezse
  "değişiklik yok, sistem çalışıyor" + kaynakların son kontrol saatleri.
- **Günlük özet** 09:00; zamanlama düşerse sonraki ilk çalıştırmada (`summary_sent_on`).
- **PC uyarıları** (yalnız sahibe): bir kaynak üst üste 2 denemede hiç taranamazsa, günde en fazla bir kez.
- Teknik uyarılar (`subject="m2kira uyarı"`) yalnız sahibe; ilan mesajları üyelere de gider.

## 5. Kullanıcıya bağlı açık noktalar

1. **Dizüstü geceleri Başlat → Kapat ile kapatılıyor** (20 ve 21 Ekim gecesi, Windows olay günlüğünde winlogon,
   hedef S5). Bu sürede hepsiemlak/sahibinden taranmaz. Öneri: kapağı kapatıp şarjda bırakmak; uyandırma ayarlı ama
   gerçek bir gecede **henüz doğrulanmadı** (son 30 günde zamanlayıcıyla uyanma kaydı yok, uyanmalar güç düğmesi/kapak).
2. sahibinden telefon bildirimleri "stabil değil" dedi; uygulamada aynı hesapla giriş, bildirim izni ve Android pil
   kısıtlaması önerildi. Bunu buradan doğrulamak mümkün değil.
3. İsteğe bağlı, yapılmadı: tamamen kapalı PC'de hepsiemlak için telefonu Tailscale exit node olarak kullanmak
   (kullanıcının uygulama kurması + auth key gerekir; mobil veride tarama başına ~5-10 MB).

## 6. Sıradaki işler

- 22.10 05:12'den sonra sahibinden denemesinin sonucuna bak (`data/m2kira.log`, "sahibinden beslemesi").
  Yine engellenirse otomatik 24 saat bekler; sürekli engelleniyorsa sahibinden'i 3–4 saatte bire çekmeyi ya da
  yalnız uygulama bildirimine bırakmayı düşün.
- hepsiemlak'ta 429 sıklığını izle (`hepsiemlak engellendi` satırları).
- Kullanıcı bilgisayarı uyutursa ilk gecenin sabahında gece taramalarını doğrula (log + Windows olay 507 nedeni).
- Site sahibinden kartlarında "konum yok" olanlar: detay sayfası çekildikçe dolar (detay önbelleği
  `data/feed/sahibinden_details.json`).

## 7. Kontrol komutları

```bash
gh run list --repo YSFTNC/m2kira --limit 10                       # çalıştırmalar (event: schedule / workflow_dispatch)
gh run view <id> --repo YSFTNC/m2kira --log | grep "yeni="       # tarama sonucu
tail -30 data/m2kira.log                                          # PC görevi
python -m pytest -q                                               # 66 test geçmeli
python main.py feed-push --only hepsiemlak --no-push              # PC'de tek kaynak, göndermeden
```

```powershell
Get-ScheduledTaskInfo -TaskName "m2kira hepsiemlak"               # son/sonraki çalışma, sonuç kodu
powershell -ExecutionPolicy Bypass -File deploy\pc-gorev.ps1      # görevi yeniden kur (30 dk, uyandırma)
```

## 8. Dosya haritası (önemliler)

- `main.py` — komutlar: `scan`, `summary`, `bot-once`, `export-web`, `feed-push`, `sahibinden-chrome`…
- `m2kira/pipeline.py` — değerlendirme, olaylar, bildirim (kart + özet + sessizlik), en az aralık koruması.
- `m2kira/feed.py` — PC beslemeleri: `collect_hepsiemlak` (kaldığı yerden devam), `collect_sahibinden`
  (detay önbelleği), `attempt_due`, `apply_block_backoff`, `notify_feed_problem`, `push`, `trigger`.
- `m2kira/sources/` — `hepsiemlak.py` (Nuxt durumu), `emlakjet.py` (ld+json + RSC), `sahibinden.py`
  (liste tablosu, "olağan dışı erişim" tanıma), `hepsiemlak_feed.py` (GitHub tarafı besleme okuyucu).
- `m2kira/bot.py` — Telegram komutları, `/davet` `/katil` `/uyeler` `/cikar` `/ayril`.
- `m2kira/web.py`, `m2kira/web/index.html` — site verisi ve arayüz (paylaş düğmesi, kayıtlı filtre, tazelik uyarısı).
- `config.yaml` — tüm aralıklar ve sınırlar burada (tarihli açıklamalarıyla).
- `.github/workflows/scan.yml`, `deploy/pc-gorev.ps1`, `deploy/google-apps-script.gs`, `deploy/kurulum.ps1`.

## 9. Gizli bilgiler ve dokunulmayacaklar

- Sırlar: PC'de `.env` (Telegram token, chat id); GitHub secrets `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
  (`IMAP_HOST` atıl); Apps Script'teki GitHub anahtarı kullanıcının Google hesabında. Hiçbirini mesajlara,
  koda ya da loglara yazma.
- `data/` ve `.env` **asla** commit edilmez; `data/chrome-profile` kullanıcının sahibinden oturumudur.
- Repo public; `feed` dalı ve `data.json` herkese açık (ilan verisi + kriterler, kişisel bilgi yok).
- Commit mesajları Türkçe, sonunda `Co-Authored-By` satırı.

## 10. Bu ortama özgü tuzaklar

- Windows'taki Git Bash aracında heredoc içindeki çift ters eğik çizgi teke iniyor: kaçış karakteri içeren
  yardımcı betikleri dosya yazma aracıyla oluştur.
- Windows PowerShell 5.1 Türkçe yerel ayar: `-match '[A-Z]'` "I" harfini kaçırır (`-cmatch` kullan); `.ps1`
  dosyaları UTF-8 BOM ister.
- hepsiemlak'ı hızlı döngülerle test etme (429 ve uzun engel). sahibinden'e elle deneme isteği atma; her istek
  "otomatik erişim" sayacına ekleniyor.
