"use client";
import { useTranslations } from "next-intl";
import type { ChatSession } from "@/lib/chat-types";

export function ChatSessionsSidebar({
  sessions,
  activeId,
  onSelect,
  onNew,
  onDelete,
}: {
  sessions: ChatSession[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
}) {
  const t = useTranslations("chat");
  return (
    <aside className="flex w-64 flex-col border-r border-slate-200 bg-slate-50">
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
  );
}
