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
