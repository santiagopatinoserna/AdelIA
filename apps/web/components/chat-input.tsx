"use client";
import { useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { Send, Square } from "lucide-react";
import { ClinicalDisclaimer } from "@/components/clinical-disclaimer";

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
      className="border-t border-line bg-surface/80 p-3 backdrop-blur-sm md:px-6"
    >
      <div className="flex items-end gap-2">
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
          className="max-h-40 flex-1 resize-none rounded-xl border border-line-control bg-surface px-4 py-2.5 text-base leading-relaxed text-ink placeholder:text-ink-faint focus:border-primary-text disabled:bg-surface-2"
        />
        {disabled ? (
          <button
            type="button"
            onClick={onStop}
            aria-label={t("stop")}
            className="ad-btn ad-btn-ghost min-h-[44px] px-4 py-2.5 text-sm"
          >
            <Square className="h-3.5 w-3.5 fill-current" strokeWidth={2} />
            <span>{t("stop")}</span>
          </button>
        ) : (
          <button
            type="submit"
            disabled={!text.trim()}
            aria-label={t("send")}
            className="ad-btn ad-btn-primary min-h-[44px] px-4 py-2.5 text-sm disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Send className="h-4 w-4" strokeWidth={2.2} />
            <span>{t("send")}</span>
          </button>
        )}
      </div>
      {/* Fixed clinical disclaimer (audit 3.8). It sits in the composer, not
          in the page footer, because the composer is the part of the column
          that never scrolls away. */}
      <ClinicalDisclaimer className="mt-2" />
      {/* Make the Enter / Shift+Enter convention discoverable. */}
      <p className="mt-1.5 hidden px-1 text-xs text-ink-faint sm:block">
        {t("keyboardHint")}
      </p>
    </form>
  );
}
