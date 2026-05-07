import type { Config } from "tailwindcss";

// Note: Tailwind 4 auto-detects sources from the CSS entry point (@import "tailwindcss"
// in globals.css). The legacy `content` array is intentionally omitted.
const config: Config = {
  theme: { extend: {} },
  plugins: [],
};
export default config;
