import Link from "next/link";

export default function NotFound() {
  return (
    <div className="panel mx-auto mt-10 flex max-w-xl flex-col items-start gap-3 p-6">
      <p className="kicker">404</p>
      <h1 className="font-display text-3xl font-black uppercase">Bulunamadı</h1>
      <p className="text-sm text-ink-2">
        Bu maç için tahmin yok: model kapsamı dışında olabilir, maç başlamış/bitmiş olabilir ya da henüz hesaplanmamıştır.
      </p>
      <Link href="/" className="rounded-md bg-accent px-3 py-1.5 text-sm font-semibold text-accent-ink">
        Bültene dön
      </Link>
    </div>
  );
}
