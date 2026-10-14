import type { Metadata } from "next";
import { getLocale, getTranslations } from "next-intl/server";
import { Link } from "@/lib/navigation";
import { LocaleSwitcher } from "@/components/locale-switcher";
import {
  ArrowRight,
  ArrowUpRight,
  ShieldCheck,
  Quote,
  MessagesSquare,
  Stethoscope,
  Code2,
  ScrollText,
  Server,
  KeyRound,
  FileText,
  Check,
  X,
  BookMarked,
  Sparkles,
  Baby,
  Mic,
  UploadCloud,
  ClipboardList,
  Send,
  Clock,
} from "lucide-react";

import { FunnelVisit, StartLink } from "@/components/funnel";
import { LandingFold } from "@/components/landing-fold";
import { getCorpusStats } from "@/lib/corpus-stats";
import { publicPageAlternates } from "@/lib/seo";

// Rendered per request, never frozen at build time: the corpus figures come
// from the API (GET /clinical/corpus-stats), which is not running during
// `next build`, and a page prerendered without them would stay that way.
export const dynamic = "force-dynamic";

const GITHUB_URL = "https://github.com/santiagopatinoserna/AdelIA";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "home" });
  return {
    description: t("metaDescription"),
    alternates: publicPageAlternates(locale, ""),
  };
}

// Inline citation markers as they come out of the product: "[ev_N]" is an
// evidence citation (guideline/study), "[N]" points at the baby's own record.
// Both render as the same tags the app uses, so the copy stays verbatim.
function cited(text: string) {
  return text.split(/(\[(?:ev_)?\d+\])/g).map((part, i) => {
    if (/^\[ev_\d+\]$/.test(part)) {
      return (
        <span key={i} className="ad-ev-tag align-middle">
          {part.slice(1, -1)}
        </span>
      );
    }
    if (/^\[\d+\]$/.test(part)) {
      return (
        <span
          key={i}
          className="rounded-[0.4rem] border border-primary-tint-line bg-primary-tint px-1.5 font-mono text-[0.7rem] font-semibold text-primary-text align-middle"
        >
          {part}
        </span>
      );
    }
    return part;
  });
}

/*
 * What a phone gets, and why (below `md`; from `md` up the page is unchanged).
 *
 * Measured 2026-10-14 at 390x844: 11,936 CSS px of scroll (about 14 screens)
 * and a six-to-seven line h1 that pushed "Ver la demo sin cuenta" past the
 * fold. The reader is a mother, often at night, often with the baby in one
 * arm. Three things have to reach her, in this order, and every section was
 * judged by which of them it carries:
 *
 *   (a) what AdelIA is, in a sentence;
 *   (b) the proof that it does not invent answers, which is what separates it
 *       from a generic chatbot;
 *   (c) a way to try it without an account.
 *
 * SURVIVE on a phone (always visible):
 *   1. Hero: h1, one supporting paragraph and two buttons, all inside the first
 *      844 px. (a) and (c): "Ver la demo sin cuenta" is the lowest-friction path
 *      the product has, so it is on the first screen, whole.
 *   2. The proof card inside the hero (a real question, a cited answer, the
 *      guideline it came from). (b), in one glance and directly under the buttons.
 *   3. #evidence, "Cada respuesta nace de un estudio": (b) in words and numbers.
 *      It is the one place that states the refusal ("si ninguno respalda tu
 *      pregunta, lo dice en vez de inventar"), which is the product's rule. It
 *      is followed by one more "Ver la demo sin cuenta" so the mother who has
 *      read the proof has the way in under her thumb (c).
 *
 * FOLDED behind "Ver más" (still in the HTML, one tap away):
 *   - #day: the page's signature on a desktop, and 2,397 px on a phone, the
 *     longest block. It illustrates, it does not prove.
 *   - #features: three claims that the hero, the proof card and #evidence have
 *     already made, shorter.
 *   - #how (modes A and B) and #story (timeline): they explain the product to
 *     someone who has decided to look closer, not to someone deciding whether to.
 *   - the comparison with a generic chatbot: it repeats the proof card at 1,438 px.
 *   - the open-source band: matters to the people who self-host, not to the
 *     first minute of a mother's visit.
 *   - #pricing: what a mother needs before paying, not before trying. The
 *     trial note ("sin tarjeta") is a tap away and the demo asks for no card.
 *
 * Also dropped on a phone only: the eyebrow (a second line of small print above
 * the h1, saying what the h1 and the paragraph already say), the "Ver cómo
 * funciona" button (its target is folded; two buttons is what fits), and the
 * header's "Empezar" (the hero carries the same action on the same screen).
 *
 * The footer stays whole: it carries the clinical disclaimer and the privacy
 * and terms links, which are not optional on a health product.
 *
 * Nothing was deleted and no i18n key was dropped: this is hierarchy and
 * visibility. #evidence is rendered twice (a phone copy ahead of the fold, the
 * desktop copy in its original place), because moving it earlier would reorder
 * the desktop narrative and reordering with CSS would split the reading order
 * from the focus order. Only one copy is ever displayed, and only the desktop
 * copy carries the id. Spec: 44 px touch floor and the amber focus ring come
 * from `.ad-btn` and `:focus-visible`; no colour, token or dark-mode rule is
 * touched here.
 */
export default async function HomePage() {
  const t = await getTranslations();
  const locale = await getLocale();
  const stats = await getCorpusStats();
  const features = [
    { icon: ShieldCheck, title: t("home.feature1Title"), body: t("home.feature1Body") },
    { icon: Quote, title: t("home.feature2Title"), body: t("home.feature2Body") },
    { icon: MessagesSquare, title: t("home.feature3Title"), body: t("home.feature3Body") },
  ];
  const briefingRows = [
    { label: t("home.modeBDemoS1Label"), body: t("home.modeBDemoS1") },
    { label: t("home.modeBDemoS2Label"), body: t("home.modeBDemoS2") },
    { label: t("home.modeBDemoS3Label"), body: t("home.modeBDemoS3") },
  ];
  const ossChips = [
    { icon: ScrollText, label: t("home.ossChip1") },
    { icon: Server, label: t("home.ossChip2") },
    { icon: KeyRound, label: t("home.ossChip3") },
  ];
  const timeline = [
    { age: t("home.mixT1Age"), event: t("home.mixT1") },
    { age: t("home.mixT2Age"), event: t("home.mixT2") },
    { age: t("home.mixT3Age"), event: t("home.mixT3") },
    { age: t("home.mixT4Age"), event: t("home.mixT4") },
    { age: t("home.mixT5Age"), event: t("home.mixT5") },
  ];
  // The figures are counted by the API in the database retrieval searches
  // (audit 1.1); the catalogs hold only the words around them. Without an
  // answer the tiles are left out and the table cell falls back to a sentence
  // with no number, so the page can be incomplete but never wrong.
  const number = new Intl.NumberFormat(locale);
  const hasRange = stats !== null && stats.year_min !== null && stats.year_max !== null;
  const evStats =
    stats === null
      ? []
      : [
          { value: number.format(stats.sources), label: t("home.evStat1L") },
          { value: number.format(stats.chunks), label: t("home.evStat2L") },
          ...(hasRange
            ? [{ value: `${stats.year_min}–${stats.year_max}`, label: t("home.evStat3L") }]
            : []),
        ];
  const corpusCell =
    stats !== null && hasRange
      ? t("home.vsR5A", {
          count: stats.sources,
          from: String(stats.year_min),
          to: String(stats.year_max),
        })
      : t("home.vsR5AFallback");
  // Institutions that stand behind at least one source in the corpus files.
  // tests/test_evidence_files.py fails when one of these names has no source
  // behind it, so the page cannot name an institution the corpus lacks.
  // "OMS" is "WHO" in English.
  const evOrgs = [
    "NICE",
    "American Academy of Pediatrics",
    locale === "en" ? "WHO" : "OMS",
    "Asociación Española de Pediatría",
    "AEPap",
    "NASPGHAN-ESPGHAN",
    "Santé publique France",
  ];
  const vsRows = [
    { l: t("home.vsR1L"), g: t("home.vsR1G"), a: t("home.vsR1A") },
    { l: t("home.vsR2L"), g: t("home.vsR2G"), a: t("home.vsR2A") },
    { l: t("home.vsR3L"), g: t("home.vsR3G"), a: t("home.vsR3A") },
    { l: t("home.vsR4L"), g: t("home.vsR4G"), a: t("home.vsR4A") },
    { l: t("home.vsR5L"), g: t("home.vsR5G"), a: corpusCell },
  ];
  const tiers = [
    {
      name: t("home.prT1Name"), price: t("home.prT1Price"), cadence: t("home.prT1Cad"),
      desc: t("home.prT1Desc"), cta: t("home.prT1Cta"), href: GITHUB_URL, external: true,
      highlight: false, devTag: t("home.prT1DevTag"),
      features: [t("home.prT1F1"), t("home.prT1F2"), t("home.prT1F3"), t("home.prT1F4")],
    },
    {
      name: t("home.prT2Name"), price: t("home.prT2Price"), cadence: t("home.prT2Cad"),
      desc: t("home.prT2Desc"), cta: t("home.prT2Cta"), href: "/billing", external: false,
      highlight: true, badge: t("home.prT2Badge"),
      trialNote: t("home.prT2Trial"),
      features: [t("home.prT2F1"), t("home.prT2F2"), t("home.prT2F3"), t("home.prT2F4")],
    },
  ];
  // There used to be a third tier here: "Con especialista", 16 EUR/month, a
  // monthly review by a paediatric specialist. Nothing behind it existed —
  // config.py declares ONE stripe_price_id and billing.py builds the checkout
  // with it, so the button (href "/dashboard") walked a buyer to the 8 EUR
  // plan while the card said 16, and no specialist was under contract at any
  // fee written down anywhere. That is advertising a service that does not
  // exist, with a real charge for a different one, in a health product for
  // babies. Removed rather than repriced (audit 4.10): it comes back the day
  // there is a paediatrician on contract, a Price of its own, professional
  // liability cover and a page saying who performs the clinical act.

  // "A day with AdelIA": one real day, one artefact per step. Every artefact
  // is either generated by the product (tag "generated") or an illustrative
  // example (tag "example"); the wording of the Telegram bot bubbles is the
  // bot's own (services/telegram_diary.py MSG).
  const dayTag = (kind: "example" | "generated") => (
    <span
      className={
        kind === "generated"
          ? "rounded-full border border-primary-tint-line bg-primary-tint px-2 py-0.5 text-[10px] font-medium text-primary-text"
          : "rounded-full border border-line-strong bg-surface-2 px-2 py-0.5 text-[10px] font-medium text-ink-soft"
      }
    >
      {kind === "generated" ? t("home.day.generatedTag") : t("home.day.exampleTag")}
    </span>
  );
  const dayChips = [
    { name: t("home.day.s2C1Name"), value: t("home.day.s2C1Value"), date: t("home.day.s2C1Date") },
    { name: t("home.day.s2C2Name"), value: t("home.day.s2C2Value"), date: t("home.day.s2C2Date") },
    { name: t("home.day.s2C3Name"), value: t("home.day.s2C3Value"), date: t("home.day.s2C3Date") },
  ];
  const dayBullets = [t("home.day.s3B1"), t("home.day.s3B2"), t("home.day.s3B3"), t("home.day.s3B4")];
  const dayBriefingRows = [
    { label: t("home.day.s5R1Label"), body: t("home.day.s5R1") },
    { label: t("home.day.s5R2Label"), body: t("home.day.s5R2") },
    { label: t("home.day.s5R3Label"), body: t("home.day.s5R3") },
  ];
  const daySteps = [
    {
      time: t("home.day.s1Time"),
      title: t("home.day.s1Title"),
      lead: t("home.day.s1Lead"),
      icon: Send,
      tone: "pine" as const,
      tag: "example" as const,
      artifact: (
        <div className="flex flex-col gap-2">
          <div className="flex justify-end">
            <div className="inline-flex max-w-[92%] flex-col gap-1 rounded-2xl rounded-br-md bg-primary px-3 py-2 text-xs text-on-primary">
              <span className="flex items-center gap-2">
                <Mic className="h-3.5 w-3.5 shrink-0" strokeWidth={2.2} />
                <span aria-hidden className="flex items-end gap-[2px]">
                  {[3, 6, 4, 8, 5, 7, 3, 5, 6, 4, 3, 5].map((h, k) => (
                    <span key={k} className="w-[2px] rounded-full bg-on-primary/80" style={{ height: h * 2 }} />
                  ))}
                </span>
              </span>
              <span className="font-mono text-[10px] text-on-primary/85">{t("home.day.s1Voice")}</span>
            </div>
          </div>
          <div className="flex justify-start">
            <div className="max-w-[95%] rounded-2xl rounded-bl-md border border-line bg-surface px-3 py-2 text-xs leading-relaxed text-ink shadow-soft">
              <span className="block">{t("home.day.s1BotHeard")}</span>
              <span className="block italic text-ink-soft">{t("home.day.s1Snippet")}</span>
              <span className="mt-1.5 block font-medium text-primary-text">{t("home.day.s1BotSaved")}</span>
              <span className="block text-ink-soft">
                {t("home.day.s1BotLink")}{" "}
                <span className="underline decoration-primary-tint-line underline-offset-2">{t("home.day.s1BotLinkLabel")}</span>
              </span>
            </div>
          </div>
        </div>
      ),
    },
    {
      time: t("home.day.s2Time"),
      title: t("home.day.s2Title"),
      lead: t("home.day.s2Lead"),
      icon: UploadCloud,
      tone: "pine" as const,
      tag: "example" as const,
      artifact: (
        <div>
          <div className="flex items-center gap-2 text-xs font-medium text-ink-soft">
            <UploadCloud className="h-3.5 w-3.5 text-primary-text" strokeWidth={2.2} />
            {t("home.day.s2Count")}
          </div>
          <ul className="mt-2.5 flex flex-col gap-1.5">
            {dayChips.map((c) => (
              <li
                key={c.name}
                className="flex flex-wrap items-baseline gap-x-1.5 rounded-lg border border-line bg-surface-2 px-2.5 py-1.5 text-xs"
              >
                <span className="font-semibold text-ink">{c.name}</span>
                <span aria-hidden className="text-ink-soft">·</span>
                <span className="text-ink">{c.value}</span>
                <span aria-hidden className="text-ink-soft">·</span>
                <span className="font-mono text-[11px] text-ink-soft">{c.date}</span>
              </li>
            ))}
          </ul>
        </div>
      ),
    },
    {
      time: t("home.day.s3Time"),
      title: t("home.day.s3Title"),
      lead: t("home.day.s3Lead"),
      icon: Mic,
      tone: "pine" as const,
      tag: "example" as const,
      artifact: (
        <div>
          <div className="flex items-center justify-between gap-2">
            <span className="ad-eyebrow">{t("home.day.s3Essentials")}</span>
            <Mic className="h-4 w-4 text-primary-text" strokeWidth={2} />
          </div>
          <ul className="mt-2.5 flex flex-col gap-1.5 text-xs leading-snug text-ink">
            {dayBullets.map((b) => (
              <li key={b} className="flex gap-2">
                <span aria-hidden className="mt-[0.45em] h-1.5 w-1.5 shrink-0 rounded-full bg-primary-text" />
                {b}
              </li>
            ))}
          </ul>
          <p className="mt-3 border-t border-line pt-2 font-mono text-[11px] leading-snug text-ink-soft">
            {t("home.day.s3Speakers")}
          </p>
          <p className="font-mono text-[11px] leading-snug text-ink-soft">{t("home.day.s3Retention")}</p>
        </div>
      ),
    },
    {
      time: t("home.day.s4Time"),
      title: t("home.day.s4Title"),
      lead: t("home.day.s4Lead"),
      icon: Sparkles,
      tone: "pine" as const,
      tag: "example" as const,
      artifact: (
        <div className="flex flex-col gap-2">
          <div className="flex justify-end">
            <div className="max-w-[92%] rounded-2xl rounded-br-md bg-primary px-3 py-2 text-xs leading-relaxed text-on-primary">
              {t("home.day.s4Q")}
            </div>
          </div>
          <div className="flex justify-start">
            <div className="rounded-2xl rounded-bl-md border border-line bg-surface px-3 py-2 text-xs leading-relaxed text-ink shadow-soft">
              {cited(t("home.day.s4A"))}
              <span className="mt-2 block border-t border-line pt-1.5 font-mono text-[10px] leading-snug text-ink-soft">
                {t("home.day.s4Src1")}
              </span>
            </div>
          </div>
        </div>
      ),
    },
    {
      time: t("home.day.s5Time"),
      title: t("home.day.s5Title"),
      lead: t("home.day.s5Lead"),
      icon: ClipboardList,
      tone: "honey" as const,
      tag: "example" as const,
      artifact: (
        <div>
          <div className="flex items-center justify-between gap-2">
            <span className="ad-eyebrow !text-accent-text">{t("home.day.s5Eyebrow")}</span>
            <FileText className="h-4 w-4 text-accent-text" strokeWidth={2} />
          </div>
          <p className="mt-1 font-mono text-[11px] text-ink-soft">{t("home.day.s5Meta")}</p>
          <dl className="mt-2.5 flex flex-col gap-2">
            {dayBriefingRows.map((row) => (
              <div key={row.label} className="border-t border-line pt-2 first:border-t-0 first:pt-0">
                <dt className="text-[10px] font-semibold uppercase tracking-wide text-primary-text">{row.label}</dt>
                <dd className="mt-0.5 text-xs leading-snug text-ink">{cited(row.body)}</dd>
              </div>
            ))}
          </dl>
        </div>
      ),
    },
  ];

  // Rendered twice, see the note above HomePage: the phone copy sits ahead of
  // the fold with no id, the desktop copy keeps #evidence where it always was.
  const evidenceSection = (props: { id?: string; className: string }) => (
    <section id={props.id} className={props.className}>
      <div className="mx-auto max-w-2xl text-center">
        <p className="ad-eyebrow flex items-center justify-center gap-2">
          <BookMarked className="h-3.5 w-3.5" strokeWidth={2.2} />
          {t("home.evEyebrow")}
        </p>
        <h2 className="mt-3 text-balance font-display text-3xl leading-tight text-ink md:text-4xl">
          {t("home.evTitle")}
        </h2>
        <p className="mt-4 text-[15px] leading-relaxed text-ink-soft">{t("home.evBody")}</p>
      </div>
      <div className="mt-10 grid grid-cols-2 gap-4 sm:gap-3 md:grid-cols-4">
        {evStats.map((s) => (
          <div key={s.label} className="ad-card px-4 py-5 text-center sm:px-5">
            <div className="font-display text-2xl font-semibold text-primary-text sm:text-3xl">{s.value}</div>
            <div className="mt-1.5 text-xs leading-snug text-ink-soft">{s.label}</div>
          </div>
        ))}
      </div>
      <div className="mt-8 flex flex-col items-center gap-3">
        <span className="ad-eyebrow">{t("home.evSourcesLabel")}</span>
        <div className="flex max-w-3xl flex-wrap items-center justify-center gap-2">
          {evOrgs.map((o) => (
            <span
              key={o}
              className="rounded-full border border-line-control bg-surface px-3 py-1 font-mono text-xs text-ink-soft"
            >
              {o}
            </span>
          ))}
        </div>
      </div>
    </section>
  );

  return (
    <div className="relative min-h-screen overflow-hidden">
      {/* One aggregate counter per page view, no cookie and no identifier
          (audit 4.8, components/funnel.tsx). Renders nothing. */}
      <FunnelVisit />
      {/* Top bar */}
      <header className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4 md:py-6">
        <span className="font-display text-2xl font-semibold tracking-tight text-ink">
          Adel<span className="text-accent-text">IA</span>
        </span>
        <div className="flex items-center gap-4">
          <a
            href={GITHUB_URL}
            target="_blank"
            rel="noreferrer"
            aria-label={t("home.footerGithub")}
            className="hidden text-ink-soft transition-colors hover:text-primary-text-hover sm:inline-flex"
          >
            <Code2 className="h-5 w-5" strokeWidth={1.9} />
          </a>
          <LocaleSwitcher current={locale} />
          {/* Phones: the hero below carries the same action on the same
              screen, so a second "Empezar" in the corner only splits the
              thumb's choice three ways. */}
          <StartLink
            href="/dashboard"
            className="ad-btn ad-btn-ghost px-3.5 py-1.5 text-sm max-sm:hidden"
          >
            {t("home.cta")}
          </StartLink>
        </div>
      </header>

      {/* Hero */}
      <main className="mx-auto max-w-6xl px-6 pb-16 pt-4 md:pb-24 md:pt-16">
        <div className="grid items-center gap-10 lg:grid-cols-[1.05fr_0.95fr] lg:gap-14">
          {/* Left: copy */}
          <div className="ad-rise" style={{ animationDelay: "60ms" }}>
            {/* Not on phones: small print above the h1 that the h1 and the
                paragraph already say. On a 390 px screen it wrapped to two
                lines and was one more thing between the mother and the
                buttons. */}
            <p className="ad-eyebrow hidden items-center gap-2 md:flex">
              <Stethoscope className="h-3.5 w-3.5" strokeWidth={2.2} />
              {t("home.eyebrow")}
            </p>
            {/* 34 px on a phone: at 48 px the h1 took seven lines (349 px) and
                pushed the demo button off the first screen. sm and up keep the
                original 48/60 px. */}
            <h1 className="text-balance font-display text-[2.125rem] leading-[1.08] tracking-tight text-ink sm:text-5xl sm:leading-[1.04] md:mt-5 md:text-6xl">
              {t("home.hero")}
            </h1>
            <p className="mt-4 max-w-xl text-base leading-relaxed text-ink-soft md:mt-6 md:text-lg">
              {t("home.subhero")}
            </p>
            {/* Phones: one column, full width, 12 px apart. Both buttons are
                `.ad-btn` (44 px floor, 8 px minimum gap in spec 7.5). */}
            <div className="mt-6 flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center md:mt-9">
              <StartLink
                href="/dashboard"
                className="ad-btn ad-btn-primary w-full px-6 py-3 text-base sm:w-auto"
              >
                {t("home.cta")}
                <ArrowRight className="h-4 w-4" strokeWidth={2.4} />
              </StartLink>
              {/* The demo is the answer to "a card before the first useful
                  pixel" (audit 4.6): a stranger can see the product answer a
                  real question, with its sources, before deciding anything. */}
              <Link href="/demo" className="ad-btn ad-btn-ghost w-full px-5 py-3 text-base sm:w-auto">
                {t("home.demoLink")}
              </Link>
              {/* Not on phones: its target (#how) is folded there. */}
              <a href="#how" className="ad-btn ad-btn-ghost px-5 py-3 text-base max-md:hidden">
                {t("home.ctaSecondary")}
              </a>
            </div>
          </div>

          {/* Right: evidence proof card — the differentiator */}
          <div className="ad-rise" style={{ animationDelay: "180ms" }}>
            <figure className="ad-card relative overflow-hidden p-6 md:p-7">
              <div
                aria-hidden
                className="pointer-events-none absolute -right-16 -top-16 h-48 w-48 rounded-full bg-primary-tint/50 blur-2xl"
              />
              <figcaption className="ad-eyebrow flex items-center gap-2">
                <Quote className="h-3.5 w-3.5" strokeWidth={2.2} />
                {t("home.proofLabel")}
              </figcaption>
              <p className="mt-4 text-sm font-medium italic text-ink-soft">
                “{t("home.proofQuestion")}”
              </p>
              <p className="mt-4 text-[15px] leading-relaxed text-ink">
                {t("home.proofAnswer")}{" "}
                <span className="ad-ev-tag align-middle">ev_1</span>
              </p>
              <div className="mt-5 border-t border-line pt-4">
                <p className="font-mono text-xs text-ink-soft">
                  {t("home.proofSource")}
                </p>
              </div>
            </figure>
          </div>
        </div>

        {/* Phones only: the proof in words and numbers, then the way in. The
            rest of the page is behind "Ver más" (note above HomePage). The
            JSX inside <LandingFold> keeps its old indentation on purpose, so
            the diff shows the fold and not 700 re-indented lines. */}
        {evidenceSection({ className: "mt-14 md:hidden" })}
        <div className="mt-10 md:hidden">
          <Link href="/demo" className="ad-btn ad-btn-primary w-full px-5 py-3 text-base">
            {t("home.demoLink")}
          </Link>
        </div>

        <LandingFold
          hint={t("home.foldHint")}
          moreLabel={t("home.foldMore")}
          lessLabel={t("home.foldLess")}
        >
        {/* A day with AdelIA: the page's signature. A real day, one artefact per step */}
        <section id="day" className="mt-24 scroll-mt-24">
          <div className="mx-auto max-w-2xl text-center">
            <p className="ad-eyebrow flex items-center justify-center gap-2">
              <Clock className="h-3.5 w-3.5" strokeWidth={2.2} />
              {t("home.day.eyebrow")}
            </p>
            <h2 className="mt-3 text-balance font-display text-3xl leading-tight text-ink md:text-4xl">
              {t("home.day.title")}
            </h2>
            <p className="mt-4 text-[15px] leading-relaxed text-ink-soft">{t("home.day.intro")}</p>
          </div>

          {/* Audit 1.2. This block talks about a fever and paracetamol, and the only
              "does not replace medical advice" on the page used to sit in the footer,
              thousands of pixels below. The notice now comes before the first step, at
              reading size (not the 11px footnote under the CTA): on a phone and on lg
              alike it is read before the timeline, not after. */}
          <div
            role="note"
            data-testid="day-disclaimer"
            className="mx-auto mt-8 flex max-w-2xl items-start gap-3 rounded-xl border border-accent-tint-line bg-accent-tint/50 p-4 text-sm leading-relaxed text-ink"
          >
            <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-accent-text" strokeWidth={2.2} aria-hidden />
            <p>{t("home.day.disclaimer")}</p>
          </div>

          {/* Timeline: vertical with the line on the left (phones), one horizontal band of 5 on lg+ */}
          <ol className="relative mt-12 flex flex-col gap-9 border-l border-line-strong pl-6 lg:grid lg:grid-cols-5 lg:items-start lg:gap-3 lg:border-l-0 lg:border-t lg:pl-0 lg:pt-7">
            {daySteps.map((step, i) => (
              <li
                key={step.time}
                className="ad-rise relative flex flex-col"
                style={{ animationDelay: `${i * 60}ms` }}
              >
                <span
                  aria-hidden
                  className={`absolute -left-[1.86rem] top-1.5 h-2.5 w-2.5 rounded-full ring-2 ring-surface lg:left-0 lg:-top-[2.07rem] ${
                    step.tone === "honey" ? "bg-accent-text" : "bg-primary-text"
                  }`}
                />
                {/* Header floor on lg keeps the five cards starting on one line even when a title wraps */}
                <div className="lg:min-h-[11rem]">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-xs font-semibold text-primary-text">{step.time}</span>
                    <span
                      className={`inline-flex h-6 w-6 items-center justify-center rounded-md ring-1 ${
                        step.tone === "honey"
                          ? "bg-accent-tint text-accent-text ring-accent-tint-line"
                          : "bg-primary-tint text-primary-text ring-primary-tint-line"
                      }`}
                    >
                      <step.icon className="h-3.5 w-3.5" strokeWidth={2.2} />
                    </span>
                  </div>
                  <h3 className="mt-2 font-display text-lg leading-snug text-ink">{step.title}</h3>
                  <p className="mt-1 text-sm leading-snug text-ink-soft">{step.lead}</p>
                </div>
                <div className="ad-card mt-4 p-3.5">
                  {step.artifact}
                  <div className="flex justify-end pt-3">{dayTag(step.tag)}</div>
                </div>
              </li>
            ))}
          </ol>

          <div className="mt-12 flex flex-col items-center gap-2">
            <StartLink href="/dashboard" className="ad-btn ad-btn-primary px-6 py-3 text-base">
              {t("home.day.cta")}
              <ArrowRight className="h-4 w-4" strokeWidth={2.4} />
            </StartLink>
            <p className="text-xs text-ink-soft">{t("home.day.ctaNote")}</p>
            <p className="mt-4 max-w-xl text-center font-mono text-[11px] leading-relaxed text-ink-soft">
              {t("home.day.footnote")}
            </p>
          </div>
        </section>

        {/* Feature triad */}
        <section id="features" className="mt-24 scroll-mt-24">
          <div className="grid gap-5 sm:grid-cols-3">
            {features.map((f, i) => (
              <div
                key={f.title}
                className="ad-card ad-card-hover ad-rise p-6"
                style={{ animationDelay: `${260 + i * 90}ms` }}
              >
                <span className="inline-flex h-11 w-11 items-center justify-center rounded-xl bg-primary-tint text-primary-text ring-1 ring-primary-tint-line">
                  <f.icon className="h-5 w-5" strokeWidth={2} />
                </span>
                <h2 className="mt-4 text-lg text-ink">{f.title}</h2>
                <p className="mt-2 text-sm leading-relaxed text-ink-soft">{f.body}</p>
              </div>
            ))}
          </div>
        </section>

        {/* How it works — two modes, one vault */}
        <section id="how" className="mt-28 scroll-mt-24">
          <div className="mx-auto max-w-2xl text-center">
            <p className="ad-eyebrow">{t("home.modesEyebrow")}</p>
            <h2 className="mt-3 text-balance font-display text-3xl leading-tight text-ink md:text-4xl">
              {t("home.modesTitle")}
            </h2>
          </div>

          <div className="mt-12 grid gap-5 md:grid-cols-2">
            {/* Mode A — self-analysis (pine) */}
            <article className="ad-card relative overflow-hidden p-7 md:p-8">
              <span
                aria-hidden
                className="absolute right-6 top-6 font-display text-5xl font-semibold text-primary-tint select-none"
              >
                A
              </span>
              <p className="ad-eyebrow">{t("home.modeALabel")}</p>
              <div className="mt-3 flex items-center gap-3">
                <span className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-primary-tint text-primary-text ring-1 ring-primary-tint-line">
                  <MessagesSquare className="h-5 w-5" strokeWidth={2} />
                </span>
                <h3 className="font-display text-xl text-ink">{t("home.modeATitle")}</h3>
              </div>
              <p className="mt-4 text-[15px] leading-relaxed text-ink-soft">{t("home.modeABody")}</p>
              {/* Realistic chat preview — mirrors the actual product UI */}
              <div className="mt-5 flex flex-col gap-2.5">
                <div className="flex justify-end">
                  <div className="max-w-[85%] rounded-2xl rounded-br-md bg-primary px-3.5 py-2 text-sm leading-relaxed text-on-primary">
                    {t("home.modeADemoQ")}
                  </div>
                </div>
                <div className="flex justify-start">
                  <div className="max-w-[92%] rounded-2xl rounded-bl-md border border-line bg-surface px-3.5 py-2.5 text-sm leading-relaxed text-ink shadow-soft">
                    {t("home.modeADemoA")} <span className="ad-ev-tag align-middle">ev_1</span>
                    <span className="mt-2 block font-mono text-[11px] text-ink-faint">
                      {t("home.modeADemoSource")}
                    </span>
                  </div>
                </div>
              </div>
            </article>

            {/* Mode B — briefing (honey) */}
            <article className="ad-card relative overflow-hidden p-7 md:p-8">
              <span
                aria-hidden
                className="absolute right-6 top-6 font-display text-5xl font-semibold text-accent-tint select-none"
              >
                B
              </span>
              <p className="ad-eyebrow !text-accent-text">{t("home.modeBLabel")}</p>
              <div className="mt-3 flex items-center gap-3">
                <span className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-accent-tint text-accent-text ring-1 ring-accent-tint-line">
                  <Stethoscope className="h-5 w-5" strokeWidth={2} />
                </span>
                <h3 className="font-display text-xl text-ink">{t("home.modeBTitle")}</h3>
              </div>
              <p className="mt-4 text-[15px] leading-relaxed text-ink-soft">{t("home.modeBBody")}</p>
              {/* Realistic one-page briefing preview */}
              <div className="mt-5 rounded-xl border border-line bg-surface-2 p-4">
                <div className="flex items-center justify-between gap-2">
                  <span className="ad-eyebrow !text-accent-text">{t("home.modeBDemoTitle")}</span>
                  <FileText className="h-4 w-4 text-accent-text" strokeWidth={2} />
                </div>
                <p className="mt-1 font-mono text-[11px] text-ink-faint">{t("home.modeBDemoMeta")}</p>
                <dl className="mt-3 flex flex-col gap-2.5">
                  {briefingRows.map((row, i) => (
                    <div key={row.label} className="border-t border-line pt-2.5 first:border-t-0 first:pt-0">
                      <dt className="text-[11px] font-semibold uppercase tracking-wide text-primary-text">
                        {row.label}
                      </dt>
                      <dd className="mt-0.5 text-sm leading-snug text-ink">
                        {row.body}
                        {i === 1 && <span className="ad-ev-tag ml-1 align-middle">ev_1</span>}
                      </dd>
                    </div>
                  ))}
                </dl>
              </div>
            </article>
          </div>
        </section>

        {/* Fusion — the baby's full history (from birth) × the science */}
        <section id="story" className="mt-28 scroll-mt-24">
          <div className="mx-auto max-w-2xl text-center">
            <p className="ad-eyebrow flex items-center justify-center gap-2">
              <Baby className="h-3.5 w-3.5" strokeWidth={2.2} />
              {t("home.mixEyebrow")}
            </p>
            <h2 className="mt-3 text-balance font-display text-3xl leading-tight text-ink md:text-4xl">
              {t("home.mixTitle")}
            </h2>
            <p className="mt-4 text-[15px] leading-relaxed text-ink-soft">{t("home.mixBody")}</p>
          </div>

          <div className="mt-10 grid gap-5 md:grid-cols-2 md:items-stretch">
            {/* Left: the baby's history from birth */}
            <div className="ad-card flex flex-col p-6 md:p-7">
              <div className="ad-eyebrow flex items-center gap-2">
                <Baby className="h-3.5 w-3.5" strokeWidth={2.2} />
                {t("home.mixTimelineLabel")}
              </div>
              <ol className="relative mt-5 flex flex-col gap-4 border-l border-line-strong pl-5">
                {timeline.map((item) => (
                  <li key={item.age} className="relative">
                    <span
                      aria-hidden
                      className="absolute -left-[1.43rem] top-1 h-2.5 w-2.5 rounded-full bg-primary-text ring-2 ring-surface"
                    />
                    <div className="font-mono text-xs font-semibold text-primary-text">{item.age}</div>
                    <div className="text-sm leading-snug text-ink">{item.event}</div>
                  </li>
                ))}
              </ol>
            </div>

            {/* Right: history × science = personalized, cited answer */}
            <div className="ad-card flex flex-col p-6 ring-1 ring-primary-tint-line md:p-7">
              <div className="ad-eyebrow flex items-center gap-2 !text-accent-text">
                <Sparkles className="h-3.5 w-3.5" strokeWidth={2.2} />
                {t("home.mixAnswerLabel")}
              </div>
              <div className="mt-5 rounded-2xl rounded-bl-md border border-line bg-surface px-4 py-3.5 text-sm leading-relaxed text-ink shadow-soft">
                {t("home.mixAnswer")}
              </div>
              <div className="mt-auto flex flex-wrap gap-x-5 gap-y-2 pt-5 text-xs text-ink-faint">
                <span className="inline-flex items-center gap-1.5">
                  <span className="rounded-[0.4rem] border border-primary-tint-line bg-primary-tint px-1.5 font-mono text-[0.7rem] font-semibold text-primary-text">
                    [N]
                  </span>
                  {t("home.mixLegendData")}
                </span>
                <span className="inline-flex items-center gap-1.5">
                  <span className="ad-ev-tag">ev_N</span>
                  {t("home.mixLegendEv")}
                </span>
              </div>
            </div>
          </div>
        </section>

        {/* Evidence guarantee — where every answer comes from. Desktop copy:
            phones read the one ahead of the fold (evidenceSection above). */}
        {evidenceSection({ id: "evidence", className: "mt-28 scroll-mt-24 max-md:hidden" })}

        {/* Classic GPT vs AdelIA — honest, structural comparison */}
        <section className="mt-28">
          <div className="mx-auto max-w-2xl text-center">
            <p className="ad-eyebrow">{t("home.vsEyebrow")}</p>
            <h2 className="mt-3 text-balance font-display text-3xl leading-tight text-ink md:text-4xl">
              {t("home.vsTitle")}
            </h2>
            <p className="mt-4 text-lg font-medium italic text-ink-soft">{t("home.vsQuestion")}</p>
          </div>
          <div className="mt-10 grid gap-5 md:grid-cols-2">
            <div className="ad-card p-6">
              <div className="flex items-center gap-2">
                <span className="inline-flex h-8 w-8 items-center justify-center rounded-lg bg-error-tint text-error-text ring-1 ring-error-tint-line">
                  <X className="h-4 w-4" strokeWidth={2.4} />
                </span>
                <span className="text-sm font-semibold text-ink">{t("home.vsGptLabel")}</span>
              </div>
              <p className="mt-4 rounded-2xl rounded-bl-md border border-line bg-surface-2 px-3.5 py-2.5 text-sm leading-relaxed text-ink-soft">
                {t("home.vsGptAnswer")}
              </p>
              <p className="mt-3 flex items-start gap-1.5 text-xs text-error-text">
                <X className="mt-0.5 h-3.5 w-3.5 shrink-0" strokeWidth={2.4} />
                {t("home.vsGptNote")}
              </p>
            </div>
            <div className="ad-card p-6 ring-1 ring-primary-tint-line">
              <div className="flex items-center gap-2">
                <span className="inline-flex h-8 w-8 items-center justify-center rounded-lg bg-primary-tint text-primary-text ring-1 ring-primary-tint-line">
                  <Check className="h-4 w-4" strokeWidth={2.4} />
                </span>
                <span className="text-sm font-semibold text-ink">{t("home.vsColAdelia")}</span>
              </div>
              <div className="mt-4 rounded-2xl rounded-bl-md border border-line bg-surface px-3.5 py-2.5 text-sm leading-relaxed text-ink shadow-soft">
                {t("home.vsAdeliaAnswer")} <span className="ad-ev-tag align-middle">ev_1</span>
                <span className="mt-2 block font-mono text-[11px] text-ink-faint">{t("home.vsAdeliaSource")}</span>
              </div>
              <p className="mt-3 flex items-start gap-1.5 text-xs text-primary-text">
                <Check className="mt-0.5 h-3.5 w-3.5 shrink-0" strokeWidth={2.4} />
                {t("home.vsAdeliaNote")}
              </p>
            </div>
          </div>
          <div className="ad-card mt-5 overflow-hidden">
            {/* Table header — hidden on phones, where each row becomes a stacked card */}
            <div className="hidden grid-cols-[1.4fr_1fr_1fr] border-b border-line bg-surface-2 text-[11px] font-semibold uppercase tracking-wide text-ink-faint sm:grid">
              <div className="px-4 py-2.5" />
              <div className="px-4 py-2.5 text-center">{t("home.vsColGpt")}</div>
              <div className="px-4 py-2.5 text-center text-primary-text">{t("home.vsColAdelia")}</div>
            </div>
            {vsRows.map((r) => (
              <div
                key={r.l}
                className="flex flex-col gap-2 border-b border-line p-4 text-sm last:border-b-0 sm:grid sm:grid-cols-[1.4fr_1fr_1fr] sm:gap-0 sm:p-0"
              >
                <div className="font-medium text-ink sm:px-4 sm:py-2.5">{r.l}</div>
                <div className="flex items-baseline justify-between gap-3 text-ink-soft sm:block sm:px-4 sm:py-2.5 sm:text-center">
                  <span className="text-[11px] font-semibold uppercase tracking-wide text-ink-faint sm:hidden">
                    {t("home.vsColGpt")}
                  </span>
                  <span>{r.g}</span>
                </div>
                <div className="flex items-baseline justify-between gap-3 font-medium text-primary-text sm:block sm:px-4 sm:py-2.5 sm:text-center">
                  <span className="text-[11px] font-semibold uppercase tracking-wide text-primary-text sm:hidden">
                    {t("home.vsColAdelia")}
                  </span>
                  <span>{r.a}</span>
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* Open-source / data sovereignty band */}
        <section className="mt-28">
          <div className="ad-grain ad-card relative overflow-hidden border-brand-band-line bg-brand-band p-8 md:p-12">
            <div
              aria-hidden
              className="pointer-events-none absolute -left-20 -top-24 h-64 w-64 rounded-full bg-primary/30 blur-3xl"
            />
            <div
              aria-hidden
              className="pointer-events-none absolute -bottom-28 right-0 h-64 w-64 rounded-full bg-on-brand-band-accent/15 blur-3xl"
            />
            <div className="relative max-w-2xl">
              <p className="ad-eyebrow !text-on-brand-band-accent">{t("home.ossEyebrow")}</p>
              <h2 className="mt-3 text-balance font-display text-3xl text-on-brand-band md:text-4xl">
                {t("home.ossTitle")}
              </h2>
              <p className="mt-4 text-[15px] leading-relaxed text-on-brand-band-soft">
                {t("home.ossBody")}
              </p>
              <div className="mt-7 flex flex-wrap items-center gap-3">
                <a
                  href={GITHUB_URL}
                  target="_blank"
                  rel="noreferrer"
                  className="ad-btn ad-btn-on-band px-5 text-sm font-semibold"
                >
                  <Code2 className="h-4 w-4" strokeWidth={2} />
                  {t("home.ossCta")}
                  <ArrowUpRight className="h-3.5 w-3.5" strokeWidth={2.4} />
                </a>
                {ossChips.map((chip) => (
                  <span
                    key={chip.label}
                    className="inline-flex items-center gap-1.5 rounded-full border border-on-brand-band/20 bg-on-brand-band/10 px-3 py-1.5 text-xs font-medium text-on-brand-band-soft"
                  >
                    <chip.icon className="h-3.5 w-3.5 text-on-brand-band-accent" strokeWidth={2} />
                    {chip.label}
                  </span>
                ))}
              </div>
            </div>
          </div>
        </section>
        {/* Pricing — how you use it */}
        <section id="pricing" className="mt-28 scroll-mt-24">
          <div className="mx-auto max-w-2xl text-center">
            <p className="ad-eyebrow flex items-center justify-center gap-2">
              <Sparkles className="h-3.5 w-3.5" strokeWidth={2.2} />
              {t("home.prEyebrow")}
            </p>
            <h2 className="mt-3 text-balance font-display text-3xl leading-tight text-ink md:text-4xl">
              {t("home.prTitle")}
            </h2>
          </div>
          <div className="mx-auto mt-12 grid max-w-3xl gap-5 md:grid-cols-2 md:items-start">
            {tiers.map((tier) => (
              <div
                key={tier.name}
                className={`ad-card relative flex flex-col p-7 ${
                  tier.highlight ? "ring-2 ring-primary-text md:-mt-3 md:mb-3" : ""
                }`}
              >
                {tier.badge && (
                  <span className="absolute -top-3 left-1/2 -translate-x-1/2 whitespace-nowrap rounded-full bg-primary px-3 py-1 text-[11px] font-semibold text-on-primary">
                    {tier.badge}
                  </span>
                )}
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <h3 className="font-display text-xl text-ink">{tier.name}</h3>
                  {tier.devTag && (
                    <span className="rounded-full border border-line-strong bg-surface-2 px-2 py-0.5 text-[11px] font-medium text-ink-soft">
                      {tier.devTag}
                    </span>
                  )}
                </div>
                <div className="mt-2 flex items-baseline gap-1">
                  <span className="font-display text-4xl font-semibold text-ink">{tier.price}</span>
                  <span className="text-sm text-ink-faint">{tier.cadence}</span>
                </div>
                <p className="mt-3 text-sm leading-relaxed text-ink-soft">{tier.desc}</p>
                <ul className="mt-5 flex flex-1 flex-col gap-2.5">
                  {tier.features.map((f) => (
                    <li key={f} className="flex items-start gap-2 text-sm text-ink">
                      <Check className="mt-0.5 h-4 w-4 shrink-0 text-primary-text" strokeWidth={2.4} />
                      {f}
                    </li>
                  ))}
                </ul>
                {tier.external ? (
                  <a
                    href={tier.href}
                    target="_blank"
                    rel="noreferrer"
                    className={`ad-btn mt-7 px-5 py-2.5 text-sm ${
                      tier.highlight ? "ad-btn-primary" : "ad-btn-ghost"
                    }`}
                  >
                    {tier.cta}
                  </a>
                ) : (
                  <StartLink
                    href={tier.href}
                    className={`ad-btn mt-7 px-5 py-2.5 text-sm ${
                      tier.highlight ? "ad-btn-primary" : "ad-btn-ghost"
                    }`}
                  >
                    {tier.cta}
                  </StartLink>
                )}
                {tier.trialNote && (
                  <p className="mt-3 text-center text-xs text-ink-soft">{tier.trialNote}</p>
                )}
              </div>
            ))}
          </div>
          <p className="mx-auto mt-6 max-w-2xl text-center text-xs text-ink-faint">
            {t("home.prFootnote")}
          </p>
        </section>
        </LandingFold>
      </main>

      {/* Footer */}
      <footer className="border-t border-line">
        <div className="mx-auto flex max-w-6xl flex-col gap-8 px-6 py-12 md:flex-row md:items-start md:justify-between">
          <div className="max-w-sm">
            <span className="font-display text-xl font-semibold tracking-tight text-ink">
              Adel<span className="text-accent-text">IA</span>
            </span>
            <p className="mt-2 text-sm text-ink-soft">{t("home.footerTagline")}</p>
            <p className="mt-4 text-xs leading-relaxed text-ink-faint">
              {t("home.footerDisclaimer")}
            </p>
          </div>
          <nav className="flex flex-col gap-2.5 text-sm" aria-label="Footer">
            <a
              href={GITHUB_URL}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1.5 py-1.5 text-ink-soft transition-colors hover:text-primary-text-hover"
            >
              <Code2 className="h-4 w-4" strokeWidth={2} />
              {t("home.footerGithub")}
            </a>
            <Link
              href="/dashboard"
              className="inline-flex items-center gap-1.5 py-1.5 text-ink-soft transition-colors hover:text-primary-text-hover"
            >
              <ArrowRight className="h-4 w-4" strokeWidth={2} />
              {t("home.footerDashboard")}
            </Link>
            <Link
              href="/demo"
              className="py-1.5 text-ink-soft transition-colors hover:text-primary-text-hover"
            >
              {t("home.demoLink")}
            </Link>
            <Link
              href="/privacidad"
              className="py-1.5 text-ink-soft transition-colors hover:text-primary-text-hover"
            >
              {t("home.footerPrivacy")}
            </Link>
            <Link
              href="/terminos"
              className="py-1.5 text-ink-soft transition-colors hover:text-primary-text-hover"
            >
              {t("home.footerTerms")}
            </Link>
          </nav>
        </div>
        <div className="border-t border-line">
          <p className="mx-auto max-w-6xl px-6 py-5 font-mono text-xs text-ink-faint">
            © {t("home.footerLicense")}
          </p>
        </div>
      </footer>
    </div>
  );
}
