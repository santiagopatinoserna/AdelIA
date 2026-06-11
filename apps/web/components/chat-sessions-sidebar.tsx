"use client";
import { useTranslations } from "next-intl";
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
          className="fixed inset-0 z-20 bg-slate-900/40 md:hidden"
        />
      )}
      <aside
        className={`fixed inset-y-0 left-0 z-30 flex w-64 flex-col border-r border-slate-200 bg-slate-50 transition-transform md:static md:z-auto md:translate-x-0 ${
          isOpen ? "translate-x-0" : "-translate-x-full"
        }`}
      >
      <button
        type="button"
        onClick={onNew}
        className="m-3 rounded-md bg-slate-900 px-3 py-2 text-sm text-white hover:bg-slate-800"
      >
        + {t("newSession")}
      </button>
      <nav className="flex-1 overflow-y-auto px-2">
        {sessions.length === 0 ? (
          <p className="px-3 py-6 text-center text-xs text-slate-500">{t("emptyHistory")}</p>
        ) : (
          <ul className="space-y-1">
            {sessions.map((s) => (
              <li key={s.id}>
                <div
                  className={`group flex items-center justify-between rounded-md px-3 py-2 text-sm ${
                    activeId === s.id ? "bg-slate-200" : "hover:bg-slate-100"
                  }`}
                >
                  <button
                    type="button"
                    onClick={() => onSelect(s.id)}
                    className="flex-1 truncate text-left"
                  >
                    {s.title}
                  </button>
                  <button
                    type="button"
                    onClick={() => onDelete(s.id)}
                    className="ml-2 hidden text-xs text-rose-600 hover:text-rose-800 group-hover:inline"
                    aria-label={t("deleteSession")}
                  >
                    ×
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
