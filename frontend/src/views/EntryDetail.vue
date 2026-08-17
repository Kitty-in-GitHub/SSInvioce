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
            <span v-if="slot.missing" class="slot-missing-tag">缺失</span>
          </h4>
          <div class="preview">
            <MaterialPreview
              v-if="slot.material"
              :url="slot.material.url"
              :kind="previewKind(slot.material)"
              mode="detail"
              :title="slot.material.original_name"
              empty-text="无法预览"
            />
            <div v-else class="empty" :class="{ 'empty-missing': slot.missing }">
              {{ slot.missing ? '材料缺失' : '尚未上传' }}
            </div>
          </div>
          <div class="meta" v-if="slot.material">{{ slot.material.original_name }}</div>
          <div class="actions">
            <label class="btn btn-sm">
              {{ slot.material ? '替换' : '上传' }}
              <input type="file" hidden :accept="slot.accept" @change="onUpload($event, slot.type)" />
            </label>
            <button v-if="slot.material" class="btn btn-danger btn-sm" @click="removeMaterial(slot.material)">删除</button>
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
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { api, isImageMaterial, isPdfMaterial } from '../api/client'
import { acceptForKind, missingLabelFromSlots, useSlots } from '../composables/useSlots'
import InvoiceDupCompare from '../components/InvoiceDupCompare.vue'
import MaterialPreview from '../components/MaterialPreview.vue'
import { useConfirmDialog } from '../composables/useConfirmDialog'

const props = defineProps({ id: { type: [String, Number], required: true } })
const route = useRoute()
const { askConfirm } = useConfirmDialog()
const entry = ref(null)
const groups = ref([])
const loading = ref(true)
const error = ref('')
const dupWarn = ref(null)
const msg = ref('')
const composing = ref(false)
const reparsing = ref(false)
const editTitle = ref('')
const editNote = ref('')
const editAmount = ref('')
const editGroupId = ref(null)
const compare = ref(null)
const { slots: slotDefs, slotLabels, invoiceId } = useSlots()

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
    return {
      type: s.id,
      label: s.label,
      accept: acceptForKind(s.file_kind),
      material,
      missing: !material && missingSet.has(s.id),
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

async function load() {
  loading.value = true
  error.value = ''
  compare.value = null
  try {
    ;[entry.value, groups.value] = await Promise.all([api.getEntry(props.id), api.listGroups()])
    editTitle.value = entry.value.title
    editNote.value = entry.value.note || ''
    editAmount.value = entry.value.amount ?? ''
    editGroupId.value = entry.value.group_id
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
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
  if (!file) return
  error.value = ''
  dupWarn.value = null
  msg.value = ''
  try {
    const existing = entry.value.materials.find((m) => m.type === type)
    if (existing) await api.deleteMaterial(existing.id)
    const uploaded = await api.uploadMaterial(file, { entryId: Number(props.id), type })
    await load()
    msg.value = `${slotLabels.value[type] || type}已更新`
    if (uploaded?.duplicate_warning) {
      dupWarn.value = uploaded.duplicate_warning
    }
  } catch (e) {
    error.value = e.message
  }
}

async function removeMaterial(m) {
  const ok = await askConfirm({
    title: '删除材料',
    message: `确定删除材料「${m.original_name}」？`,
    confirmText: '删除',
    cancelText: '取消',
    danger: true,
  })
  if (!ok) return
  try {
    await api.deleteMaterial(m.id)
    if (m.type === 'invoice') dupWarn.value = null
    await load()
  } catch (e) {
    error.value = e.message
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

watch(() => route.params.id, load)
onMounted(load)
</script>
