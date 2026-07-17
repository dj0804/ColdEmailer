import { useEffect, useState } from 'react'
import { api } from './api'

export default function DraftReview({ draftId, onClose }) {
  const [draft, setDraft] = useState(null)
  const [subject, setSubject] = useState('')
  const [body, setBody] = useState('')
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(null)
  const [sent, setSent] = useState(null)

  useEffect(() => {
    api.getDraft(draftId)
      .then((d) => { setDraft(d); setSubject(d.subject); setBody(d.body) })
      .catch((e) => setError(e.message))
  }, [draftId])

  const dirty = draft && (subject !== draft.subject || body !== draft.body)
  const attachments = draft?.attachment_paths ? JSON.parse(draft.attachment_paths) : []

  async function save() {
    setBusy('save'); setError(null)
    try {
      const d = await api.editDraft(draftId, { subject, body })
      setDraft(d)
    } catch (e) { setError(e.message) } finally { setBusy(null) }
  }

  async function approve() {
    setBusy('approve'); setError(null)
    try {
      // Persist edits first — editing re-opens approval, so this must precede send.
      if (dirty) await api.editDraft(draftId, { subject, body })
      setSent(await api.approveDraft(draftId))
    } catch (e) { setError(e.message) } finally { setBusy(null) }
  }

  async function reject() {
    setBusy('reject'); setError(null)
    try { await api.rejectDraft(draftId); onClose() }
    catch (e) { setError(e.message); setBusy(null) }
  }

  if (!draft && !error) return <p style={{ padding: 24 }}>Loading…</p>

  return (
    <div style={{ maxWidth: 800, margin: '0 auto', padding: 24 }}>
      <button onClick={onClose} style={{ marginBottom: 16 }}>← Back to dashboard</button>

      {error && (
        <div style={{
          background: '#fef2f2', color: 'var(--danger)', border: '1px solid #fecaca',
          borderRadius: 8, padding: '10px 12px', marginBottom: 16,
        }}>{error}</div>
      )}

      {sent ? (
        <div style={{
          background: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: 10, padding: 20,
        }}>
          <h2 style={{ margin: '0 0 8px', fontSize: 17, color: '#166534' }}>Sent ✓</h2>
          <p style={{ margin: 0 }}>
            Delivered to <strong>{sent.to}</strong> at {new Date(sent.sent_at).toLocaleString()}.
          </p>
          <button className="primary" style={{ marginTop: 14 }} onClick={onClose}>
            Back to dashboard
          </button>
        </div>
      ) : draft && (
        <div style={{
          background: 'var(--panel)', border: '1px solid var(--border)',
          borderRadius: 10, padding: 20,
        }}>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center', marginBottom: 16 }}>
            <span style={{
              background: '#fff7e6', color: '#a16207', borderRadius: 999,
              padding: '2px 10px', fontSize: 12, fontWeight: 600,
            }}>{draft.type}</span>
            <span style={{ color: 'var(--muted)', fontSize: 13 }}>
              status: {draft.status}
              {draft.status !== 'approved' && ' · nothing sends until you approve'}
            </span>
          </div>

          <label style={{ fontSize: 12, color: 'var(--muted)', fontWeight: 600 }}>Subject</label>
          <input value={subject} onChange={(e) => setSubject(e.target.value)}
            style={{ marginTop: 4, marginBottom: 14 }} />

          <label style={{ fontSize: 12, color: 'var(--muted)', fontWeight: 600 }}>Body</label>
          <textarea rows={18} value={body} onChange={(e) => setBody(e.target.value)}
            style={{ marginTop: 4 }} />

          <div style={{ margin: '14px 0', fontSize: 13, color: 'var(--muted)' }}>
            Attachments: {attachments.length === 0
              ? 'none'
              : attachments.map((p) => p.split(/[\\/]/).pop()).join(', ')}
          </div>

          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <button className="primary" onClick={approve} disabled={!!busy}>
              {busy === 'approve' ? 'Sending…' : 'Approve & send'}
            </button>
            <button onClick={save} disabled={!!busy || !dirty}>
              {busy === 'save' ? 'Saving…' : 'Save edits'}
            </button>
            <button className="danger" onClick={reject} disabled={!!busy}
              style={{ marginLeft: 'auto' }}>
              Discard
            </button>
          </div>
          {dirty && (
            <p style={{ color: 'var(--muted)', fontSize: 12, marginBottom: 0 }}>
              Unsaved edits — “Approve &amp; send” saves them first.
            </p>
          )}
        </div>
      )}
    </div>
  )
}
