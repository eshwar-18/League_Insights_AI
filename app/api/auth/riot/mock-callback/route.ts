import { NextRequest, NextResponse } from 'next/server';

/**
 * Mock OAuth callback for development/testing
 * This simulates a successful OAuth flow without requiring Riot's approval
 * Once Riot approves your OAuth app, replace this with the real callback
 */
export async function GET(request: NextRequest) {
  const searchParams = request.nextUrl.searchParams;
  const state = searchParams.get('state');

  // Validate state parameter (CSRF protection)
  const storedState = request.cookies.get('oauth_state')?.value;
  if (!state || state !== storedState) {
    return NextResponse.redirect(
      new URL('/login?error=Invalid state parameter', request.url)
    );
  }

  try {
    // For development: Create mock summoner/user data
    const mockUserData = {
      id: 'mock_user_' + Math.random().toString(36).substring(7),
      username: 'TestPlayer',
      puuid: 'mock_puuid_' + Math.random().toString(36).substring(7),
    };

    const mockAccessToken = 'mock_token_' + Math.random().toString(36).substring(7);

    console.log('Mock OAuth: User authenticated:', mockUserData);

    // Create response and set session cookies
    const response = NextResponse.redirect(new URL('/analyze', request.url));

    // Set secure session cookie with token
    response.cookies.set('auth_token', mockAccessToken, {
      httpOnly: true,
      secure: process.env.NODE_ENV === 'production',
      sameSite: 'lax',
      maxAge: 60 * 60 * 24 * 7, // 7 days
    });

    // Store user info in a non-httpOnly cookie so client can access it
    response.cookies.set('user_info', JSON.stringify({
      id: mockUserData.id,
      username: mockUserData.username,
      puuid: mockUserData.puuid,
    }), {
      secure: process.env.NODE_ENV === 'production',
      sameSite: 'lax',
      maxAge: 60 * 60 * 24 * 7,
    });

    return response;
  } catch (error) {
    console.error('Mock OAuth callback error:', error);
    return NextResponse.redirect(
      new URL('/login?error=Authentication failed', request.url)
    );
  }
}
