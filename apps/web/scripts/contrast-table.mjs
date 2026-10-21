// Key-pair contrast table. node scripts/contrast-table.mjs [path/to/globals.css]
import { readFileSync } from "node:fs";
const p = process.argv[2] ?? new URL("../app/globals.css", import.meta.url);
const css = readFileSync(p, "utf8");
const tok = (b) => new Map([...b.matchAll(/(--color-[a-z0-9-]+)\s*:\s*(#[0-9a-fA-F]{6})\s*;/g)].map((m) => [m[1], m[2]]));
const light = tok(css.match(/@theme static\s*\{([\s\S]*?)\n\}/)[1]);
const db = [...css.matchAll(/:root\[data-theme="dark"\]\s*\{([^}]*)\}/g)].map((m) => m[1]).find((b) => b.includes("--color-canvas"));
const dark = new Map([...light, ...tok(db)]);
const f = (c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
const L = (h) => { const [r,g,b] = [1,3,5].map((i) => f(parseInt(h.slice(i,i+2),16)/255)); return .2126*r+.7152*g+.0722*b; };
const R = (a,b) => { const [x,y]=[L(a),L(b)].sort((p,q)=>q-p); return (x+.05)/(y+.05); };
const pairs = [
 ["Texto principal / canvas","ink","canvas",4.5],
 ["Texto principal / card","ink","surface",4.5],
 ["Texto secundario / canvas","ink-soft","canvas",4.5],
 ["Texto secundario / card","ink-soft","surface",4.5],
 ["Texto tenue (placeholder) / card","ink-faint","surface",4.5],
 ["Texto tenue / canvas","ink-faint","canvas",4.5],
 ["Btn primario (on-primary/primary)","on-primary","primary",4.5],
 ["Btn primario hover","on-primary","primary-hover",4.5],
 ["Btn acento (on-accent/accent)","on-accent","accent",4.5],
 ["Btn acento hover","on-accent","accent-hover",4.5],
 ["Enlace pino / canvas","primary-text","canvas",4.5],
 ["Enlace pino / card","primary-text","surface",4.5],
 ["Etiqueta ev_N (texto/tinte)","on-accent-tint","accent-tint",4.5],
 ["Etiqueta ev_N (borde/tinte) 1.4.11","accent-line","accent-tint",3],
 ["Badge Demo (texto/tinte)","accent-text","accent-tint",4.5],
 ["Eyebrow acento / canvas","accent-text","canvas",4.5],
 ["Borde de control / card 1.4.11","line-control","surface",3],
 ["Anillo de foco / canvas 1.4.11","focus","canvas",3],
 ["Anillo de foco / card 1.4.11","focus","surface",3],
 ["Banda: texto / banda","on-brand-band","brand-band",4.5],
 ["Banda: texto suave / banda","on-brand-band-soft","brand-band",4.5],
 ["Error texto / tinte","error-text","error-tint",4.5],
 ["Separación card vs canvas (borde)","line","canvas",1.0],
];
const out=[];
for (const [n,a,b,min] of pairs) { const r=[light,dark].map(m=>R(m.get("--color-"+a),m.get("--color-"+b))); out.push(`| ${n} | ${min} | ${r[0].toFixed(2)} | ${r[1].toFixed(2)} |`);}
console.log("| Par | mín | claro | oscuro |\n|---|---|---|---|\n"+out.join("\n"));
