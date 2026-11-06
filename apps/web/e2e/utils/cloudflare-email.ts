import type { BrowserContext } from "@playwright/test";

// What Cloudflare's Email Address Obfuscation (Scrape Shield, on by default
// for a proxied zone) does to every HTML response of adelia.godi.ai, played
// in the test browser because no local server sits behind Cloudflare.
//
// Production threw React #418 ("server rendered text didn't match the
// client") on every visit to /dashboard/settings, the only panel screen that
// prints the account email, while local runs were clean (prod journey
// 2026-11-06). Cloudflare had swapped the address in the HTML for
//   <a href="/cdn-cgi/l/email-protection" class="__cf_email__"
//      data-cfemail="…">[email protected]</a>
// plus a decode script, so React found a link, or after decoding three text
// nodes, where it had rendered one.
//
// Modelled on the documented behaviour
// (developers.cloudflare.com/waf/tools/scrape-shield/email-address-obfuscation):
// addresses in visible text are replaced; <head>, <script>, <noscript>,
// <textarea> and attributes are left alone; a response carrying
// `Cache-Control: no-transform` is not touched at all. The decode script is
// our own minimal equivalent of email-decode.min.js: it replaces each link
// with a text node and removes itself.

export const DECODE_SCRIPT_PATH = "/cdn-cgi/scripts/5c5dd728/cloudflare-static/email-decode.min.js";

const EMAIL = /[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}/g;
// Segments Cloudflare does not scan: whole raw-text or skipped elements, and
// every tag (its attributes) on its own.
const SKIPPED = new RegExp(
  [
    "<head[\\s>][\\s\\S]*?</head>",
    "<script[\\s>][\\s\\S]*?</script>",
    "<style[\\s>][\\s\\S]*?</style>",
    "<noscript[\\s>][\\s\\S]*?</noscript>",
    "<textarea[\\s>][\\s\\S]*?</textarea>",
    "<!--[\\s\\S]*?-->",
    "<[^>]*>",
  ].join("|"),
);

function encode(email: string): string {
  const key = 0x5a;
  const hex = (n: number) => n.toString(16).padStart(2, "0");
  return hex(key) + [...email].map((c) => hex(c.charCodeAt(0) ^ key)).join("");
}

export function obfuscateEmails(html: string): { html: string; count: number } {
  let count = 0;
  const parts = html.split(new RegExp(`(${SKIPPED.source})`, "gi"));
  const out = parts.map((part, i) => {
    // split() with one capture group alternates text, skipped, text, ...
    if (i % 2 === 1) return part;
    return part.replace(EMAIL, (email) => {
      count += 1;
      return (
        `<a href="/cdn-cgi/l/email-protection" class="__cf_email__" ` +
        `data-cfemail="${encode(email)}">[email&#160;protected]</a>`
      );
    });
  });
  let result = out.join("");
  if (count > 0) {
    const tag = `<script data-cfasync="false" src="${DECODE_SCRIPT_PATH}"></script>`;
    result = result.includes("</body>") ? result.replace("</body>", `${tag}</body>`) : result + tag;
  }
  return { html: result, count };
}

const DECODE_SCRIPT = `(function () {
  var links = document.querySelectorAll("a.__cf_email__");
  for (var i = 0; i < links.length; i++) {
    var a = links[i], data = a.getAttribute("data-cfemail");
    if (!data) continue;
    var key = parseInt(data.substr(0, 2), 16), out = "";
    for (var j = 2; j < data.length; j += 2) {
      out += String.fromCharCode(parseInt(data.substr(j, 2), 16) ^ key);
    }
    a.parentNode.replaceChild(document.createTextNode(out), a);
  }
  var me = document.currentScript;
  if (me && me.parentNode) me.parentNode.removeChild(me);
})();`;

/**
 * Put the context behind a simulated Cloudflare edge. `seen` collects every
 * HTML document that went through it, `rewritten` those that had at least one
 * address replaced. The context must block service workers
 * (`test.use({ serviceWorkers: "block" })`): once public/sw.js controls the
 * page it fetches navigations itself and Playwright's routes never see them.
 */
export async function behindCloudflareEmailObfuscation(context: BrowserContext) {
  const seen: string[] = [];
  const rewritten: string[] = [];
  await context.route(`**${DECODE_SCRIPT_PATH}`, (route) =>
    route.fulfill({ status: 200, contentType: "application/javascript", body: DECODE_SCRIPT }),
  );
  await context.route("**/*", async (route) => {
    const request = route.request();
    if (request.resourceType() !== "document") return route.fallback();
    const response = await route.fetch();
    const headers = response.headers();
    seen.push(request.url());
    const type = headers["content-type"] ?? "";
    if (!type.includes("text/html") || /no-transform/i.test(headers["cache-control"] ?? "")) {
      return route.fulfill({ response });
    }
    const { html, count } = obfuscateEmails(await response.text());
    if (count > 0) rewritten.push(request.url());
    delete headers["content-length"];
    delete headers["content-encoding"];
    return route.fulfill({ response, headers, body: html });
  });
  return { seen, rewritten };
}
