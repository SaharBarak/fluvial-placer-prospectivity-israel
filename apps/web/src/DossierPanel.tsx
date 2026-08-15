import type { Dossier } from "./types";
import {
  ACTIONABILITY_LABELS,
  AUTHORITY_LABELS,
  EVIDENCE_KIND_LABELS,
  FLOW_LABELS,
  GUARDRAIL_STATUS_LABELS,
  MEASUREMENT_LABELS,
  OBJECTION_LABELS,
  POLICY_LABELS,
  QUALITY_LABELS,
  STATE_LABELS,
  featureLabel,
  label,
} from "./labels";

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
          <h2>{dossier.waterway.name ?? "מקטע ללא שם"}</h2>
          <div className="badges">
            <span className="badge state">{label(STATE_LABELS, dossier.state)}</span>
            <span className="badge action">
              {label(ACTIONABILITY_LABELS, dossier.actionability)}
            </span>
            <span className="badge flow">
              {label(FLOW_LABELS, dossier.waterway.flow_status)}
            </span>
          </div>
        </div>
        <button onClick={onClose} aria-label="סגירה">
          ✕
        </button>
      </header>

      {score && (
        <section>
          <h3>ציון פוטנציאל</h3>
          <div className="scoreRow">
            <div className="scoreBig">{score.value.toFixed(1)}</div>
            <div className="scoreMeta">
              <div>אי-ודאות {(score.uncertainty * 100).toFixed(0)}%</div>
              <div className="mono">{score.model_version}</div>
            </div>
          </div>
          <p className="note">
            ציון מודל יחסי — לא הסתברות למציאת זהב (PRD §10.1).
          </p>
        </section>
      )}

      {drivers.length > 0 && (
        <section>
          <h3>גורמים מובילים</h3>
          <ul className="drivers">
            {drivers.map((d) => (
              <li key={d.feature}>
                <span>{featureLabel(d.feature)}</span>
                <span className="mono">+{d.contribution.toFixed(1)}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {dossier.objections.length > 0 && (
        <section>
          <h3>התנגדויות המבקר</h3>
          <ul className="objections">
            {dossier.objections.map((o, i) => (
              <li key={i} className={`sev-${o.severity.toLowerCase()}`}>
                <strong>{label(OBJECTION_LABELS, o.kind)}</strong> — {o.statement}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section>
        <h3>יומן ראיות ({dossier.evidence.length})</h3>
        <ul className="evidence">
          {dossier.evidence.map((e) => (
            <li key={e.id}>
              <div className="evKind">
                {label(EVIDENCE_KIND_LABELS, e.kind)} ·{" "}
                {label(QUALITY_LABELS, e.quality)} ·{" "}
                {label(AUTHORITY_LABELS, e.authority)}
              </div>
              <div className="evClaim">{e.claim}</div>
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
                · מזהה מקור: <span className="mono">{e.source.reference}</span>
              </div>
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h3>מנגנוני הגנה</h3>
        <ul className="guardrails">
          {dossier.guardrails.map((g) => (
            <li key={g.policy_id}>
              <span
                className="dot"
                style={{ background: STATUS_COLORS[g.status] ?? "#999" }}
              />
              <strong>{label(POLICY_LABELS, g.policy_id)}</strong>:{" "}
              {label(GUARDRAIL_STATUS_LABELS, g.status)}
              {g.remediation ? ` — ${g.remediation}` : ""}
            </li>
          ))}
        </ul>
      </section>

      {dossier.next_measurement && (
        <section>
          <h3>המדידה הבאה הטובה ביותר</h3>
          <p>
            <strong>{label(MEASUREMENT_LABELS, dossier.next_measurement.kind)}</strong>{" "}
            · רווח מידע צפוי {dossier.next_measurement.eig_score.toFixed(2)}
          </p>
          <p className="note">{dossier.next_measurement.rationale}</p>
          <button
            className="assayBtn"
            onClick={() => {
              const raw = window.prompt(
                "תוצאת מעבדה סינתטית — Au ב-ppb (הדגמת לולאת השטח):",
                "42",
              );
              if (raw === null) return;
              const value = Number(raw);
              if (Number.isFinite(value) && value >= 0)
                onSubmitAssay(dossier.id, value);
            }}
          >
            הזנת תוצאת מעבדה ← דירוג מחדש
          </button>
        </section>
      )}

      {score && dossier.score_history.length > 1 && (
        <section>
          <h3>היסטוריית ציונים</h3>
          <ul className="history">
            {dossier.score_history.map((h, i) => (
              <li key={i} className="mono">
                {new Date(h.at).toLocaleString("he-IL")} ← {h.score.toFixed(1)}{" "}
                (אי-ודאות {h.uncertainty.toFixed(2)})
              </li>
            ))}
          </ul>
        </section>
      )}

      {dossier.trace && (
        <section>
          <h3>נתיב החלטה</h3>
          <div className="mono small">
            {label(STATE_LABELS, dossier.trace.state_before)} ←{" "}
            {label(STATE_LABELS, dossier.trace.state_after)}
          </div>
          <div className="mono small">
            hash {dossier.trace.output_hash.slice(0, 16)}…
          </div>
          <p className="note">{dossier.trace.rationale_summary}</p>
          <details>
            <summary>פיצ'רים מחושבים</summary>
            <ul className="history">
              {Object.entries(dossier.trace.derived_features).map(([k, v]) => (
                <li key={k} className="small">
                  {featureLabel(k)} = <span className="mono">{v}</span>
                </li>
              ))}
            </ul>
          </details>
        </section>
      )}
    </aside>
  );
}
