# Transkript

YouTube linkinden veya yerel videodan **PDF transkript** ureten Windows masaustu
uygulamasi. Transkripsiyon tamamen **yerelde** calisiyor: ses hicbir zaman
ucuncu bir servise gonderilmiyor.

Link yapistir, kuyruga at, PDF al.

---

## Ne yapiyor

- **YouTube linki veya yerel dosya.** Playlist adresleri tek tek videolara aciliyor.
  Linkler cok satirli kutuya satir satir yapistiriliyor, dosyalar surukleyip birakiliyor.
- **Kalici kuyruk.** Uygulama kapansa da duruyor. Yarim kalan isler acilista
  kaldigi yerden devam ediyor, bastan baslamiyor.
- **Bolumlu PDF.** Video YouTube bolum isaretleri tasiyorsa PDF'te baslik,
  icindekiler ve yer imi oluyor; 3.5 saatlik bir konusma 90 sayfalik duz metin
  duvari yerine gezilebilir bir belge cikiyor. Video bolum tasimiyorsa belirli
  araliklarla zaman basligi konuyor.
- **Hazir altyazi kisayolu.** Videoda insan eliyle yazilmis altyazi varsa
  sorup onu kullanabiliyor: 3 saatlik islem 2 saniyeye iniyor.
- **8 GB RAM'de calisiyor.** Model, yigin boyutu ve pencere boyu acilista
  olculen bellege gore seciliyor; is sirasinda bellek daralirsa cokmek yerine
  yavasliyor.
- Cikti: PDF + TXT.

---

## Kurulum (kullanici)

`dist/Transkript-Setup-1.0.0.exe` dosyasini calistirin (96 MB, kuruldugunda
diskte ~350 MB). Yonetici hakki istemiyor, kullanici klasorune kuruluyor.

Imzasiz oldugu icin Windows SmartScreen uyarisi cikar:
**Daha fazla bilgi > Yine de calistir**.

Ilk baslatmada Whisper modeli iniyor (varsayilan `large-v3-turbo`, ~1.6 GB).
Model `%LOCALAPPDATA%\Transkript\models` altinda kaliyor, bir kez iniyor.
Modeller kurulum dosyasina BILEREK dahil edilmedi: `large-v3` tek basina 3 GB.

---

## Donanim ve sure beklentisi

GPU kullanilmiyor, her sey CPU'da calisiyor. 3.5 saatlik bir video icin kaba beklenti:

| Model | Indirme | RAM (yigin 4) | 3.5 saat | Turkce kalitesi | 8 GB'da |
|---|---|---|---|---|---|
| `small` | ~250 MB | ~1.0 GB | ~40-60 dk | Zayif | Rahat |
| `medium` | ~1.5 GB | ~2.0 GB | ~2-3 saat | Orta | Rahat |
| `large-v3-turbo` | ~1.6 GB | ~2.2 GB | ~2.5-3.5 saat | Iyi | **Varsayilan** |
| `large-v3` | ~3.1 GB | ~4.0 GB | ~6-8 saat | En iyi | Hayir, 16 GB ister |

`large-v3-turbo`, `large-v3` ile ayni encoder'i kullaniyor (asil bellek orada),
sadece decoder'i kucuk. Bu yuzden RAM'i yari yariya dusuk ama kalitesi ona yakin.

> Bu sayilar **tahmin**. Kendi makinenizde olcmek icin `scripts/benchmark.py`
> kullanin, gercek degerler `transkript/resources.py` icindeki katalogla
> karsilastirilir.

Uygulama, kuyruk calisirken bilgisayarin uyumasini engelliyor ve isci sureci
dusuk oncelikte calistiriyor: gece boyu suren bir is sirasinda bilgisayar
kullanilabilir kaliyor.

---

## Gelistirme

```bash
git clone <repo> transkript
cd transkript
py -3.12 -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
```

Kalite kapisi:

```bash
.venv\Scripts\ruff check transkript tests scripts
.venv\Scripts\pytest tests -q
```

Arayuzu calistir:

```bash
.venv\Scripts\python run_transkript.py
```

Komut satirindan tek is (arayuz olmadan uctan uca hat):

```bash
.venv\Scripts\python -m transkript.cli "https://www.youtube.com/watch?v=..." --lang tr
.venv\Scripts\python -m transkript.cli --info
```

Donanim olcumu (model secimini buradan yapin):

```bash
.venv\Scripts\python scripts\benchmark.py "https://www.youtube.com/watch?v=..." --slice-minutes 8
```

Kurulum dosyasini uret:

```bash
.venv\Scripts\python scripts\build.py
```

Uretilen ciktilar:

| Cikti | Boyut |
|---|---|
| `dist/Transkript/` (calisir paket) | ~350 MB |
| `dist/Transkript-Setup-1.0.0.exe` | ~96 MB |

PyInstaller adimi bu makinede ~4.5 dakika suruyor.

Inno Setup kurulu degilse sadece `dist/Transkript/` klasoru uretilir, uygulama
yine calisir. Kurmak icin: `winget install JRSoftware.InnoSetup`

---

## Mimari

```
Girdi (link / dosya)
   |
   v
source/resolver ---> ytdlp_source (meta veri, bolumler, ses, altyazi)
   |                 file_source (yerel dosya)
   v
jobqueue (SQLite, WAL)  <--- arayuz buradan okuyor
   |
   v
orchestrator ---> her is AYRI SUREC'te
                    |
                    v
                  pipeline
                    |
      audio (pencereli akis) --> engine/local (faster-whisper)
                    |                  |
                    |            checkpoint (JSONL, pencere pencere)
                    v
              segments (paragraf + halusinasyon filtresi)
                    |
              chapters (bolumleme)
                    |
              export/pdf + export/txt
```

### Uc tasarim karari

**Pencereli akis.** Ses hicbir zaman tamamen bellege alinmiyor; 10 dakikalik
pencereler halinde okunuyor. Tepe bellek video uzunlugundan bagimsiz: 3.5
saatlik video ile 10 dakikalik video ayni RAM'i kullaniyor. 8 GB hedefini
mumkun kilan yapisal karar bu.

Pencere siniri kelimeyi ortadan bolmemek icin once sessizlige hizalaniyor
(hedefin ±15 saniyesinde aranıyor). Sessizlik yoksa 5 saniye bindirme
uygulaniyor ve dikiste olusan tekrar `segments.TranscriptAssembler` tarafindan
temizleniyor.

**Her is ayri surecte.** Uc gerekce: CTranslate2 model bellegini surec omru
boyunca tutuyor ve isletim sistemine geri vermiyor (8 GB'da arka arkaya on video
islenirse bu birikim olumcul); uzun bir cikarim cagrisinin ortasindaki is
parcacigi kesilemiyor ama surec sonlandirilabiliyor; bozuk bir medya dosyasi
yerel kutuphanede cokmeye yol acarsa sadece o is oluyor.

**Pencere bazli ara kayit.** Segmentler geldigi anda JSONL'e yaziliyor ama bir
pencere ancak KENDI ISARETI yazildiginda islenmis sayiliyor. Yarim kalan
pencerenin segmentleri devam ederken atiliyor, cunku o pencere bastan islenecek
ve tutulsalardi metin iki kez cikardi.

### EnCodec neden kullanilmiyor

"Videoyu nöral bir codec ile sikistirip o ciktidan transkript alalim" fikri
degerlendirildi, calismiyor:

- Whisper sikistirilmis veri yemiyor. Girdisi log-Mel spektrogram; codec ciktisi
  Whisper'a verilmeden once PCM'e geri cozulmek zorunda. Zincire iki sinir agi
  gecisi ekleniyor ve ayni yere variliyor: **daha fazla hesap, daha az degil**.
- Darbogaz dosya boyutu degil, encoder hesabi. 3.5 saatlik ses hangi formatta
  saklanirsa saklansin ayni sayida mel karesi uretiyor.
- Dusuk bit hizli nöral codec'ler ASR hata oranini artiriyor.

Fikrin dogru olan kismi alindi: gecici WAV hic yazilmiyor. Sesi arsivlemek
isterseniz dogru format Opus 24 kbps mono (3.5 saat ~38 MB), `audio.export_archive_audio`.

---

## Veri konumlari

| Ne | Nerede |
|---|---|
| Ayarlar, kuyruk, ara kayitlar, kayit dosyalari | `%APPDATA%\Transkript` |
| Whisper modelleri, gecici ses, guncellenen yt-dlp | `%LOCALAPPDATA%\Transkript` |
| PDF ve TXT ciktilari | `Belgeler\Transkript` (ayarlardan degistirilebilir) |

---

## Bakim

**yt-dlp zamanla bozulur.** YouTube sik degisiyor ve paketle gelen surum birkac
ay icinde link indirmede hata vermeye baslar. Ayarlar > YouTube ve sistem >
**yt-dlp'yi guncelle** en son surumu kullanici dizinine cekiyor ve paketlenmis
surum yerine onu kullaniyor. Link tarafinda hata aliyorsaniz once burayi deneyin.

**Yas kisitli veya ozel videolar** icin Ayarlar'dan tarayici cerezi secilmesi
gerekiyor. Tarayicinin kapali olmasi gerekebiliyor.

---

## Lisans

MIT. Indirilen videolarin telif ve kullanim sartlarina uygunlugu kullanicinin
sorumlulugunda.
