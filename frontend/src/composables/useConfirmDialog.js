import { reactive } from 'vue'

const state = reactive({
  open: false,
  title: '确认操作',
  message: '',
  confirmText: '确定',
  cancelText: '取消',
  danger: false,
  _resolve: null,
})

export function useConfirmDialog() {
  function askConfirm({
    title = '确认操作',
    message = '',
    confirmText = '确定',
    cancelText = '取消',
    danger = false,
  } = {}) {
    return new Promise((resolve) => {
      state.open = true
      state.title = title
      state.message = message
      state.confirmText = confirmText
      state.cancelText = cancelText
      state.danger = danger
      state._resolve = resolve
    })
  }

  function accept() {
    const resolve = state._resolve
    state.open = false
    state._resolve = null
    resolve?.(true)
  }

  function cancel() {
    const resolve = state._resolve
    state.open = false
    state._resolve = null
    resolve?.(false)
  }

  return { state, askConfirm, accept, cancel }
}
