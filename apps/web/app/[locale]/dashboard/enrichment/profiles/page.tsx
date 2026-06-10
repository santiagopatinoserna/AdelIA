"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";

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
      <h1 className="text-2xl font-semibold">{t("enrichment.tabs.profiles")}</h1>

      {error && (
        <div className="mt-4 rounded border border-red-300 bg-red-50 p-3 text-sm text-red-800">
          {error}
        </div>
      )}

      <ul className="mt-6 space-y-2">
        {profiles.map((p) => (
          <li
            key={p.id}
            className="flex items-center justify-between rounded border border-slate-200 bg-white p-3"
          >
            <div>
              <div className="font-medium">
                {p.display_name}
                {p.is_default && (
                  <span className="ml-2 rounded bg-green-100 px-1.5 py-0.5 text-xs text-green-800">
                    {t("enrichment.profiles.default")}
                  </span>
                )}
              </div>
              <div className="text-xs text-slate-500">
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
                  className="text-xs text-blue-700 hover:underline"
                >
                  {t("enrichment.profiles.setDefault")}
                </button>
              )}
              <button
                type="button"
                onClick={() => handleDelete(p.id)}
                className="text-xs text-red-700 hover:underline"
              >
                {t("enrichment.profiles.delete")}
              </button>
            </div>
          </li>
        ))}
      </ul>

      {showAdd ? (
        <div className="mt-6 space-y-3 rounded border border-slate-300 bg-white p-4">
          <input
            type="text"
            placeholder={t("enrichment.profiles.displayName")}
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            className="w-full rounded border border-slate-300 px-3 py-2 text-sm"
          />
          <select
            value={newRel}
            onChange={(e) => setNewRel(e.target.value as Relationship)}
            className="w-full rounded border border-slate-300 px-3 py-2 text-sm"
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
            value={newDob}
            onChange={(e) => setNewDob(e.target.value)}
            className="w-full rounded border border-slate-300 px-3 py-2 text-sm"
          />
          <select
            value={newSex}
            onChange={(e) => setNewSex(e.target.value)}
            className="w-full rounded border border-slate-300 px-3 py-2 text-sm"
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
              className="rounded bg-slate-900 px-3 py-1.5 text-sm text-white hover:bg-slate-800"
            >
              {t("enrichment.profiles.create")}
            </button>
            <button
              type="button"
              onClick={() => setShowAdd(false)}
              className="rounded border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50"
            >
              {t("enrichment.profiles.cancel")}
            </button>
          </div>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => setShowAdd(true)}
          className="mt-6 rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800"
        >
          + {t("enrichment.profiles.addProfile")}
        </button>
      )}
    </main>
  );
}
