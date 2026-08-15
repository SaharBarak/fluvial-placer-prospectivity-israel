/** Hebrew labels for backend enum values and feature names. */

export const STATE_LABELS: Record<string, string> = {
  CANDIDATE: "מועמד",
  NEEDS_EVIDENCE: "נדרשות ראיות",
  RESEARCH_READY: "מוכן למחקר",
  FIELD_READY: "מוכן לשטח",
  OBSERVATION_ONLY: "תצפית בלבד",
  BLOCKED_NO_FLOW: "חסום — אין זרימה",
  BLOCKED_SAFETY: "חסום — בטיחות",
  BLOCKED_LEGAL: "חסום — משפטי",
  VALIDATED_POSITIVE: "אומת חיובי",
  VALIDATED_NEGATIVE: "אומת שלילי",
  ARCHIVED: "בארכיון",
};

export const ACTIONABILITY_LABELS: Record<string, string> = {
  OBSERVE_ONLY: "תצפית בלבד",
  SAMPLE_ALLOWED_UNKNOWN: "דיגום — סטטוס לא ידוע",
  PERMIT_REQUIRED: "נדרש היתר",
  BLOCKED: "חסום",
};

export const FLOW_LABELS: Record<string, string> = {
  VERIFIED_PERENNIAL: "איתן מאומת",
  VERIFIED_CURRENT: "זרימה מאומתת",
  SEASONAL_EXPECTED: "עונתי משוער",
  EPHEMERAL: "אכזב",
  DRY: "יבש",
  UNKNOWN: "לא ידוע",
};

export const EVIDENCE_KIND_LABELS: Record<string, string> = {
  GEOLOGICAL_UNIT: "יחידה גיאולוגית",
  STRUCTURAL_FEATURE: "מבנה גיאולוגי",
  MINERAL_OCCURRENCE: "הופעת מינרלים",
  GEOCHEMICAL_SAMPLE: "דגימה גיאוכימית",
  FLOW_OBSERVATION: "תצפית זרימה",
  SPRING_DISCHARGE: "ספיקת מעיין",
  WATER_QUALITY: "איכות מים",
  REMOTE_SENSING: "חישה מרחוק",
  MORPHOLOGY: "מורפולוגיה",
  HISTORICAL_REPORT: "דוח היסטורי",
  ASSAY_RESULT: "תוצאת מעבדה",
  CONTAMINATION_SOURCE: "מקור זיהום",
};

export const QUALITY_LABELS: Record<string, string> = {
  HIGH: "גבוהה",
  MEDIUM: "בינונית",
  LOW: "נמוכה",
  UNRELIABLE: "לא אמין",
};

export const AUTHORITY_LABELS: Record<string, string> = {
  AUTHORITATIVE: "מקור רשמי",
  PEER_REVIEWED: "ביקורת עמיתים",
  OFFICIAL_AGGREGATION: "אגרגציה רשמית",
  SECONDARY: "מקור משני",
  FIELD_GROUND_TRUTH: "אמת שטח",
};

export const GUARDRAIL_STATUS_LABELS: Record<string, string> = {
  ALLOW: "מאושר",
  WARN: "אזהרה",
  REVIEW: "נדרשת בחינה",
  BLOCK: "חסום",
};

export const POLICY_LABELS: Record<string, string> = {
  "flow-gate": "שער זרימה",
  "mining-rights": "זכויות כרייה",
  "water-quality": "איכות מים",
  "protected-areas": "שטחים מוגנים",
  flood: "שיטפונות",
  contamination: "זיהום",
};

export const OBJECTION_LABELS: Record<string, string> = {
  CONTAMINATION_ALTERNATIVE: "הסבר חלופי — זיהום",
  NON_GOLD_LITHOLOGY: "ליתולוגיה לא נושאת זהב",
  NO_TRANSPORT_PATH: "אין נתיב הובלה",
  WEAK_EVIDENCE: "ראיות חלשות",
  FLOW_UNVERIFIED: "זרימה לא מאומתת",
  DATA_QUALITY: "איכות נתונים",
  SENSOR_LIMITATION: "מגבלת חיישן",
};

export const MEASUREMENT_LABELS: Record<string, string> = {
  SEDIMENT_ASSAY: "דיגום סחף לבדיקת מעבדה",
  HEAVY_MINERAL_CONCENTRATE: "ריכוז מינרלים כבדים",
  FIELD_FLOW_OBSERVATION: "תצפית זרימה בשטח",
  HIGH_RES_IMAGERY: "צילום ברזולוציה גבוהה",
  LITERATURE_DEEP_DIVE: "מחקר ספרות מעמיק",
  WATER_QUALITY_CHECK: "בדיקת איכות מים",
};

export const FEATURE_LABELS: Record<string, string> = {
  upstream_lithology_favorability: "התאמת ליתולוגיה במעלה האגן",
  structural_context: "הקשר מבני (קרבה להעתקים)",
  known_mineral_occurrence_upstream: "הופעת מינרלים ידועה במעלה",
  upstream_geochemical_signal: "אות גיאוכימי במעלה",
  upstream_connectivity: "קישוריות ניקוז במעלה",
  gradient_trap_context: "מלכודת שיפוע",
  confluence_density: "צפיפות מפגשי ערוצים",
  channel_sinuosity: "פיתוליות הערוץ",
  evidence_quality_factor: "מקדם איכות ראיות",
  contamination_discount: "הנחת זיהום",
};

export function label(dict: Record<string, string>, key: string): string {
  return dict[key] ?? key;
}

export function featureLabel(name: string): string {
  if (name.startsWith("contamination_")) return "סיכון זיהום";
  return FEATURE_LABELS[name] ?? name;
}
