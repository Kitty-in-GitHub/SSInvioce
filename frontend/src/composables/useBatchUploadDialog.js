import { reactive } from 'vue'

const state = reactive({
  open: false,
  onDone: null,
})

export function useBatchUploadDialog() {
  function openBatchUpload(options = {}) {
    state.onDone = typeof options.onDone === 'function' ? options.onDone : null
    state.open = true
  }

  function closeBatchUpload({ done = false } = {}) {
    const cb = state.onDone
    state.open = false
    state.onDone = null
    if (done && cb) cb()
  }

  return { state, openBatchUpload, closeBatchUpload }
}
