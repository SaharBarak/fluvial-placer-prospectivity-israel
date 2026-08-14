export interface TargetProperties {
  id: string;
  state: string;
  actionability: string;
  score: number | null;
  uncertainty: number | null;
  segment_name: string | null;
  flow_status: string;
  rank: number;
}

export interface ScoreComponent {
  feature: string;
  family: string;
  raw_normalized: number;
  weight: number;
  contribution: number;
  evidence_ids: string[];
}

export interface EvidenceItem {
  id: string;
  kind: string;
  claim: string | null;
  measurement: { analyte: string; value: number; unit: string } | null;
  confidence: number;
  quality: string;
  authority: string;
  source: {
    name: string;
    url: string;
    license: string | null;
    reference: string;
  };
}

export interface Objection {
  kind: string;
  severity: string;
  statement: string;
}

export interface GuardrailDecision {
  policy_id: string;
  status: string;
  reason_code: string;
  remediation: string | null;
  expires_at: string | null;
}

export interface Dossier {
  id: string;
  geometry: { type: string; coordinates: [number, number] };
  state: string;
  actionability: string;
  waterway: {
    segment_id: string;
    name: string | null;
    flow_status: string;
    flow_confidence: number;
    flow_valid_until: string | null;
    length_m: number;
  };
  score: {
    model_version: string;
    value: number;
    uncertainty: number;
    components: ScoreComponent[];
    created_at: string;
    run_id: string | null;
  } | null;
  score_history: { score: number; uncertainty: number; at: string }[];
  evidence: EvidenceItem[];
  objections: Objection[];
  guardrails: GuardrailDecision[];
  next_measurement: {
    kind: string;
    eig_score: number;
    expected_uncertainty_reduction: number;
    decision_impact: number;
    normalized_cost: number;
    actionability: string;
    rationale: string;
  } | null;
  trace: {
    trace_id: string;
    run_id: string;
    state_before: string;
    state_after: string;
    derived_features: Record<string, number>;
    rationale_summary: string;
    output_hash: string;
    scoring_model_version: string | null;
    created_at: string;
  } | null;
}
