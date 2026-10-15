import Link from "next/link";
import { dateTime, relative } from "@/lib/format";
import { BackendError, getJSON, IS_STATIC } from "@/lib/server-api";
import type { StatusResponse } from "@/lib/types";

export default async function StatusPill() {
  let s: StatusResponse;
  try {
    s = await getJSON<StatusResponse>("/api/status");
  } catch (e) {
    const msg = e instanceof BackendError ? e.message : "Arka uç hatası";
    return (
      <Link href="/veri" title={msg} className="flex items-center gap-2 rounded-full border border-line px-3 py-1 text-xs text-critical-ink">
        <span className="h-2 w-2 rounded-full bg-critical" aria-hidden />
        Arka uç kapalı
      </Link>
    );
  }
  if (IS_STATIC) {
    return (
      <Link href="/veri" className="flex items-center gap-2 rounded-full border border-line px-3 py-1 text-xs text-ink-2 hover:bg-surface-2">
        <span className="h-2 w-2 rounded-full bg-good" aria-hidden />
        Güncellendi {dateTime(s.jobs.find((j) => j.status === "ok")?.finished_at ?? s.iddaa_last_fetch)}
      </Link>
    );
  }
  const running = s.running;
  const lastOk = s.jobs.find((j) => j.status === "ok" && (j.job === "refresh" || j.job === "odds" || j.job === "bootstrap"));
  return (
    <Link
      href="/veri"
      className="flex items-center gap-2 rounded-full border border-line px-3 py-1 text-xs text-ink-2 hover:bg-surface-2"
      title={running?.message ?? "Veri durumu"}
    >
      <span
        className={`h-2 w-2 rounded-full ${running ? "animate-pulse bg-warn" : "bg-good"}`}
        aria-hidden
      />
      {running ? `Güncelleniyor: ${running.job}` : `Oranlar ${relative(s.iddaa_last_fetch)} · model ${relative(lastOk?.finished_at)}`}
    </Link>
  );
}
