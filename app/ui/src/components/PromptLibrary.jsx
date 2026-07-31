import React, { useEffect, useMemo, useState } from "react";
import { getPrompts } from "../api.js";

export default function PromptLibrary({ docs, onPick }) {
  const [prompts, setPrompts] = useState([]);
  const [open, setOpen] = useState(null);

  useEffect(() => { getPrompts().then(setPrompts).catch(() => setPrompts([])); }, []);

  const groups = useMemo(() => {
    const byGroup = new Map();
    prompts.forEach((p) => {
      if (!byGroup.has(p.group)) byGroup.set(p.group, []);
      byGroup.get(p.group).push(p);
    });
    return [...byGroup.entries()];
  }, [prompts]);

  const ingested = useMemo(
    () => new Set(docs.map((d) => d.source_name)), [docs]);

  if (!prompts.length) return null;

  return (
    <div className="prompt-lib">
      <h4>Prompt library</h4>
      <div className="lib-note">from eval/questions.yaml — the sealed set</div>
      {groups.map(([group, items]) => (
        <div key={group} className="lib-group">
          <button className="lib-head" onClick={() => setOpen(open === group ? null : group)}>
            <span className="caret">{open === group ? "▾" : "▸"}</span>
            {group}
            <span className="count">{items.length}</span>
          </button>
          {open === group && (
            <div className="lib-items">
              {items.map((p, i) => {
                const missing = p.document && !ingested.has(p.document);
                return (
                  <button key={i} className={"lib-item" + (missing ? " missing" : "")}
                    title={missing ? `${p.document} is not ingested` : p.question}
                    onClick={() => onPick(p)}>
                    <span className={"pill " + p.kind}>
                      {p.kind === "adversarial" ? "adv" : "ans"}
                    </span>
                    <span className="q">{p.question}</span>
                    {p.expect && <span className="expect">{p.expect}</span>}
                  </button>
                );
              })}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
