import type { PickStatus } from "@/lib/live-model";

const STYLE: Record<PickStatus, { cls: string; icon: string }> = {
  bekliyor: { cls: "border-line text-muted", icon: "○" },
  tutuyor: { cls: "border-good/40 text-good-ink", icon: "●" },
  tutmuyor: { cls: "border-critical/40 text-critical-ink", icon: "●" },
  tuttu: { cls: "border-good bg-good/15 text-good-ink", icon: "✓" },
  yattı: { cls: "border-critical bg-critical/10 text-critical-ink", icon: "✕" },
  "takip yok": { cls: "border-line text-muted", icon: "–" },
};

const LABEL: Record<PickStatus, string> = {
  bekliyor: "başlamadı",
  tutuyor: "şu an tutuyor",
  tutmuyor: "şu an tutmuyor",
  tuttu: "tuttu",
  yattı: "yattı",
  "takip yok": "takip yok",
};

export default function StatusChip({ status }: { status: PickStatus }) {
  const s = STYLE[status];
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[0.68rem] font-semibold ${s.cls}`}>
      <span aria-hidden>{s.icon}</span>
      {LABEL[status]}
    </span>
  );
}
