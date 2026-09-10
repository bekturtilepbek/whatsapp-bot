import { cookies } from "next/headers";
import { API_INTERNAL_URL } from "@/lib/env";

// Единая точка входа для всех client-компонентов кабинета (FEATURES.md
// 6.18) — браузер больше не стучится в api напрямую. Читает session-cookie
// admin-web, форвардит на API_INTERNAL_URL с Authorization: Bearer, стримит
// ответ обратно. Работает и для multipart (загрузка фото товара) — тело не
// парсится, только форвардится с оригинальным Content-Type.

const HOP_BY_HOP_HEADERS = new Set([
  "connection",
  "keep-alive",
  "transfer-encoding",
  "content-length",
  "host",
]);

async function proxy(request: Request, path: string[]): Promise<Response> {
  const token = (await cookies()).get("session")?.value;
  if (!token) {
    return new Response(JSON.stringify({ detail: "not authenticated" }), {
      status: 401,
      headers: { "Content-Type": "application/json" },
    });
  }

  const url = new URL(request.url);
  const target = `${API_INTERNAL_URL}/${path.join("/")}${url.search}`;

  const headers = new Headers();
  request.headers.forEach((value, key) => {
    if (!HOP_BY_HOP_HEADERS.has(key.toLowerCase())) {
      headers.set(key, value);
    }
  });
  headers.set("Authorization", `Bearer ${token}`);

  const hasBody = request.method !== "GET" && request.method !== "HEAD";
  const upstream = await fetch(target, {
    method: request.method,
    headers,
    body: hasBody ? await request.arrayBuffer() : undefined,
  });

  const responseHeaders = new Headers();
  upstream.headers.forEach((value, key) => {
    if (!HOP_BY_HOP_HEADERS.has(key.toLowerCase())) {
      responseHeaders.set(key, value);
    }
  });

  return new Response(upstream.body, { status: upstream.status, headers: responseHeaders });
}

export async function GET(request: Request, { params }: { params: Promise<{ path: string[] }> }) {
  return proxy(request, (await params).path);
}
export async function POST(request: Request, { params }: { params: Promise<{ path: string[] }> }) {
  return proxy(request, (await params).path);
}
export async function PATCH(request: Request, { params }: { params: Promise<{ path: string[] }> }) {
  return proxy(request, (await params).path);
}
export async function DELETE(request: Request, { params }: { params: Promise<{ path: string[] }> }) {
  return proxy(request, (await params).path);
}
