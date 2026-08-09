<template>
  <div>
    <div class="page-head">
      <div>
        <router-link class="meta" to="/">← 返回列表</router-link>
        <h1 v-if="entry">{{ entry.title }}</h1>
        <p v-if="entry">
          <span :class="entry.completeness.complete ? 'badge badge-ok' : 'badge badge-warn'">
            {{ entry.completeness.complete ? '齐套' : `缺：${missingLabel(entry.completeness.missing)}` }}
          </span>
          <span v-if="entry.note" class="meta"> · {{ entry.note }}</span>
        </p>
      </div>
      <div class="actions">
        <button class="btn btn-primary" :disabled="!entry?.completeness.complete || composing" @click="compose">
          {{ composing ? '拼版中…' : '生成拼版 PDF' }}
        </button>
      </div>
    </div>

    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="msg" class="okmsg">{{ msg }}</p>
    <div v-if="loading" class="meta">加载中…</div>

    <template v-else-if="entry">
      <div class="card" style="margin-bottom: 1rem">
        <div class="form-row">
          <input v-model="editTitle" style="flex:1" />
          <input v-model="editNote" placeholder="备注" style="flex:1" />
          <button class="btn" @click="saveMeta">保存信息</button>
        </div>
      </div>

      <div class="slots">
        <div v-for="slot in slots" :key="slot.type" class="slot">
          <h4>{{ slot.label }}</h4>
          <div class="preview">
            <template v-if="slot.material">
              <img v-if="isImage(slot.material)" :src="slot.material.url" :alt="slot.material.original_name" />
              <div v-else class="empty">PDF：{{ slot.material.original_name }}</div>
            </template>
            <div v-else class="empty">尚未上传</div>
          </div>
          <div class="meta" v-if="slot.material">{{ slot.material.original_name }}</div>
          <div class="actions">
            <label class="btn">
              {{ slot.material ? '替换' : '上传' }}
              <input type="file" hidden :accept="slot.accept" @change="onUpload($event, slot.type)" />
            </label>
            <button v-if="slot.material" class="btn btn-danger" @click="removeMaterial(slot.material)">删除</button>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { api, missingLabel, TYPE_LABELS } from '../api/client'
import { useConfirmDialog } from '../composables/useConfirmDialog'

const props = defineProps({ id: { type: [String, Number], required: true } })
const route = useRoute()
const { askConfirm } = useConfirmDialog()
const entry = ref(null)
const loading = ref(true)
const error = ref('')
const msg = ref('')
const composing = ref(false)
const editTitle = ref('')
const editNote = ref('')

const slots = computed(() => {
  const mats = entry.value?.materials || []
  const pick = (type) => mats.find((m) => m.type === type) || null
  return [
    { type: 'invoice', label: TYPE_LABELS.invoice, accept: 'application/pdf,.pdf', material: pick('invoice') },
    { type: 'order', label: TYPE_LABELS.order, accept: 'image/*', material: pick('order') },
    { type: 'payment', label: TYPE_LABELS.payment, accept: 'image/*', material: pick('payment') },
  ]
})

function isImage(m) {
  return (m.mime || '').startsWith('image/') || /\.(png|jpe?g|webp|gif|bmp)$/i.test(m.original_name)
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    entry.value = await api.getEntry(props.id)
    editTitle.value = entry.value.title
    editNote.value = entry.value.note || ''
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

async function saveMeta() {
  error.value = ''
  msg.value = ''
  try {
    entry.value = await api.updateEntry(props.id, { title: editTitle.value, note: editNote.value })
    msg.value = '已保存'
  } catch (e) {
    error.value = e.message
  }
}

async function onUpload(ev, type) {
  const file = ev.target.files?.[0]
  ev.target.value = ''
  if (!file) return
  error.value = ''
  msg.value = ''
  try {
    const existing = entry.value.materials.find((m) => m.type === type)
    if (existing) await api.deleteMaterial(existing.id)
    await api.uploadMaterial(file, { entryId: Number(props.id), type })
    await load()
    msg.value = `${TYPE_LABELS[type]}已更新`
  } catch (e) {
    error.value = e.message
  }
}

async function removeMaterial(m) {
  const ok = await askConfirm({
    title: '删除材料',
    message: `确定删除材料「${m.original_name}」？`,
    confirmText: '删除',
    cancelText: '取消',
    danger: true,
  })
  if (!ok) return
  try {
    await api.deleteMaterial(m.id)
    await load()
  } catch (e) {
    error.value = e.message
  }
}

async function compose() {
  composing.value = true
  error.value = ''
  try {
    const { blob, filename } = await api.composeEntry(props.id)
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.click()
    URL.revokeObjectURL(url)
  } catch (e) {
    error.value = e.message
  } finally {
    composing.value = false
  }
}

watch(() => route.params.id, load)
onMounted(load)
</script>
