"use client";

import { useRouter } from "next/navigation";
import { useTransition } from "react";

export default function ErrorPanel({ title = "Veri yüklenemedi", message, onRetry }: { title?: string; message: string; onRetry?: () => void }) {
  const router = useRouter();
  const [pending, start] = useTransition();
  return (
    <div role="alert" className="panel flex flex-col items-start gap-3 border-critical/40 px-5 py-5">
      <div className="flex items-center gap-2 text-critical-ink">
        <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden>
          <path d="M9 1.5 17 16H1L9 1.5Z" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
          <path d="M9 7v4M9 13v.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
        </svg>
        <p className="font-semibold">{title}</p>
      </div>
      <p className="text-sm text-ink-2">{message}</p>
      <button
        type="button"
        disabled={pending}
        onClick={() => (onRetry ? onRetry() : start(() => router.refresh()))}
        className="rounded-md border border-line-strong px-3 py-1.5 text-sm font-medium hover:bg-surface-2 disabled:opacity-60"
      >
        {pending ? "Yeniden deneniyor…" : "Tekrar dene"}
      </button>
    </div>
  );
}
