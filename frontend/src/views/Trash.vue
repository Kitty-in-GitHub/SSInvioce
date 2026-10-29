<template>
  <div>
    <div class="page-head">
      <div>
        <h1>回收站</h1>
        <p>删除的材料会在这里保留 {{ retentionDays }} 天；可恢复到收件箱或原条目，也可彻底删除</p>
      </div>
      <div class="actions">
        <button class="btn" type="button" :disabled="loading || busy" @click="load">刷新</button>
        <button class="btn btn-danger" type="button" :disabled="!count || busy" @click="purgeAll">
          清空回收站
        </button>
      </div>
    </div>

    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="msg" class="okmsg">{{ msg }}</p>
    <div v-if="loading" class="meta">加载中…</div>
    <div v-else-if="!count" class="card empty">回收站是空的。</div>

    <div v-else class="trash-groups">
      <section v-for="g in groups" :key="g.batch_id" class="card trash-group">
        <header class="trash-group-head">
          <div class="trash-group-meta">
            <strong>{{ reasonLabel(g.reason) }}</strong>
            <span class="meta"> · {{ formatTime(g.deleted_at) }} · {{ g.items.length }} 个文件</span>
            <span v-if="g.entry_title" class="meta"> · 原条目「{{ g.entry_title }}」</span>
          </div>
          <div class="actions">
            <button class="btn btn-sm" type="button" :disabled="busy" @click="restore(g.items)">
              全部恢复
            </button>
            <button class="btn btn-danger btn-sm" type="button" :disabled="busy" @click="purgeGroup(g)">
              彻底删除本批
            </button>
          </div>
        </header>
        <ul class="trash-items">
          <li v-for="it in g.items" :key="it.id" class="trash-item">
            <span class="trash-item-name" :title="it.original_name">{{ it.original_name }}</span>
            <span class="chip chip-muted">{{ typeLabel(it.type) }}</span>
            <span class="meta">{{ formatSize(it.size) }}</span>
            <div class="actions">
              <button class="btn btn-sm" type="button" :disabled="busy" @click="restore([it])">
                恢复
              </button>
              <button class="btn btn-danger btn-sm" type="button" :disabled="busy" @click="purgeItem(it)">
                彻底删除
              </button>
            </div>
          </li>
        </ul>
      </section>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { api, TYPE_LABELS } from '../api/client'
import { useSlots } from '../composables/useSlots'
import { useConfirmDialog } from '../composables/useConfirmDialog'

const retentionDays = 30
const { slotLabels } = useSlots()
const { askConfirm } = useConfirmDialog()
const groups = ref([])
const count = ref(0)
const loading = ref(true)
const busy = ref(false)
const error = ref('')
const msg = ref('')

function typeLabel(type) {
  return slotLabels.value[type] || TYPE_LABELS[type] || type
}

function reasonLabel(reason) {
  const map = {
    classify_discard: '整理丢弃',
    material_deleted: '删除材料',
    entry_deleted: '删除条目',
    replaced: '上传替换',
  }
  return map[reason] || '删除'
}

function formatTime(value) {
  if (!value) return '—'
  const dt = new Date(value)
  if (Number.isNaN(dt.getTime())) return value
  return dt.toLocaleString('zh-CN', { hour12: false })
}

function formatSize(size) {
  const n = Number(size)
  if (!Number.isFinite(n) || n <= 0) return '—'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const res = await api.listTrash()
    groups.value = res?.groups || []
    count.value = res?.count || 0
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

async function restore(items) {
  const ids = (items || []).map((it) => it.id)
  if (!ids.length) return
  busy.value = true
  error.value = ''
  msg.value = ''
  try {
    const res = await api.restoreTrash(ids)
    const results = res?.results || []
    const toEntry = results.filter((r) => r.ok && r.restored_to === 'entry').length
    const toInbox = results.filter((r) => r.ok && r.restored_to === 'inbox').length
    const failed = results.filter((r) => !r.ok).length
    const parts = []
    if (toEntry) parts.push(`回原条目 ${toEntry} 个`)
    if (toInbox) parts.push(`回收到收件箱 ${toInbox} 个`)
    if (failed) parts.push(`失败 ${failed} 个`)
    msg.value = parts.length ? `已恢复：${parts.join('，')}` : '没有可恢复的文件'
    await load()
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = false
  }
}

async function purgeItem(item) {
  const ok = await askConfirm({
    title: '彻底删除',
    message: `将永久删除「${item.original_name}」，无法恢复。`,
    confirmText: '彻底删除',
    cancelText: '取消',
    danger: true,
  })
  if (!ok) return
  busy.value = true
  error.value = ''
  try {
    await api.purgeTrash([item.id])
    msg.value = '已彻底删除'
    await load()
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = false
  }
}

async function purgeGroup(group) {
  const ids = (group?.items || []).map((it) => it.id)
  if (!ids.length) return
  const ok = await askConfirm({
    title: '彻底删除本批',
    message: `将永久删除这 ${ids.length} 个文件，无法恢复。`,
    confirmText: '彻底删除',
    cancelText: '取消',
    danger: true,
  })
  if (!ok) return
  busy.value = true
  error.value = ''
  try {
    await api.purgeTrash(ids)
    msg.value = `已彻底删除 ${ids.length} 个文件`
    await load()
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = false
  }
}

async function purgeAll() {
  const ok = await askConfirm({
    title: '清空回收站',
    message: `将永久删除回收站里的 ${count.value} 个文件，无法恢复。`,
    confirmText: '清空',
    cancelText: '取消',
    danger: true,
  })
  if (!ok) return
  busy.value = true
  error.value = ''
  try {
    const res = await api.purgeAllTrash()
    msg.value = `已清空（${res?.purged ?? 0} 个文件）`
    await load()
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = false
  }
}

onMounted(load)
</script>
