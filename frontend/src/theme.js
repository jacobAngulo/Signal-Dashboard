// Design tokens for the places CSS can't reach: SVG attributes and the props
// recharts wants as literal colour strings.
//
// styles.css owns the values -- these are read back off :root so the charts and
// the stylesheet can never drift apart. The fallbacks below are only used if a
// custom property is missing (a browser that failed to apply the stylesheet, or
// a unit test rendering without it), and they exist so a chart still draws in
// the right hues rather than defaulting to black.
const FALLBACK = {
  '--canvas': '#0A0B0C',
  '--inset': '#101315',
  '--hair': '#15181B',
  '--rule': '#1F2327',
  '--rule-strong': '#2C3136',
  '--text': '#E6E9EC',
  '--muted': '#7A828A',
  '--faint': '#4F565C',
  '--dim': '#3F464C',
  '--up': 'oklch(0.76 0.15 152)',
  '--up-text': 'oklch(0.80 0.15 152)',
  '--down': 'oklch(0.68 0.17 22)',
  '--down-text': 'oklch(0.76 0.16 22)',
  '--pending': 'oklch(0.82 0.13 85)',
  '--pending-text': 'oklch(0.88 0.12 85)',
  '--lstm': 'oklch(0.72 0.13 258)',
  '--lstm-text': 'oklch(0.80 0.12 258)',
  '--intrinsic': 'oklch(0.72 0.13 300)',
  '--intrinsic-text': 'oklch(0.80 0.12 300)',
  '--foundry': 'oklch(0.72 0.13 195)',
  '--foundry-text': 'oklch(0.80 0.12 195)',
}

const cache = new Map()

export function token(name) {
  if (cache.has(name)) return cache.get(name)
  let value = ''
  try {
    value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  } catch {
    // No document -- fall through to the literal.
  }
  // Only a real read is worth caching. main.jsx imports styles.css after the
  // component tree, so a token asked for during module evaluation would see
  // nothing; caching that miss would pin the fallback for the whole session.
  if (!value) return FALLBACK[name] || '#888'
  cache.set(name, value)
  return value
}

// Named accessors, so call sites read as intent rather than as a variable name.
export const C = {
  get canvas() { return token('--canvas') },
  get inset() { return token('--inset') },
  get hair() { return token('--hair') },
  get rule() { return token('--rule') },
  get ruleStrong() { return token('--rule-strong') },
  get text() { return token('--text') },
  get muted() { return token('--muted') },
  get faint() { return token('--faint') },
  get dim() { return token('--dim') },
  get up() { return token('--up') },
  get upText() { return token('--up-text') },
  get down() { return token('--down') },
  get downText() { return token('--down-text') },
  get pending() { return token('--pending') },
  get pendingText() { return token('--pending-text') },
}

// Direction of a return, as a stroke/fill colour. Null and zero are neutral --
// 2a keeps green and red reserved for money that actually moved.
export const signColor = (v) =>
  v === null || v === undefined ? C.dim : v > 0 ? C.up : v < 0 ? C.down : C.dim
