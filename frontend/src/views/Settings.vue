<template>
  <div>
    <div class="page-head">
      <div>
        <h1>设置</h1>
        <p>界面偏好与默认配置</p>
      </div>
    </div>

    <div class="settings-tabs" role="tablist">
      <button
        type="button"
        class="settings-tab"
        role="tab"
        :aria-selected="tab === 'keywords'"
        :class="{ active: tab === 'keywords' }"
        @click="tab = 'keywords'"
      >
        分类关键词
      </button>
    </div>

    <section v-show="tab === 'keywords'" class="settings-panel card" role="tabpanel">
      <p class="meta settings-lead">
        批量上传判定材料类型时，会在 PDF 文本 / OCR 结果与文件名中匹配这些词。正文命中权重高于文件名。保存后立即生效。
      </p>
      <p v-if="error" class="error">{{ error }}</p>
      <p v-if="msg" class="okmsg">{{ msg }}</p>

      <div v-if="loading" class="meta">加载中…</div>
      <template v-else>
        <div v-for="kind in kinds" :key="kind.key" class="keyword-block">
          <div class="keyword-block-head">
            <h3>{{ kind.label }}</h3>
            <span class="meta">{{ draft[kind.key].length }} 个词</span>
          </div>
          <div class="keyword-chips">
            <span v-for="(word, idx) in draft[kind.key]" :key="`${kind.key}-${idx}-${word}`" class="keyword-chip">
              {{ word }}
              <button type="button" class="keyword-chip-remove" :aria-label="`删除 ${word}`" @click="removeWord(kind.key, idx)">
                ×
              </button>
            </span>
            <span v-if="!draft[kind.key].length" class="meta">暂无关键词</span>
          </div>
          <div class="keyword-add">
            <input
              v-model="inputs[kind.key]"
              type="text"
              :placeholder="`添加「${kind.label}」关键词，回车确认`"
              @keydown.enter.prevent="addWord(kind.key)"
            />
            <button class="btn btn-sm" type="button" @click="addWord(kind.key)">添加</button>
          </div>
        </div>

        <div class="actions settings-actions">
          <button class="btn btn-primary" type="button" :disabled="saving" @click="save">
            {{ saving ? '保存中…' : '保存' }}
          </button>
          <button class="btn" type="button" :disabled="saving" @click="resetDefaults">恢复默认</button>
        </div>
      </template>
    </section>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { api } from '../api/client'

const tab = ref('keywords')
const loading = ref(true)
const saving = ref(false)
const error = ref('')
const msg = ref('')

const kinds = [
  { key: 'invoice', label: '发票' },
  { key: 'order', label: '订单截图' },
  { key: 'payment', label: '支付记录' },
]

const draft = reactive({
  invoice: [],
  order: [],
  payment: [],
})
const inputs = reactive({
  invoice: '',
  order: '',
  payment: '',
})

function applyKeywords(kw) {
  draft.invoice = [...(kw?.invoice || [])]
  draft.order = [...(kw?.order || [])]
  draft.payment = [...(kw?.payment || [])]
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const res = await api.getSettings()
    applyKeywords(res.classify_keywords)
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

function addWord(kind) {
  const word = (inputs[kind] || '').trim()
  if (!word) return
  if (draft[kind].includes(word)) {
    inputs[kind] = ''
    return
  }
  draft[kind].push(word)
  inputs[kind] = ''
  msg.value = ''
}

function removeWord(kind, idx) {
  draft[kind].splice(idx, 1)
  msg.value = ''
}

async function save() {
  saving.value = true
  error.value = ''
  msg.value = ''
  try {
    const res = await api.updateSettings({
      classify_keywords: {
        invoice: [...draft.invoice],
        order: [...draft.order],
        payment: [...draft.payment],
      },
    })
    applyKeywords(res.classify_keywords)
    msg.value = '已保存'
  } catch (e) {
    error.value = e.message
  } finally {
    saving.value = false
  }
}

async function resetDefaults() {
  saving.value = true
  error.value = ''
  msg.value = ''
  try {
    const res = await api.resetClassifyKeywords()
    applyKeywords(res.classify_keywords)
    msg.value = '已恢复默认关键词'
  } catch (e) {
    error.value = e.message
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>
