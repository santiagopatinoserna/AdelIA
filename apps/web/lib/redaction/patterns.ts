// Deterministic detectors: no model, no network, no state.
//
// Each detector is a named function `(text) => Span[]` that implements ONE
// national format and says which. They are meant to carry most of the value of
// local redaction on their own, which is why they are strict instead of wide:
// a detector that fires on a clinical number does more harm than one that
// misses a rare identifier, because the first silently corrupts the question
// the parent is asking while the second only fails to hide something.
//
// Two techniques keep them strict:
//   1. Self-validating formats (DNI, NIE, NIR) are accepted only when their
//      check letter / check key is right. A random 8-digit number followed by
//      a letter is not a DNI, a 1-in-23 chance aside, and the shape alone would
//      otherwise match lot numbers and report codes.
//   2. Formats that are NOT self-validating and look like ordinary numbers
//      (postal codes, dates of birth, the bare-digit health card numbers) are
//      accepted only right after a keyword that says what they are
//      ("nacimiento", "código postal", "tarjeta sanitaria"...). A five-digit
//      number is a postal code only if someone called it one; "12500" next to
//      "leucocitos" is a white cell count.
//
// Boundaries are Unicode-aware lookarounds, not \b: \b treats "ó" as a
// non-word character and would let "nació" end in the middle of a word.

import type { Detector, Span } from "./types";

const B = "(?<![\\p{L}\\p{N}_])"; // not preceded by a letter, digit or underscore
const A = "(?![\\p{L}\\p{N}_])"; // not followed by one

function span(start: number, end: number, kind: Span["kind"]): Span {
  return { start, end, kind };
}

// ---------------------------------------------------------------------------
// Spain: DNI and NIE
// ---------------------------------------------------------------------------

// The check letter of a DNI/NIE is the remainder of the number mod 23 looked
// up in this table (Orden INT/2058/2008 and its predecessors).
const CHECK_LETTERS = "TRWAGMYFPDXBNJZSQVHLCKE";

/** Check letter for the 8-digit number of a Spanish DNI. */
export function dniLetter(number: number): string {
  return CHECK_LETTERS[number % 23];
}

/**
 * Check letter of a Spanish NIE. The prefix letter stands for a digit,
 * X=0, Y=1, Z=2, which is put in front of the 7 digits to make an 8-digit
 * number that then goes through the same mod 23 as a DNI.
 */
export function nieLetter(prefix: string, digits: string): string {
  const lead = "XYZ".indexOf(prefix.toUpperCase());
  if (lead < 0 || !/^\d{7}$/.test(digits)) throw new Error("not a NIE body");
  return dniLetter(Number(`${lead}${digits}`));
}

/** `12345678Z`, with or without the dots and dash people type, case-insensitive. */
export function isValidDni(raw: string): boolean {
  const m = /^(\d{2}\.?\d{3}\.?\d{3})[- ]?([A-Za-z])$/.exec(raw.trim());
  if (!m) return false;
  return dniLetter(Number(m[1].replace(/\./g, ""))) === m[2].toUpperCase();
}

/** `X1234567L`, prefix X, Y or Z, with or without separators. */
export function isValidNie(raw: string): boolean {
  const m = /^([XYZxyz])[-. ]?(\d{7})[- ]?([A-Za-z])$/.exec(raw.trim());
  if (!m) return false;
  return nieLetter(m[1], m[2]) === m[3].toUpperCase();
}

// 8 digits (dots optional) then the letter. A lowercase letter is accepted
// only when it is glued on or after a dash, because "20240101 a las" is how
// Spanish writes a time, not an identifier. After a space only an uppercase
// letter counts.
const DNI = new RegExp(`${B}(\\d{2}\\.?\\d{3}\\.?\\d{3})(?:-?([A-Za-z])| ([A-Z]))${A}`, "gu");

/**
 * SPAIN. Documento Nacional de Identidad: 8 digits plus a check letter.
 * Only hits whose letter is right are returned (see the header, point 1).
 */
export const detectDni: Detector = (text) => {
  const out: Span[] = [];
  for (const m of text.matchAll(DNI)) {
    const letter = (m[2] ?? m[3]).toUpperCase();
    if (dniLetter(Number(m[1].replace(/\./g, ""))) === letter) {
      out.push(span(m.index, m.index + m[0].length, "DNI"));
    }
  }
  return out;
};

const NIE = new RegExp(`${B}([XYZxyz])[-. ]?(\\d{7})[- ]?([A-Za-z])${A}`, "gu");

/**
 * SPAIN. Número de Identidad de Extranjero: prefix X, Y or Z, 7 digits, check
 * letter computed as for a DNI with the prefix read as 0, 1 or 2.
 */
export const detectNie: Detector = (text) => {
  const out: Span[] = [];
  for (const m of text.matchAll(NIE)) {
    if (nieLetter(m[1], m[2]) === m[3].toUpperCase()) {
      out.push(span(m.index, m.index + m[0].length, "NIE"));
    }
  }
  return out;
};

// ---------------------------------------------------------------------------
// France: NIR (numéro de sécurité sociale) and the Carte Vitale
// ---------------------------------------------------------------------------

const NIR_SEP = "[ \\u00A0.-]?";
// sex(1) year(2) month(2) department(2 or 2A/2B) commune(3) order(3), then the
// 2-digit key. Sex 1/2 are the usual ones, 3/4 and 7/8 are the provisional
// numbers given to people registered before their civil status is settled.
const NIR_BODY =
  `(?<sex>[1-478])${NIR_SEP}(?<yy>\\d{2})${NIR_SEP}(?<mm>\\d{2})${NIR_SEP}(?<dept>\\d{2}|2[AaBb])` +
  `${NIR_SEP}(?<commune>\\d{3})${NIR_SEP}(?<order>\\d{3})`;

type NirGroups = { sex: string; yy: string; mm: string; dept: string; commune: string; order: string };

function body13(g: NirGroups): string {
  return `${g.sex}${g.yy}${g.mm}${g.dept}${g.commune}${g.order}`;
}

function isCorsica(g: NirGroups): boolean {
  return g.dept.toUpperCase() === "2A" || g.dept.toUpperCase() === "2B";
}

function plausibleNirStructure(g: NirGroups): boolean {
  const mm = Number(g.mm);
  // 01-12 is a real month; 20, 30-42 and 50-99 are the codes used when the
  // month of birth is unknown or the record was created from a reconstitution.
  const monthOk = (mm >= 1 && mm <= 12) || mm === 20 || (mm >= 30 && mm <= 42) || mm >= 50;
  if (!monthOk) return false;
  if (isCorsica(g)) return true;
  const d = Number(g.dept);
  return (d >= 1 && d <= 95) || d === 97 || d === 98 || d === 99;
}

/**
 * The 2-digit key of a NIR: 97 minus the first 13 digits mod 97.
 *
 * Corsica (department 2A / 2B) is NOT validated here. Its letters have to be
 * turned into numbers before the modulo and the substitution rule could not be
 * checked against a primary source when this was written, so shipping a
 * guessed rule would reject real numbers. A Corsican NIR is accepted on its
 * structure alone, which is safe because the letter inside a 15-character run
 * already makes the shape rare.
 */
export function nirKey(first13: string): number {
  return 97 - (Number(first13) % 97);
}

function keyMatches(g: NirGroups & { key: string }): boolean {
  return isCorsica(g) || nirKey(body13(g)) === Number(g.key);
}

/** `1 85 05 78 006 084 36` and friends, with the key checked (Corsica excepted). */
export function isValidNir(raw: string): boolean {
  const m = new RegExp(`^${NIR_BODY}${NIR_SEP}(?<key>\\d{2})$`, "u").exec(raw.trim());
  if (!m?.groups) return false;
  const g = m.groups as NirGroups & { key: string };
  return plausibleNirStructure(g) && keyMatches(g);
}

const NIR_STRICT = new RegExp(`${B}${NIR_BODY}${NIR_SEP}(?<key>\\d{2})${A}`, "gu");

/**
 * FRANCE. NIR, the 15-digit number a French social-security card carries:
 * 13 digits of structure and a 2-digit key. Accepted only with a valid key, so
 * no clinical number can be mistaken for one.
 */
export const detectNir: Detector = (text) => {
  const out: Span[] = [];
  for (const m of text.matchAll(NIR_STRICT)) {
    const g = m.groups as NirGroups & { key: string };
    if (plausibleNirStructure(g) && keyMatches(g)) {
      out.push(span(m.index, m.index + m[0].length, "NIR"));
    }
  }
  return out;
};

// Words that announce a NIR.
const NIR_KEYWORD =
  `${B}(?:carte\\s+vitale|s[ée]curit[ée]\\s+sociale|s[ée]cu|NIR|` +
  `n[°º]\\s?(?:de\\s+)?(?:ss|s[ée]cu)|num[ée]ro\\s+(?:de\\s+)?ss)${A}`;
// Up to 30 characters with no digit and no line break between keyword and
// number, so the number has to be the first one that follows the keyword.
// Lazy, so a leading character of the value is never swallowed by the filler.
const NIR_CONTEXT = new RegExp(
  `${NIR_KEYWORD}[^\\d\\n]{0,30}?(?<nir>${B}${NIR_BODY}(?:${NIR_SEP}\\d{2})?)${A}`,
  "giud",
);

/**
 * FRANCE. The number printed on a Carte Vitale, which is the NIR. Unlike
 * detectNir this one needs the keyword ("carte vitale", "sécurité sociale",
 * "NIR"...) but not a valid key, and accepts the 13-digit form without the key:
 * a parent who mistyped one digit still typed her identifier, and the keyword
 * is what makes it safe to say so. Structure is still checked.
 */
export const detectCarteVitale: Detector = (text) => {
  const out: Span[] = [];
  for (const m of text.matchAll(NIR_CONTEXT)) {
    const g = m.groups as NirGroups | undefined;
    const at = m.indices?.groups?.nir;
    if (g && at && plausibleNirStructure(g)) out.push(span(at[0], at[1], "NIR"));
  }
  return out;
};

// ---------------------------------------------------------------------------
// Phone numbers
// ---------------------------------------------------------------------------

// Not the middle of a longer number and not the tail of a decimal ("3.612...").
const PHONE_B = `${B}(?<!\\d[.,])`;
const PHONE_A = `${A}(?![.,]\\d)`;

// One separator, used consistently inside a number ("\\k<t>" repeats what was
// captured the first time, which may be nothing). Without that, a date followed
// by two digits ("01.02.2024 10") reads as a French phone number.
const PHONE_ES = new RegExp(
  `${PHONE_B}(?:(?:\\+|00)34[ .-]?)?[6-9]\\d{2}` +
    `(?:(?<t>[ -]?)\\d{3}\\k<t>\\d{3}|(?<s>[ .-]?)\\d{2}\\k<s>\\d{2}\\k<s>\\d{2})${PHONE_A}`,
  "gu",
);

/**
 * SPAIN. Nine digits starting 6-9, optionally behind +34 or 0034, written
 * 612345678, 612 345 678 or 612 34 56 78.
 *
 * The 3-3-3 grouping accepts space and dash but NOT dot: "650.000.000" is how
 * a count of cells is written with thousands separators, not a phone number.
 */
export const detectPhoneEs: Detector = (text) => rangesOf(text, PHONE_ES, "TELEFONO");

const PHONE_FR = new RegExp(
  `${PHONE_B}(?:(?:\\+|00)33[ .-]?[1-9]|0[1-9])(?<s>[ .-]?)\\d{2}(?:\\k<s>\\d{2}){3}${PHONE_A}`,
  "gu",
);

/**
 * FRANCE. Ten digits starting 01-09 grouped in pairs (06 12 34 56 78, with
 * spaces, dots or dashes), or +33 / 0033 followed by the nine digits without
 * the leading zero.
 */
export const detectPhoneFr: Detector = (text) => rangesOf(text, PHONE_FR, "TELEFONO");

const PHONE_INTL = new RegExp(`${PHONE_B}\\+[1-9]\\d{0,2}(?:[ .-]?\\d){7,12}${PHONE_A}`, "gu");

/**
 * ANY COUNTRY. `+` and a country code followed by 7 to 12 more digits. The
 * leading plus is what makes this safe: no clinical value is written with one.
 * Spanish and French numbers with their prefix are caught by the two detectors
 * above; this one is for the relatives abroad.
 */
export const detectPhoneInternational: Detector = (text) => rangesOf(text, PHONE_INTL, "TELEFONO");

// ---------------------------------------------------------------------------
// Email
// ---------------------------------------------------------------------------

const EMAIL = /[\p{L}\p{N}._%+-]+@[\p{L}\p{N}-]+(?:\.[\p{L}\p{N}-]+)*\.\p{L}{2,}/gu;

/** ANY COUNTRY. A pragmatic address pattern; a final full stop is not part of it. */
export const detectEmail: Detector = (text) => rangesOf(text, EMAIL, "EMAIL");

// ---------------------------------------------------------------------------
// Postal codes (contextual)
// ---------------------------------------------------------------------------

const CP_KEYWORD = "(?:c\\.?\\s?p\\.?|c[oó]digo\\s+postal|code\\s+postal)";
// What may sit between the keyword and the number: spaces, a colon, a dash, "nº".
const CP_GLUE = "[\\s:#.-]{0,3}";

function postalRegex(value: string): RegExp {
  return new RegExp(`${B}${CP_KEYWORD}${CP_GLUE}(?<cp>${value})${A}`, "giud");
}

// Spanish provinces run 01 to 52 (Ceuta 51, Melilla 52).
const CP_ES = postalRegex("(?:0[1-9]|[1-4]\\d|5[0-2])\\d{3}");
// French départements run 01 to 95, plus 97x and 98x overseas.
const CP_FR = postalRegex("(?:0[1-9]|[1-8]\\d|9[0-5]|9[78])\\d{3}");

function captured(text: string, re: RegExp, group: string, kind: Span["kind"]): Span[] {
  const out: Span[] = [];
  for (const m of text.matchAll(re)) {
    const g = m.indices?.groups?.[group];
    if (g) out.push(span(g[0], g[1], kind));
  }
  return out;
}

/**
 * SPAIN. Five digits, 01000-52999, only right after "CP", "C.P." or "código
 * postal". Without the keyword a five-digit number is far more likely to be a
 * count ("12500 leucocitos") than a postal code.
 */
export const detectPostalCodeEs: Detector = (text) => captured(text, CP_ES, "cp", "CODIGO_POSTAL");

/** FRANCE. Five digits, 01000-95999 and 97000-98999, only after "CP" or "code postal". */
export const detectPostalCodeFr: Detector = (text) => captured(text, CP_FR, "cp", "CODIGO_POSTAL");

// ---------------------------------------------------------------------------
// Date of birth (contextual)
// ---------------------------------------------------------------------------

const MONTHS = [
  // es
  "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
  "septiembre", "setiembre", "octubre", "noviembre", "diciembre",
  "ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sept?", "set", "oct", "nov", "dic",
  // fr
  "janvier", "f[ée]vrier", "mars", "avril", "mai", "juin", "juillet", "ao[uû]t",
  "septembre", "octobre", "novembre", "d[ée]cembre",
  "janv", "f[ée]vr", "avr", "juil", "d[ée]c",
  // en
  "january", "february", "march", "april", "may", "june", "july", "august",
  "september", "october", "november", "december", "jan", "apr", "aug", "dec",
].join("|");

// 12/03/2024, 12-03-24, 12.03.2024
const DATE_NUMERIC = "\\d{1,2}[/.-]\\d{1,2}[/.-]\\d{2,4}";
// 2024-03-12
const DATE_ISO = "\\d{4}-\\d{2}-\\d{2}";
// 12 de marzo de 2024, 12 mars 2024, 1er mars 2024
const DATE_DAY_MONTH = `\\d{1,2}(?:er|º|°)?\\s+(?:de\\s+|d['’]\\s?)?(?:${MONTHS})\\.?,?\\s+(?:de\\s+|del\\s+)?\\d{4}`;
// March 12, 2024
const DATE_MONTH_DAY = `(?:${MONTHS})\\.?\\s+\\d{1,2}(?:st|nd|rd|th)?,?\\s+\\d{4}`;

// Words that say "this date is a birth date". Ordered so the long forms win.
const BIRTH_KEYWORD =
  "(?:fecha\\s+de\\s+nacimiento|f\\.?\\s?(?:de\\s+)?nac(?:imiento)?\\.?|nacimiento|naci[óo]|nacid[oa]|fdn|" +
  "date\\s+de\\s+naissance|ddn|naissance|n[ée]e?(?:\\(e\\))?|" +
  "date\\s+of\\s+birth|birth\\s?date|birthday|dob|born|cumplea[ñn]os)";
// "nació el 12 de marzo", "née le 12/03/2024", "DOB: 12/03/2024": a colon or
// dash and the little article, nothing that could carry a second sentence.
const BIRTH_GLUE = "[\\s:=-]{0,3}(?:(?:el|le|la|on|en|the)\\s+)?(?:d[ií]a\\s+)?";

const BIRTH_DATE = new RegExp(
  `${B}${BIRTH_KEYWORD}${A}${BIRTH_GLUE}(?<date>${DATE_ISO}|${DATE_NUMERIC}|${DATE_DAY_MONTH}|${DATE_MONTH_DAY})${A}`,
  "giud",
);

/** Calendar sanity for the numeric forms, so "99/99/9999" is not a date. */
function plausibleNumericDate(s: string): boolean {
  const parts = s.split(/[/.-]/).map(Number);
  if (parts.length !== 3) return true; // textual forms were matched by a stricter pattern
  const [a, b, c] = parts;
  if (s.length >= 8 && /^\d{4}/.test(s)) return b >= 1 && b <= 12 && c >= 1 && c <= 31; // ISO
  return a >= 1 && a <= 31 && b >= 1 && b <= 12;
}

/**
 * ES / FR / EN. A date written right after a word that says it is a birth date
 * ("nació el", "fecha de nacimiento:", "née le", "date de naissance", "DOB").
 * Only the date is returned, so "nació el [FECHA_NACIMIENTO_1]" keeps its verb.
 *
 * This is the detector that matters most for not corrupting clinical text, and
 * the rule that protects it is the keyword: a date of a measurement, a vaccine
 * or a visit ("peso 8.350 kg el 15/03/2025") is never preceded by one of these
 * words, so it passes through untouched. A date of birth written with NO
 * keyword is not detected, and that is a deliberate price.
 *
 * Month and year alone ("marzo de 2024") is not masked: it is not a date of
 * birth, and parents say it constantly.
 */
export const detectBirthDate: Detector = (text) => {
  const out: Span[] = [];
  for (const m of text.matchAll(BIRTH_DATE)) {
    const g = m.indices?.groups?.date;
    if (g && plausibleNumericDate(text.slice(g[0], g[1]))) out.push(span(g[0], g[1], "FECHA_NACIMIENTO"));
  }
  return out;
};

// ---------------------------------------------------------------------------
// Spanish health card numbers (Tarjeta Sanitaria Individual)
// ---------------------------------------------------------------------------

// Source: Ministerio de Sanidad, "Modelos de tarjetas sanitarias en el SNS"
// (Plan VEO v3.0), which fixes the CIP-SNS and lists the CIP-AUT structure of
// every autonomous community and mutualidad.
//
//   CIP-SNS (national, same everywhere):  2 letters + 6 digits. The document
//     does not say in which order, so both are accepted.
//   CIP-AUT (assigned by each community, so the format varies):
//     Andalucía      AN + 10 digits, or 12 digits
//     Aragón         AR + 9 digits + 1 letter
//     Asturias       ASTU + 12 digits
//     Baleares       11 digits
//     Canarias, Cantabria, Castilla-La Mancha, La Rioja, Ceuta y Melilla,
//     Extremadura, Murcia, Castilla y León, Madrid
//                    4 letters + 12 digits (Extremadura CAEX, Murcia CARM)
//     Castilla y León  also CYL + 10 digits
//     Cataluña       4 letters + 10 digits
//     C. Valenciana  7 or 8 digits
//     Galicia        6 digits + 4 letters + 4 digits
//     Madrid         also 10 digits
//     Navarra, País Vasco   8 digits
//     ISFAS, MUFACE, MUGEJU  ISFS / MFCE / MGJU + 12 digits
//
// Shapes that carry letters identify themselves and are accepted on sight.
// Shapes that are only digits are accepted after a keyword.
const SELF_IDENTIFYING =
  "[A-Z]{4} ?\\d{4} ?\\d{4} ?(?:\\d{4}|\\d{2})" + // 4 letters + 12 or 10 digits
  "|AN ?\\d{10}|AR ?\\d{9}[A-Z]|CYL ?\\d{10}" +
  "|\\d{6} ?[A-Z]{4} ?\\d{4}"; // Galicia

const HEALTH_CARD_SELF = new RegExp(`${B}(?:${SELF_IDENTIFYING})${A}`, "gu");

const HEALTH_CARD_KEYWORD =
  `${B}(?:tarjeta\\s+sanitaria(?:\\s+individual)?|targeta\\s+sanit[àa]ria|TSI|` +
  `CIP(?:[-\\s]?(?:SNS|AUT|M|A))?|SIP)${A}`;
// Bare digits after the keyword: 7-8 (Valencia, Navarra, País Vasco), 10
// (Madrid), 11 (Baleares), 12 (Andalucía), optionally grouped by single
// spaces. Nine is excluded on purpose, it is a phone number.
const DIGITS_ONLY = "\\d(?: ?\\d){6,11}";
const CIP_SNS = "[A-Z]{2}\\d{6}|\\d{6}[A-Z]{2}";
const HEALTH_CARD_CONTEXT = new RegExp(
  `${HEALTH_CARD_KEYWORD}[^\\d\\n]{0,30}?${B}(?<card>${SELF_IDENTIFYING}|${CIP_SNS}|${DIGITS_ONLY})${A}`,
  "giud",
);

function plausibleDigitOnlyHealthCard(card: string): boolean {
  if (!/^\d[\d ]*$/.test(card)) return true; // a lettered shape, matched as such
  const n = card.replace(/ /g, "").length;
  return n === 7 || n === 8 || n === 10 || n === 11 || n === 12;
}

/**
 * SPAIN. Health card numbers (CIP-SNS and the regional CIP-AUT), see the table
 * above. Lettered formats are caught anywhere in the text, digit-only ones only
 * after "tarjeta sanitaria", "TSI", "CIP" or "SIP".
 *
 * The Spanish Social Security affiliation number (12 digits, NUSS) is a
 * different number and is NOT detected: its check-digit rule could not be
 * confirmed from a primary source.
 */
export const detectHealthCardEs: Detector = (text) => {
  const out: Span[] = rangesOf(text, HEALTH_CARD_SELF, "TARJETA_SANITARIA");
  for (const m of text.matchAll(HEALTH_CARD_CONTEXT)) {
    const g = m.indices?.groups?.card;
    if (g && plausibleDigitOnlyHealthCard(text.slice(g[0], g[1]))) {
      out.push(span(g[0], g[1], "TARJETA_SANITARIA"));
    }
  }
  return out;
};

// ---------------------------------------------------------------------------

function rangesOf(text: string, re: RegExp, kind: Span["kind"]): Span[] {
  const out: Span[] = [];
  for (const m of text.matchAll(re)) out.push(span(m.index, m.index + m[0].length, kind));
  return out;
}

/**
 * Every detector with the priority it wins overlaps with (higher wins). Two
 * detectors can legitimately claim the same characters, e.g. a French NIR is
 * found by both detectNir and detectCarteVitale, and a number inside an email
 * address could look like a phone number; the order below decides.
 */
export const PATTERN_DETECTORS: ReadonlyArray<{ name: string; priority: number; detect: Detector }> = [
  { name: "dni", priority: 90, detect: detectDni },
  { name: "nie", priority: 90, detect: detectNie },
  { name: "nir", priority: 90, detect: detectNir },
  { name: "carteVitale", priority: 85, detect: detectCarteVitale },
  { name: "healthCardEs", priority: 80, detect: detectHealthCardEs },
  { name: "email", priority: 70, detect: detectEmail },
  { name: "phoneInternational", priority: 60, detect: detectPhoneInternational },
  { name: "phoneEs", priority: 60, detect: detectPhoneEs },
  { name: "phoneFr", priority: 60, detect: detectPhoneFr },
  { name: "birthDate", priority: 50, detect: detectBirthDate },
  { name: "postalCodeEs", priority: 40, detect: detectPostalCodeEs },
  { name: "postalCodeFr", priority: 40, detect: detectPostalCodeFr },
];
