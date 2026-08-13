<template>
  <div class="material-preview" :class="[`mode-${mode}`, { clickable: canOpenLightbox }]">
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

    <Teleport to="body">
      <div v-if="lightboxOpen" class="modal-backdrop" @click.self="closeLightbox">
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
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'

const props = defineProps({
  url: { type: String, default: '' },
  kind: { type: String, default: 'image' }, // image | pdf
  mode: { type: String, default: 'detail' }, // detail | compact
  title: { type: String, default: '' },
  emptyText: { type: String, default: '无预览' },
})

const lightboxOpen = ref(false)

const canOpenLightbox = computed(
  () => !!props.url && (props.kind === 'image' || (props.kind === 'pdf' && props.mode === 'compact')),
)

function openLightbox() {
  if (!canOpenLightbox.value) return
  lightboxOpen.value = true
}

function closeLightbox() {
  lightboxOpen.value = false
}

function onKeydown(e) {
  if (e.key === 'Escape') closeLightbox()
}

watch(
  () => props.url,
  () => closeLightbox(),
)

onMounted(() => window.addEventListener('keydown', onKeydown))
onUnmounted(() => {
  window.removeEventListener('keydown', onKeydown)
  closeLightbox()
})
</script>
