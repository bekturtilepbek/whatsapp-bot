import { NextResponse, type NextRequest } from "next/server";

// UX-гейт: реальная авторизация проверяется api на каждый запрос
// (require_bot_access/require_platform_owner, FEATURES.md 6.18) — баг или
// отсутствие здесь не открывает дыру, только портит UX (пустая страница
// вместо редиректа на /login, либо форма входа поверх сайдбара для уже
// залогиненного — Sidebar.tsx рендерится безусловно в app/layout.tsx и
// сам ничего не знает о текущем маршруте).
export function middleware(request: NextRequest): NextResponse {
  const hasSession = request.cookies.has("session");
  const isLoginPage = request.nextUrl.pathname === "/login";

  if (!hasSession && !isLoginPage) {
    const loginUrl = new URL("/login", request.url);
    return NextResponse.redirect(loginUrl);
  }

  if (hasSession && isLoginPage) {
    const botsUrl = new URL("/bots", request.url);
    return NextResponse.redirect(botsUrl);
  }

  return NextResponse.next();
}

export const config = {
  // brand/*, icon.png, apple-icon.png — статичные ассеты логотипа
  // (public/brand, app/icon.png, app/apple-icon.png): без сессии редирект
  // на /login возвращал HTML вместо картинки, логотип не грузился даже на
  // самой странице входа.
  matcher: [
    "/((?!api-proxy|_next/static|_next/image|favicon.ico|icon.png|apple-icon.png|brand/).*)",
  ],
};
