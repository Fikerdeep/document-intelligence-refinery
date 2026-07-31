import React, { useState } from "react";

function Step({ index, entry }) {
  const [open, setOpen] = useState(false);
  const isError = entry.result && entry.result.error;
  return (
    <div className="agent-step">
      <button className="agent-call" onClick={() => setOpen(!open)}>
        <span className="n">{index + 1}</span>
        <code>{entry.tool}({JSON.stringify(entry.args)})</code>
        {isError && <span className="tag red">error</span>}
        <span className="caret">{open ? "▾" : "▸"}</span>
      </button>
      {open && (
        <pre className="agent-out">{JSON.stringify(entry.result, null, 1)}</pre>
      )}
    </div>
  );
}

export default function AgentView({ runs }) {
  const [selected, setSelected] = useState(0);

  if (!runs.length) {
    return (
      <div className="empty">
        No agent runs yet this session — ask a question in the Ask tab, then come
        back here to see every tool call with its full output.
      </div>
    );
  }

  const run = runs[Math.min(selected, runs.length - 1)];

  return (
    <>
      <div className="view-title">Agent trace</div>
      <div className="view-sub">
        every tool call and its full output — the agent's working, not just its answer
      </div>

      <div className="run-list">
        {runs.map((r, i) => (
          <button key={i} className={"run-pill" + (i === selected ? " active" : "")}
            onClick={() => setSelected(i)}>
            <span className={"dot " + r.result.status} />
            {r.question.slice(0, 60)}{r.question.length > 60 ? "…" : ""}
          </button>
        ))}
      </div>

      <div className="panel">
        <h3>{run.doc} — {run.result.status} — {(run.result.tool_log || []).length} tool calls</h3>
        <div className="agent-q">{run.question}</div>
        {(run.result.tool_log || []).map((entry, i) => (
          <Step key={i} index={i} entry={entry} />
        ))}
        {!(run.result.tool_log || []).length && (
          <div className="empty">
            no tool outputs recorded — restart the server so the agent's new logging
            code is loaded
          </div>
        )}
        {run.result.answer && (
          <div className={"answer" + (run.result.status === "answered" ? "" : " notfound")}>
            <div className="text">{run.result.answer}</div>
          </div>
        )}
      </div>
    </>
  );
}
