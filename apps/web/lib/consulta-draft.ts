// The consult recording, kept on the device while it is being made.
//
// MediaRecorder hands over a chunk every 10 s and the recorder kept them only
// in memory: a reload, a closed tab or a phone that killed the backgrounded
// tab lost the whole visit, which cannot be repeated (QA 2026-11-12, 6/6).
// Each chunk is now also written here, and the recorder offers to upload what
// is left the next time it opens. Since the verification QA of 2026-11-13 a
// chunk comes every second, plus one when the page is hidden or unloads: with
// 10 s chunks a reload at 15 s lost the doctor's last answer and one at 6 s
// lost the visit. The draft is cleared after a 2xx upload,
// when the professional objects (kill switch) and when she discards it, so
// audio stays on the device only while it is the one copy of a visit.
//
// Every call swallows its own failure: private mode, a full disk or a browser
// without IndexedDB must never stop a recording, they only lose this backup.
//
// A draft older than DRAFT_TTL_MS is deleted when it is read instead of
// offered. Without it, a draft that belongs to another account on a shared
// phone (never offered here, see DraftMeta.profileId) stayed on the device
// for good. Seven days is what the server keeps a consult audio whose
// transcription failed (privacy.retentionBody).

const DB_NAME = "adelia-consulta";
const STORE = "draft";
const META_KEY = "meta";
export const DRAFT_TTL_MS = 7 * 24 * 60 * 60 * 1000;

export type DraftMeta = {
  mime: string;
  /** Whose visit it is. The draft is only offered back when this profile is
   * one of the signed-in account's, so a shared phone never hands one
   * family's recording to another account. */
  profileId: string | null;
  startedAt: number;
  /** The consent wording she accepted when she recorded. An upload days later
   * must report that version, not the one current at upload time. */
  policyVersion?: string;
};

type StoredChunk = { type: string; bytes: ArrayBuffer };

function open(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(STORE);
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function run<T>(
  mode: IDBTransactionMode,
  body: (store: IDBObjectStore) => IDBRequest<T> | void,
): Promise<T | undefined> {
  const db = await open();
  try {
    return await new Promise<T | undefined>((resolve, reject) => {
      const tx = db.transaction(STORE, mode);
      const req = body(tx.objectStore(STORE));
      tx.oncomplete = () => resolve(req ? req.result : undefined);
      tx.onerror = () => reject(tx.error);
      tx.onabort = () => reject(tx.error);
    });
  } finally {
    db.close();
  }
}

function chunkKey(seq: number): string {
  // Zero-padded so the keys sort in recording order.
  return `chunk-${String(seq).padStart(6, "0")}`;
}

/** Start a new draft: whatever an earlier one held is gone. */
export async function draftStart(meta: DraftMeta): Promise<void> {
  try {
    await run("readwrite", (store) => {
      store.clear();
      store.put(meta, META_KEY);
    });
  } catch {
    /* no backup on this device; the recording itself goes on */
  }
}

export async function draftAppend(seq: number, chunk: Blob): Promise<void> {
  try {
    // Bytes, not the Blob: older WebKit could not store a Blob in IndexedDB.
    const stored: StoredChunk = { type: chunk.type, bytes: await chunk.arrayBuffer() };
    await run("readwrite", (store) => {
      store.put(stored, chunkKey(seq));
    });
  } catch {
    /* see draftStart */
  }
}

export async function draftClear(): Promise<void> {
  try {
    await run("readwrite", (store) => {
      store.clear();
    });
  } catch {
    /* nothing stored, nothing to clear */
  }
}

/** The interrupted recording, if a draft with at least one chunk exists and is
 * younger than DRAFT_TTL_MS. An older one is deleted, not offered.
 *
 * One readonly transaction for the meta and every chunk. It used to open the
 * database once per chunk (about 180 opens for a 30-minute visit), and the
 * recorder keeps "Grabar" disabled until this answers: a start that ran
 * first queued draftStart, whose clear() erased the visit before it was ever
 * offered. */
export async function draftLoad(
  now = Date.now(),
): Promise<{ meta: DraftMeta; blob: Blob } | null> {
  try {
    if (typeof indexedDB === "undefined") return null;
    const db = await open();
    let meta: DraftMeta | undefined;
    let chunks: StoredChunk[] = [];
    try {
      await new Promise<void>((resolve, reject) => {
        const tx = db.transaction(STORE, "readonly");
        const store = tx.objectStore(STORE);
        const metaReq = store.get(META_KEY);
        // getAll returns values in key order: the zero-padded chunk keys
        // are the recording order. The range is built here, not at module
        // level: this module is also imported while the page renders on the
        // server, where IDBKeyRange does not exist.
        const chunksReq = store.getAll(IDBKeyRange.bound("chunk-", "chunk-\uffff"));
        tx.oncomplete = () => {
          meta = metaReq.result as DraftMeta | undefined;
          chunks = (chunksReq.result ?? []) as StoredChunk[];
          resolve();
        };
        tx.onerror = () => reject(tx.error);
        tx.onabort = () => reject(tx.error);
      });
    } finally {
      db.close();
    }
    if (!meta || chunks.length === 0) return null;
    if (!(now - meta.startedAt < DRAFT_TTL_MS)) {
      await draftClear();
      return null;
    }
    const parts: BlobPart[] = chunks.map((c) => c.bytes);
    return { meta, blob: new Blob(parts, { type: meta.mime || "audio/webm" }) };
  } catch {
    return null;
  }
}
