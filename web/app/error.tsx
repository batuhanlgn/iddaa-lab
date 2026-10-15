"use client";

export default function Error({ error, retry }: { error: Error & { digest?: string }; retry: () => void }) {
  return (
    <div role="alert" className="panel mx-auto mt-10 flex max-w-xl flex-col items-start gap-3 p-6">
      <p className="kicker">Beklenmeyen hata</p>
      <h1 className="font-display text-3xl font-black uppercase">Sayfa yüklenemedi</h1>
      <p className="text-sm text-ink-2">{error.message || "Bilinmeyen bir hata oluştu."}</p>
      {error.digest && <p className="num text-xs text-muted">Kod: {error.digest}</p>}
      <button type="button" onClick={() => retry()} className="rounded-md bg-accent px-3 py-1.5 text-sm font-semibold text-accent-ink">
        Tekrar dene
      </button>
    </div>
  );
}
