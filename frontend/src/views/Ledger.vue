<template>
  <div>
    <div class="page-head">
      <div>
        <h1>记账</h1>
        <p>全社团余额、分活动花费与按科目汇总。收入手记；报销可从条目一键入账。</p>
      </div>
      <div class="actions">
        <button class="btn" type="button" @click="showCats = !showCats">{{ showCats ? '收起科目' : '管理科目' }}</button>
        <button class="btn btn-primary" type="button" @click="openCreate()">记一笔</button>
      </div>
    </div>

    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="msg" class="okmsg">{{ msg }}</p>
    <div v-if="loading" class="meta">加载中…</div>

    <template v-else>
      <div class="settings-tabs" role="tablist">
        <button type="button" class="settings-tab" :class="{ active: view === 'club' }" @click="setView('club')">全社团</button>
        <button type="button" class="settings-tab" :class="{ active: view === 'activity' }" @click="setView('activity')">分活动</button>
        <button type="button" class="settings-tab" :class="{ active: view === 'category' }" @click="setView('category')">按科目</button>
      </div>

      <div class="ledger-kpis">
        <div class="ledger-kpi card">
          <span class="meta">收入</span>
          <strong>{{ formatAmount(summary.income_sum) }}</strong>
        </div>
        <div class="ledger-kpi card">
          <span class="meta">支出</span>
          <strong>{{ formatAmount(summary.expense_sum) }}</strong>
        </div>
        <div class="ledger-kpi card">
          <span class="meta">可用余额</span>
          <strong :class="{ 'ledger-neg': summary.balance < 0 }">{{ formatAmount(summary.balance) }}</strong>
        </div>
      </div>

      <section v-if="view === 'activity'" class="card ledger-buckets">
        <p class="meta settings-lead">活动预算选填。剩余 = 预算 − 该组支出（未填预算则只显示花费）。</p>
        <table class="ledger-table">
          <thead>
            <tr>
              <th>活动 / 分组</th>
              <th>预算</th>
              <th>支出</th>
              <th>剩余</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="b in summary.by_group"
              :key="b.group_id ?? 'ungrouped'"
              class="ledger-click-row"
              :class="{ active: isGroupFilter(b) }"
              @click="selectGroup(b)"
            >
              <td>{{ b.group_name }}</td>
              <td @click.stop>
                <input
                  v-if="b.group_id != null"
                  class="ledger-budget-input"
                  type="number"
                  min="0"
                  step="0.01"
                  :value="b.budget ?? ''"
                  placeholder="—"
                  @change="onBudget(b, $event)"
                />
                <span v-else class="meta">—</span>
              </td>
              <td>{{ formatAmount(b.expense_sum) }}</td>
              <td>
                <span v-if="b.remaining != null" :class="{ 'ledger-neg': b.remaining < 0 }">{{ formatAmount(b.remaining) }}</span>
                <span v-else class="meta">—</span>
              </td>
            </tr>
          </tbody>
        </table>
      </section>

      <section v-else-if="view === 'category'" class="card ledger-buckets">
        <div class="ledger-cat-cols">
          <div>
            <h4 class="form-fill-h">收入科目</h4>
            <table class="ledger-table">
              <tbody>
                <tr
                  v-for="c in incomeBuckets"
                  :key="c.category_id"
                  class="ledger-click-row"
                  :class="{ active: filter.category_id === c.category_id }"
                  @click="selectCategory(c.category_id)"
                >
                  <td>{{ c.name }}</td>
                  <td>{{ formatAmount(c.amount_sum) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div>
            <h4 class="form-fill-h">支出科目</h4>
            <table class="ledger-table">
              <tbody>
                <tr
                  v-for="c in expenseBuckets"
                  :key="c.category_id"
                  class="ledger-click-row"
                  :class="{ active: filter.category_id === c.category_id }"
                  @click="selectCategory(c.category_id)"
                >
                  <td>{{ c.name }}</td>
                  <td>{{ formatAmount(c.amount_sum) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <section v-if="showCats" class="card ledger-cat-admin">
        <p class="meta settings-lead">科目用于记账分类。已有流水的科目不能删除。</p>
        <div class="ledger-cat-admin-grid">
          <div v-for="kind in ['income', 'expense']" :key="kind">
            <h4 class="form-fill-h">{{ kind === 'income' ? '收入' : '支出' }}</h4>
            <div v-for="c in catsOf(kind)" :key="c.id" class="form-def-row">
              <input :value="c.id" disabled />
              <input :value="c.name" maxlength="40" @change="renameCat(c, $event)" />
              <button class="btn-ghost custom-color-remove" type="button" title="删除" @click="removeCat(c)">×</button>
            </div>
            <div class="form-def-row">
              <input v-model="newCat[kind].id" maxlength="32" placeholder="id" />
              <input v-model="newCat[kind].name" maxlength="40" placeholder="显示名" />
              <button class="btn btn-sm" type="button" @click="addCat(kind)">添加</button>
            </div>
          </div>
        </div>
      </section>

      <section class="card ledger-txns">
        <div class="ledger-txn-head">
          <h4 class="form-fill-h">流水</h4>
          <span class="meta">{{ txnFilterHint }}</span>
          <button v-if="hasFilter" class="btn btn-sm" type="button" @click="clearFilter">显示全部</button>
        </div>
        <p v-if="!txns.length" class="meta">暂无流水</p>
        <table v-else class="ledger-table">
          <thead>
            <tr>
              <th>日期</th>
              <th>摘要</th>
              <th>科目</th>
              <th>活动</th>
              <th>金额</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="t in txns" :key="t.id" :class="{ 'ledger-row-hl': highlightId === t.id }">
              <td>{{ t.occurred_on }}</td>
              <td>
                {{ t.title }}
                <span v-if="t.entry_id" class="chip chip-ok">报销</span>
              </td>
              <td>{{ t.category_name }}</td>
              <td>{{ t.group_name || '—' }}</td>
              <td :class="t.kind === 'income' ? 'ledger-in' : 'ledger-out'">
                {{ t.kind === 'income' ? '+' : '−' }}{{ formatAmount(t.amount) }}
              </td>
              <td class="col-actions">
                <router-link v-if="t.entry_id" class="link-btn" :to="`/entries/${t.entry_id}`">条目</router-link>
                <button class="link-btn" type="button" @click="openEdit(t)">改</button>
                <button class="link-btn link-danger" type="button" @click="removeTxn(t)">删</button>
              </td>
            </tr>
          </tbody>
        </table>
      </section>
    </template>

    <Teleport to="body">
      <div v-if="formOpen" class="modal-backdrop" @click.self="formOpen = false">
        <div class="modal-card" role="dialog" aria-modal="true">
          <h3 class="modal-title">{{ form.id ? '改流水' : '记一笔' }}</h3>
          <div class="meta-grid" style="margin-top: 0.75rem">
            <div class="field">
              <label>类型</label>
              <select v-model="form.kind" :disabled="!!form.entry_id">
                <option value="income">收入</option>
                <option value="expense">支出</option>
              </select>
            </div>
            <div class="field">
              <label>金额</label>
              <input v-model="form.amount" type="number" min="0" step="0.01" :disabled="!!form.entry_id" />
            </div>
            <div class="field">
              <label>日期</label>
              <input v-model="form.occurred_on" type="date" />
            </div>
            <div class="field">
              <label>科目</label>
              <select v-model="form.category_id">
                <option v-for="c in catsOf(form.kind)" :key="c.id" :value="c.id">{{ c.name }}</option>
              </select>
            </div>
            <div class="field field-span-2">
              <label>摘要</label>
              <input v-model="form.title" maxlength="200" :disabled="!!form.entry_id" />
            </div>
            <div class="field">
              <label>活动分组</label>
              <select v-model="form.group_id" :disabled="!!form.entry_id">
                <option value="">未分组</option>
                <option v-for="g in groups" :key="g.id" :value="g.id">{{ g.name }}</option>
              </select>
            </div>
            <div class="field field-span-2">
              <label>备注</label>
              <input v-model="form.note" />
            </div>
          </div>
          <p v-if="form.entry_id" class="meta">来自报销条目：金额、摘要、分组以条目为准，请到条目里改。</p>
          <div class="modal-actions">
            <button class="btn" type="button" @click="formOpen = false">取消</button>
            <button class="btn btn-primary" type="button" :disabled="saving" @click="saveForm">{{ saving ? '保存中…' : '保存' }}</button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { api, formatAmount } from '../api/client'
import { useConfirmDialog } from '../composables/useConfirmDialog'

const route = useRoute()
const { askConfirm } = useConfirmDialog()

const loading = ref(true)
const saving = ref(false)
const error = ref('')
const msg = ref('')
const view = ref('club')
const summary = ref({ income_sum: 0, expense_sum: 0, balance: 0, by_group: [], by_category: [] })
const txns = ref([])
const categories = ref([])
const groups = ref([])
const showCats = ref(false)
const highlightId = ref(null)
const filter = reactive({ group_id: undefined, ungrouped: false, category_id: '' })
const formOpen = ref(false)
const form = reactive(emptyForm())
const newCat = reactive({
  income: { id: '', name: '' },
  expense: { id: '', name: '' },
})

const incomeBuckets = computed(() => (summary.value.by_category || []).filter((c) => c.kind === 'income'))
const expenseBuckets = computed(() => (summary.value.by_category || []).filter((c) => c.kind === 'expense'))
const hasFilter = computed(() => filter.ungrouped || filter.group_id != null || !!filter.category_id)
const txnFilterHint = computed(() => {
  if (filter.category_id) {
    const c = categories.value.find((x) => x.id === filter.category_id)
    return c ? `科目：${c.name}` : ''
  }
  if (filter.ungrouped) return '未分组'
  if (filter.group_id != null) {
    const g = (summary.value.by_group || []).find((x) => x.group_id === filter.group_id)
    return g ? `活动：${g.group_name}` : ''
  }
  return '全部'
})

function emptyForm() {
  return {
    id: null,
    entry_id: null,
    kind: 'expense',
    amount: '',
    occurred_on: new Date().toISOString().slice(0, 10),
    title: '',
    note: '',
    group_id: '',
    category_id: 'other',
  }
}

function catsOf(kind) {
  return categories.value.filter((c) => c.kind === kind)
}

function setView(v) {
  view.value = v
  if (v === 'club') clearFilter()
}

function isGroupFilter(b) {
  if (b.group_id == null) return filter.ungrouped
  return filter.group_id === b.group_id
}

function selectGroup(b) {
  filter.category_id = ''
  if (b.group_id == null) {
    filter.ungrouped = true
    filter.group_id = undefined
  } else {
    filter.ungrouped = false
    filter.group_id = b.group_id
  }
  loadTxns()
}

function selectCategory(id) {
  filter.ungrouped = false
  filter.group_id = undefined
  filter.category_id = id
  loadTxns()
}

function clearFilter() {
  filter.ungrouped = false
  filter.group_id = undefined
  filter.category_id = ''
  loadTxns()
}

async function loadAll() {
  loading.value = true
  error.value = ''
  try {
    const [sum, cats, gs] = await Promise.all([
      api.ledgerSummary(),
      api.listLedgerCategories(),
      api.listGroups(),
    ])
    summary.value = sum
    categories.value = cats
    groups.value = gs
    await loadTxns()
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

async function loadTxns() {
  const params = {}
  if (filter.category_id) params.category_id = filter.category_id
  if (filter.ungrouped) params.ungrouped = true
  else if (filter.group_id != null) params.group_id = filter.group_id
  try {
    txns.value = await api.listLedgerTxns(params)
  } catch (e) {
    error.value = e.message
  }
}

function openCreate() {
  Object.assign(form, emptyForm())
  const first = catsOf(form.kind)[0]
  if (first) form.category_id = first.id
  formOpen.value = true
}

function openEdit(t) {
  form.id = t.id
  form.entry_id = t.entry_id
  form.kind = t.kind
  form.amount = t.amount
  form.occurred_on = t.occurred_on
  form.title = t.title
  form.note = t.note || ''
  form.group_id = t.group_id ?? ''
  form.category_id = t.category_id
  formOpen.value = true
}

watch(
  () => form.kind,
  (k) => {
    if (form.id) return
    const ids = catsOf(k).map((c) => c.id)
    if (!ids.includes(form.category_id)) form.category_id = ids[0] || ''
  },
)

async function saveForm() {
  const amount = Number(form.amount)
  if (!form.title.trim() || Number.isNaN(amount) || amount <= 0) {
    error.value = '请填写摘要和大于 0 的金额'
    return
  }
  saving.value = true
  error.value = ''
  try {
    const gid = form.group_id === '' || form.group_id == null ? null : Number(form.group_id)
    const payload = {
      kind: form.kind,
      amount,
      occurred_on: form.occurred_on,
      title: form.title.trim(),
      note: form.note,
      category_id: form.category_id,
    }
    if (form.id) {
      payload.group_id = gid
      payload.clear_group = gid == null
    } else {
      payload.group_id = gid
    }
    if (form.id) await api.updateLedgerTxn(form.id, payload)
    else await api.createLedgerTxn(payload)
    formOpen.value = false
    msg.value = '已保存'
    await loadAll()
  } catch (e) {
    error.value = e.message
  } finally {
    saving.value = false
  }
}

async function removeTxn(t) {
  const ok = await askConfirm({
    title: '删除流水',
    message: `删除「${t.title}」${formatAmount(t.amount)}？${t.entry_id ? '条目可再次入账。' : ''}`,
    confirmText: '删除',
    danger: true,
  })
  if (!ok) return
  try {
    await api.deleteLedgerTxn(t.id)
    await loadAll()
  } catch (e) {
    error.value = e.message
  }
}

async function onBudget(b, ev) {
  const raw = ev.target.value
  try {
    if (raw === '') await api.updateGroup(b.group_id, { clear_budget: true })
    else await api.updateGroup(b.group_id, { budget: Number(raw) })
    summary.value = await api.ledgerSummary()
  } catch (e) {
    error.value = e.message
  }
}

async function addCat(kind) {
  const id = newCat[kind].id.trim()
  const name = newCat[kind].name.trim()
  if (!id || !name) return
  try {
    await api.createLedgerCategory({ id, kind, name })
    newCat[kind].id = ''
    newCat[kind].name = ''
    categories.value = await api.listLedgerCategories()
    summary.value = await api.ledgerSummary()
  } catch (e) {
    error.value = e.message
  }
}

async function renameCat(c, ev) {
  const name = ev.target.value.trim()
  if (!name || name === c.name) return
  try {
    await api.updateLedgerCategory(c.id, { name })
    categories.value = await api.listLedgerCategories()
    summary.value = await api.ledgerSummary()
  } catch (e) {
    error.value = e.message
  }
}

async function removeCat(c) {
  const ok = await askConfirm({
    title: '删除科目',
    message: `删除科目「${c.name}」？`,
    confirmText: '删除',
    danger: true,
  })
  if (!ok) return
  try {
    await api.deleteLedgerCategory(c.id)
    categories.value = await api.listLedgerCategories()
    summary.value = await api.ledgerSummary()
  } catch (e) {
    error.value = e.message
  }
}

onMounted(async () => {
  const q = route.query
  if (q.view === 'activity' || q.view === 'category') view.value = q.view
  if (q.group === 'ungrouped') {
    view.value = 'activity'
    filter.ungrouped = true
  } else if (q.group) {
    view.value = 'activity'
    filter.group_id = Number(q.group)
  }
  if (q.category) {
    view.value = 'category'
    filter.category_id = String(q.category)
  }
  if (q.txn) highlightId.value = Number(q.txn)
  await loadAll()
})
</script>
