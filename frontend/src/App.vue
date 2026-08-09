<template>
  <div class="app-shell">
    <header class="topbar">
      <router-link class="brand" to="/">报销助手</router-link>
      <nav class="nav">
        <router-link to="/">条目</router-link>
        <router-link to="/upload">批量上传</router-link>
        <router-link to="/inbox">收件箱</router-link>
      </nav>
    </header>
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
    <ConfirmDialog />
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { checkApiHealth } from './api/client'
import ConfirmDialog from './components/ConfirmDialog.vue'

const apiError = ref('')
const apiInfo = ref(null)

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
