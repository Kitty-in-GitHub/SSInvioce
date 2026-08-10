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
      <div class="card spaced">
        <div class="meta-grid">
          <div class="field field-span-2">
            <label>标题</label>
            <input v-model="editTitle" />
          </div>
          <div class="field">
            <label>所属分组</label>
            <select v-model="editGroupId">
              <option :value="null">未分组</option>
              <option v-for="g in groups" :key="g.id" :value="g.id">{{ g.name }}</option>
            </select>
          </div>
          <div class="field field-span-2">
            <label>备注</label>
            <input v-model="editNote" placeholder="可选" />
          </div>
          <div class="field">
            <label>报销金额</label>
            <div class="amount-field-row">
              <div class="amount-edit">
                <span class="amount-prefix" aria-hidden="true">¥</span>
                <input v-model="editAmount" type="number" step="0.01" min="0" placeholder="0.00" />
              </div>
              <span class="amount-tag" :class="entry.amount_source">
                {{ entry.amount_source === 'manual' ? '已手改' : entry.amount_source === 'auto' ? '自动' : '无金额' }}
              </span>
            </div>
          </div>
        </div>
        <div class="meta-actions">
          <button class="btn btn-primary btn-sm" @click="saveMeta">保存信息</button>
          <button class="btn btn-sm" :disabled="reparsing" @click="reparse">
            {{ reparsing ? '识别中…' : '重新识别金额' }}
          </button>
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
            <label class="btn btn-sm">
              {{ slot.material ? '替换' : '上传' }}
              <input type="file" hidden :accept="slot.accept" @change="onUpload($event, slot.type)" />
            </label>
            <button v-if="slot.material" class="btn btn-danger btn-sm" @click="removeMaterial(slot.material)">删除</button>
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
const groups = ref([])
const loading = ref(true)
const error = ref('')
const msg = ref('')
const composing = ref(false)
const reparsing = ref(false)
const editTitle = ref('')
const editNote = ref('')
const editAmount = ref('')
const editGroupId = ref(null)

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
    ;[entry.value, groups.value] = await Promise.all([api.getEntry(props.id), api.listGroups()])
    editTitle.value = entry.value.title
    editNote.value = entry.value.note || ''
    editAmount.value = entry.value.amount ?? ''
    editGroupId.value = entry.value.group_id
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
    const amountRaw = editAmount.value
    const amount = amountRaw === '' || amountRaw == null ? null : Number(amountRaw)
    if (amountRaw !== '' && amountRaw != null && Number.isNaN(amount)) {
      error.value = '金额格式无效'
      return
    }
    const body = {
      title: editTitle.value,
      note: editNote.value,
      amount,
    }
    if (editGroupId.value == null) body.clear_group = true
    else body.group_id = editGroupId.value
    entry.value = await api.updateEntry(props.id, body)
    editAmount.value = entry.value.amount ?? ''
    editGroupId.value = entry.value.group_id
    msg.value = '已保存'
  } catch (e) {
    error.value = e.message
  }
}

async function reparse() {
  reparsing.value = true
  error.value = ''
  msg.value = ''
  try {
    const force = entry.value?.amount_source === 'manual'
    entry.value = await api.reparseAmount(props.id, force)
    editAmount.value = entry.value.amount ?? ''
    msg.value = force ? '已强制重新识别并覆盖手改金额' : '已重新识别金额'
  } catch (e) {
    error.value = e.message
  } finally {
    reparsing.value = false
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
