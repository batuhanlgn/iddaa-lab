import type { Metadata } from "next";
import { Big_Shoulders, Instrument_Sans, JetBrains_Mono } from "next/font/google";
import { Suspense } from "react";
import Nav from "@/components/Nav";
import StatusPill from "@/components/StatusPill";
import "./globals.css";

const display = Big_Shoulders({ variable: "--font-bsd", subsets: ["latin", "latin-ext"], weight: ["600", "800", "900"] });
const body = Instrument_Sans({ variable: "--font-ins", subsets: ["latin", "latin-ext"] });
const mono = JetBrains_Mono({ variable: "--font-jbm", subsets: ["latin", "latin-ext"], weight: ["400", "600"] });

export const metadata: Metadata = {
  title: "iddaa·lab — maç analizi ve simülasyon",
  description: "Ücretsiz verilerle maç olasılıkları, oyuncu şut simülasyonu ve iddaa kupon analizi",
};

// Tema seçimini boyamadan önce uygula (yanıp sönmeyi önler); localStorage erişimi try/catch içinde.
const themeScript = `try{var t=localStorage.getItem("iddaa-lab-theme");if(t==="light"||t==="dark")document.documentElement.dataset.theme=t}catch(e){}`;

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="tr" className={`${display.variable} ${body.variable} ${mono.variable} h-full antialiased`} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body className="min-h-full flex flex-col">
        <Nav
          status={
            <Suspense fallback={<span className="skeleton inline-block h-6 w-40" />}>
              <StatusPill />
            </Suspense>
          }
        />
        <main className="mx-auto w-full max-w-[1320px] flex-1 px-4 pb-24 pt-6 sm:px-6">{children}</main>
        <footer className="mx-auto w-full max-w-[1320px] px-4 pb-10 sm:px-6">
          <div className="chalk-rule mb-4" />
          <p className="text-xs leading-relaxed text-muted">
            Veriler: ESPN (fikstür, sonuç, oyuncu istatistikleri) ve iddaa.com bülteni (oranlar) — ücretsiz, herkese açık
            kaynaklar. Olasılıklar istatistiksel model çıktısıdır; kesinlik içermez. Kupon önerileri yatırım tavsiyesi
            değildir. 18 yaş altı bahis oynayamaz; kaybetmeyi göze alamayacağınız parayla oynamayın.
          </p>
        </footer>
      </body>
    </html>
  );
}
