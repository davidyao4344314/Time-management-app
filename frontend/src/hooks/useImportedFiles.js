import { useEffect, useRef, useState } from 'react'

async function fileApi(options = {}) {
  const response = await fetch('/api/files', { credentials: 'same-origin', ...options })
  const data = await response.json()
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Could not access imported files.')
  return data
}

export default function useImportedFiles() {
  const [files, setFiles] = useState([])
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const controller = useRef(null)
  const active = useRef(false)
  const uploadingNow = useRef(false)

  useEffect(() => {
    active.current = true
    const request = new AbortController()
    controller.current = request
    fileApi({ signal: request.signal }).then(data => {
      if (!request.signal.aborted) setFiles(data.files)
    }).catch(failure => {
      if (!request.signal.aborted) setError(failure.message)
    }).finally(() => {
      if (!request.signal.aborted) setLoading(false)
    })
    return () => { active.current = false; controller.current?.abort() }
  }, [])

  async function upload(file) {
    if (!active.current || uploadingNow.current) return false
    setError('')
    setMessage('')
    if (!file || !/\.(txt|pdf|docx)$/i.test(file.name)) {
      setError('Choose a .txt, .pdf or .docx file.')
      return false
    }
    if (file.size > 5 * 1024 * 1024 || file.size === 0) {
      setError('Choose a non-empty file of at most 5 MB.')
      return false
    }
    uploadingNow.current = true
    controller.current?.abort()
    const request = new AbortController()
    controller.current = request
    setUploading(true)
    setLoading(false)
    try {
      const form = new FormData()
      form.append('file', file)
      const imported = await fileApi({ method: 'POST', body: form, signal: request.signal })
      if (request.signal.aborted || !active.current) return false
      setFiles(current => [imported, ...current.filter(item => item.file_id !== imported.file_id)])
      setMessage(`Imported ${imported.filename}. No AI request was made. Mention its filename or choose “Use in question”.`)
      return true
    } catch (failure) {
      if (!request.signal.aborted && active.current) setError(failure.message)
      return false
    } finally {
      uploadingNow.current = false
      if (!request.signal.aborted && active.current) setUploading(false)
    }
  }

  return { files, loading, uploading, message, error, upload }
}
