import { NextRequest, NextResponse } from 'next/server';

export function middleware(request: NextRequest) {
  const pathname = request.nextUrl.pathname;

  // Protect /analyze route
  if (pathname.startsWith('/analyze')) {
    const authToken = request.cookies.get('auth_token');
    const userInfo = request.cookies.get('user_info');

    if (!authToken || !userInfo) {
      return NextResponse.redirect(new URL('/login', request.url));
    }
  }

  return NextResponse.next();
}

export const config = {
  matcher: ['/analyze/:path*'],
};
