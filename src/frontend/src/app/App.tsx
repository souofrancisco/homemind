import { useEffect, useState } from "react";
import { getHealth, type Health } from "../api/health";

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    getHealth().then(setHealth).catch(() => setError(true));
  }, []);

  return (
    <main className="mx-auto max-w-xl p-6">
      <h1 className="text-2xl font-bold">HomeMind Spaces</h1>
      <p className="mt-2" role="status">
        {error ? "Backend indisponível" : health ? `Backend ${health.status} · modo ${health.mode}` : "A carregar…"}
      </p>
    </main>
  );
}
