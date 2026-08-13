import React, { useEffect, useRef, useState } from 'react'
import { api } from '../api.js'

const newId = () => globalThis.crypto?.randomUUID?.() || `feedback-${Date.now()}`

export default function FeedbackWidget() {
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState(null)
  const id = useRef(newId())
  const titleRef = useRef(null)

  useEffect(() => {
    if (open) titleRef.current?.focus()
    const close = (event) => event.key === 'Escape' && setOpen(false)
    document.addEventListener('keydown', close)
    return () => document.removeEventListener('keydown', close)
  }, [open])

  async function submit(event) {
    event.preventDefault()
    setBusy(true)
    setNotice(null)
    const form = event.currentTarget
    const data = new FormData(form)
    try {
      const receipt = await api('feedback', null, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          kind: data.get('kind'),
          title: data.get('title'),
          description: data.get('description') || null,
          source: {
            external_id: id.current,
            url: location.href,
            context: { page_title: document.title },
          },
        }),
      })
      form.reset()
      id.current = newId()
      setNotice({ kind: 'ok', text: `${receipt.identifier || 'Request'} added to Backlog.` })
    } catch (error) {
      setNotice({ kind: 'error', text: error instanceof Error ? error.message : 'Submission failed.' })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="feedback-control">
      {open && (
        <section className="feedback-panel" role="dialog" aria-modal="false" aria-labelledby="feedback-heading">
          <div className="feedback-head">
            <div><span className="feedback-kicker">Signal Dashboard</span><h2 id="feedback-heading">Report an issue</h2></div>
            <button className="feedback-close" type="button" onClick={() => setOpen(false)} aria-label="Close feedback">×</button>
          </div>
          <p className="feedback-context">Bug reports and feature requests go straight to this project’s backlog.</p>
          {notice && <div className={`feedback-notice ${notice.kind}`} role="status">{notice.text}</div>}
          <form className="feedback-form" onSubmit={submit}>
            <label>Request type<select name="kind" defaultValue="bug"><option value="bug">Bug</option><option value="feature">Feature request</option></select></label>
            <label>Summary<input ref={titleRef} name="title" maxLength="200" required placeholder="What did you notice?" /></label>
            <label>Details<textarea name="description" maxLength="5000" rows="5" placeholder="Include the ticker, view, or steps if relevant." /></label>
            <span className="feedback-identity">Submitted with your signed-in account</span>
            <button className="btn primary-btn feedback-submit" type="submit" disabled={busy}>{busy ? 'Sending…' : 'Send to backlog'}</button>
          </form>
        </section>
      )}
      <button className="feedback-launcher" type="button" aria-expanded={open} onClick={() => setOpen((value) => !value)}>
        <span aria-hidden="true">◆</span> Feedback
      </button>
    </div>
  )
}
