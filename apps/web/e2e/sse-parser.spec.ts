import { expect, test } from "@playwright/test";

import { parseBufferBlocks } from "@/lib/chat-types";

test("SSE parser handles CRLF event separators (regression)", () => {
  // sse-starlette separates events with \r\n\r\n — the bug was that the parser
  // only split on \n\n, so tokens arrived but never rendered.
  const raw =
    'event: start\r\ndata: {"session_id":"s1"}\r\n\r\n' +
    'event: token\r\ndata: {"content":"Hola"}\r\n\r\n' +
    'event: token\r\ndata: {"content":" mundo"}\r\n\r\n';
  let buf = raw;
  const events = [...parseBufferBlocks(() => buf, (rest) => { buf = rest; })];
  const tokens = events.filter((e) => e.type === "token").map((e: any) => e.content);
  expect(tokens).toEqual(["Hola", " mundo"]);
  expect(events.find((e) => e.type === "start")).toBeTruthy();
});

test("SSE parser still handles plain LF separators", () => {
  const raw = 'event: token\ndata: {"content":"x"}\n\n';
  let buf = raw;
  const events = [...parseBufferBlocks(() => buf, (rest) => { buf = rest; })];
  expect(events.filter((e) => e.type === "token").map((e: any) => e.content)).toEqual(["x"]);
});
