# Ortak Karar (Claude ↔ Codex) — v1

Codex'in eleştirisi (02) kabul edildi, aşağıdaki farklarla:

## Yeni bulgu: iddaa'nın kendi ücretsiz oran JSON'u çalışıyor
`https://sportsbookv2.iddaa.com/sportsbook/events?st=1&type=0&version=0` → ~1170 futbol maçı, anahtar yok.
Alanlar: i (event id), hn/an (ev/dep), d (epoch), ci (yarışma id → /sportsbook/competitions), mbc (MBS), m[] pazarlar (t, st, sov, o[]: no, odd, n).
Çözülen pazar kodları (t,st): (1,1) MS 1X2 · (2,88) İY 1X2 · (2,36) 2.Y 1X2 · (2,92) ÇŞ · (2,77) İY ÇŞ · (2,89) KG · (2,720) İY KG
(2,101) MS A/Ü (sov) · (2,60) İY A/Ü · (2,603) Ev gol A/Ü · (2,604) Dep gol A/Ü · (2,100) Handikap (sov = ev sahibine eklenen gol)
(2,90) İY/MS · (2,91) Tek/Çift · (2,4) Toplam gol aralığı · (2,6) Daha çok gol olan yarı · (2,7) MS&A/Ü2.5 · (2,698) MS&KG · (2,700) A/Ü2.5&KG · (2,48) Korner A/Ü
→ Oranlar her yenilemede zaman damgalı arşivlenir. DraftKings/Bet365 (ESPN) oranları iddaa oranı olarak SUNULMAZ, kullanılmaz.

## Model
- Takım gol modeli: TEK ortak hiyerarşik Poisson + DC rho. λ = exp(μ_yarışma + ev_yarışma + att_ev − def_dep).
  att_t ~ N(A_lig(t), σ²), A_lig ~ N(0, τ²) (def için aynı). Avrupa kupaları ve küme düşen/çıkan takımlar ligleri birbirine bağlar.
  Zaman ağırlığı ξ ve σ walk-forward doğrulamayla seçilir (sabit değil). Az veri / zayıf lig bağlantısı → "düşük güven" etiketi.
- Skor pazarları DC skor matrisinden analitik. İY pazarları: FT skorun binom inceltmesi (p1 = ligin 1. yarı gol oranı, ESPN gol dakikalarından) — FT dağılımı aynen korunur.
- Şut/SoT/oyuncu: Codex süreci birebir: (C_H,C_A) ~ DC; P(S,T,F,O | F+O=c) ∝ NB(S)·Bin(T;S,u)·Bin(F;T,v)·Pois(O;ω); oyunculara gol / golsüz SoT / isabetsiz şut ayrı multinomial.
- Kadro: geçerli ilk 11 (1 kaleci + 10) Gumbel-top-k ile, çıkış dakikaları oyuncunun geçmiş dağılımından, girenler yedek eğilimiyle; resmi kadro açıklandıysa sabitlenir. Kırmızı kart sonrası 1 maç dışarıda. Sakatlık verisi yok → açıkça yazılır.
- Korner: aynı sayım-modeli altyapısıyla, "deneysel" etiketli. Kart: yok (hakem verisi yok).

## Kupon
- Kupon üretimi KALIR (kullanıcının ana talebi) ama: "Banko" adı yok; Kelly yok; değer yoksa "bugün değer kuponu yok".
- Seçim olasılığı = model ile piyasa (iddaa, marj arındırılmış) log-odds harmanı; EV = p·oran − 1, eşik + marj payı.
- Maç başına tek seçim; MBS kuralına uyulur; kupon olasılığı "bağımsızlık varsayımıyla" etiketli.
- Üretilen her kupon zaman damgasıyla arşivlenir, sonuçlanınca ileriye dönük ROI izlenir.

## Kapsam
- ESPN ligleri: tur.1, tur.2, eng.1, eng.2, esp.1, ita.1, ger.1, fra.1, ned.1, por.1, bel.1, sco.1, uefa.champions, uefa.europa, uefa.europa.conf
- iddaa'daki tüm futbol maçları listelenir; model kapsamı dışındakiler yalnızca piyasa olasılığıyla, açıkça etiketli.
- Lig/sezon veri kapsam raporu UI'da. Walk-forward backtest (log-loss/Brier/kalibrasyon, baz: lig ortalaması & basit Poisson).
- Animasyon yok; "modelden örnek senaryo" etiketli dakika-dakika olay akışı (saha koordinatı uydurulmaz).
