# iddaa·lab

Maçları analiz eden, oyuncu şutlarını simüle eden ve iddaa oranlarıyla kıyaslayıp kupon öneren web uygulaması.
Tamamen **ücretsiz** kaynaklarla çalışır, API anahtarı gerekmez.

**Canlı site:** https://batuhanlgn.github.io/iddaa-lab/

## GitHub'da otomatik çalışma

`.github/workflows/update.yml` dosyası her şeyi kendiliğinden yapar:

1. **3 saatte bir** veri, iddaa oranları, model, tahmin ve kuponlar güncellenir.
2. Site statik olarak derlenir ve GitHub Pages'te yayınlanır.
3. **Pazartesileri** ek olarak backtest çalışır.

Diğer ayrıntılar:

- Veritabanı, `data` adlı Release'te saklanır. Her çalışma bir öncekinin üzerine kurulur.
- Elle tetiklemek için: Actions → "Güncelle ve yayınla" → Run workflow.

## Yerelde çalıştırma

```powershell
cd C:\iddaa-lab
.\start.ps1      # arka uç + arayüz; tarayıcıda http://127.0.0.1:3000 açılır
.\stop.ps1       # durdurur
```

İlk açılışta veritabanı boşsa 27 aylık veri iner, ardından backtest ve tahminler hesaplanır. Bu yaklaşık 1–1,5 saat sürer
ve ilerleme **Veri** sayfasında görünür. Uygulama açıkken veriler kendiliğinden güncellenir:

- oranlar 30 dakikada bir,
- tam güncelleme 3 saatte bir.

## Veri kaynakları

| Kaynak | Ne için | Not |
|---|---|---|
| ESPN `site.api.espn.com` | Fikstür, sonuç, takım istatistikleri (şut, isabet, korner), oyuncu istatistikleri, gol dakikaları, kadrolar | 47 lig/kupa; anahtarsız |
| iddaa.com `sportsbookv2.iddaa.com` | Güncel iddaa oranları, MBS | ~1.100 futbol maçı; her değişiklik arşivlenir |
| ESPN `apis/v2/.../standings` | Lig puan durumu (resmi tablo: puan silme, bölge notları, konferans/grup) | 39 lig; 15 dakikada bir |
| ESPN `all/teams/{id}/schedule` | Karşılıklı geçmiş için eski sezon maçları | Ayrı tabloda (`h2h_history`); model eğitimi kullanmaz |
| iddaa.com `sportotov2.iddaa.com` + `contentv2.iddaa.com/appconfig` | Spor Toto programı, sonuçlar, ikramiyeler; kolon bedeli ve kupon başına kolon sınırı | Anahtarsız |

## Model (Claude ↔ Codex ortak kararı, `docs/`)

- **Skor:** tek ortak hiyerarşik Poisson modelidir ve Dixon-Coles düzeltmesi içerir.
  - Takım gücü = lig ortalaması + lig içinde toplamı sıfır sapma.
  - Avrupa kupaları, yerel kupalar ve küme düşen/çıkan takımlar ligleri birbirine bağlar.
  - Zaman sönümü ξ ve büzülme σ, walk-forward doğrulamayla seçilir.
- **İlk yarı:** tam maç skoru, gollerin yarılara binom dağıtımıyla bölünür. Bu yöntem tam maç dağılımını aynen korur.
- **Simülasyon (maç başına 10.000):**
  - Skor modelden çekilir.
  - Şut, isabetli şut ve gol bu skora koşullu üretilir: `P(S,T,F,O | F+O=skor)`.
  - Geçerli bir ilk 11 ve değişiklik senaryosu örneklenir.
  - Şutlar oyunculara dağıtılır. Her zaman `gol ≤ isabetli ≤ şut` tutar; kendi kalesine goller ayrı tutulur.
- **Oyuncu oranları:** şut/90, isabet ve dönüşüm oranları pozisyon ortalamasına doğru büzülür (az veri = temkinli tahmin).
- **Piyasa harmanı:**
  - iddaa oranından marj arındırılır.
  - Model ile geometrik olarak harmanlanır; ağırlık, oran arşivi yeterince birikince kendiliğinden kalibre olur.
  - EV = p × oran − 1.

## Kuponlar

- **Değer**, **Yüksek olasılık** ve **Dengeli** kuponlar üretilir.
- Yalnızca backtest'te doğrulanmış pazar aileleri kullanılır.
- Maç başına tek seçim yapılır ve MBS kuralı uygulanır.
- Değer yoksa kupon üretilmez.
- Her kupon arşivlenir. Maçlar bitince otomatik sonuçlandırılır ve gerçek isabet ile ROI **Performans** sayfasında izlenir.

## Spor Toto

- Her hafta iddaa Spor Toto servisinden 15 maç alınır; maçlar iddaa bülteni ve ESPN ile eşleştirilir.
- Maç olasılığı: model+oran harmanı → model → iddaa oranı (marjsız) → bilgi yoksa eşit (arayüzde uyarılır).
- Kupon **en fazla 3.000 TL** (`TOTO_BUDGET_TL`). Her maça 1, 2 ya da 3 işaret; kolon = Π işaret, maliyet = kolon × kolon bedeli.
  Bütçe ve kolon sınırı içinde 15'i de bilme olasılığını en büyüten seçim kesin DP ile bulunur.
- Kupon kapanıştan 1 saat önce kilitlenir; sonuç açıklanınca isabet, kazanan kolon sayıları (12–15) ve ikramiye
  `toto_coupons` tablosunda saklanır.
- Oynanma oranları (ikramiyenin paylaşımı) resmi kaynakta olmadığı için hesaba katılmaz.

## Bilinen sınırlar

- Kaynakta sakatlık ve ceza verisi yok. Son maçlarda kadroda görünmeyen oyuncular işaretlenir.
- Türkiye 1. Lig ESPN'de yok. Bu maçlar yalnızca piyasa olasılığıyla listelenir ve kupona alınmaz.
- iddaa bülteni oyuncu pazarı (gol atar, isabetli şut) yayınlamıyor. Oyuncu olasılıkları saf model çıktısıdır.
- Birbiriyle hiç maç yapmamış liglerin (ör. MLS ve Süper Lig) gücü yalnızca prior'a dayanır. Bu durumda güven "düşük" görünür.

## Geliştirme

```powershell
cd backend; .\.venv\Scripts\python.exe -m pytest        # model testleri
.\.venv\Scripts\python.exe -m app.jobs refresh           # elle tam güncelleme
.\.venv\Scripts\python.exe -m app.jobs backtest          # doğrulama + hiperparametre ayarı
cd ..\web; npx tsc --noEmit; npx eslint .; npm run build
```

> Olasılıklar istatistiksel tahmindir, kesinlik içermez. 18 yaş altı bahis oynayamaz.
