import { useState } from 'react';
import MetricsModal from './MetricsModal';

const API_URL = 'http://localhost:8000/api/evaluate/';

const INITIAL_FORM = {
  project_title: '',
  project_description: '',
  task_title: '',
  task_description: '',
  acceptance_criteria: '',
  repository_path: '',
  base_commit: '',
  target_commit: '',
  branch: '',
  difficulty: 'MEDIUM',
};

function getScoreClass(score) {
  if (score >= 70) return 'score-high';
  if (score >= 40) return 'score-mid';
  return 'score-low';
}

function getStatusClass(status) {
  const s = (status || '').toLowerCase();
  if (s === 'pass' || s === 'passed') return 'status-pass';
  if (s.includes('partial')) return 'status-partial';
  return 'status-fail';
}

export default function EvaluationForm() {
  const [form, setForm] = useState(INITIAL_FORM);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [metricsOpen, setMetricsOpen] = useState(false);

  function handleChange(e) {
    setForm((prev) => ({ ...prev, [e.target.name]: e.target.value }));
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setLoading(true);
    setResult(null);
    setError(null);

    // Strip blank optional fields
    const payload = { ...form };
    if (!payload.target_commit) delete payload.target_commit;
    if (!payload.branch) delete payload.branch;

    try {
      const res = await fetch(API_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      const data = await res.json();

      if (!res.ok) {
        setError(data.error || data.detail || JSON.stringify(data));
      } else {
        setResult(data);
      }
    } catch (err) {
      setError(err.message || 'Network error. Is the backend running?');
    } finally {
      setLoading(false);
    }
  }

  function handleReset() {
    setForm(INITIAL_FORM);
    setResult(null);
    setError(null);
  }

  return (
    <>
      <form onSubmit={handleSubmit} autoComplete="off">
        <div className="card">
          {/* ── Project Context ─────────────────────── */}
          <div className="card-header">
            <div className="card-section-title">Project Context</div>
          </div>
          <div className="card-body">
            <div className="form-grid">
              <div className="form-group">
                <label className="form-label" htmlFor="project_title">
                  Project Title
                </label>
                <input
                  id="project_title"
                  name="project_title"
                  className="form-input"
                  placeholder="e.g. DevGrow AI Platform"
                  value={form.project_title}
                  onChange={handleChange}
                  required
                />
              </div>

              <div className="form-group">
                <label className="form-label" htmlFor="task_title">
                  Task Title
                </label>
                <input
                  id="task_title"
                  name="task_title"
                  className="form-input"
                  placeholder="e.g. Add user authentication"
                  value={form.task_title}
                  onChange={handleChange}
                  required
                />
              </div>

              <div className="form-group full-width">
                <label className="form-label" htmlFor="project_description">
                  Project Description
                </label>
                <textarea
                  id="project_description"
                  name="project_description"
                  className="form-textarea"
                  placeholder="Describe the project's purpose, tech stack, and high-level architecture…"
                  value={form.project_description}
                  onChange={handleChange}
                  required
                  rows={3}
                />
              </div>

              <div className="form-group full-width">
                <label className="form-label" htmlFor="task_description">
                  Task Description
                </label>
                <textarea
                  id="task_description"
                  name="task_description"
                  className="form-textarea"
                  placeholder="What should this task accomplish? Include any relevant details…"
                  value={form.task_description}
                  onChange={handleChange}
                  required
                  rows={3}
                />
              </div>

              <div className="form-group full-width">
                <label className="form-label" htmlFor="acceptance_criteria">
                  Acceptance Criteria
                </label>
                <textarea
                  id="acceptance_criteria"
                  name="acceptance_criteria"
                  className="form-textarea"
                  placeholder="List each acceptance criterion on a new line…"
                  value={form.acceptance_criteria}
                  onChange={handleChange}
                  required
                  rows={4}
                />
              </div>

              <div className="full-width">
                <button
                  type="button"
                  className="btn btn-metrics"
                  onClick={() => setMetricsOpen(true)}
                >
                  ⚙ Configure Scoring Metrics
                </button>
              </div>
            </div>
          </div>

          <div className="card-divider" />

          {/* ── Git Details ─────────────────────────── */}
          <div className="card-header">
            <div className="card-section-title">Git Details</div>
          </div>
          <div className="card-body">
            <div className="form-grid">
              <div className="form-group full-width">
                <label className="form-label" htmlFor="repository_path">
                  Repository Path
                </label>
                <input
                  id="repository_path"
                  name="repository_path"
                  className="form-input"
                  placeholder="e.g. /home/user/projects/my-app"
                  value={form.repository_path}
                  onChange={handleChange}
                  required
                />
              </div>

              <div className="form-group">
                <label className="form-label" htmlFor="base_commit">
                  Base Branch / Commit
                </label>
                <input
                  id="base_commit"
                  name="base_commit"
                  className="form-input"
                  placeholder="e.g. main or a1b2c3d"
                  value={form.base_commit}
                  onChange={handleChange}
                  required
                />
                <span className="form-hint">Branch or commit to compare from</span>
              </div>

              <div className="form-group">
                <label className="form-label" htmlFor="target_commit">
                  <span>Target Branch / Commit</span>
                  <span className="optional">(optional)</span>
                  <span
                    className="info-tooltip-wrapper"
                    onClick={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                    }}
                  >
                    <span
                      className="info-icon-btn"
                      tabIndex={0}
                      role="button"
                      aria-label="Target branch and commit evaluation logic"
                    >
                      <svg viewBox="0 0 20 20" fill="currentColor" width="14" height="14">
                        <path
                          fillRule="evenodd"
                          d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z"
                          clipRule="evenodd"
                        />
                      </svg>
                    </span>
                    <span className="info-popover">
                      <span className="info-popover-title">Branch Evaluation Logic</span>
                      <span className="info-popover-item">
                        <strong>1. Left Blank / Omitted:</strong> Evaluates complete supported source files from the base branch (full snapshot evaluation).
                      </span>
                      <span className="info-popover-item">
                        <strong>2. Different from Base:</strong> Git diff identifies changed files between base and target; only complete target versions of changed files are evaluated.
                      </span>
                      <span className="info-popover-item">
                        <strong>3. Same as Base:</strong> Backend compares the latest commit with its parent; only files changed in the latest commit are evaluated.
                      </span>
                      <span className="info-popover-item">
                        <strong>4. Initial Commit:</strong> If base and target resolve to the same initial commit (no parent exists), all supported source files are treated as newly added.
                      </span>
                    </span>
                  </span>
                </label>
                <input
                  id="target_commit"
                  name="target_commit"
                  className="form-input"
                  placeholder="e.g. feature/auth or e4f5g6h"
                  value={form.target_commit}
                  onChange={handleChange}
                />
                <span className="form-hint">Branch or commit to evaluate against</span>
              </div>

              <div className="form-group">
                <label className="form-label" htmlFor="branch">
                  Branch
                  <span className="optional">(optional)</span>
                </label>
                <input
                  id="branch"
                  name="branch"
                  className="form-input"
                  placeholder="e.g. feature/auth"
                  value={form.branch}
                  onChange={handleChange}
                />
              </div>

              <div className="form-group">
                <label className="form-label" htmlFor="difficulty">
                  Difficulty
                </label>
                <select
                  id="difficulty"
                  name="difficulty"
                  className="form-select"
                  value={form.difficulty}
                  onChange={handleChange}
                >
                  <option value="EASY">Easy</option>
                  <option value="MEDIUM">Medium</option>
                  <option value="HARD">Hard</option>
                </select>
              </div>
            </div>
          </div>

          {/* ── Actions ─────────────────────────────── */}
          <div className="form-actions">
            <button
              type="button"
              className="btn btn-secondary"
              onClick={handleReset}
              disabled={loading}
            >
              Reset
            </button>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={loading}
            >
              {loading && <span className="spinner" />}
              {loading ? 'Evaluating…' : 'Run Evaluation'}
            </button>
          </div>
        </div>
      </form>

      {/* ── Error ──────────────────────────────────── */}
      {error && (
        <div className="error-alert">
          <span className="error-alert-icon">⚠</span>
          <span>{error}</span>
        </div>
      )}

      {/* ── Result ─────────────────────────────────── */}
      {result && (
        <div className="result-panel card">
          <div className="result-header">
            <div className={`result-score ${getScoreClass(result.score)}`}>
              {result.score}
            </div>
            <div className="result-meta">
              <h3>Evaluation Complete</h3>
              <span className={`result-status ${getStatusClass(result.status)}`}>
                {result.status}
              </span>
            </div>
          </div>

          <div className="result-summary">
            <h4>Summary</h4>
            <p>{result.summary}</p>
          </div>

          {result.rubric && Object.keys(result.rubric).length > 0 && (
            <div className="rubric-section">
              <h4>Rubric Breakdown</h4>
              <table className="rubric-table">
                <thead>
                  <tr>
                    <th>Metric</th>
                    <th>Score</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(result.rubric).map(([key, value]) => (
                    <tr key={key}>
                      <td>{key.replace(/_/g, ' ')}</td>
                      <td>{typeof value === 'object' ? JSON.stringify(value) : String(value)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {metricsOpen && <MetricsModal onClose={() => setMetricsOpen(false)} />}
    </>
  );
}
