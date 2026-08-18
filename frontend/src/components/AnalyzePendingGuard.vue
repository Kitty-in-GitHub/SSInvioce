<template>
  <div v-if="hasPending" class="analyze-pending-card" role="status">
    <strong>正在后台识别 {{ count }} 个文件</strong>
    <p>金额和查重会在识别完成后自动写入。关闭程序或结束后端窗口会中断处理。</p>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, watch } from 'vue'
import { useAnalyzeJobs } from '../composables/useAnalyzeJobs'
import { useConfirmDialog } from '../composables/useConfirmDialog'

const { count, hasPending, kickAnalyzePolling } = useAnalyzeJobs()
const { askConfirm } = useConfirmDialog()
let allowUnload = false
let asking = false

function onBeforeUnload(e) {
  if (allowUnload || !hasPending.value) return
  e.preventDefault()
  e.returnValue = '仍有文件正在识别，关闭程序会中断处理。'
}

async function warnIfLeaving(e) {
  if (allowUnload || !hasPending.value || asking) return
  const refresh = e.key === 'F5' || ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'r')
  if (!refresh) return
  e.preventDefault()
  asking = true
  try {
    const ok = await askConfirm({
      title: '识别尚未完成',
      message: `仍有 ${count.value} 个文件正在后台识别。现在刷新或关闭程序会中断处理，金额和查重可能不会写入。`,
      confirmText: '仍要离开',
      cancelText: '继续等待',
      danger: true,
    })
    if (ok) {
      allowUnload = true
      window.location.reload()
    }
  } finally {
    asking = false
  }
}

onMounted(() => {
  kickAnalyzePolling()
  window.addEventListener('beforeunload', onBeforeUnload)
  window.addEventListener('keydown', warnIfLeaving, true)
})
onUnmounted(() => {
  window.removeEventListener('beforeunload', onBeforeUnload)
  window.removeEventListener('keydown', warnIfLeaving, true)
})

watch(hasPending, (pending) => {
  if (!pending) allowUnload = false
})
</script>
