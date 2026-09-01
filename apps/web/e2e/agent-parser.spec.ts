import { test, expect } from "@playwright/test";

import { parseAgentBlocks } from "@/lib/agent-types";

function collect(raw: string) {
  let buffer = raw;
  return [...parseAgentBlocks(() => buffer, (rest) => { buffer = rest; })];
}

test("parses token and card events", () => {
  const raw =
    'event: token\ndata: {"content":"Hola"}\n\n' +
    'event: card\ndata: {"card":{"type":"lab","id":"l1","payload":{"flag":"low"},"actions":[]}}\n\n';
  const events = collect(raw);
  expect(events[0]).toEqual({ type: "token", content: "Hola" });
  expect(events[1]).toMatchObject({ type: "card", card: { type: "lab", id: "l1" } });
});

test("ignores unknown events", () => {
  const events = collect('event: mystery\ndata: {}\n\n');
  expect(events).toHaveLength(0);
});

test("the final frame carries both citation namespaces (audit 3.7)", () => {
  // Before item 3.7 the terminal frame was `{}`: the answer contract asked
  // the model for [ev_N] markers on a surface with no citation channel, so
  // every marker on /dashboard pointed at nothing.
  const raw =
    'event: final\ndata: {"citations":[{"chunk_id":"c1"}],' +
    '"evidence_citations":[{"tag":"ev_1","title":"NICE NG143"}]}\n\n';
  const [event] = collect(raw) as any[];
  expect(event.type).toBe("final");
  expect(event.citations).toHaveLength(1);
  expect(event.evidence_citations[0].tag).toBe("ev_1");
});

test("a final frame with no citations yields empty arrays, not undefined", () => {
  const [event] = collect('event: final\ndata: {}\n\n') as any[];
  expect(event.citations).toEqual([]);
  expect(event.evidence_citations).toEqual([]);
});
