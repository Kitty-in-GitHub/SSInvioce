<template>
  <div>
    <div class="page-head">
      <div>
        <h1>待归类收件箱</h1>
        <p>尚未挂到条目的材料，可改类型并分配到条目</p>
      </div>
      <div class="actions">
        <button class="btn" @click="load">刷新</button>
      </div>
    </div>

    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="msg" class="okmsg">{{ msg }}</p>
    <div v-if="loading" class="meta">加载中…</div>
    <div v-else-if="!items.length" class="card empty">收件箱为空。</div>
    <div v-else class="card">
      <table class="table">
        <thead>
          <tr>
            <th>预览</th>
            <th>文件</th>
            <th>类型</th>
            <th>分配到条目</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="m in items" :key="m.id">
            <td>
              <MaterialPreview
                :url="m.url"
                :kind="previewKind(m)"
                mode="compact"
                :title="m.original_name"
              />
            </td>
            <td>{{ m.original_name }}</td>
            <td>
              <select :value="m.type" @change="changeType(m, $event.target.value)">
                <option v-for="s in slotDefs" :key="s.id" :value="s.id">{{ s.label }}</option>
                <option value="unknown">未分类</option>
              </select>
            </td>
            <td>
              <select v-model.number="assignMap[m.id]">
                <option :value="null">选择条目</option>
                <option v-for="e in entries" :key="e.id" :value="e.id">{{ e.title }}</option>
              </select>
              <button class="btn" style="margin-left:0.35rem" :disabled="!assignMap[m.id]" @click="assign(m)">挂入</button>
            </td>
            <td>
              <button class="btn btn-danger" @click="remove(m)">删除</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { api, isImageMaterial, isPdfMaterial } from '../api/client'
import { useSlots } from '../composables/useSlots'
import MaterialPreview from '../components/MaterialPreview.vue'
import { useConfirmDialog } from '../composables/useConfirmDialog'

const { askConfirm } = useConfirmDialog()
const { slots: slotDefs } = useSlots()
const items = ref([])
const entries = ref([])
const loading = ref(true)
const error = ref('')
const msg = ref('')
const assignMap = reactive({})

function previewKind(m) {
  if (isPdfMaterial(m)) return 'pdf'
  if (isImageMaterial(m)) return 'image'
  return 'image'
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    ;[items.value, entries.value] = await Promise.all([api.listInbox(), api.listEntries()])
    for (const m of items.value) {
      if (!(m.id in assignMap)) assignMap[m.id] = null
    }
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

async function changeType(m, type) {
  try {
    await api.updateMaterial(m.id, { type })
    msg.value = '类型已更新'
    await load()
  } catch (e) {
    error.value = e.message
  }
}

async function assign(m) {
  const entryId = assignMap[m.id]
  if (!entryId) return
  if (m.type === 'unknown') {
    error.value = '请先指定类型再挂入条目'
    return
  }
  try {
    await api.updateMaterial(m.id, { entry_id: entryId })
    msg.value = '已挂入条目'
    await load()
  } catch (e) {
    error.value = e.message
  }
}

async function remove(m) {
  const ok = await askConfirm({
    title: '删除材料',
    message: `确定删除「${m.original_name}」？`,
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

onMounted(load)
</script>
