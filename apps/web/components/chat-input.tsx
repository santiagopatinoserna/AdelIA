"use client";
import { useState } from "react";
import { useTranslations } from "next-intl";
import { Send, Loader2 } from "lucide-react";

export function ChatInput({
  onSubmit,
  disabled,
}: {
  onSubmit: (text: string) => void;
  disabled: boolean;
}) {
  const t = useTranslations("chat");
  const [text, setText] = useState("");

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!text.trim() || disabled) return;
    onSubmit(text.trim());
    setText("");
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="flex items-center gap-2 border-t border-line bg-surface/80 p-3 backdrop-blur-sm md:px-6"
    >
      <input
        type="text"
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={t("placeholder")}
        disabled={disabled}
        className="flex-1 rounded-xl border border-line-strong bg-surface px-4 py-2.5 text-sm text-ink placeholder:text-ink-faint focus:border-pine-400 focus:outline-none focus:ring-2 focus:ring-pine-100 disabled:bg-surface-2"
      />
      <button
        type="submit"
        disabled={disabled || !text.trim()}
        aria-label={disabled ? t("thinking") : t("send")}
        className="ad-btn ad-btn-primary px-3.5 py-2.5 text-sm disabled:cursor-not-allowed disabled:opacity-50 sm:px-4"
      >
        {disabled ? (
          <>
            <Loader2 className="h-4 w-4 animate-spin" strokeWidth={2.2} />
            <span className="hidden sm:inline">{t("thinking")}</span>
          </>
        ) : (
          <>
            <Send className="h-4 w-4" strokeWidth={2.2} />
            <span className="hidden sm:inline">{t("send")}</span>
          </>
        )}
      </button>
    </form>
  );
}
