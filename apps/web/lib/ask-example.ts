// Which "Pregunta con citas" example the panel offers, by the age of the child
// on screen. There used to be one sentence for every account, "¿Es normal que
// con 13 meses solo quiera leche materna?", and the supervisor saw it under
// Lucía, 5 months, on 2026-11-06: a question about another age reads as a
// template and undoes the one thing the panel has to say, that AdelIA knows
// her baby. So the example names no age and is a question mothers really ask
// in that band; each one is a golden group A topic (clinical/golden.py: A14
// reflux, A2 vegetables, A11 breastfeeding past a year), so the tap that sends
// it lands on a cited answer.
//
//   young    0-5 months, milk only: spitting up after feeds.
//   solids   6-11 months, first foods: refusing vegetables.
//   toddler  12-24 months: still wanting only the breast.
//   noAge    no birth date, or a profile past 24 months (her own row): a
//            question that fits any age instead of a guess.
export type AskExampleKey = "young" | "solids" | "toddler" | "noAge";

export function askExampleKey(months: number | null): AskExampleKey {
  if (months === null || months < 0 || months > 24) return "noAge";
  if (months < 6) return "young";
  if (months < 12) return "solids";
  return "toddler";
}
