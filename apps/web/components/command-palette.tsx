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

type Cmd = { id: string; label: string; icon: LucideIcon; href: string };

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
      { id: "home", label: tc("home"), icon: Home, href: "/dashboard" },
      { id: "chat", label: "Chat", icon: MessagesSquare, href: "/dashboard/chat" },
      { id: "newchat", label: tc("newChat"), icon: Plus, href: "/dashboard/chat" },
      { id: "briefings", label: "Briefings", icon: ClipboardList, href: "/dashboard/briefings" },
      { id: "questionnaire", label: t("questionnaire.navLabel"), icon: Baby, href: "/dashboard/questionnaire" },
      { id: "consulta", label: t("consulta.navLabel"), icon: Stethoscope, href: "/dashboard/consulta" },
      { id: "ingestion", label: t("dashboard.navImport"), icon: Download, href: "/dashboard/ingestion" },
      { id: "enrichment", label: t("dashboard.navInsights"), icon: Sparkles, href: "/dashboard/enrichment" },
      { id: "upload", label: t("dashboard.uploadCta"), icon: UploadCloud, href: "/dashboard/upload" },
      { id: "settings", label: t("settings.title"), icon: Settings, href: "/dashboard/settings" },
    ],
    [t, tc],
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return commands;
    return commands.filter((c) => c.label.toLowerCase().includes(q));
  }, [query, commands]);

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
        className="ad-btn ad-btn-ghost h-9 gap-2 px-2.5 text-sm text-ink-soft lg:px-3"
      >
        <Search className="h-4 w-4" strokeWidth={2} />
        <span className="hidden lg:inline">{tc("label")}</span>
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
            className="ad-card w-full max-w-lg overflow-hidden p-0 shadow-glow"
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
                <li className="px-3 py-6 text-center text-sm text-ink-faint">{tc("noResults")}</li>
              ) : (
                filtered.map((c, i) => (
                  <li key={c.id}>
                    <button
                      type="button"
                      onClick={() => run(c)}
                      onMouseMove={() => setSel(i)}
                      aria-selected={i === sel}
                      className={`flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm ${
                        i === sel ? "bg-pine-50 text-pine-800" : "text-ink"
                      }`}
                    >
                      <c.icon
                        className={`h-4 w-4 shrink-0 ${i === sel ? "text-pine-500" : "text-ink-faint"}`}
                        strokeWidth={2}
                      />
                      <span className="flex-1">{c.label}</span>
                      {i === sel && <CornerDownLeft className="h-3.5 w-3.5 text-pine-400" strokeWidth={2} />}
                    </button>
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
