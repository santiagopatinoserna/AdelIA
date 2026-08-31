import { Pool } from "pg";

// Direct Postgres seeding for the rows the UI reads back through the real API,
// the same way session.ts seeds the user: nothing test-specific ships in
// production code.
//   * a profile, because the height mark on the panel home renders the baby's
//     real name and age and does not render without them;
//   * a document, because the chat's suggestion list only replaces the "upload
//     something first" empty state once the account has one.

function env(name: string, fallback?: string): string {
  const v = process.env[name] ?? fallback;
  if (v === undefined) throw new Error(`${name} not set for e2e`);
  return v;
}

function pool() {
  return new Pool({
    host: env("POSTGRES_HOST", "localhost"),
    port: Number(env("POSTGRES_PORT", "5434")),
    user: env("POSTGRES_USER", "adelia"),
    password: env("POSTGRES_PASSWORD", "adelia_dev"),
    database: env("POSTGRES_DB", "adelia"),
  });
}

export async function seedProfile(
  userId: string,
  { displayName, dateOfBirth }: { displayName: string; dateOfBirth: string },
): Promise<string> {
  const db = pool();
  const { rows } = await db.query(
    `INSERT INTO profiles (user_id, display_name, relationship, date_of_birth, is_default)
     VALUES ($1, $2, 'child', $3::date, true)
     RETURNING id`,
    [userId, displayName, dateOfBirth],
  );
  await db.end();
  return rows[0].id as string;
}

export async function seedDocument(userId: string): Promise<string> {
  const db = pool();
  const { rows } = await db.query(
    // documents.id has no server default (the model fills it in Python), so
    // the row has to bring its own.
    `INSERT INTO documents (id, user_id, source, mime_type, s3_key, raw_text, processed_at)
     VALUES (gen_random_uuid(), $1, 'manual', 'application/pdf', $2, 'Documento de prueba e2e.', now())
     RETURNING id`,
    [userId, `e2e/${Date.now()}-${Math.random().toString(36).slice(2, 8)}.pdf`],
  );
  await db.end();
  return rows[0].id as string;
}

// An ISO date exactly `months` whole months before today, safe on month ends
// (the 31st of a month that the target month does not have lands on its last
// day, which is what the app's own month arithmetic assumes).
export function isoMonthsAgo(months: number): string {
  const now = new Date();
  const d = new Date(now.getFullYear(), now.getMonth() - months, 1);
  const lastDay = new Date(d.getFullYear(), d.getMonth() + 1, 0).getDate();
  d.setDate(Math.min(now.getDate(), lastDay));
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}
