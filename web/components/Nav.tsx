import Link from "next/link";
import { Suspense, type ReactNode } from "react";
import NavLinks from "./NavLinks";
import ThemeToggle from "./ThemeToggle";

export default function Nav({ status }: { status: ReactNode }) {
  return (
    <header className="sticky top-0 z-40 border-b border-line bg-page/85 backdrop-blur-md">
      <div className="mx-auto flex w-full max-w-[1320px] items-center gap-4 px-4 py-3 sm:px-6">
        <Link href="/" className="group flex items-center gap-2.5" aria-label="iddaa·lab ana sayfa">
          <svg width="30" height="30" viewBox="0 0 30 30" aria-hidden className="shrink-0">
            <rect x="1" y="1" width="28" height="28" rx="7" fill="var(--accent)" />
            <circle cx="15" cy="15" r="6.5" fill="none" stroke="var(--accent-ink)" strokeWidth="1.6" />
            <line x1="15" y1="1" x2="15" y2="29" stroke="var(--accent-ink)" strokeWidth="1.6" />
            <circle cx="15" cy="15" r="1.6" fill="var(--accent-ink)" />
          </svg>
          <span className="font-display text-[1.55rem] font-black uppercase leading-none tracking-wide">
            iddaa<span className="text-accent">·</span>lab
          </span>
        </Link>
        <Suspense fallback={<span className="skeleton inline-block h-7 w-72" />}>
          <NavLinks />
        </Suspense>
        <div className="ml-auto flex items-center gap-2">
          <div className="hidden md:block">{status}</div>
          <ThemeToggle />
        </div>
      </div>
    </header>
  );
}
