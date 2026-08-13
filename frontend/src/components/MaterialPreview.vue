<template>
  <div
    v-if="mode !== 'lightbox'"
    class="material-preview"
    :class="[`mode-${mode}`, { clickable: canOpenLightbox }]"
  >
    <template v-if="kind === 'image' && url">
      <img class="material-preview-img" :src="url" :alt="title" @click="openLightbox" />
    </template>
    <template v-else-if="kind === 'pdf' && url">
      <template v-if="mode === 'detail'">
        <iframe class="pdf-frame" :src="url" :title="title || 'PDF 预览'" />
        <div class="material-preview-actions">
          <a class="link-btn" :href="url" target="_blank" rel="noopener">新窗口打开</a>
        </div>
      </template>
      <button v-else type="button" class="pdf-thumb" @click="openLightbox">
        <span class="pdf-thumb-badge">PDF</span>
        <span class="pdf-thumb-hint">点击预览</span>
      </button>
    </template>
    <div v-else class="empty">{{ emptyText }}</div>
  </div>

  <Teleport to="body">
    <div v-if="lightboxOpen" class="modal-backdrop modal-backdrop-compare" @click.self="closeLightbox">
      <div class="modal-card modal-wide material-preview-modal" role="dialog" aria-modal="true">
        <div class="modal-head">
          <div>
            <h3 class="modal-title">{{ title || '预览' }}</h3>
          </div>
          <div class="material-preview-modal-actions">
            <a v-if="url" class="link-btn" :href="url" target="_blank" rel="noopener">新窗口打开</a>
            <button class="btn-ghost" type="button" @click="closeLightbox">关闭</button>
          </div>
        </div>
        <div class="material-preview-modal-body">
          <img v-if="kind === 'image'" class="material-preview-modal-img" :src="url" :alt="title" />
          <iframe v-else class="pdf-frame pdf-frame-modal" :src="url" :title="title || 'PDF 预览'" />
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'

const props = defineProps({
  url: { type: String, default: '' },
  kind: { type: String, default: 'image' }, // image | pdf
  mode: { type: String, default: 'detail' }, // detail | compact | lightbox
  title: { type: String, default: '' },
  emptyText: { type: String, default: '无预览' },
  /** Controlled open for mode=lightbox (or force-open lightbox) */
  open: { type: Boolean, default: false },
})

const emit = defineEmits(['close', 'update:open'])

const lightboxOpen = ref(false)

const canOpenLightbox = computed(
  () => !!props.url && (props.kind === 'image' || (props.kind === 'pdf' && props.mode === 'compact')),
)

function openLightbox() {
  if (!props.url) return
  lightboxOpen.value = true
  emit('update:open', true)
}

function closeLightbox() {
  lightboxOpen.value = false
  emit('update:open', false)
  emit('close')
}

function onKeydown(e) {
  if (e.key === 'Escape' && lightboxOpen.value) closeLightbox()
}

watch(
  () => props.open,
  (v) => {
    if (v && props.url) lightboxOpen.value = true
    if (!v) lightboxOpen.value = false
  },
  { immediate: true },
)

watch(
  () => props.url,
  () => {
    if (!props.open) closeLightbox()
  },
)

onMounted(() => window.addEventListener('keydown', onKeydown))
onUnmounted(() => {
  window.removeEventListener('keydown', onKeydown)
  lightboxOpen.value = false
})

defineExpose({ open: openLightbox, close: closeLightbox })
</script>
