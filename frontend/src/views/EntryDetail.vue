<template>
  <div>
    <div class="page-head">
      <div>
        <router-link class="meta" to="/">← 返回列表</router-link>
        <h1 v-if="entry">{{ entry.title }}</h1>
        <p v-if="entry">
          <span
            v-if="!entry.completeness.complete"
            class="badge badge-warn"
          >
            缺：{{ missingLabel(entry.completeness.missing) }}
          </span>
          <span v-if="entry.note" class="meta">
            <template v-if="!entry.completeness.complete"> · </template>{{ entry.note }}
          </span>
        </p>
      </div>
      <div class="actions">
        <router-link
          v-if="entry?.ledger_txn_id"
          class="btn"
          :to="{ path: '/ledger', query: { txn: entry.ledger_txn_id } }"
        >已入账</router-link>
        <button
          v-else
          class="btn"
          type="button"
          :disabled="!entry || entry.amount == null || Number(entry.amount) <= 0 || posting"
          @click="postToLedger"
        >
          {{ posting ? '入账中…' : '记入账本' }}
        </button>
        <button class="btn btn-primary" :disabled="!entry?.completeness.complete || composing" @click="compose">
          {{ composing ? '拼版中…' : '生成拼版 PDF' }}
        </button>
      </div>
    </div>

    <p v-if="error" class="error">{{ error }}</p>
    <div v-if="dupWarn" class="dup-warn">
      <p>{{ formatDupWarn(dupWarn) }}</p>
      <div class="dup-warn-actions">
        <button type="button" class="btn btn-sm" @click="openDupCompare">对比查看</button>
        <button
          v-if="dupWarn.existing_entry_id != null"
          type="button"
          class="btn btn-danger btn-sm"
          @click="deleteDupEntry"
        >
          删除已有条目
        </button>
        <button
          v-if="invoiceMaterial"
          type="button"
          class="btn btn-sm"
          @click="removeMaterial(invoiceMaterial)"
        >
          删除本条目发票
        </button>
      </div>
    </div>
    <p v-if="msg" class="okmsg">{{ msg }}</p>
    <div v-if="loading" class="meta">加载中…</div>

    <template v-else-if="entry">
      <div class="card spaced">
        <div class="meta-grid">
          <div class="field field-span-2">
            <label>标题</label>
            <input v-model="editTitle" />
          </div>
          <div class="field">
            <label>所属分组</label>
            <select v-model="editGroupId">
              <option :value="null">未分组</option>
              <option v-for="g in groups" :key="g.id" :value="g.id">{{ g.name }}</option>
            </select>
          </div>
          <div class="field field-span-2">
            <label>备注</label>
            <input v-model="editNote" placeholder="可选" />
          </div>
          <div class="field">
            <label>报销金额</label>
            <div class="amount-field-row">
              <div class="amount-edit">
                <span class="amount-prefix" aria-hidden="true">¥</span>
                <input v-model="editAmount" type="number" step="0.01" min="0" placeholder="0.00" />
              </div>
              <span class="amount-tag" :class="entry.amount_source">
                {{ entry.amount_source === 'manual' ? '已手改' : entry.amount_source === 'auto' ? '自动' : '无金额' }}
              </span>
            </div>
          </div>
        </div>
        <div class="meta-actions">
          <button class="btn btn-primary btn-sm" @click="saveMeta">保存信息</button>
          <button class="btn btn-sm" :disabled="reparsing" @click="reparse">
            {{ reparsing ? '识别中…' : '重新识别金额' }}
          </button>
        </div>
      </div>

      <div class="slots">
        <div
          v-for="slot in slots"
          :key="slot.type"
          class="slot"
          :class="{ 'slot-missing': slot.missing }"
        >
          <h4>
            {{ slot.label }}
            <span v-if="slot.material?.processing" class="chip chip-muted">识别中</span>
            <span v-else-if="slot.missing" class="slot-missing-tag">缺失</span>
          </h4>
          <div class="preview">
            <MaterialPreview
              v-if="slot.preview"
              :url="slot.preview.url"
              :kind="previewKind(slot.preview)"
              mode="detail"
              :title="slot.preview.original_name"
              empty-text="无法预览"
            />
            <div v-else class="empty" :class="{ 'empty-missing': slot.missing }">
              {{ slot.missing ? '材料缺失' : '尚未上传' }}
            </div>
          </div>
          <div class="meta" v-if="slot.preview">{{ slot.preview.original_name }}</div>
          <div class="actions">
            <label class="btn btn-sm">
              {{ slotBusy(slot.type) ? '处理中…' : slot.material ? '替换' : '上传' }}
              <input
                type="file"
                hidden
                :accept="slot.accept"
                :disabled="slotBusy(slot.type)"
                @change="onUpload($event, slot.type)"
              />
            </label>
            <button
              v-if="slot.material"
              class="btn btn-danger btn-sm"
              :disabled="slotBusy(slot.type)"
              @click="removeMaterial(slot.material)"
            >
              {{ deletingType === slot.type ? '删除中…' : '删除' }}
            </button>
          </div>
        </div>
      </div>
    </template>

    <InvoiceDupCompare
      :open="!!compare"
      :invoice-number="compare?.invoiceNumber || ''"
      :left-label="compare?.leftLabel || '本条目发票'"
      :left-url="compare?.leftUrl || ''"
      :left-kind="compare?.leftKind || 'pdf'"
      :left-title="compare?.leftTitle || ''"
      :right-label="compare?.rightLabel || '已有发票'"
      :right-url="compare?.rightUrl || ''"
      :right-kind="compare?.rightKind || 'pdf'"
      :right-title="compare?.rightTitle || ''"
      @close="compare = null"
    />
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { api, isImageMaterial, isPdfMaterial } from '../api/client'
import { acceptForKind, missingLabelFromSlots, useSlots } from '../composables/useSlots'
import InvoiceDupCompare from '../components/InvoiceDupCompare.vue'
import MaterialPreview from '../components/MaterialPreview.vue'
import { useConfirmDialog } from '../composables/useConfirmDialog'
import { useAnalyzeJobs } from '../composables/useAnalyzeJobs'

const props = defineProps({ id: { type: [String, Number], required: true } })
const route = useRoute()
const { askConfirm } = useConfirmDialog()
const { kickAnalyzePolling } = useAnalyzeJobs()
const entry = ref(null)
const groups = ref([])
const loading = ref(true)
const error = ref('')
const dupWarn = ref(null)
const msg = ref('')
const composing = ref(false)
const posting = ref(false)
const reparsing = ref(false)
const editTitle = ref('')
const editNote = ref('')
const editAmount = ref('')
const editGroupId = ref(null)
const compare = ref(null)
const uploadingType = ref('')
const deletingType = ref('')
const localPreview = ref(null)
const { slots: slotDefs, slotLabels, invoiceId, requiredIds } = useSlots()

function missingLabel(missing) {
  return missingLabelFromSlots(missing, slotLabels.value)
}

const slots = computed(() => {
  const mats = entry.value?.materials || []
  const pick = (type) => mats.find((m) => m.type === type) || null
  const missingSet = new Set(entry.value?.completeness?.missing || [])
  return (slotDefs.value.length ? slotDefs.value : [
    { id: 'invoice', label: '发票', file_kind: 'pdf' },
    { id: 'order', label: '订单截图', file_kind: 'image' },
    { id: 'payment', label: '支付记录', file_kind: 'image' },
  ]).map((s) => {
    const material = pick(s.id)
    const preview = localPreview.value?.type === s.id ? localPreview.value : material
    return {
      type: s.id,
      label: s.label,
      accept: acceptForKind(s.file_kind),
      material,
      preview,
      missing: !material && !preview && missingSet.has(s.id),
    }
  })
})

const invoiceMaterial = computed(() => slots.value.find((s) => s.type === invoiceId.value)?.material || null)

function previewKind(m) {
  if (isPdfMaterial(m)) return 'pdf'
  if (isImageMaterial(m)) return 'image'
  return 'image'
}

function previewKindFromNameMime(name, mime) {
  if (/\.pdf$/i.test(name || '') || (mime || '').includes('pdf')) return 'pdf'
  return 'image'
}

function slotBusy(type) {
  return uploadingType.value === type || deletingType.value === type
}

function completenessFromMaterials(materials) {
  const types = new Set((materials || []).map((m) => m.type))
  const required = requiredIds.value.length ? requiredIds.value : ['invoice', 'order', 'payment']
  const missing = required.filter((id) => !types.has(id))
  const inv = invoiceId.value
  return {
    complete: missing.length === 0,
    has_invoice: types.has(inv),
    has_order: types.has('order'),
    has_payment: types.has('payment'),
    missing,
  }
}

function syncDupWarn(next = entry.value) {
  const inv = (next?.materials || []).find((m) => m.type === invoiceId.value)
  dupWarn.value = inv?.duplicate_warning || null
}

function applyEntry(next) {
  entry.value = next
  editTitle.value = next.title
  editNote.value = next.note || ''
  editAmount.value = next.amount ?? ''
  editGroupId.value = next.group_id
  syncDupWarn(next)
}

async function load({ silent } = {}) {
  if (!silent) loading.value = true
  error.value = ''
  if (!silent) compare.value = null
  try {
    const [next, groupList] = await Promise.all([api.getEntry(props.id), api.listGroups()])
    applyEntry(next)
    groups.value = groupList
  } catch (e) {
    error.value = e.message
  } finally {
    if (!silent) loading.value = false
  }
}

async function saveMeta() {
  error.value = ''
  msg.value = ''
  try {
    const amountRaw = editAmount.value
    const amount = amountRaw === '' || amountRaw == null ? null : Number(amountRaw)
    if (amountRaw !== '' && amountRaw != null && Number.isNaN(amount)) {
      error.value = '金额格式无效'
      return
    }
    const body = {
      title: editTitle.value,
      note: editNote.value,
      amount,
    }
    if (editGroupId.value == null) body.clear_group = true
    else body.group_id = editGroupId.value
    entry.value = await api.updateEntry(props.id, body)
    editAmount.value = entry.value.amount ?? ''
    editGroupId.value = entry.value.group_id
    msg.value = '已保存'
  } catch (e) {
    error.value = e.message
  }
}

async function reparse() {
  reparsing.value = true
  error.value = ''
  msg.value = ''
  try {
    const force = entry.value?.amount_source === 'manual'
    entry.value = await api.reparseAmount(props.id, force)
    editAmount.value = entry.value.amount ?? ''
    msg.value = force ? '已强制重新识别并覆盖手改金额' : '已重新识别金额'
  } catch (e) {
    error.value = e.message
  } finally {
    reparsing.value = false
  }
}

function formatDupWarn(w) {
  if (!w) return ''
  const no = w.invoice_number ? `（发票号码 ${w.invoice_number}）` : ''
  const title = w.existing_entry_title || (w.existing_entry_id != null ? `#${w.existing_entry_id}` : '已有材料')
  return `可能与已有条目「${title}」重复${no}；可对比后删除其一`
}

function openDupCompare() {
  const w = dupWarn.value
  const inv = invoiceMaterial.value
  if (!w?.existing_material_id || !inv?.url) {
    error.value = '无法打开对比：缺少发票预览'
    return
  }
  compare.value = {
    invoiceNumber: w.invoice_number || '',
    leftLabel: '本条目发票',
    leftUrl: inv.url,
    leftKind: previewKind(inv),
    leftTitle: inv.original_name,
    rightLabel: w.existing_entry_title ? `已有：${w.existing_entry_title}` : '已有发票',
    rightUrl: api.materialFileUrl(w.existing_material_id),
    rightKind: previewKindFromNameMime(w.existing_original_name, w.existing_mime),
    rightTitle: w.existing_original_name || `材料 #${w.existing_material_id}`,
  }
}

async function deleteDupEntry() {
  const w = dupWarn.value
  const entryId = w?.existing_entry_id
  if (entryId == null) return
  if (Number(entryId) === Number(props.id)) {
    error.value = '不能删除当前正在查看的条目'
    return
  }
  const title = w.existing_entry_title || `#${entryId}`
  const ok = await askConfirm({
    title: '删除已有条目',
    message: `确定删除已有条目「${title}」及其全部材料？`,
    confirmText: '删除已有条目',
    cancelText: '取消',
    danger: true,
  })
  if (!ok) return
  error.value = ''
  try {
    await api.deleteEntry(entryId)
    dupWarn.value = null
    msg.value = `已删除条目「${title}」`
  } catch (e) {
    error.value = e.message
  }
}

async function onUpload(ev, type) {
  const file = ev.target.files?.[0]
  ev.target.value = ''
  if (!file || slotBusy(type)) return
  error.value = ''
  dupWarn.value = null
  msg.value = ''
  uploadingType.value = type
  const blobUrl = URL.createObjectURL(file)
  localPreview.value = {
    type,
    url: blobUrl,
    original_name: file.name,
    mime: file.type || '',
  }
  try {
    await api.uploadMaterial(file, { entryId: Number(props.id), type })
    await load({ silent: true })
    kickAnalyzePolling()
    msg.value = `${slotLabels.value[type] || type}已上传，正在后台识别`
  } catch (e) {
    error.value = e.message
  } finally {
    uploadingType.value = ''
    if (localPreview.value?.url === blobUrl) localPreview.value = null
    nextTick(() => URL.revokeObjectURL(blobUrl))
  }
}

async function removeMaterial(m) {
  if (slotBusy(m.type)) return
  const ok = await askConfirm({
    title: '删除材料',
    message: `确定删除材料「${m.original_name}」？`,
    confirmText: '删除',
    cancelText: '取消',
    danger: true,
  })
  if (!ok) return
  const snapshot = entry.value
  const materials = (snapshot.materials || []).filter((x) => x.id !== m.id)
  entry.value = {
    ...snapshot,
    materials,
    completeness: completenessFromMaterials(materials),
  }
  if (m.type === invoiceId.value || m.type === 'invoice') dupWarn.value = null
  deletingType.value = m.type
  error.value = ''
  try {
    await api.deleteMaterial(m.id)
    await load({ silent: true })
  } catch (e) {
    if (e.status === 404) {
      await load({ silent: true })
    } else {
      entry.value = snapshot
      error.value = e.message
    }
  } finally {
    deletingType.value = ''
  }
}

async function postToLedger() {
  const e = entry.value
  if (!e || e.amount == null || Number(e.amount) <= 0) return
  const ok = await askConfirm({
    title: '记入账本',
    message: `将「${e.title}」记为支出 ¥${Number(e.amount).toFixed(2)}？金额以当前值为快照。`,
    confirmText: '入账',
  })
  if (!ok) return
  posting.value = true
  error.value = ''
  try {
    const txn = await api.ledgerFromEntry(e.id)
    entry.value = { ...e, ledger_txn_id: txn.id }
    msg.value = '已记入账本'
  } catch (err) {
    error.value = err.message
  } finally {
    posting.value = false
  }
}

async function compose() {
  composing.value = true
  error.value = ''
  try {
    const { blob, filename } = await api.composeEntry(props.id)
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.click()
    URL.revokeObjectURL(url)
  } catch (e) {
    error.value = e.message
  } finally {
    composing.value = false
  }
}

const anyProcessing = computed(() => (entry.value?.materials || []).some((m) => m.processing))
let processingTimer = null

function stopProcessingTimer() {
  if (!processingTimer) return
  clearInterval(processingTimer)
  processingTimer = null
}

watch(
  anyProcessing,
  (busy, was) => {
    if (busy) {
      kickAnalyzePolling()
      if (!processingTimer) {
        processingTimer = window.setInterval(async () => {
          await kickAnalyzePolling()
          await load({ silent: true })
        }, 1600)
      }
      return
    }
    stopProcessingTimer()
    if (was) {
      void load({ silent: true })
      if (String(msg.value).includes('后台识别')) msg.value = '识别已完成'
    }
  },
  { immediate: true },
)

watch(() => route.params.id, () => load())
onMounted(load)
onUnmounted(stopProcessingTimer)
</script>
