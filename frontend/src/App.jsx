import EvaluationForm from './components/EvaluationForm';

export default function App() {
  return (
    <div className="app">
      <header className="app-header">
        <div className="app-header-inner">
          <div className="app-logo">DG</div>
          <span className="app-title">DevGrow AI Evaluator</span>
          <span className="app-subtitle">Code Evaluation Platform</span>
        </div>
      </header>

      <main className="app-main">
        <div className="hero">
          <div className="hero-badge">
            <span className="hero-badge-dot" />
            Evaluation Engine
          </div>
          <h1>Evaluate Code Changes</h1>
          <p>
            Submit project context, task details, and git commit info to get an
            AI-powered evaluation of code quality and acceptance criteria
            coverage.
          </p>
        </div>

        <EvaluationForm />
      </main>
    </div>
  );
}
