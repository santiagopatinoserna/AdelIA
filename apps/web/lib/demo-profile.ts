// The fictional baby lives in ONE place, the API, and both the record card and
// the context the model is given are built from it (adelia/demo/fixture.py).
// A second copy in the message catalogues would drift, and the first thing to
// drift would be the numbers the answer cites back at the visitor.
// Moved out of demo/page.tsx when the demo became part of the landing, so
// there is still one loader and one shape.

const API_URL =
  process.env.API_INTERNAL_URL ??
  process.env.NEXT_PUBLIC_API_URL ??
  "http://localhost:8000";

export type DemoItem = {
  kind: "report" | "lab" | "consulta" | "diary";
  title: string;
  meta: string;
  date: string;
  lines: string[];
};

export type DemoProfile = {
  is_demo: boolean;
  baby_name: string;
  age_label: string;
  banner: string;
  record_title: string;
  record_note: string;
  suggested: string[];
  items: DemoItem[];
};

export async function loadDemoProfile(locale: string): Promise<DemoProfile | null> {
  try {
    const res = await fetch(`${API_URL}/demo/profile?locale=${encodeURIComponent(locale)}`, {
      cache: "no-store",
    });
    if (!res.ok) return null;
    return (await res.json()) as DemoProfile;
  } catch {
    return null;
  }
}
