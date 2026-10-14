import { expect, test } from "@playwright/test";

import { streamChat, type StreamEvent } from "@/lib/chat-client-browser";
import {
  forgetRedactionState,
  isLocalRedactionEnabled,
  redactOutgoingQuestion,
} from "@/lib/redaction/chat";

// streamChat is the one place the question leaves the browser for the chat API,
// and the one call site of local redaction. These tests drive the REAL
// streamChat with a stubbed fetch, so what is asserted is the request the API
// would receive and the events the UI would render, not a copy of the logic.

const FLAG = "NEXT_PUBLIC_LOCAL_REDACTION";

type Captured = { url: string; init: RequestInit };

function sse(events: Array<[string, unknown]>): string {
  return events.map(([name, data]) => `event: ${name}\r\ndata: ${JSON.stringify(data)}\r\n\r\n`).join("");
}

/** Replace fetch for one test, record the request, answer with `body` in `pieces`. */
async function withStubbedFetch<T>(
  body: string,
  run: (captured: Captured[]) => Promise<T>,
  pieces = 1,
): Promise<T> {
  const original = globalThis.fetch;
  const captured: Captured[] = [];
  globalThis.fetch = (async (url: unknown, init?: RequestInit) => {
    captured.push({ url: String(url), init: init ?? {} });
    const encoder = new TextEncoder();
    const size = Math.ceil(body.length / pieces);
    const parts = Array.from({ length: pieces }, (_, i) => body.slice(i * size, (i + 1) * size));
    return new Response(
      new ReadableStream({
        start(controller) {
          for (const part of parts) controller.enqueue(encoder.encode(part));
          controller.close();
        },
      }),
      { status: 200, headers: { "Content-Type": "text/event-stream" } },
    );
  }) as typeof fetch;
  try {
    return await run(captured);
  } finally {
    globalThis.fetch = original;
  }
}

async function collect(gen: AsyncGenerator<StreamEvent>): Promise<StreamEvent[]> {
  const out: StreamEvent[] = [];
  for await (const e of gen) out.push(e);
  return out;
}

function tokens(events: StreamEvent[]): string {
  return events.map((e) => (e.type === "token" ? e.content : "")).join("");
}

test.beforeEach(() => {
  forgetRedactionState();
});

test.afterEach(() => {
  delete process.env[FLAG];
});

const PLAIN_ANSWER = sse([
  ["start", { session_id: "s1" }],
  ["token", { content: "Hola " }],
  ["token", { content: "de nuevo" }],
  ["final", { session_id: "s1", citations: [], evidence_citations: [] }],
]);

test.describe("flag OFF (the default): the request is what it always was", () => {
  test("the flag is off when the variable is unset, empty, or anything but on", () => {
    delete process.env[FLAG];
    expect(isLocalRedactionEnabled()).toBe(false);
    for (const value of ["", "0", "false", "off", "no", "2", "yes please"]) {
      process.env[FLAG] = value;
      expect(isLocalRedactionEnabled(), value).toBe(false);
    }
    for (const value of ["1", "true", "TRUE", "on", " 1 "]) {
      process.env[FLAG] = value;
      expect(isLocalRedactionEnabled(), value).toBe(true);
    }
  });

  test("the body is byte-identical to the one built before redaction existed", async () => {
    delete process.env[FLAG];
    await withStubbedFetch(PLAIN_ANSWER, async (captured) => {
      await collect(streamChat("¿Puede tomar paracetamol?", null, "es"));
      expect(captured).toHaveLength(1);
      // The literal below is what `JSON.stringify({ session_id, question,
      // locale, profile_id: profileId ?? null })` produced before this change.
      expect(captured[0].init.body).toBe(
        '{"session_id":null,"question":"¿Puede tomar paracetamol?","locale":"es","profile_id":null}',
      );
      expect(captured[0].url).toBe("/api/backend/chat");
      expect(captured[0].init.method).toBe("POST");
      expect(captured[0].init.headers).toEqual({
        "Content-Type": "application/json",
        Accept: "text/event-stream",
      });
    });
  });

  test("identifiers in the question are sent as typed, with a session and a profile", async () => {
    process.env[FLAG] = "0";
    const question = "Mi DNI es 12345678Z, llamad al 612 345 678. Nació el 12/03/2024. Tiene 38.2 °C.";
    await withStubbedFetch(PLAIN_ANSWER, async (captured) => {
      await collect(streamChat(question, "sess-9", "fr", undefined, "profile-3"));
      expect(captured[0].init.body).toBe(
        JSON.stringify({ session_id: "sess-9", question, locale: "fr", profile_id: "profile-3" }),
      );
      expect(JSON.parse(String(captured[0].init.body))).toEqual({
        session_id: "sess-9",
        question,
        locale: "fr",
        profile_id: "profile-3",
      });
    });
  });

  test("the answer is passed through untouched, placeholders and all", async () => {
    delete process.env[FLAG];
    const body = sse([
      ["start", { session_id: "s1" }],
      ["token", { content: "Hola [NOMBRE_1]" }],
      ["final", { session_id: "s1", citations: [], evidence_citations: [] }],
    ]);
    await withStubbedFetch(body, async () => {
      const events = await collect(streamChat("hola", null, "es"));
      expect(tokens(events)).toBe("Hola [NOMBRE_1]");
      expect(events.map((e) => e.type)).toEqual(["start", "token", "final"]);
    });
  });
});

test.describe("flag ON: redacted going out, rehydrated coming back", () => {
  test.beforeEach(() => {
    process.env[FLAG] = "1";
  });

  test("the request carries the redacted text and nothing identifying", async () => {
    const question = "Mi DNI es 12345678Z y mi móvil 612 345 678. Tiene 38.2 °C y pesa 8.350 kg.";
    await withStubbedFetch(PLAIN_ANSWER, async (captured) => {
      await collect(streamChat(question, null, "es", undefined, "profile-3"));
      const sent = String(captured[0].init.body);
      expect(sent).not.toContain("12345678Z");
      expect(sent).not.toContain("612 345 678");
      expect(JSON.parse(sent)).toEqual({
        session_id: null,
        question: "Mi DNI es [DNI_1] y mi móvil [TELEFONO_1]. Tiene 38.2 °C y pesa 8.350 kg.",
        locale: "es",
        profile_id: "profile-3",
      });
    });
  });

  test("a question with nothing to hide goes out unchanged, the same bytes as with the flag off", async () => {
    const question = "¿Cuánto paracetamol le toca? Pesa 8.350 kg y tiene 38.2 °C.";
    let withFlag = "";
    let without = "";
    await withStubbedFetch(PLAIN_ANSWER, async (captured) => {
      await collect(streamChat(question, null, "es"));
      withFlag = String(captured[0].init.body);
    });
    delete process.env[FLAG];
    await withStubbedFetch(PLAIN_ANSWER, async (captured) => {
      await collect(streamChat(question, null, "es"));
      without = String(captured[0].init.body);
    });
    expect(withFlag).toBe(without);
  });

  test("the answer is rehydrated, including a placeholder split across tokens", async () => {
    const body = sse([
      ["start", { session_id: "s1" }],
      ["token", { content: "Tu DNI " }],
      ["token", { content: "[DN" }],
      ["token", { content: "I_1] consta, y el tel" }],
      ["token", { content: "éfono [TELEFONO_1]." }],
      ["final", { session_id: "s1", citations: [], evidence_citations: [] }],
    ]);
    await withStubbedFetch(body, async () => {
      const events = await collect(streamChat("DNI 12345678Z, tel 612 345 678", null, "es"));
      expect(tokens(events)).toBe("Tu DNI 12345678Z consta, y el teléfono 612 345 678.");
      expect(events.some((e) => e.type === "token" && e.content.includes("[DN"))).toBe(false);
      expect(events[events.length - 1].type).toBe("final");
    });
  });

  test("the whole stream also works when the network delivers it in tiny pieces", async () => {
    const body = sse([
      ["start", { session_id: "s1" }],
      ["token", { content: "Hola [NOMBRE_1], " }],
      ["token", { content: "tu DNI [DNI_1]." }],
      ["final", { session_id: "s1", citations: [], evidence_citations: [] }],
    ]);
    await withStubbedFetch(
      body,
      async () => {
        const events = await collect(streamChat("DNI 12345678Z", null, "es"));
        expect(tokens(events)).toBe("Hola [NOMBRE_1], tu DNI 12345678Z.");
      },
      40,
    );
  });

  test("a placeholder held back when the stream ends without a final event is not lost", async () => {
    const body = sse([
      ["start", { session_id: "s1" }],
      ["token", { content: "fin [NOMBRE_" }],
    ]);
    await withStubbedFetch(body, async () => {
      const events = await collect(streamChat("hola", null, "es"));
      expect(tokens(events)).toBe("fin [NOMBRE_");
    });
  });

  test("citations and the session id pass through unchanged", async () => {
    const body = sse([
      ["start", { session_id: "s1" }],
      ["token", { content: "x" }],
      [
        "final",
        {
          session_id: "s1",
          citations: [{ chunk_id: "c1", document_id: "d1", raw_quote: "Hb 12.5 g/dL", page: 2 }],
          evidence_citations: [],
        },
      ],
    ]);
    await withStubbedFetch(body, async () => {
      const events = await collect(streamChat("hola", null, "es"));
      const final = events.find((e) => e.type === "final") as Extract<StreamEvent, { type: "final" }>;
      expect(final.session_id).toBe("s1");
      expect(final.citations[0].raw_quote).toBe("Hb 12.5 g/dL");
    });
  });

  test("a conversation keeps its numbering: the second message continues from the first", async () => {
    await withStubbedFetch(PLAIN_ANSWER, async (captured) => {
      await collect(streamChat("Mi DNI es 12345678Z", null, "es"));
      // The server said session s1; the next message belongs to it.
      await collect(streamChat("El de mi pareja es 87654321X y el mío 12345678Z", "s1", "es"));
      expect(JSON.parse(String(captured[1].init.body)).question).toBe(
        "El de mi pareja es [DNI_2] y el mío [DNI_1]",
      );
    });
  });

  test("a model that is available adds names; one that is not changes nothing else", async () => {
    const detect = async (text: string) => {
      const at = text.indexOf("Valentina");
      return at < 0 ? [] : [{ start: at, end: at + 9, kind: "NOMBRE" as const, score: 0.99 }];
    };
    const withModel = await redactOutgoingQuestion("Mi hija Valentina, DNI 12345678Z", null, { detect });
    expect(withModel.question).toBe("Mi hija [NOMBRE_1], DNI [DNI_1]");
    const without = await redactOutgoingQuestion("Mi hija Valentina, DNI 12345678Z", null, {
      detect: async () => [],
    });
    expect(without.question).toBe("Mi hija Valentina, DNI [DNI_1]");
  });

  test("no model and no WebGPU in this environment: the patterns alone still redact", async () => {
    // No `detect` injected: the real detector, which finds no WebGPU here.
    const redaction = await redactOutgoingQuestion("DNI 12345678Z", null);
    expect(redaction.question).toBe("DNI [DNI_1]");
  });
});
