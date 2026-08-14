import type { Dossier } from "./types";

const STATUS_COLORS: Record<string, string> = {
  ALLOW: "#2e7d32",
  WARN: "#f9a825",
  REVIEW: "#ef6c00",
  BLOCK: "#c62828",
};

export function DossierPanel({
  dossier,
  onClose,
  onSubmitAssay,
}: {
  dossier: Dossier;
  onClose: () => void;
  onSubmitAssay: (targetId: string, valuePpb: number) => void;
}) {
  const score = dossier.score;
  const drivers = (score?.components ?? [])
    .filter((c) => c.contribution > 0)
    .sort((a, b) => b.contribution - a.contribution)
    .slice(0, 3);

  return (
    <aside className="dossier">
      <header>
        <div>
          <h2>{dossier.waterway.name ?? "Unnamed segment"}</h2>
          <div className="badges">
            <span className="badge state">{dossier.state}</span>
            <span className="badge action">{dossier.actionability}</span>
            <span className="badge flow">{dossier.waterway.flow_status}</span>
          </div>
        </div>
        <button onClick={onClose} aria-label="close">
          ✕
        </button>
      </header>

      {score && (
        <section>
          <h3>Prospect score</h3>
          <div className="scoreRow">
            <div className="scoreBig">{score.value.toFixed(1)}</div>
            <div className="scoreMeta">
              <div>uncertainty {(score.uncertainty * 100).toFixed(0)}%</div>
              <div className="mono">{score.model_version}</div>
            </div>
          </div>
          <p className="note">
            Relative model score, not a probability of finding gold (PRD §10.1).
          </p>
        </section>
      )}

      {drivers.length > 0 && (
        <section>
          <h3>Primary drivers</h3>
          <ul className="drivers">
            {drivers.map((d) => (
              <li key={d.feature}>
                <span>{d.feature}</span>
                <span className="mono">+{d.contribution.toFixed(1)}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {dossier.objections.length > 0 && (
        <section>
          <h3>Critic objections</h3>
          <ul className="objections">
            {dossier.objections.map((o, i) => (
              <li key={i} className={`sev-${o.severity.toLowerCase()}`}>
                <strong>{o.kind}</strong> — {o.statement}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section>
        <h3>Evidence ledger ({dossier.evidence.length})</h3>
        <ul className="evidence">
          {dossier.evidence.map((e) => (
            <li key={e.id}>
              <div className="evKind">
                {e.kind} · {e.quality} · {e.authority}
              </div>
              <div>{e.claim}</div>
              {e.measurement && (
                <div className="mono">
                  {e.measurement.analyte} = {e.measurement.value}{" "}
                  {e.measurement.unit}
                </div>
              )}
              <div className="evSource">
                <a href={e.source.url} target="_blank" rel="noreferrer">
                  {e.source.name}
                </a>{" "}
                · ref {e.source.reference}
              </div>
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h3>Guardrails</h3>
        <ul className="guardrails">
          {dossier.guardrails.map((g) => (
            <li key={g.policy_id}>
              <span
                className="dot"
                style={{ background: STATUS_COLORS[g.status] ?? "#999" }}
              />
              <strong>{g.policy_id}</strong>: {g.status}
              {g.remediation ? ` — ${g.remediation}` : ""}
            </li>
          ))}
        </ul>
      </section>

      {dossier.next_measurement && (
        <section>
          <h3>Next best measurement</h3>
          <p>
            <strong>{dossier.next_measurement.kind}</strong> · EIG{" "}
            {dossier.next_measurement.eig_score.toFixed(2)}
          </p>
          <p className="note">{dossier.next_measurement.rationale}</p>
          <button
            className="assayBtn"
            onClick={() => {
              const raw = window.prompt(
                "Synthetic assay result — Au in ppb (demo of the field loop):",
                "42",
              );
              if (raw === null) return;
              const value = Number(raw);
              if (Number.isFinite(value) && value >= 0)
                onSubmitAssay(dossier.id, value);
            }}
          >
            Submit assay result → re-score
          </button>
        </section>
      )}

      {score && dossier.score_history.length > 1 && (
        <section>
          <h3>Score history</h3>
          <ul className="history">
            {dossier.score_history.map((h, i) => (
              <li key={i} className="mono">
                {new Date(h.at).toLocaleString()} → {h.score.toFixed(1)} (u=
                {h.uncertainty.toFixed(2)})
              </li>
            ))}
          </ul>
        </section>
      )}

      {dossier.trace && (
        <section>
          <h3>Decision trace</h3>
          <div className="mono small">
            {dossier.trace.state_before} → {dossier.trace.state_after}
          </div>
          <div className="mono small">hash {dossier.trace.output_hash.slice(0, 16)}…</div>
          <p className="note">{dossier.trace.rationale_summary}</p>
          <details>
            <summary>Derived features</summary>
            <ul className="history">
              {Object.entries(dossier.trace.derived_features).map(([k, v]) => (
                <li key={k} className="mono small">
                  {k} = {v}
                </li>
              ))}
            </ul>
          </details>
        </section>
      )}
    </aside>
  );
}
