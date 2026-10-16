"use client";

import { useMemo, useState } from "react";
import { relative } from "@/lib/format";
import type { LeagueStandings } from "@/lib/types";
import StandingsTable from "./StandingsTable";
import { SectionTitle } from "./ui";

const DEFAULT_LEAGUE = "tur.1";

export default function StandingsBoard({ leagues }: { leagues: LeagueStandings[] }) {
  const fallback = leagues.find((l) => l.slug === DEFAULT_LEAGUE)?.slug ?? leagues[0].slug;
  const [slug, setSlug] = useState<string>(fallback);

  const byCountry = useMemo(() => {
    const m = new Map<string, LeagueStandings[]>();
    leagues.forEach((l) => m.set(l.country, [...(m.get(l.country) ?? []), l]));
    return [...m.entries()];
  }, [leagues]);

  const league = leagues.find((l) => l.slug === slug) ?? leagues[0];

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center gap-3">
        <label htmlFor="league" className="kicker">
          Lig
        </label>
        <select
          id="league"
          value={league.slug}
          onChange={(e) => setSlug(e.target.value)}
          className="min-w-0 max-w-full rounded-md border border-line bg-surface px-3 py-2 text-sm"
        >
          {byCountry.map(([country, ls]) => (
            <optgroup key={country} label={country}>
              {ls.map((l) => (
                <option key={l.slug} value={l.slug}>
                  {l.country} · {l.name}
                </option>
              ))}
            </optgroup>
          ))}
        </select>
        <span className="text-xs text-muted">
          {league.season ?? ""} · güncellendi {relative(league.fetched_at)}
        </span>
      </div>

      {league.groups.map((g) => (
        <section key={g.name} className="panel rise p-4 sm:p-5">
          <SectionTitle right={<span className="kicker">{g.entries.length} takım</span>}>
            {league.groups.length > 1 ? g.name : `${league.country} · ${league.name}`}
          </SectionTitle>
          <StandingsTable entries={g.entries} />
        </section>
      ))}
    </div>
  );
}
