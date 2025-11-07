import { NextRequest, NextResponse } from 'next/server';

export async function GET(request: NextRequest) {
  const searchParams = request.nextUrl.searchParams;
  const code = searchParams.get('code');
  const state = searchParams.get('state');
  const error = searchParams.get('error');

  // Handle OAuth errors
  if (error) {
    const errorDescription = searchParams.get('error_description');
    return NextResponse.redirect(
      new URL(`/login?error=${encodeURIComponent(errorDescription || error)}`, request.url)
    );
  }

  // Validate state parameter (prevent CSRF)
  const storedState = request.cookies.get('oauth_state')?.value;
  if (!state || state !== storedState) {
    return NextResponse.redirect(
      new URL('/login?error=Invalid state parameter', request.url)
    );
  }

  if (!code) {
    return NextResponse.redirect(
      new URL('/login?error=No authorization code received', request.url)
    );
  }

  try {
    // Exchange authorization code for access token
    const tokenResponse = await fetch('https://auth.riotgames.com/oauth/token', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
      },
      body: new URLSearchParams({
        grant_type: 'authorization_code',
        code,
        redirect_uri: `${process.env.NEXT_PUBLIC_APP_URL}/api/auth/riot/callback`,
        client_id: process.env.NEXT_PUBLIC_RIOT_CLIENT_ID || '',
        client_secret: process.env.RIOT_CLIENT_SECRET || '',
      }),
    });

    if (!tokenResponse.ok) {
      const error = await tokenResponse.text();
      console.error('Token exchange failed:', error);
      return NextResponse.redirect(
        new URL('/login?error=Token exchange failed', request.url)
      );
    }

    const tokenData = await tokenResponse.json();
    const accessToken = tokenData.access_token;

    // Fetch account info from Riot using Account V1 API
    const accountResponse = await fetch(
      `https://americas.api.riotgames.com/riot/account/v1/accounts/me`,
      {
        headers: {
          Authorization: `Bearer ${accessToken}`,
        },
      }
    );

    if (!accountResponse.ok) {
      console.error('Failed to fetch account info');
      return NextResponse.redirect(
        new URL('/login?error=Failed to fetch account information', request.url)
      );
    }

    const accountData = await accountResponse.json();

    // TODO: Save user data to your database
    // Store: accountData.puuid, accountData.gameName, accountData.tagLine, accessToken, etc.
    console.log('User authenticated:', accountData);

    // Create response and set session cookie
    const response = NextResponse.redirect(new URL('/analyze', request.url));

    // Set secure session cookie with token
    response.cookies.set('auth_token', accessToken, {
      httpOnly: true,
      secure: process.env.NODE_ENV === 'production',
      sameSite: 'lax',
      maxAge: 60 * 60 * 24 * 7, // 7 days
    });

    // Store user info in a non-httpOnly cookie so client can access it
    response.cookies.set('user_info', JSON.stringify({
      puuid: accountData.puuid,
      gameName: accountData.gameName,
      tagLine: accountData.tagLine,
    }), {
      secure: process.env.NODE_ENV === 'production',
      sameSite: 'lax',
      maxAge: 60 * 60 * 24 * 7,
    });

    return response;
  } catch (error) {
    console.error('OAuth callback error:', error);
    return NextResponse.redirect(
      new URL('/login?error=Authentication failed', request.url)
    );
  }
}
