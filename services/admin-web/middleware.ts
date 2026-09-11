import { NextResponse, type NextRequest } from "next/server";

// UX-гейт: реальная авторизация проверяется api на каждый запрос
// (require_bot_access/require_platform_owner, FEATURES.md 6.18) — баг или
// отсутствие здесь не открывает дыру, только портит UX (пустая страница
// вместо редиректа на /login).
export function middleware(request: NextRequest): NextResponse {
  const hasSession = request.cookies.has("session");
  if (!hasSession && request.nextUrl.pathname !== "/login") {
    const loginUrl = new URL("/login", request.url);
    return NextResponse.redirect(loginUrl);
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!login|api-proxy|_next/static|_next/image|favicon.ico).*)"],
};
