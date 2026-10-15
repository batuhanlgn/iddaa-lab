1. **YÜKSEK — [route.ts:38](C:/iddaa-lab/web/app/api/backend/[...path]/route.ts:38), [server-api.ts:52](C:/iddaa-lab/web/lib/server-api.ts:52)**  
   **Sorun:** Proxy yalnızca `Host` kontrol ediyor; isteğin kaynağını doğrulamadan backend token’ını ekliyor.  
   **Senaryo:** Localhost erişimine izin veren tarayıcıda saldırgan sayfa, `text/plain` formuyla geçerli JSON gönderip `/api/backend/refresh` üzerinden `backtest` başlatabilir. Proxy gövdeyi `application/json` olarak iletiyor.  
   **Düzeltme:** Değişiklik yapan isteklerde güvenilir `Origin`, içerik türü ve CSRF doğrulaması uygula; kupon arşivleyen GET’i de değişiklik yapan uç olarak ele al.

2. **YÜKSEK — [espn.py:178](C:/iddaa-lab/backend/app/sources/espn.py:178), [coupons.py:245](C:/iddaa-lab/backend/app/coupons.py:245)**  
   **Sorun:** Uzatma sonundaki skor normal süre skoru olarak eğitime, backtest’e ve kupon sonuçlandırmaya giriyor.  
   **Senaryo:** Yerel arşivde `401871356` maçının ilk iki devresi 1–1; uzatmayla 2–1 oluyor. Sistem MS beraberliği kayıp, ev galibiyetini kazanmış sayıyor.  
   **Düzeltme:** Doğrulanmış 90 dakika skorunu ayrı sakla; çıkarılamayan uzatmalı maçları ilgili eğitim ve sonuçlandırmadan dışla.

3. **YÜKSEK — [goals.py:37](C:/iddaa-lab/backend/app/model/goals.py:37), [players.py:86](C:/iddaa-lab/backend/app/model/players.py:86)**  
   **Sorun:** Tarihsel eğitim sınırı, sonucun bilinebildiği zamana değil başlama saatine uygulanıyor.  
   **Senaryo:** Gece 00.00’daki backtest kesiminde, önceki gün 23.30’da başlayan maçın nihai sonucu eğitimde bulunuyor; o anda maç henüz bitmemişti.  
   **Düzeltme:** Sonuç kullanılabilirlik/bitiş zamanıyla filtrele; bu zaman yoksa muhafazakâr bir gecikme uygula.

4. **YÜKSEK — [backtest.py:319](C:/iddaa-lab/backend/app/backtest.py:319), [pipeline.py:106](C:/iddaa-lab/backend/app/model/pipeline.py:106)**  
   **Sorun:** Oyuncu backtest’i gelecekteki veriden hesaplanan NB dağılım parametresini kullanıyor.  
   **Senaryo:** `tune_and_evaluate`, değerlendirme döneminin tamamından `aux_dispersion` yazıyor. Ardından `evaluate_players`, geçmiş haftalara ait `fit_all` çağrılarında aynı parametreyi okuyor; test edilen maçlar kendi tahminlerinin dağılımını etkiliyor.  
   **Düzeltme:** Her kesim için yalnızca önceki veriden hesaplanmış parametre kullan veya değerlendirme öncesinde sabitle.

5. **YÜKSEK — [blend.py:68](C:/iddaa-lab/backend/app/blend.py:68), [coupons.py:75](C:/iddaa-lab/backend/app/coupons.py:75)**  
   **Sorun:** Ortak karardaki bağımsız harman doğrulaması uygulanmıyor. Ağırlık bütün örneklerde seçiliyor; ayrı değerlendirme dilimi yok. Kupon kapısı da `blend_calibrated` durumunu kontrol etmiyor.  
   **Senaryo:** Gol ailesi doğrulanmışken hiç sonuçlanmış oran arşivi bulunmasa bile varsayılan `w=0.5` ile değer kuponu üretilebilir.  
   **Düzeltme:** Ağırlık, marj yöntemi ve seçim eşiğini geçmiş ayarlama diliminde seç; ayrı dilimde doğrulanmış harmanı kupona aç.

6. **YÜKSEK — [ingest.py:235](C:/iddaa-lab/backend/app/ingest.py:235)**  
   **Sorun:** Yeni bültenden kaldırılan etkinliklerin eski `odds_current` kayıtları aktif kalıyor. Sonraki tahmin ve kupon aşamalarında güncel bültende bulunma şartı aranmıyor.  
   **Senaryo:** Yarınki maç satıştan kaldırıldığında sonraki başarılı yenileme eski oranlarını silmiyor; sistem artık oynanamayan oranla kupon üretebiliyor. Bellekte yeniden üretildi.  
   **Düzeltme:** Her başarılı bülten için aktif etkinlik kümesini güncelle; kaldırılmış, canlı veya bayat oranları seçimden çıkar.

7. **YÜKSEK — [coupons.py:126](C:/iddaa-lab/backend/app/coupons.py:126), [coupons.py:149](C:/iddaa-lab/backend/app/coupons.py:149)**  
   **Sorun:** `_fit_mbs`, istenen sayıya ulaşamasa da kısmi liste döndürüyor; geçersiz kupon arşivleniyor.  
   **Senaryo:** Yalnızca bir uygun maç ve MBS=3 olduğunda yüksek olasılık kuponu tek seçimle dönüyor. `mbs_ok=False` olmasına rağmen arşive yazılıyor.  
   **Düzeltme:** Son seçim sayısı bütün seçimlerin MBS’sini sağlamıyorsa kuponu boş döndür ve arşivleme.

8. **YÜKSEK — [espn.py:333](C:/iddaa-lab/backend/app/sources/espn.py:333), [espn.py:365](C:/iddaa-lab/backend/app/sources/espn.py:365)**  
   **Sorun:** Eksik gol olayları, bilinen 0–0 ilk yarı sonucu olarak kaydediliyor.  
   **Senaryo:** Header’ın ilk yarıyı 1–0 verdiği, `keyEvents` listesinin boş olduğu yanıtta parser 0–0 döndürüyor. Bu sonuç İY doğrulamasını ve kupon sonuçlandırmasını yanlış etkiliyor.  
   **Düzeltme:** Doğrulanmış devre skorlarını kullan; olay kapsamı doğrulanamıyorsa ilk yarıyı `NULL` bırak.

9. **ORTA — [pipeline.py:195](C:/iddaa-lab/backend/app/model/pipeline.py:195)**  
   **Sorun:** Pazarlar ayrı harmanlanıyor; ortak kararda istenen örtüşen olay tutarlılığı denetlenmiyor.  
   **Senaryo:** Aynı skor modeli ve `w=0.5` ile yeniden üretimde `P(MS=1)=0.504342`, fakat `P(1 ve KG Var)+P(1 ve KG Yok)=0.549908` çıktı. Aynı olayın olasılığı seçilen pazara göre değişiyor.  
   **Düzeltme:** Pazarları ortak bir tutarlı dağılıma uzlaştır veya tutarsız pazarları EV/kupon hesabından çıkar.

10. **ORTA — [coupons.py:179](C:/iddaa-lab/backend/app/coupons.py:179)**  
    **Sorun:** Arşiv tekrar kontrolü oranları ve tahmin sürümünü içermiyor; yeni kupon eski kayda bağlanabiliyor.  
    **Senaryo:** Aynı seçimlerin oranı 2.00’dan 2.10’a değişince yanıtta 2.10 gösteriliyor, `archived_id` ise 2.00’lık kaydı gösteriyor. İleriye dönük getiri gösterilen kuponu izlemiyor.  
    **Düzeltme:** Değişen oran/tahmin için yeni arşiv kaydı oluştur; tekrar kullanılan kayıtta arşivdeki kuponun aynısını döndür.

11. **ORTA — [simulate.py:65](C:/iddaa-lab/backend/app/model/simulate.py:65), [simulate.py:80](C:/iddaa-lab/backend/app/model/simulate.py:80)**  
    **Sorun:** Oyuncu çıkışları bağımsız örnekleniyor, yerine girişler en fazla beş kişiyle sınırlanıyor; kadro bütünlüğü korunmuyor.  
    **Senaryo:** Altı ilk 11 oyuncusu 60’ta çıkarsa yalnızca beşi değiştiriliyor; kırmızı kart olmadan takım on kişi kalıyor. Kaleci çıkışında yerine saha oyuncusu da girebiliyor.  
    **Düzeltme:** Çıkış ve girişleri eşleşmiş değişiklikler olarak, değişiklik sınırı ve kaleci koşuluyla birlikte örnekle.

12. **ORTA — [simulate.py:162](C:/iddaa-lab/backend/app/model/simulate.py:162), [simulate.py:170](C:/iddaa-lab/backend/app/model/simulate.py:170)**  
    **Sorun:** Koşullu şut modelinin `u,v` değerleri her kadro senaryosundan hesaplanmıyor; bütün simülasyonların ortalama oyuncu ağırlıkları kullanılıyor.  
    **Senaryo:** Bitiriciliği yüksek forvetin oynadığı ve oynamadığı senaryolar aynı takım şut/SoT tablosundan çekiliyor. Kararlaştırılan kadroya ve skora koşullu dağılım kayboluyor.  
    **Düzeltme:** `u,v` değerlerini senaryo bazında hesapla; uygun önbellekleme veya gruplamayla koşullu tablodan örnekle.

**GENEL DEĞERLENDİRME**

Belirtilen dosyaları ve iki karar belgesini okudum; hiçbir dosyayı değiştirmedim. Mevcut 10 test geçti, ancak yukarıdaki hata senaryolarını kapsamıyorlar. Normal süre skorları ve zaman sızıntıları düzeltilmeden backtest sonuçlarına; harman, oran güncelliği ve MBS sorunları giderilmeden kuponların geçerliliğine güvenilmemeli. Proxy’nin kaynak doğrulaması da güvenlik açısından öncelikli.