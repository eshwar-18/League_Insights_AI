import Link from 'next/link';

export const metadata = {
  title: 'Are You The Problem? - AI-powered LoL analysis',
  description:
    'AI-powered match analysis for League players — champion performance, role-specific tips, and practice drills from your season history.',
};

export default function Page() {
  return (
    <main className="relative min-h-screen flex items-center justify-center text-center">
      {/* Background (decorative) */}
      <div
        className="absolute inset-0 bg-cover bg-center brightness-75"
        style={{ backgroundImage: "url('/rift-bg.jpg')" }}
        aria-hidden="true"
      />

      {/* Overlay for readability */}
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" aria-hidden="true" />

      {/* Foreground content */}
      <div className="relative z-10 text-white px-4">
        <h1 className="text-4xl sm:text-6xl font-extrabold drop-shadow-lg">
          Are You The Problem?
        </h1>
        <p className="mt-4 text-lg sm:text-xl text-gray-200 max-w-xl mx-auto">
          AI-powered match analysis for League players — champion performance, role-specific tips, and practical
          drills from your season history.
        </p>

        <div className="mt-8 flex items-center justify-center gap-4">
          <Link
            href="/login"
            className="bg-emerald-500 hover:bg-emerald-600 text-white px-6 py-3 rounded-lg font-semibold shadow-lg transition focus:outline-none focus:ring-2 focus:ring-emerald-400"
            aria-label="Analyze my season"
          >
            Analyze My Season
          </Link>

          <a href="#how-it-works" className="text-emerald-300 hover:underline">
            How it works
          </a>
        </div>

        <section className="mt-12 grid gap-6 sm:grid-cols-3 max-w-4xl mx-auto" aria-label="Key features">
          <div className="bg-white/5 p-6 rounded-lg">
            <h3 className="text-lg font-semibold">Personalized Insights</h3>
            <p className="mt-2 text-sm text-gray-300">Understand your strengths and weaknesses across champions and roles.</p>
          </div>

          <div className="bg-white/5 p-6 rounded-lg">
            <h3 className="text-lg font-semibold">Champion Tips</h3>
            <p className="mt-2 text-sm text-gray-300">Build, rune, and laning advice tailored to your playstyle.</p>
          </div>

          <div className="bg-white/5 p-6 rounded-lg">
            <h3 className="text-lg font-semibold">Training Drills</h3>
            <p className="mt-2 text-sm text-gray-300">Short, actionable drills to improve your next games.</p>
          </div>
        </section>

        <section id="how-it-works" className="mt-12 text-left max-w-3xl mx-auto bg-white/5 p-6 rounded-lg" aria-label="How it works">
          <h2 className="text-2xl font-bold">How it works</h2>
          <ol className="mt-4 list-decimal list-inside text-gray-300">
            <li>Connect your Riot account securely.</li>
            <li>We analyze your match history & generate AI-driven insights.</li>
            <li>Receive personalized tips and practice drills to improve.</li>
          </ol>

          <p className="mt-4 text-xs text-gray-400">
            We only use your match data to generate insights. See our{' '}
            <Link href="/privacy" className="underline">
              Privacy Policy
            </Link>
            .
          </p>
        </section>
      </div>
    </main>
  );
}
