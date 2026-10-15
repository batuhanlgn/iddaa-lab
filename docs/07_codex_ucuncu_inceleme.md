15 test geçti; dosya ve veritabanına yazmadım.

- **5: KAPANDI.** Holdout bazı gerçek iddaa MS olasılığı; kabul koşulu toleranssız `<`.
- **“w=0”: KAPANDI.** `p_safe ≤ p_market`; sınanan piyasalarda sahte pozitif EV oluşmadı.
- **6: KAPANDI.** Aktiflik, canlılık, aynı güncel oran ve tazelik kontrolleri uygulanmış.
- **10: AÇIK.** [coupons.py:244](C:/iddaa-lab/backend/app/coupons.py:244) olasılığı dört ondalığa yuvarlıyor. Aynı sürüm/oranda `0,60001 → 0,60004` değişiminde aynı `archived_id` döndü; arşiv ve yanıt hâlâ farklılaşabiliyor.
- **Yeni-2: KAPANDI.** Kalibrasyon tahminden önce; `generate` eski ağırlıklı tahminleri eliyor.
- **Yeni-3: KAPANDI.** Üç iş de eğitimden önce `_prepare` çalıştırıyor.

Yeni gerçek hata:

- **[blend.py:52](C:/iddaa-lab/backend/app/blend.py:52): Kalibrasyon, kuponda kullanılan `p_safe` yerine matris harmanını doğruluyor.** Tutarlı piyasalardan kurulan 200 maçlık örnekte `validated=True`, `w=0` çıktı: holdout log-loss matris için **1,095**, gerçek piyasa için **1,528**, kullanılan `p_safe` için **1,742**. Piyasadan kötü kullanılan olasılık “doğrulanmış” sayılıyor.