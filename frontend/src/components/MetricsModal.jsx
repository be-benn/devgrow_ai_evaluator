import { useState } from 'react';

const METRICS_URL = 'http://localhost:8000/api/scoring-metrics/';

const DEFAULT_METRICS = [
  {
    name: 'requirement_coverage',
    display_name: 'Requirement Coverage',
    description:
      'Percentage of acceptance criteria addressed by the code. Score based on how many criteria have a visible implementation.',
  },
  {
    name: 'correctness',
    display_name: 'Code Correctness',
    description:
      'Whether the implemented logic is correct, free of bugs, and handles edge cases. Deduct for logic errors, crashes, or wrong outputs.',
  },
];

const EMPTY_METRIC = { name: '', display_name: '', description: '' };

export default function MetricsModal({ onClose }) {
  const [extras, setExtras] = useState([]);
  const [saving, setSaving] = useState(false);
  const [feedback, setFeedback] = useState(null);

  function addMetric() {
    if (extras.length >= 3) return;
    setExtras((prev) => [...prev, { ...EMPTY_METRIC }]);
  }

  function updateExtra(index, field, value) {
    setExtras((prev) =>
      prev.map((m, i) => (i === index ? { ...m, [field]: value } : m))
    );
  }

  function removeExtra(index) {
    setExtras((prev) => prev.filter((_, i) => i !== index));
  }

  async function handleSave() {
    // Validate: every extra must have name + display_name
    const valid = extras.every((m) => m.name.trim() && m.display_name.trim());
    if (!valid) {
      setFeedback({ type: 'error', text: 'Name and Display Name are required for each metric.' });
      return;
    }

    setSaving(true);
    setFeedback(null);

    try {
      const res = await fetch(METRICS_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ metrics: extras }),
      });

      const data = await res.json();

      if (!res.ok) {
        setFeedback({ type: 'error', text: data.error || JSON.stringify(data) });
      } else {
        const extraCount = (data.metrics?.length || 0) - 2; // minus 2 defaults
        setFeedback({
          type: 'success',
          text: `Saved! ${extraCount} additional metric${extraCount !== 1 ? 's' : ''} active.${data.warning ? ' ' + data.warning : ''}`,
        });
      }
    } catch (err) {
      setFeedback({ type: 'error', text: err.message || 'Network error.' });
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2 className="modal-title">Scoring Metrics</h2>
          <button className="modal-close" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>

        <div className="modal-body">
          {/* ── Default metrics ─────────────────────── */}
          <div className="modal-section-label">Default Metrics</div>
          <div className="default-metrics-list">
            {DEFAULT_METRICS.map((m) => (
              <div key={m.name} className="default-metric-card">
                <div className="default-metric-header">
                  <span className="default-metric-name">{m.display_name}</span>
                  <span className="default-metric-badge">Default</span>
                </div>
                <p className="default-metric-desc">{m.description}</p>
              </div>
            ))}
          </div>

          {/* ── Additional metrics ──────────────────── */}
          <div className="modal-section-label" style={{ marginTop: 24 }}>
            Additional Metrics
            <span className="modal-section-hint">(max 3)</span>
          </div>

          {extras.length === 0 && (
            <p className="metrics-empty">No additional metrics. Click below to add one.</p>
          )}

          <div className="extras-list">
            {extras.map((m, i) => (
              <div key={i} className="extra-metric-card">
                <div className="extra-metric-row">
                  <div className="form-group">
                    <label className="form-label">Name</label>
                    <input
                      className="form-input"
                      placeholder="e.g. code_quality"
                      value={m.name}
                      onChange={(e) => updateExtra(i, 'name', e.target.value)}
                    />
                  </div>
                  <div className="form-group">
                    <label className="form-label">Display Name</label>
                    <input
                      className="form-input"
                      placeholder="e.g. Code Quality"
                      value={m.display_name}
                      onChange={(e) => updateExtra(i, 'display_name', e.target.value)}
                    />
                  </div>
                  <button
                    type="button"
                    className="extra-metric-remove"
                    onClick={() => removeExtra(i)}
                    aria-label="Remove metric"
                  >
                    ×
                  </button>
                </div>
                <div className="form-group">
                  <label className="form-label">
                    Description <span className="optional">(optional)</span>
                  </label>
                  <input
                    className="form-input"
                    placeholder="What this metric evaluates…"
                    value={m.description}
                    onChange={(e) => updateExtra(i, 'description', e.target.value)}
                  />
                </div>
              </div>
            ))}
          </div>

          {extras.length < 3 && (
            <button type="button" className="btn btn-add-metric" onClick={addMetric}>
              + Add Metric
            </button>
          )}

          {/* ── Feedback ───────────────────────────── */}
          {feedback && (
            <div className={`modal-feedback ${feedback.type === 'error' ? 'modal-feedback-error' : 'modal-feedback-success'}`}>
              {feedback.text}
            </div>
          )}
        </div>

        <div className="modal-footer">
          <button type="button" className="btn btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={handleSave}
            disabled={saving || extras.length === 0}
          >
            {saving && <span className="spinner" />}
            {saving ? 'Saving…' : 'Save Metrics'}
          </button>
        </div>
      </div>
    </div>
  );
}
