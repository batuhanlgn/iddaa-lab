// İstemci bileşenleri için dar kapsamlı proxy: yalnızca izinli yollar, token sunucuda eklenir.
import type { NextRequest } from "next/server";
import { BackendError, backendRequest } from "@/lib/server-api";

// Yalnızca istemci bileşenlerinin gerçekten kullandığı yollar (sunucu bileşenleri arka uca doğrudan gider)
const GET_ALLOWED = [/^status$/];
const POST_ALLOWED = [/^refresh$/];

const LOCAL_HOST = /^(127\.0\.0\.1|localhost)(:\d+)?$/;

function isLocal(req: NextRequest): boolean {
  return LOCAL_HOST.test(req.headers.get("host") ?? "");
}

/** Durum değiştiren istekler için CSRF koruması: aynı yerel köken + JSON içerik türü (basit form gönderimi olamaz). */
function isTrustedMutation(req: NextRequest): boolean {
  const host = req.headers.get("host") ?? "";
  const origin = req.headers.get("origin");
  if (!origin) return false;
  let originHost: string;
  try {
    originHost = new URL(origin).host;
  } catch {
    return false;
  }
  if (originHost !== host || !LOCAL_HOST.test(originHost)) return false;
  const site = req.headers.get("sec-fetch-site");
  if (site && site !== "same-origin") return false;
  return (req.headers.get("content-type") ?? "").toLowerCase().startsWith("application/json");
}

async function forward(req: NextRequest, joined: string, method: "GET" | "POST"): Promise<Response> {
  const search = req.nextUrl.search;
  try {
    const res = await backendRequest(`/api/${joined}${search}`, {
      method,
      body: method === "POST" ? await req.text() : undefined,
      headers: method === "POST" ? { "Content-Type": "application/json" } : undefined,
    });
    const body = await res.text();
    return new Response(body, { status: res.status, headers: { "Content-Type": "application/json" } });
  } catch (e) {
    const status = e instanceof BackendError ? e.status : 502;
    const detail = e instanceof Error ? e.message : "Bilinmeyen proxy hatası";
    return Response.json({ detail }, { status });
  }
}

export async function GET(req: NextRequest, ctx: RouteContext<"/api/backend/[...path]">): Promise<Response> {
  if (!isLocal(req)) return Response.json({ detail: "Yalnızca yerel erişim" }, { status: 403 });
  const { path } = await ctx.params;
  const joined = path.join("/");
  if (!GET_ALLOWED.some((r) => r.test(joined))) return Response.json({ detail: "İzinli olmayan yol" }, { status: 404 });
  return forward(req, joined, "GET");
}

export async function POST(req: NextRequest, ctx: RouteContext<"/api/backend/[...path]">): Promise<Response> {
  if (!isLocal(req) || !isTrustedMutation(req)) return Response.json({ detail: "Güvenilmeyen istek kaynağı" }, { status: 403 });
  const { path } = await ctx.params;
  const joined = path.join("/");
  if (!POST_ALLOWED.some((r) => r.test(joined))) return Response.json({ detail: "İzinli olmayan yol" }, { status: 404 });
  return forward(req, joined, "POST");
}
