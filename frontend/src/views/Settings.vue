<template>
  <div>
    <div class="page-head">
      <div>
        <h1>设置</h1>
        <p>槽位、分类关键词与拼版画板</p>
      </div>
    </div>

    <div class="settings-tabs" role="tablist">
      <button type="button" class="settings-tab" role="tab" :aria-selected="tab === 'slots'" :class="{ active: tab === 'slots' }" @click="tab = 'slots'">槽位</button>
      <button type="button" class="settings-tab" role="tab" :aria-selected="tab === 'layout'" :class="{ active: tab === 'layout' }" @click="tab = 'layout'">拼版</button>
      <button type="button" class="settings-tab" role="tab" :aria-selected="tab === 'keywords'" :class="{ active: tab === 'keywords' }" @click="tab = 'keywords'">分类关键词</button>
    </div>

    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="msg" class="okmsg">{{ msg }}</p>
    <div v-if="loading" class="meta">加载中…</div>

    <section v-show="!loading && tab === 'slots'" class="settings-panel card" role="tabpanel">
      <p class="meta settings-lead">全局一套槽位。发票是唯一特殊 PDF 槽；其它自定义槽一般为图片。删除仍有材料的槽位会被拒绝。</p>
      <div
        v-for="(slot, idx) in draftSlots"
        :key="slot.id + '-' + idx"
        class="slot-editor"
        :class="{ 'slot-color-open': colorMenuIdx === idx }"
      >
        <div class="slot-editor-head">
          <span class="slot-swatch" :style="{ background: slot.color }" />
          <strong>{{ slot.label || slot.id }}</strong>
          <span class="meta">{{ slot.file_kind === 'pdf' ? 'PDF' : '图片' }}{{ slot.special === 'invoice' ? ' · 发票' : '' }}{{ slot.required ? ' · 必填' : ' · 选填' }}</span>
          <label class="slot-required">
            <input v-model="slot.required" type="checkbox" :disabled="slot.special === 'invoice'" />
            必填（计入齐套）
          </label>
          <button v-if="slot.special !== 'invoice'" class="btn btn-sm btn-danger" type="button" @click="removeSlot(idx)">删除</button>
        </div>
        <div class="meta-grid slot-fields">
          <div class="field">
            <label>显示名</label>
            <input v-model="slot.label" maxlength="40" />
          </div>
          <div class="field">
            <label>ID</label>
            <input v-model="slot.id" :disabled="slot.special === 'invoice' || slot._locked" maxlength="32" />
          </div>
          <div class="field">
            <label>文件类型</label>
            <select v-model="slot.file_kind" :disabled="slot.special === 'invoice'">
              <option value="pdf">PDF</option>
              <option value="image">图片</option>
            </select>
          </div>
          <div class="field field-color">
            <label>颜色</label>
            <div class="color-dropdown">
              <button
                type="button"
                class="color-trigger"
                :aria-expanded="colorMenuIdx === idx"
                @click.stop="toggleColorMenu(idx)"
              >
                <span class="color-trigger-swatch" :style="{ background: slot.color }" />
                <span class="color-trigger-text">{{ slot.color }}</span>
                <span class="color-trigger-caret" aria-hidden="true">▾</span>
              </button>
              <div v-if="colorMenuIdx === idx" class="color-popover" @click.stop>
                <div class="color-popover-section">
                  <div class="color-popover-label">默认色卡</div>
                  <div class="color-swatch-row" role="listbox">
                    <button
                      v-for="c in presetColors"
                      :key="'p-' + idx + '-' + c"
                      type="button"
                      class="color-chip"
                      role="option"
                      :aria-selected="normColor(slot.color) === c"
                      :class="{ active: normColor(slot.color) === c }"
                      :style="{ background: c }"
                      :title="c"
                      @click="pickSlotColor(idx, c)"
                    />
                  </div>
                </div>
                <div v-if="customColors.length" class="color-popover-section">
                  <div class="color-popover-label">自定义色卡</div>
                  <div class="color-swatch-row" role="listbox">
                    <div v-for="c in customColors" :key="'c-' + idx + '-' + c" class="color-chip-wrap">
                      <button
                        type="button"
                        class="color-chip"
                        role="option"
                        :aria-selected="normColor(slot.color) === c"
                        :class="{ active: normColor(slot.color) === c }"
                        :style="{ background: c }"
                        :title="c"
                        @click="pickSlotColor(idx, c)"
                      />
                      <button
                        type="button"
                        class="color-chip-remove"
                        :title="`从色卡移除 ${c}`"
                        @click.stop="removeCustomColor(c)"
                      >×</button>
                    </div>
                  </div>
                </div>
                <button type="button" class="btn btn-sm color-popover-mix" @click="openMixerFor(idx)">调制新颜色…</button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="actions settings-actions">
        <button class="btn" type="button" @click="addSlot">添加图片槽位</button>
        <button class="btn btn-primary" type="button" :disabled="saving" @click="saveAll">{{ saving ? '保存中…' : '保存' }}</button>
        <button class="btn" type="button" :disabled="saving" @click="resetAll">恢复默认槽位与版式</button>
      </div>
    </section>

    <Teleport to="body">
      <div
        v-if="mixerOpen"
        class="modal-backdrop modal-backdrop-color-mixer"
        @click.self="closeMixer"
      >
        <div class="modal-card color-mixer-card" role="dialog" aria-modal="true" aria-labelledby="color-mixer-title">
          <div class="modal-head">
            <div>
              <h3 id="color-mixer-title" class="modal-title">调制新颜色</h3>
              <p class="modal-sub">调色后加入自定义色卡，供各槽位选用。</p>
            </div>
            <button class="btn btn-sm btn-ghost" type="button" @click="closeMixer">关闭</button>
          </div>
          <div class="color-mixer-body">
            <label class="color-mixer-preview" :style="{ background: mixerColor }">
              <input v-model="mixerColor" type="color" class="color-mixer-native" />
            </label>
            <div class="field color-mixer-hex-field">
              <label>色值</label>
              <input
                v-model="mixerHexInput"
                type="text"
                maxlength="7"
                spellcheck="false"
                placeholder="#3d5a80"
                @change="commitMixerHex"
                @keydown.enter.prevent="commitMixerHex"
              />
            </div>
          </div>
          <p v-if="mixerHint" class="meta color-mixer-hint">{{ mixerHint }}</p>
          <div class="modal-actions">
            <button class="btn" type="button" @click="closeMixer">取消</button>
            <button class="btn" type="button" @click="confirmMixer(false)">加入色卡</button>
            <button class="btn btn-primary" type="button" @click="confirmMixer(true)">加入并用于当前槽位</button>
          </div>
        </div>
      </div>
    </Teleport>

    <section v-show="!loading && tab === 'layout'" class="settings-panel card" role="tabpanel">
      <p class="meta settings-lead">多页 A4 画板。左侧色板：浅色=未放入，实心=已放入。同一槽位可摆多次。必填槽未放入时无法导出。</p>
      <div class="layout-workspace">
        <aside class="layout-palette">
          <h3>槽位</h3>
          <button
            v-for="slot in draftSlots"
            :key="slot.id"
            type="button"
            class="palette-item"
            :class="{ placed: placedIds.has(slot.id) }"
            :style="{ '--slot-color': slot.color }"
            @click="addRegion(slot.id)"
          >
            <span class="palette-dot" />
            <span>{{ slot.label }}</span>
            <span class="meta">{{ placedIds.has(slot.id) ? '已放入' : '未放入' }}</span>
          </button>
          <p class="meta">点击槽位可在当前页添加一个框</p>
        </aside>
        <div class="layout-main">
          <div class="layout-toolbar">
            <button class="btn btn-sm" type="button" :disabled="pageIdx <= 0" @click="pageIdx--">上一页</button>
            <span class="meta">第 {{ pageIdx + 1 }} / {{ draftLayout.pages.length }} 页</span>
            <button class="btn btn-sm" type="button" :disabled="pageIdx >= draftLayout.pages.length - 1" @click="pageIdx++">下一页</button>
            <button class="btn btn-sm" type="button" @click="addPage">加页</button>
            <button class="btn btn-sm btn-danger" type="button" :disabled="draftLayout.pages.length <= 1" @click="removePage">删本页</button>
            <button class="btn btn-sm" type="button" @click="resetLayoutOnly">恢复默认版式</button>
          </div>
          <div
            ref="boardEl"
            class="layout-board"
            @pointermove="onPointerMove"
            @pointerup="onPointerUp"
            @pointerleave="onPointerUp"
          >
            <div
              v-for="(region, rIdx) in currentRegions"
              :key="rIdx"
              class="layout-region"
              :class="{ active: selectedIdx === rIdx }"
              :style="regionStyle(region)"
              @pointerdown.stop="startDrag($event, rIdx)"
            >
              <span class="layout-region-label">{{ labelOf(region.slot_id) }}</span>
              <button type="button" class="layout-region-del" @click.stop="removeRegion(rIdx)">×</button>
              <span class="layout-handle" @pointerdown.stop="startResize($event, rIdx)" />
            </div>
          </div>
          <div class="actions settings-actions">
            <button class="btn btn-primary" type="button" :disabled="saving" @click="saveAll">{{ saving ? '保存中…' : '保存版式' }}</button>
          </div>
        </div>
      </div>
    </section>

    <section v-show="!loading && tab === 'keywords'" class="settings-panel card" role="tabpanel">
      <p class="meta settings-lead">批量上传时按关键词匹配槽位。正文命中权重高于文件名。</p>
      <div v-for="slot in draftSlots" :key="'kw-' + slot.id" class="keyword-block">
        <div class="keyword-block-head">
          <h3>{{ slot.label }}</h3>
          <span class="meta">{{ (slot.keywords || []).length }} 个词</span>
        </div>
        <div class="keyword-chips">
          <span v-for="(word, idx) in slot.keywords" :key="slot.id + '-' + idx + '-' + word" class="keyword-chip">
            {{ word }}
            <button type="button" class="keyword-chip-remove" @click="slot.keywords.splice(idx, 1)">×</button>
          </span>
          <span v-if="!(slot.keywords || []).length" class="meta">暂无关键词</span>
        </div>
        <div class="keyword-add">
          <input v-model="kwInputs[slot.id]" type="text" :placeholder="`添加「${slot.label}」关键词`" @keydown.enter.prevent="addKeyword(slot)" />
          <button class="btn btn-sm" type="button" @click="addKeyword(slot)">添加</button>
        </div>
      </div>
      <div class="actions settings-actions">
        <button class="btn btn-primary" type="button" :disabled="saving" @click="saveAll">{{ saving ? '保存中…' : '保存' }}</button>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '../api/client'
import { loadSlots } from '../composables/useSlots'

const route = useRoute()
const tab = ref(route.query.tab === 'layout' ? 'layout' : route.query.tab === 'keywords' ? 'keywords' : 'slots')
const loading = ref(true)
const saving = ref(false)
const error = ref('')
const msg = ref('')
const draftSlots = ref([])
const draftLayout = ref({ pages: [{ regions: [] }] })
const presetColors = ref([
  '#163a7a',
  '#2a6b4a',
  '#8a5a12',
  '#6b3fa0',
  '#a11f2c',
  '#1a6a8c',
  '#5c4a12',
  '#3d5a80',
])
const customColors = ref([])
const mixerColor = ref('#3d5a80')
const mixerHexInput = ref('#3d5a80')
const mixerOpen = ref(false)
const mixerHint = ref('')
const activeSlotIdx = ref(0)
const colorMenuIdx = ref(-1)
const kwInputs = reactive({})
const pageIdx = ref(0)
const selectedIdx = ref(-1)
const boardEl = ref(null)
const drag = ref(null)

const currentRegions = computed(() => draftLayout.value.pages[pageIdx.value]?.regions || [])
const placedIds = computed(() => {
  const ids = new Set()
  for (const page of draftLayout.value.pages || []) {
    for (const r of page.regions || []) if (r.slot_id) ids.add(r.slot_id)
  }
  return ids
})

watch(mixerColor, (v) => {
  const c = normColor(v)
  if (c) mixerHexInput.value = c
})

function normColor(raw) {
  const c = String(raw || '').trim().toLowerCase()
  if (/^#[0-9a-f]{6}$/.test(c)) return c
  if (/^#[0-9a-f]{3}$/.test(c)) return `#${c[1]}${c[1]}${c[2]}${c[2]}${c[3]}${c[3]}`
  return ''
}

function toggleColorMenu(idx) {
  colorMenuIdx.value = colorMenuIdx.value === idx ? -1 : idx
  if (colorMenuIdx.value === idx) activeSlotIdx.value = idx
}

function pickSlotColor(idx, color) {
  const c = normColor(color)
  if (!c || !draftSlots.value[idx]) return
  draftSlots.value[idx].color = c
  activeSlotIdx.value = idx
  colorMenuIdx.value = -1
}

function openMixerFor(idx) {
  const i = Number.isInteger(idx) ? idx : activeSlotIdx.value
  activeSlotIdx.value = Math.max(0, Math.min(i, Math.max(0, draftSlots.value.length - 1)))
  colorMenuIdx.value = -1
  const seed = draftSlots.value[activeSlotIdx.value]?.color || mixerColor.value || '#3d5a80'
  const color = normColor(seed) || '#3d5a80'
  mixerColor.value = color
  mixerHexInput.value = color
  mixerHint.value = ''
  mixerOpen.value = true
}

function closeMixer() {
  mixerOpen.value = false
  mixerHint.value = ''
}

function commitMixerHex() {
  let raw = String(mixerHexInput.value || '').trim()
  if (!raw) {
    mixerHexInput.value = mixerColor.value
    return true
  }
  if (!raw.startsWith('#')) raw = `#${raw}`
  const color = normColor(raw)
  if (!color) {
    mixerHint.value = '请输入有效的十六进制色值，例如 #3d5a80'
    return false
  }
  mixerColor.value = color
  mixerHexInput.value = color
  mixerHint.value = ''
  return true
}

function onDocPointerDown(ev) {
  if (mixerOpen.value) return
  if (colorMenuIdx.value < 0) return
  const t = ev.target
  if (t && typeof t.closest === 'function' && t.closest('.color-dropdown')) return
  colorMenuIdx.value = -1
}

function onDocKeydown(ev) {
  if (ev.key !== 'Escape') return
  if (mixerOpen.value) {
    closeMixer()
    return
  }
  colorMenuIdx.value = -1
}

function labelOf(id) {
  return draftSlots.value.find((s) => s.id === id)?.label || id
}

function regionStyle(region) {
  const slot = draftSlots.value.find((s) => s.id === region.slot_id)
  return {
    left: `${region.x * 100}%`,
    top: `${region.y * 100}%`,
    width: `${region.w * 100}%`,
    height: `${region.h * 100}%`,
    borderColor: slot?.color || '#163a7a',
    background: `${slot?.color || '#163a7a'}22`,
  }
}

function cloneSettings(res) {
  draftSlots.value = (res.slots || []).map((s) => ({
    ...s,
    keywords: [...(s.keywords || [])],
    _locked: ['invoice', 'order', 'payment'].includes(s.id),
  }))
  draftLayout.value = JSON.parse(JSON.stringify(res.layout || { pages: [{ regions: [] }] }))
  if (!draftLayout.value.pages?.length) draftLayout.value.pages = [{ regions: [] }]
  pageIdx.value = Math.min(pageIdx.value, draftLayout.value.pages.length - 1)
  presetColors.value = (res.preset_colors || []).length ? [...res.preset_colors] : [...presetColors.value]
  customColors.value = [...(res.custom_colors || [])]
  activeSlotIdx.value = Math.min(activeSlotIdx.value, Math.max(0, draftSlots.value.length - 1))
  for (const s of draftSlots.value) {
    if (!(s.id in kwInputs)) kwInputs[s.id] = ''
  }
}

function addCustomColor(applyToActive = false) {
  if (!commitMixerHex()) return false
  const color = normColor(mixerColor.value)
  if (!color) {
    mixerHint.value = '请选择或输入有效颜色'
    return false
  }
  const preset = new Set(presetColors.value.map(normColor))
  if (preset.has(color)) {
    mixerHint.value = '该色已在默认色卡中，无需加入自定义色卡'
    if (applyToActive) {
      applyColorToActive(color)
      return true
    }
    return false
  }
  if (!customColors.value.includes(color)) {
    if (customColors.value.length >= 24) {
      mixerHint.value = '自定义色卡最多 24 色'
      error.value = '自定义色卡最多 24 色'
      return false
    }
    customColors.value.push(color)
  }
  if (applyToActive) applyColorToActive(color)
  error.value = ''
  mixerHint.value = ''
  return true
}

function confirmMixer(applyToActive = false) {
  if (addCustomColor(applyToActive)) closeMixer()
}

function removeCustomColor(color) {
  const c = normColor(color)
  customColors.value = customColors.value.filter((x) => x !== c)
}

function applyColorToActive(color) {
  const c = normColor(color)
  if (!c || !draftSlots.value.length) return
  let idx = activeSlotIdx.value
  if (idx < 0 || idx >= draftSlots.value.length) idx = 0
  draftSlots.value[idx].color = c
  activeSlotIdx.value = idx
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const res = await api.getSettings()
    cloneSettings(res)
    await loadSlots(true)
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

function addSlot() {
  const n = draftSlots.value.length + 1
  const id = `slot_${n}`
  const color = presetColors.value[(n - 1) % presetColors.value.length] || '#3d5a80'
  draftSlots.value.push({
    id,
    label: `自定义${n}`,
    file_kind: 'image',
    required: false,
    special: null,
    color,
    keywords: [],
  })
  activeSlotIdx.value = draftSlots.value.length - 1
  kwInputs[id] = ''
}

function removeSlot(idx) {
  const slot = draftSlots.value[idx]
  if (!slot || slot.special === 'invoice') return
  draftSlots.value.splice(idx, 1)
  for (const page of draftLayout.value.pages) {
    page.regions = page.regions.filter((r) => r.slot_id !== slot.id)
  }
  if (activeSlotIdx.value >= draftSlots.value.length) {
    activeSlotIdx.value = Math.max(0, draftSlots.value.length - 1)
  } else if (activeSlotIdx.value > idx) {
    activeSlotIdx.value -= 1
  }
  if (colorMenuIdx.value === idx) colorMenuIdx.value = -1
  else if (colorMenuIdx.value > idx) colorMenuIdx.value -= 1
}

function addKeyword(slot) {
  const word = (kwInputs[slot.id] || '').trim()
  if (!word) return
  if (!slot.keywords.includes(word)) slot.keywords.push(word)
  kwInputs[slot.id] = ''
}

function addPage() {
  draftLayout.value.pages.push({ regions: [] })
  pageIdx.value = draftLayout.value.pages.length - 1
}

function removePage() {
  if (draftLayout.value.pages.length <= 1) return
  draftLayout.value.pages.splice(pageIdx.value, 1)
  pageIdx.value = Math.max(0, pageIdx.value - 1)
}

function addRegion(slotId) {
  const page = draftLayout.value.pages[pageIdx.value]
  if (!page) return
  page.regions.push({ slot_id: slotId, x: 0.08, y: 0.08, w: 0.35, h: 0.28 })
  selectedIdx.value = page.regions.length - 1
}

function removeRegion(idx) {
  currentRegions.value.splice(idx, 1)
  selectedIdx.value = -1
}

function startDrag(ev, idx) {
  selectedIdx.value = idx
  const region = currentRegions.value[idx]
  const rect = boardEl.value.getBoundingClientRect()
  drag.value = {
    mode: 'move',
    idx,
    startX: ev.clientX,
    startY: ev.clientY,
    ox: region.x,
    oy: region.y,
    ow: region.w,
    oh: region.h,
    bw: rect.width,
    bh: rect.height,
  }
  ev.currentTarget.setPointerCapture?.(ev.pointerId)
}

function startResize(ev, idx) {
  selectedIdx.value = idx
  const region = currentRegions.value[idx]
  const rect = boardEl.value.getBoundingClientRect()
  drag.value = {
    mode: 'resize',
    idx,
    startX: ev.clientX,
    startY: ev.clientY,
    ox: region.x,
    oy: region.y,
    ow: region.w,
    oh: region.h,
    bw: rect.width,
    bh: rect.height,
  }
}

function onPointerMove(ev) {
  if (!drag.value) return
  const d = drag.value
  const region = currentRegions.value[d.idx]
  if (!region) return
  const dx = (ev.clientX - d.startX) / d.bw
  const dy = (ev.clientY - d.startY) / d.bh
  if (d.mode === 'move') {
    region.x = Math.max(0, Math.min(1 - region.w, d.ox + dx))
    region.y = Math.max(0, Math.min(1 - region.h, d.oy + dy))
  } else {
    region.w = Math.max(0.04, Math.min(1 - region.x, d.ow + dx))
    region.h = Math.max(0.04, Math.min(1 - region.y, d.oh + dy))
  }
}

function onPointerUp() {
  drag.value = null
}

async function saveAll() {
  saving.value = true
  error.value = ''
  msg.value = ''
  try {
    const payload = {
      slots: draftSlots.value.map(({ _locked, ...s }) => ({
        id: String(s.id || '').trim().toLowerCase(),
        label: s.label,
        file_kind: s.file_kind,
        required: !!s.required,
        special: s.special || null,
        color: s.color,
        keywords: [...(s.keywords || [])],
      })),
      layout: JSON.parse(JSON.stringify(draftLayout.value)),
      custom_colors: [...customColors.value],
    }
    const res = await api.updateSettings(payload)
    cloneSettings(res)
    await loadSlots(true)
    msg.value = '已保存'
  } catch (e) {
    error.value = e.message
  } finally {
    saving.value = false
  }
}

async function resetAll() {
  saving.value = true
  error.value = ''
  msg.value = ''
  try {
    const res = await api.resetClassifyKeywords()
    cloneSettings(res)
    await loadSlots(true)
    msg.value = '已恢复默认槽位与版式'
  } catch (e) {
    error.value = e.message
  } finally {
    saving.value = false
  }
}

async function resetLayoutOnly() {
  saving.value = true
  error.value = ''
  msg.value = ''
  try {
    const res = await api.resetLayout()
    cloneSettings(res)
    await loadSlots(true)
    msg.value = '已恢复默认版式'
  } catch (e) {
    error.value = e.message
  } finally {
    saving.value = false
  }
}

watch(
  () => route.query.tab,
  (v) => {
    if (v === 'layout' || v === 'keywords' || v === 'slots') tab.value = v
  },
)

onMounted(() => {
  load()
  document.addEventListener('pointerdown', onDocPointerDown)
  document.addEventListener('keydown', onDocKeydown)
})
onUnmounted(() => {
  document.removeEventListener('pointerdown', onDocPointerDown)
  document.removeEventListener('keydown', onDocKeydown)
})
</script>
