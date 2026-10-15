"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState, useTransition } from "react";
import { dateTime } from "@/lib/format";
import type { JobRun, StatusResponse } from "@/lib/types";

const JOB_LABEL: Record<string, string> = {
  bootstrap: "İlk kurulum",
  refresh: "Tam güncelleme",
  odds: "Oran güncelleme",
  backtest: "Backtest",
  ingest: "Veri indirme",
  iddaa: "iddaa bülteni",
};

const STATIC_MODE = process.env.NEXT_PUBLIC_STATIC_MODE === "1";
const REPO_URL = process.env.NEXT_PUBLIC_REPO_URL ?? "";

export default function JobControls({ initial }: { initial: StatusResponse }) {
  if (STATIC_MODE) return <StaticJobs status={initial} />;
  return <LiveJobControls initial={initial} />;
}

function StaticJobs({ status }: { status: StatusResponse }) {
  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
      <div className="panel flex flex-col gap-3 p-5">
        <p className="text-sm text-ink-2">
          Bu sürüm GitHub Actions ile 3 saatte bir kendiliğinden güncellenir (pazartesileri backtest de çalışır).
          Elle güncellemek için Actions sayfasında &quot;Run workflow&quot; düğmesini kullan.
        </p>
        {REPO_URL && (
          <a href={`${REPO_URL}/actions`} target="_blank" rel="noreferrer" className="self-start rounded-md bg-accent px-3 py-1.5 text-sm font-semibold text-accent-ink hover:opacity-90">
            GitHub Actions ↗
          </a>
        )}
        <dl className="grid grid-cols-2 gap-1 text-xs text-ink-2">
          <dt className="text-muted">Model sürümü</dt>
          <dd className="num truncate">{status.model_version ?? "–"}</dd>
          <dt className="text-muted">Son oran çekimi</dt>
          <dd className="num">{dateTime(status.iddaa_last_fetch)}</dd>
        </dl>
      </div>
      <JobTable jobs={status.jobs} />
    </div>
  );
}

function JobTable({ jobs }: { jobs: JobRun[] }) {
  return (
    <div className="panel overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="text-left text-xs text-muted">
          <tr>
            <th className="px-4 py-2 font-medium">İş</th>
            <th className="px-2 py-2 font-medium">Başlangıç</th>
            <th className="px-2 py-2 font-medium">Durum</th>
            <th className="px-4 py-2 font-medium">Mesaj</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line/60">
          {jobs.map((j) => (
            <tr key={j.id}>
              <td className="px-4 py-1.5">{JOB_LABEL[j.job] ?? j.job}</td>
              <td className="num px-2 py-1.5 text-xs text-ink-2">{dateTime(j.started_at)}</td>
              <td className={`px-2 py-1.5 text-xs ${j.status === "ok" ? "text-good-ink" : j.status === "error" ? "text-critical-ink" : "text-warn"}`}>
                {j.status === "ok" ? "✓ tamam" : j.status === "error" ? "✕ hata" : "● sürüyor"}
              </td>
              <td className="max-w-md truncate px-4 py-1.5 text-xs text-ink-2" title={j.message ?? ""}>
                {j.message}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function LiveJobControls({ initial }: { initial: StatusResponse }) {
  const router = useRouter();
  const [status, setStatus] = useState<StatusResponse>(initial);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [, startTransition] = useTransition();
  const running = status.running;

  // Çalışan iş varken 5 sn'de bir durumu yenile
  useEffect(() => {
    if (!running) return;
    const t = setInterval(async () => {
      try {
        const r = await fetch("/api/backend/status");
        if (!r.ok) return;
        const s = (await r.json()) as StatusResponse;
        setStatus(s);
        if (!s.running) startTransition(() => router.refresh());
      } catch {
        // geçici ağ hatası: bir sonraki turda tekrar denenir
      }
    }, 5000);
    return () => clearInterval(t);
  }, [running, router]);

  async function trigger(command: "refresh" | "odds" | "backtest") {
    setBusy(true);
    setMsg(null);
    try {
      const r = await fetch("/api/backend/refresh", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ command }),
      });
      const j = (await r.json()) as { started?: boolean; reason?: string; detail?: string };
      if (!r.ok) throw new Error(j.detail ?? `${r.status}`);
      if (j.started) {
        setMsg({ ok: true, text: `${JOB_LABEL[command]} başlatıldı.` });
        const s = await fetch("/api/backend/status");
        if (s.ok) setStatus((await s.json()) as StatusResponse);
      } else {
        setMsg({ ok: false, text: j.reason ?? "Başlatılamadı" });
      }
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : "İstek başarısız" });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
      <div className="panel flex flex-col gap-3 p-5">
        <p className="text-sm text-ink-2">
          Arka uç açıkken oranlar 30 dakikada, tam güncelleme 3 saatte bir kendiliğinden çalışır. Elle başlatmak için:
        </p>
        <div className="flex flex-wrap gap-2">
          <button type="button" disabled={busy || !!running} onClick={() => trigger("odds")} className="rounded-md border border-line-strong px-3 py-1.5 text-sm font-medium hover:bg-surface-2 disabled:opacity-50">
            Oranları güncelle
          </button>
          <button type="button" disabled={busy || !!running} onClick={() => trigger("refresh")} className="rounded-md bg-accent px-3 py-1.5 text-sm font-semibold text-accent-ink hover:opacity-90 disabled:opacity-50">
            Tam güncelleme
          </button>
          <button type="button" disabled={busy || !!running} onClick={() => trigger("backtest")} className="rounded-md border border-line-strong px-3 py-1.5 text-sm font-medium hover:bg-surface-2 disabled:opacity-50">
            Backtest çalıştır
          </button>
        </div>
        {running && (
          <div className="rounded-lg border border-warn/40 px-3 py-2 text-sm" aria-live="polite">
            <p className="flex items-center gap-2 font-medium text-warn">
              <span className="h-2 w-2 animate-pulse rounded-full bg-warn" aria-hidden />
              {JOB_LABEL[running.job] ?? running.job} çalışıyor · {dateTime(running.started_at)}
            </p>
            <p className="mt-1 text-ink-2">{running.message ?? "Başlıyor…"}</p>
          </div>
        )}
        {msg && (
          <p role="status" className={`text-sm ${msg.ok ? "text-good-ink" : "text-critical-ink"}`}>
            {msg.text}
          </p>
        )}
        <dl className="grid grid-cols-2 gap-1 text-xs text-ink-2">
          <dt className="text-muted">Model sürümü</dt>
          <dd className="num truncate">{status.model_version ?? "–"}</dd>
          <dt className="text-muted">Son oran çekimi</dt>
          <dd className="num">{dateTime(status.iddaa_last_fetch)}</dd>
        </dl>
      </div>
      <JobTable jobs={status.jobs} />
    </div>
  );
}
