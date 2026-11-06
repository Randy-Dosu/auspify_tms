/** Small shared UI primitives used across pages. */

export function Alert({ tone = 'error', children }) {
  if (!children) return null
  return (
    <div className={`alert ${tone}`} role={tone === 'error' ? 'alert' : 'status'}>
      {children}
    </div>
  )
}

/** Centred message used for loading / 403 / 404 states. */
export function FullPageMessage({ title, body, tone, linkTo, linkLabel }) {
  return (
    <main className="page">
      <section className="card center-card">
        <h1 className={tone === 'error' ? 'text-danger' : undefined}>{title}</h1>
        {body && <p className="muted">{body}</p>}
        {linkTo && (
          <p>
            <a className="btn" href={linkTo}>
              {linkLabel || 'Continue'}
            </a>
          </p>
        )}
      </section>
    </main>
  )
}

export function Spinner({ label = 'Loading…' }) {
  return (
    <p className="muted small" role="status">
      {label}
    </p>
  )
}

export function Badge({ tone = 'neutral', children }) {
  return <span className={`badge ${tone}`}>{children}</span>
}

/** Labelled form input with inline error text. */
export function Field({ label, error, hint, id, ...props }) {
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <input id={id} {...props} aria-invalid={error ? 'true' : 'false'} />
      {hint && !error && <span className="hint">{hint}</span>}
      {error && <span className="field-error">{error}</span>}
    </div>
  )
}

export function PageHeader({ title, subtitle, actions }) {
  return (
    <header className="page-header">
      <div>
        <h1>{title}</h1>
        {subtitle && <p className="muted">{subtitle}</p>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </header>
  )
}
