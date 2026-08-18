<template>
  <div class="app-shell">
    <aside class="sidebar">
      <router-link class="sidebar-brand" to="/">
        <span class="sidebar-mark">报</span>
        <span class="sidebar-brand-text">
          <strong>报销助手</strong>
          <small>Star Invoice</small>
        </span>
      </router-link>

      <nav class="sidebar-nav">
        <router-link
          v-for="item in navItems"
          :key="item.to"
          :to="item.to"
          class="sidebar-link"
          active-class=""
          exact-active-class=""
          :class="{ active: isNavActive(item) }"
        >
          <span class="sidebar-link-icon" aria-hidden="true">{{ item.icon }}</span>
          <span>{{ item.label }}</span>
        </router-link>
        <div class="sidebar-nav-spacer" aria-hidden="true" />
        <router-link
          to="/help"
          class="sidebar-link"
          active-class=""
          exact-active-class=""
          :class="{ active: isNavActive(helpNav) }"
        >
          <span class="sidebar-link-icon" aria-hidden="true">{{ helpNav.icon }}</span>
          <span>{{ helpNav.label }}</span>
        </router-link>
        <router-link
          to="/settings"
          class="sidebar-link"
          active-class=""
          exact-active-class=""
          :class="{ active: isNavActive(settingsNav) }"
        >
          <span class="sidebar-link-icon" aria-hidden="true">{{ settingsNav.icon }}</span>
          <span>{{ settingsNav.label }}</span>
        </router-link>
      </nav>

      <div class="sidebar-footer">
        <div v-if="apiError" class="sidebar-status bad">后端不可用</div>
        <div v-else-if="apiInfo" class="sidebar-status ok">数据正常</div>
        <div v-else class="sidebar-status">检测中…</div>
        <div v-if="apiInfo" class="sidebar-meta">v{{ apiInfo.version }}</div>
      </div>
    </aside>

    <div class="app-body">
      <div v-if="apiError" class="banner-error">
        后端不可用：{{ apiError }}
        <button class="btn" style="margin-left:0.75rem" @click="probe">重试检测</button>
      </div>
      <div v-else-if="apiInfo" class="banner-ok">
        API 已连接 · {{ apiInfo.service }} v{{ apiInfo.version }}
      </div>
      <main class="main">
        <router-view />
      </main>
    </div>

    <BatchUploadDialog />
    <ConfirmDialog />
    <AnalyzePendingGuard />
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { checkApiHealth } from './api/client'
import ConfirmDialog from './components/ConfirmDialog.vue'
import BatchUploadDialog from './components/BatchUploadDialog.vue'
import AnalyzePendingGuard from './components/AnalyzePendingGuard.vue'

const route = useRoute()
const apiError = ref('')
const apiInfo = ref(null)

/** 侧栏导航（批量上传用弹窗，不进侧栏；帮助与设置固定在底部） */
const navItems = [
  { to: '/', label: '条目', icon: '☰', match: ['/', '/entries'] },
  { to: '/inbox', label: '收件箱', icon: '▢' },
  { to: '/ledger', label: '记账', icon: '¥' },
]
const helpNav = { to: '/help', label: '使用帮助', icon: '?' }
const settingsNav = { to: '/settings', label: '设置', icon: '⚙' }

function isNavActive(item) {
  const path = route.path
  if (item.match) {
    return item.match.some((m) => (m === '/' ? path === '/' : path === m || path.startsWith(`${m}/`)))
  }
  return path === item.to || path.startsWith(`${item.to}/`)
}

async function probe() {
  apiError.value = ''
  apiInfo.value = null
  try {
    apiInfo.value = await checkApiHealth()
  } catch (e) {
    apiError.value = e.message
  }
}

onMounted(probe)
</script>
