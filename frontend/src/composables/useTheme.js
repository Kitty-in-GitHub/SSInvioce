import { computed, ref } from 'vue'

const STORAGE_KEY = 'star-invoice-theme'
const DEFAULT_THEME = 'navy'

/** @type {{ id: string, name: string, blurb: string, swatches: string[] }[]} */
export const THEME_PRESETS = [
  {
    id: 'navy',
    name: '深蓝',
    blurb: '默认：深色侧栏 + 海军蓝',
    swatches: ['#0f1b33', '#163a7a', '#e6edf7', '#f4f6fa'],
  },
  {
    id: 'slate-teal',
    name: '青石',
    blurb: '浅侧栏 + 青石蓝绿（如图）',
    swatches: ['#f2f6f7', '#2f7380', '#a12621', '#eaf4f6'],
  },
  {
    id: 'forest',
    name: '松绿',
    blurb: '深绿侧栏 + 松针绿',
    swatches: ['#163528', '#2f6b4f', '#e5f0ea', '#f3f7f4'],
  },
  {
    id: 'wine',
    name: '绛红',
    blurb: '酒红侧栏 + 绛红主色',
    swatches: ['#2a151b', '#8b3a4a', '#f5e8eb', '#faf6f6'],
  },
  {
    id: 'amber',
    name: '琥珀',
    blurb: '暖棕侧栏 + 琥珀橙',
    swatches: ['#2a2116', '#b56a1e', '#f6ebdc', '#faf7f2'],
  },
  {
    id: 'graphite',
    name: '石墨',
    blurb: '深色界面 + 冷蓝点缀',
    swatches: ['#0c0e12', '#5b8fd9', '#1a1f27', '#12151a'],
  },
]

const themeIds = new Set(THEME_PRESETS.map((t) => t.id))
const themeId = ref(readStoredTheme())

function readStoredTheme() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw && themeIds.has(raw)) return raw
  } catch {
    /* ignore */
  }
  return DEFAULT_THEME
}

export function applyTheme(id) {
  const next = themeIds.has(id) ? id : DEFAULT_THEME
  themeId.value = next
  document.documentElement.setAttribute('data-theme', next)
  try {
    localStorage.setItem(STORAGE_KEY, next)
  } catch {
    /* ignore */
  }
}

/** Call once before mount to avoid a flash of the wrong palette. */
export function initTheme() {
  applyTheme(readStoredTheme())
}

export function useTheme() {
  const current = computed(() => THEME_PRESETS.find((t) => t.id === themeId.value) || THEME_PRESETS[0])
  return {
    themeId,
    current,
    presets: THEME_PRESETS,
    setTheme: applyTheme,
  }
}
