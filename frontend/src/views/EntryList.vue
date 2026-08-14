<template>
  <div class="page-list">
    <div class="page-head">
      <div>
        <h1>报销条目</h1>
        <p>分组管理 · 金额统计 · 齐套拼版</p>
      </div>
      <div class="actions">
        <button class="btn" type="button" @click="openUpload">批量上传</button>
      </div>
    </div>

    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="hint" class="okmsg">{{ hint }}</p>

    <div v-if="loading" class="meta">加载中…</div>
    <template v-else>
      <div class="list-board">
        <div v-if="entries.length" class="list-toolbar">
          <div class="list-toolbar-select">
            <button class="btn btn-sm" type="button" :disabled="!entries.length" @click="toggleSelectAll">
              {{ allEntriesChecked ? '取消全选' : '全选' }}
            </button>
            <button class="btn btn-sm" type="button" :disabled="!selectableEntries.length" @click="selectAllComplete">
              全选齐套
            </button>
          </div>
          <span class="meta">已选 {{ selectedIds.length }} · 共 {{ entries.length }} 条</span>
          <div class="list-toolbar-actions">
            <button class="btn btn-primary btn-sm" :disabled="!selectedCompleteCount || batchComposing || batchDeleting" @click="composeSelected">
              {{ batchComposing ? '合并拼版中…' : `合并导出（${selectedCompleteCount}）` }}
            </button>
            <button class="btn btn-danger btn-sm" :disabled="!selectedIds.length || batchComposing || batchDeleting" @click="removeSelected">
              {{ batchDeleting ? '删除中…' : `删除选中（${selectedIds.length}）` }}
            </button>
          </div>
        </div>

        <div class="group-sections">
          <section
            v-for="section in sections"
            :key="section.key"
            class="group-section"
            :class="{ collapsed: isCollapsed(section.key) }"
          >
            <header class="group-head">
              <div class="group-head-lead">
                <label class="group-check" :title="groupSelectTitle(section)" @click.stop>
                  <input
                    type="checkbox"
                    :checked="groupSelectState(section) === 'all'"
                    :indeterminate="groupSelectState(section) === 'some'"
                    :disabled="!section.entries.length"
                    @change="toggleGroupSelect(section)"
                  />
                </label>
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
                  <span class="group-meta">
                    <span>{{ section.entries.length }} 条</span>
                    <span>·</span>
                    <span>{{ formatAmount(section.amountSum) }}</span>
                    <span
                      v-if="section.group"
                      class="chip"
                      :class="section.group.complete ? 'chip-ok' : 'chip-warn'"
                    >
                      {{ section.group.complete ? '齐套' : `缺 ${section.group.incomplete_count}` }}
                    </span>
                    <span v-if="section.group?.has_form" class="chip chip-ok">已填表</span>
                    <span v-else-if="section.entries.length" class="chip chip-muted">未分组</span>
                  </span>
                </div>
              </div>
              <div class="group-head-actions" @click.stop>
                <button
                  v-if="section.group"
                  class="link-btn"
                  type="button"
                  @click="openForm(section.group)"
                >
                  {{ section.group.has_form ? '改表' : '填表' }}
                </button>
                <button
                  v-if="section.group"
                  class="link-btn"
                  type="button"
                  :disabled="!section.group.complete || composingGroupId === section.group.id"
                  :title="section.group.complete ? (section.group.has_form ? '将把已填表格拼进 PDF 首页' : '未填表则只导出材料') : '组内有不齐套条目，禁止导出'"
                  @click="composeGroup(section.group)"
                >
                  {{ composingGroupId === section.group.id ? '导出中…' : '导出本组' }}
                </button>
                <button class="link-btn" type="button" @click="selectGroupComplete(section)">选中齐套</button>
                <button
                  type="button"
                  class="add-plus add-plus-icon"
                  :title="section.group ? `在「${section.title}」新建条目` : '新建未分组条目'"
                  :aria-label="section.group ? `在「${section.title}」新建条目` : '新建未分组条目'"
                  @click="startDraftEntry(section)"
                >
                  <svg class="add-plus-svg" viewBox="0 0 16 16" aria-hidden="true">
                    <path d="M8 3v10M3 8h10" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" />
                  </svg>
                </button>
                <button
                  v-if="section.group"
                  class="link-btn link-danger"
                  type="button"
                  @click="removeGroup(section.group)"
                >
                  删除
                </button>
              </div>
            </header>

            <div v-if="draftingEntryKey === section.key" class="group-add-entry">
              <div class="inline-create">
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
            </div>

            <div v-show="!isCollapsed(section.key)" :id="`group-body-${section.key}`" class="group-body">
              <div v-if="!section.entries.length" class="empty entry-list-empty">本组暂无条目</div>
              <div v-else class="list entry-list">
                <div v-for="e in section.entries" :key="e.id" class="entry-row">
                  <label class="entry-check">
                    <input
                      type="checkbox"
                      :checked="selectedIds.includes(e.id)"
                      @change="toggleSelect(e)"
                    />
                  </label>
                  <div class="entry-main">
                    <div class="entry-title-row">
                      <router-link class="entry-title" :to="`/entries/${e.id}`">{{ e.title }}</router-link>
                      <span class="chip" :class="e.completeness.complete ? 'chip-ok' : 'chip-warn'">
                        {{ e.completeness.complete ? '齐套' : `缺：${missingLabel(e.completeness.missing)}` }}
                      </span>
                      <span
                        class="chip"
                        :class="amountChipClass(e.amount_source)"
                        :title="amountSourceHint(e.amount_source)"
                      >
                        {{ e.amount_source === 'manual' ? '手改' : e.amount_source === 'auto' ? '自动' : '无金额' }}
                      </span>
                    </div>
                    <div v-if="e.note" class="entry-note">{{ e.note }}</div>
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
                      class="link-btn link-accent"
                      type="button"
                      :disabled="!e.completeness.complete || composingId === e.id"
                      @click="compose(e)"
                    >
                      {{ composingId === e.id ? '拼版中…' : '拼版' }}
                    </button>
                    <router-link class="link-btn" :to="`/entries/${e.id}`">详情</router-link>
                    <button class="link-btn link-danger" type="button" @click="remove(e)">删除</button>
                  </div>
                </div>
              </div>
            </div>
          </section>
        </div>

        <div class="add-group-footer">
          <div v-if="draftingGroup" class="inline-create">
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
          <button v-else type="button" class="add-plus add-plus-block" title="新建分组" aria-label="新建分组" @click="startDraftGroup">
            <svg class="add-plus-svg" viewBox="0 0 16 16" aria-hidden="true">
              <path d="M8 3v10M3 8h10" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" />
            </svg>
          </button>
        </div>
      </div>
    </template>
    <GroupFormDialog :group-id="formGroupId" @close="formGroupId = null" @saved="load" />
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, ref } from 'vue'
import { api, formatAmount } from '../api/client'
import { missingLabelFromSlots, useSlots } from '../composables/useSlots'
import { useConfirmDialog } from '../composables/useConfirmDialog'
import { useBatchUploadDialog } from '../composables/useBatchUploadDialog'
import GroupFormDialog from '../components/GroupFormDialog.vue'

const { askConfirm } = useConfirmDialog()
const { slotLabels } = useSlots()
function missingLabel(missing) {
  return missingLabelFromSlots(missing, slotLabels.value)
}
const { openBatchUpload } = useBatchUploadDialog()
const entries = ref([])
const groups = ref([])
const loading = ref(true)
const creating = ref(false)
const creatingGroup = ref(false)
const error = ref('')
const hint = ref('')
const composingId = ref(null)
const composingGroupId = ref(null)
const formGroupId = ref(null)
const selectedIds = ref([])
const batchComposing = ref(false)
const batchDeleting = ref(false)

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

function amountChipClass(source) {
  if (source === 'manual') return 'chip-warn'
  if (source === 'auto') return 'chip-ok'
  return 'chip-muted'
}

function amountSourceHint(source) {
  if (source === 'manual') return '金额已手改，不再随识别结果覆盖'
  if (source === 'auto') return '金额来自发票/支付记录自动识别'
  return '尚未识别到金额'
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
const allEntriesChecked = computed(
  () => entries.value.length > 0 && entries.value.every((e) => selectedIds.value.includes(e.id)),
)
const selectedCompleteCount = computed(
  () => selectedIds.value.filter((id) => selectableEntries.value.some((e) => e.id === id)).length,
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
    const valid = new Set(entries.value.map((e) => e.id))
    selectedIds.value = selectedIds.value.filter((id) => valid.has(id))
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

function openUpload() {
  openBatchUpload({ onDone: load })
}

function toggleSelect(e) {
  if (selectedIds.value.includes(e.id)) {
    selectedIds.value = selectedIds.value.filter((id) => id !== e.id)
  } else {
    selectedIds.value = [...selectedIds.value, e.id]
  }
}

function toggleSelectAll() {
  selectedIds.value = allEntriesChecked.value ? [] : entries.value.map((e) => e.id)
}

function groupSelectState(section) {
  const total = section.entries.length
  if (!total) return 'none'
  const n = section.entries.filter((e) => selectedIds.value.includes(e.id)).length
  if (n === 0) return 'none'
  if (n === total) return 'all'
  return 'some'
}

function groupSelectTitle(section) {
  const state = groupSelectState(section)
  if (!section.entries.length) return '本组暂无条目'
  if (state === 'all') return '取消选中本组'
  if (state === 'some') return '本组部分已选，点击全选本组'
  return '选中本组全部条目'
}

function toggleGroupSelect(section) {
  const ids = section.entries.map((e) => e.id)
  if (!ids.length) return
  const set = new Set(selectedIds.value)
  if (groupSelectState(section) === 'all') {
    for (const id of ids) set.delete(id)
  } else {
    for (const id of ids) set.add(id)
  }
  selectedIds.value = [...set]
}

function selectAllComplete() {
  selectedIds.value = selectableEntries.value.map((e) => e.id)
  hint.value = `已选中 ${selectedIds.value.length} 条齐套条目`
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

async function removeSelected() {
  const ids = [...selectedIds.value]
  if (!ids.length) return
  const titles = entries.value.filter((e) => ids.includes(e.id)).map((e) => e.title)
  const preview = titles.slice(0, 5).join('、')
  const extra = titles.length > 5 ? ` 等 ${titles.length} 条` : ''
  const ok = await askConfirm({
    title: '删除选中条目',
    message: `确定删除 ${ids.length} 条：${preview}${extra}？材料文件也会一并删除，此操作不可恢复。`,
    confirmText: '删除选中',
    cancelText: '取消',
    danger: true,
  })
  if (!ok) return
  batchDeleting.value = true
  error.value = ''
  hint.value = ''
  try {
    for (const id of ids) {
      await api.deleteEntry(id)
    }
    selectedIds.value = []
    await load()
    hint.value = `已删除 ${ids.length} 条`
  } catch (err) {
    error.value = err.message
    await load()
  } finally {
    batchDeleting.value = false
  }
}

async function composeSelected() {
  const ids = selectedIds.value.filter((id) => selectableEntries.value.some((e) => e.id === id))
  if (!ids.length) {
    error.value = '所选条目均不齐套，无法合并导出'
    return
  }
  batchComposing.value = true
  error.value = ''
  try {
    const { blob, filename } = await api.composeBatch(ids)
    downloadBlob(blob, filename)
  } catch (err) {
    error.value = err.message
  } finally {
    batchComposing.value = false
  }
}

function openForm(g) {
  formGroupId.value = g.id
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
