'use client';

import { useState, useEffect } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import Link from 'next/link';

export default function LoginPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [riotId, setRiotId] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Check for errors
  useEffect(() => {
    const errorParam = searchParams.get('error');
    if (errorParam) {
      setError(decodeURIComponent(errorParam));
    }
  }, [searchParams]);

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);

    try {
      if (!riotId.trim()) {
        setError('Please enter your Riot ID');
        setLoading(false);
        return;
      }

      // Call backend to verify account and get their data
      const response = await fetch('/api/auth/account', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ riotId: riotId.trim() }),
      });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.error || 'Failed to find account');
      }

      // Redirect to analyze page
      router.push('/analyze');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed');
      setLoading(false);
    }
  };

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
        <div className="max-w-md mx-auto bg-white/5 p-8 rounded-lg">
          <h1 className="text-3xl font-bold mb-2">Connect Your Account</h1>
          <p className="text-gray-300 mb-8">
            Log in with your Riot account to analyze your League season
          </p>

          {error && (
            <div className="mb-6 p-4 bg-red-500/20 border border-red-500 rounded-lg text-red-200">
              {error}
            </div>
          )}

          <form onSubmit={handleLogin} className="space-y-4">
            <input
              type="text"
              placeholder="Enter your Riot ID (e.g., PlayerName#NA1)"
              value={riotId}
              onChange={(e) => setRiotId(e.target.value)}
              disabled={loading}
              className="w-full px-4 py-3 rounded-lg bg-white/10 text-white placeholder-gray-400 border border-emerald-500/30 focus:outline-none focus:ring-2 focus:ring-emerald-400 disabled:opacity-50"
            />

            <button
              type="submit"
              disabled={loading}
              className="w-full bg-emerald-500 hover:bg-emerald-600 disabled:bg-gray-600 text-white px-6 py-3 rounded-lg font-semibold shadow-lg transition focus:outline-none focus:ring-2 focus:ring-emerald-400"
            >
              {loading ? 'Analyzing...' : 'Analyze My Season'}
            </button>
          </form>

          <p className="mt-6 text-xs text-gray-400">
            We use your Riot account to securely access your match history.{' '}
            <Link href="/privacy" className="underline hover:text-gray-300">
              Privacy Policy
            </Link>
          </p>

          <Link href="/" className="mt-4 text-emerald-300 hover:underline block text-sm">
            Back to home
          </Link>
        </div>
      </div>
    </main>
  );
}
