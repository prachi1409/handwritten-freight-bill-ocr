/**
 * Presentation helpers for existing Points 1–5 metadata.
 * Does not rank candidates, calibrate, or invent relationships.
 */

export const VALIDATE_OWNED_CODES = new Set([
  "FREIGHT_EXCEEDS_TOTAL",
  "LINE_ITEM_SUM_MISMATCH",
]);

const EVIDENCE_SOURCES = new Set(["ocr", "ocr_text", "gazetteer", "alias"]);

export function isFieldPresent(val) {
  return val !== null && val !== undefined && String(val).trim() !== "" && String(val).trim() !== "—";
}

export function resolveOcrMetadata(doc) {
  const extracted = (doc && doc.extracted_data) || {};
  const column = (doc && doc.ocr_metadata) || {};
  const raw = (doc && doc.raw_ocr) || {};
  const nested = raw.ocr_metadata && typeof raw.ocr_metadata === "object" ? raw.ocr_metadata : {};
  const primary =
    column.field_candidates || column.joint_decode || column.field_calibration || column.consistency_checks
      ? column
      : nested.field_candidates || nested.joint_decode || nested.field_calibration || nested.consistency_checks
        ? nested
        : column;
  return {
    ...nested,
    ...raw,
    ...primary,
    field_candidates: primary.field_candidates || nested.field_candidates || extracted.field_candidates || {},
    joint_decode: primary.joint_decode || nested.joint_decode || extracted.joint_decode || null,
    field_calibration: primary.field_calibration || nested.field_calibration || extracted.field_calibration || null,
    consistency_checks: primary.consistency_checks || nested.consistency_checks || extracted.consistency_checks || null,
  };
}

export function getCalibrationRow(meta, extracted, field) {
  const block = (meta && meta.field_calibration) || (extracted && extracted.field_calibration) || {};
  const row = (block.fields || {})[field];
  return row && typeof row === "object" ? row : null;
}

export function isSelectableCandidate(candidate) {
  if (!candidate || !isFieldPresent(candidate.value)) return false;
  const sources = Array.isArray(candidate.sources)
    ? candidate.sources
    : candidate.source
      ? [candidate.source]
      : [];
  return sources.some((src) => EVIDENCE_SOURCES.has(String(src)));
}

export function getFieldCandidates(meta, field) {
  const rows = meta && meta.field_candidates ? meta.field_candidates[field] : null;
  if (!Array.isArray(rows)) return [];
  return rows.filter(isSelectableCandidate);
}

export function formatSourceLabel(candidate) {
  const sources = Array.isArray(candidate.sources)
    ? candidate.sources
    : candidate.source
      ? [candidate.source]
      : [];
  const labels = sources
    .map((src) => {
      const key = String(src || "").toLowerCase();
      if (key === "ocr" || key === "ocr_text") return "OCR";
      if (key === "gazetteer") return "Gazetteer";
      if (key === "alias") return "Alias";
      if (key === "prior") return "Prior";
      return src;
    })
    .filter(Boolean);
  const unique = [...new Set(labels)];
  return unique.filter((label) => label !== "Prior").join(" · ") || unique.join(" · ") || "Evidence";
}

export function formatScore(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return null;
  return Number(value).toFixed(2);
}

export function getJointFieldEvidence(joint, field, currentValue) {
  if (!joint || typeof joint !== "object") return null;
  const selected = joint.selected && joint.selected[field];
  const relations = Array.isArray(joint.relations_used) ? joint.relations_used : [];
  const relevant = relations.filter((row) => {
    if (!row || typeof row !== "object") return false;
    const relation = String(row.relation || "");
    const targetField = relation.split("→").pop();
    const targetAliases = {
      carrier: ["carrier"],
      driver: ["driver_name", "driver"],
      consignee: ["consignee"],
      destination: ["destination"],
    };
    const aliases = targetAliases[targetField] || [targetField, field];
    if (aliases.includes(field)) return true;
    if (isFieldPresent(row.target) && isFieldPresent(currentValue) && collapse(row.target) === collapse(currentValue)) {
      return relation.includes(field.replace("_name", "")) || aliases.some((name) => relation.includes(name));
    }
    return false;
  });
  if (!isFieldPresent(selected) && relevant.length === 0) return null;
  return {
    selected: isFieldPresent(selected) ? selected : null,
    jointScore: joint.joint_score,
    relations: relevant,
  };
}

function collapse(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/[^a-z0-9&]+/g, "");
}

export function humanizeRelation(relation) {
  return String(relation || "")
    .replace(/→/g, " → ")
    .replace(/\+/g, " + ");
}

export function getHistoricalSupport(candidates, jointEvidence, consistencyRows, field, currentValue) {
  const items = [];
  const currentKey = collapse(currentValue);
  const selectedCand = (candidates || []).find((row) => collapse(row.value) === currentKey) || null;
  const withPrior = (candidates || []).filter((row) => Number(row.prior_count || 0) > 0 && collapse(row.value) === currentKey);
  withPrior.slice(0, 2).forEach((row) => {
    items.push({
      kind: "candidate",
      text: `${row.prior_count} historical ticket${Number(row.prior_count) === 1 ? "" : "s"} used “${row.value}”`,
      probability: row.prior_probability,
    });
  });
  (jointEvidence && jointEvidence.relations ? jointEvidence.relations : []).forEach((row) => {
    if (!row.count) return;
    const given = Array.isArray(row.given) ? row.given.filter(Boolean).join(" + ") : "";
    items.push({
      kind: "relation",
      text: given && row.target ? `${given} → ${row.target}` : humanizeRelation(row.relation),
      count: row.count,
      probability: row.probability,
    });
  });
  (consistencyRows || [])
    .filter((row) => row.code === "HISTORICAL_RELATIONSHIP_CONFLICT" && row.evidence)
    .forEach((row) => {
      const ev = row.evidence;
      if (!ev.usual_value) return;
      items.push({
        kind: "conflict",
        text: `Historical ${humanizeRelation(ev.relation || "")} usually uses “${ev.usual_value}”`,
        count: ev.usual_count,
        probability: ev.usual_probability,
      });
    });
  if (selectedCand && selectedCand.prior_count && items.length === 0) {
    items.push({
      kind: "candidate",
      text: `${selectedCand.prior_count} historical tickets used this value`,
      probability: selectedCand.prior_probability,
    });
  }
  return items;
}

export function getFieldConsistency(payload, field) {
  const checks = payload && Array.isArray(payload.checks) ? payload.checks : [];
  return checks.filter((row) => Array.isArray(row.fields_involved) && row.fields_involved.includes(field));
}

function warningLooksLikeCode(text, code) {
  const blob = String(text || "").toLowerCase();
  if (code === "FREIGHT_EXCEEDS_TOTAL") return blob.includes("freight") && blob.includes("exceed");
  if (code === "LINE_ITEM_SUM_MISMATCH") return blob.includes("line item sum") || blob.includes("mismatches total");
  return false;
}

export function splitConsistencyForDisplay(payload, validationWarnings) {
  const checks = payload && Array.isArray(payload.checks) ? payload.checks : [];
  const warnings = Array.isArray(validationWarnings) ? validationWarnings : [];
  const unique = checks.filter((row) => {
    if (!row || !row.code) return false;
    if (VALIDATE_OWNED_CODES.has(row.code) && warnings.some((text) => warningLooksLikeCode(text, row.code))) {
      return false;
    }
    return true;
  });
  return {
    errors: unique.filter((row) => row.severity === "error"),
    warnings: unique.filter((row) => row.severity !== "error"),
  };
}

export function buildReviewReasons({
  status,
  validationWarnings,
  calibration,
  consistency,
  extracted,
}) {
  if (String(status || "").toUpperCase() !== "REVIEW") return [];
  const reasons = [];
  const warns = Array.isArray(validationWarnings) ? validationWarnings : [];
  const missing = warns.filter((text) => /missing critical/i.test(String(text)));
  const lowOverall = warns.filter((text) => /low overall confidence/i.test(String(text)));
  const otherValidate = warns.filter(
    (text) => !/missing critical/i.test(String(text)) && !/low overall confidence/i.test(String(text))
  );

  if (missing.length) {
    reasons.push({ key: "missing", text: missing[0] });
  }
  if (lowOverall.length) {
    reasons.push({ key: "overall", text: lowOverall[0] });
  }

  const fields = (calibration && calibration.fields) || {};
  let below = 0;
  Object.entries(fields).forEach(([field, row]) => {
    if (!row || !row.calibration_available) return;
    if (row.auto_post) return;
    if (!isFieldPresent(extracted && extracted[field])) return;
    below += 1;
  });
  if (below > 0) {
    reasons.push({
      key: "autopost",
      text: `${below} field${below === 1 ? "" : "s"} below auto-post threshold`,
    });
  }

  const split = splitConsistencyForDisplay(consistency, warns);
  if (split.errors.length) {
    reasons.push({
      key: "consistency-error",
      text: `${split.errors.length} consistency error${split.errors.length === 1 ? "" : "s"}`,
    });
  }
  if (split.warnings.length) {
    reasons.push({
      key: "consistency-warning",
      text: `${split.warnings.length} consistency warning${split.warnings.length === 1 ? "" : "s"}`,
    });
  }
  otherValidate.forEach((text, index) => {
    reasons.push({ key: `validate-${index}`, text });
  });
  return reasons;
}

export function fieldHasReviewerIntel(meta, extracted, field) {
  const cal = getCalibrationRow(meta, extracted, field);
  const cands = getFieldCandidates(meta, field);
  const checks = getFieldConsistency(meta && meta.consistency_checks, field);
  const joint = getJointFieldEvidence(meta && meta.joint_decode, field, extracted && extracted[field]);
  return Boolean(
    (cal && (cal.calibration_available || cal.raw_confidence || cal.calibrated_confidence)) ||
      cands.length > 0 ||
      checks.length > 0 ||
      (joint && (joint.relations.length > 0 || joint.selected))
  );
}
