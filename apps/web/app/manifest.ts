import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "AdelIA — Tu vault médico personal",
    short_name: "AdelIA",
    description: "Tu historia clínica, tuya. Análisis IA en 2 modos.",
    start_url: "/",
    display: "standalone",
    background_color: "#f4f1e9",
    theme_color: "#0a2820",
    icons: [
      { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png" },
      { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png" },
      {
        src: "/icons/icon-512-maskable.png",
        sizes: "512x512",
        type: "image/png",
        purpose: "maskable",
      },
    ],
  };
}
