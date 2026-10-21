# m2kira — Ankara M2 hattı eşyalı kiralık ilan takipçisi

Kızılay–Çayyolu–Koru (M2) metro istasyonlarına yürüme mesafesindeki **eşyalı kiralık daire**
ilanlarını hepsiemlak, emlakjet ve sahibinden üzerinden düzenli tarar; kriterlere uyan **yeni**
ilanları ve **fiyat düşüşlerini** anında, her sabah 09:00'da da bir özet olarak Telegram'a
(ya da e-posta / ntfy.sh) gönderir. Yayından kalkan ilanları da takip eder.

## Web sitesi — https://ysftnc.github.io/m2kira/

Her çalıştırmadan sonra yeniden üretilen, telefonda da çalışan yönetim sitesi. Üç sekme:

**İlanlar** (herkese açık, filtreleme tarayıcıda anında)
- Durak şeridi: Kızılay → Koru hat sırasıyla her durakta ilan sayısı ve en ucuz fiyat; durağa dokununca
  seçilir (birden çok). "Duraklar" görünümü ilanları durak durak gruplar (adet, en ucuz, medyan, işe süre).
- Hazır filtreler: Önerilen · Yeni (24 sa) · Fiyatı düşenler · Milli Kütüphane'ye yakın · Şehir Hastanesi
  rotası · İki hedefe de yakın · En ucuz 1+1 · Yürüme ≤ 8 dk · Faturalar dahil · Pazarlıkla · Favoriler · Tümü.
- Filtreler: fiyat, m², oda, eşya, durağa yürüme, işe ulaşım süresi, kaynak, uyarılı ilanları gizleme,
  faturalar dahil, fiyatı düşen, yeni, metin arama. Sıralama: fiyat, yeni, yürüme, hedeflere süre, m², TL/m².
- Fotoğraflı kartlar (hepsiemlak, sahibinden; emlakjet görsellerini başka sitelerde göstermeyi engellediği
  için emlakjet kartında "fotoğraflar emlakjet'te" yazar), üstte gösterge kutuları (ilan sayısı, son 24 saatte
  yeni, en ucuz, medyan, kaynaklara göre dağılım) — hepsi seçili filtrelere göre; durak gruplarının başında
  fiyatların nokta şeridi ve bütçe çizgisi. Filtreler yandan açılan panelde; aktif filtreler × ile kaldırılan
  etiketler olarak görünür. Açık/koyu tema düğmesi; telefonda alt sekme çubuğu (İlanlar · Harita · Ayarlar · Durum).
- Görünümler: Duraklar · Liste · Harita. Kartta "Detay": açıklama, fiyat geçmişi, ilk görülme, haritada
  aç, durağa yürüyüş tarifi. Filtre kombinasyonu adres çubuğunda durur (yer imi / paylaşım).

**Ayarlar** (bildirimleri ve "kriterlere uyan" listesini belirler)
- Bütçe ve pazarlık payı, kabul edilen oda tipleri ve eşya durumları, metroya yürüme sınırı ve toleransı,
  bildirilmeyecek uyarılar, yalnız seçilen duraklar için bildirim, kalkma bildirimi, taranacak mahalleler.
- "Kaydet ve uygula": ayarları reponun `feed` dalına (`feed/settings.json`) yazar ve kısa bir GitHub
  çalıştırması başlatır (~2 dk); tüm ilanlar yeni ayarlarla yeniden değerlendirilir, yeni uygun hale
  gelenler Telegram'a "✅ Artık kriterlere uyuyor" diye gelir, sayfa kendiliğinden yenilenir.
- Telegram'daki `/butce`, `/gizle`, `/mahalle` da çalışmaya devam eder; site yeniden kaydedene kadar geçerlidir.

**Durum**
- Kaynak başına son tarama, aktif/uygun ilan, son hata; PC'nin son hepsiemlak beslemesinin zamanı;
  son GitHub çalıştırmaları; "Şimdi tara" (tam tarama, ~3-5 dk).

**GitHub'a bağlanma** (yalnız yazma işlemleri için, tarayıcı başına bir kez): sağ üstteki düğme adım
adım anlatır — github.com'da yalnız `m2kira` reposuna *Contents* ve *Actions* yazma izni olan
fine-grained bir anahtar oluşturup yapıştırmak. Anahtar yalnız o tarayıcıda saklanır. Bağlıyken
favoriler ve gizlenenler tüm cihazlarda eşitlenir; gizlenen ilan bildirim üretmez, favori ilanın fiyat
düşüşü ve yayından kalkması her durumda bildirilir.

Telegram: `/filtre` (ya da `/filtre Kızılay`) site linkini, `/durak` durak durak özeti verir; günlük
özette ve toplu bildirimde de link var. Not: repo public olduğu için site de herkese açıktır (ilan
verisi zaten herkese açık; token, kişisel bilgi ya da sahibinden oturumu içermez).

## PC kapalıyken bildirim — önerilen kurulum (≈10 dk, ücretsiz)

| Kaynak | Nerede çalışır | Bildirim |
|---|---|---|
| emlakjet | GitHub Actions, 30 dakikada bir (PC'den bağımsız) | Telegram kartı, 09:00 özet, filtre sayfası |
| hepsiemlak | **PC açıkken ya da uykudayken** (şarjda) Görev Zamanlayıcı ile 30 dakikada bir (pencere açmaz) → GitHub'a besleme | aynı Telegram kartları ve site; PC tamamen kapalıyken son bilinen hali kalır |
| sahibinden | **PC açıkken ya da uykudayken** (şarjda) aynı görev, en fazla 2 saatte bir (30 dakikada bir açılan arama "olağan dışı erişim" sayfasına düştü), giriş yapılmış Chrome profilinle görünmez tarar → GitHub'a besleme. Ayrıca sahibinden'in kendi kayıtlı araması **"M2 eşyalı 39bin altı"** | Telegram kartları ve site (fotoğraf, konum, harita); PC kapalıyken sahibinden uygulaması bildirir |

sahibinden arama sonuçları üye girişi ve gerçek tarayıcı istediği için GitHub sunucusundan taranamıyor;
bu yüzden PC açıkken PC'deki görev tarayıp siteye gönderir, PC kapalıyken sahibinden'in kendi bildirim
sistemi devreye girer. Hem görev hem kayıtlı arama 22 hedef mahalleyi, "Eşyalı: Evet"
ve 39.000 TL tavanını içeriyor; Konutkent, Yaşamkent ve Beytepe dışarıda (oradaki ilanların hiçbiri
istasyona 1,5 km'den yakın değil). **Telefonda sahibinden uygulamasında aynı hesapla oturum açık
olmalı ve bildirim izni verilmeli.**

Kurulum adımları:

1. Telegram'da **@BotFather** → `/newbot` → bota bir ad ver, verdiği token'ı kopyala. Sonra botunu
   açıp `/start` yaz.
2. Proje klasöründe PowerShell:
   ```powershell
   powershell -ExecutionPolicy Bypass -File deploy\kurulum.ps1
   ```
   Betik GitHub CLI'yi kurar, GitHub'a giriş yaptırır (tarayıcı açılır; hesap yoksa orada açılır),
   token'ı sorar, chat id'yi bulur, `m2kira` reposunu oluşturup kodu gönderir, bilgileri repo
   secret'ı olarak kaydeder ve ilk taramayı başlatır. `.env` ve `data/` (sahibinden oturumun dahil)
   asla gönderilmez.
3. İlk tarama ~15-25 dk sürer; uygun ilanların tamamı Telegram'a tek liste olarak gelir. Sonrası
   yalnızca yeni ilan / fiyat düşüşü / yayından kalkma ve her sabah özet.

Repo varsayılan olarak **public** açılır: public repolarda GitHub Actions dakikaları sınırsız ve
ücretsizdir. Repoda sırlar yoktur (token'lar GitHub Secrets'ta); görünen şey kod ve `config.yaml`
(bütçe, mahalleler). Gizli olsun istersen `kurulum.ps1 -Private`: ücretsiz private kota ayda 2000
dakika olduğu için tarama 5 saatte bire düşer.

Bilinmesi gerekenler:
- GitHub zamanlanmış işleri bazen 5-15 dk gecikmeli başlatır.
- Telegram komutları anında değil, bir sonraki çalıştırmada işlenir (`/liste`, `/butce` vb.).
- hepsiemlak GitHub'ın veri merkezi IP'lerini Cloudflare doğrulamasında engelliyor (19 Ekim 2026'da
  headless ve sanal ekranlı görünür Chrome ile denendi, ikisi de HTTP 403). Bu yüzden hepsiemlak ev
  internetinden, PC açıkken taranıyor (aşağıda "hepsiemlak: PC beslemesi"). PC kapalıyken de
  hepsiemlak isteniyorsa evde sürekli açık bir cihaz (Raspberry Pi, eski bir dizüstü) gerekir.
- Public repoda 60 gün commit olmazsa GitHub zamanlamayı durdurur; Actions sekmesinden yeniden açılır.

**sahibinden'i Telegram'a da almak (isteğe bağlı):** sahibinden e-postaları hangi adrese geliyorsa
o hesap için IMAP erişimi gerekir (Gmail: 2 adımlı doğrulama + "uygulama şifresi"). `.env`'e
`IMAP_USER` / `IMAP_PASSWORD` yazıp `kurulum.ps1`'i tekrar çalıştırmak yeterli; `sahibinden_mail`
kaynağı her taramada yeni e-postalardaki ilan linklerini çıkarıp Telegram kartı olarak iletir.
Deneme: `python main.py scan --dry --source sahibinden_mail`.

**PC açıkken sahibinden'i doğrudan taramak (isteğe bağlı):** `python main.py sahibinden-chrome`
gerçek Chrome'u ayrı bir profille açar; orada bir kez giriş yaptıktan sonra
`python main.py scan --source sahibinden` aynı birleşik aramayı (2-3 sayfa) bu Chrome üzerinden tarar
ve ilan detaylarından koordinatla yürüme mesafesini hesaplar.

### PC beslemesi: hepsiemlak + sahibinden

hepsiemlak ve sahibinden bulut sunucularını (GitHub dahil) robot doğrulamasında durduruyor; 20.10.2026'da
GitHub'dan Cloudflare WARP üzerinden de denendi, ikisi de "Bir dakika lütfen" sayfasında kaldı. Bu yüzden bu
iki kaynak evdeki bilgisayardan taranır. **Bilgisayarı kapatma, uyut:** kapağı kapat ya da Başlat → Uyku, şarja
takılı bırak. Görev 30 dakikada bir bilgisayarı uyandırır (ekran açılmaz), tarar, gönderir; Windows sonra yeniden
uyutur. Uyandırma yalnız şarjdayken olur (Windows'un "uyandırma zamanlayıcılarına izin ver" ayarı şarjda açık,
pilde kapalı). "Kapat" ile tamamen kapatılan bilgisayarı hiçbir şey uyandıramaz; o sürede sahibinden'in kendi
uygulama bildirimi ve emlakjet (GitHub) çalışmaya devam eder.

```powershell
powershell -ExecutionPolicy Bypass -File deploy\pc-gorev.ps1          # Görev Zamanlayıcı görevini kur
powershell -ExecutionPolicy Bypass -File deploy\pc-gorev.ps1 -Kaldir  # kaldır
python main.py feed-push                                             # elle bir kez çalıştır
```

sahibinden için: görev, gerçek Google Chrome'u giriş yaptığın profille (`data/chrome-profile`) **görünmez**
(`--headless=new`) açar; 22 mahallelik kayıtlı aramayı (2 sayfa) okur, konum için tarama başına en fazla
15 yeni ilanın detayını çeker (detaylar önbellekte kalır, her ilan bir kez) ve Chrome'u kapatır. sahibinden
kısa sürede çok detay açılınca geçici bir giriş duvarı gösteriyor (~30 detayda görüldü); o zaman detay o
tarama için bırakılır, liste yine gönderilir. Oturum gerçekten düşerse PC'den Telegram'a
"🔑 sahibinden oturumu düştü" uyarısı gelir: `python main.py sahibinden-chrome` çalıştırıp açılan Chrome'da
giriş yap, pencereyi kapat.

Görev oturum açıkken 30 dakikada bir ve oturum açılışında `python main.py feed-push` çalıştırır:
önce sahibinden (birkaç dakika), sonra hepsiemlak (hızlı geçiş + günde bir tam geçiş) taranır. Her kaynağın
sonucu bittiği anda reponun `feed` dalına (`feed/sahibinden.json`, `feed/hepsiemlak.json`) yazılır ve
GitHub işi varsayılan kaynaklarla hemen tetiklenir; yavaş bir hepsiemlak geçişi sahibinden bildirimlerini
bekletmez. Her GitHub çalıştırması taze ve işlenmemiş tüm beslemeleri, vakti gelmişse emlakjet'i ve kaçan
günlük özeti işler; bu yüzden GitHub'ın zamanlayıcısı bir çalıştırmayı düşürse ya da sıradaki bir iş iptal
olsa da veri kaybolmaz. Hedef 30 dakikada bir yenileme: GitHub zamanlanmış çalıştırmaları sık düşürdüğü için
iş 15 dakikada bir denenir; emlakjet 25 dakikadan sık taranmaz (sitedeki "Şimdi tara" bu kuralı atlar).
Site açık kaldıkça yeni sonuçları 5 dakikada bir kendiliğinden yükler.
Bir kaynak üst üste iki çalıştırmada hiç taranamazsa PC Telegram'a çözüm önerisiyle haber verir.
Tek kaynak: `python main.py feed-push --only sahibinden`.
GitHub tarafı beslemeyi normal bir kaynak gibi işler: yeni ilan / fiyat düşüşü bildirimi, kopya
tespiti, filtre sayfası. 3 saatten eski besleme işlenmez (ilanlar silinmez, uyarı gitmez); aynı besleme
iki kez işlenmez. Bütçe, yayınlanan `data.json`'dan alınır (`/butce` değişikliği PC'ye de yansır).
Kayıt: `data\m2kira.log`.

### GitHub zamanlayıcısı çalışmazsa: dış tetikleyici (5 dakika, ücretsiz)

**En kolayı Google Apps Script:** [deploy/google-apps-script.gs](deploy/google-apps-script.gs) dosyasının başındaki
4 adımı izle (script.google.com'da yeni proje, kodu yapıştır, GitHub anahtarını gir, `kur` işlevini çalıştır).
Google hesabında çalışır, ayrı hesap gerekmez, 30 dakikada bir GitHub işini başlatır. Aşağıdaki cron-job.org
yolu aynı işi yapar (20.10.2026'da konsolu bakımdaydı).

GitHub zamanlanmış çalıştırmaları düşürebiliyor (20.10.2026 gecesi 10 saatte 6 zamanlamadan 1'i çalıştı).
PC kapalıyken emlakjet, Telegram komutları ve 09:00 özeti bu çalıştırmalara bağlı. Sitenin Durum
sekmesindeki "Son çalıştırmalar" listesinde saatlerce "zamanlanmış" satırı görünmüyorsa:

1. GitHub → Settings → Developer settings → Fine-grained tokens → yalnız `YSFTNC/m2kira` deposu,
   izin **Actions: Read and write** ile bir token oluştur (sitedeki "GitHub'a bağlan" için oluşturduğun
   token da olur).
2. https://cron-job.org adresinde ücretsiz hesap aç → **Create cronjob**:
   - URL: `https://api.github.com/repos/YSFTNC/m2kira/actions/workflows/scan.yml/dispatches`
   - Zamanlama: her 30 dakikada bir (Every 30 minutes)
   - Advanced → Request method: **POST**, Request body: `{"ref":"main"}`
   - Headers: `Authorization: Bearer <token>`, `Accept: application/vnd.github+json`,
     `X-GitHub-Api-Version: 2022-11-28`
3. Kaydet. Sık tetikleme sorun değil: emlakjet en az 25 dakika arayla taranır, beslemeler bir kez
   işlenir, özet günde bir gider.

### Alternatif çalışma yerleri

- **Raspberry Pi / VPS** (komutlar anında, ev IP'si Cloudflare için en rahatı): `docker compose up -d --build`
  ([docker-compose.yml](docker-compose.yml)) ya da [deploy/m2kira.service](deploy/m2kira.service).
- **PC'de**: `python main.py run` (uyku modu kapalı olmalı).

## Yerel kurulum ve komutlar

```bash
python -m venv .venv && .venv\Scripts\activate      # Linux/mac: source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
copy .env.example .env                               # Telegram token'ı .env'e yazın
```

```bash
python main.py run                 # zamanlayıcı (30 dakikada bir tarama, 09:00 özet) + Telegram komutları
python main.py scan                # tek tarama (bildirim gönderir)
python main.py scan --dry          # tek tarama, bildirimler konsola
python main.py scan --source emlakjet --neighborhood Emek
python main.py list                # bütçe içindeki uygun ilanlar
python main.py summary             # özeti gönder
python main.py status
python main.py check-known         # handoff'taki bilinen ilanlar veritabanında mı?
python main.py test-notify         # bildirim kanalı testi
python main.py sahibinden-chrome   # gerçek Chrome'u aç (cdp modu), orada giriş yap
python main.py bot-once            # birikmiş Telegram komutlarını bir kez işle (GitHub Actions)
```

`M2KIRA_SOURCES=hepsiemlak,emlakjet` ortam değişkeni taramayı bu kaynaklarla sınırlar.

## Telegram komutları

| Komut | İşlev |
|---|---|
| `/liste [n]` | bütçe içindeki aktif ilanlar, en ucuz n tanesi (varsayılan 15) |
| `/liste pazarlik` | bütçeyi %5'e kadar aşan ilanlar |
| `/liste istasyon Söğütözü` · `/liste mahalle Emek` | istasyon / mahalle süzgeci |
| `/ilan he:131733-2621` | ilan kartı + fiyat geçmişi |
| `/butce 40000` | bütçe tavanı (kalıcı; config'i ezer) |
| `/mahalle` · `/mahalle ekle Ayrancı Kızılay` · `/mahalle sil Ayrancı` | izlenen mahalleler |
| `/gizle he:131733-2621` · `/goster ...` | ilanı gizle / geri getir |
| `/durak` | durak durak özet (hat sırasıyla adet, en ucuz, medyan; her durak filtre sayfasına link) |
| `/filtre` · `/filtre Kızılay` | filtre sayfası linki (isteğe bağlı durak seçili) |
| `/ozet` · `/tara` · `/durum` · `/yardim` | özet, hemen tara, durum |

İlan kimlikleri kısa biçimde: `he:` hepsiemlak, `ej:` emlakjet, `sb:` sahibinden.

## Arkadaşınla birlikte kullanmak

- **Site:** sağ üstteki paylaş düğmesi o anki filtrelerle bağlantıyı paylaşır (telefonda paylaşım menüsü,
  bilgisayarda panoya kopyalar). Arkadaşın filtrelerini ve favorilerini kendi tarayıcısında tutar; ayarları
  değiştiremez. Favoriler ve ayarlar ortak olsun istersen ona da bir GitHub anahtarı ver (yalnız bu depo,
  Contents + Actions: Read and write) ve sitede "GitHub'a bağlan" ile girsin.
- **Telegram:** bota `/davet` yaz; çıkan kodu arkadaşına ver, o da bota `/katil KOD` yazsın (kod 48 saat
  geçerli, tek kullanımlık). Katılan üyeler ilan kartlarını, değişiklik özetlerini ve günlük özeti alır,
  komutları kullanabilir; teknik arıza uyarıları yalnız sana gelir. `/uyeler`, `/cikar <no>`, üye için `/ayril`.

## Yapılandırma (`config.yaml`)

* `budget`, `budget_tolerance_pct` (bütçeyi %5'e kadar aşanlar "🤝 pazarlıkla" etiketiyle gelir)
* `scan_interval_hours`, `daily_summary_time`, `timezone`
* `max_walk_m` (1000) ve `walk_tolerance_m` (500): koordinatı olan ilanlarda en yakın M2
  istasyonuna kuş uçuşu mesafe hesaplanır; 1000–1500 m "sınırda" (bildirilir, ⚠️), üstü "uzak"
  (bildirilmez). Koordinat yoksa mahallenin varsayılan istasyonu atanır ve "mesafe doğrulanmadı"
  denir. Geniş mahallelerde (`require_distance: true` — Beytepe, Konutkent, Yaşamkent) koordinat
  doğrulanmadan bildirim yapılmaz; koordinat detay sayfasından gelir (tarama başına kota dahilinde).
  Not: Bahçelievler/Emek ilanlarının çoğu Milli Kütüphane'ye 1.1–1.9 km düşüyor (Ankaray daha
  yakın); bunlar "sınırda" ya da "uzak" olarak işaretlenir.
* `furnished_accept`: `full` (eşyalı), `partial` (beyaz eşyalı), `either` (eşyalı veya eşyasız).
  `include_unknown_furnished: true` yaparsanız eşya durumu belirsiz ilanlar da bildirilir.
* `exclude_flags`: varsayılan `gunluk`, `oda` (oda kiralık/paylaşımlı), `uzak` — bu ilanlar
  kaydedilir ama bildirilmez.
* `stations`: M2 istasyon koordinatları (OpenStreetMap). Koru sonrası uzantı istasyonları
  `M2EXT` olarak duruyor; açıldıysa `line: M2` yapın. Ankaray istasyonları yalnızca uyarı içindir.
* `neighborhoods`: mahalle adı, varsayılan istasyon, hepsiemlak/emlakjet URL slug'ı ve sahibinden
  mahalle kimliği (`address_quarter`, sitenin `/ajax/search/locationFacets` uç noktasından). Bir kaynakta
  mahalle yoksa `false`. Yanlış slug 404 verir; tarama özetinde "slug yanlış olabilir" diye görünür.
  hepsiemlak slug'ları sitenin kendi navigasyon verisinden alındı: bazı mahalleler `cankaya-` önekiyle
  (`cankaya-emek`), bazıları öneksiz tam yol olarak (`korkutreis-kiralik/daire`) tanımlı; hepsiemlak'ta
  ayrıca "semt" sayfaları var (`cayyolu-kiralik/daire` geniş, `cayyolu-mah-kiralik/daire` dar).
* `sources.<kaynak>.max_detail_fetch`: tarama başına detay sayfası sınırı. Detay yalnızca bütçe
  tavanını geçen ve eşya durumu belirsiz / koordinatsız ilanlar için çekilir.
* **Hızlı / tam geçiş**: her taramada yalnızca `fast_categories` listeleri çekilir (hepsiemlak: eşyalı
  daire; emlakjet: daire) — yeni ilan ve fiyat düşüşü buradan gelir. `full_scan_every_hours`'ta bir
  (hepsiemlak 24 sa, taramada en çok `max_full_per_run`=4 mahalle; emlakjet 6 sa) residence ve
  filtresiz listeler de taranır; "yayından kalktı" kararı yalnızca tam geçişte verilir. Böylece
  hepsiemlak'a giden istek sayısı tarama başına ~110'dan ~40'a iner.
* `request_interval_sec` (5): aynı siteye ardışık istekler arası bekleme. hepsiemlak için
  `min_interval_sec` (8) geçerli: resim/JS de yüklenirken 5 sn aralıkla ~25 sayfada Cloudflare
  **HTTP 429** verdi; artık yalnız HTML yükleniyor (`block_resources`). 429/doğrulama görülürse
  `cooldown_sec` (120) beklenip bir kez daha denenir; yine olmazsa kaynak `block_cooldown_min` (45)
  boyunca atlanır. Liste sayfaları 20 dk, detaylar 24 saat disk önbelleğinde tutulur (`data/cache`).

## Nasıl çalışır

1. **Tarama** (`m2kira/pipeline.py`): her kaynak × mahalle için liste sayfaları çekilir
   (hepsiemlak: eşyalı filtresi + bütçe tavanlı filtresiz liste; emlakjet: mahalle sayfası;
   sahibinden: 22 mahallelik tek birleşik arama), ilanlar `Listing` modeline normalize edilir.
   Birleşik aramadan gelen ilanlar ilan sayfasındaki mahalle adına göre config'teki mahalleye eşlenir.
2. **Zenginleştirme**: başlık+açıklamadan eşya durumu (`eşyalı|mobilyalı|möbleli`, "beyaz eşyalı"
   → kısmi, "eşyalı veya eşyasız" → either), fiyata dahil olanlar (faturalar/aidat/her şey),
   risk bayrakları (ACİL, depozitosuz, kapora, kısa süreli, kot/bodrum, "kız öğrenci/kadınlara
   özel" kısıtı, oda kiralık) ve **Ankaray uyarısı** (metinde Ankaray/Emek metro/Bahçelievler
   metro/Beşevler metro/AŞTİ geçiyorsa ya da koordinat Ankaray durağına M2'den daha yakınsa).
   Koordinat varsa en yakın M2 istasyonu ve tahmini yürüme süresi.
3. **Değişiklik tespiti** (`m2kira/db.py`): yeni ilan, fiyat düşüşü/artışı (fiyat geçmişi
   tutulur), yeniden yayına girme ve yayından kalkma (ardışık 2 tam geçişte görünmeyen ilan).
   **Kopya tespiti**: aynı ofis + aynı m²/kat/fiyat, aynı başlık + m², ya da hepsiemlak'ta aynı
   ofis numarası → "muhtemel kopya: he:…" bayrağı.
4. **Bildirim**: kriterlere uyan yeni/yeniden yayında/fiyat düşen ilanlar kart olarak; daha önce
   bildirilmiş ilan kalkınca "yayından kalktı". Tek taramada 12'den fazla değişiklik varsa tek bir
   kompakt liste gönderilir (ilk tarama). Parser bozulursa (sayfa gelir ama veri çıkmazsa)
   "🛠 parser hata verdi" bildirimi gelir (6 saatte bir en fazla).
5. **Bölge medyanı**: aynı mahalledeki aktif ilanların medyanının %40 altındaki fiyatlar
   "fiyat çok düşük ⚠️" bayrağı alır (en az 5 örnek).

## Kaynaklar ve bot koruması (19 Ekim 2026 itibarıyla)

| Kaynak | Erişim | Yöntem | Not |
|---|---|---|---|
| hepsiemlak | Cloudflare managed challenge (curl/requests 403) + hız sınırı (HTTP 429) | headless Chrome/Chromium (Playwright), yalnız HTML, `window.__NUXT__` JSON, 8 sn aralık | Koordinat, eşya bayrağı, m², kat, ofis listede hazır. `?maxPrice=` ve `?page=` robots.txt'te serbest (site bunları `p32`/`p33`'e çevirir). Eşyalı filtresine girmeyen ilanlar "eşyasız" sayılır; başlık "eşyalı / eşyalı veya eşyasız" diyorsa metin kazanır. |
| emlakjet | Düz HTTP 200 | `requests` + schema.org ld+json + Next.js RSC yükü | Liste kartında eşya rozeti/eski fiyat; detayda koordinat, Eşya Durumu, aidat. robots.txt `max_fiyat`/`oda_sayisi` parametrelerini yasaklar, kullanılmaz. |
| sahibinden | Cloudflare + PerimeterX; arama sonuçları **giriş istiyor**; Playwright Chromium'da doğrulama döngüsü, headless Chromium'da engel | PC'de kullanıcının **gerçek Chrome**'u, giriş yapılmış ayrı profil, `--headless=new` (görünmez) → `feed/sahibinden.json` → GitHub'da `sahibinden_feed` | Tek birleşik arama: 22 mahalle kimliği + `a103713=true` (Eşyalı) + `price_max`, 50'şer ilanlık 2 sayfa. Sonuç yoksa (`data-totalmatches="0"`) tablo "benzer ilanlar" önerisiyle gelir; parser bunları atar. Detay: `dl.classifiedInfoList` dt/dd, `#gmap[data-lat/lon]`. Fotoğraf: satırdaki `lthmb_` → `x5_`. |
| emlakclick | Düz HTTP, ancak mahalle sayfası URL'si bulunamadı (404) | — | Uygulanmadı (yedek kaynak). |

Her site için parser ayrı modüldedir: `m2kira/sources/hepsiemlak.py`, `emlakjet.py`, `sahibinden.py`.
Site değişince yalnızca ilgili modül ve `tests/fixtures/` altındaki kayıtlı sayfa güncellenir.

## Doğrulama (19 Ekim 2026, canlı dry-run)

Son tam tarama (daire + residence, temiz veritabanı): **608 aktif ilan, 51'i kriterlere uygun**.

* **emlakjet**: 26 mahalle × 2 kategori = 52 sayfa, 267 ilan (259 daire + 8 residence), ~7,5 dk
  (önbellekle 2 dk). Handoff'taki 9 emlakjet ilanının 9'u da bulundu (19968826: 35.000 TL, 1+1,
  Ümit, eşyalı, koordinat → Çayyolu ~630 m; 19956486: kot 1 + faturalar dahil + Ankaray uyarısı;
  19992619: Emek 3+1 30.000, "sınırda"). emlakjet'te "Kızılay Mahallesi", "Ehlibeyt", "Kızılırmak"
  sayfalarında kiralık ilan yok (0 sonuç, hata değil).
* **hepsiemlak**: ilk denemede 5 sn aralıkla ~25 sayfadan sonra Cloudflare HTTP 429 geldi ve
  ~1 saat sürdü (alt kaynak istekleri de sayılıyor). 15 sn aralık + yalnızca HTML yükleme +
  45 dk geri çekilme ile 26 mahalle × 2 kategori, 109 sayfa, 347 ilan ~18 dk'da engelsiz tarandı.
  Namık Kemal, Söğütözü, Çukurambar, Kızılırmak, Mustafa Kemal sayfalarında bütçe tavanı altında
  ilan yok. Bilinen 17 hepsiemlak ilanından 14'ü doğru fiyat/oda/mahalle ile bulundu; 14457-526 ↔ 14457-532 kopya
  olarak yakalandı; 25987-2269 "eşyalı veya eşyasız", 44819-2375 "kot/bodrum" etiketi aldı.
  Bulunamayan 3'ü: 0-47236360 ve 0-47307387 yayından kalkmış (detay sayfası listeye yönlendiriyor);
  7655-1320 (Mustafa Kemal stüdyo) detayı açık ama sitenin Mustafa Kemal liste sayfasında yok
  (muhtemelen süresi dolmuş/pasif ilan) — liste tabanlı tarama bunu göremez.
  Dikkat: hepsiemlak sonuç olmayan mahalle sayfasında `list` içine Çankaya genelinden 24 ilanlık
  "üst bölge" listesi koyuyor (`totalAdvertisement: 0`); parser bunu atar. "Semt" sayfaları
  (`cankaya-kocatepe`) komşu mahalleleri de listeler; config'de mahalle sayfaları (`-mah`) seçildi.
* **sahibinden** (kullanıcının oturumuyla, gerçek Chrome üzerinden): birleşik arama 2 sayfada
  75 ilan getirdi, hepsi mahallesine eşlendi; detay çekilen 10 ilanda koordinattan mesafe hesaplandı
  (Kızılay ilanları 200-860 m, bir Emek ilanı 1,6 km → "uzak"); oda kiralık ve günlük ilanlar elendi.
  sahibinden 1260966563 (Ümit, 35.000 TL, Gordion AVM karşısı) emlakjet 19968826 ile aynı daire.
  Headless ve Playwright Chromium ile sahibinden doğrulamayı geçemiyor.
* **GitHub Actions simülasyonu** (yerelde, boş veritabanı, `M2KIRA_SOURCES=hepsiemlak,emlakjet`,
  sistem Chrome'u, hızlı/tam geçiş planı): hepsiemlak 39 sayfa / 150 ilan, hiç 429 yok; emlakjet
  47 sayfa / 192 ilan; ilk tarama detay çekimleriyle ~13 dk. Sonraki taramalar daha kısa (detaylar
  veritabanında kalıyor).
* Handoff'ta "bu hafta bulunamayan" 4 hepsiemlak ilanı (1124-6418, 6792-5182, 8292-4421, 4077-2408)
  taramada **yayında** çıktı (ör. 1124-6418 19 Ekim'de 18.000 TL ile yeniden girilmiş; 8292-4421
  Çukurambar Akman Residence 35.000 TL). `python main.py check-known` bu listeyi her zaman yeniden
  kontrol eder.

## Testler

```bash
python -m pytest -q
```

`tests/fixtures/` altında 19 Ekim 2026'da kaydedilmiş gerçek sayfalar var (hepsiemlak Kızılay
eşyalı listesi + 131733-2621 detayı; emlakjet Bahçelievler ve Çayyolu listeleri + 19968826
detayı; sahibinden birleşik arama, sıfır sonuçlu öneri sayfası ve 1260966563 detayı — sahibinden
sayfaları hesap bilgisi içermeyecek şekilde kırpıldı). Testler bilinen ilanları (fiyat, oda, m², kat, koordinat, eşya, aidat) doğrular; ayrıca
metin normalizasyonu, mesafe hesabı ve sahte kaynakla tam tarama yaşam döngüsü (yeni → fiyat
düşüşü → kalkma → yeniden yayın, kopya, gizleme, bütçe/mahalle ayarları) test edilir.

## Dosya düzeni

```
main.py                 CLI
config.yaml             bütçe, mahalleler, istasyonlar, kaynaklar, bildirim
.env                    sırlar (Telegram token vb.)
m2kira/
  config.py  models.py  textnorm.py  geo.py      yapılandırma, ilan modeli, metin/eşya/bayrak, mesafe
  http.py    browser.py                           kibar HTTP (aralık+önbellek) / Playwright getirici
  sources/   hepsiemlak.py emlakjet.py sahibinden.py sahibinden_mail.py
  db.py      dedup.py    pipeline.py              SQLite, kopya tespiti, tarama orkestrasyonu
  format.py  notify/     bot.py  scheduler.py     mesajlar, Telegram/e-posta/ntfy, komutlar, zamanlayıcı
  web.py     web/index.html  site_settings.py      web sitesi (data.json + arayüz) ve siteden gelen ayarlar
  feed.py    sources/hepsiemlak_feed.py            PC -> GitHub hepsiemlak beslemesi
tests/                  pytest + kayıtlı HTML/JSON fikstürleri
deploy/                 kurulum.ps1 (GitHub Actions kurulumu), m2kira.service (systemd)
.github/workflows/      scan.yml (30 dakikada bir tarama + 09:00 özet)
data/                   m2kira.sqlite, cache/, profiles/ (tarayıcı oturumları), m2kira.log
```
