export default function Home() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center p-8">
      <h1 className="text-4xl font-bold mb-4">Deliberate</h1>
      <p className="text-lg text-gray-600 mb-8">
        The approval layer for LangGraph agents
      </p>
      <a
        href="https://github.com/beomwookang/deliberate"
        className="text-blue-600 hover:underline"
        target="_blank"
        rel="noopener noreferrer"
      >
        View on GitHub
      </a>
    </main>
  );
}
