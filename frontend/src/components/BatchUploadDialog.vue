<template>
  <Teleport to="body">
    <div v-if="state.open" class="modal-backdrop" @click.self="close">
      <div class="modal-card modal-wide" role="dialog" aria-modal="true" aria-labelledby="batch-upload-title">
        <div class="modal-head">
          <div>
            <h3 id="batch-upload-title" class="modal-title">批量上传</h3>
            <p class="modal-sub">OCR / 发票文本自动识别类型与金额，按线索归入拟建条目，确认后入库</p>
          </div>
          <button class="btn-ghost" type="button" aria-label="关闭" @click="close">关闭</button>
        </div>
        <BatchUploadPanel ref="panelRef" @done="onDone" />
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { onMounted, onUnmounted, ref, watch } from 'vue'
import BatchUploadPanel from './BatchUploadPanel.vue'
import { useBatchUploadDialog } from '../composables/useBatchUploadDialog'

const { state, closeBatchUpload } = useBatchUploadDialog()
const panelRef = ref(null)

function close() {
  panelRef.value?.clear?.()
  closeBatchUpload({ done: false })
}

function onDone() {
  closeBatchUpload({ done: true })
}

function onKeydown(e) {
  if (!state.open) return
  if (e.key === 'Escape') close()
}

watch(
  () => state.open,
  (open) => {
    if (!open) panelRef.value?.clear?.()
  },
)

onMounted(() => window.addEventListener('keydown', onKeydown))
onUnmounted(() => window.removeEventListener('keydown', onKeydown))
</script>
