'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';

interface UserInfo {
  puuid: string;
  gameName: string;
  tagLine: string;
}

export default function AnalyzePage() {
  const router = useRouter();
  const [userInfo, setUserInfo] = useState<UserInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // Get user info from cookie
    try {
      const userCookie = document.cookie
        .split('; ')
        .find((row) => row.startsWith('user_info='));

      if (userCookie) {
        const userJson = userCookie.split('=')[1];
        const decoded = JSON.parse(decodeURIComponent(userJson));
        console.log('User info from cookie:', decoded);
        setUserInfo(decoded);
      } else {
        setError('No user information found. Please log in again.');
        setTimeout(() => router.push('/login'), 2000);
      }
    } catch (err) {
      setError('Failed to load user information');
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [router]);

  const handleLogout = () => {
    // Clear cookies
    document.cookie = 'auth_token=; path=/; expires=Thu, 01 Jan 1970 00:00:00 UTC;';
    document.cookie = 'user_info=; path=/; expires=Thu, 01 Jan 1970 00:00:00 UTC;';
    router.push('/');
  };

  if (loading) {
    return (
      <main className="relative min-h-screen flex items-center justify-center text-center">
        <div
          className="absolute inset-0 bg-cover bg-center brightness-75"
          style={{ backgroundImage: "url('/rift-bg.jpg')" }}
          aria-hidden="true"
        />
        <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" aria-hidden="true" />
        <div className="relative z-10 text-white">
          <p className="text-xl">Loading...</p>
        </div>
      </main>
    );
  }

  return (
    <main className="relative min-h-screen flex items-center justify-center text-center">
      {/* Background */}
      <div
        className="absolute inset-0 bg-cover bg-center brightness-75"
        style={{ backgroundImage: "url('/rift-bg.jpg')" }}
        aria-hidden="true"
      />

      {/* Overlay */}
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" aria-hidden="true" />

      {/* Content */}
      <div className="relative z-10 text-white px-4">
        <div className="max-w-2xl mx-auto">
          <h1 className="text-4xl font-bold mb-8">Account Verified ✓</h1>

          {error ? (
            <div className="bg-red-500/20 border border-red-500 rounded-lg p-6 mb-8">
              <p className="text-red-200">{error}</p>
            </div>
          ) : userInfo ? (
            <div className="bg-white/5 border border-emerald-500/30 rounded-lg p-8 mb-8">
              <div className="space-y-6">
                <div className="bg-white/10 p-6 rounded-lg">
                  <p className="text-gray-300 text-sm mb-2">Game Name</p>
                  <p className="text-2xl font-bold text-emerald-400">
                    {userInfo.gameName}#{userInfo.tagLine}
                  </p>
                </div>

                <div className="bg-white/10 p-6 rounded-lg">
                  <p className="text-gray-300 text-sm mb-2">PUUID</p>
                  <p className="text-sm font-mono text-gray-300 break-all">{userInfo.puuid}</p>
                </div>

                <div className="bg-emerald-500/10 border border-emerald-500/30 p-6 rounded-lg">
                  <p className="text-emerald-300 mb-4">
                    ✓ Successfully authenticated with Riot Games
                  </p>
                  <p className="text-gray-300 text-sm">
                    Your account information has been retrieved and verified.
                  </p>
                </div>
              </div>
            </div>
          ) : null}

          <div className="flex gap-4 justify-center">
            <button
              onClick={handleLogout}
              className="bg-red-600 hover:bg-red-700 text-white px-6 py-3 rounded-lg font-semibold transition"
            >
              Logout
            </button>

            <Link
              href="/"
              className="bg-emerald-500 hover:bg-emerald-600 text-white px-6 py-3 rounded-lg font-semibold transition"
            >
              Back to Home
            </Link>
          </div>

          <p className="mt-8 text-gray-400 text-sm">
            Next: Build your analysis features here!
          </p>
        </div>
      </div>
    </main>
  );
}
