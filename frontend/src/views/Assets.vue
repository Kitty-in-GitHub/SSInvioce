<template>
  <div>
    <div class="page-head">
      <div>
        <h1>物资</h1>
        <p>耐用品借还、消耗品出入库。图书请继续用外部表格，不在本页管理。</p>
      </div>
      <div class="actions">
        <button class="btn btn-primary" type="button" @click="openCreate">登记物品</button>
      </div>
    </div>

    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="msg" class="okmsg">{{ msg }}</p>
    <div v-if="loading" class="meta">加载中…</div>

    <template v-else>
      <div class="settings-tabs" role="tablist">
        <button type="button" class="settings-tab" :class="{ active: filterKind === '' }" @click="filterKind = ''">全部</button>
        <button type="button" class="settings-tab" :class="{ active: filterKind === 'durable' }" @click="filterKind = 'durable'">耐用品</button>
        <button type="button" class="settings-tab" :class="{ active: filterKind === 'consumable' }" @click="filterKind = 'consumable'">消耗品</button>
      </div>

      <p v-if="!filtered.length" class="meta">暂无物品。点击「登记物品」开始造册。</p>
      <section v-else class="card">
        <table class="ledger-table">
          <thead>
            <tr>
              <th>名称</th>
              <th>类型</th>
              <th>在库</th>
              <th>状态</th>
              <th>位置</th>
              <th>采购条目</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="a in filtered" :key="a.id">
              <td>
                <strong>{{ a.name }}</strong>
                <div v-if="a.note" class="meta">{{ a.note }}</div>
              </td>
              <td>{{ a.kind === 'durable' ? '耐用品' : '消耗品' }}</td>
              <td>{{ formatQty(a.qty) }}{{ a.unit ? ` ${a.unit}` : '' }}</td>
              <td>
                <span v-if="a.kind === 'durable'" class="chip" :class="a.borrowed_qty > 0 ? 'chip-warn' : 'chip-ok'">
                  {{ a.borrowed_qty > 0 ? `借出 ${formatQty(a.borrowed_qty)}` : '在库' }}
                </span>
                <span v-else class="chip" :class="a.qty <= 0 ? 'chip-warn' : 'chip-muted'">
                  {{ a.qty <= 0 ? '无库存' : '有库存' }}
                </span>
              </td>
              <td>{{ a.location || '—' }}</td>
              <td>
                <router-link v-if="a.entry_id" :to="`/entries/${a.entry_id}`">{{ a.entry_title || `#${a.entry_id}` }}</router-link>
                <span v-else class="meta">—</span>
              </td>
              <td class="col-actions">
                <button v-if="a.kind === 'consumable'" class="link-btn" type="button" @click="openTxn(a, 'in')">入库</button>
                <button v-if="a.kind === 'consumable'" class="link-btn" type="button" @click="openTxn(a, 'out')">领用</button>
                <button v-if="a.kind === 'durable'" class="link-btn" type="button" @click="openTxn(a, 'borrow')">借出</button>
                <button v-if="a.kind === 'durable'" class="link-btn" type="button" :disabled="a.borrowed_qty <= 0" @click="openTxn(a, 'return')">归还</button>
                <button class="link-btn" type="button" @click="openHistory(a)">流水</button>
                <button class="link-btn" type="button" @click="openEdit(a)">改</button>
                <button class="link-btn link-danger" type="button" @click="remove(a)">删</button>
              </td>
            </tr>
          </tbody>
        </table>
      </section>
    </template>

    <Teleport to="body">
      <div v-if="formOpen" class="modal-backdrop" @click.self="formOpen = false">
        <div class="modal-card" role="dialog" aria-modal="true">
          <h3 class="modal-title">{{ form.id ? '改物品' : '登记物品' }}</h3>
          <div class="meta-grid" style="margin-top: 0.75rem">
            <div class="field">
              <label>类型</label>
              <select v-model="form.kind" :disabled="!!form.id">
                <option value="durable">耐用品</option>
                <option value="consumable">消耗品</option>
              </select>
            </div>
            <div class="field">
              <label>名称</label>
              <input v-model="form.name" maxlength="200" />
            </div>
            <div v-if="!form.id" class="field">
              <label>数量</label>
              <input v-model="form.qty" type="number" min="0" step="1" />
            </div>
            <div class="field">
              <label>单位</label>
              <input v-model="form.unit" placeholder="个 / 台 / 盒" />
            </div>
            <div class="field">
              <label>存放位置</label>
              <input v-model="form.location" />
            </div>
            <div class="field field-span-2">
              <label>关联报销条目（可选）</label>
              <select v-model="form.entry_id">
                <option value="">不关联</option>
                <option v-for="e in entries" :key="e.id" :value="e.id">#{{ e.id }} {{ e.title }}</option>
              </select>
            </div>
            <div class="field field-span-2">
              <label>备注</label>
              <input v-model="form.note" />
            </div>
          </div>
          <div class="modal-actions">
            <button class="btn" type="button" @click="formOpen = false">取消</button>
            <button class="btn btn-primary" type="button" :disabled="saving" @click="saveForm">{{ saving ? '保存中…' : '保存' }}</button>
          </div>
        </div>
      </div>

      <div v-if="txnOpen" class="modal-backdrop" @click.self="txnOpen = false">
        <div class="modal-card" role="dialog" aria-modal="true">
          <h3 class="modal-title">{{ txnTitle }}</h3>
          <div class="meta-grid" style="margin-top: 0.75rem">
            <div class="field">
              <label>数量</label>
              <input v-model="txn.qty" type="number" min="0" step="1" />
            </div>
            <div v-if="txn.action === 'borrow'" class="field">
              <label>借用人</label>
              <input v-model="txn.person" />
            </div>
            <div class="field">
              <label>日期</label>
              <input v-model="txn.occurred_on" type="date" />
            </div>
            <div class="field field-span-2">
              <label>备注</label>
              <input v-model="txn.note" />
            </div>
          </div>
          <div class="modal-actions">
            <button class="btn" type="button" @click="txnOpen = false">取消</button>
            <button class="btn btn-primary" type="button" :disabled="saving" @click="saveTxn">{{ saving ? '提交中…' : '确定' }}</button>
          </div>
        </div>
      </div>

      <div v-if="histOpen" class="modal-backdrop" @click.self="histOpen = false">
        <div class="modal-card modal-wide" role="dialog" aria-modal="true">
          <div class="modal-head">
            <h3 class="modal-title">{{ histAsset?.name }} · 流水</h3>
            <button class="btn btn-sm" type="button" @click="histOpen = false">关闭</button>
          </div>
          <p v-if="!histTxns.length" class="meta">暂无流水</p>
          <table v-else class="ledger-table">
            <thead>
              <tr>
                <th>日期</th>
                <th>操作</th>
                <th>数量</th>
                <th>借用人</th>
                <th>备注</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="t in histTxns" :key="t.id">
                <td>{{ t.occurred_on }}</td>
                <td>{{ actionLabel(t.action) }}</td>
                <td>{{ formatQty(t.qty) }}</td>
                <td>{{ t.person || '—' }}</td>
                <td>{{ t.note || '—' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { api } from '../api/client'
import { useConfirmDialog } from '../composables/useConfirmDialog'

const { askConfirm } = useConfirmDialog()
const loading = ref(true)
const saving = ref(false)
const error = ref('')
const msg = ref('')
const assets = ref([])
const entries = ref([])
const filterKind = ref('')
const formOpen = ref(false)
const txnOpen = ref(false)
const histOpen = ref(false)
const histAsset = ref(null)
const histTxns = ref([])
const form = reactive(emptyForm())
const txn = reactive({ asset: null, action: 'in', qty: 1, person: '', occurred_on: today(), note: '' })

const filtered = computed(() => {
  if (!filterKind.value) return assets.value
  return assets.value.filter((a) => a.kind === filterKind.value)
})

const txnTitle = computed(() => {
  const map = { in: '入库', out: '领用', borrow: '借出', return: '归还' }
  const name = txn.asset?.name || ''
  return `${map[txn.action] || '操作'} · ${name}`
})

function today() {
  return new Date().toISOString().slice(0, 10)
}

function emptyForm() {
  return { id: null, kind: 'durable', name: '', qty: 1, unit: '个', location: '', note: '', entry_id: '' }
}

function formatQty(n) {
  const x = Number(n)
  if (Number.isNaN(x)) return '—'
  return Number.isInteger(x) ? String(x) : x.toFixed(2).replace(/0+$/, '').replace(/\.$/, '')
}

function actionLabel(a) {
  return { in: '入库', out: '领用', borrow: '借出', return: '归还', adjust: '调整' }[a] || a
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [list, ents] = await Promise.all([api.listAssets(), api.listEntries()])
    assets.value = list
    entries.value = ents
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

function openCreate() {
  Object.assign(form, emptyForm())
  formOpen.value = true
}

function openEdit(a) {
  form.id = a.id
  form.kind = a.kind
  form.name = a.name
  form.qty = a.qty
  form.unit = a.unit
  form.location = a.location
  form.note = a.note
  form.entry_id = a.entry_id ?? ''
  formOpen.value = true
}

function openTxn(a, action) {
  txn.asset = a
  txn.action = action
  txn.qty = 1
  txn.person = ''
  txn.occurred_on = today()
  txn.note = ''
  txnOpen.value = true
}

async function openHistory(a) {
  error.value = ''
  try {
    histAsset.value = a
    histTxns.value = await api.listAssetTxns(a.id)
    histOpen.value = true
  } catch (e) {
    error.value = e.message
  }
}

async function saveForm() {
  if (!form.name.trim()) {
    error.value = '请填写名称'
    return
  }
  saving.value = true
  error.value = ''
  try {
    const entry_id = form.entry_id === '' || form.entry_id == null ? null : Number(form.entry_id)
    if (form.id) {
      await api.updateAsset(form.id, {
        name: form.name.trim(),
        unit: form.unit,
        location: form.location,
        note: form.note,
        entry_id,
        clear_entry: entry_id == null,
      })
    } else {
      await api.createAsset({
        kind: form.kind,
        name: form.name.trim(),
        qty: Number(form.qty) || 0,
        unit: form.unit,
        location: form.location,
        note: form.note,
        entry_id,
      })
    }
    formOpen.value = false
    msg.value = '已保存'
    assets.value = await api.listAssets()
  } catch (e) {
    error.value = e.message
  } finally {
    saving.value = false
  }
}

async function saveTxn() {
  const qty = Number(txn.qty)
  if (!txn.asset || Number.isNaN(qty) || qty <= 0) {
    error.value = '数量须大于 0'
    return
  }
  saving.value = true
  error.value = ''
  try {
    await api.createAssetTxn(txn.asset.id, {
      action: txn.action,
      qty,
      person: txn.person,
      occurred_on: txn.occurred_on,
      note: txn.note,
    })
    txnOpen.value = false
    msg.value = '已记录'
    assets.value = await api.listAssets()
  } catch (e) {
    error.value = e.message
  } finally {
    saving.value = false
  }
}

async function remove(a) {
  const ok = await askConfirm({
    title: '删除物品',
    message: `删除「${a.name}」及其流水？未归还的借出无法删除。`,
    confirmText: '删除',
    danger: true,
  })
  if (!ok) return
  try {
    await api.deleteAsset(a.id)
    assets.value = await api.listAssets()
  } catch (e) {
    error.value = e.message
  }
}

watch(filterKind, () => {
  msg.value = ''
})

onMounted(load)
</script>
