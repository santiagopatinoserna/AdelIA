"use client";
import { useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { Send, Square } from "lucide-react";

export function ChatInput({
  onSubmit,
  disabled,
  onStop,
}: {
  onSubmit: (text: string) => void;
  disabled: boolean;
  onStop?: () => void;
}) {
  const t = useTranslations("chat");
  const [text, setText] = useState("");
  const taRef = useRef<HTMLTextAreaElement>(null);

  // Auto-grow with content up to a cap, then scroll inside the field.
  function resize() {
    const el = taRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }

  function submit() {
    if (!text.trim() || disabled) return;
    onSubmit(text.trim());
    setText("");
    requestAnimationFrame(() => {
      if (taRef.current) taRef.current.style.height = "auto";
    });
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    submit();
  }

  // Enter sends; Shift+Enter inserts a newline (modern chat convention).
  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="flex items-end gap-2 border-t border-line bg-surface/80 p-3 backdrop-blur-sm md:px-6"
    >
      <textarea
        ref={taRef}
        rows={1}
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          resize();
        }}
        onKeyDown={handleKeyDown}
        placeholder={t("placeholder")}
        disabled={disabled}
        aria-label={t("placeholder")}
        className="max-h-40 flex-1 resize-none rounded-xl border border-line-strong bg-surface px-4 py-2.5 text-sm leading-relaxed text-ink placeholder:text-ink-faint focus:border-pine-400 focus:outline-none focus:ring-2 focus:ring-pine-100 disabled:bg-surface-2"
      />
      {disabled ? (
        <button
          type="button"
          onClick={onStop}
          aria-label={t("stop")}
          className="ad-btn ad-btn-ghost px-3.5 py-2.5 text-sm sm:px-4"
        >
          <Square className="h-3.5 w-3.5 fill-current" strokeWidth={2} />
          <span className="hidden sm:inline">{t("stop")}</span>
        </button>
      ) : (
        <button
          type="submit"
          disabled={!text.trim()}
          aria-label={t("send")}
          className="ad-btn ad-btn-primary px-3.5 py-2.5 text-sm disabled:cursor-not-allowed disabled:opacity-50 sm:px-4"
        >
          <Send className="h-4 w-4" strokeWidth={2.2} />
          <span className="hidden sm:inline">{t("send")}</span>
        </button>
      )}
    </form>
  );
}
