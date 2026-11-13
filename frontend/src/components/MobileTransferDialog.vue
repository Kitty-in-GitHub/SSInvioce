<template>
  <Teleport to="body">
    <div v-if="open" class="modal-backdrop" @click.self="close">
      <div
        class="modal-card mobile-transfer-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="mobile-transfer-title"
      >
        <div class="modal-head">
          <div>
            <h3 id="mobile-transfer-title">扫码传文件</h3>
            <p class="modal-sub">手机和电脑连同一个 Wi‑Fi（或电脑热点），扫码后选截图上传</p>
          </div>
          <button class="btn-ghost mobile-close" type="button" aria-label="关闭" @click="close">✕</button>
        </div>

        <p v-if="error" class="error">{{ error }}</p>
        <div v-if="loading" class="meta">正在启动接收服务…</div>

        <template v-else-if="session?.active">
          <img v-if="session.qr" class="mobile-qr" :src="session.qr" alt="手机扫码上传" />
          <p class="mobile-url">{{ session.url }}</p>
          <p v-if="localOnly" class="error mobile-warn">
            没检测到局域网地址，手机无法访问。请先连上 Wi-Fi，或开电脑热点。
          </p>
          <p class="meta mobile-status">
            已收到 <strong>{{ session.received || 0 }}</strong> 个 · 剩余 {{ leftText }}
          </p>
          <ul v-if="recentItems.length" class="mobile-received">
            <li v-for="(it, i) in recentItems" :key="i">
              {{ it.name }}
            </li>
          </ul>
          <div class="actions mobile-actions">
            <button class="btn" type="button" @click="copyUrl">{{ copied ? '已复制' : '复制链接' }}</button>
            <button class="btn" type="button" @click="stopAndClose">停止接收</button>
          </div>
          <p class="meta mobile-foot">
            手机打不开时：确认在同一 Wi-Fi；Windows 防火墙需允许本程序访问「专用网络」。
          </p>
        </template>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { computed, onUnmounted, ref, watch } from 'vue'
import { api } from '../api/client'

const props = defineProps({ open: { type: Boolean, default: false } })
const emit = defineEmits(['close', 'received'])

const session = ref(null)
const error = ref('')
const loading = ref(false)
const copied = ref(false)
let pollTimer = null
let copyTimer = null
let lastReceived = 0
let starting = false

const localOnly = computed(() => /127\.0\.0\.1|localhost/.test(session.value?.url || ''))
const recentItems = computed(() => (session.value?.items || []).slice(-5).reverse())
const leftText = computed(() => {
  const sec = Math.max(0, Number(session.value?.expires_in ?? 0))
  const m = Math.floor(sec / 60)
  const s = sec % 60
  return `${m}:${String(s).padStart(2, '0')}`
})

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

async function start() {
  if (starting) return
  starting = true
  loading.value = true
  error.value = ''
  session.value = null
  lastReceived = 0
  try {
    const data = await api.startMobileSession()
    if (!props.open) {
      api.stopMobileSession().catch(() => {})
      return
    }
    if (!data?.active) throw new Error('无法启动接收服务')
    session.value = data
    pollTimer = window.setInterval(poll, 1500)
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
    starting = false
  }
}

async function poll() {
  try {
    const data = await api.mobileSession()
    if (!data?.active) {
      stopPolling()
      session.value = null
      error.value = '接收已结束（可能已过期），请关闭后重试'
      return
    }
    session.value = { ...session.value, ...data }
    const received = Number(data.received || 0)
    if (received > lastReceived) {
      lastReceived = received
      emit('received', { received, items: data.items || [] })
    }
  } catch {
    /* transient network errors: keep polling */
  }
}

async function stopSession() {
  stopPolling()
  const active = session.value?.active
  session.value = null
  if (active) {
    try {
      await api.stopMobileSession()
    } catch {
      /* ignore */
    }
  }
}

function close() {
  stopSession()
  emit('close')
}

function stopAndClose() {
  close()
}

async function copyUrl() {
  if (!session.value?.url) return
  try {
    await navigator.clipboard.writeText(session.value.url)
    copied.value = true
    if (copyTimer) clearTimeout(copyTimer)
    copyTimer = window.setTimeout(() => {
      copied.value = false
    }, 1500)
  } catch {
    copied.value = false
  }
}

watch(
  () => props.open,
  (open) => {
    if (open) start()
    else stopSession()
  },
)

onUnmounted(() => {
  stopPolling()
  if (copyTimer) clearTimeout(copyTimer)
  if (session.value?.active) api.stopMobileSession().catch(() => {})
})
</script>
