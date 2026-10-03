function AgentContextInspector({ context, actions = [] }) {
  return (
    <details className="agent-context">
      <summary>How the agent used context</summary>
      {context ? (
        <>
          <p className="agent-context-note">{context.authority_note}</p>
          <section aria-label="Routing">
            <h3>Routing</h3>
            <p><strong>{context.routing.label || 'Routing metadata unavailable'}</strong></p>
            <dl className="agent-context-fields">
              <dt>Status</dt><dd>{context.routing.status || 'Unavailable'}</dd>
              <dt>Intent</dt><dd>{context.routing.intent || 'Not classified by this stage'}</dd>
              <dt>Time scope</dt><dd>{context.routing.time_scope || 'Not specified'}</dd>
            </dl>
            <p>{context.routing.reason}</p>
          </section>

          <section aria-label="Context sources">
            <h3>Context Sources</h3>
            <ul className="agent-context-list">
              {context.context_sources.map((source) => (
                <li key={source.source}>
                  <strong>{source.label}</strong> — {source.selected ? 'Selected' : 'Not selected'}
                  <span className="agent-context-authority">{source.authority}</span>
                  <p>{source.reason}</p>
                </li>
              ))}
            </ul>
          </section>

          {context.context_status && (
            <section aria-label="Context recovery">
              <h3>Context Recovery</h3>
              <dl className="agent-context-fields">
                {Object.entries(context.context_status).map(([source, status]) => (
                  <div className="agent-context-field" key={source}>
                    <dt>{source.replaceAll('_', ' ')}</dt>
                    <dd>{context.initial_context_status?.[source] === status
                      ? status
                      : `${context.initial_context_status?.[source] || 'Unknown'} → ${status}`}</dd>
                  </div>
                ))}
              </dl>
              {context.context_recovery && (
                <>
                  <p>
                    Main-agent calls: {context.context_recovery.main_agent_attempts}
                    {' · '}Recovery attempts: {context.context_recovery.attempts}/{context.context_recovery.max_retries}
                    {' · '}Status: {context.context_recovery.status}
                  </p>
                  {context.context_recovery.requests.map((request) => (
                    <p key={request.source}>
                      {request.source} / {request.time_scope}: {request.status_before} → {request.status_after}
                    </p>
                  ))}
                </>
              )}
            </section>
          )}

          <section aria-label="Retrieved memory">
            <h3>Retrieved Memory</h3>
            <p>{context.memory_message}</p>
            {context.memory_lookups.map((lookup, index) => (
              <p key={index} className="agent-context-note">
                {lookup.phase} lookup: {lookup.status} · {lookup.result_count} results
                {lookup.scope ? ` · ${lookup.scope}` : ''}
                {lookup.truncated ? ' · Results limited' : ''}
                {lookup.unavailable_sources.length > 0 ? ` · Unavailable: ${lookup.unavailable_sources.join(', ')}` : ''}
              </p>
            ))}
            <ul className="agent-context-list">
              {context.retrieved_memory.map((item, index) => (
                <li key={`${item.source_type}-${item.source_id}-${index}`}>
                  <strong>{item.label}</strong>
                  {item.category && <span> · {item.category}</span>}
                  <p className="agent-context-excerpt">{item.excerpt}</p>
                  <p>{item.reason}</p>
                  <p>{item.used_in_model ? 'Included in model context' : 'Retrieved, but not sent in an additional model call'}</p>
                  <details>
                    <summary>Provenance details</summary>
                    <dl className="agent-context-fields">
                      <dt>Source ID</dt><dd>{item.source_id || 'Unavailable'}</dd>
                      {item.conversation_id && <><dt>Conversation</dt><dd>{item.conversation_id}</dd></>}
                      {item.timestamp && <><dt>Timestamp</dt><dd>{item.timestamp}</dd></>}
                      {item.period_start && <><dt>Period start</dt><dd>{item.period_start}</dd></>}
                      {item.period_end && <><dt>Period end</dt><dd>{item.period_end}</dd></>}
                      {item.time_match && <><dt>Time match</dt><dd>{item.time_match}</dd></>}
                      {item.source_refs.length > 0 && <><dt>Source references</dt><dd>{item.source_refs.join(', ')}</dd></>}
                    </dl>
                  </details>
                </li>
              ))}
            </ul>
          </section>
        </>
      ) : <p>Context metadata is unavailable for this response.</p>}

      <section aria-label="Proposed actions">
        <h3>Proposed Actions</h3>
        <p>Proposals only. This panel does not execute actions.</p>
        {actions.length === 0 ? <p>No actions proposed.</p> : (
          <ul className="agent-context-list">
            {actions.map((action, index) => (
              <li key={index}>
                <strong>{action.tool}</strong>
                <dl className="agent-context-fields">
                  {Object.entries(action.arguments).map(([field, value]) => (
                    <div className="agent-context-field" key={field}>
                      <dt>{field.replaceAll('_', ' ')}</dt>
                      <dd>{value === null ? 'Not set' : String(value)}</dd>
                    </div>
                  ))}
                </dl>
              </li>
            ))}
          </ul>
        )}
      </section>
    </details>
  )
}

export default AgentContextInspector
