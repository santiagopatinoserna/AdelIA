// Clinical quantities: the one thing the redactor must never touch.
//
// A redactor that eats "38.2" is worse than no redactor: the answer would be
// computed from a text whose fever, dose or lab value is gone, and the parent
// would not know. So every detector in patterns.ts has a format strict enough
// not to match a measurement by construction, and redact() ALSO asks this
// module for the measurements in the text and refuses any hit that overlaps
// one. Two independent guards, because the cost of a mistake is asymmetric.
//
// Two classes of quantity are distinguished:
//   - "dose":    amounts of a medicine (mg, ml, UI, gotas, comprimidos...).
//   - "measure": everything else (kg, cm, %, degrees, mmHg, lab units, counts).
// The model-backed layer needs the difference. A named-entity model reads
// "Dalsy 100 mg" as a person, and a capitalised word right before a dose is
// almost always a drug, so redact() rejects model hits that sit in front of a
// dose. It deliberately does NOT do that for measures, because "Lucía 5 kg" is
// how parents really type a child's name and weight.
//
// Ages ("4 meses", "2 años") are not clinical quantities here: they are not
// identifying on their own and must never veto a name that precedes them.

export type ClinicalValue = {
  start: number;
  end: number;
  kind: "dose" | "measure";
};

// Regex alternation takes the FIRST branch that lets the whole pattern match,
// not the longest, so a bare "mg" listed ahead of "mg/dL" would claim
// "90 mg/dL" as a dose and stop short of the "/dL". Compound units therefore
// come first, in each class, and the simple ones after them.
const DOSE_COMPOUND = [
  "mg\\s?/\\s?kg(?:\\s?/\\s?(?:d[ií]a|dosis|toma|h))?",
  "mg\\s?/\\s?\\d+(?:[.,]\\d+)?\\s?ml",
  "mg\\s?/\\s?ml",
];

const MEASURE_COMPOUND = [
  // lab units, written the way Spanish and French reports write them
  "g\\s?/\\s?d[lL]",
  "mg\\s?/\\s?d[lL]",
  "g\\s?/\\s?[lL]",
  "mmol\\s?/\\s?[lL]",
  "mEq\\s?/\\s?[lL]",
  "[µμu]mol\\s?/\\s?[lL]",
  "ng\\s?/\\s?m[lL]",
  "pg\\s?/\\s?m[lL]",
  "(?:UI|U)\\s?/\\s?[lL]",
  "(?:x\\s?)?10\\^?\\d{1,2}\\s?/\\s?[µμu]?[lL]",
  "/\\s?(?:[µμu]\\s?[lL]|mm3|mm³)",
  "lat(?:idos)?\\s?/\\s?min",
  "resp(?:iraciones)?\\s?/\\s?min",
];

const DOSE_SIMPLE = [
  "mcg",
  "[µμ]g",
  "ug",
  "mg",
  "ml",
  "cc",
  "ui",
  "iu",
  "gotas?",
  "gouttes?",
  "comprimidos?",
  "comprim[ée]s?",
  "sobres?",
  "puffs?",
  "dosis",
  "supositorios?",
];

const MEASURE_SIMPLE = [
  "mmHg",
  "mmol",
  "mEq",
  // body measures
  "kg",
  "g",
  "cm",
  "mm",
  "d[lL]",
  "[lL]",
  "kcal",
  // vital signs
  "bpm",
  "lpm",
  "rpm",
  "%",
  "[°º]\\s?[cCfF]",
  "[°º]",
  "grados",
];

const UNIT_ALTERNATION = [
  ...DOSE_COMPOUND,
  ...MEASURE_COMPOUND,
  ...DOSE_SIMPLE,
  ...MEASURE_SIMPLE,
].join("|");
const DOSE_SET = new RegExp(`^(?:${[...DOSE_COMPOUND, ...DOSE_SIMPLE].join("|")})$`, "iu");

// number [range] [space] unit. The number may carry thousands separators
// ("12.500/µL"), a decimal comma or point ("38,2"), and be half of a range
// ("10-15 mg/kg"). The left boundary stops us starting in the middle of a
// longer token; the right one stops "5 gr" from reading as "5 g".
const QUANTITY = new RegExp(
  "(?<![\\p{L}\\p{N}_])" +
    "\\d+(?:[.,]\\d+)*" +
    "(?:\\s?[-–]\\s?\\d+(?:[.,]\\d+)*)?" +
    `\\s?(${UNIT_ALTERNATION})` +
    "(?![\\p{L}\\p{N}_])",
  "giu",
);

/**
 * Every medicine dose or clinical measurement in `text`, in order.
 *
 * Deliberately a recogniser of "number + unit" and nothing broader: a bare
 * number with no unit is not claimed (it could be a house number, and the
 * detectors do not match bare numbers anyway).
 */
export function findClinicalValues(text: string): ClinicalValue[] {
  const out: ClinicalValue[] = [];
  for (const m of text.matchAll(QUANTITY)) {
    const unit = m[1];
    out.push({
      start: m.index,
      end: m.index + m[0].length,
      kind: DOSE_SET.test(unit) ? "dose" : "measure",
    });
  }
  return out;
}
