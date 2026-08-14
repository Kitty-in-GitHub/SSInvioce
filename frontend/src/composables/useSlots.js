import { computed, onMounted, ref } from 'vue'
import { api } from '../api/client'

const slots = ref([])
const layout = ref({ pages: [{ regions: [] }] })
const loaded = ref(false)
const loadError = ref('')
let loadingPromise = null

export function acceptForKind(kind) {
  return kind === 'pdf' ? 'application/pdf,.pdf' : 'image/*,.jpg,.jpeg,.png,.webp,.bmp,.gif'
}

export async function loadSlots(force = false) {
  if (loadingPromise && !force) return loadingPromise
  loadingPromise = (async () => {
    loadError.value = ''
    try {
      const res = await api.getSettings()
      slots.value = res.slots || []
      layout.value = res.layout || { pages: [{ regions: [] }] }
      loaded.value = true
      return res
    } catch (e) {
      loadError.value = e.message
      throw e
    } finally {
      loadingPromise = null
    }
  })()
  return loadingPromise
}

export function useSlots() {
  onMounted(() => {
    if (!loaded.value) loadSlots().catch(() => {})
  })
  const slotLabels = computed(() => {
    const map = { unknown: '未分类' }
    for (const s of slots.value) map[s.id] = s.label
    return map
  })
  const requiredIds = computed(() => slots.value.filter((s) => s.required).map((s) => s.id))
  const invoiceId = computed(() => slots.value.find((s) => s.special === 'invoice')?.id || 'invoice')
  return { slots, layout, loaded, loadError, slotLabels, requiredIds, invoiceId, loadSlots, acceptForKind }
}

export function missingLabelFromSlots(missing, labels) {
  return (missing || []).map((t) => labels?.[t] || t).join('、')
}
