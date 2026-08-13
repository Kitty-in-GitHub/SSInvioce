<template>
  <Teleport to="body">
    <div v-if="state.open" class="modal-backdrop modal-backdrop-confirm" @click.self="cancel">
      <div class="modal-card" role="dialog" aria-modal="true" :aria-labelledby="titleId">
        <h3 :id="titleId" class="modal-title">{{ state.title }}</h3>
        <p class="modal-message">{{ state.message }}</p>
        <div class="modal-actions">
          <button class="btn" type="button" @click="cancel">{{ state.cancelText }}</button>
          <button
            class="btn"
            :class="state.danger ? 'btn-danger-solid' : 'btn-primary'"
            type="button"
            @click="accept"
          >
            {{ state.confirmText }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { onMounted, onUnmounted } from 'vue'
import { useConfirmDialog } from '../composables/useConfirmDialog'

const titleId = 'confirm-dialog-title'
const { state, accept, cancel } = useConfirmDialog()

function onKeydown(e) {
  if (!state.open) return
  if (e.key === 'Escape') cancel()
}

onMounted(() => window.addEventListener('keydown', onKeydown))
onUnmounted(() => window.removeEventListener('keydown', onKeydown))
</script>
