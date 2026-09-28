import { cookies } from "next/headers";
import { NextResponse } from "next/server";

// api ответил 401 на серверный запрос (apiFetch, lib/api.ts) — cookie
// "session" была прислана, но api её не принял (просрочен/невалиден JWT).
// Стереть cookie можно только здесь: у Server Component нет доступа к
// cookies().delete() при рендере (Next 15). Без этого шага middleware.ts
// увидит cookie как формально присутствующую и отобьёт /login обратно на
// /bots ("hasSession && isLoginPage" — редирект в бесконечный цикл).
export async function GET(request: Request): Promise<NextResponse> {
  (await cookies()).delete("session");
  // request.url в Route Handler (в отличие от middleware) резолвится через
  // адрес, на котором слушает сервер (0.0.0.0 в dev/проде — see
  // "next dev/start -H 0.0.0.0"), а не через Host, который прислал клиент
  // — редирект на "http://0.0.0.0:3000/login" недостижим ни из браузера,
  // ни из-за reverse-proxy. Собираем адрес из заголовка Host самостоятельно.
  const host = request.headers.get("host") ?? "localhost";
  const protocol = request.headers.get("x-forwarded-proto") ?? "http";
  return NextResponse.redirect(`${protocol}://${host}/login`);
}
