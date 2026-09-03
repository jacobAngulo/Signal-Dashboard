import React, { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api.js'
import { fmtNum, fmtPct, signCls } from '../format.js'
import { navigate } from '../nav.js'
import {
  Card, DateLink, EmptyState, ErrorBox, PageHeader, PerfTag, Spinner,
  TickerLink,
} from '../ui.jsx'
import SignalDetail from '../SignalDetail.jsx'
import LstmWindows from './LstmWindows.jsx'

const PAGE = 100
const NO_VALUE = '(no value)'
const OTHER = '(other)'

// The producer toggle's positions before the server has answered. The payload
// carries the authoritative list -- including which ones are wired up -- but
// the control has to render on the first paint too, and a toggle that appears
// one position at a time as data lands is worse than one that starts complete.
const FALLBACK_PRODUCERS = [
  { key: 'lstm', label: 'LSTM', available: true },
  { key: 'intrinsic', label: 'Intrinsic', available: false },
  { key: 'foundry', label: 'Foundry', available: false },
]

const num = (v) => (v === null || v === undefined || Number.isNaN(Number(v)) ? null : Number(v))
const Ret = ({ v }) => <span className={signCls(num(v))}>{fmtPct(num(v))}</span>
const pp = (v) => (v === null || v === undefined ? '–' : `${(v * 100).toFixed(1)}pp`)

// Value formatting for facet readouts. The catalogue's `kind` already says
// what a field is; this only decides how many characters it takes to say it.
const fmtVal = (kind, v) => {
  if (v === null || v === undefined) return '–'
  if (kind === 'pct') return `${(v * 100).toFixed(1)}%`
  if (kind === 'money') return v >= 1000 ? `$${Math.round(v).toLocaleString()}` : `$${v.toFixed(2)}`
  if (kind === 'discrete') return String(v)
  return Number(v).toPrecision(3).replace(/\.?0+$/, '')
}

// ---------------------------------------------------------------- facet state
//
// One entry per touched vector. Untouched vectors have no entry at all, which
// is what makes "reset" and "is anything on?" trivial, and keeps the request
// free of predicates that would not narrow anything.
//
// numeric  -> { lo, hi, noValue }   lo/hi null = unbounded on that side
// category -> { off: [values...] }  values the user has switched off

/**
 * Turn facet state into the `where` clauses the endpoint takes.
 *
 * Categorical exclusion becomes an `in` over what is left, and `in` cannot
 * match a blank cell -- so switching any value off also drops the rows that
 * have no value at all. That is surfaced on the (no value) chip rather than
 * silently applied.
 */
function encode(facets, domains) {
  const out = []
  for (const [key, state] of Object.entries(facets)) {
    const domain = domains?.[key]
    if (!domain) continue
    if (domain.kind === 'numeric' || domain.kind === 'date') {
      if (state.lo !== null && state.lo !== undefined && state.lo !== '') out.push(`${key}:gte:${state.lo}`)
      if (state.hi !== null && state.hi !== undefined && state.hi !== '') out.push(`${key}:lte:${state.hi}`)
      if (state.noValue === false) out.push(`${key}:notnull`)
    } else {
      const off = new Set(state.off || [])
      if (!off.size) continue
      const kept = domain.values.map((v) => v.value).filter((v) => !off.has(v))
      // Everything switched off would be an empty `in`, which the server
      // rejects. Say "nothing from this vector" as a contradiction instead of
      // a sentinel value: no row can be both null and not null, and no real
      // value can collide with it.
      if (kept.length) out.push(`${key}:in:${kept.join('|')}`)
      else out.push(`${key}:isnull`, `${key}:notnull`)
    }
  }
  return out
}

const isTouched = (state, domain) => {
  if (!state || !domain) return false
  if (domain.kind === 'numeric' || domain.kind === 'date') {
    return (state.lo !== null && state.lo !== undefined && state.lo !== '')
      || (state.hi !== null && state.hi !== undefined && state.hi !== '')
      || state.noValue === false
  }
  return Boolean(state.off?.length)
}

// ------------------------------------------------------------------ histogram

/**
 * The distribution behind a numeric facet's track, with the selected span lit.
 *
 * Drawn over the domain's 1st-99th percentile rather than its full range: one
 * $6,380 close otherwise squashes every other row into the leftmost pixel and
 * the control cannot be aimed. Rows outside that clip are still included --
 * the counts either side say how many.
 */
function Histogram({ domain, lo, hi }) {
  const bins = domain.bins || []
  const peak = Math.max(1, ...bins)
  const span = (domain.clip_hi - domain.clip_lo) || 1
  const at = (v) => Math.max(0, Math.min(1, (v - domain.clip_lo) / span))
  const from = lo === null || lo === undefined ? 0 : at(lo)
  const to = hi === null || hi === undefined ? 1 : at(hi)
  return (
    <svg className="facet-hist" viewBox="0 0 100 20" preserveAspectRatio="none"
         aria-hidden="true">
      {bins.map((n, i) => {
        const x = (i / bins.length) * 100
        const w = 100 / bins.length
        // A bin holding one row is still somewhere the handle can land, so it
        // gets a visible stub instead of a sub-pixel nothing. Sparse fields --
        // `window_sessions` puts everything in three of twenty-four bins --
        // were otherwise a blank strip with one bar in it.
        const h = n === 0 ? 0 : Math.max(1.4, (n / peak) * 18.6)
        const mid = (i + 0.5) / bins.length
        const inRange = mid >= from && mid <= to
        return <rect key={i} x={x} y={19.4 - h} width={w * 0.86} height={h}
                     className={inRange ? 'hist-in' : 'hist-out'} />
      })}
      {/* A rect, not a line: preserveAspectRatio="none" scales a stroke
          unevenly and the baseline comes out wedge-shaped. */}
      <rect x="0" y="19.4" width="100" height="0.6" className="hist-base" />
    </svg>
  )
}

// ---------------------------------------------------------------- range track

/**
 * A step that reads like a number a person would type.
 *
 * The server's step is the field's own resolution, which on `close` is
 * 1.3999784 -- every drag produced a bound like $743.19199 and the readout was
 * unreadable. Aim for a couple of hundred stops across the visible span and
 * round to 1/2/5, the way an axis is ticked.
 */
function niceStep(domain, kind) {
  if (kind === 'discrete') return 1
  const raw = (domain.clip_hi - domain.clip_lo) / 200
  if (!(raw > 0)) return domain.step || 0.001
  const mag = 10 ** Math.floor(Math.log10(raw))
  const n = raw / mag
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * mag
}

/**
 * Two handles on one track.
 *
 * Not two stacked `<input type="range">`. That arrangement needs
 * `pointer-events: none` on the inputs and `auto` on
 * `::-webkit-slider-thumb` so the covered handle stays reachable, and
 * Chromium does not restore hit-testing on the pseudo-element:
 * `elementFromPoint` over every part of the track returned the wrapper, so
 * neither handle could be grabbed with a mouse at all and the control was
 * keyboard-only without saying so.
 *
 * Owning the pointer maths also buys the two things the native pair could not
 * do: the whole track is a target rather than a 12px circle, and the drag
 * reports continuously while committing once, on release, so a slider is one
 * request instead of one per pixel.
 */
function RangeSlider({ label, min, max, step, lo, hi, format, onInput, onCommit }) {
  const trackRef = useRef(null)
  // Refs, not state, for everything the pointer handlers read back. A click is
  // pointerdown and pointerup in two separate events with no render guaranteed
  // between them, so a handler closing over state read the value from before
  // the press and the commit never fired. State here is only the cursor.
  const dragRef = useRef(null)
  const valueRef = useRef([lo, hi])
  const [dragging, setDragging] = useState(false)
  valueRef.current = dragRef.current ? valueRef.current : [lo, hi]
  const span = max - min || 1
  const pct = (v) => ((v - min) / span) * 100

  // Snapped to multiples of the step itself, not to offsets from the domain's
  // low end: `close` starts at $0.0116, so stepping from there put every bound
  // at $490.0116 and the readout was unreadable. Rounded to the step's own
  // precision, or binary float noise puts it back.
  const decimals = Math.max(0, Math.min(12, -Math.floor(Math.log10(step))))
  const snap = (value) => Number(
    Math.max(min, Math.min(max, Math.round(value / step) * step)).toFixed(decimals))

  const valueAt = (clientX) => {
    const rect = trackRef.current.getBoundingClientRect()
    return snap(min + Math.max(0, Math.min(1, (clientX - rect.left) / (rect.width || 1))) * span)
  }

  // The handles cannot cross: each one clamps against where the other is.
  const move = (which, value) => {
    const [curLo, curHi] = valueRef.current
    const next = which === 'lo'
      ? [Math.min(value, curHi), curHi]
      : [curLo, Math.max(value, curLo)]
    valueRef.current = next
    onInput(next[0], next[1])
    return next
  }

  const pick = (value) => {
    const [curLo, curHi] = valueRef.current
    const dLo = Math.abs(value - curLo)
    const dHi = Math.abs(value - curHi)
    // Equidistant means the handles are stacked -- send the one that can move
    // towards the click, so a pair parked together never locks up.
    if (dLo === dHi) return value >= curHi ? 'hi' : 'lo'
    return dLo < dHi ? 'lo' : 'hi'
  }

  const onPointerDown = (e) => {
    if (e.button) return
    const value = valueAt(e.clientX)
    dragRef.current = pick(value)
    setDragging(true)
    e.currentTarget.setPointerCapture(e.pointerId)
    move(dragRef.current, value)
  }

  const onPointerMove = (e) => {
    if (dragRef.current) move(dragRef.current, valueAt(e.clientX))
  }

  const stop = (e) => {
    if (!dragRef.current) return
    dragRef.current = null
    setDragging(false)
    if (e.currentTarget.hasPointerCapture?.(e.pointerId)) {
      e.currentTarget.releasePointerCapture(e.pointerId)
    }
    onCommit(valueRef.current[0], valueRef.current[1])
  }

  const onKeyDown = (which) => (e) => {
    const big = (max - min) / 10
    const delta = { ArrowLeft: -step, ArrowDown: -step, ArrowRight: step, ArrowUp: step,
                    PageDown: -big, PageUp: big }[e.key]
    const jump = { Home: min, End: max }[e.key]
    if (delta === undefined && jump === undefined) return
    e.preventDefault()
    const from = which === 'lo' ? valueRef.current[0] : valueRef.current[1]
    const next = move(which, snap(jump !== undefined ? jump : from + delta))
    onCommit(next[0], next[1])
  }

  // No stopPropagation on the handle: the track's own pointerdown is what
  // starts the drag and takes pointer capture, and swallowing the event there
  // meant pressing directly on a handle -- the obvious gesture -- did nothing.
  const handle = (which, value) => (
    <button type="button" className="range-handle" style={{ left: `${pct(value)}%` }}
            role="slider" aria-label={`${label} ${which === 'lo' ? 'minimum' : 'maximum'}`}
            aria-valuemin={min} aria-valuemax={max} aria-valuenow={value}
            aria-valuetext={format(value)} onKeyDown={onKeyDown(which)} />
  )

  return (
    <div ref={trackRef} className={`facet-range${dragging ? ' is-dragging' : ''}`}
         onPointerDown={onPointerDown} onPointerMove={onPointerMove}
         onPointerUp={stop} onPointerCancel={stop}>
      <span className="range-rail" aria-hidden="true" />
      <span className="range-fill" aria-hidden="true"
            style={{ left: `${pct(lo)}%`, width: `${Math.max(0, pct(hi) - pct(lo))}%` }} />
      {handle('lo', lo)}
      {handle('hi', hi)}
    </div>
  )
}

// ---------------------------------------------------------------------- facet

function NumericFacet({ vector, domain, state, onChange }) {
  const lo = state?.lo ?? null
  const hi = state?.hi ?? null
  const noValue = state?.noValue !== false
  const step = niceStep(domain, vector.kind)
  // Handles travel over the clipped body. Parked at an end means unbounded on
  // that side, so an untouched facet includes the outliers it cannot show.
  const sliderLo = lo === null ? domain.clip_lo : lo
  const sliderHi = hi === null ? domain.clip_hi : hi

  // Where the handles are while a drag is in flight. The committed state only
  // moves on release, so one drag is one request rather than one per pixel --
  // and the readout underneath still tracks the handle the whole way.
  const [draft, setDraft] = useState(null)
  const shownLo = draft ? draft[0] : sliderLo
  const shownHi = draft ? draft[1] : sliderHi

  const commit = (nextLo, nextHi) => onChange({
    ...state,
    lo: nextLo <= domain.clip_lo ? null : nextLo,
    hi: nextHi >= domain.clip_hi ? null : nextHi,
  })

  // Typing is committed on blur or Enter, not per keystroke: "0.2" arrives as
  // "0", "0." and "0.2", and the first two are a slice nobody asked for.
  const [text, setText] = useState(null)
  const typed = (which) => (raw) => {
    const value = raw === '' ? null : Number(raw)
    if (raw !== '' && Number.isNaN(value)) return
    onChange({ ...state, [which]: value })
  }

  // What the boxes read: the handle's live position while a drag is in
  // flight, the committed bound otherwise, and blank at either end because
  // parked means unbounded. Without the draft the number lagged the handle by
  // the whole gesture and there was nothing to aim with.
  const box = (i, committed) => {
    const value = draft ? draft[i] : committed
    if (value === null || value === undefined) return ''
    if (i === 0 && value <= domain.clip_lo) return ''
    if (i === 1 && value >= domain.clip_hi) return ''
    return value
  }

  const fmt = (v) => fmtVal(vector.kind, v)
  // The number box holds what the field holds, so its placeholder has to be
  // in that unit too: a `pct` hint of "58.4%" over an input whose value is
  // 0.584 invites typing 58.4 and asking for a slice 100x too wide.
  const hint = (v) => (vector.kind === 'pct' ? String(Number(v.toPrecision(3))) : fmt(v))

  return (
    <>
      <Histogram domain={domain} lo={shownLo === domain.clip_lo ? null : shownLo}
                 hi={shownHi === domain.clip_hi ? null : shownHi} />
      <RangeSlider label={vector.label} min={domain.clip_lo} max={domain.clip_hi}
                   step={step} lo={shownLo} hi={shownHi} format={fmt}
                   onInput={(nextLo, nextHi) => setDraft([nextLo, nextHi])}
                   onCommit={(nextLo, nextHi) => { commit(nextLo, nextHi); setDraft(null) }} />
      <div className="facet-bounds">
        <input type="number" step={step}
               value={text?.lo !== undefined ? text.lo : box(0, lo)}
               placeholder={hint(domain.min)}
               aria-label={`${vector.label} lower bound`}
               onChange={(e) => setText({ ...text, lo: e.target.value })}
               onBlur={(e) => { typed('lo')(e.target.value); setText(null) }}
               onKeyDown={(e) => { if (e.key === 'Enter') e.currentTarget.blur() }} />
        <span className="muted">to</span>
        <input type="number" step={step}
               value={text?.hi !== undefined ? text.hi : box(1, hi)}
               placeholder={hint(domain.max)}
               aria-label={`${vector.label} upper bound`}
               onChange={(e) => setText({ ...text, hi: e.target.value })}
               onBlur={(e) => { typed('hi')(e.target.value); setText(null) }}
               onKeyDown={(e) => { if (e.key === 'Enter') e.currentTarget.blur() }} />
      </div>
      {/* Rendered whenever the field has outliers, not only once a handle has
          moved: appearing on the first drag shifted every facet below it down
          a line, under the cursor that caused it. */}
      {(domain.below > 0 || domain.above > 0) && (
        <div className="facet-tails muted">
          {domain.below > 0 && <span>{domain.below.toLocaleString()} below</span>}
          {domain.below > 0 && domain.above > 0 && <span> · </span>}
          {domain.above > 0 && <span>{domain.above.toLocaleString()} above</span>}
          <span> the track, kept until a handle moves</span>
        </div>
      )}
      {domain.missing > 0 && (
        <label className="facet-null">
          <input type="checkbox" checked={noValue}
                 onChange={(e) => onChange({ ...state, noValue: e.target.checked })} />
          keep {domain.missing.toLocaleString()} with no value
        </label>
      )}
    </>
  )
}

// ISO dates compare correctly as strings, so a date facet is two bounds and
// the same gte/lte the numeric one uses. It is a separate control because the
// alternative -- one chip per trading day -- was seventy-five chips.
function DateFacet({ vector, domain, state, onChange }) {
  return (
    <>
      <div className="facet-bounds">
        <input type="date" value={state?.lo || ''} min={domain.min} max={domain.max}
               aria-label={`${vector.label} from`}
               onChange={(e) => onChange({ ...state, lo: e.target.value || null })} />
        <span className="muted">to</span>
        <input type="date" value={state?.hi || ''} min={domain.min} max={domain.max}
               aria-label={`${vector.label} to`}
               onChange={(e) => onChange({ ...state, hi: e.target.value || null })} />
      </div>
      <div className="facet-tails muted">
        {domain.min} – {domain.max} · {domain.distinct.toLocaleString()} days
      </div>
    </>
  )
}

// Beyond this a chip list is a wall, not a control. `ticker` has 289 values.
const CHIP_LIMIT = 10

function CategoryFacet({ vector, domain, state, onChange }) {
  const [all, setAll] = useState(false)
  const off = new Set(state?.off || [])
  const toggle = (value) => {
    const next = new Set(off)
    if (next.has(value)) next.delete(value)
    else next.add(value)
    onChange({ ...state, off: [...next] })
  }
  // Anything switched off stays visible even when it is past the cut, so a
  // collapsed facet can never hide the reason the slice is narrow.
  const shown = all ? domain.values
    : domain.values.filter((item, i) => i < CHIP_LIMIT || off.has(item.value))
  const hidden = domain.values.length - shown.length
  // Same problem as the cards: `price_basis` values agree for sixty
  // characters, so the chips all read "economic_value_per_initi…" and the
  // control cannot be used. Lift the shared head into the header.
  const trim = trimCommon(domain.values.map((v) => v.value))
  return (
    <>
      {sharedLabel(trim) && (
        <div className="facet-prefix muted">
          every value: {sharedLabel(trim)}
        </div>
      )}
      <div className="facet-chips">
        {shown.map((item) => (
          <button key={item.value} type="button"
                  className={`chip${off.has(item.value) ? ' is-off' : ''}`}
                  aria-pressed={!off.has(item.value)}
                  onClick={() => toggle(item.value)}>
            <span className="chip-label" title={item.value}>
              {elide(trimmed(trim, item.value), 30)}
            </span>
            <span className="chip-n">{item.n.toLocaleString()}</span>
          </button>
        ))}
        {hidden > 0 && (
          <button type="button" className="chip chip-more" onClick={() => setAll(true)}>
            +{hidden.toLocaleString()} more
          </button>
        )}
        {all && domain.values.length > CHIP_LIMIT && (
          <button type="button" className="chip chip-more" onClick={() => setAll(false)}>
            show fewer
          </button>
        )}
      </div>
      {domain.missing > 0 && (
        // `in` cannot match a blank cell, so any exclusion here also drops the
        // rows that have no value. Said out loud rather than applied quietly.
        <div className="facet-tails muted"
             title={off.size
               ? 'An `in` filter cannot match a blank cell, so switching any chip off drops these too.'
               : 'Kept while every chip is on.'}>
          {domain.missing.toLocaleString()} with no value:{' '}
          {off.size ? 'dropped' : 'kept'}
        </div>
      )}
    </>
  )
}

function Facet({ vector, domain, state, onChange, onReset }) {
  const touched = isTouched(state, domain)
  return (
    <section id={`facet-${vector.key}`} className={`facet${touched ? ' is-touched' : ''}`}>
      <header className="facet-head">
        <h3 title={vector.key}>{vector.label}</h3>
        {touched
          ? <button type="button" className="text-btn" onClick={onReset}>reset</button>
          : <span className="facet-kind muted">{vector.kind}</span>}
      </header>
      {domain.kind === 'numeric'
        ? <NumericFacet vector={vector} domain={domain} state={state} onChange={onChange} />
        : domain.kind === 'date'
          ? <DateFacet vector={vector} domain={domain} state={state} onChange={onChange} />
          : <CategoryFacet vector={vector} domain={domain} state={state} onChange={onChange} />}
    </section>
  )
}

// ---------------------------------------------------------------- small multiple

/**
 * One vector's buckets against the chosen outcome.
 *
 * Bars are scaled to the widest bucket in this card, not across the grid: the
 * question a card answers is which of *its* buckets did better, and a shared
 * scale would flatten every card that is not the day's biggest mover into a
 * row of stubs. The spread badge is what compares cards.
 */
// A card is a glance, not a table. `ticker` alone folds to twenty buckets, and
// twenty rows in a 290px card is a scroll bar with a heading on it.
const CARD_ROWS = 8

/**
 * The part of a bucket label that actually differs from its neighbours.
 *
 * `price_basis` values are 90-character provenance strings that agree for the
 * first 60: truncating them to card width produced four rows reading
 * "ECONOMIC_VALUE…", which is one label repeated, not four buckets. Strip what
 * every bucket in the card shares and the tail that distinguishes them
 * survives the truncation.
 */
function trimCommon(labels) {
  const none = { cut: 0, tailCut: 0, prefix: '', suffix: '' }
  const real = labels.filter((l) => l !== NO_VALUE && l !== OTHER)
  if (real.length < 2) return none
  const first = real[0]
  let cut = 0
  while (cut < first.length && real.every((l) => l[cut] === first[cut])) cut += 1
  // Only worth doing when the shared head is long enough to be the whole
  // problem, and never when it would leave nothing behind.
  if (cut < 12 || real.some((l) => l.length - cut < 2)) cut = 0
  // The head is not all these strings share: every `price_basis` value also
  // ends `|policy=dashboard`, and with both ends off, four of its five buckets
  // are a single word. Measured against what the head trim left, so the two
  // can never overlap and consume a label whole.
  const rest = real.map((l) => l.slice(cut))
  const shortest = Math.min(...rest.map((l) => l.length))
  let tailCut = 0
  while (tailCut < shortest - 1
         && rest.every((l) => l[l.length - 1 - tailCut] === rest[0][rest[0].length - 1 - tailCut])) {
    tailCut += 1
  }
  if (tailCut < 8) tailCut = 0
  if (!cut && !tailCut) return none
  return {
    cut,
    tailCut,
    prefix: first.slice(0, cut),
    suffix: tailCut ? first.slice(first.length - tailCut) : '',
  }
}

// What is left of a bucket label once the ends every bucket shares are off it.
const trimmed = (trim, label) => (
  label === NO_VALUE || label === OTHER
    ? label
    : label.slice(trim.cut, trim.tailCut ? label.length - trim.tailCut : undefined)
)

// The one line saying what was lifted off every label, so the rows stay
// readable without the provenance becoming unrecoverable.
const sharedLabel = (trim) => (trim.cut || trim.tailCut ? `${trim.prefix}\u2026${trim.suffix}` : '')

/**
 * Elide the middle, not the end.
 *
 * CSS truncation cuts the right-hand side, which is exactly where these labels
 * differ: two `price_basis` buckets both rendered "confirmed|policy=dashbo…",
 * so the card showed one label twice and neither could be identified. Keeping
 * both ends keeps them apart.
 */
function elide(text, max) {
  if (text.length <= max) return text
  const head = Math.ceil((max - 1) * 0.6)
  return `${text.slice(0, head)}\u2026${text.slice(text.length - (max - 1 - head))}`
}

function VectorCard({ entry, outcome, minBucket }) {
  const [all, setAll] = useState(false)
  const groups = entry.groups || []
  const peak = Math.max(1e-9, ...groups.map((g) => Math.abs(g.avg ?? 0)))
  // Show the extremes rather than the first eight: the top and bottom of a
  // bucket list is where the finding is, and an alphabetical head would hide
  // it. Categorical groups arrive sorted by size, numeric ones by value, so
  // both ends carry meaning either way.
  // Head and tail of the buckets that measured something, not of the raw list.
  // A bucket with no measured rows is not a finding at either end, and on the
  // date vectors -- where the newest days have no five-day return yet -- the
  // literal head was four identical blank rows out of eight. They are still
  // in the card, one click away.
  const scored = groups.filter((g) => g.measured > 0)
  const pool = scored.length >= 2 ? scored : groups
  const collapsed = pool.length <= CARD_ROWS ? pool
    : [...pool.slice(0, Math.ceil(CARD_ROWS / 2)),
       ...pool.slice(-Math.floor(CARD_ROWS / 2))]
  const shown = all ? groups : collapsed
  const hidden = groups.length - collapsed.length
  const trim = trimCommon(groups.map((g) => g.label))
  // A spread is only a finding for a vector that is in the ranking. On the
  // ones kept out of it -- fields derived from the returns being measured, and
  // pure time axes -- the number is arithmetic about itself, so the badge says
  // why instead of quoting it.
  const rankable = entry.scannable && entry.spread !== null && entry.spread !== undefined
  return (
    <section className={`vcard${entry.scannable ? '' : ' is-context'}`}>
      <header className="vcard-head">
        <h3 title={entry.key}>{entry.label}</h3>
        {rankable ? (
          <span className="vcard-spread" title={`thinnest bucket compared: ${entry.support} rows`}>
            {pp(entry.spread)}
          </span>
        ) : (
          <span className="vcard-flat muted"
                title={entry.excluded_reason
                  || `Fewer than two buckets reached ${minBucket} measured rows.`}>
            {entry.scannable ? 'not ranked' : 'context'}
          </span>
        )}
      </header>
      {/* On its own line rather than squeezed into the header: at card width
          the three of them together left about eleven characters each. */}
      {sharedLabel(trim) && (
        <div className="vcard-prefix muted">
          every bucket: {sharedLabel(trim)}
        </div>
      )}
      <table className="vcard-table">
        <caption className="sr-only">{entry.label} by {outcome}</caption>
        <tbody>
          {shown.map((g) => {
            const avg = num(g.avg)
            // A bucket that moved a little still moved: without a floor the
            // bar rounds to nothing and reads the same as one with no rows.
            const width = avg === null || avg === 0
              ? 0 : Math.max(1.5, (Math.abs(avg) / peak) * 50)
            // An unmeasured bucket is not a finding either -- same treatment as
            // the folded ones, so the eye skips all of them together.
            const dim = g.label === NO_VALUE || g.label === OTHER || !g.measured
            return (
              <tr key={g.key} className={dim ? 'is-dim' : undefined}>
                <th scope="row" title={g.label}>{elide(trimmed(trim, g.label), 20)}</th>
                <td className="vcard-bar">
                  {/* Zero sits at the middle, so sign reads as direction
                      before the number is read at all. */}
                  <span className="bar-axis" aria-hidden="true" />
                  {avg !== null && (
                    <span className={`bar ${avg < 0 ? 'bar-neg' : 'bar-pos'}`}
                          style={avg < 0 ? { right: '50%', width: `${width}%` }
                                         : { left: '50%', width: `${width}%` }} />
                  )}
                </td>
                <td className="vcard-avg"><Ret v={g.avg} /></td>
                <td className="vcard-n muted">{g.measured.toLocaleString()}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
      {hidden > 0 && (
        <button type="button" className="text-btn vcard-more"
                onClick={() => setAll(!all)}>
          {all ? 'show fewer' : `show ${hidden} more bucket${hidden === 1 ? '' : 's'}`}
        </button>
      )}
    </section>
  )
}

// -------------------------------------------------------------------- the page

const ROW_COLUMNS = [
  { key: 'date', label: 'Day', render: (r) => <DateLink d={r.date} /> },
  { key: 'ticker', label: 'Ticker', render: (r) => <TickerLink t={r.ticker} /> },
  { key: 'horizon', label: 'Horizon' },
  { key: 'adj_prob', label: 'Adj prob', align: 'right', render: (r) => fmtPct(r.adj_prob, 2) },
  { key: 'volatility', label: 'Volatility', align: 'right', render: (r) => fmtNum(r.volatility) },
  { key: 'close', label: 'Signal px', align: 'right', render: (r) => fmtNum(r.close, 2) },
  { key: 'ret_5d', label: '5d', align: 'right', render: (r) => <Ret v={r.ret_5d} /> },
  { key: 'ret_since', label: 'Since', align: 'right', render: (r) => <Ret v={r.ret_since} /> },
  { key: 'status_perf', label: 'Status', render: (r) => (
    <PerfTag status={r.status_perf} stale={r.px_stale} asOf={r.last_date}
             actionWarning={r.has_action_warning} statusBasis={r.status_basis} />
  ) },
]

/**
 * Every vector, controllable at once.
 *
 * The curated view (`LstmWindows`, the former LSTM tab, still reachable from
 * the toggle) groups by one vector at a time because it was built around a
 * dropdown. This page has no dropdown and no chosen vector: the left rail is
 * one live control per vector, and the right side is every vector bucketed
 * against the outcome, recomputed over whatever the rail currently selects.
 *
 * Filtering and bucketing run on the server -- the full enriched history is
 * ~12k candidates, and the cards have to describe the whole slice rather than
 * the hundred rows a page of the table would carry.
 */
export default function Lab({ producer = 'lstm', view = 'free' }) {
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)
  const [loading, setLoading] = useState(true)
  const [outcome, setOutcome] = useState('ret_5d')
  const [buckets, setBuckets] = useState(5)
  const [minBucket, setMinBucket] = useState(20)
  const [facets, setFacets] = useState({})
  const [q, setQ] = useState('')
  const [showRows, setShowRows] = useState(false)
  // The rail's order, taken from the first answer for this producer and then
  // left alone. The server re-ranks every vector by spread on every request,
  // so ordering the rail live meant one bound change rewrote the whole list --
  // the control you had just touched jumped several hundred pixels and the
  // rest rearranged under the cursor.
  const [railOrder, setRailOrder] = useState(null)
  const [sort, setSort] = useState('date')
  const [dir, setDir] = useState('desc')
  const [offset, setOffset] = useState(0)
  const [sel, setSel] = useState(null)

  // Domains ride along with the payload, but the request is built from facet
  // state that already knows its own shape, so encoding needs the domains from
  // the response that is currently on screen. On the very first request there
  // are none and there is nothing switched on either.
  const domains = data?.domains
  const where = useMemo(() => encode(facets, domains), [facets, domains])
  const whereKey = where.join(' ')

  useEffect(() => { setOffset(0) }, [whereKey, sort, dir, outcome])
  useEffect(() => { setRailOrder(null) }, [producer])

  useEffect(() => {
    // The curated view is `LstmWindows` and fetches its own data.
    if (view === 'curated') return undefined
    const controller = new AbortController()
    setLoading(true)
    api('lab', {
      producer,
      where: where.length ? where : undefined,
      outcome, buckets, min_bucket: minBucket,
      sort, dir, limit: showRows ? PAGE : 1, offset,
    }, { signal: controller.signal })
      .then((next) => {
        setData(next)
        setErr(null)
        setRailOrder((current) => current
          || (next.breakdowns?.length ? next.breakdowns.map((b) => b.key) : null))
      })
      .catch((nextErr) => { if (nextErr.name !== 'AbortError') setErr(nextErr) })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [producer, view, whereKey, outcome, buckets, minBucket, showRows, sort, dir, offset])

  const producers = data?.producers?.length ? data.producers : FALLBACK_PRODUCERS
  const producerMeta = producers.find((p) => p.key === producer)
  const curated = producer === 'lstm' && view === 'curated'

  const chrome = (
    <>
      {/* The producer and the shape both have a toggle immediately below, so
          naming either one here would only restate a control. */}
      <PageHeader title="Vector lab" />
      <Card className="lab-nav">
        <div className="lab-toggles">
          <div className="seg" role="group" aria-label="Producer">
            {producers.map((item) => (
              <button key={item.key} type="button"
                      className={`seg-btn${item.key === producer ? ' is-on' : ''}`}
                      aria-pressed={item.key === producer}
                      title={item.available ? undefined : 'Needs development'}
                      onClick={() => navigate('lab', item.key)}>
                {item.label}
                {!item.available && <span className="seg-todo">needs work</span>}
              </button>
            ))}
          </div>
          {producer === 'lstm' && (
            <div className="seg" role="group" aria-label="View">
              <button type="button" className={`seg-btn${curated ? '' : ' is-on'}`}
                      aria-pressed={!curated}
                      onClick={() => navigate('lab', producer)}>Free-form</button>
              <button type="button" className={`seg-btn${curated ? ' is-on' : ''}`}
                      aria-pressed={curated}
                      onClick={() => navigate('lab', producer, 'curated')}>Curated</button>
            </div>
          )}
        </div>
      </Card>
    </>
  )

  if (curated) return <div className="lab-page">{chrome}<div className="lab-page-scroll"><LstmWindows embedded /></div></div>
  if (err) return <div className="lab-page">{chrome}<ErrorBox err={err} /></div>
  if (!data) return <div className="lab-page">{chrome}<Spinner /></div>
  if (data.available === false) {
    return (
      <div className="lab-page">
        {chrome}
        <Card>
          <EmptyState title={`${producerMeta?.label || producer} is not wired up yet`}
                      detail={data.note} />
        </Card>
      </div>
    )
  }

  const vectors = data.vectors || []
  const breakdowns = data.breakdowns || []
  const summary = data.summary || {}
  const outcomeLabel = (data.outcomes || []).find((o) => o.key === data.outcome)?.label || data.outcome
  const query = q.trim().toLowerCase()
  // The rail is ordered the way the cards are, not alphabetically: the vector
  // that separates the outcome most should be the first control under your
  // hand. Touched facets are pinned to the top so a slice can always be undone
  // without hunting for what set it.
  const rank = new Map((railOrder || breakdowns.map((b) => b.key)).map((key, i) => [key, i]))
  const railVectors = vectors
    .filter((v) => domains?.[v.key]
      && (!query || v.label.toLowerCase().includes(query) || v.key.includes(query)))
    .sort((a, b) => (rank.get(a.key) ?? 999) - (rank.get(b.key) ?? 999))
  // Pinning the touched ones to the top is what made the rail move. The list
  // stays put and the head says what is on instead, with a way back to each.
  const active = vectors.filter((v) => isTouched(facets[v.key], domains?.[v.key]))

  const jumpTo = (key) => {
    const node = document.getElementById(`facet-${key}`)
    if (node) node.scrollIntoView({ block: 'center', behavior: 'smooth' })
  }

  const setFacet = (key, next) => setFacets({ ...facets, [key]: next })
  const resetFacet = (key) => {
    const next = { ...facets }
    delete next[key]
    setFacets(next)
  }

  const clickCol = (key) => {
    if (sort === key) setDir(dir === 'asc' ? 'desc' : 'asc')
    else { setSort(key); setDir('desc') }
  }

  return (
    <div className="lab-page">
      {chrome}

      <div className={`lab-layout${loading ? ' is-loading' : ''}`}>
        <aside className="lab-rail" aria-label="Vector controls">
          <div className="rail-sticky">
            <div className="rail-head">
              <div>
                <b>{(data.total || 0).toLocaleString()}</b>
                <span className="muted"> of {(data.universe || 0).toLocaleString()} rows</span>
              </div>
              <button type="button" className="text-btn" disabled={!active.length}
                      onClick={() => setFacets({})}>
                reset {active.length || 'all'}
              </button>
            </div>
            <input className="rail-search" value={q} onChange={(e) => setQ(e.target.value)}
                   placeholder={`Find one of ${vectors.length} vectors…`}
                   aria-label="Find a vector" />
            {/* Always rendered, even empty. Appearing on the first drag is
                what pushed all thirty-four facets down 27px mid-drag. */}
            <div className="rail-active">
              {!active.length && <span className="rail-empty muted">no filters</span>}
              {active.map((vector) => (
                <span key={vector.key} className="chip chip-active">
                  <button type="button" className="chip-jump"
                          onClick={() => jumpTo(vector.key)}
                          title={`Scroll to ${vector.label}`}>{vector.label}</button>
                  <button type="button" className="chip-x" aria-label={`Reset ${vector.label}`}
                          onClick={() => resetFacet(vector.key)}>&times;</button>
                </span>
              ))}
            </div>
          </div>
          {!railVectors.length ? (
            <p className="muted small">No vector matches “{q}”.</p>
          ) : railVectors.map((vector) => (
            <Facet key={vector.key} vector={vector} domain={domains[vector.key]}
                   state={facets[vector.key]}
                   onChange={(next) => setFacet(vector.key, next)}
                   onReset={() => resetFacet(vector.key)} />
          ))}
        </aside>

        <div className="lab-results">
          <div className="lab-readout">
            <label>Measure
              <select value={outcome} onChange={(e) => setOutcome(e.target.value)}>
                {(data.outcomes || []).map((o) => (
                  <option key={o.key} value={o.key}>{o.label}</option>
                ))}
              </select>
            </label>
            <label>Buckets
              <input type="number" min="2" max="12" value={buckets}
                     onChange={(e) => setBuckets(Number(e.target.value) || 5)} />
            </label>
            {/* Below this a bucket is not ranked, so one lucky three-row
                bucket cannot crown a vector. */}
            <label>Min bucket
              <input type="number" min="1" max="5000" value={minBucket}
                     onChange={(e) => setMinBucket(Number(e.target.value) || 1)} />
            </label>
            <div className="readout-stats">
              {/* Rows and measured are different numbers whenever the outcome
                  is still pending for part of the slice, and every average on
                  this page belongs to the second one. */}
              <span><b>{(data.measured || 0).toLocaleString()}</b>
                <span className="muted"> measured</span></span>
              <span className={signCls(num(summary.avg_5d))}>{fmtPct(summary.avg_5d)}
                <span className="muted"> avg 5d</span></span>
              <span className={signCls(num(summary.avg_since))}>{fmtPct(summary.avg_since)}
                <span className="muted"> avg since</span></span>
              <span>{summary.wr_5d === null || summary.wr_5d === undefined
                ? '–' : fmtPct(summary.wr_5d, 0)}<span className="muted"> win 5d</span></span>
            </div>
          </div>

          <div className="lab-grid-head">
            <h2>Vectors</h2>
            <span className="muted small">
              bucketed by {outcomeLabel.toLowerCase()}, ordered by spread between
              best and worst bucket; the ones that cannot be ranked follow
            </span>
          </div>

          {!breakdowns.length ? (
            <EmptyState title="Nothing to bucket"
                        detail="The rail has narrowed the slice to nothing. Reset a control." />
          ) : (
            <div className="lab-grid">
              {breakdowns.map((entry) => (
                <VectorCard key={entry.key} entry={entry} outcome={outcomeLabel}
                            minBucket={minBucket} />
              ))}
            </div>
          )}

          <Card className="lab-rows"
                title="Rows"
                right={
                  <button type="button" className="text-btn"
                          onClick={() => setShowRows(!showRows)}>
                    {showRows ? 'hide' : `show ${(data.total || 0).toLocaleString()}`}
                  </button>
                }>
            {!showRows ? (
              <p className="muted small">
                The cards above describe the whole slice. Open this to check
                which rows produced them.
              </p>
            ) : !data.candidates?.length ? (
              <EmptyState title="No rows match" detail="Reset a control to widen the slice." />
            ) : (
              <>
                <div className="table-wrap">
                  <table className="candidate-table">
                    <caption className="sr-only">Rows in the current slice</caption>
                    <thead>
                      <tr>
                        {ROW_COLUMNS.map((c) => (
                          <th key={c.key} scope="col"
                              className={`${data.sort === c.key ? 'sorted ' : ''}col-${c.key}${c.align === 'right' ? ' right' : ''}`}
                              aria-sort={data.sort === c.key ? (data.dir === 'asc' ? 'ascending' : 'descending') : 'none'}>
                            <button type="button" className="sort-button" onClick={() => clickCol(c.key)}>
                              {c.label}
                              <span aria-hidden="true">
                                {data.sort === c.key ? (data.dir === 'asc' ? ' ▲' : ' ▼') : ''}
                              </span>
                            </button>
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {data.candidates.map((row) => (
                        <tr key={row.id} className="clickable" onClick={() => setSel(row)}>
                          {ROW_COLUMNS.map((c) => (
                            <td key={c.key} className={`col-${c.key}${c.align === 'right' ? ' right' : ''}`}>
                              {c.render ? c.render(row) : row[c.key] ?? '–'}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="table-pager">
                  <button type="button" className="btn" disabled={offset === 0}
                          onClick={() => setOffset(Math.max(0, offset - PAGE))}>&larr; Previous</button>
                  <span className="muted small">
                    {(data.total ? offset + 1 : 0).toLocaleString()}&ndash;
                    {Math.min(offset + PAGE, data.total).toLocaleString()} of {(data.total || 0).toLocaleString()}
                  </span>
                  <button type="button" className="btn"
                          disabled={offset + PAGE >= data.total}
                          onClick={() => setOffset(offset + PAGE)}>Next &rarr;</button>
                </div>
              </>
            )}
          </Card>
        </div>
      </div>

      <SignalDetail signal={sel} onClose={() => setSel(null)} />
    </div>
  )
}
