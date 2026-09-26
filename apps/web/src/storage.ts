const DB = "ntu-course-agent";
const STORE = "audio-parts";

export type StoredPart = { key: string; sessionId: string; sequence: number; blob: Blob; uploaded: boolean };

function database(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB, 1);
    request.onupgradeneeded = () => request.result.createObjectStore(STORE, { keyPath: "key" });
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

export async function putPart(part: StoredPart) {
  const db = await database();
  return new Promise<void>((resolve, reject) => {
    const tx = db.transaction(STORE, "readwrite");
    tx.objectStore(STORE).put(part); tx.oncomplete = () => resolve(); tx.onerror = () => reject(tx.error);
  });
}

export async function pendingParts(sessionId: string): Promise<StoredPart[]> {
  const db = await database();
  return new Promise((resolve, reject) => {
    const request = db.transaction(STORE).objectStore(STORE).getAll();
    request.onsuccess = () => resolve((request.result as StoredPart[]).filter(x => x.sessionId === sessionId && !x.uploaded).sort((a,b) => a.sequence-b.sequence));
    request.onerror = () => reject(request.error);
  });
}

export async function markUploaded(part: StoredPart) { await putPart({ ...part, uploaded: true }); }

export async function sha256(blob: Blob) {
  const digest = await crypto.subtle.digest("SHA-256", await blob.arrayBuffer());
  return Array.from(new Uint8Array(digest)).map(x => x.toString(16).padStart(2, "0")).join("");
}

