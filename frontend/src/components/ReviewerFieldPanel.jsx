import React from 'react';
import {
  fieldHasReviewerIntel,
  formatScore,
  formatSourceLabel,
  getCalibrationRow,
  getFieldCandidates,
  getFieldConsistency,
  getHistoricalSupport,
  getJointFieldEvidence,
  humanizeRelation,
  isFieldPresent,
} from '../reviewerEvidence';

function ConfidenceBlock({ calibration, heuristic }) {
  const raw = calibration && calibration.raw_confidence != null
    ? calibration.raw_confidence
    : heuristic;
  const calibrated = calibration && calibration.calibration_available
    ? calibration.calibrated_confidence
    : null;
  const status = calibration && calibration.calibration_status;

  if (raw == null && calibrated == null) return null;

  if (calibrated != null && status === "calibrated") {
    const meets = Boolean(calibration.auto_post);
    return (
      <div className="reviewer-conf" data-testid="confidence-calibrated">
        <div className="reviewer-meta-label">Confidence</div>
        <div>Raw: {formatScore(raw)}</div>
        <div>Calibrated estimate: {formatScore(calibrated)}</div>
        {calibration.threshold != null && (
          <div>Auto-post threshold: {formatScore(calibration.threshold)}</div>
        )}
        <div className={meets ? "reviewer-ok" : "reviewer-flag"}>
          {meets ? "Meets auto-post threshold" : "Below auto-post threshold → review"}
        </div>
      </div>
    );
  }

  const threshold = calibration && calibration.threshold;
  const previewMeets = raw != null && threshold != null && Number(raw) >= Number(threshold);
  return (
    <div className="reviewer-conf" data-testid="confidence-heuristic">
      <div className="reviewer-meta-label">Confidence</div>
      <div>Heuristic: {formatScore(raw)}</div>
      {threshold != null && (
        <div>Auto-post threshold: {formatScore(threshold)} (not fitted yet)</div>
      )}
      {threshold != null && (
        <div className="reviewer-muted">
          {previewMeets
            ? "Heuristic is at/above threshold; bill status still uses whole-ticket rules"
            : "Heuristic is below threshold; stays in review until calibrated"}
        </div>
      )}
      <div className="reviewer-muted">Calibration: Not available yet</div>
    </div>
  );
}

export default function ReviewerFieldPanel({
  field,
  currentValue,
  extracted,
  meta,
  heuristicConfidence,
  isEditing,
  onUseCandidate,
}) {
  if (!fieldHasReviewerIntel(meta, extracted, field) && !isFieldPresent(heuristicConfidence)) {
    return null;
  }

  const calibration = getCalibrationRow(meta, extracted, field);
  const candidates = getFieldCandidates(meta, field);
  const checks = getFieldConsistency(meta && meta.consistency_checks, field);
  const joint = getJointFieldEvidence(meta && meta.joint_decode, field, currentValue);
  const historical = getHistoricalSupport(candidates, joint, checks, field, currentValue);
  const jointRelations = joint && joint.relations ? joint.relations : [];

  return (
    <div className="reviewer-field-panel" data-testid={`reviewer-panel-${field}`}>
      <ConfidenceBlock calibration={calibration} heuristic={heuristicConfidence} />

      {candidates.length > 0 && (
        <div className="reviewer-alts" data-testid={`candidates-${field}`}>
          <div className="reviewer-meta-label">Alternatives</div>
          <ol>
            {candidates.map((row, index) => {
              const fuzzy = formatScore(row.fuzzy_score);
              return (
                <li key={`${row.value}-${index}`}>
                  {isEditing ? (
                    <button
                      type="button"
                      className="reviewer-cand-btn"
                      onClick={() => onUseCandidate && onUseCandidate(row.value)}
                    >
                      <span className="reviewer-cand-value">{row.value}</span>
                      <span className="reviewer-cand-meta">
                        {formatSourceLabel(row)}
                        {fuzzy ? ` · ${fuzzy}` : ""}
                      </span>
                    </button>
                  ) : (
                    <div className="reviewer-cand-static">
                      <span className="reviewer-cand-value">{row.value}</span>
                      <span className="reviewer-cand-meta">
                        {formatSourceLabel(row)}
                        {fuzzy ? ` · ${fuzzy}` : ""}
                      </span>
                    </div>
                  )}
                </li>
              );
            })}
          </ol>
        </div>
      )}

      {joint && joint.selected && isFieldPresent(currentValue) && String(joint.selected) !== String(currentValue) && (
        <div className="reviewer-muted" data-testid={`joint-selected-${field}`}>
          Joint decode preferred “{joint.selected}”; OCR-guard kept the extracted value.
        </div>
      )}

      {jointRelations.length > 0 && (
        <div className="reviewer-why" data-testid={`joint-${field}`}>
          <div className="reviewer-meta-label">Why this was selected</div>
          {jointRelations.map((row, index) => (
            <div key={`${row.relation}-${index}`} className="reviewer-why-row">
              {humanizeRelation(row.relation)}
              {Array.isArray(row.given) && row.given.length > 0 && row.target
                ? `: ${row.given.filter(Boolean).join(" + ")} → ${row.target}`
                : ""}
              {row.count ? ` (${row.count} ticket${row.count === 1 ? "" : "s"})` : ""}
            </div>
          ))}
          {candidates.length > 0 && (
            <div className="reviewer-muted">
              Joint decoding considered {candidates.length} candidate{candidates.length === 1 ? "" : "s"} for this field.
            </div>
          )}
        </div>
      )}

      {historical.length > 0 && (
        <div className="reviewer-hist" data-testid={`history-${field}`}>
          <div className="reviewer-meta-label">Historical evidence</div>
          {historical.map((row, index) => (
            <div key={`${row.kind}-${index}`}>
              {row.text}
              {row.probability != null && Number(row.probability) > 0
                ? ` · share ${formatScore(row.probability)}`
                : ""}
            </div>
          ))}
        </div>
      )}

      {checks.length > 0 && (
        <div className="reviewer-field-warns" data-testid={`field-consistency-${field}`}>
          {checks.map((row, index) => (
            <div
              key={`${row.code}-${index}`}
              className={row.severity === "error" ? "reviewer-flag" : "reviewer-warn"}
            >
              {(row.severity || "warning").toUpperCase()}: {row.message}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
