import { useState } from 'react'
import { api } from './api'

const BLANK = {
  company_name: '',
  domain: '',
  contact_name: '',
  email: '',
  title: '',
  target_role: '',
}

/** Add a contact you sourced yourself and draft outreach to them in one step. */
export default function AddContact({ onDrafted }) {
  const [open, setOpen] = useState(false)
  const [f, setF] = useState(BLANK)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [done, setDone] = useState(null)
  const [sendNow, setSendNow] = useState(false)

  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })
  // Send-now works with just an email (nameless role inboxes get a generic draft).
  const ready = f.email.includes('@') && (sendNow || (f.company_name.trim() && f.contact_name.trim()))

  async function submit(e) {
    e.preventDefault()
    setBusy(true); setError(null); setDone(null)
    try {
      const common = {
        ...f,
        domain: f.domain || null,
        title: f.title || null,
        target_role: f.target_role || null,
        contact_name: f.contact_name || null,
        company_name: f.company_name || null,
      }
      if (sendNow) {
        const res = await api.quickSend({ ...common, send_now: true })
        setDone({ sent: true, to: res.to })
      } else {
        const draft = await api.manualContact(common)
        setDone({ id: draft.id })
      }
      setF(BLANK)
      onDrafted?.()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  if (!open) {
    return (
      <button style={{ marginBottom: 16 }} onClick={() => setOpen(true)}>
        + Add a contact manually
      </button>
    )
  }

  return (
    <section style={{
      background: 'var(--panel)', border: '1px solid var(--border)',
      borderRadius: 10, padding: 16, marginBottom: 20,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 12 }}>
        <strong>Add a contact manually</strong>
        <span style={{ color: 'var(--muted)', fontSize: 12, marginLeft: 10 }}>
          no discovery API used — drafts straight to approval
        </span>
        <button style={{ marginLeft: 'auto' }} onClick={() => { setOpen(false); setDone(null) }}>
          Close
        </button>
      </div>

      {error && (
        <div style={{
          background: '#fef2f2', color: 'var(--danger)', border: '1px solid #fecaca',
          borderRadius: 8, padding: '8px 10px', marginBottom: 12, fontSize: 13,
        }}>{error}</div>
      )}
      {done && (
        <div style={{
          background: '#f0fdf4', color: '#166534', border: '1px solid #bbf7d0',
          borderRadius: 8, padding: '8px 10px', marginBottom: 12, fontSize: 13,
        }}>
          {done.sent
            ? `Sent to ${done.to}.`
            : `Draft #${done.id} created — review it in the table below.`}
        </div>
      )}

      <form onSubmit={submit} style={{ display: 'grid', gap: 10 }}>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
          <Field label="Company *" value={f.company_name} onChange={set('company_name')}
            placeholder="Netradyne" />
          <Field label="Domain" value={f.domain} onChange={set('domain')}
            placeholder="netradyne.com (optional)" />
          <Field label="Contact name *" value={f.contact_name} onChange={set('contact_name')}
            placeholder="Priya Sharma" />
          <Field label="Email *" value={f.email} onChange={set('email')}
            placeholder="priya@netradyne.com" />
          <Field label="Their title" value={f.title} onChange={set('title')}
            placeholder="Head of ML (helps personalise)" />
          <Field label="Target role" value={f.target_role} onChange={set('target_role')}
            placeholder="Computer Vision Intern (picks the resume)" />
        </div>
        <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13 }}>
          <input type="checkbox" checked={sendNow} style={{ width: 'auto' }}
            onChange={(e) => setSendNow(e.target.checked)} />
          Send immediately (skip approval) — for role inboxes like careers@/hr@; a
          name isn’t required and a generic eager email is used.
        </label>
        <div>
          <button className="primary" type="submit" disabled={!ready || busy}>
            {busy ? (sendNow ? 'Sending…' : 'Drafting…')
                  : (sendNow ? 'Draft & send now' : 'Add & draft outreach')}
          </button>
          <span style={{ color: 'var(--muted)', fontSize: 12, marginLeft: 10 }}>
            {sendNow ? 'This sends the email right away.' : 'Nothing sends until you approve it.'}
          </span>
        </div>
      </form>
    </section>
  )
}

function Field({ label, ...props }) {
  return (
    <label style={{ display: 'block' }}>
      <span style={{ fontSize: 12, color: 'var(--muted)', fontWeight: 600 }}>{label}</span>
      <input {...props} style={{ marginTop: 4 }} />
    </label>
  )
}
