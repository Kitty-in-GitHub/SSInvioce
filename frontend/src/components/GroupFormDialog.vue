<template>
  <Teleport to="body">
    <div v-if="open" class="modal-backdrop" @click.self="close">
      <div class="modal-card modal-wide form-fill-card" role="dialog" aria-modal="true" aria-labelledby="group-form-title">
        <div class="modal-head">
          <div>
            <h3 id="group-form-title" class="modal-title">{{ template.name || '填表' }}</h3>
            <p class="modal-sub">填写后保存，即可下载 Word，并在「导出本组」时拼进 PDF 首页。</p>
          </div>
          <button class="btn btn-sm btn-ghost" type="button" @click="close">关闭</button>
        </div>

        <p v-if="error" class="error">{{ error }}</p>
        <div v-if="loading" class="meta">加载中…</div>

        <template v-else>
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

          <h4 class="form-fill-h">支出</h4>
          <div class="form-fill-table-wrap">
            <table class="form-fill-table">
              <thead>
                <tr>
                  <th>支出内容</th>
                  <th>金额（预算）</th>
                  <th>核销金额</th>
                  <th>备注</th>
                  <th>归入条目</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in expenseRows" :key="row.id">
                  <td>{{ row.label }}</td>
                  <td>
                    <input v-model="rows[row.id].amount" type="number" step="0.01" min="0" class="form-fill-money" />
                  </td>
                  <td>
                    <input
                      :value="rows[row.id].reimburse"
                      type="number"
                      step="0.01"
                      min="0"
                      class="form-fill-money"
                      @input="onReimburseInput(row.id, $event)"
                    />
                    <div class="meta">汇总 {{ formatMoney(autoReimburse[row.id]) }}</div>
                  </td>
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

          <h4 class="form-fill-h">组内条目归类</h4>
          <p class="meta">将发票条目归入支出类别后，核销金额默认按金额汇总，手改后不再自动覆盖。</p>
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
        </template>

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
import { computed, reactive, ref, watch } from 'vue'
import { api, formatAmount } from '../api/client'

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

const autoReimburse = computed(() => {
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
  let amount = 0
  let reimburse = 0
  for (const row of expenseRows.value) {
    const r = rows[row.id] || {}
    const a = Number(r.amount)
    const b = Number(r.reimburse)
    if (!Number.isNaN(a) && r.amount !== '' && r.amount != null) amount += a
    if (!Number.isNaN(b) && r.reimburse !== '' && r.reimburse != null) reimburse += b
  }
  return { amount: Math.round(amount * 100) / 100, reimburse: Math.round(reimburse * 100) / 100 }
})

function formatMoney(val) {
  if (val == null || val === '') return '—'
  const n = Number(val)
  if (Number.isNaN(n)) return '—'
  return formatAmount(n)
}

function assignedEntries(rowId) {
  return entries.value.filter((e) => e.expense_row === rowId)
}

function resetLocal() {
  error.value = ''
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
      amount: saved.amount ?? '',
      reimburse: saved.reimburse ?? '',
      remark: saved.remark ?? row.remark ?? '',
      reimburse_manual: !!saved.reimburse_manual,
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

function onReimburseInput(rowId, ev) {
  if (!rows[rowId]) return
  rows[rowId].reimburse = ev.target.value
  rows[rowId].reimburse_manual = true
}

function onEntryRow(entry, ev) {
  entry.expense_row = ev.target.value || null
  for (const row of expenseRows.value) {
    if (rows[row.id] && !rows[row.id].reimburse_manual) {
      const v = autoReimburse.value[row.id]
      rows[row.id].reimburse = v ? String(v) : ''
    }
  }
}

function payload() {
  const entry_rows = {}
  for (const e of entries.value) entry_rows[e.id] = e.expense_row || null
  const rowsOut = {}
  for (const row of expenseRows.value) {
    const r = rows[row.id] || {}
    rowsOut[row.id] = {
      amount: r.amount,
      reimburse: r.reimburse,
      remark: r.remark || '',
      reimburse_manual: !!r.reimburse_manual,
    }
  }
  return {
    template_id: template.value.id,
    fields: { ...fields },
    rows: rowsOut,
    entry_rows,
  }
}

async function load() {
  if (props.groupId == null) return
  loading.value = true
  error.value = ''
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
</script>
