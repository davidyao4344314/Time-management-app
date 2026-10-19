const measurements = {
  reported: 'API reported', estimated: 'Estimated', mixed: 'Reported + estimates',
  local: 'Local / no model tokens', unavailable: 'Unavailable',
}

function count(value, approximate = false) {
  return Number.isSafeInteger(value) && value >= 0
    ? `${approximate ? '≈' : ''}${value.toLocaleString('en-US')}` : 'Unknown'
}

export default function TokenUsagePanel({ usage }) {
  if (!usage?.totals || !Array.isArray(usage.stages)) {
    return <section aria-label="Token usage"><h3>Token Usage</h3>
      <p className="agent-context-note">Token usage is unavailable for this older response.</p></section>
  }
  const totals = usage.totals
  const approximate = ['estimated', 'mixed'].includes(totals.measurement)
  return <section aria-label="Token usage">
    <h3>Token Usage</h3>
    <p>{measurements[totals.measurement] || 'Unavailable'} · {count(totals.model_calls)} model calls</p>
    <dl className="agent-context-fields">
      <dt>Total input</dt><dd>{count(totals.input_tokens, approximate)}</dd>
      <dt>Total output</dt><dd>{count(totals.output_tokens, approximate)}</dd>
      <dt>Total tokens</dt><dd>{count(totals.total_tokens, approximate)}</dd>
    </dl>
    <p className="agent-context-note">{usage.note}</p>
    <ul className="agent-context-list">
      {usage.stages.map((stage, index) => <li key={`${stage.stage}-${stage.call}-${index}`}>
        <strong>{stage.label}</strong>
        <p>{stage.model ? `${stage.model} · ` : ''}{stage.status.replaceAll('_', ' ')}
          {' · '}{measurements[stage.measurement] || 'Unavailable'}</p>
        <dl className="agent-context-fields">
          <dt>Input</dt><dd>{count(stage.input_tokens, stage.measurement === 'estimated')}</dd>
          <dt>Output</dt><dd>{count(stage.output_tokens, stage.measurement === 'estimated')}</dd>
          <dt>Total</dt><dd>{count(stage.total_tokens, stage.measurement === 'estimated')}</dd>
          {stage.measurement === 'reported' && <>
            <dt>Cached input (included)</dt><dd>{count(stage.cached_input_tokens)}</dd>
            <dt>Reasoning output (included)</dt><dd>{count(stage.reasoning_output_tokens)}</dd>
          </>}
        </dl>
        {Object.values(stage.context_estimates || {}).some(value => value > 0) && <details>
          <summary>Estimated input breakdown</summary>
          <p className="agent-context-note">{usage.estimate_method} These components are estimates even when the API total is reported.</p>
          <dl className="agent-context-fields">
            {Object.entries(stage.context_estimates).filter(([, value]) => value > 0).map(([name, value]) =>
              <div className="agent-context-field" key={name}>
                <dt>{name.replaceAll('_', ' ')}</dt><dd>{count(value, true)}</dd>
              </div>)}
          </dl>
        </details>}
      </li>)}
    </ul>
    <p className="agent-context-note">This is token telemetry, not a dollar charge. Historical replies are not recalculated. No extra AI request is made to count tokens.</p>
  </section>
}
