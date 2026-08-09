<template>
  <div>
    <div class="page-head">
      <div>
        <h1>批量上传与归类</h1>
        <p>上传后按规则建议类型，确认后入库；未知类型需手选</p>
      </div>
    </div>

    <div
      class="dropzone"
      :class="{ active: dragging }"
      @dragover.prevent="dragging = true"
      @dragleave.prevent="dragging = false"
      @drop.prevent="onDrop"
      @click="fileInput?.click()"
    >
      拖拽文件到此处，或点击选择（PDF / JPG / PNG）
      <input ref="fileInput" type="file" multiple hidden accept=".pdf,.jpg,.jpeg,.png,.webp,.bmp,.gif" @change="onPick" />
    </div>

    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="msg" class="okmsg">{{ msg }}</p>

    <div v-if="items.length" class="card" style="margin-top: 1rem">
      <table class="table">
        <thead>
          <tr>
            <th>预览</th>
            <th>文件名</th>
            <th>类型</th>
            <th>归属</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in items" :key="item.temp_id">
            <td>
              <img v-if="item.localUrl && !item.original_name.toLowerCase().endsWith('.pdf')" class="thumb" :src="item.localUrl" alt="" />
              <span v-else class="meta">PDF</span>
            </td>
            <td>{{ item.original_name }}</td>
            <td>
              <select v-model="item.type">
                <option value="invoice">发票</option>
                <option value="order">订单截图</option>
                <option value="payment">支付记录</option>
                <option value="unknown">未分类</option>
              </select>
            </td>
            <td>
              <select v-model="item.assignMode">
                <option value="inbox">先放收件箱</option>
                <option value="existing">挂到已有条目</option>
                <option value="new">新建条目</option>
              </select>
              <select v-if="item.assignMode === 'existing'" v-model.number="item.entry_id" style="margin-left:0.35rem">
                <option :value="null" disabled>选择条目</option>
                <option v-for="e in entries" :key="e.id" :value="e.id">{{ e.title }}</option>
              </select>
              <input
                v-if="item.assignMode === 'new'"
                v-model="item.create_entry_title"
                placeholder="新条目名称"
                style="margin-left:0.35rem;min-width:140px"
              />
            </td>
          </tr>
        </tbody>
      </table>
      <div class="actions" style="margin-top: 1rem">
        <button class="btn btn-primary" :disabled="confirming" @click="confirm">确认入库</button>
        <button class="btn" @click="clear">清空</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { api } from '../api/client'

const fileInput = ref(null)
const dragging = ref(false)
const items = ref([])
const entries = ref([])
const error = ref('')
const msg = ref('')
const confirming = ref(false)

async function loadEntries() {
  entries.value = await api.listEntries()
}

async function handleFiles(fileList) {
  const files = [...fileList]
  if (!files.length) return
  error.value = ''
  msg.value = ''
  try {
    const res = await api.classifyPreview(files)
    const mapped = res.items.map((it, idx) => ({
      ...it,
      type: it.suggested_type,
      assignMode: 'inbox',
      entry_id: null,
      create_entry_title: it.suggested_type === 'invoice' ? it.original_name.replace(/\.pdf$/i, '') : '',
      localUrl: files[idx] && !files[idx].name.toLowerCase().endsWith('.pdf') ? URL.createObjectURL(files[idx]) : null,
    }))
    items.value.push(...mapped)
  } catch (e) {
    error.value = e.message
  }
}

function onPick(ev) {
  handleFiles(ev.target.files || [])
  ev.target.value = ''
}

function onDrop(ev) {
  dragging.value = false
  handleFiles(ev.dataTransfer.files || [])
}

function clear() {
  for (const it of items.value) {
    if (it.localUrl) URL.revokeObjectURL(it.localUrl)
  }
  items.value = []
}

async function confirm() {
  error.value = ''
  msg.value = ''
  for (const it of items.value) {
    if (it.type === 'unknown') {
      error.value = `请为「${it.original_name}」选择类型`
      return
    }
    if (it.assignMode === 'existing' && !it.entry_id) {
      error.value = `请为「${it.original_name}」选择条目`
      return
    }
    if (it.assignMode === 'new' && !it.create_entry_title?.trim()) {
      error.value = `请为「${it.original_name}」填写新条目名称`
      return
    }
  }
  confirming.value = true
  try {
    const payload = items.value.map((it) => ({
      temp_id: it.temp_id,
      type: it.type,
      entry_id: it.assignMode === 'existing' ? it.entry_id : null,
      create_entry_title: it.assignMode === 'new' ? it.create_entry_title.trim() : null,
    }))
    await api.classifyConfirm(payload)
    msg.value = `已入库 ${payload.length} 个文件`
    clear()
    await loadEntries()
  } catch (e) {
    error.value = e.message
  } finally {
    confirming.value = false
  }
}

onMounted(loadEntries)
onUnmounted(clear)
</script>
