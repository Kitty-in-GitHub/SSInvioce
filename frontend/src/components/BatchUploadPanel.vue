<template>
  <div class="batch-upload-panel">
    <div
      class="dropzone"
      :class="{ active: dragging && !analyzing, disabled: analyzing || confirming }"
      @dragover.prevent="onDragOver"
      @dragleave.prevent="dragging = false"
      @drop.prevent="onDrop"
      @click="onDropzoneClick"
    >
      拖拽文件到此处，或点击选择（PDF / JPG / PNG）
      <p class="meta dropzone-hint">将自动 OCR / 读发票文本，按金额等线索归入拟建条目</p>
      <input
        ref="fileInput"
        type="file"
        multiple
        hidden
        accept=".pdf,.jpg,.jpeg,.png,.webp,.bmp,.gif"
        :disabled="analyzing || confirming"
        @change="onPick"
      />
    </div>

    <div v-if="analyzing" class="batch-loading" role="status" aria-live="polite">
      <span class="batch-loading-spinner" aria-hidden="true" />
      <div>
        <strong>正在识别与归组…</strong>
        <p class="meta batch-loading-hint">请稍候，完成前请勿关闭弹窗</p>
      </div>
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
          <span v-if="c.complete" class="chip chip-ok">齐套</span>
        </header>
        <div v-if="c.dupKeepBoth" class="dup-ok">已选择都添加，确认入库时将一并写入</div>
        <div v-else-if="c.duplicate_warning" class="dup-warn">
          <p>{{ formatDupWarn(c.duplicate_warning) }}</p>
          <div class="dup-warn-actions">
            <button type="button" class="btn btn-sm" @click="openCompare(c)">对比查看</button>
          </div>
        </div>
        <div class="cluster-slots">
          <div
            v-for="slot in slotTypes"
            :key="slot"
            class="cluster-slot"
            :class="itemInCluster(c, slot) ? 'cluster-slot-filled cluster-slot-clickable' : 'cluster-slot-missing'"
            :title="itemInCluster(c, slot) ? '点击预览' : `缺少${TYPE_LABELS[slot]}`"
            @click="openSlotPreview(itemInCluster(c, slot))"
          >
            <template v-if="itemInCluster(c, slot)">
              <div class="cluster-slot-row">
                <button
                  type="button"
                  class="cluster-file-btn"
                  :title="itemInCluster(c, slot).original_name"
                  @click.stop="openSlotPreview(itemInCluster(c, slot))"
                >
                  {{ itemInCluster(c, slot).original_name }}
                </button>
                <span class="meta cluster-slot-type">{{ TYPE_LABELS[slot] }}</span>
                <select
                  :value="itemInCluster(c, slot).type"
                  @click.stop
                  @change="onItemType(itemInCluster(c, slot), $event)"
                >
                  <option v-for="s in slotDefs" :key="s.id" :value="s.id">{{ s.label }}</option>
                  <option value="unknown">未分类</option>
                </select>
              </div>
            </template>
            <template v-else>
              <div class="cluster-slot-row">
                <span class="cluster-slot-missing-label">{{ TYPE_LABELS[slot] }}</span>
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
                <option v-for="s in slotDefs" :key="'u-'+s.id" :value="s.id">{{ s.label }}</option>
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
      <button class="btn btn-primary" :disabled="confirming || analyzing" @click="confirm">
        {{ confirming ? '入库中…' : '确认入库' }}
      </button>
      <button class="btn" type="button" :disabled="confirming || analyzing" @click="recluster">重新归组</button>
      <button class="btn" type="button" :disabled="confirming || analyzing" @click="clear">清空</button>
    </div>

    <Teleport to="body">
      <div
        v-if="slotPreview"
        class="modal-backdrop modal-backdrop-preview"
        @click.self="closeSlotPreview"
      >
        <div class="modal-card modal-wide material-preview-modal" role="dialog" aria-modal="true">
          <div class="modal-head">
            <div>
              <h3 class="modal-title">{{ slotPreview.title || '预览' }}</h3>
            </div>
            <div class="material-preview-modal-actions">
              <a class="link-btn" :href="slotPreview.url" target="_blank" rel="noopener">新窗口打开</a>
              <button class="btn-ghost" type="button" @click="closeSlotPreview">关闭</button>
            </div>
          </div>
          <div class="material-preview-modal-body">
            <img
              v-if="slotPreview.kind === 'image'"
              class="material-preview-modal-img"
              :src="slotPreview.url"
              :alt="slotPreview.title"
            />
            <iframe
              v-else
              class="pdf-frame pdf-frame-modal"
              :src="slotPreview.url"
              :title="slotPreview.title || 'PDF 预览'"
            />
          </div>
        </div>
      </div>
    </Teleport>

    <InvoiceDupCompare
      :open="!!compare"
      resolvable
      :busy="compareBusy"
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
      @resolve="onCompareResolve"
    />
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { api } from '../api/client'
import { useSlots } from '../composables/useSlots'
import { useConfirmDialog } from '../composables/useConfirmDialog'
import InvoiceDupCompare from './InvoiceDupCompare.vue'
import MaterialPreview from './MaterialPreview.vue'

const emit = defineEmits(['done', 'busy-change'])
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
const analyzing = ref(false)
const ocrAvailable = ref(null)
const compare = ref(null)
const compareBusy = ref(false)
const slotPreview = ref(null)
/** invoice_number / peer keys the user chose to keep both */
const keepBothKeys = ref(new Set())

const { slots: slotDefs, slotLabels, invoiceId } = useSlots()
const slotTypes = computed(() => (slotDefs.value.length ? slotDefs.value.map((s) => s.id) : ['invoice', 'order', 'payment']))
const TYPE_LABELS = computed(() => ({ unknown: '未分类', ...slotLabels.value }))

function isPdfName(name) {
  return /\.pdf$/i.test(name || '')
}

function previewKindFromNameMime(name, mime) {
  if (isPdfName(name) || (mime || '').includes('pdf')) return 'pdf'
  return 'image'
}

function dupDecisionKey(w) {
  if (!w) return null
  if (w.invoice_number) return `no:${w.invoice_number}`
  if (w.existing_material_id != null) return `mat:${w.existing_material_id}`
  if (w.peer_temp_id) return `peer:${w.peer_temp_id}`
  return null
}

function clusterIsKeepBoth(c) {
  const keys = keepBothKeys.value
  if (!keys.size) return false
  const w = c.duplicate_warning
  if (w) {
    const k = dupDecisionKey(w)
    if (k && keys.has(k)) return true
    if (w.invoice_number && keys.has(`no:${w.invoice_number}`)) return true
    if (w.peer_temp_id && keys.has(`peer:${w.peer_temp_id}`)) return true
  }
  for (const tid of c.temp_ids || []) {
    if (keys.has(`peer:${tid}`)) return true
  }
  return false
}

function formatDupWarn(w) {
  if (!w) return ''
  const no = w.invoice_number ? `（发票号码 ${w.invoice_number}）` : ''
  if (w.reason === 'same_batch_number') {
    return `与本批另一文件发票号码相同${no}；请对比后选择保留哪一份`
  }
  if (w.reason === 'file_hash') {
    return `与本批另一文件内容相同（疑似重复文件）${no}；请对比后选择保留哪一份`
  }
  const title = w.existing_entry_title || (w.existing_entry_id != null ? `#${w.existing_entry_id}` : '已有材料')
  return `可能与已有条目「${title}」重复${no}；请对比后选择保留哪一份或都添加`
}

function invoiceItemInCluster(cluster) {
  return itemInCluster(cluster, invoiceId.value)
}

function itemPreviewUrl(item) {
  if (!item) return ''
  if (item.localUrl) return item.localUrl
  if (item.temp_id) return api.stagingFileUrl(item.temp_id)
  return ''
}

function closeSlotPreview() {
  slotPreview.value = null
}

function closeOverlays() {
  slotPreview.value = null
  compare.value = null
}

function openSlotPreview(item) {
  if (!item) return
  const url = itemPreviewUrl(item)
  if (!url) {
    error.value = '无法预览：文件地址不可用'
    return
  }
  error.value = ''
  slotPreview.value = {
    url,
    kind: previewKindFromNameMime(item.original_name, item.mime),
    title: item.original_name || '预览',
  }
}

function hasOverlay() {
  return !!slotPreview.value || !!compare.value
}

function openCompare(cluster) {
  const w = cluster.duplicate_warning
  const inv = invoiceItemInCluster(cluster)
  const leftUrl = itemPreviewUrl(inv)
  if (!w || !leftUrl) {
    error.value = '无法打开对比：缺少本次发票预览'
    return
  }
  const base = {
    clusterId: cluster.cluster_id,
    warning: w,
    invoiceNumber: w.invoice_number || '',
    leftLabel: '本次上传',
    leftUrl,
    leftKind: previewKindFromNameMime(inv.original_name, inv.mime),
    leftTitle: inv.original_name,
  }
  if (w.existing_material_id != null) {
    compare.value = {
      ...base,
      mode: 'existing',
      rightLabel: w.existing_entry_title ? `已有：${w.existing_entry_title}` : '已有发票',
      rightUrl: api.materialFileUrl(w.existing_material_id),
      rightKind: previewKindFromNameMime(w.existing_original_name, w.existing_mime),
      rightTitle: w.existing_original_name || `材料 #${w.existing_material_id}`,
    }
    return
  }
  if (w.peer_temp_id) {
    const peer = items.value.find((it) => it.temp_id === w.peer_temp_id)
    const rightUrl = itemPreviewUrl(peer)
    if (!rightUrl) {
      error.value = '无法打开对比：对照文件预览不可用'
      return
    }
    compare.value = {
      ...base,
      mode: 'peer',
      rightLabel: '本批另一文件',
      rightUrl,
      rightKind: previewKindFromNameMime(peer.original_name, peer.mime),
      rightTitle: peer.original_name,
    }
    return
  }
  error.value = '没有可对照的已有发票'
}

async function discardTempIds(tempIds, okMessage) {
  const tids = [...tempIds]
  if (!tids.length) return
  const res = await api.classifyDiscard(tids)
  applyPreview(res, [])
  if (okMessage) msg.value = okMessage
}

async function onCompareResolve(decision) {
  const ctx = compare.value
  if (!ctx?.clusterId) return
  const cluster = clusters.value.find((c) => c.cluster_id === ctx.clusterId)
  if (!cluster) {
    compare.value = null
    return
  }
  const w = ctx.warning || cluster.duplicate_warning
  error.value = ''
  compareBusy.value = true
  try {
    if (decision === 'keep_both') {
      const next = new Set(keepBothKeys.value)
      const key = dupDecisionKey(w)
      if (key) next.add(key)
      if (w?.invoice_number) next.add(`no:${w.invoice_number}`)
      if (w?.peer_temp_id) next.add(`peer:${w.peer_temp_id}`)
      const inv = invoiceItemInCluster(cluster)
      if (inv?.temp_id) next.add(`peer:${inv.temp_id}`)
      keepBothKeys.value = next
      for (const c of clusters.value) {
        const ck = dupDecisionKey(c.duplicate_warning)
        if (ck && next.has(ck)) {
          c.duplicate_warning = null
          c.dupKeepBoth = true
        }
      }
      cluster.duplicate_warning = null
      cluster.dupKeepBoth = true
      compare.value = null
      msg.value = '已标记为都添加'
      return
    }

    if (decision === 'keep_left') {
      if (ctx.mode === 'existing') {
        const entryId = w?.existing_entry_id
        if (entryId == null) {
          error.value = '无法删除对照：缺少已有条目'
          return
        }
        const title = w.existing_entry_title || `#${entryId}`
        const ok = await askConfirm({
          title: '保留本次上传',
          message: `将删除已有条目「${title}」及其全部材料，仅保留本次拟建条目。`,
          confirmText: '删除已有并保留本次',
          cancelText: '取消',
          danger: true,
        })
        if (!ok) return
        await api.deleteEntry(entryId)
        await loadEntries()
        compare.value = null
        await recluster()
        msg.value = `已删除已有条目「${title}」，保留本次`
        return
      }
      if (ctx.mode === 'peer' && w?.peer_temp_id) {
        compare.value = null
        await discardTempIds([w.peer_temp_id], '已移除对照文件，保留本次')
        return
      }
      error.value = '无法执行：缺少对照目标'
      return
    }

    if (decision === 'keep_right') {
      const tids = [...(cluster.temp_ids || [])]
      compare.value = null
      await discardTempIds(tids, '已放弃本次拟建条目，保留对照')
    }
  } catch (e) {
    error.value = e.message
  } finally {
    compareBusy.value = false
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
  clusters.value = (res.clusters || []).map((c) => {
    const base = {
      ...c,
      types: { ...(c.types || {}) },
      temp_ids: [...(c.temp_ids || [])],
    }
    const keepBoth = clusterIsKeepBoth(base)
    return {
      ...base,
      duplicate_warning: keepBoth ? null : c.duplicate_warning,
      dupKeepBoth: keepBoth,
    }
  })
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

function onDropzoneClick() {
  if (analyzing.value || confirming.value) return
  fileInput.value?.click()
}

function onDragOver() {
  if (analyzing.value || confirming.value) return
  dragging.value = true
}

async function handleFiles(fileList) {
  const files = [...fileList]
  if (!files.length || analyzing.value || confirming.value) return
  error.value = ''
  msg.value = ''
  analyzing.value = true
  const beforeIds = new Set(items.value.map((i) => i.temp_id))
  try {
    const res = await api.classifyPreview(files)
    applyPreview(res, files)
    // Prefer order of newly staged temp_ids over filename matching (Chinese names etc.)
    const newcomers = (res.items || []).filter((it) => !beforeIds.has(it.temp_id))
    newcomers.forEach((it, idx) => {
      const row = items.value.find((x) => x.temp_id === it.temp_id)
      const file = files[idx]
      if (!row || !file) return
      if (row.localUrl) URL.revokeObjectURL(row.localUrl)
      row.localUrl = URL.createObjectURL(file)
    })
  } catch (e) {
    error.value = e.message
  } finally {
    analyzing.value = false
  }
}

function onPick(ev) {
  handleFiles(ev.target.files || [])
  ev.target.value = ''
}

function onDrop(ev) {
  dragging.value = false
  if (analyzing.value || confirming.value) return
  handleFiles(ev.dataTransfer.files || [])
}

function clear({ force = false } = {}) {
  if (!force && (analyzing.value || confirming.value)) return
  for (const it of items.value) {
    if (it.localUrl) URL.revokeObjectURL(it.localUrl)
  }
  items.value = []
  clusters.value = []
  unmatchedIds.value = []
  keepBothKeys.value = new Set()
  compare.value = null
  slotPreview.value = null
  msg.value = ''
  error.value = ''
}

function isBusy() {
  return analyzing.value || confirming.value || compareBusy.value
}

watch(
  [analyzing, confirming, compareBusy],
  () => emit('busy-change', isBusy()),
  { immediate: true },
)

async function recluster() {
  if (analyzing.value || confirming.value) return
  error.value = ''
  analyzing.value = true
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
  } finally {
    analyzing.value = false
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
    clear({ force: true })
    await loadEntries()
    emit('done')
  } catch (e) {
    error.value = e.message
  } finally {
    confirming.value = false
  }
}

onMounted(loadEntries)
onUnmounted(() => clear({ force: true }))

defineExpose({ clear, isBusy, hasOverlay, closeOverlays, closeSlotPreview })
</script>
