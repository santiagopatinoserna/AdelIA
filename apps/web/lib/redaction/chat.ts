// The bridge between the chat client and the redaction primitive.
//
// OFF BY DEFAULT. Nothing in this file runs unless NEXT_PUBLIC_LOCAL_REDACTION
// is "1", "true" or "on" when the web app is BUILT (Next inlines NEXT_PUBLIC_
// variables, so it is a build-time switch, and the Dockerfile does not pass it
// on). With the flag off, streamChat never calls into this module past
// isLocalRedactionEnabled(), the request body is byte-identical to what it was
// before this existed, and the model is never imported.
//
// What it does when ON, for one question:
//   1. redact the question (patterns, plus the model's person spans if the
//      model is ready), seeded with the mapping of the conversation so far;
//   2. let streamChat send the redacted text;
//   3. rehydrate every token of the answer on the way back, so the parent reads
//      her child's name and the server never saw it.
//
// KNOWN LIMITS, all of them reasons the flag stays off until someone decides:
//   - The mapping lives in memory, per tab. A reloaded page, or a conversation
//     reopened from the sidebar, shows the placeholders the server stored,
//     because getChatSession returns what the server has, and a conversation
//     continued after a reload starts numbering again from 1. Fixing that means
//     persisting identifiers on the device, which is a privacy decision.
//   - The server stores the REDACTED question and answer. That is the intent,
//     and it is also why this changes what the history looks like.
//   - A model that rewrites a placeholder ("[nombre_1]", "[NOMBRE 1]") defeats
//     rehydration for that occurrence. Only measurement can say how often.
//   - If redaction itself throws, the error propagates and the question is NOT
//     sent: failing closed is the only behaviour consistent with the claim.

import type { StreamEvent } from "../chat-types";
import { detectEntities } from "./ner";
import { redact } from "./redact";
import { createStreamRehydrator } from "./rehydrate";
import type { RedactionMap, Span } from "./types";

/** Build-time switch. A function, not a constant, so a test can flip the env. */
export function isLocalRedactionEnabled(): boolean {
  const v = process.env.NEXT_PUBLIC_LOCAL_REDACTION?.trim().toLowerCase();
  return v === "1" || v === "true" || v === "on";
}

export type ChatRedaction = {
  /** What to put in the request instead of the parent's question. */
  question: string;
  /** Rehydrates token events and binds the session id; pass the parsed stream through it. */
  events(source: Iterable<StreamEvent>): Generator<StreamEvent>;
  /** Anything still held back when the stream ended without a terminal event. */
  finish(): StreamEvent[];
};

// session id -> mapping so far. Per tab, in memory, never persisted (see top).
const conversations = new Map<string, RedactionMap>();

/** Forget every mapping. For tests, and for a future "sign out". */
export function forgetRedactionState(): void {
  conversations.clear();
}

export type OutgoingDeps = {
  detect?: (text: string) => Promise<Span[]>;
  names?: readonly string[];
};

export async function redactOutgoingQuestion(
  question: string,
  sessionId: string | null,
  deps: OutgoingDeps = {},
): Promise<ChatRedaction> {
  const detect = deps.detect ?? detectEntities;
  const seed = (sessionId && conversations.get(sessionId)) || {};
  const modelSpans = await detect(question);
  const result = redact(question, { seed, names: deps.names, modelSpans });

  if (sessionId) conversations.set(sessionId, result.map);
  const rehydrator = createStreamRehydrator(result.map);

  const held = () => {
    const rest = rehydrator.flush();
    return rest ? ({ type: "token", content: rest } as const) : null;
  };

  return {
    question: result.text,
    *events(source) {
      for (const event of source) {
        if (event.type === "token") {
          const content = rehydrator.push(event.content);
          if (content) yield { ...event, content };
          continue;
        }
        // Anything that is not a token ends the run of text, so whatever was
        // waiting for the rest of a placeholder is released before it.
        const rest = held();
        if (rest) yield rest;
        if (event.type === "start") conversations.set(event.session_id, result.map);
        yield event;
      }
    },
    finish() {
      const rest = held();
      return rest ? [rest] : [];
    },
  };
}
