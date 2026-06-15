"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Users } from "lucide-react";

import { enrichment } from "@/lib/api-client-browser";
import type { Profile, Relationship } from "@/lib/enrichment-types";

const RELATIONSHIPS: Relationship[] = ["self", "child", "parent", "spouse", "sibling", "other"];

export default function ProfilesPage() {
  const t = useTranslations();
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [showAdd, setShowAdd] = useState(false);
  const [newName, setNewName] = useState("");
  const [newRel, setNewRel] = useState<Relationship>("child");
  const [newDob, setNewDob] = useState("");
  const [newSex, setNewSex] = useState("");

  async function refresh() {
    try {
      const list = await enrichment.listProfiles();
      setProfiles(list);
    } catch (e) {
      setError(String(e));
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function handleAdd() {
    if (!newName.trim()) return;
    try {
      await enrichment.createProfile({
        display_name: newName,
        relationship: newRel,
        date_of_birth: newDob || null,
        sex: newSex || null,
      });
      setNewName("");
      setNewDob("");
      setNewSex("");
      setShowAdd(false);
      await refresh();
    } catch (e) {
      setError(String(e));
    }
  }

  async function handleSetDefault(id: string) {
    try {
      await enrichment.setDefaultProfile(id);
      await refresh();
    } catch (e) {
      setError(String(e));
    }
  }

  async function handleDelete(id: string) {
    if (!confirm(t("enrichment.profiles.deleteConfirm"))) return;
    try {
      await enrichment.deleteProfile(id);
      await refresh();
    } catch (e) {
      setError(String(e));
    }
  }

  return (
    <main className="mx-auto max-w-3xl px-6 py-10">
      <h1 className="flex items-center gap-2 text-2xl text-pine-900">
        <Users className="h-5 w-5 text-pine-500" strokeWidth={2} />
        {t("enrichment.tabs.profiles")}
      </h1>

      {error && (
        <div className="mt-4 rounded-lg border border-clay-100 bg-clay-50 p-3 text-sm text-clay-700">
          {error}
        </div>
      )}

      <ul className="mt-6 space-y-2">
        {profiles.map((p) => (
          <li
            key={p.id}
            className="ad-card flex items-center justify-between p-3"
          >
            <div>
              <div className="font-medium text-ink">
                {p.display_name}
                {p.is_default && (
                  <span className="ml-2 rounded bg-pine-50 px-1.5 py-0.5 text-xs text-pine-700 ring-1 ring-pine-100">
                    {t("enrichment.profiles.default")}
                  </span>
                )}
              </div>
              <div className="text-xs text-ink-faint">
                {t(`enrichment.profiles.${p.relationship}`)}
                {p.date_of_birth && ` · ${p.date_of_birth}`}
                {p.sex && ` · ${p.sex}`}
              </div>
            </div>
            <div className="flex gap-2">
              {!p.is_default && (
                <button
                  type="button"
                  onClick={() => handleSetDefault(p.id)}
                  className="text-xs text-pine-600 hover:text-pine-700 hover:underline"
                >
                  {t("enrichment.profiles.setDefault")}
                </button>
              )}
              <button
                type="button"
                onClick={() => handleDelete(p.id)}
                className="text-xs text-clay-600 hover:text-clay-700 hover:underline"
              >
                {t("enrichment.profiles.delete")}
              </button>
            </div>
          </li>
        ))}
      </ul>

      {showAdd ? (
        <div className="ad-card mt-6 space-y-3 p-4">
          <input
            type="text"
            placeholder={t("enrichment.profiles.displayName")}
            aria-label={t("enrichment.profiles.displayName")}
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            className="w-full rounded-xl border border-line-strong bg-surface px-3 py-2 text-sm text-ink placeholder:text-ink-faint focus:border-pine-400 focus:outline-none focus:ring-2 focus:ring-pine-100"
          />
          <select
            value={newRel}
            onChange={(e) => setNewRel(e.target.value as Relationship)}
            aria-label={t("enrichment.profiles.relationship")}
            className="w-full rounded-xl border border-line-strong bg-surface px-3 py-2 text-sm text-ink focus:border-pine-400 focus:outline-none focus:ring-2 focus:ring-pine-100"
          >
            {RELATIONSHIPS.map((r) => (
              <option key={r} value={r}>
                {t(`enrichment.profiles.${r}`)}
              </option>
            ))}
          </select>
          <input
            type="date"
            placeholder={t("enrichment.profiles.dob")}
            aria-label={t("enrichment.profiles.dob")}
            value={newDob}
            onChange={(e) => setNewDob(e.target.value)}
            className="w-full rounded-xl border border-line-strong bg-surface px-3 py-2 text-sm text-ink placeholder:text-ink-faint focus:border-pine-400 focus:outline-none focus:ring-2 focus:ring-pine-100"
          />
          <select
            value={newSex}
            onChange={(e) => setNewSex(e.target.value)}
            aria-label={t("enrichment.profiles.sex")}
            className="w-full rounded-xl border border-line-strong bg-surface px-3 py-2 text-sm text-ink focus:border-pine-400 focus:outline-none focus:ring-2 focus:ring-pine-100"
          >
            <option value="">—</option>
            <option value="M">M</option>
            <option value="F">F</option>
            <option value="other">{t("enrichment.profiles.other")}</option>
          </select>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={handleAdd}
              className="ad-btn ad-btn-primary px-3 py-1.5 text-sm"
            >
              {t("enrichment.profiles.create")}
            </button>
            <button
              type="button"
              onClick={() => setShowAdd(false)}
              className="ad-btn ad-btn-ghost px-3 py-1.5 text-sm"
            >
              {t("enrichment.profiles.cancel")}
            </button>
          </div>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => setShowAdd(true)}
          className="ad-btn ad-btn-primary mt-6 px-4 py-2 text-sm"
        >
          + {t("enrichment.profiles.addProfile")}
        </button>
      )}
    </main>
  );
}
