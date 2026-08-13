<template>
  <Teleport to="body">
    <div v-if="open" class="modal-backdrop modal-backdrop-compare" @click.self="onBackdrop">
      <div class="modal-card modal-wide invoice-dup-compare" role="dialog" aria-modal="true">
        <div class="modal-head">
          <div>
            <h3 class="modal-title">重复发票对比</h3>
            <p v-if="invoiceNumber" class="modal-sub">发票号码 {{ invoiceNumber }}</p>
          </div>
          <button class="btn-ghost" type="button" :disabled="busy" @click="close">关闭</button>
        </div>
        <div class="dup-compare-grid">
          <section class="dup-compare-pane">
            <header class="dup-compare-label">{{ leftLabel }}</header>
            <p class="meta dup-compare-name">{{ leftTitle || '—' }}</p>
            <MaterialPreview
              v-if="leftUrl"
              :url="leftUrl"
              :kind="leftKind"
              mode="detail"
              :title="leftTitle"
            />
            <div v-else class="empty">无预览</div>
          </section>
          <section class="dup-compare-pane">
            <header class="dup-compare-label">{{ rightLabel }}</header>
            <p class="meta dup-compare-name">{{ rightTitle || '—' }}</p>
            <MaterialPreview
              v-if="rightUrl"
              :url="rightUrl"
              :kind="rightKind"
              mode="detail"
              :title="rightTitle"
            />
            <div v-else class="empty">无预览</div>
          </section>
        </div>
        <div v-if="resolvable" class="dup-compare-actions">
          <p class="meta dup-compare-hint">选择保留哪一份，或两份都入库</p>
          <div class="dup-compare-action-row">
            <button class="btn btn-primary" type="button" :disabled="busy" @click="choose('keep_left')">
              保留左侧（本次）
            </button>
            <button class="btn" type="button" :disabled="busy" @click="choose('keep_right')">
              保留右侧（对照）
            </button>
            <button class="btn" type="button" :disabled="busy" @click="choose('keep_both')">
              都添加
            </button>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { onMounted, onUnmounted, watch } from 'vue'
import MaterialPreview from './MaterialPreview.vue'

const props = defineProps({
  open: { type: Boolean, default: false },
  invoiceNumber: { type: String, default: '' },
  leftLabel: { type: String, default: '本次上传' },
  leftUrl: { type: String, default: '' },
  leftKind: { type: String, default: 'pdf' },
  leftTitle: { type: String, default: '' },
  rightLabel: { type: String, default: '已有发票' },
  rightUrl: { type: String, default: '' },
  rightKind: { type: String, default: 'pdf' },
  rightTitle: { type: String, default: '' },
  resolvable: { type: Boolean, default: false },
  busy: { type: Boolean, default: false },
})

const emit = defineEmits(['close', 'resolve'])

function close() {
  if (props.busy) return
  emit('close')
}

function onBackdrop() {
  close()
}

function choose(decision) {
  if (props.busy) return
  emit('resolve', decision)
}

function onKeydown(e) {
  if (e.key === 'Escape' && props.open) close()
}

watch(
  () => props.open,
  (v) => {
    document.body.style.overflow = v ? 'hidden' : ''
  },
)

onMounted(() => window.addEventListener('keydown', onKeydown))
onUnmounted(() => {
  window.removeEventListener('keydown', onKeydown)
  document.body.style.overflow = ''
})
</script>
