import { computed, ref } from 'vue'
import { api } from '../api/client'

const pending = ref([])
let pollTimer = null
let inFlight = false

async function refreshAnalyzeJobs() {
  if (inFlight) return
  inFlight = true
  try {
    const data = await api.listAnalyzeJobs()
    pending.value = data?.pending || []
  } catch {
    /* backend restarting or offline */
  } finally {
    inFlight = false
  }
  if (pending.value.length) scheduleAnalyzePoll()
}

function scheduleAnalyzePoll() {
  if (pollTimer) return
  pollTimer = window.setTimeout(async () => {
    pollTimer = null
    await refreshAnalyzeJobs()
  }, 1500)
}

export function kickAnalyzePolling() {
  if (pollTimer) {
    clearTimeout(pollTimer)
    pollTimer = null
  }
  return refreshAnalyzeJobs()
}

export function useAnalyzeJobs() {
  const count = computed(() => pending.value.length)
  const hasPending = computed(() => count.value > 0)

  function jobsForEntry(entryId) {
    const id = Number(entryId)
    return pending.value.filter((j) => Number(j.entry_id) === id)
  }

  return {
    pending,
    count,
    hasPending,
    jobsForEntry,
    kickAnalyzePolling,
    refreshAnalyzeJobs,
  }
}
