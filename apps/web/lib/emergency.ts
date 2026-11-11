// The number to call in an urgent answer, and whether an answer is one.
//
// The number is read from the fixed red-flag frame of the API
// (answer_contract.red_flag_reply: "Llama al {number}" / "Call {number}" /
// "Appelez le {number}"), which already carries the country's number, never
// from a model's text: a number elsewhere in an answer is not a phone. The
// demo and the panel both draw their «Llamar al 112» from here (UX_PRINCIPLES
// 13; the panel only had it as text until the 2026-11-11 usability run).
const EMERGENCY_FRAME = /(?:Llama al|Call|Appelez le) (\d{2,3})\b/;

export function emergencyNumber(answer: string): string | null {
  return EMERGENCY_FRAME.exec(answer)?.[1] ?? null;
}

/**
 * The guard marks its referral in the citation it sends with it
 * (clinical/red_flags.citation_for, `red_flag:<code>`): the panel's turns
 * carry no `kind`, and this is how the web tells an urgency from a plan.
 */
export function isRedFlag(evidence: { source_id?: string | null }[]): boolean {
  return evidence.some((e) => e.source_id?.startsWith("red_flag:"));
}

/** The number to call for this panel turn, or null when it is not the guard's referral. */
export function urgentCallNumber(answer: string, evidence: { source_id?: string | null }[]): string | null {
  return isRedFlag(evidence) ? emergencyNumber(answer) : null;
}
