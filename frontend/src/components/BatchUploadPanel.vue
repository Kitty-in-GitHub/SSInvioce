<template>
  <div class="batch-upload-panel">
    <div
      class="dropzone"
      :class="{ active: dragging }"
      @dragover.prevent="dragging = true"
      @dragleave.prevent="dragging = false"
      @drop.prevent="onDrop"
      @click="fileInput?.click()"
    >
      拖拽文件到此处，或点击选择（PDF / JPG / PNG）
      <p class="meta dropzone-hint">将自动 OCR / 读发票文本，按金额等线索归入拟建条目</p>
      <input
        ref="fileInput"
        type="file"
        multiple
        hidden
        accept=".pdf,.jpg,.jpeg,.png,.webp,.bmp,.gif"
        @change="onPick"
      />
    </div>

    <p v-if="ocrHint" class="meta">{{ ocrHint }}</p>
    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="msg" class="okmsg">{{ msg }}</p>

    <div v-if="clusters.length" class="cluster-list">
      <h4 class="cluster-section-title">拟建条目（{{ clusters.length }}）</h4>
      <section v-for="c in clusters" :key="c.cluster_id" class="cluster-card card">
        <header class="cluster-card-head">
          <div class="cluster-title-amount">
            <input v-model="c.title" class="cluster-title-input" placeholder="项目名" />
            <div class="amount-edit cluster-amount-edit">
              <span class="amount-prefix">¥</span>
              <input
                type="number"
                step="0.01"
                min="0"
                :value="c.amount ?? ''"
                placeholder="金额"
                @change="onClusterAmount(c, $event)"
              />
            </div>
          </div>
          <span class="chip" :class="c.complete ? 'chip-ok' : 'chip-warn'">
            {{ c.complete ? '齐套' : `缺：${missingLabel(c.missing)}` }}
          </span>
        </header>
        <div v-if="c.duplicate_warning" class="dup-warn">
          <p>{{ formatDupWarn(c.duplicate_warning) }}</p>
          <div class="dup-warn-actions">
            <button type="button" class="btn btn-sm" @click="openCompare(c)">对比查看</button>
            <button
              v-if="c.duplicate_warning.existing_entry_id != null"
              type="button"
              class="btn btn-danger btn-sm"
              @click="deleteExistingEntry(c)"
            >
              删除已有条目
            </button>
            <button type="button" class="btn btn-sm" @click="discardCluster(c)">放弃本拟建条目</button>
          </div>
        </div>
        <div class="cluster-slots">
          <div v-for="slot in slotTypes" :key="slot" class="cluster-slot">
            <template v-if="itemInCluster(c, slot)">
              <MaterialPreview
                v-if="itemInCluster(c, slot).localUrl"
                :url="itemInCluster(c, slot).localUrl"
                :kind="isPdfName(itemInCluster(c, slot).original_name) ? 'pdf' : 'image'"
                mode="compact"
                :title="itemInCluster(c, slot).original_name"
              />
              <div class="cluster-slot-row">
                <span class="cluster-file" :title="itemInCluster(c, slot).original_name">
                  {{ itemInCluster(c, slot).original_name }}
                </span>
                <span class="meta cluster-slot-type">{{ TYPE_LABELS[slot] }}</span>
                <select :value="itemInCluster(c, slot).type" @change="onItemType(itemInCluster(c, slot), $event)">
                  <option value="invoice">发票</option>
                  <option value="order">订单截图</option>
                  <option value="payment">支付记录</option>
                  <option value="unknown">未分类</option>
                </select>
              </div>
            </template>
            <template v-else>
              <div class="cluster-slot-row">
                <span class="empty">空</span>
                <span class="meta cluster-slot-type">{{ TYPE_LABELS[slot] }}</span>
              </div>
            </template>
          </div>
        </div>
      </section>
    </div>

    <div v-if="unmatchedItems.length" class="unmatched-block">
      <h4 class="cluster-section-title">未匹配（{{ unmatchedItems.length }}）</h4>
      <table class="table">
        <thead>
          <tr>
            <th>预览</th>
            <th>文件名</th>
            <th>类型</th>
            <th>金额</th>
            <th>归属</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in unmatchedItems" :key="item.temp_id">
            <td>
              <MaterialPreview
                v-if="item.localUrl"
                :url="item.localUrl"
                :kind="isPdfName(item.original_name) ? 'pdf' : 'image'"
                mode="compact"
                :title="item.original_name"
              />
              <span v-else class="meta">—</span>
            </td>
            <td>
              <div>{{ item.original_name }}</div>
              <div v-if="item.features?.text_preview" class="meta entry-note">{{ item.features.text_preview }}</div>
            </td>
            <td>
              <select v-model="item.type">
                <option value="invoice">发票</option>
                <option value="order">订单截图</option>
                <option value="payment">支付记录</option>
                <option value="unknown">未分类</option>
              </select>
            </td>
            <td class="meta">{{ item.features?.amount != null ? `¥${Number(item.features.amount).toFixed(2)}` : '—' }}</td>
            <td class="batch-assign">
              <select v-model="item.assignMode">
                <option value="inbox">先放收件箱</option>
                <option value="existing">挂到已有条目</option>
                <option value="new">新建条目</option>
                <option v-for="c in clusters" :key="c.cluster_id" :value="`cluster:${c.cluster_id}`">
                  并入：{{ c.title }}
                </option>
              </select>
              <select v-if="item.assignMode === 'existing'" v-model.number="item.entry_id">
                <option :value="null" disabled>选择条目</option>
                <option v-for="e in entries" :key="e.id" :value="e.id">{{ e.title }}</option>
              </select>
              <input
                v-if="item.assignMode === 'new'"
                v-model="item.create_entry_title"
                placeholder="新条目名称"
              />
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-if="items.length" class="actions batch-upload-actions">
      <button class="btn btn-primary" :disabled="confirming" @click="confirm">
        {{ confirming ? '入库中…' : '确认入库' }}
      </button>
      <button class="btn" type="button" :disabled="confirming" @click="recluster">重新归组</button>
      <button class="btn" type="button" @click="clear">清空</button>
    </div>

    <InvoiceDupCompare
      :open="!!compare"
      :invoice-number="compare?.invoiceNumber || ''"
      :left-label="compare?.leftLabel || '本次上传'"
      :left-url="compare?.leftUrl || ''"
      :left-kind="compare?.leftKind || 'pdf'"
      :left-title="compare?.leftTitle || ''"
      :right-label="compare?.rightLabel || '对照发票'"
      :right-url="compare?.rightUrl || ''"
      :right-kind="compare?.rightKind || 'pdf'"
      :right-title="compare?.rightTitle || ''"
      @close="compare = null"
    />
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { TYPE_LABELS, api, missingLabel } from '../api/client'
import { useConfirmDialog } from '../composables/useConfirmDialog'
import InvoiceDupCompare from './InvoiceDupCompare.vue'
import MaterialPreview from './MaterialPreview.vue'

const emit = defineEmits(['done'])
const { askConfirm } = useConfirmDialog()

const fileInput = ref(null)
const dragging = ref(false)
const items = ref([])
const clusters = ref([])
const unmatchedIds = ref([])
const entries = ref([])
const error = ref('')
const msg = ref('')
const confirming = ref(false)
const ocrAvailable = ref(null)
const compare = ref(null)

const slotTypes = ['invoice', 'order', 'payment']

function isPdfName(name) {
  return /\.pdf$/i.test(name || '')
}

function previewKindFromNameMime(name, mime) {
  if (isPdfName(name) || (mime || '').includes('pdf')) return 'pdf'
  return 'image'
}

function formatDupWarn(w) {
  if (!w) return ''
  const no = w.invoice_number ? `（发票号码 ${w.invoice_number}）` : ''
  if (w.reason === 'same_batch_number') {
    return `与本批另一文件发票号码相同${no}；可对比后删除其一`
  }
  if (w.reason === 'file_hash') {
    return `与本批另一文件内容相同（疑似重复文件）${no}；可对比后删除其一`
  }
  const title = w.existing_entry_title || (w.existing_entry_id != null ? `#${w.existing_entry_id}` : '已有材料')
  return `可能与已有条目「${title}」重复${no}；可对比、删除已有条目，或放弃本次`
}

function invoiceItemInCluster(cluster) {
  return itemInCluster(cluster, 'invoice')
}

function openCompare(cluster) {
  const w = cluster.duplicate_warning
  const inv = invoiceItemInCluster(cluster)
  if (!w || !inv?.localUrl) {
    error.value = '无法打开对比：缺少本次发票预览'
    return
  }
  const left = {
    leftLabel: '本次上传',
    leftUrl: inv.localUrl,
    leftKind: previewKindFromNameMime(inv.original_name, inv.mime),
    leftTitle: inv.original_name,
  }
  if (w.existing_material_id != null) {
    compare.value = {
      invoiceNumber: w.invoice_number || '',
      ...left,
      rightLabel: w.existing_entry_title ? `已有：${w.existing_entry_title}` : '已有发票',
      rightUrl: api.materialFileUrl(w.existing_material_id),
      rightKind: previewKindFromNameMime(w.existing_original_name, w.existing_mime),
      rightTitle: w.existing_original_name || `材料 #${w.existing_material_id}`,
    }
    return
  }
  if (w.peer_temp_id) {
    const peer = items.value.find((it) => it.temp_id === w.peer_temp_id)
    if (!peer?.localUrl) {
      error.value = '无法打开对比：对照文件预览不可用'
      return
    }
    compare.value = {
      invoiceNumber: w.invoice_number || '',
      ...left,
      rightLabel: '本批另一文件',
      rightUrl: peer.localUrl,
      rightKind: previewKindFromNameMime(peer.original_name, peer.mime),
      rightTitle: peer.original_name,
    }
    return
  }
  error.value = '没有可对照的已有发票'
}

async function deleteExistingEntry(cluster) {
  const w = cluster.duplicate_warning
  const entryId = w?.existing_entry_id
  if (entryId == null) return
  const title = w.existing_entry_title || `#${entryId}`
  const ok = await askConfirm({
    title: '删除已有条目',
    message: `确定删除已有条目「${title}」及其全部材料？删除后本拟建条目可正常入库。`,
    confirmText: '删除已有条目',
    cancelText: '取消',
    danger: true,
  })
  if (!ok) return
  error.value = ''
  try {
    await api.deleteEntry(entryId)
    await loadEntries()
    await recluster()
    msg.value = `已删除条目「${title}」`
  } catch (e) {
    error.value = e.message
  }
}

async function discardCluster(cluster) {
  const tids = [...(cluster.temp_ids || [])]
  if (!tids.length) return
  const ok = await askConfirm({
    title: '放弃本拟建条目',
    message: `将从本批移除「${cluster.title}」中的 ${tids.length} 个文件，不会写入库。`,
    confirmText: '放弃',
    cancelText: '取消',
    danger: true,
  })
  if (!ok) return
  error.value = ''
  try {
    const res = await api.classifyDiscard(tids)
    applyPreview(res, [])
    msg.value = '已放弃该拟建条目'
  } catch (e) {
    error.value = e.message
  }
}

const unmatchedItems = computed(() => {
  const set = new Set(unmatchedIds.value)
  return items.value.filter((it) => set.has(it.temp_id) || !it.proposed_cluster_id)
})

const ocrHint = computed(() => {
  if (ocrAvailable.value === false) return '未检测到 OCR 模型（vendor/ocr），图片将仅靠文件名/尺寸猜测'
  if (ocrAvailable.value === true) return 'OCR 已启用'
  return ''
})

function itemInCluster(cluster, type) {
  const tid = Object.entries(cluster.types || {}).find(([, t]) => t === type)?.[0]
  if (!tid) return null
  return items.value.find((it) => it.temp_id === tid) || null
}

function onItemType(item, ev) {
  if (!item) return
  item.type = ev.target.value
  for (const c of clusters.value) {
    if (c.types?.[item.temp_id]) c.types[item.temp_id] = item.type
  }
}

function onClusterAmount(c, ev) {
  const raw = ev.target.value
  c.amount = raw === '' ? null : Number(raw)
}

async function loadEntries() {
  entries.value = await api.listEntries()
}

function applyPreview(res, fileList) {
  ocrAvailable.value = !!res.ocr_available
  const byName = new Map()
  for (const f of fileList || []) {
    if (!byName.has(f.name)) byName.set(f.name, [])
    byName.get(f.name).push(f)
  }
  const prevById = new Map(items.value.map((x) => [x.temp_id, x]))
  const mapped = (res.items || []).map((it) => {
    const prev = prevById.get(it.temp_id)
    const queue = byName.get(it.original_name) || []
    const file = queue.shift()
    let localUrl = prev?.localUrl || null
    if (!localUrl && file) {
      localUrl = URL.createObjectURL(file)
    }
    return {
      ...it,
      type: prev?.type && prev.type !== 'unknown' ? prev.type : it.suggested_type,
      assignMode: prev?.assignMode || 'inbox',
      entry_id: prev?.entry_id ?? null,
      create_entry_title: prev?.create_entry_title || '',
      localUrl,
      features: it.features || {},
      proposed_cluster_id: it.proposed_cluster_id || null,
    }
  })
  // Drop staging files no longer in snapshot; revoke orphaned previews
  const keep = new Set(mapped.map((m) => m.temp_id))
  for (const prev of items.value) {
    if (!keep.has(prev.temp_id) && prev.localUrl) URL.revokeObjectURL(prev.localUrl)
  }
  items.value = mapped
  clusters.value = (res.clusters || []).map((c) => ({
    ...c,
    types: { ...(c.types || {}) },
    temp_ids: [...(c.temp_ids || [])],
  }))
  unmatchedIds.value = [...(res.unmatched_temp_ids || [])]
  for (const it of items.value) it.proposed_cluster_id = null
  for (const c of clusters.value) {
    for (const [tid, t] of Object.entries(c.types || {})) {
      const it = items.value.find((x) => x.temp_id === tid)
      if (it) {
        it.type = t
        it.proposed_cluster_id = c.cluster_id
      }
    }
  }
}

async function handleFiles(fileList) {
  const files = [...fileList]
  if (!files.length) return
  error.value = ''
  msg.value = ''
  try {
    const res = await api.classifyPreview(files)
    applyPreview(res, files)
  } catch (e) {
    error.value = e.message
  }
}

function onPick(ev) {
  handleFiles(ev.target.files || [])
  ev.target.value = ''
}

function onDrop(ev) {
  dragging.value = false
  handleFiles(ev.dataTransfer.files || [])
}

function clear() {
  for (const it of items.value) {
    if (it.localUrl) URL.revokeObjectURL(it.localUrl)
  }
  items.value = []
  clusters.value = []
  unmatchedIds.value = []
  msg.value = ''
  error.value = ''
}

async function recluster() {
  error.value = ''
  try {
    const res = await api.classifyRecluster(items.value.map((i) => i.temp_id))
    // keep localUrl/type edits where possible
    const locals = new Map(items.value.map((i) => [i.temp_id, i]))
    applyPreview(res, [])
    for (const it of items.value) {
      const prev = locals.get(it.temp_id)
      if (prev?.localUrl) it.localUrl = prev.localUrl
    }
  } catch (e) {
    error.value = e.message
  }
}

async function confirm() {
  error.value = ''
  msg.value = ''

  const used = new Set()
  const clusterPayload = []
  for (const c of clusters.value) {
    const materials = []
    for (const tid of c.temp_ids) {
      const it = items.value.find((x) => x.temp_id === tid)
      if (!it) continue
      if (it.type === 'unknown') {
        error.value = `拟建条目「${c.title}」中有未分类文件`
        return
      }
      materials.push({ temp_id: tid, type: it.type })
      used.add(tid)
    }
    // absorb unmatched assigned to this cluster
    for (const it of unmatchedItems.value) {
      if (it.assignMode === `cluster:${c.cluster_id}`) {
        if (it.type === 'unknown') {
          error.value = `请为「${it.original_name}」选择类型`
          return
        }
        materials.push({ temp_id: it.temp_id, type: it.type })
        used.add(it.temp_id)
      }
    }
    if (!materials.length) continue
    if (!c.title?.trim()) {
      error.value = '拟建条目标题不能为空'
      return
    }
    clusterPayload.push({
      title: c.title.trim(),
      amount: c.amount == null || Number.isNaN(Number(c.amount)) ? null : Number(c.amount),
      materials,
    })
  }

  const loose = []
  for (const it of items.value) {
    if (used.has(it.temp_id)) continue
    if (String(it.assignMode || '').startsWith('cluster:')) continue
    if (it.type === 'unknown') {
      error.value = `请为「${it.original_name}」选择类型`
      return
    }
    if (it.assignMode === 'existing' && !it.entry_id) {
      error.value = `请为「${it.original_name}」选择条目`
      return
    }
    if (it.assignMode === 'new' && !it.create_entry_title?.trim()) {
      error.value = `请为「${it.original_name}」填写新条目名称`
      return
    }
    loose.push({
      temp_id: it.temp_id,
      type: it.type,
      entry_id: it.assignMode === 'existing' ? it.entry_id : null,
      create_entry_title: it.assignMode === 'new' ? it.create_entry_title.trim() : null,
    })
  }

  if (!clusterPayload.length && !loose.length) {
    error.value = '没有可入库的文件'
    return
  }

  confirming.value = true
  try {
    await api.classifyConfirm({ clusters: clusterPayload, items: loose })
    msg.value = `已入库：${clusterPayload.length} 个条目，${loose.length} 个散件`
    clear()
    await loadEntries()
    emit('done')
  } catch (e) {
    error.value = e.message
  } finally {
    confirming.value = false
  }
}

onMounted(loadEntries)
onUnmounted(clear)

defineExpose({ clear })
</script>
