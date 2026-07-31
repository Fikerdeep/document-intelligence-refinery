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
export const audit = (claim) =>
  fetch("/api/audit", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ claim }) }).then(json);
