<template>
  <div>
    <div class="page-head">
      <div>
        <h1>报销条目</h1>
        <p>分组管理 · 金额统计 · 齐套拼版</p>
      </div>
      <div class="actions">
        <router-link class="btn" to="/upload">批量上传</router-link>
      </div>
    </div>

    <div class="card" style="margin-bottom: 1rem">
      <div class="form-row">
        <input v-model="title" placeholder="新条目名称" style="flex:1;min-width:180px" @keyup.enter="create" />
        <input v-model="note" placeholder="备注（可选）" style="flex:1;min-width:140px" @keyup.enter="create" />
        <select v-model="newGroupId">
          <option :value="null">未分组</option>
          <option v-for="g in groups" :key="g.id" :value="g.id">{{ g.name }}</option>
        </select>
        <button class="btn btn-primary" :disabled="!title.trim() || creating" @click="create">新建条目</button>
      </div>
      <div class="form-row" style="margin-bottom:0">
        <input v-model="newGroupName" placeholder="新组名称" style="flex:1;min-width:160px" @keyup.enter="createGroup" />
        <button class="btn" :disabled="!newGroupName.trim() || creatingGroup" @click="createGroup">新建分组</button>
      </div>
      <p v-if="error" class="error">{{ error }}</p>
      <p v-if="hint" class="okmsg">{{ hint }}</p>
    </div>

    <div v-if="entries.length" class="card batch-bar">
      <label class="check-line">
        <input type="checkbox" :checked="allSelectableChecked" @change="toggleSelectAll" />
        全选齐套条目
      </label>
      <span class="meta">已选 {{ selectedIds.length }} 项</span>
      <button class="btn btn-primary" :disabled="!selectedIds.length || batchComposing" @click="composeSelected">
        {{ batchComposing ? '合并拼版中…' : `合并导出 PDF（${selectedIds.length}）` }}
      </button>
    </div>

    <div v-if="loading" class="meta">加载中…</div>
    <div v-else-if="!entries.length" class="card empty">暂无条目，先新建一条或去批量上传。</div>
    <div v-else class="group-sections">
      <section v-for="section in sections" :key="section.key" class="group-section card">
        <header class="group-head">
          <div>
            <h2>{{ section.title }}</h2>
            <p class="meta">
              {{ section.entries.length }} 条 · 合计 {{ formatAmount(section.amountSum) }}
              <span v-if="section.group" :class="section.group.complete ? 'badge badge-ok' : 'badge badge-warn'">
                {{ section.group.complete ? '齐套可导出' : `缺套 ${section.group.incomplete_count}` }}
              </span>
              <span v-else-if="section.entries.length" class="badge badge-warn">未分组</span>
            </p>
          </div>
          <div class="actions">
            <button class="btn" type="button" @click="selectGroupComplete(section)">选中本组齐套</button>
            <button
              v-if="section.group"
              class="btn btn-primary"
              type="button"
              :disabled="!section.group.complete || composingGroupId === section.group.id"
              :title="section.group.complete ? '' : '组内有不齐套条目，禁止导出'"
              @click="composeGroup(section.group)"
            >
              {{ composingGroupId === section.group.id ? '导出中…' : '导出本组 PDF' }}
            </button>
            <button v-if="section.group" class="btn" type="button" @click="renameGroup(section.group)">改名</button>
            <button v-if="section.group" class="btn btn-danger" type="button" @click="removeGroup(section.group)">删组</button>
          </div>
        </header>

        <div v-if="!section.entries.length" class="empty">本组暂无条目</div>
        <div v-else class="list">
          <div v-for="e in section.entries" :key="e.id" class="card entry-row nested">
            <label class="entry-check">
              <input
                type="checkbox"
                :disabled="!e.completeness.complete"
                :checked="selectedIds.includes(e.id)"
                @change="toggleSelect(e)"
              />
            </label>
            <div>
              <h3>
                <router-link :to="`/entries/${e.id}`">{{ e.title }}</router-link>
              </h3>
              <div class="meta">
                <span v-if="e.note">{{ e.note }} · </span>
                <span :class="e.completeness.complete ? 'badge badge-ok' : 'badge badge-warn'">
                  {{ e.completeness.complete ? '齐套' : `缺：${missingLabel(e.completeness.missing)}` }}
                </span>
                <span class="amount-tag" :class="e.amount_source">
                  {{ e.amount_source === 'manual' ? '已手改' : e.amount_source === 'auto' ? '自动' : '无金额' }}
                </span>
              </div>
            </div>
            <div class="amount-edit">
              <input
                type="number"
                step="0.01"
                min="0"
                :value="e.amount ?? ''"
                placeholder="金额"
                @change="onAmountChange(e, $event)"
              />
            </div>
            <div class="actions">
              <select :value="e.group_id ?? ''" @change="onGroupChange(e, $event)">
                <option value="">未分组</option>
                <option v-for="g in groups" :key="g.id" :value="g.id">{{ g.name }}</option>
              </select>
              <router-link class="btn" :to="`/entries/${e.id}`">详情</router-link>
              <button class="btn btn-primary" :disabled="!e.completeness.complete || composingId === e.id" @click="compose(e)">
                {{ composingId === e.id ? '拼版中…' : '拼版' }}
              </button>
              <button class="btn btn-danger" @click="remove(e)">删除</button>
            </div>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { api, formatAmount, missingLabel } from '../api/client'
import { useConfirmDialog } from '../composables/useConfirmDialog'

const { askConfirm } = useConfirmDialog()
const entries = ref([])
const groups = ref([])
const loading = ref(true)
const title = ref('')
const note = ref('')
const newGroupId = ref(null)
const newGroupName = ref('')
const creating = ref(false)
const creatingGroup = ref(false)
const error = ref('')
const hint = ref('')
const composingId = ref(null)
const composingGroupId = ref(null)
const selectedIds = ref([])
const batchComposing = ref(false)

const selectableEntries = computed(() => entries.value.filter((e) => e.completeness.complete))
const allSelectableChecked = computed(
  () => selectableEntries.value.length > 0 && selectableEntries.value.every((e) => selectedIds.value.includes(e.id)),
)

const sections = computed(() => {
  const byGroup = new Map()
  for (const g of groups.value) {
    byGroup.set(g.id, [])
  }
  const ungrouped = []
  for (const e of entries.value) {
    if (e.group_id != null && byGroup.has(e.group_id)) byGroup.get(e.group_id).push(e)
    else ungrouped.push(e)
  }
  const result = groups.value.map((g) => {
    const list = byGroup.get(g.id) || []
    const amountSum = list.reduce((s, e) => s + (e.amount != null ? Number(e.amount) : 0), 0)
    return {
      key: `g-${g.id}`,
      title: g.name,
      group: g,
      entries: list,
      amountSum,
    }
  })
  result.push({
    key: 'ungrouped',
    title: '未分组',
    group: null,
    entries: ungrouped,
    amountSum: ungrouped.reduce((s, e) => s + (e.amount != null ? Number(e.amount) : 0), 0),
  })
  return result
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    ;[entries.value, groups.value] = await Promise.all([api.listEntries(), api.listGroups()])
    const valid = new Set(selectableEntries.value.map((e) => e.id))
    selectedIds.value = selectedIds.value.filter((id) => valid.has(id))
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

function toggleSelect(e) {
  if (!e.completeness.complete) return
  if (selectedIds.value.includes(e.id)) {
    selectedIds.value = selectedIds.value.filter((id) => id !== e.id)
  } else {
    selectedIds.value = [...selectedIds.value, e.id]
  }
}

function toggleSelectAll(ev) {
  selectedIds.value = ev.target.checked ? selectableEntries.value.map((e) => e.id) : []
}

function selectGroupComplete(section) {
  const completeIds = section.entries.filter((e) => e.completeness.complete).map((e) => e.id)
  const skipped = section.entries.length - completeIds.length
  const set = new Set(selectedIds.value)
  for (const id of completeIds) set.add(id)
  selectedIds.value = [...set]
  hint.value = skipped > 0 ? `已选中本组齐套条目，跳过 ${skipped} 条不齐套` : `已选中本组 ${completeIds.length} 条齐套条目`
}

async function create() {
  if (!title.value.trim()) return
  creating.value = true
  error.value = ''
  try {
    await api.createEntry({
      title: title.value.trim(),
      note: note.value,
      group_id: newGroupId.value,
    })
    title.value = ''
    note.value = ''
    await load()
  } catch (e) {
    error.value = e.message
  } finally {
    creating.value = false
  }
}

async function createGroup() {
  if (!newGroupName.value.trim()) return
  creatingGroup.value = true
  error.value = ''
  try {
    const g = await api.createGroup({ name: newGroupName.value.trim() })
    newGroupName.value = ''
    await load()
    newGroupId.value = g.id
    hint.value = `已创建分组「${g.name}」`
  } catch (e) {
    error.value = e.message
  } finally {
    creatingGroup.value = false
  }
}

async function renameGroup(g) {
  const name = window.prompt('新组名', g.name)
  if (name == null) return
  const trimmed = name.trim()
  if (!trimmed || trimmed === g.name) return
  try {
    await api.updateGroup(g.id, { name: trimmed })
    await load()
  } catch (e) {
    error.value = e.message
  }
}

async function removeGroup(g) {
  const ok = await askConfirm({
    title: '删除分组',
    message: `删除分组「${g.name}」？组内条目将变为未分组，不会删除条目。`,
    confirmText: '删除',
    cancelText: '取消',
    danger: true,
  })
  if (!ok) return
  try {
    await api.deleteGroup(g.id)
    await load()
  } catch (e) {
    error.value = e.message
  }
}

async function remove(e) {
  const ok = await askConfirm({
    title: '删除条目',
    message: `确定删除条目「${e.title}」及其全部材料？此操作不可恢复。`,
    confirmText: '删除',
    cancelText: '取消',
    danger: true,
  })
  if (!ok) return
  try {
    await api.deleteEntry(e.id)
    selectedIds.value = selectedIds.value.filter((id) => id !== e.id)
    await load()
  } catch (err) {
    error.value = err.message
  }
}

async function onAmountChange(e, ev) {
  const raw = ev.target.value
  const amount = raw === '' ? null : Number(raw)
  if (raw !== '' && Number.isNaN(amount)) {
    error.value = '金额格式无效'
    ev.target.value = e.amount ?? ''
    return
  }
  try {
    await api.updateEntry(e.id, { amount })
    await load()
  } catch (err) {
    error.value = err.message
  }
}

async function onGroupChange(e, ev) {
  const val = ev.target.value
  const group_id = val === '' ? null : Number(val)
  try {
    await api.updateEntry(e.id, group_id == null ? { clear_group: true } : { group_id })
    await load()
  } catch (err) {
    error.value = err.message
  }
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

async function compose(e) {
  composingId.value = e.id
  error.value = ''
  try {
    const { blob, filename } = await api.composeEntry(e.id)
    downloadBlob(blob, filename)
  } catch (err) {
    error.value = err.message
  } finally {
    composingId.value = null
  }
}

async function composeSelected() {
  if (!selectedIds.value.length) return
  batchComposing.value = true
  error.value = ''
  try {
    const { blob, filename } = await api.composeBatch(selectedIds.value)
    downloadBlob(blob, filename)
  } catch (err) {
    error.value = err.message
  } finally {
    batchComposing.value = false
  }
}

async function composeGroup(g) {
  if (!g.complete) {
    error.value = '组内存在不齐套条目，禁止导出'
    return
  }
  composingGroupId.value = g.id
  error.value = ''
  try {
    const { blob, filename } = await api.composeGroup(g.id)
    downloadBlob(blob, filename)
  } catch (err) {
    error.value = err.message
  } finally {
    composingGroupId.value = null
  }
}

onMounted(load)
</script>
