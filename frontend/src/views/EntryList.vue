<template>
  <div class="page-list">
    <div class="page-head">
      <div>
        <h1>报销条目</h1>
        <p>分组管理 · 金额统计 · 齐套拼版</p>
      </div>
      <div class="actions">
        <router-link class="btn" to="/upload">批量上传</router-link>
      </div>
    </div>

    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="hint" class="okmsg">{{ hint }}</p>

    <div v-if="entries.length" class="card batch-bar">
      <label class="check-line">
        <input type="checkbox" :checked="allSelectableChecked" @change="toggleSelectAll" />
        全选齐套条目
      </label>
      <span class="meta">已选 {{ selectedIds.length }} 项</span>
      <button class="btn btn-primary btn-sm" :disabled="!selectedIds.length || batchComposing" @click="composeSelected">
        {{ batchComposing ? '合并拼版中…' : `合并导出 PDF（${selectedIds.length}）` }}
      </button>
    </div>

    <div v-if="loading" class="meta">加载中…</div>
    <template v-else>
      <div class="group-sections">
        <section
          v-for="section in sections"
          :key="section.key"
          class="group-section card"
          :class="{ collapsed: isCollapsed(section.key) }"
        >
          <header class="group-head">
            <div class="group-head-lead">
              <button
                type="button"
                class="group-collapse-btn"
                :aria-expanded="!isCollapsed(section.key)"
                :aria-controls="`group-body-${section.key}`"
                :aria-label="isCollapsed(section.key) ? '展开分组' : '折叠分组'"
                @click="toggleCollapse(section.key)"
              >
                <span class="group-chevron" aria-hidden="true">▸</span>
              </button>
              <div class="group-head-info">
                <template v-if="section.group && editingGroupId === section.group.id">
                  <input
                    ref="renameInputEl"
                    v-model="editingGroupName"
                    class="group-title-input"
                    maxlength="80"
                    @keydown.enter.prevent="commitRename(section.group)"
                    @keydown.escape.prevent="cancelRename"
                    @blur="commitRename(section.group)"
                  />
                </template>
                <button
                  v-else-if="section.group"
                  type="button"
                  class="group-title-btn"
                  title="点击改名"
                  @click="startRename(section.group)"
                >
                  {{ section.title }}
                </button>
                <span v-else class="group-title">{{ section.title }}</span>
                <span class="meta group-meta">
                  {{ section.entries.length }} 条 · 合计 {{ formatAmount(section.amountSum) }}
                  <span v-if="section.group" :class="section.group.complete ? 'badge badge-ok' : 'badge badge-warn'">
                    {{ section.group.complete ? '齐套可导出' : `缺套 ${section.group.incomplete_count}` }}
                  </span>
                  <span v-else-if="section.entries.length" class="badge badge-warn">未分组</span>
                </span>
              </div>
            </div>
            <div class="group-head-actions" @click.stop>
              <div class="group-head-primary">
                <button class="btn btn-sm" type="button" @click="selectGroupComplete(section)">选中本组齐套</button>
                <button
                  v-if="section.group"
                  class="btn btn-primary btn-sm"
                  type="button"
                  :disabled="!section.group.complete || composingGroupId === section.group.id"
                  :title="section.group.complete ? '' : '组内有不齐套条目，禁止导出'"
                  @click="composeGroup(section.group)"
                >
                  {{ composingGroupId === section.group.id ? '导出中…' : '导出本组 PDF' }}
                </button>
              </div>
              <div v-if="section.group" class="group-head-secondary">
                <button class="btn-ghost danger" type="button" @click="removeGroup(section.group)">删组</button>
              </div>
            </div>
          </header>

          <div class="group-add-entry">
            <div v-if="draftingEntryKey === section.key" class="inline-create">
              <input
                ref="entryInputEl"
                v-model="draftEntryTitle"
                class="grow"
                placeholder="新条目名称"
                maxlength="120"
                @keydown.enter.prevent="submitEntry(section)"
                @keydown.escape.prevent="cancelDraftEntry"
              />
              <button class="btn btn-primary btn-sm" type="button" :disabled="!draftEntryTitle.trim() || creating" @click="submitEntry(section)">
                {{ creating ? '创建中…' : '创建' }}
              </button>
              <button class="btn-ghost" type="button" @click="cancelDraftEntry">取消</button>
            </div>
            <button
              v-else
              type="button"
              class="add-plus"
              :title="section.group ? `在「${section.title}」新建条目` : '新建未分组条目'"
              @click="startDraftEntry(section)"
            >
              <span aria-hidden="true">+</span>
              <span class="add-plus-label">新建条目</span>
            </button>
          </div>

          <div v-show="!isCollapsed(section.key)" :id="`group-body-${section.key}`" class="group-body">
            <div v-if="!section.entries.length" class="empty entry-list-empty">本组暂无条目</div>
            <div v-else class="list entry-list">
              <div v-for="e in section.entries" :key="e.id" class="entry-row">
                <label class="entry-check">
                  <input
                    type="checkbox"
                    :disabled="!e.completeness.complete"
                    :checked="selectedIds.includes(e.id)"
                    @change="toggleSelect(e)"
                  />
                </label>
                <div class="entry-main">
                  <h3>
                    <router-link :to="`/entries/${e.id}`">{{ e.title }}</router-link>
                  </h3>
                  <div class="meta entry-meta">
                    <span v-if="e.note" class="entry-note">{{ e.note }}</span>
                    <span :class="e.completeness.complete ? 'badge badge-ok' : 'badge badge-warn'">
                      {{ e.completeness.complete ? '齐套' : `缺：${missingLabel(e.completeness.missing)}` }}
                    </span>
                    <span class="amount-tag" :class="e.amount_source">
                      {{ e.amount_source === 'manual' ? '已手改' : e.amount_source === 'auto' ? '自动' : '无金额' }}
                    </span>
                  </div>
                </div>
                <div class="amount-edit">
                  <span class="amount-prefix" aria-hidden="true">¥</span>
                  <input
                    type="number"
                    step="0.01"
                    min="0"
                    :value="e.amount ?? ''"
                    placeholder="0.00"
                    @change="onAmountChange(e, $event)"
                  />
                </div>
                <select class="entry-group-select" :value="e.group_id ?? ''" @change="onGroupChange(e, $event)">
                  <option value="">未分组</option>
                  <option v-for="g in groups" :key="g.id" :value="g.id">{{ g.name }}</option>
                </select>
                <div class="entry-actions">
                  <button
                    class="btn btn-primary btn-sm"
                    :disabled="!e.completeness.complete || composingId === e.id"
                    @click="compose(e)"
                  >
                    {{ composingId === e.id ? '拼版中…' : '拼版' }}
                  </button>
                  <router-link class="btn btn-sm" :to="`/entries/${e.id}`">详情</router-link>
                  <button class="btn-ghost danger" type="button" @click="remove(e)">删除</button>
                </div>
              </div>
            </div>
          </div>
        </section>
      </div>

      <div class="add-group-footer">
        <div v-if="draftingGroup" class="inline-create card">
          <input
            ref="groupInputEl"
            v-model="draftGroupName"
            class="grow"
            placeholder="新组名称"
            maxlength="80"
            @keydown.enter.prevent="submitGroup"
            @keydown.escape.prevent="cancelDraftGroup"
          />
          <button class="btn btn-primary btn-sm" type="button" :disabled="!draftGroupName.trim() || creatingGroup" @click="submitGroup">
            {{ creatingGroup ? '创建中…' : '创建分组' }}
          </button>
          <button class="btn-ghost" type="button" @click="cancelDraftGroup">取消</button>
        </div>
        <button v-else type="button" class="add-plus add-plus-block" title="新建分组" @click="startDraftGroup">
          <span aria-hidden="true">+</span>
          <span class="add-plus-label">新建分组</span>
        </button>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, ref } from 'vue'
import { api, formatAmount, missingLabel } from '../api/client'
import { useConfirmDialog } from '../composables/useConfirmDialog'

const { askConfirm } = useConfirmDialog()
const entries = ref([])
const groups = ref([])
const loading = ref(true)
const creating = ref(false)
const creatingGroup = ref(false)
const error = ref('')
const hint = ref('')
const composingId = ref(null)
const composingGroupId = ref(null)
const selectedIds = ref([])
const batchComposing = ref(false)

const draftingEntryKey = ref(null)
const draftEntryTitle = ref('')
const draftingGroup = ref(false)
const draftGroupName = ref('')
const editingGroupId = ref(null)
const editingGroupName = ref('')
const renaming = ref(false)

const entryInputEl = ref(null)
const groupInputEl = ref(null)
const renameInputEl = ref(null)

const COLLAPSE_STORAGE_KEY = 'star-invoice-collapsed-groups'
const collapsedKeys = ref(loadCollapsedKeys())

function loadCollapsedKeys() {
  try {
    const raw = localStorage.getItem(COLLAPSE_STORAGE_KEY)
    const list = raw ? JSON.parse(raw) : []
    return new Set(Array.isArray(list) ? list : [])
  } catch {
    return new Set()
  }
}

function persistCollapsed() {
  localStorage.setItem(COLLAPSE_STORAGE_KEY, JSON.stringify([...collapsedKeys.value]))
}

function isCollapsed(key) {
  return collapsedKeys.value.has(key)
}

function toggleCollapse(key) {
  const next = new Set(collapsedKeys.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  collapsedKeys.value = next
  persistCollapsed()
}

function focusRef(elRef) {
  nextTick(() => {
    const el = elRef.value
    const node = Array.isArray(el) ? el[0] : el
    node?.focus?.()
    node?.select?.()
  })
}

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

function startDraftEntry(section) {
  draftingGroup.value = false
  draftingEntryKey.value = section.key
  draftEntryTitle.value = ''
  if (isCollapsed(section.key)) toggleCollapse(section.key)
  focusRef(entryInputEl)
}

function cancelDraftEntry() {
  draftingEntryKey.value = null
  draftEntryTitle.value = ''
}

async function submitEntry(section) {
  if (!draftEntryTitle.value.trim() || creating.value) return
  creating.value = true
  error.value = ''
  try {
    await api.createEntry({
      title: draftEntryTitle.value.trim(),
      note: '',
      group_id: section.group?.id ?? null,
    })
    cancelDraftEntry()
    await load()
  } catch (e) {
    error.value = e.message
  } finally {
    creating.value = false
  }
}

function startDraftGroup() {
  draftingEntryKey.value = null
  draftingGroup.value = true
  draftGroupName.value = ''
  focusRef(groupInputEl)
}

function cancelDraftGroup() {
  draftingGroup.value = false
  draftGroupName.value = ''
}

async function submitGroup() {
  if (!draftGroupName.value.trim() || creatingGroup.value) return
  creatingGroup.value = true
  error.value = ''
  try {
    const g = await api.createGroup({ name: draftGroupName.value.trim() })
    cancelDraftGroup()
    await load()
    hint.value = `已创建分组「${g.name}」`
  } catch (e) {
    error.value = e.message
  } finally {
    creatingGroup.value = false
  }
}

function startRename(g) {
  editingGroupId.value = g.id
  editingGroupName.value = g.name
  focusRef(renameInputEl)
}

function cancelRename() {
  editingGroupId.value = null
  editingGroupName.value = ''
}

async function commitRename(g) {
  if (renaming.value) return
  if (editingGroupId.value !== g.id) return
  const trimmed = editingGroupName.value.trim()
  if (!trimmed) {
    cancelRename()
    return
  }
  if (trimmed === g.name) {
    cancelRename()
    return
  }
  renaming.value = true
  error.value = ''
  try {
    await api.updateGroup(g.id, { name: trimmed })
    cancelRename()
    await load()
  } catch (e) {
    error.value = e.message
  } finally {
    renaming.value = false
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
