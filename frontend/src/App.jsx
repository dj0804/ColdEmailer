import { useCallback, useEffect, useState } from 'react'
import { api } from './api'
import DraftReview from './DraftReview'
import AddContact from './AddContact'

const STAGE_STYLE = {
  draft: ['#eef2f7', '#475569'],
  pending_approval: ['#fff7e6', '#a16207'],
  sent: ['#eef6ff', '#1d4ed8'],
  recruiter_reply: ['#f0fdf4', '#15803d'],
  interview_request: ['#dcfce7', '#166534'],
  rejection: ['#fef2f2', '#b91c1c'],
  ghosted_dead: ['#f3f4f6', '#6b7280'],
}

function Stage({ value }) {
  const [bg, fg] = STAGE_STYLE[value] || ['#f3f4f6', '#374151']
  return (
    <span style={{
      background: bg, color: fg, borderRadius: 999, padding: '2px 10px',
      fontSize: 12, fontWeight: 600, whiteSpace: 'nowrap',
    }}>
      {value.replace(/_/g, ' ')}
    </span>
  )
}

const fmtDate = (s) =>
  s ? new Date(s).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }) : '—'

export default function App() {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(null)
  const [reviewId, setReviewId] = useState(null)

  const load = useCallback(async () => {
    try {
      setData(await api.dashboard())
      setError(null)
    } catch (e) {
      setError(e.message)
    }
  }, [])

  useEffect(() => { load() }, [load])

  async function run(label, fn) {
    setBusy(label)
    setError(null)
    try {
      await fn()
      await load()
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(null)
    }
  }

  if (reviewId) {
    return (
      <DraftReview
        draftId={reviewId}
        onClose={() => { setReviewId(null); load() }}
      />
    )
  }

  return (
    <div style={{ maxWidth: 1100, margin: '0 auto', padding: 24 }}>
      <header style={{ display: 'flex', alignItems: 'baseline', gap: 16, marginBottom: 20 }}>
        <h1 style={{ margin: 0, fontSize: 22 }}>Applier</h1>
        {data && (
          <span style={{ color: 'var(--muted)' }}>
            {data.pending_count} pending approval{data.pending_count === 1 ? '' : 's'} ·
            {' '}sent today {data.sends_today}/{data.daily_cap}
          </span>
        )}
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
          <button onClick={() => run('poll', api.pollReplies)} disabled={!!busy}>
            {busy === 'poll' ? 'Checking…' : 'Check replies'}
          </button>
          <button onClick={() => run('ghost', api.checkGhosting)} disabled={!!busy}>
            {busy === 'ghost' ? 'Running…' : 'Run nudge sweep'}
          </button>
          <button onClick={load} disabled={!!busy}>Refresh</button>
        </div>
      </header>

      {error && (
        <div style={{
          background: '#fef2f2', color: 'var(--danger)', border: '1px solid #fecaca',
          borderRadius: 8, padding: '10px 12px', marginBottom: 16,
        }}>
          {error}
        </div>
      )}

      <AddContact onDrafted={load} />

      {!data ? (
        <p style={{ color: 'var(--muted)' }}>Loading…</p>
      ) : (
        <>
          <section style={{
            background: 'var(--panel)', border: '1px solid var(--border)',
            borderRadius: 10, overflow: 'hidden',
          }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ background: '#fafbfc', textAlign: 'left' }}>
                  {['Company', 'Contact', 'Stage', 'Last contact', 'Silent', 'Pending'].map((h) => (
                    <th key={h} style={{
                      padding: '10px 12px', fontSize: 12, color: 'var(--muted)',
                      borderBottom: '1px solid var(--border)', fontWeight: 600,
                    }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.rows.length === 0 && (
                  <tr><td colSpan={6} style={{ padding: 20, color: 'var(--muted)' }}>
                    No applications yet.
                  </td></tr>
                )}
                {data.rows.map((r) => (
                  <tr key={r.application_id} style={{ borderBottom: '1px solid var(--border)' }}>
                    <td style={{ padding: '10px 12px', fontWeight: 600 }}>{r.company}</td>
                    <td style={{ padding: '10px 12px' }}>
                      <div>{r.contact_name || '—'}</div>
                      <div style={{ color: 'var(--muted)', fontSize: 12 }}>{r.contact_email || 'no contact'}</div>
                    </td>
                    <td style={{ padding: '10px 12px' }}>
                      <Stage value={r.stage} />
                      {r.last_reply_class && (
                        <div style={{ color: 'var(--muted)', fontSize: 11, marginTop: 2 }}>
                          last reply: {r.last_reply_class.replace(/_/g, ' ')}
                        </div>
                      )}
                    </td>
                    <td style={{ padding: '10px 12px' }}>{fmtDate(r.last_contact_at)}</td>
                    <td style={{ padding: '10px 12px', color: 'var(--muted)' }}>
                      {r.business_days_silent == null ? '—' : `${r.business_days_silent} bd`}
                    </td>
                    <td style={{ padding: '10px 12px' }}>
                      {r.pending_drafts.length === 0 ? (
                        <span style={{ color: 'var(--muted)' }}>—</span>
                      ) : (
                        r.pending_drafts.map((d) => (
                          <button key={d.id} className="primary" style={{ marginRight: 6 }}
                            onClick={() => setReviewId(d.id)}>
                            Review {d.type}
                          </button>
                        ))
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          {data.companies_without_application.length > 0 && (
            <section style={{ marginTop: 24 }}>
              <h2 style={{ fontSize: 15, margin: '0 0 8px' }}>Companies without an application</h2>
              <div style={{
                background: 'var(--panel)', border: '1px solid var(--border)',
                borderRadius: 10, padding: 12,
              }}>
                {data.companies_without_application.map((c) => (
                  <div key={c.company_id} style={{
                    display: 'flex', alignItems: 'center', gap: 12, padding: '6px 0',
                  }}>
                    <strong style={{ minWidth: 160 }}>{c.company}</strong>
                    <span style={{ color: 'var(--muted)', flex: 1 }}>
                      {c.contact_email || 'no contact found'}
                    </span>
                    {c.contact_email ? (
                      <button disabled={!!busy}
                        onClick={() => run(`gen${c.company_id}`, () => api.generateDrafts([c.company_id]))}>
                        {busy === `gen${c.company_id}` ? 'Drafting…' : 'Draft outreach'}
                      </button>
                    ) : (
                      <button disabled={!!busy}
                        onClick={() => run(`disc${c.company_id}`, () => api.discover(c.company_id))}>
                        {busy === `disc${c.company_id}` ? 'Searching…' : 'Find contact'}
                      </button>
                    )}
                  </div>
                ))}
              </div>
            </section>
          )}
        </>
      )}
    </div>
  )
}
