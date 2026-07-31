import React, { useState } from "react";
import { audit, pageUrl } from "../api.js";

export default function AuditView() {
  const [claim, setClaim] = useState("");
  const [busy, setBusy] = useState(false);
  const [verdict, setVerdict] = useState(null);
  const [error, setError] = useState(null);

  const submit = () => {
    if (!claim.trim()) return;
    setBusy(true); setError(null); setVerdict(null);
    audit(claim)
      .then(setVerdict)
      .catch((e) => setError(e.message))
      .finally(() => setBusy(false));
  };

  return (
    <>
      <div className="view-title">Audit</div>
      <div className="view-sub">
        deterministic claim verification — the source page is re-read, never trusted from storage
      </div>

      <div className="askbox">
        <input value={claim} placeholder="July EFY 2017 general inflation was 13.7"
          onChange={(e) => setClaim(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && submit()} />
        <button className="btn" disabled={busy} onClick={submit}>
          {busy ? <span className="spin" /> : "Verify"}
        </button>
      </div>

      {error && <div className="error">{error}</div>}

      {verdict && (
        <>
          <div className={"stamp " + verdict.status}>
            {verdict.status === "VERIFIED" ? "✓" : verdict.status === "REFUTED" ? "✕" : "?"}{" "}
            {verdict.status}
          </div>
          <div className="panel">
            <h3>Finding</h3>
            <div style={{ fontSize: 15 }}>{verdict.detail}</div>
          </div>
          {verdict.receipt && verdict.doc_id && (
            <div className="split">
              <div className="page-viewer">
                <img src={pageUrl(verdict.doc_id, verdict.receipt.page, verdict.receipt.bbox)}
                  alt="receipt" />
                <div className="cap">
                  {verdict.receipt.document} — page {verdict.receipt.page} — printed value{" "}
                  <b>{verdict.receipt.printed_value}</b> in the highlighted region
                </div>
              </div>
              <div className="panel">
                <h3>Receipt</h3>
                <pre style={{ fontSize: 12, overflowX: "auto" }}>
                  {JSON.stringify(verdict.receipt, null, 2)}
                </pre>
              </div>
            </div>
          )}
        </>
      )}
    </>
  );
}
