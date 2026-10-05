import { useRef, useState } from 'react'
import useImportedFiles from '../hooks/useImportedFiles'
import './FileImportPanel.css'

function FileImportPanel({ disabled = false, canAsk = true, onUseFile }) {
  const state = useImportedFiles()
  const [selected, setSelected] = useState(null)
  const input = useRef(null)

  async function importFile(event) {
    event.preventDefault()
    if (await state.upload(selected)) {
      setSelected(null)
      if (input.current) input.current.value = ''
    }
  }

  return <details className="file-import-panel">
    <summary>Files for AI context</summary>
    <p className="agent-context-note">Import text-based TXT, PDF or Word files (up to 5 MB). Uploading is local and does not call AI. Only relevant excerpts are sent when you ask about a file. Do not upload secrets.</p>
    <form onSubmit={importFile} className="file-import-form">
      <label htmlFor="agent-file">Choose a file</label>
      <input ref={input} id="agent-file" type="file" accept=".txt,.pdf,.docx" disabled={disabled || state.uploading}
        onChange={event => setSelected(event.target.files[0] || null)} />
      <button className="chat-secondary" type="submit" disabled={disabled || state.uploading || !selected}>
        {state.uploading ? 'Importing file…' : 'Import File'}
      </button>
    </form>
    {state.loading && <p role="status">Loading imported files…</p>}
    {state.message && <p role="status">{state.message}</p>}
    {state.error && <p className="chat-error" role="alert">{state.error}</p>}
    {!state.loading && state.files.length === 0 && <p>No files imported yet.</p>}
    {!canAsk && <p className="agent-context-note">You can import now. Start a New Chat to ask about your files.</p>}
    <ul className="file-import-list">
      {state.files.map(file => <li key={file.file_id}>
        <strong>{file.filename}</strong><span>{file.file_type.toUpperCase()} · {file.chunk_count} chunks</span>
        <code>{file.file_id}</code>
        <button type="button" className="chat-secondary" disabled={disabled || state.uploading || !canAsk} onClick={() => onUseFile(file)}>Use in question</button>
      </li>)}
    </ul>
    {state.files.length >= 100 && <p className="agent-context-note">Showing the latest 100 uploads. Older files can still be referenced by filename or ID.</p>}
  </details>
}

export default FileImportPanel
