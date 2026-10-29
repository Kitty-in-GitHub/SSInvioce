<template>
  <div class="batch-upload-panel">
    <header class="batch-toolbar">
      <p v-if="error" ref="confirmErrorEl" class="error batch-confirm-error">{{ error }}</p>
      <div class="batch-toolbar-row">
        <div class="batch-toolbar-head">
          <h3 id="batch-upload-title" class="batch-toolbar-title">整理</h3>
          <p class="batch-toolbar-sub">把收件箱里的材料归成条目</p>
        </div>
        <div class="batch-toolbar-stats">
          <span class="batch-stat">拟建 <b>{{ clusters.length }}</b></span>
          <span class="batch-stat">未匹配 <b>{{ unmatchedItems.length }}</b></span>
          <span v-if="duplicateItems.length" class="batch-stat batch-stat-warn">
            副本 <b>{{ duplicateItems.length }}</b>
          </span>
          <button
            class="link-btn batch-regroup-btn"
            type="button"
            :disabled="confirming || analyzing"
            title="按材料当前类型重新计算归组（会重置未保存的标题/金额/归属）"
            @click="recluster"
          >
            重新归组
          </button>
        </div>
        <div class="batch-upload-action-btns">
          <button
            class="btn"
            type="button"
            :disabled="confirming || analyzing || !duplicateUploadCount"
            :title="duplicateUploadCount ? '把所有判定为重复的拟建条目和副本移入回收站' : '没有重复上传'"
            @click="discardAllDuplicates"
          >
            丢弃重复{{ duplicateUploadCount ? `（${duplicateUploadCount}）` : '' }}
          </button>
          <button
            class="btn btn-primary"
            :disabled="confirming || analyzing || !items.length"
            @click="confirm"
          >
            {{ confirming ? '入库中…' : '确认入库' }}
          </button>
          <button
            class="btn-ghost batch-close-btn"
            type="button"
            :disabled="analyzing || confirming"
            title="关闭（未入库的材料会留在收件箱）"
            aria-label="关闭"
            @click="emit('request-close')"
          >
            <svg class="batch-close-icon" viewBox="0 0 16 16" aria-hidden="true">
              <path d="M4 4l8 8M12 4l-8 8" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" />
            </svg>
          </button>
        </div>
      </div>
    </header>

    <div class="batch-upload-scroll">
      <p v-if="ocrHint" class="meta">{{ ocrHint }}</p>
      <p v-if="msg" class="okmsg">{{ msg }}</p>

      <div v-if="analyzing" class="batch-loading" role="status" aria-live="polite">
        <span class="batch-loading-spinner" aria-hidden="true" />
        <div>
          <strong>正在重新归组…</strong>
          <p class="meta batch-loading-hint">请稍候</p>
        </div>
      </div>

      <div v-if="!analyzing && !items.length" class="card empty batch-empty">
        收件箱里还没有未归类材料。到「收件箱」点「上传」快速入库，或在条目里上传材料。
      </div>

    <div v-if="clusters.length" class="cluster-list">
      <div class="section-head">
        <h4 class="cluster-section-title">拟建条目</h4>
        <span class="section-count">{{ clusters.length }}</span>
      </div>
      <section v-for="c in clusters" :key="c.cluster_id" class="cluster-card card">
        <header class="cluster-card-head">
          <div class="cluster-title-amount">
            <input
              v-model="c.title"
              class="cluster-title-input"
              placeholder="项目名"
              :disabled="!!c.entry_id"
            />
            <label class="cluster-merge-field">
              <span class="cluster-merge-label">归属</span>
              <select
                class="cluster-merge-select"
                :value="c.entry_id ? String(c.entry_id) : ''"
                :title="c.entry_id ? '并入已有条目' : '新建条目，或并入一个未齐套的条目'"
                @change="onClusterTarget(c, $event)"
              >
                <option value="">新建条目</option>
                <option
                  v-for="e in entryCandidatesForCluster(c)"
                  :key="'merge-' + e.id"
                  :value="String(e.id)"
                >
                  并入：{{ e.title }}（缺 {{ entryMissingText(e) }}）
                </option>
              </select>
            </label>
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
          <span v-if="!clusterHasMaterials(c)" class="chip chip-draft">拟建</span>
          <span v-else-if="c.complete" class="chip chip-ok">齐套</span>
          <button
            type="button"
            class="btn btn-sm cluster-discard-btn"
            :disabled="analyzing || confirming"
            title="丢弃本簇（移入回收站，可恢复）"
            aria-label="丢弃本簇"
            @click="discardCluster(c)"
          >
            <svg class="cluster-discard-icon" viewBox="0 0 16 16" aria-hidden="true">
              <path
                d="M3 5h10M6.5 5V3.5h3V5M5 5l.6 8h4.8L11 5M6.8 7.5v3.5M9.2 7.5v3.5"
                fill="none"
                stroke="currentColor"
                stroke-width="1.3"
                stroke-linecap="round"
                stroke-linejoin="round"
              />
            </svg>
          </button>
        </header>
        <div v-if="c.dupKeepBoth" class="dup-ok">将一并添加</div>
        <div v-else-if="c.duplicate_warning" class="dup-warn">
          <p>{{ formatDupWarn(c.duplicate_warning) }}</p>
          <div class="dup-warn-actions">
            <button type="button" class="btn btn-sm" @click="openCompare(c)">对比</button>
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
                <button
                  type="button"
                  class="cluster-slot-remove"
                  title="移入回收站（可恢复）"
                  :disabled="analyzing || confirming"
                  @click.stop="discardItem(itemInCluster(c, slot))"
                >
                  ×
                </button>
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
      <div class="section-head">
        <h4 class="cluster-section-title">未匹配</h4>
        <span class="section-count">{{ unmatchedItems.length }}</span>
      </div>
      <div class="unmatched-list">
        <div
          v-for="item in unmatchedItems"
          :key="item.temp_id"
          class="unmatched-row"
          :class="{ 'unmatched-row-warn': problemTempIds.has(item.temp_id) }"
          :data-temp-id="item.temp_id"
        >
          <div class="unmatched-preview">
            <MaterialPreview
              v-if="itemPreviewUrl(item)"
              :url="itemPreviewUrl(item)"
              :kind="isPdfName(item.original_name) ? 'pdf' : 'image'"
              mode="compact"
              :title="item.original_name"
            />
            <span v-else class="meta">—</span>
          </div>
          <div class="unmatched-name">
            <div class="unmatched-filename">{{ item.original_name }}</div>
            <div v-if="item.features?.text_preview" class="meta entry-note">{{ item.features.text_preview }}</div>
          </div>
          <select v-model="item.type" class="unmatched-control">
            <option v-for="s in slotDefs" :key="'u-'+s.id" :value="s.id">{{ s.label }}</option>
            <option value="unknown">未分类</option>
          </select>
          <span class="unmatched-amount meta">
            {{ item.features?.amount != null ? `¥${Number(item.features.amount).toFixed(2)}` : '—' }}
          </span>
          <div class="batch-assign">
            <select
              v-model="item.assignMode"
              class="unmatched-control"
              @change="onAssignModeChange(item)"
            >
              <option value="inbox">放收件箱</option>
              <option value="existing">挂到条目</option>
              <option value="new">新建条目</option>
              <option v-for="c in clusters" :key="c.cluster_id" :value="`cluster:${c.cluster_id}`">
                并入：{{ c.title }}
              </option>
            </select>
            <select
              v-if="item.assignMode === 'existing'"
              v-model.number="item.entry_id"
              class="unmatched-control"
            >
              <option :value="null" disabled>选择条目</option>
              <option v-for="e in entries" :key="e.id" :value="e.id">{{ e.title }}</option>
            </select>
            <input
              v-if="item.assignMode === 'new'"
              v-model="item.create_entry_title"
              class="unmatched-control unmatched-title-input"
              placeholder="新条目名称"
            />
          </div>
        </div>
      </div>
    </div>

    <div v-if="duplicateItems.length" class="duplicate-block">
      <div class="section-head">
        <h4 class="cluster-section-title">重复副本</h4>
        <span class="section-count section-count-warn">{{ duplicateItems.length }}</span>
      </div>
      <div class="card duplicate-card">
        <p class="meta">与收件箱中另一文件相同，已折叠</p>
        <label class="duplicate-toggle">
          <input v-model="discardDuplicates" type="checkbox" />
          入库时移入回收站
        </label>
        <ul class="duplicate-list">
          <li v-for="it in duplicateItems" :key="it.temp_id" class="duplicate-item">
            <span class="duplicate-name" :title="it.original_name">{{ it.original_name }}</span>
            <span class="meta">同「{{ duplicateOfName(it) }}」</span>
            <button
              class="btn btn-sm"
              type="button"
              :disabled="analyzing || confirming"
              @click="discardItem(it)"
            >
              移除
            </button>
          </li>
        </ul>
      </div>
    </div>

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
              <a class="link-btn" :href="pdfPreviewSrc(slotPreview.url)" target="_blank" rel="noopener">新窗口打开</a>
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
              :src="pdfPreviewSrc(slotPreview.url)"
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
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { api, pdfEmbedSrc } from '../api/client'
import { useSlots } from '../composables/useSlots'
import { useConfirmDialog } from '../composables/useConfirmDialog'
import InvoiceDupCompare from './InvoiceDupCompare.vue'
import MaterialPreview from './MaterialPreview.vue'

const emit = defineEmits(['done', 'busy-change', 'request-close'])
const { askConfirm } = useConfirmDialog()

const confirmErrorEl = ref(null)
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
const problemTempIds = ref(new Set())
/** invoice_number / peer keys the user chose to keep both */
const keepBothKeys = ref(new Set())
const discardDuplicates = ref(true)

const { slots: slotDefs, slotLabels, invoiceId } = useSlots()
const slotTypes = computed(() => (slotDefs.value.length ? slotDefs.value.map((s) => s.id) : ['invoice', 'order', 'payment']))
const TYPE_LABELS = computed(() => ({ unknown: '未分类', ...slotLabels.value }))

function isPdfName(name) {
  return /\.pdf$/i.test(name || '')
}

function pdfPreviewSrc(url) {
  return slotPreview.value?.kind === 'pdf' ? pdfEmbedSrc(url) : url
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
  const title = w.existing_entry_title || (w.existing_entry_id != null ? `#${w.existing_entry_id}` : '已有材料')
  if (w.reason === 'same_batch_number') return '同批发票号重复，请选择保留哪份'
  if (w.reason === 'file_hash') return '同批文件内容重复，请选择保留哪份'
  if (w.reason === 'existing_file_hash') {
    const kind = TYPE_LABELS.value[w.existing_type] || '材料'
    return `与「${title}」的${kind}是同一文件`
  }
  return `与「${title}」的发票号重复`
}

/** 对比时优先用发票；没有发票的簇（订单+支付）用簇里第一个文件 */
function representativeItem(cluster) {
  return (
    itemInCluster(cluster, invoiceId.value)
    || (cluster.temp_ids || [])
      .map((tid) => items.value.find((it) => it.temp_id === tid))
      .find(Boolean)
    || null
  )
}

function itemPreviewUrl(item) {
  if (!item) return ''
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
  const inv = representativeItem(cluster)
  const leftUrl = itemPreviewUrl(inv)
  if (!w || !leftUrl) {
    error.value = '无法对比：缺少预览'
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
  applyPreview(res)
  if (okMessage) msg.value = okMessage
}

async function discardItem(item) {
  if (!item) return
  const ok = await askConfirm({
    title: '丢弃文件',
    message: `将「${item.original_name}」移入回收站（可恢复）。`,
    confirmText: '丢弃',
    cancelText: '取消',
    danger: true,
  })
  if (!ok) return
  try {
    await discardTempIds([item.temp_id], '已移入回收站')
  } catch (e) {
    error.value = e.message
  }
}

async function discardCluster(cluster) {
  const ids = [...(cluster.temp_ids || [])]
  if (!ids.length) return
  const ok = await askConfirm({
    title: '丢弃拟建条目',
    message: `将「${cluster.title || '未命名'}」的 ${ids.length} 个文件移入回收站（可恢复）。`,
    confirmText: '丢弃',
    cancelText: '取消',
    danger: true,
  })
  if (!ok) return
  try {
    await discardTempIds(ids, '已移入回收站')
  } catch (e) {
    error.value = e.message
  }
}

async function discardAllDuplicates() {
  const ids = duplicateUploadIds.value
  if (!ids.length) return
  const parts = []
  const clusterFiles = duplicateClusters.value.reduce((n, c) => n + (c.temp_ids?.length || 0), 0)
  if (duplicateClusters.value.length) {
    parts.push(`${duplicateClusters.value.length} 个重复拟建条目（共 ${clusterFiles} 个文件）`)
  }
  if (duplicateItems.value.length) {
    parts.push(`${duplicateItems.value.length} 个重复副本`)
  }
  const ok = await askConfirm({
    title: '丢弃重复上传',
    message: `将${parts.join('、')}移入回收站（可恢复）。`,
    confirmText: '全部丢弃',
    cancelText: '取消',
    danger: true,
  })
  if (!ok) return
  try {
    await discardTempIds(ids, `已丢弃 ${ids.length} 个重复文件`)
  } catch (e) {
    error.value = e.message
  }
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
      const inv = representativeItem(cluster)
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
  return items.value.filter((it) => !it.duplicate_of && (set.has(it.temp_id) || !it.proposed_cluster_id))
})

const duplicateItems = computed(() => items.value.filter((it) => it.duplicate_of))

const duplicateClusters = computed(() => clusters.value.filter((c) => c.duplicate_warning))

const duplicateUploadIds = computed(() => {
  const ids = new Set()
  for (const c of duplicateClusters.value) {
    for (const tid of c.temp_ids || []) ids.add(tid)
  }
  for (const it of duplicateItems.value) ids.add(it.temp_id)
  return [...ids]
})

const duplicateUploadCount = computed(() => duplicateUploadIds.value.length)

function duplicateOfName(item) {
  const rep = items.value.find((x) => x.temp_id === item.duplicate_of)
  return rep?.original_name || `#${item.duplicate_of}`
}

const ocrHint = computed(() =>
  ocrAvailable.value === false ? '未检测到 OCR 模型，图片仅按文件名识别' : '',
)

function clusterHasMaterials(cluster) {
  if ((cluster.temp_ids || []).length) return true
  return unmatchedItems.value.some((it) => it.assignMode === `cluster:${cluster.cluster_id}`)
}

const incompleteEntries = computed(() =>
  (entries.value || []).filter((e) => !e?.completeness?.complete),
)

function entryMissingText(e) {
  return (e?.completeness?.missing || [])
    .map((id) => slotLabels.value[id] || TYPE_LABELS.value[id] || id)
    .join('、')
}

/** 缺这个簇里的某个槽、且没有同槽材料冲突的条目，才适合"并入" */
function entryCandidatesForCluster(c) {
  const types = new Set(Object.values(c.types || {}))
  if (!types.size) return []
  return incompleteEntries.value.filter((e) => {
    const missing = e?.completeness?.missing || []
    const conflict = (e?.materials || []).some((m) => types.has(m.type))
    return !conflict && missing.some((m) => types.has(m))
  })
}

function onClusterTarget(c, ev) {
  const raw = ev.target.value
  c.entry_id = raw ? Number(raw) : null
  error.value = ''
}

function autoAmountFromItem(item) {
  const n = Number(item?.features?.amount)
  return Number.isFinite(n) ? n : null
}

function applyAutoAmountToCluster(cluster, item) {
  const amt = autoAmountFromItem(item)
  if (amt == null) return
  cluster.amount = amt
}

function itemInCluster(cluster, type) {
  const tid = Object.entries(cluster.types || {}).find(([, t]) => t === type)?.[0]
  if (!tid) return null
  return items.value.find((it) => it.temp_id === tid) || null
}

async function onItemType(item, ev) {
  if (!item) return
  item.type = ev.target.value
  for (const c of clusters.value) {
    if (c.types?.[item.temp_id]) c.types[item.temp_id] = item.type
  }
  // 类型改动立即落到材料上，关掉窗口再打开也不会丢
  try {
    await api.updateMaterial(Number(item.temp_id), { type: item.type })
  } catch (e) {
    error.value = e.message
  }
}

function onClusterAmount(c, ev) {
  const raw = ev.target.value
  c.amount = raw === '' ? null : Number(raw)
}

async function loadEntries() {
  entries.value = await api.listEntries()
}

function applyPreview(res) {
  ocrAvailable.value = !!res.ocr_available
  const prevById = new Map(items.value.map((x) => [x.temp_id, x]))
  const mapped = (res.items || []).map((it) => {
    const prev = prevById.get(it.temp_id)
    return {
      ...it,
      type: prev?.type && prev.type !== 'unknown' ? prev.type : it.suggested_type,
      assignMode: prev?.assignMode || 'inbox',
      entry_id: prev?.entry_id ?? null,
      create_entry_title: prev?.create_entry_title || '',
      features: it.features || {},
      proposed_cluster_id: it.proposed_cluster_id || null,
    }
  })
  items.value = mapped
  clusters.value = (res.clusters || []).map((c) => {
    const base = {
      ...c,
      types: { ...(c.types || {}) },
      temp_ids: [...(c.temp_ids || [])],
      entry_id: null,
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

function clear({ force = false } = {}) {
  if (!force && (analyzing.value || confirming.value)) return
  items.value = []
  clusters.value = []
  unmatchedIds.value = []
  keepBothKeys.value = new Set()
  problemTempIds.value = new Set()
  discardDuplicates.value = true
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
    applyPreview(res)
  } catch (e) {
    error.value = e.message
  } finally {
    analyzing.value = false
  }
}

function titleFromFilename(name) {
  const base = String(name || '').trim()
  if (!base) return ''
  return base.replace(/\.[^.]+$/, '') || base
}

function onAssignModeChange(item) {
  if (!item) return
  if (item.assignMode === 'new' && !String(item.create_entry_title || '').trim()) {
    item.create_entry_title = titleFromFilename(item.original_name)
  }
  problemTempIds.value = new Set()
  const mode = String(item.assignMode || '')
  if (mode.startsWith('cluster:')) {
    const cid = mode.slice('cluster:'.length)
    const cluster = clusters.value.find((c) => String(c.cluster_id) === cid)
    if (cluster) applyAutoAmountToCluster(cluster, item)
  }
}

function failConfirm(message, tempId = null) {
  error.value = message
  problemTempIds.value = tempId ? new Set([tempId]) : new Set()
  nextTick(() => {
    confirmErrorEl.value?.scrollIntoView?.({ behavior: 'smooth', block: 'nearest' })
    if (tempId) {
      const row = [...document.querySelectorAll('.unmatched-row')].find(
        (el) => el.getAttribute('data-temp-id') === tempId,
      )
      row?.scrollIntoView?.({ behavior: 'smooth', block: 'nearest' })
    }
  })
}

async function confirm() {
  error.value = ''
  msg.value = ''
  problemTempIds.value = new Set()

  const used = new Set()
  const clusterPayload = []
  for (const c of clusters.value) {
    const materials = []
    for (const tid of c.temp_ids) {
      const it = items.value.find((x) => x.temp_id === tid)
      if (!it) continue
      if (it.type === 'unknown') {
        failConfirm(`「${c.title}」有未分类文件，请先选类型`, tid)
        return
      }
      materials.push({ temp_id: tid, type: it.type })
      used.add(tid)
    }
    // absorb unmatched assigned to this cluster
    for (const it of unmatchedItems.value) {
      if (it.assignMode === `cluster:${c.cluster_id}`) {
        if (it.type === 'unknown') {
          failConfirm(`请为「${it.original_name}」选择类型`, it.temp_id)
          return
        }
        materials.push({ temp_id: it.temp_id, type: it.type })
        used.add(it.temp_id)
      }
    }
    if (!materials.length) continue
    const targetId = c.entry_id ? Number(c.entry_id) : null
    if (!targetId && !c.title?.trim()) {
      failConfirm('拟建条目标题不能为空')
      return
    }
    clusterPayload.push({
      title: (c.title || '').trim(),
      amount: c.amount == null || Number.isNaN(Number(c.amount)) ? null : Number(c.amount),
      entry_id: targetId,
      materials,
    })
  }

  const loose = []
  for (const it of items.value) {
    if (it.duplicate_of) continue
    if (used.has(it.temp_id)) continue
    if (String(it.assignMode || '').startsWith('cluster:')) continue
    const mode = it.assignMode || 'inbox'
    // 先放收件箱允许未分类；挂到条目 / 新建条目必须指定类型
    if (it.type === 'unknown' && mode !== 'inbox') {
      failConfirm(`请为「${it.original_name}」选择类型`, it.temp_id)
      return
    }
    if (mode === 'existing' && !it.entry_id) {
      failConfirm('请选择要挂入的条目', it.temp_id)
      return
    }
    if (mode === 'new') {
      if (!it.create_entry_title?.trim()) {
        it.create_entry_title = titleFromFilename(it.original_name)
      }
      if (!it.create_entry_title?.trim()) {
        failConfirm('请填写新条目名称', it.temp_id)
        return
      }
    }
    loose.push({
      temp_id: it.temp_id,
      type: it.type,
      entry_id: mode === 'existing' ? it.entry_id : null,
      create_entry_title: mode === 'new' ? it.create_entry_title.trim() : null,
    })
  }

  if (!clusterPayload.length && !loose.length) {
    failConfirm('没有可入库的文件')
    return
  }

  const dupIds = duplicateItems.value.map((it) => it.temp_id)
  const dropDup = discardDuplicates.value && dupIds.length > 0

  confirming.value = true
  try {
    const res = await api.classifyConfirm({ clusters: clusterPayload, items: loose })
    const created = res?.created_entry_ids?.length ?? clusterPayload.length
    const merged = res?.updated_entry_ids?.length ?? 0
    let dupNote = ''
    if (dropDup) {
      try {
        await api.classifyDiscard(dupIds)
        dupNote = `，${dupIds.length} 个副本已移入回收站`
      } catch (err) {
        dupNote = `，但重复副本移入回收站失败：${err.message}`
      }
    }
    msg.value = `已入库 ${created} 条${merged ? `，并入 ${merged}` : ''}，散件 ${loose.length}${dupNote}`
    clear({ force: true })
    await loadEntries()
    emit('done')
  } catch (e) {
    failConfirm(e.message)
  } finally {
    confirming.value = false
  }
}

async function restoreStaging() {
  // 收件箱里的未归类材料就是"暂存"，打开窗口即接着上次继续
  analyzing.value = true
  try {
    const res = await api.classifyRecluster(null)
    const count = (res?.items || []).length
    applyPreview(res)
    if (count) msg.value = `已载入 ${count} 个未归类材料`
  } catch {
    /* 后端未启动时静默，空状态会提示 */
  } finally {
    analyzing.value = false
  }
}

onMounted(async () => {
  await loadEntries()
  await restoreStaging()
})
onUnmounted(() => clear({ force: true }))

defineExpose({ clear, isBusy, hasOverlay, closeOverlays, closeSlotPreview })
</script>
