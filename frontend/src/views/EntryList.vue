<template>
  <div>
    <div class="page-head">
      <div>
        <h1>报销条目</h1>
        <p>管理发票、订单截图与支付记录的齐套状态</p>
      </div>
      <div class="actions">
        <router-link class="btn" to="/upload">批量上传</router-link>
      </div>
    </div>

    <div class="card" style="margin-bottom: 1rem">
      <div class="form-row">
        <input v-model="title" placeholder="新条目名称，如：社团年会物资" style="flex:1;min-width:200px" @keyup.enter="create" />
        <input v-model="note" placeholder="备注（可选）" style="flex:1;min-width:160px" @keyup.enter="create" />
        <button class="btn btn-primary" :disabled="!title.trim() || creating" @click="create">新建条目</button>
      </div>
      <p v-if="error" class="error">{{ error }}</p>
    </div>

    <div v-if="loading" class="meta">加载中…</div>
    <div v-else-if="!entries.length" class="card empty">暂无条目，先新建一条或去批量上传。</div>
    <div v-else class="list">
      <div v-for="e in entries" :key="e.id" class="card entry-row">
        <div>
          <h3>
            <router-link :to="`/entries/${e.id}`">{{ e.title }}</router-link>
          </h3>
          <div class="meta">
            <span v-if="e.note">{{ e.note }} · </span>
            材料 {{ e.materials.length }} 个 ·
            <span :class="e.completeness.complete ? 'badge badge-ok' : 'badge badge-warn'">
              {{ e.completeness.complete ? '齐套' : `缺：${missingLabel(e.completeness.missing)}` }}
            </span>
          </div>
        </div>
        <div class="actions">
          <router-link class="btn" :to="`/entries/${e.id}`">详情</router-link>
          <button class="btn btn-primary" :disabled="!e.completeness.complete || composingId === e.id" @click="compose(e)">
            {{ composingId === e.id ? '拼版中…' : '拼版 PDF' }}
          </button>
          <button class="btn btn-danger" @click="remove(e)">删除</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { api, missingLabel } from '../api/client'
import { useConfirmDialog } from '../composables/useConfirmDialog'

const { askConfirm } = useConfirmDialog()
const entries = ref([])
const loading = ref(true)
const title = ref('')
const note = ref('')
const creating = ref(false)
const error = ref('')
const composingId = ref(null)

async function load() {
  loading.value = true
  error.value = ''
  try {
    entries.value = await api.listEntries()
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

async function create() {
  if (!title.value.trim()) return
  creating.value = true
  error.value = ''
  try {
    await api.createEntry({ title: title.value.trim(), note: note.value })
    title.value = ''
    note.value = ''
    await load()
  } catch (e) {
    error.value = e.message
  } finally {
    creating.value = false
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
    await load()
  } catch (err) {
    error.value = err.message
  }
}

async function compose(e) {
  composingId.value = e.id
  error.value = ''
  try {
    const { blob, filename } = await api.composeEntry(e.id)
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.click()
    URL.revokeObjectURL(url)
  } catch (err) {
    error.value = err.message
  } finally {
    composingId.value = null
  }
}

onMounted(load)
</script>
