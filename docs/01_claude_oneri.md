Sen bu projede Claude'un ORTAĞISIN (eşit söz hakkı). Salt-okur moddasın; kod yazmayacaksın, mimari kararları birlikte veriyoruz. Türkçe cevap ver, net ve maddeli ol. Katılmadığın her yerde gerekçeyle itiraz et ve alternatif öner.

## Proje
Kullanıcı (Türk, iddaa oynuyor) şunu istiyor: tüm maçları analiz eden, iddaa kuponu çıkaran, oyuncuların isabetli şut vb. atabileceklerini varsayarak maçları SİMÜLE eden ve web arayüzünde görselleştiren bir sistem. ÜCRETLİ API YOK, sadece ücretsiz kaynak. Windows 11, Python 3.12, Node 24 kurulu. Kullanıcı stack tercihi: Next.js 14+ / TypeScript strict / Tailwind. Placeholder/mock veri YASAK, gerçek veri.

## Veri kaynağı - Claude test etti, ÇALIŞIYOR (anahtar yok):
- https://site.api.espn.com/apis/site/v2/sports/soccer/{lig}/scoreboard  (?dates=YYYYMMDD) -> fikstür/sonuç. tur.1, eng.1 vs.
- .../summary?event={id} -> rosters[].roster[] oyuncu stats: appearances, subIns, totalShots, shotsOnTarget, totalGoals, goalAssists, foulsCommitted, foulsSuffered, yellowCards, redCards, offsides, saves, shotsFaced. starter bayrağı + pozisyon. boxscore takım stats: totalShots, shotsOnTarget, wonCorners, possessionPct, yellowCards, fouls, saves... keyEvents (gol dakikaları, değişiklikler, kartlar). odds/pickcenter: DraftKings moneyline + O/U 2.5 (Amerikan format, her ligde olmayabilir).
- football-data.co.uk bu makineden erişilemedi (timeout). Understat 200 dönüyor (xG, sadece top5+RPL).
- Oyuncu DAKİKA verisi doğrudan yok; starter + keyEvents'teki değişiklik dakikalarından türetilebilir.

## Claude'un önerisi
1. Backend: Python (FastAPI + numpy/scipy/pandas + SQLite cache). Ingest: son 2 sezon + güncel sezon, ligler: tur.1, tur.2?, eng.1, esp.1, ita.1, ger.1, fra.1, ned.1, por.1, uefa.champions, uefa.europa, uefa.europa.conf. Summary'ler bir kere çekilip cache'lenir (bitmiş maç değişmez). Rate-limit: nazik (~4 req/s), retry/backoff.
2. Model:
   a. Takım gol modeli: lig bazında Dixon-Coles (zaman ağırlıklı, ξ~0.0019/gün), ev sahibi avantajı, düşük skor düzeltmesi rho. Avrupa kupaları için takımın kendi lig rating'i + lig gücü katsayısı.
   b. Şut modeli: takım şut ~ NegBin(log-lineer: hücum şut üretimi × rakip şut izni × ev). İsabetli şut = şut × isabet oranı (takım, shrinkage).
   c. Oyuncu: dakika-başı şut payı (team shot share) Beta/Dirichlet shrinkage pozisyon önceliğiyle; SoT oranı beta-binomial pozisyon prior; gol dönüşümü SoT başına shrinkage. Beklenen kadro: son maçlardaki starter sıklığı + dakika.
   d. Korner, kart: takım bazlı Poisson/NegBin rate'ler (rakip+hakem yok).
3. Monte Carlo (maç başı 20k): Gol(DC) -> takım şut/SoT gol ile tutarlı olsun diye: önce takım SoT örnekle, sonra gol | SoT binom? YA DA gol DC'den, SoT >= gol koşullu. (Burada fikrini istiyorum: tutarlılık nasıl sağlanmalı?) Oyunculara şut dağıtımı multinomial (dakika-ağırlıklı payla), golcü = SoT'lar arasından dönüşümle. İY/MS için gol dakikaları (lig gol dakikası dağılımından).
4. Pazarlar: 1X2, ÇŞ, Alt/Üst 0.5-4.5, KG Var/Yok, handikap, İY/MS, İY 1X2, tek/çift, toplam korner A/Ü, kart A/Ü, oyuncu gol atar, oyuncu 1+/2+ isabetli şut, oyuncu 2+/3+ şut, skor tahmini.
5. Kupon motoru: her pazarın adil oranı = 1/p. Piyasa oranı varsa (ESPN DraftKings) edge = p*oran-1. Kupon tipleri: "Banko" (p>=0.75 seçimler, 3-4 maç), "Değer" (edge>0, Kelly kesirli), "Sürpriz" (yüksek oran). Maç başına tek seçim (korelasyon), toplam olasılık = çarpım; kupon olasılık & beklenen değer gösterilir. iddaa resmi oranlarını çekmek: iddaa.com'un public JSON endpoint'i var mı bilmiyoruz, opsiyonel.
6. Backtest: walk-forward (her hafta öncesi fit), log-loss/Brier/kalibrasyon grafiği, ROI (DraftKings oranları olan maçlarda). UI'da "Model performansı" sayfası.
7. Frontend Next.js: /  (günün/haftanın maçları, 1X2 bar, A/Ü, KG, en olası skor), /mac/[id] (skor ısı haritası, gol dağılımı, oyuncu tablosu: P(1+ SoT), P(gol), beklenen şut; tek bir simülasyonun dakika-dakika saha üzerinde 'replay' animasyonu + olay akışı), /kuponlar, /performans, /ligler. Backend localhost:8000, frontend 3000. Tek komutla başlatma (start.ps1). Günlük güncelleme: scheduled task veya uygulama açılınca stale ise refresh.

## Senden istediğim
1. Bu mimaride YANLIŞ veya riskli gördüklerin (özellikle istatistik modeli, gol-şut tutarlılığı, oyuncu dakika tahmini, Avrupa kupaları, veri boyutu/rate-limit).
2. Simülasyonda gol/şut/SoT tutarlılığı için senin önerdiğin generative süreç (net formül).
3. Kupon motorunda korelasyon ve 'Banko' tanımına itirazın.
4. Ücretsiz iddaa oranı kaynağı biliyorsan söyle (bilmiyorsan uydurma).
5. Kapsam: MVP'de neyi kesmeliyiz, neyi asla kesmemeliyiz.
6. Sonunda "ORTAK KARAR" başlığıyla kısa bir nihai karar listesi ver.
