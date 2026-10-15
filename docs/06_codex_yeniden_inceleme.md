Dosyaları okudum; değiştirmedim. **15 test geçti**, ayrıca matematik kontrollerini ve bellek içi hata senaryolarını çalıştırdım.

1. **KAPANDI.** CSRF koruması ve GET’ten arşivlemenin kaldırılması uygulanmış.
2. **KAPANDI.** Eğitim ve sonuçlandırma `ft90_*` kullanıyor; bilinen uzatmalı maç doğru ayrıştırılıyor.
3. **KAPANDI.** Eğitim verisine üç saatlik gecikme uygulanıyor.
4. **KAPANDI.** Oyuncu değerlendirmesinde kullanılan NB `k`, değerlendirme öncesindeki dilimden geliyor.
5. **AÇIK:** Holdout bazı gerçek piyasa olasılığı değil, piyasaya uydurulmuş DC matrisi. Ayrıca `+0,002` log-loss kötüleşmesi kabul ediliyor. [blend.py:68](C:/iddaa-lab/backend/app/blend.py:68)
6. **AÇIK:** Kupon üretimi güncel etkinlik/oran tablolarını yeniden kontrol etmiyor. Pasif ve oranları silinmiş üç maçı eski tahminlerden kupona sokabildim. Özel kupon değerlendirmesi de tazelik kontrolünü kapatıyor. [coupons.py:53](C:/iddaa-lab/backend/app/coupons.py:53), [coupons.py:252](C:/iddaa-lab/backend/app/coupons.py:252)
7. **KAPANDI.** Eksik boyut döndürülmüyor; geçersiz MBS arşivlenmiyor.
8. **KAPANDI.** Eksik olay listesi artık doğrudan 0–0 İY sayılmıyor.
9. **KAPANDI.** KL hesabı ve normalize geometrik harman doğru; ortak matris olay tutarlılığını sağlıyor.
10. **AÇIK:** İmzada tahmin sürümü/olasılık yok. Aynı oranlarla olasılığı değiştirdiğimde aynı `archived_id`, arşivde **0,216**, yanıtta **0,343** kupon olasılığıyla döndü. [coupons.py:217](C:/iddaa-lab/backend/app/coupons.py:217)
11. **KAPANDI.** Çıkışlar uygun yedek sayısı ve beş değişiklikle sınırlandırılmış; kaleci korunuyor.
12. **KAPANDI.** `F|c` ağırlıkları ve Gamma posteriorunun `k/μ+uv` hızı doğru. Doğrudan olasılık toplamıyla örnekleme sonuçları uyuştu.

**Düzeltmelerin getirdiği üç yeni hata:**

- **`w=0` gerçek piyasaya dönmüyor.** [pipeline.py:186](C:/iddaa-lab/backend/app/model/pipeline.py:186): Piyasanın DC’ye izdüşümü kullanılıyor. Kendi içinde tutarlı bir piyasa örneğinde beraberlik **%19,82’den %26,74’e** çıktı; **4,505** oranda, sıfır model ağırlığıyla **+%20,45 EV** üretildi. Başarısız harmanda piyasaya dönüş güvencesi sağlanmıyor.

- **Yeni ağırlık eski tahminlere uygulanmış gibi onaylanıyor.** [jobs.py:77](C:/iddaa-lab/backend/app/jobs.py:77): Tahminler kalibrasyondan önce üretiliyor. İlk doğrulamada seçilen ağırlık örneğin `0` olsa bile, varsayılan `0,5` ile hesaplanmış seçimler yeni `validated=True` kapısından geçip arşivlenebiliyor.

- **Mevcut kurulumda geri doldurma önkoşulu eksik.** [jobs.py:84](C:/iddaa-lab/backend/app/jobs.py:84): Doğrudan `backtest` ve `odds`, `backfill_periods` çalıştırmıyor. Yerel veritabanında tamamlanmış **30.706 maçın tamamında `ft90` boş**; yeni eğitim filtresi hepsini eliyor ve model eğitimi hata veriyor. Önce başarılı bir `refresh` gerekiyor.