import { ImageResponse } from "next/og";

import es from "@/messages/es.json";
import en from "@/messages/en.json";
import fr from "@/messages/fr.json";

// Branded social card, generated at request time — no binary asset to maintain.
// Mirrors the "calidez clínica" palette: pine authority + honey accent on cream.
export const alt = "AdelIA — tu vault médico personal con IA y evidencia";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

const MESSAGES = { es, en, fr } as const;
type Locale = keyof typeof MESSAGES;

export default async function OpengraphImage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  const m = MESSAGES[(locale as Locale) in MESSAGES ? (locale as Locale) : "es"];
  const eyebrow = m.home.eyebrow;
  const hero = m.home.hero;
  const proofLabel = m.home.proofLabel;

  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          padding: "72px 80px",
          backgroundColor: "#0a2820",
          backgroundImage:
            "radial-gradient(1100px 700px at 12% -10%, #115443 0%, transparent 60%), radial-gradient(900px 600px at 108% 8%, rgba(196,134,43,0.28) 0%, transparent 55%)",
          color: "#f3f7f3",
          fontFamily: "sans-serif",
        }}
      >
        {/* Top: eyebrow */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 14,
            color: "#d99f43",
            fontSize: 26,
            fontWeight: 600,
            letterSpacing: 2,
            textTransform: "uppercase",
          }}
        >
          <div style={{ width: 40, height: 4, background: "#c4862b", borderRadius: 4 }} />
          {eyebrow}
        </div>

        {/* Middle: wordmark + tagline */}
        <div style={{ display: "flex", flexDirection: "column", gap: 28 }}>
          <div style={{ display: "flex", fontSize: 92, fontWeight: 800, letterSpacing: -2 }}>
            <span>Adel</span>
            <span style={{ color: "#d99f43" }}>IA</span>
          </div>
          <div
            style={{
              display: "flex",
              maxWidth: 880,
              fontSize: 44,
              lineHeight: 1.15,
              fontWeight: 600,
              color: "#e9f1ec",
            }}
          >
            {hero}
          </div>
        </div>

        {/* Bottom: evidence chip + url */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 16,
              fontSize: 24,
              color: "#a9cdbd",
            }}
          >
            <div
              style={{
                display: "flex",
                alignItems: "center",
                padding: "8px 16px",
                background: "rgba(196,134,43,0.16)",
                border: "1px solid rgba(217,159,67,0.5)",
                borderRadius: 10,
                color: "#eed6a6",
                fontSize: 22,
                fontWeight: 600,
              }}
            >
              {proofLabel}  ·  ev_1
            </div>
          </div>
          <div style={{ display: "flex", fontSize: 26, color: "#a9cdbd", fontWeight: 600 }}>
            adelia.godi.ai
          </div>
        </div>
      </div>
    ),
    size,
  );
}
