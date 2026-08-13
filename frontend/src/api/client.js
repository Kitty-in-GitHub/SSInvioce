async function formatDetail(detail) {
  if (detail == null) return ''
  if (typeof detail === 'string') return detail
  if (detail.message) {
    const missing = detail.missing?.length ? `（缺：${detail.missing.join(', ')}）` : ''
    const incomplete = detail.incomplete?.length
      ? `；不齐套：${detail.incomplete.map((x) => x.title || x.entry_id).join('、')}`
      : ''
    return `${detail.message}${missing}${incomplete}`
  }
  try {
    return JSON.stringify(detail)
  } catch {
    return String(detail)
  }
}

async function request(path, options = {}) {
  let res
  try {
    res = await fetch(path, options)
  } catch (e) {
    throw new Error(`无法连接后端（${path}）。请先启动 API（默认端口 8765），再刷新页面。原始错误：${e.message}`)
  }

  const contentType = res.headers.get('content-type') || ''
  let data = null
  if (contentType.includes('application/json')) {
    data = await res.json()
  } else if (!res.ok) {
    data = await res.text()
  }

  if (!res.ok) {
    const detail = data?.detail ?? data ?? res.statusText
    let message = await formatDetail(detail)
    if (res.status === 404) {
      message = `接口不存在或后端不是本项目（${options.method || 'GET'} ${path}）。请确认 Vite 代理指向 8765，且运行的是报销助手 API。详情：${message || 'Not Found'}`
    }
    const err = new Error(message || res.statusText)
    err.status = res.status
    err.detail = detail
    throw err
  }
  return data
}

export const EXPECTED_SERVICE = 'star-invoice-helper'

export async function checkApiHealth() {
  const data = await request('/api/health')
  if (!data?.ok || data.service !== EXPECTED_SERVICE) {
    throw new Error(
      `后端健康检查异常：期望 service=${EXPECTED_SERVICE}，实际 ${JSON.stringify(data)}。当前代理可能连到了其他程序。`,
    )
  }
  return data
}

export const api = {
  health: checkApiHealth,
  listEntries: () => request('/api/entries'),
  createEntry: (body) =>
    request('/api/entries', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  getEntry: (id) => request(`/api/entries/${id}`),
  updateEntry: (id, body) =>
    request(`/api/entries/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  deleteEntry: (id) => request(`/api/entries/${id}`, { method: 'DELETE' }),
  uploadMaterial: async (file, { entryId, type } = {}) => {
    const fd = new FormData()
    fd.append('file', file)
    if (entryId != null) fd.append('entry_id', String(entryId))
    if (type) fd.append('type', type)
    return request('/api/materials/upload', { method: 'POST', body: fd })
  },
  listInbox: () => request('/api/materials/inbox'),
  updateMaterial: (id, body) =>
    request(`/api/materials/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  deleteMaterial: (id) => request(`/api/materials/${id}`, { method: 'DELETE' }),
  classifyPreview: async (files) => {
    const fd = new FormData()
    for (const f of files) fd.append('files', f)
    return request('/api/classify/preview', { method: 'POST', body: fd })
  },
  classifyRecluster: (tempIds) =>
    request('/api/classify/recluster', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ temp_ids: tempIds || null }),
    }),
  classifyConfirm: (payload) =>
    request('/api/classify/confirm', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(Array.isArray(payload) ? { items: payload, clusters: [] } : payload),
    }),
  composeEntry: async (id) => {
    let res
    try {
      res = await fetch(`/api/entries/${id}/compose`, { method: 'POST' })
    } catch (e) {
      throw new Error(`无法连接后端进行拼版：${e.message}`)
    }
    if (!res.ok) {
      const data = await res.json().catch(() => ({}))
      const detail = data.detail ?? res.statusText
      throw new Error(await formatDetail(detail) || res.statusText)
    }
    const blob = await res.blob()
    const disposition = res.headers.get('content-disposition') || ''
    const match = /filename\*=UTF-8''([^;]+)|filename="?([^";]+)"?/i.exec(disposition)
    const filename = decodeURIComponent(match?.[1] || match?.[2] || `entry_${id}.pdf`)
    return { blob, filename }
  },
  composeBatch: async (entryIds) => {
    let res
    try {
      res = await fetch('/api/entries/compose-batch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ entry_ids: entryIds }),
      })
    } catch (e) {
      throw new Error(`无法连接后端进行批量拼版：${e.message}`)
    }
    if (!res.ok) {
      const data = await res.json().catch(() => ({}))
      const detail = data.detail ?? res.statusText
      throw new Error(await formatDetail(detail) || res.statusText)
    }
    const blob = await res.blob()
    const disposition = res.headers.get('content-disposition') || ''
    const match = /filename\*=UTF-8''([^;]+)|filename="?([^";]+)"?/i.exec(disposition)
    const filename = decodeURIComponent(match?.[1] || match?.[2] || `batch_${entryIds.length}.pdf`)
    return { blob, filename }
  },
  listGroups: () => request('/api/groups'),
  createGroup: (body) =>
    request('/api/groups', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  updateGroup: (id, body) =>
    request(`/api/groups/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  deleteGroup: (id) => request(`/api/groups/${id}`, { method: 'DELETE' }),
  reparseAmount: (id, force = false) =>
    request(`/api/entries/${id}/reparse-amount`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ force }),
    }),
  composeGroup: async (groupId) => {
    let res
    try {
      res = await fetch(`/api/groups/${groupId}/compose`, { method: 'POST' })
    } catch (e) {
      throw new Error(`无法连接后端进行组拼版：${e.message}`)
    }
    if (!res.ok) {
      const data = await res.json().catch(() => ({}))
      const detail = data.detail ?? res.statusText
      throw new Error(await formatDetail(detail) || res.statusText)
    }
    const blob = await res.blob()
    const disposition = res.headers.get('content-disposition') || ''
    const match = /filename\*=UTF-8''([^;]+)|filename="?([^";]+)"?/i.exec(disposition)
    const filename = decodeURIComponent(match?.[1] || match?.[2] || `group_${groupId}.pdf`)
    return { blob, filename }
  },
  getSettings: () => request('/api/settings'),
  updateSettings: (payload) =>
    request('/api/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  resetClassifyKeywords: () =>
    request('/api/settings/classify-keywords/reset', { method: 'POST' }),
}

export function formatAmount(val) {
  if (val == null || val === '') return '—'
  const n = Number(val)
  if (Number.isNaN(n)) return '—'
  return `¥${n.toFixed(2)}`
}

export const TYPE_LABELS = {
  invoice: '发票',
  order: '订单截图',
  payment: '支付记录',
  unknown: '未分类',
}

export function missingLabel(missing) {
  return (missing || []).map((t) => TYPE_LABELS[t] || t).join('、')
}

export function isImageMaterial(m) {
  if (!m) return false
  const name = m.original_name || m.name || ''
  return (m.mime || '').startsWith('image/') || /\.(png|jpe?g|webp|gif|bmp)$/i.test(name)
}

export function isPdfMaterial(m) {
  if (!m) return false
  const name = m.original_name || m.name || ''
  return (m.mime || '').toLowerCase() === 'application/pdf' || /\.pdf$/i.test(name)
}
