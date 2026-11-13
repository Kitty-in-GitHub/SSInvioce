/** Clipboard paste helpers: images from screenshots and files copied from Explorer. */

export function clipboardFiles(event) {
  const dt = event?.clipboardData
  if (!dt) return []
  const files = []
  const seen = new Set()
  if (dt.items && dt.items.length) {
    for (const item of dt.items) {
      if (item.kind !== 'file') continue
      const file = item.getAsFile()
      if (!file) continue
      const key = `${file.name}|${file.size}|${file.type}`
      if (seen.has(key)) continue
      seen.add(key)
      files.push(file)
    }
  }
  if (!files.length && dt.files && dt.files.length) {
    for (const file of dt.files) files.push(file)
  }
  return files
}

export function isEditableTarget(target) {
  if (!target) return false
  const tag = (target.tagName || '').toLowerCase()
  return tag === 'input' || tag === 'textarea' || target.isContentEditable === true
}

export function hasOpenModal() {
  return !!document.querySelector('.modal-backdrop')
}

/** Give clipboard bitmaps (Chrome/Firefox name them image.png) a readable name. */
export function normalizePastedFile(file, index = 0) {
  if (!file) return file
  const generic = !file.name || /^image\.(png|jpe?g|webp)$/i.test(file.name) || /^blob$/i.test(file.name)
  if (!generic) return file
  const type = file.type || 'image/png'
  const ext = type.includes('jpeg')
    ? 'jpg'
    : type.includes('webp')
      ? 'webp'
      : type.includes('gif')
        ? 'gif'
        : 'png'
  const d = new Date()
  const p = (n) => String(n).padStart(2, '0')
  const stamp = `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}_${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`
  const suffix = index > 0 ? `_${index + 1}` : ''
  return new File([file], `粘贴截图_${stamp}${suffix}.${ext}`, { type })
}
