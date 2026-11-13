<script setup>
import { onMounted, onBeforeUnmount, ref, computed } from 'vue'
import { api, isImageMaterial } from '../api/client'
import MaterialPreview from '../components/MaterialPreview.vue'

const items = ref([])
const loading = ref(false)
const err = ref('')
const selectedId = ref(null)
const search = ref('')
const reAnalyzing = ref(false)
const reAnalyzeMsg = ref('')
let pollTimer = null

async function load() {
  loading.value = true
  err.value = ''
  try {
    const res = await api.inspectMaterials()
    items.value = res.items || []
  } catch (e) {
    err.value = e.message || String(e)
  } finally {
    loading.value = false
  }
}

const filtered = computed(() => {
  const q = search.value.trim().toLowerCase()
  if (!q) return items.value
  return items.value.filter(
    (it) =>
      (it.original_name || '').toLowerCase().includes(q) ||
      (it.features?.merchant || '').toLowerCase().includes(q) ||
      (it.features?.invoice_number || '').includes(q) ||
      (it.features?.order_no || '').toLowerCase().includes(q)
  )
})

const selected = computed(() => items.value.find((x) => x.id === selectedId.value) || null)

const feat = computed(() => selected.value?.features || null)
const ocrLines = computed(() => feat.value?.ocr_lines || [])
const textSource = computed(() => feat.value?.text_source || 'none')

function fmtSource(s) {
  if (s === 'pdf') return '📄 PDF 文本层'
  if (s === 'ocr') return '🔤 OCR'
  if (s === 'filename') return '📝 文件名'
  return '—'
}

async function triggerReAnalyze() {
  if (!selected.value) return
  if (reAnalyzing.value) return
  reAnalyzing.value = true
  reAnalyzeMsg.value = '识别中…'
  try {
    await api.reAnalyzeMaterial(selected.value.id)
    // Poll: re-fetch list every 1.2s until analyze_status != 'pending'
    let attempts = 0
    const maxAttempts = 30 // ~36s
    pollTimer = setInterval(async () => {
      attempts++
      try {
        const res = await api.inspectMaterials()
        items.value = res.items || []
        const cur = items.value.find((x) => x.id === selected.value.id)
        if (!cur || cur.analyze_status !== 'pending') {
          clearInterval(pollTimer)
          pollTimer = null
          reAnalyzing.value = false
          if (cur?.analyze_status === 'done') {
            reAnalyzeMsg.value = '✅ 完成'
            setTimeout(() => (reAnalyzeMsg.value = ''), 2500)
          } else if (cur) {
            reAnalyzeMsg.value = `状态: ${cur.analyze_status}`
            setTimeout(() => (reAnalyzeMsg.value = ''), 2500)
          }
        } else if (attempts >= maxAttempts) {
          clearInterval(pollTimer)
          pollTimer = null
          reAnalyzing.value = false
          reAnalyzeMsg.value = '⏱️ 超时，刷新查看结果'
        }
      } catch {
        // swallow transient poll errors
      }
    }, 1200)
  } catch (e) {
    reAnalyzing.value = false
    reAnalyzeMsg.value = '❌ 提交失败: ' + (e.message || e)
  }
}

onBeforeUnmount(() => { if (pollTimer) clearInterval(pollTimer) })

function rowSourceTag(s) {
  if (s === 'pdf') return '📄'
  if (s === 'ocr') return '🔤'
  return '·'
}

function previewKind(it) {
  if (it.original_name && /\.pdf$/i.test(it.original_name)) return 'pdf'
  return 'image'
}

function previewUrl(it) {
  return api.materialFileUrl(it.id)
}

function scoreColor(s) {
  if (s == null) return 'var(--muted)'
  if (s >= 0.9) return 'var(--ok)'
  if (s >= 0.75) return 'var(--warn)'
  return 'var(--err)'
}

// Full concatenated text — shows the EXACT input fed to extract_features
const fullText = computed(() => {
  if (!ocrLines.value.length) return ''
  return ocrLines.value.map((l) => l.text).join('\n')
})

// Highlight which rows contributed to each extracted field.
// Substring-match the field value against each row text.
const fieldMap = computed(() => {
  if (!feat.value) return []
  const fields = [
    { key: 'amount', label: '金额', val: feat.value.amount, hint: 'amount.py 正则 + 文件名兜底' },
    { key: 'merchant', label: '商家', val: feat.value.merchant, hint: '_extract_merchant()' },
    { key: 'product_name', label: '商品/项目', val: feat.value.product_name, hint: '_extract_product_name()' },
    { key: 'date', label: '日期', val: feat.value.date, hint: '_extract_date()' },
    { key: 'order_no', label: '订单号', val: feat.value.order_no, hint: '_extract_order_no()' },
    { key: 'invoice_number', label: '发票号码', val: feat.value.invoice_number, hint: '_extract_invoice_number()' },
    { key: 'invoice_code', label: '发票代码', val: feat.value.invoice_code, hint: '_extract_invoice_code()' },
  ]
  return fields.map((f) => {
    const hits = []
    if (f.val) {
      const needle = String(f.val).replace(/\s+/g, '')
      if (needle) {
        ocrLines.value.forEach((line, idx) => {
          const compact = line.text.replace(/\s+/g, '')
          if (compact.includes(needle)) hits.push(idx)
        })
      }
    }
    return { ...f, hits }
  })
})

// When user clicks a field card → highlight the matching rows
const highlightRowIdx = ref(null)
function highlightField(field) {
  if (!field.hits.length) return
  highlightRowIdx.value = field.hits[0]
}

onMounted(load)
</script>

<template>
  <div class="page inspect-page">
    <header class="page-head">
      <h2>识别检查</h2>
      <p>查看每份材料的 OCR 原始行与提取到的字段。<br />
         提示：历史材料没有 OCR 原始行（当时没存），重新整理一次后就会有。</p>
      <div class="page-head-actions">
        <input v-model="search" placeholder="🔍 搜索文件名 / 商家 / 发票号 / 订单号" class="inspect-search" />
        <button @click="load" class="btn">刷新列表</button>
        <button
          @click="triggerReAnalyze"
          :disabled="!selected || reAnalyzing"
          class="btn btn-primary"
          :title="selected ? `对「${selected.original_name}」重新识别` : '先选一份材料'"
        >
          {{ reAnalyzing ? '识别中…' : '🔄 重新识别' }}
        </button>
        <span v-if="reAnalyzeMsg" class="reanalyze-msg">{{ reAnalyzeMsg }}</span>
      </div>
    </header>

    <div class="inspect-body">
      <!-- Left: material list -->
      <aside class="inspect-list">
        <div v-if="loading" class="inspect-empty">加载中…</div>
        <div v-else-if="err" class="inspect-empty err">❌ {{ err }}</div>
        <div v-else-if="filtered.length === 0" class="inspect-empty">没有材料</div>
        <ul v-else>
          <li
            v-for="it in filtered"
            :key="it.id"
            :class="{ active: it.id === selectedId }"
            @click="selectedId = it.id"
          >
            <div class="li-name" :title="it.original_name">{{ it.original_name || '(未命名)' }}</div>
            <div class="li-meta">
              <span class="tag tag-type">{{ it.type }}</span>
              <span v-if="it.entry_id" class="tag">条目 #{{ it.entry_id }}</span>
              <span class="tag" :class="'src-' + (it.features?.text_source || 'none')">
                {{ fmtSource(it.features?.text_source) }}
              </span>
              <span v-if="it.features?.amount != null" class="li-amount">¥{{ it.features.amount.toFixed(2) }}</span>
              <span v-if="!it.features" class="tag">未分析</span>
            </div>
            <div v-if="it.features?.merchant" class="li-merchant">{{ it.features.merchant }}</div>
          </li>
        </ul>
      </aside>

      <!-- Right: detail -->
      <section v-if="selected" class="inspect-detail">
        <!-- Top: field extraction summary -->
        <div class="panel field-panel">
          <h3>抽取字段 <span class="muted small">（点击字段卡 → 高亮来源行；点击行 → 反向定位字段）</span></h3>
          <div class="field-grid">
            <div
              v-for="f in fieldMap"
              :key="f.key"
              class="field-item"
              :class="{ ok: f.val, miss: !f.val, clickable: f.hits.length }"
              @click="highlightField(f)"
            >
              <div class="field-label">{{ f.label }}</div>
              <div class="field-value" :title="f.hint">
                {{ f.val ?? '—' }}
              </div>
              <div class="field-hits small muted">
                <template v-if="f.hits.length === 0 && f.val">⚠️ 未在行文本中找到命中（可能来自文件名兜底）</template>
                <template v-else-if="f.hits.length">命中行 #{{ f.hits.map(i => i + 1).join(', #') }}</template>
                <template v-else>—</template>
              </div>
            </div>
          </div>
          <div class="field-meta small muted">
            text_source: {{ textSource }} · ocr_used: {{ feat?.ocr_used }} · stored: {{ selected.stored_path }}
          </div>
        </div>

        <div class="inspect-columns">
          <!-- Unified rows panel (PDF 文本层 / OCR / 混排) -->
          <div class="panel rows-panel">
            <h3>
              原始提取行
              <span class="muted small">
                共 {{ ocrLines.length }} 行
                <template v-if="ocrLines.some(l => l.source === 'pdf')"> · 📄 PDF文本 {{ ocrLines.filter(l => l.source === 'pdf').length }}</template>
                <template v-if="ocrLines.some(l => l.source === 'ocr')"> · 🔤 OCR {{ ocrLines.filter(l => l.source === 'ocr').length }}</template>
              </span>
            </h3>
            <div v-if="ocrLines.length === 0" class="muted small">
              该材料没有保存原始行。旧版识别不会存。<br />
              重新在收件箱整理或在详情页「重新识别」后就会有。
            </div>
            <ul v-else class="ocr-rows">
              <li
                v-for="(row, idx) in ocrLines"
                :key="idx"
                class="ocr-row"
                :class="{
                  'src-pdf': row.source === 'pdf',
                  'src-ocr': row.source === 'ocr',
                  highlighted: highlightRowIdx === idx,
                }"
                @click="highlightRowIdx = idx"
              >
                <span class="ocr-idx">{{ String(idx + 1).padStart(2, '0') }}</span>
                <span class="ocr-src">{{ rowSourceTag(row.source) }}</span>
                <span class="ocr-text">{{ row.text }}</span>
                <span v-if="row.score != null" class="ocr-score" :style="{ color: scoreColor(row.score) }">
                  {{ (row.score * 100).toFixed(1) }}%
                </span>
                <span v-else class="ocr-score muted">—</span>
              </li>
            </ul>
          </div>

          <!-- Right column: fulltext + preview -->
          <div class="inspect-right">
            <div class="panel fulltext-panel">
              <h3>拼接全文 <span class="muted small">（extract_features 的 text 入参，{{ fullText.length }} 字）</span></h3>
              <pre class="fulltext">{{ fullText || '(无)' }}</pre>
            </div>
            <div class="panel preview-panel">
              <h3>原图预览</h3>
              <MaterialPreview
                :url="previewUrl(selected)"
                :kind="previewKind(selected)"
                mode="fit"
              />
              <div class="preview-meta small muted">
                type: {{ selected.type }} · id: {{ selected.id }}
              </div>
            </div>
          </div>
        </div>
      </section>

      <section v-else class="inspect-detail inspect-empty">
        <div class="empty-center">
          <div class="big">👈 选择左侧一份材料</div>
          <div class="muted">查看 OCR 原始行、字段抽取结果、以及原图预览</div>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.inspect-page {
  padding: 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}
.page-head h2 { margin: 0 0 0.25rem; }
.page-head p { margin: 0.25rem 0 0.75rem; font-size: 0.8rem; color: var(--muted); }
.page-head-actions { display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap; }
.page-head-actions .btn-primary {
  background: var(--accent, #4a6fd1);
  color: #fff;
  border-color: var(--accent, #4a6fd1);
}
.page-head-actions .btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.reanalyze-msg {
  font-size: 0.78rem;
  padding: 0 0.3rem;
  color: var(--muted);
}
.inspect-search {
  flex: 1;
  min-width: 12rem;
  padding: 0.4rem 0.6rem;
  border: 1px solid var(--border);
  border-radius: 6px;
  font-size: 0.85rem;
  background: var(--bg-card);
}

.inspect-body {
  display: grid;
  grid-template-columns: 22rem 1fr;
  gap: 1rem;
  min-height: 60vh;
  max-height: calc(100vh - 10rem);
}

/* List */
.inspect-list {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow-y: auto;
}
.inspect-list ul { list-style: none; padding: 0; margin: 0; }
.inspect-list li {
  padding: 0.6rem 0.8rem;
  border-bottom: 1px solid var(--border);
  cursor: pointer;
  transition: background 0.15s;
}
.inspect-list li:hover { background: var(--bg-hover, #f0f1f4); }
.inspect-list li.active { background: var(--accent, #4a6fd1); color: #fff; }
.inspect-list li.active .li-merchant,
.inspect-list li.active .tag { color: #fff !important; opacity: 0.9; }

.li-name { font-weight: 500; font-size: 0.88rem; word-break: break-all; }
.li-meta { display: flex; flex-wrap: wrap; gap: 0.25rem; margin-top: 0.25rem; }
.li-meta .tag { font-size: 0.68rem; padding: 0.1rem 0.35rem; background: var(--bg-muted, #eef0f4); border-radius: 3px; color: var(--muted); }
.li-meta .tag-type { background: var(--accent-soft, #dbe5fb); color: var(--accent); }
.li-meta .tag.src-ocr { background: #e6f3ea; color: #2d7a46; }
.li-meta .tag.src-pdf { background: #f1e9d7; color: #8a6a1f; }
.li-meta .tag.src-none { background: #eee; color: #999; }
.li-amount { margin-left: auto; font-weight: 600; font-size: 0.85rem; color: var(--err); }
.li-merchant { font-size: 0.78rem; color: var(--muted); margin-top: 0.15rem; }

.inspect-empty {
  padding: 1rem;
  color: var(--muted);
  text-align: center;
}
.inspect-empty.err { color: var(--err); }

/* Detail */
.inspect-detail {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  overflow-y: auto;
  min-width: 0;
}
.panel {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 0.75rem 1rem;
}
.panel h3 { margin: 0 0 0.5rem; font-size: 0.9rem; }

.field-panel { flex: 0 0 auto; }
.field-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(13rem, 1fr));
  gap: 0.5rem;
}
.field-item {
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 0.45rem 0.6rem;
  background: var(--bg-muted, #f7f8fb);
}
.field-item.ok { border-color: var(--ok, #2da866); }
.field-item.miss { border-color: var(--err, #c64545); background: #fbe9e9; }
.field-label { font-size: 0.7rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px; }
.field-value { font-size: 0.95rem; font-weight: 600; color: var(--text); word-break: break-all; }
.field-item.miss .field-value { color: var(--err); }
.field-hits { margin-top: 0.2rem; }
.field-meta { margin-top: 0.5rem; border-top: 1px dashed var(--border); padding-top: 0.4rem; }

.inspect-columns {
  display: grid;
  grid-template-columns: 1.5fr 1fr;
  gap: 0.75rem;
}

.rows-panel { overflow: hidden; display: flex; flex-direction: column; }
.ocr-rows {
  list-style: none; padding: 0; margin: 0;
  max-height: 360px; overflow-y: auto;
}
.ocr-row {
  display: grid;
  grid-template-columns: 2rem 1.6rem 1fr 4.5rem;
  gap: 0.4rem;
  padding: 0.25rem 0.4rem;
  border-bottom: 1px solid var(--border);
  font-family: ui-monospace, Consolas, monospace;
  font-size: 0.82rem;
  cursor: pointer;
  transition: background 0.1s;
  align-items: baseline;
}
.ocr-row:hover { background: var(--bg-hover, #f0f1f4); }
.ocr-row.highlighted { background: #fff4c2; border-left: 3px solid #f5a623; padding-left: 0.25rem; }
.ocr-row.src-pdf { background: #fbf7f0; }
.ocr-row.src-pdf.highlighted { background: #fff4c2; }
.ocr-row.src-ocr .ocr-src { color: #2d7a46; }
.ocr-row.src-pdf .ocr-src { color: #8a6a1f; }
.ocr-idx { color: var(--muted); text-align: right; user-select: none; }
.ocr-src { text-align: center; font-size: 0.85rem; }
.ocr-text { word-break: break-all; min-width: 0; }
.ocr-score { text-align: right; font-size: 0.75rem; }

.inspect-right {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.fulltext-panel { display: flex; flex-direction: column; }
.fulltext {
  background: var(--bg-muted, #f7f8fb);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 0.5rem;
  margin: 0;
  font-family: ui-monospace, Consolas, monospace;
  font-size: 0.8rem;
  max-height: 200px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-all;
  line-height: 1.5;
}

.preview-panel { display: flex; flex-direction: column; }
.preview-panel :deep(.material-preview-root) {
  min-height: 240px;
  max-height: 420px;
  overflow: auto;
}
.preview-meta { margin-top: 0.4rem; border-top: 1px dashed var(--border); padding-top: 0.4rem; }

.empty-center { display: flex; flex-direction: column; justify-content: center; align-items: center; min-height: 300px; gap: 0.5rem; }
.empty-center .big { font-size: 1.1rem; }

.field-item.clickable { cursor: pointer; transition: transform 0.1s, box-shadow 0.15s; }
.field-item.clickable:hover { transform: translateY(-1px); box-shadow: 0 2px 6px rgba(0,0,0,0.08); }

@media (max-width: 960px) {
  .inspect-body { grid-template-columns: 1fr; }
  .inspect-columns { grid-template-columns: 1fr; }
}
</style>
