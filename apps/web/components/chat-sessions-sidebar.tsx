"use client";
import { useTranslations } from "next-intl";
import { Plus, MessageSquare, Trash2 } from "lucide-react";
import type { ChatSession } from "@/lib/chat-types";

export function ChatSessionsSidebar({
  sessions,
  activeId,
  onSelect,
  onNew,
  onDelete,
  isOpen = false,
  onClose,
}: {
  sessions: ChatSession[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
  isOpen?: boolean;
  onClose?: () => void;
}) {
  const t = useTranslations("chat");
  return (
    <>
      {/* Mobile backdrop — tap to dismiss the drawer */}
      {isOpen && (
        <button
          type="button"
          aria-label={t("closeSessions")}
          onClick={onClose}
          className="fixed inset-0 z-20 bg-pine-900/40 backdrop-blur-sm md:hidden"
        />
      )}
      <aside
        className={`fixed inset-y-0 left-0 z-30 flex w-64 flex-col border-r border-line bg-surface-2 transition-transform md:static md:z-auto md:translate-x-0 ${
          isOpen ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <button
          type="button"
          onClick={onNew}
          className="ad-btn ad-btn-primary m-3 px-3 py-2 text-sm"
        >
          <Plus className="h-4 w-4" strokeWidth={2.4} />
          {t("newSession")}
        </button>
        <nav className="flex-1 overflow-y-auto px-2 pb-3">
          {sessions.length === 0 ? (
            <p className="px-3 py-6 text-center text-xs text-ink-faint">{t("emptyHistory")}</p>
          ) : (
            <ul className="space-y-0.5">
              {sessions.map((s) => (
                <li key={s.id}>
                  <div
                    className={`group flex items-center justify-between gap-1 rounded-lg px-3 py-2 text-sm transition-colors ${
                      activeId === s.id
                        ? "bg-pine-50 text-pine-800 ring-1 ring-pine-100"
                        : "text-ink-soft hover:bg-surface"
                    }`}
                  >
                    <button
                      type="button"
                      onClick={() => onSelect(s.id)}
                      className="flex min-w-0 flex-1 items-center gap-2 text-left"
                    >
                      <MessageSquare
                        className={`h-3.5 w-3.5 shrink-0 ${activeId === s.id ? "text-pine-500" : "text-ink-faint"}`}
                        strokeWidth={2}
                      />
                      <span className="truncate">{s.title}</span>
                    </button>
                    <button
                      type="button"
                      onClick={() => onDelete(s.id)}
                      className="ml-1 hidden shrink-0 rounded p-1 text-clay-500 hover:bg-clay-50 hover:text-clay-600 group-hover:inline-flex"
                      aria-label={t("deleteSession")}
                    >
                      <Trash2 className="h-3.5 w-3.5" strokeWidth={2} />
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </nav>
      </aside>
    </>
  );
}
