import { NextRequest, NextResponse } from 'next/server';

export async function POST(request: NextRequest) {
  try {
    const { riotId } = await request.json();

    if (!riotId) {
      return NextResponse.json(
        { error: 'Riot ID is required' },
        { status: 400 }
      );
    }

    const apiKey = process.env.NEXT_PUBLIC_RIOT_API_KEY;
    if (!apiKey) {
      return NextResponse.json(
        { error: 'API key not configured' },
        { status: 500 }
      );
    }

    // Parse Riot ID (format: "gameName#tagLine")
    const [gameName, tagLine] = riotId.split('#');
    if (!gameName || !tagLine) {
      return NextResponse.json(
        { error: 'Invalid Riot ID format. Use: PlayerName#TAG' },
        { status: 400 }
      );
    }

    // Fetch account data from Riot API using Account V1
    const encodedGameName = encodeURIComponent(gameName.trim());
    const encodedTagLine = encodeURIComponent(tagLine.trim());
    
    const url = `https://americas.api.riotgames.com/riot/account/v1/accounts/by-riot-id/${encodedGameName}/${encodedTagLine}`;
    console.log('Fetching account from URL:', url);

    const accountResponse = await fetch(url, {
      headers: {
        'X-Riot-Token': apiKey,
      },
    });

    if (!accountResponse.ok) {
      if (accountResponse.status === 404) {
        return NextResponse.json(
          { error: 'Account not found. Check your Riot ID and try again.' },
          { status: 404 }
        );
      }
      throw new Error(`Riot API error: ${accountResponse.status}`);
    }

    const accountData = await accountResponse.json();

    // Create response and set session cookies
    const response = NextResponse.json({ success: true });

    // Log the data we received
    console.log('Account data from Riot API:', accountData);
    console.log('Storing in cookie:', {
      puuid: accountData.puuid,
      gameName: accountData.gameName,
      tagLine: accountData.tagLine,
    });

    // Set secure session cookie with API key
    response.cookies.set('auth_token', apiKey, {
      httpOnly: true,
      secure: process.env.NODE_ENV === 'production',
      sameSite: 'lax',
      maxAge: 60 * 60 * 24 * 7, // 7 days
    });

    // Store account info in a non-httpOnly cookie so client can access it
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
    console.error('Account lookup error:', error);
    return NextResponse.json(
      { error: 'Failed to fetch account data' },
      { status: 500 }
    );
  }
}
