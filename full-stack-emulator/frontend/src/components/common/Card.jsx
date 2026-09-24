import { useState } from 'react'

export default function Card({ title, subtitle, actions, children, collapsible = false, defaultExpanded = true }) {
  const [expanded, setExpanded] = useState(defaultExpanded)

  return (
    <section className="card">
      <div className="card-header">
        <div className="card-header-copy">
          <h3>{title}</h3>
          {subtitle ? <p>{subtitle}</p> : null}
        </div>
        {(actions || collapsible) ? (
          <div className="card-actions">
            {actions}
            {collapsible ? (
              <button className="card-toggle" onClick={() => setExpanded((value) => !value)}>
                {expanded ? 'Collapse' : 'Expand'}
              </button>
            ) : null}
          </div>
        ) : null}
      </div>
      {(!collapsible || expanded) ? children : null}
    </section>
  )
}
