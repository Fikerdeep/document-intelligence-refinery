import React, { useEffect, useState } from "react";
import { askStream, pageUrl } from "../api.js";

export default function AskView({ doc, seeded, onRun }) {
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [receipt, setReceipt] = useState(null);
  const [steps, setSteps] = useState([]);
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (!seeded) return;
    setQuestion(seeded.text);
    setResult(null);
    setError(null);
  }, [seeded && seeded.stamp]);

  const submit = () => {
    if (!question.trim() || !doc) return;
    setBusy(true); setError(null); setResult(null); setSteps([]); setElapsed(0);
    const asked = question;
    const started = Date.now();
    const tick = setInterval(() => setElapsed((Date.now() - started) / 1000), 100);
    askStream(doc.doc_id, asked, (ev) => {
      if (ev.event === "tool") setSteps((prev) => [...prev, ev.tool]);
      else if (ev.event === "result") {
        setResult(ev);
        if (onRun) onRun({ question: asked, doc: doc.source_name, result: ev });
      } else if (ev.event === "error") setError(ev.detail);
    })
      .catch((e) => setError(e.message))
      .finally(() => { clearInterval(tick); setBusy(false); });
  };

  const renderAnswer = (text, citations) =>
    text.split(/(\[\d+\])/g).map((part, i) => {
      const m = part.match(/^\[(\d+)\]$/);
      const cite = m && citations[Number(m[1]) - 1];
      if (!cite) return <span key={i}>{part}</span>;
      return (
        <button key={i} className="cite-mark" title={`${cite.document} · p.${cite.page}`}
          onClick={() => setReceipt(cite)}>{m[1]}</button>
      );
    });

  if (!doc) return <div className="empty">Select a document first.</div>;

  return (
    <>
      <div className="view-title">Ask</div>
      <div className="view-sub">
        {doc.source_name} — answers carry receipts; click a citation to see the exact source region
      </div>

      <div className="askbox">
        <input value={question} placeholder="What was general inflation in July EFY 2017?"
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && submit()} />
        <button className="btn" disabled={busy} onClick={submit}>
          {busy ? <span className="spin" /> : "Ask"}
        </button>
      </div>

      {seeded && seeded.text === question && (
        <div className="seeded">
          {seeded.kind === "adversarial"
            ? "adversarial — the only correct outcome is not_found with zero citations"
            : `answerable — a correct answer contains ${seeded.expect}`}
        </div>
      )}

      {error && <div className="error">{error}</div>}

      {busy && (
        <div className="seeded">
          {elapsed.toFixed(1)}s · {steps.length
            ? `${steps.length} tool call${steps.length > 1 ? "s" : ""} · ${steps[steps.length - 1]}`
            : "thinking…"}
        </div>
      )}

      {result && result.routed && result.routed.length > 0 && (
        <div className="seeded">
          routed to: {result.routed.join("  ·  ")}
        </div>
      )}

      {result && result.status === "no_convergence" && (
        <div className="answer notfound">
          <div className="text">
            The agent hit its round limit without converging on this question.
            It stops rather than invent — no answer is reported and nothing was
            fabricated. Long documents make this more likely; it is a known v1
            limit (roadmap: agent termination at scale).
          </div>
          <div className="citations">
            <span className="tag amber">no convergence — honest failure</span>
          </div>
        </div>
      )}

      {result && result.status === "citation_error" && (
        <div className="answer notfound">
          <div className="text">
            The agent produced an answer whose citations could not be verified
            against what its tools actually returned — so the answer was
            withheld. Nothing unverifiable is ever shown; ask again to retry.
          </div>
          <div className="citations">
            <span className="tag red">citation integrity — answer withheld</span>
          </div>
        </div>
      )}

      {result && result.status !== "no_convergence" && result.status !== "citation_error" && (
        <div className={"answer" + (result.status === "not_found" ? " notfound" : "")}>
          <div className="text">{renderAnswer(result.answer, result.citations)}</div>
          <div className="citations">
            {result.citations.map((c, i) => (
              <button key={c.content_hash} className="cite" onClick={() => setReceipt(c)}>
                [{i + 1}] {c.document} · p.{c.page}
              </button>
            ))}
            {result.status === "not_found" &&
              <span className="tag amber">not found — the honest answer</span>}
            {result.elapsed_s != null && (
              <span className="tag gray">
                {(result.tool_log || []).length} tool calls · {result.elapsed_s}s — full trace in the Agent tab
              </span>
            )}
          </div>
        </div>
      )}

      {receipt && (
        <div className="modal-back" onClick={() => setReceipt(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <img src={pageUrl(receipt.doc_id || result.doc_id, receipt.page, receipt.bbox)}
              alt="source" />
            <div className="cap">
              {receipt.document} — page {receipt.page} — the highlighted region is the citation
              · hash {receipt.content_hash}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
