// Yalnızca sunucu tarafında kullanılır: arka uca yerel paylaşılan token ile istek atar.
// Tarayıcı arka uca doğrudan erişmez; istemci etkileşimleri /api/backend proxy'sinden geçer.
import { readFileSync } from "node:fs";
import path from "node:path";
import { connection } from "next/server";

export const BACKEND_URL = process.env.IDDAA_LAB_BACKEND ?? "http://127.0.0.1:8765";
/** Statik mod (GitHub Pages): veri derleme anında bu klasördeki JSON dosyalarından okunur (app.export_static). */
export const STATIC_DIR = process.env.IDDAA_STATIC_DIR ? path.resolve(process.env.IDDAA_STATIC_DIR) : null;
export const IS_STATIC = STATIC_DIR !== null;

// API yolu -> dışa aktarılan dosya
const STATIC_ROUTES: [RegExp, (m: RegExpMatchArray) => string][] = [
  [/^\/api\/matches\?/, () => "matches.json"],
  [/^\/api\/matches\/(\d{1,20})$/, (m) => `matches/${m[1]}.json`],
  [/^\/api\/coupons\?/, () => "coupons.json"],
  [/^\/api\/coupons\/history$/, () => "coupons_history.json"],
  [/^\/api\/players\/top/, () => "players_top.json"],
  [/^\/api\/performance$/, () => "performance.json"],
  [/^\/api\/status$/, () => "status.json"],
  [/^\/api\/coverage$/, () => "coverage.json"],
  [/^\/api\/live\/base$/, () => "live_base.json"],
];

function readStatic<T>(pathname: string): T {
  for (const [re, file] of STATIC_ROUTES) {
    const m = pathname.match(re);
    if (!m) continue;
    try {
      return JSON.parse(readFileSync(path.join(STATIC_DIR as string, file(m)), "utf-8")) as T;
    } catch {
      throw new BackendError(404, "Bu veri yayınlanan sürümde yok (maç kapsam dışında ya da güncelleme sonrası eklendi).");
    }
  }
  throw new BackendError(404, `Statik veride karşılığı olmayan yol: ${pathname}`);
}

/** Statik modda maç detay sayfalarının listesi (generateStaticParams). */
export function staticMatchIds(): string[] {
  if (!STATIC_DIR) return [];
  try {
    const d = JSON.parse(readFileSync(path.join(STATIC_DIR, "matches.json"), "utf-8")) as {
      items: { covered: boolean; match: { id: string } }[];
    };
    return d.items.filter((i) => i.covered).map((i) => i.match.id);
  } catch {
    return [];
  }
}
const TOKEN_FILE = path.resolve(process.cwd(), "..", "data", ".local_api_token");

export class BackendError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "BackendError";
    this.status = status;
  }
}

export function readToken(): string {
  try {
    const t = readFileSync(TOKEN_FILE, "utf-8").trim();
    if (t.length < 32) throw new BackendError(503, "Yerel API anahtarı geçersiz. Arka ucu yeniden başlatın.");
    return t;
  } catch (e) {
    if (e instanceof BackendError) throw e;
    throw new BackendError(
      503,
      "Arka uç henüz başlatılmamış (yerel API anahtarı bulunamadı). start.ps1 ile başlatın.",
    );
  }
}

async function parseError(res: Response): Promise<string> {
  try {
    const body: unknown = await res.json();
    if (body && typeof body === "object" && "detail" in body) {
      const d = (body as { detail: unknown }).detail;
      return typeof d === "string" ? d : JSON.stringify(d);
    }
  } catch {
    // gövde JSON değil: durum metnine düş
  }
  return `${res.status} ${res.statusText}`;
}

export async function backendRequest(pathname: string, init?: RequestInit): Promise<Response> {
  const token = readToken();
  try {
    return await fetch(`${BACKEND_URL}${pathname}`, {
      ...init,
      headers: { ...(init?.headers ?? {}), "X-Local-Token": token, Accept: "application/json" },
      cache: "no-store",
    });
  } catch {
    throw new BackendError(503, "Arka uca ulaşılamıyor (127.0.0.1:8765). Arka uç çalışıyor mu?");
  }
}

/** Sunucu bileşenlerinden veri. Canlı modda istek başına (mutlaka <Suspense> içinde); statik modda derleme anında. */
export async function getJSON<T>(pathname: string): Promise<T> {
  if (IS_STATIC) return readStatic<T>(pathname);
  await connection();
  const res = await backendRequest(pathname);
  if (!res.ok) throw new BackendError(res.status, await parseError(res));
  return (await res.json()) as T;
}
