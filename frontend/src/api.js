async function req(path, options = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  const text = await res.text()
  const data = text ? JSON.parse(text) : null
  if (!res.ok) throw new Error(data?.detail || `${res.status} ${res.statusText}`)
  return data
}

export const api = {
  dashboard: () => req('/api/dashboard'),
  getDraft: (id) => req(`/api/drafts/${id}`),
  editDraft: (id, body) => req(`/api/drafts/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  approveDraft: (id) => req(`/api/drafts/${id}/approve`, { method: 'POST' }),
  rejectDraft: (id) => req(`/api/drafts/${id}/reject`, { method: 'POST' }),
  batchApprove: (batchId) => req(`/api/drafts/batch/${batchId}/approve`, { method: 'POST' }),
  generateDrafts: (companyIds) =>
    req('/api/drafts/batch/generate', {
      method: 'POST',
      body: JSON.stringify({ company_ids: companyIds }),
    }),
  discover: (companyId) => req(`/api/companies/${companyId}/discover`, { method: 'POST', body: '{}' }),
  manualContact: (body) =>
    req('/api/companies/manual-contact', { method: 'POST', body: JSON.stringify(body) }),
  quickSend: (body) =>
    req('/api/companies/quick-send', { method: 'POST', body: JSON.stringify(body) }),
  jobsStatus: () => req('/api/jobs/status'),
  pollReplies: () => req('/api/jobs/poll-replies', { method: 'POST' }),
  checkGhosting: () => req('/api/jobs/check-ghosting', { method: 'POST' }),
}
