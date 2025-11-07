import { NextRequest, NextResponse } from 'next/server';
import crypto from 'crypto';

export async function GET(request: NextRequest) {
  try {
    // Generate state parameter for CSRF protection
    const state = crypto.randomBytes(32).toString('hex');

    // Create response and set state cookie
    const response = new NextResponse(null, { status: 307 });

    // Set state cookie (httpOnly for security)
    response.cookies.set('oauth_state', state, {
      httpOnly: true,
      secure: process.env.NODE_ENV === 'production',
      sameSite: 'lax',
      maxAge: 60 * 10, // 10 minutes
    });

    // For development: Use mock callback if we don't have valid OAuth credentials yet
    if (!process.env.NEXT_PUBLIC_RIOT_CLIENT_ID || process.env.NEXT_PUBLIC_RIOT_CLIENT_ID === '775762') {
      // Use mock callback for testing
      const mockUrl = new URL(`${process.env.NEXT_PUBLIC_APP_URL}/api/auth/riot/mock-callback`);
      mockUrl.searchParams.set('code', 'mock_code_' + Math.random().toString(36).substring(7));
      mockUrl.searchParams.set('state', state);
      response.headers.set('Location', mockUrl.toString());
      return response;
    }

    // Build real Riot OAuth authorization URL (when OAuth is approved)
    const authUrl = new URL('https://auth.riotgames.com/oauth/authorize');
    authUrl.searchParams.set('response_type', 'code');
    authUrl.searchParams.set('client_id', process.env.NEXT_PUBLIC_RIOT_CLIENT_ID);
    authUrl.searchParams.set('redirect_uri', `${process.env.NEXT_PUBLIC_APP_URL}/api/auth/riot/callback`);
    authUrl.searchParams.set('state', state);
    authUrl.searchParams.set('scope', 'openid');

    response.headers.set('Location', authUrl.toString());
    return response;
  } catch (error) {
    console.error('OAuth initiation error:', error);
    return NextResponse.redirect(
      new URL('/login?error=Failed to initiate authentication', request.url)
    );
  }
}
