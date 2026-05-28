"use client";

import { useEffect, useState } from "react";

import { API_URL } from "@/lib/api-client";
import { auth } from "@/lib/auth";

interface LinkResponse {
  bot_url: string;
  link_token: string;
  instructions: string;
}

export default function TelegramLinkPage() {
  const [data, setData] = useState<LinkResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  async function fetchLink() {
    try {
      const session = await auth();
      const token = (session as { jwt?: string } | null)?.jwt;
      const res = await fetch(`${API_URL}/ingestion/telegram/link`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        cache: "no-store",
      });
      if (!res.ok) throw new Error(`telegram/link: ${res.status}`);
      setData(await res.json());
    } catch (e) {
      setError(String(e));
    }
  }

  useEffect(() => {
    fetchLink();
  }, []);

  async function copyCommand() {
    if (!data) return;
    await navigator.clipboard.writeText(`/start ${data.link_token}`);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <main className="mx-auto max-w-2xl px-6 py-10">
      <h1 className="text-2xl font-semibold">💬 Enlazar Telegram</h1>
      <p className="mt-1 text-sm text-slate-600">
        Reenvía PDFs, fotos y audios médicos al bot y se ingestan automáticamente.
      </p>

      {error && (
        <div className="mt-4 rounded border border-red-300 bg-red-50 p-3 text-sm text-red-800">
          {error}
        </div>
      )}

      {data && (
        <div className="mt-6 space-y-4">
          <ol className="space-y-3 text-sm">
            <li>
              <span className="font-medium">1.</span>{" "}
              <a
                href={data.bot_url}
                target="_blank"
                rel="noopener"
                className="text-blue-700 underline"
              >
                Abrir bot en Telegram ({data.bot_url})
              </a>
            </li>
            <li>
              <span className="font-medium">2.</span> Pulsa "Start" o envía:
              <div className="mt-2 flex items-center gap-2 rounded border border-slate-300 bg-slate-50 px-3 py-2 font-mono text-xs">
                <code className="break-all">/start {data.link_token}</code>
                <button
                  type="button"
                  onClick={copyCommand}
                  className="rounded bg-slate-900 px-2 py-1 text-white"
                >
                  {copied ? "✅" : "Copy"}
                </button>
              </div>
              <p className="mt-1 text-xs text-slate-500">
                Token expira en 1 hora. Si tarda, refresca esta página para generar uno nuevo.
              </p>
            </li>
            <li>
              <span className="font-medium">3.</span> Una vez enlazado, reenvía
              cualquier PDF/foto/audio al bot. Lo procesará automáticamente.
            </li>
          </ol>
        </div>
      )}
    </main>
  );
}
