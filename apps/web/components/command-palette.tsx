"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "@/lib/navigation";
import { useTranslations } from "next-intl";
import { useFocusTrap } from "@/lib/use-focus-trap";
import {
  Search,
  MessagesSquare,
  ClipboardList,
  Baby,
  Stethoscope,
  Download,
  Sparkles,
  UploadCloud,
  Settings,
  Home,
  Plus,
  CornerDownLeft,
  type LucideIcon,
} from "lucide-react";

type Group = "ask" | "visit" | "manage";
type Cmd = { id: string; label: string; desc: string; group: Group; icon: LucideIcon; href: string };
const GROUP_ORDER: Group[] = ["ask", "visit", "manage"];

// ⌘K command palette: jump to any section / action from anywhere, keyboard-first
// (the modern web convention). Doubles as the mobile cross-section nav — the
// search button opens it where the desktop section nav is hidden.
export function CommandPalette() {
  const t = useTranslations();
  const tc = useTranslations("command");
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [sel, setSel] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  useFocusTrap(dialogRef, open);

  const commands: Cmd[] = useMemo(
    () => [
      { id: "chat", label: "Chat", desc: tc("descChat"), group: "ask", icon: MessagesSquare, href: "/dashboard/chat" },
      { id: "newchat", label: tc("newChat"), desc: tc("descNewChat"), group: "ask", icon: Plus, href: "/dashboard/chat" },
      { id: "questionnaire", label: t("questionnaire.navLabel"), desc: tc("descQuestionnaire"), group: "visit", icon: Baby, href: "/dashboard/questionnaire" },
      { id: "consulta", label: t("consulta.navLabel"), desc: tc("descConsulta"), group: "visit", icon: Stethoscope, href: "/dashboard/consulta" },
      { id: "briefings", label: "Briefings", desc: tc("descBriefings"), group: "visit", icon: ClipboardList, href: "/dashboard/briefings" },
      { id: "home", label: tc("home"), desc: tc("descHome"), group: "manage", icon: Home, href: "/dashboard" },
      { id: "upload", label: t("dashboard.uploadCta"), desc: tc("descUpload"), group: "manage", icon: UploadCloud, href: "/dashboard/upload" },
      { id: "ingestion", label: t("dashboard.navImport"), desc: tc("descIngestion"), group: "manage", icon: Download, href: "/dashboard/ingestion" },
      { id: "enrichment", label: t("dashboard.navInsights"), desc: tc("descEnrichment"), group: "manage", icon: Sparkles, href: "/dashboard/enrichment" },
      { id: "settings", label: t("settings.title"), desc: tc("descSettings"), group: "manage", icon: Settings, href: "/dashboard/settings" },
    ],
    [t, tc],
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return commands;
    return commands.filter(
      (c) => c.label.toLowerCase().includes(q) || c.desc.toLowerCase().includes(q),
    );
  }, [query, commands]);

  // Keep the visual category headers while preserving the flat index used by
  // keyboard nav (sel maps to filtered[]). We render groups in a fixed order,
  // tracking each item's absolute index across groups.
  const grouped = useMemo(() => {
    return GROUP_ORDER.map((g) => ({
      group: g,
      items: filtered
        .map((c, idx) => ({ c, idx }))
        .filter(({ c }) => c.group === g),
    })).filter((s) => s.items.length > 0);
  }, [filtered]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((o) => !o);
      } else if (e.key === "Escape") {
        // Close from anywhere in the palette (focus may be on a list item).
        setOpen(false);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    if (open) {
      setQuery("");
      setSel(0);
      const id = setTimeout(() => inputRef.current?.focus(), 20);
      return () => clearTimeout(id);
    }
  }, [open]);

  useEffect(() => setSel(0), [query]);

  function run(c: Cmd) {
    setOpen(false);
    router.push(c.href);
  }

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSel((s) => Math.min(s + 1, filtered.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSel((s) => Math.max(s - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (filtered[sel]) run(filtered[sel]);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  }

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label={tc("label")}
        className="ad-btn ad-btn-ghost h-9 gap-2 px-3 text-sm text-ink-soft"
      >
        <Search className="h-4 w-4 shrink-0" strokeWidth={2} />
        <span>{tc("label")}</span>
        <kbd className="hidden rounded border border-line-strong bg-surface-2 px-1.5 py-px font-mono text-[10px] text-ink-faint lg:inline">
          ⌘K
        </kbd>
      </button>

      {open && (
        <div
          className="fixed inset-0 z-50 flex items-start justify-center bg-pine-900/40 p-4 pt-[16vh] backdrop-blur-sm"
          onClick={() => setOpen(false)}
        >
          <div
            ref={dialogRef}
            role="dialog"
            aria-modal="true"
            aria-label={tc("label")}
            onClick={(e) => e.stopPropagation()}
            className="ad-card w-full max-w-sm overflow-hidden p-0 shadow-glow sm:max-w-lg"
          >
            <div className="flex items-center gap-2 border-b border-line px-4">
              <Search className="h-4 w-4 shrink-0 text-ink-faint" strokeWidth={2} />
              <input
                ref={inputRef}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={onKeyDown}
                placeholder={tc("placeholder")}
                aria-label={tc("placeholder")}
                className="w-full bg-transparent py-3.5 text-sm text-ink placeholder:text-ink-faint focus:outline-none"
              />
            </div>
            <ul className="max-h-80 overflow-y-auto p-2">
              {filtered.length === 0 ? (
                <li className="px-3 py-6 text-center text-sm text-ink-soft">{tc("noResults")}</li>
              ) : (
                grouped.map((section) => (
                  <li key={section.group}>
                    <p className="ad-eyebrow px-3 pb-1 pt-3 first:pt-1">{tc(`group_${section.group}`)}</p>
                    <ul>
                      {section.items.map(({ c, idx }) => (
                        <li key={c.id}>
                          <button
                            type="button"
                            onClick={() => run(c)}
                            onMouseMove={() => setSel(idx)}
                            aria-selected={idx === sel}
                            className={`flex min-h-[44px] w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm ${
                              idx === sel ? "bg-pine-50 text-pine-800" : "text-ink"
                            }`}
                          >
                            <c.icon
                              className={`h-4 w-4 shrink-0 ${idx === sel ? "text-pine-500" : "text-ink-soft"}`}
                              strokeWidth={2}
                            />
                            <span className="flex-1 leading-tight">
                              <span className="block font-medium">{c.label}</span>
                              <span className={`block text-xs ${idx === sel ? "text-pine-700" : "text-ink-soft"}`}>
                                {c.desc}
                              </span>
                            </span>
                            {idx === sel && (
                              <CornerDownLeft className="h-3.5 w-3.5 shrink-0 text-pine-400" strokeWidth={2} />
                            )}
                          </button>
                        </li>
                      ))}
                    </ul>
                  </li>
                ))
              )}
            </ul>
          </div>
        </div>
      )}
    </>
  );
}
