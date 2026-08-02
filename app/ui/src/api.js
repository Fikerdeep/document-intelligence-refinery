const json = (r) => {
  if (!r.ok) return r.json().then((e) => Promise.reject(new Error(e.detail || r.statusText)));
  return r.json();
};

export const getDocuments = () => fetch("/api/documents").then(json);
export const getPrompts = () => fetch("/api/prompts").then(json);
export const getTrace = (docId) => fetch(`/api/trace/${docId}`).then(json);
export const getFacts = (docId) => fetch(`/api/facts/${docId}`).then(json);
export const pageUrl = (docId, page, bbox) =>
  `/api/page/${docId}/${page}` + (bbox ? `?bbox=${bbox.join(",")}` : "");
export const ask = (docId, question) =>
  fetch("/api/ask", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ doc_id: docId, question }) }).then(json);
export const askStream = async (docId, question, onEvent) => {
  const r = await fetch("/api/ask/stream", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ doc_id: docId, question }) });
  if (!r.ok) {
    const e = await r.json().catch(() => ({}));
    throw new Error(e.detail || r.statusText);
  }
  const reader = r.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop();
    for (const line of lines) if (line.trim()) onEvent(JSON.parse(line));
  }
};
export const audit = (claim) =>
  fetch("/api/audit", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ claim }) }).then(json);
