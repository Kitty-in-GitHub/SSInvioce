<template>
  <Teleport to="body">
    <div v-if="open" class="modal-backdrop" @click.self="close">
      <div class="modal-card modal-wide form-fill-card" :class="{ 'form-fill-with-preview': previewOn }" role="dialog" aria-modal="true" aria-labelledby="group-form-title">
        <div class="modal-head">
          <div>
            <h3 id="group-form-title" class="modal-title">{{ template.name || '填表' }}</h3>
            <p class="modal-sub">表头手填；支出金额按条目归类自动汇总。预览为程序生成的 PDF（无需安装 Word），版式接近官方表。</p>
          </div>
          <div class="form-fill-head-actions">
            <label class="form-preview-toggle">
              <input v-model="previewOn" type="checkbox" />
              显示预览栏
            </label>
            <button class="btn btn-sm btn-ghost" type="button" @click="close">关闭</button>
          </div>
        </div>

        <p v-if="error" class="error">{{ error }}</p>
        <div v-if="loading" class="meta">加载中…</div>

        <div v-else class="form-fill-layout">
          <div class="form-fill-editor">
            <div class="form-fill-date" v-if="hasYmd">
              <div class="field">
                <label>填表日期</label>
                <input v-model="dateInput" type="date" @change="onDateChange" />
              </div>
            </div>
            <div class="meta-grid form-fill-fields">
              <div v-for="field in visibleFields" :key="field.id" class="field">
                <label>{{ field.label }}</label>
                <input
                  v-model="fields[field.id]"
                  :type="field.type === 'number' || field.type === 'money' ? 'number' : 'text'"
                  :step="field.type === 'money' ? '0.01' : undefined"
                />
              </div>
            </div>

            <h4 class="form-fill-h">组内条目归类</h4>
            <p class="meta">将条目归入支出类别后，金额与核销金额由程序按条目金额汇总，不可手改。</p>
            <div v-if="!entries.length" class="meta">本组暂无条目</div>
            <div v-else class="form-fill-entries">
              <div v-for="e in entries" :key="e.id" class="form-fill-entry">
                <span class="form-fill-entry-title">{{ e.title }}</span>
                <span class="meta">{{ formatMoney(e.amount) }}</span>
                <select :value="e.expense_row || ''" @change="onEntryRow(e, $event)">
                  <option value="">未归类</option>
                  <option v-for="row in expenseRows" :key="row.id" :value="row.id">{{ row.label }}</option>
                </select>
              </div>
            </div>

            <h4 class="form-fill-h">支出汇总</h4>
            <div class="form-fill-table-wrap">
              <table class="form-fill-table">
                <thead>
                  <tr>
                    <th>支出内容</th>
                    <th>金额</th>
                    <th>核销金额</th>
                    <th>备注</th>
                    <th>归入条目</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="row in expenseRows" :key="row.id">
                    <td>{{ row.label }}</td>
                    <td class="form-fill-money-cell">{{ formatMoney(autoAmount[row.id] || null) }}</td>
                    <td class="form-fill-money-cell">{{ formatMoney(autoAmount[row.id] || null) }}</td>
                    <td>
                      <input v-model="rows[row.id].remark" type="text" />
                    </td>
                    <td class="form-fill-assigned">
                      <span v-for="e in assignedEntries(row.id)" :key="e.id" class="form-fill-chip">{{ e.title }}</span>
                      <span v-if="!assignedEntries(row.id).length" class="meta">无</span>
                    </td>
                  </tr>
                  <tr class="form-fill-total">
                    <td>合计</td>
                    <td>{{ formatMoney(totals.amount) }}</td>
                    <td>{{ formatMoney(totals.reimburse) }}</td>
                    <td colspan="2"></td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <aside v-if="previewOn" class="form-preview-panel" aria-label="导出文件预览">
            <div class="form-preview-toolbar">
              <strong>导出预览（PDF）</strong>
              <button class="btn btn-sm btn-primary" type="button" :disabled="previewing || loading" @click="refreshPreview">
                {{ previewing ? '生成中…' : previewUrl ? '刷新预览' : '生成预览' }}
              </button>
            </div>
            <p v-if="previewError" class="error">{{ previewError }}</p>
            <p v-else-if="!previewUrl && !previewing" class="meta">
              点击「生成预览」：按当前填写内容生成 PDF（不依赖本机 Word）。下载「官方 Word」仍可用「保存并下载 Word」。
            </p>
            <div v-if="previewUrl" class="form-preview-frame-wrap">
              <iframe class="form-preview-frame" :src="previewUrl" title="表格导出预览" />
            </div>
          </aside>
        </div>

        <div class="modal-actions">
          <button class="btn" type="button" @click="close">取消</button>
          <button class="btn" type="button" :disabled="saving || loading" @click="saveAndDownload">{{ saving ? '处理中…' : '保存并下载 Word' }}</button>
          <button class="btn btn-primary" type="button" :disabled="saving || loading" @click="saveOnly">{{ saving ? '保存中…' : '保存' }}</button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { computed, onUnmounted, reactive, ref, watch } from 'vue'
import { api, formatAmount } from '../api/client'

const PREVIEW_KEY = 'star-invoice-form-preview-panel'

const props = defineProps({
  groupId: { type: Number, default: null },
})
const emit = defineEmits(['close', 'saved'])

const open = computed(() => props.groupId != null)
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const template = ref({ name: '', fields: [], tables: [] })
const fields = reactive({})
const rows = reactive({})
const entries = ref([])
const dateInput = ref('')
const previewOn = ref(loadPreviewPref())
const previewing = ref(false)
const previewError = ref('')
const previewUrl = ref('')

const expenseTable = computed(() => (template.value.tables || [])[0] || { rows: [], columns: [] })
const expenseRows = computed(() => expenseTable.value.rows || [])
const hasYmd = computed(() => {
  const ids = new Set((template.value.fields || []).map((f) => f.id))
  return ids.has('year') && ids.has('month') && ids.has('day')
})
const visibleFields = computed(() => {
  const hide = hasYmd.value ? new Set(['year', 'month', 'day']) : new Set()
  return (template.value.fields || []).filter((f) => !hide.has(f.id))
})

const autoAmount = computed(() => {
  const map = {}
  for (const row of expenseRows.value) map[row.id] = 0
  for (const e of entries.value) {
    const rid = e.expense_row
    if (!rid || !(rid in map)) continue
    const n = Number(e.amount)
    if (!Number.isNaN(n)) map[rid] += n
  }
  for (const k of Object.keys(map)) map[k] = Math.round(map[k] * 100) / 100
  return map
})

const totals = computed(() => {
  let sum = 0
  for (const row of expenseRows.value) {
    const n = Number(autoAmount.value[row.id] || 0)
    if (!Number.isNaN(n)) sum += n
  }
  const v = Math.round(sum * 100) / 100
  return { amount: v, reimburse: v }
})

function loadPreviewPref() {
  try {
    const raw = localStorage.getItem(PREVIEW_KEY)
    if (raw === null) return false
    return raw === '1' || raw === 'true'
  } catch {
    return false
  }
}

watch(previewOn, (v) => {
  try {
    localStorage.setItem(PREVIEW_KEY, v ? '1' : '0')
  } catch {
    /* ignore */
  }
})

function clearPreviewUrl() {
  if (previewUrl.value) {
    URL.revokeObjectURL(previewUrl.value)
    previewUrl.value = ''
  }
}

function formatMoney(val) {
  if (val == null || val === '' || val === 0) return '—'
  const n = Number(val)
  if (Number.isNaN(n) || n === 0) return '—'
  return formatAmount(n)
}

function assignedEntries(rowId) {
  return entries.value.filter((e) => e.expense_row === rowId)
}

function resetLocal() {
  error.value = ''
  previewError.value = ''
  previewing.value = false
  clearPreviewUrl()
  template.value = { name: '', fields: [], tables: [] }
  dateInput.value = ''
  for (const k of Object.keys(fields)) delete fields[k]
  for (const k of Object.keys(rows)) delete rows[k]
  entries.value = []
}

function applyPayload(data) {
  template.value = data.template || { name: '', fields: [], tables: [] }
  const f = data.values?.fields || {}
  for (const k of Object.keys(fields)) delete fields[k]
  for (const field of template.value.fields || []) {
    fields[field.id] = f[field.id] ?? ''
  }
  const r = data.values?.rows || {}
  for (const k of Object.keys(rows)) delete rows[k]
  for (const row of expenseRows.value) {
    const saved = r[row.id] || {}
    rows[row.id] = {
      remark: saved.remark ?? row.remark ?? '',
    }
  }
  entries.value = (data.entries || []).map((e) => ({ ...e }))
  if (hasYmd.value && fields.year && fields.month && fields.day) {
    const y = String(fields.year).padStart(4, '0')
    const m = String(fields.month).padStart(2, '0')
    const d = String(fields.day).padStart(2, '0')
    if (/^\d{4}$/.test(y) && /^\d{2}$/.test(m) && /^\d{2}$/.test(d)) dateInput.value = `${y}-${m}-${d}`
  }
}

function onDateChange() {
  const raw = dateInput.value
  if (!raw) return
  const [y, m, d] = raw.split('-')
  fields.year = y || ''
  fields.month = m ? String(Number(m)) : ''
  fields.day = d ? String(Number(d)) : ''
}

function onEntryRow(entry, ev) {
  entry.expense_row = ev.target.value || null
}

function moneyText(n) {
  if (!n) return ''
  return Number.isInteger(n) ? String(n) : n.toFixed(2)
}

function payload() {
  const entry_rows = {}
  for (const e of entries.value) entry_rows[e.id] = e.expense_row || null
  const rowsOut = {}
  for (const row of expenseRows.value) {
    const text = moneyText(autoAmount.value[row.id] || 0)
    rowsOut[row.id] = {
      amount: text,
      reimburse: text,
      remark: rows[row.id]?.remark || '',
      reimburse_manual: false,
    }
  }
  return {
    template_id: template.value.id,
    fields: { ...fields },
    rows: rowsOut,
    entry_rows,
  }
}

async function refreshPreview() {
  if (props.groupId == null || previewing.value) return
  previewing.value = true
  previewError.value = ''
  error.value = ''
  try {
    const blob = await api.previewGroupFormPdf(props.groupId, payload())
    clearPreviewUrl()
    previewUrl.value = URL.createObjectURL(blob)
  } catch (e) {
    previewError.value = e.message
  } finally {
    previewing.value = false
  }
}

async function load() {
  if (props.groupId == null) return
  loading.value = true
  error.value = ''
  clearPreviewUrl()
  previewError.value = ''
  try {
    applyPayload(await api.getGroupForm(props.groupId))
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

async function saveOnly() {
  saving.value = true
  error.value = ''
  try {
    applyPayload(await api.saveGroupForm(props.groupId, payload()))
    emit('saved')
  } catch (e) {
    error.value = e.message
  } finally {
    saving.value = false
  }
}

async function saveAndDownload() {
  saving.value = true
  error.value = ''
  try {
    applyPayload(await api.saveGroupForm(props.groupId, payload()))
    emit('saved')
    const { blob, filename } = await api.downloadGroupFormDocx(props.groupId)
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.click()
    URL.revokeObjectURL(url)
  } catch (e) {
    error.value = e.message
  } finally {
    saving.value = false
  }
}

function close() {
  emit('close')
}

watch(
  () => props.groupId,
  (id) => {
    if (id == null) resetLocal()
    else load()
  },
)

onUnmounted(() => {
  clearPreviewUrl()
})
</script>
