import React, { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { mountRoot } from '../settings/root';
import { Button, Dialog, Field, SelectField } from './controls';

// Mounted once in the base layout. The toolbar (mountBulkToolbar.jsx) opens a
// short dialog with `bulk-actions-open`. Anything slow then runs as a "job" in a
// docked card, so the page stays usable. Add Plays jobs are remembered in
// localStorage and pick up again after a reload or a visit to another page.
const SCOPES = [
  { value: 'aired', label: 'All aired episodes' },
  { value: 'watched', label: 'Episodes my status says I watched' },
  { value: 'seasons', label: 'A range of seasons' },
];
const EXISTING = [
  { value: 'skip', label: 'Skip episodes that already have a play' },
  { value: 'add', label: 'Add another play anyway' },
];
const DATES = [
  { value: 'air_date', label: 'Episode air dates (estimate)' },
  { value: 'one_date', label: 'One date for every play' },
  { value: 'range', label: 'Spread across a date range' },
];
const SCOPE_HELP = {
  aired: 'Every episode that has aired. Specials are left out.',
  watched: 'Completed shows get every aired episode. Other shows get only their completed seasons.',
  seasons: 'Aired episodes in these seasons. Season 0 is specials.',
};
const DATE_HELP = {
  air_date: 'Each play is dated when the episode first aired. This is an estimate of when you watched, not a real watch time.',
  one_date: 'Every play lands on one day. Many plays on one day can distort activity, streaks and Statistics.',
  range: 'Plays are spread evenly in order across the dates. Still an estimate.',
};
const STORE = 'floppy-bulk-jobs';

const plural = (n, word) => `${n.toLocaleString()} ${word}${n === 1 ? '' : 's'}`;
const notify = (message, type = 'success') => {
  if (message && typeof window.showTrackToast === 'function') window.showTrackToast({ message, type });
};
const finished = () => window.dispatchEvent(new CustomEvent('bulk-job-finished'));

// ---- job store -------------------------------------------------------------
let jobs = [];
const listeners = new Set();
const remembered = job => job.kind === 'plays' && ['previewing', 'review', 'running'].includes(job.phase);
function setJobs(next) {
  jobs = next;
  try { localStorage.setItem(STORE, JSON.stringify(jobs.filter(remembered))); } catch { /* storage is optional */ }
  listeners.forEach(listener => listener());
}
const patchJob = (id, patch) => setJobs(jobs.map(job => job.id === id ? { ...job, ...patch } : job));
const dropJob = id => setJobs(jobs.filter(job => job.id !== id));
const useJobs = () => useSyncExternalStore(
  listener => { listeners.add(listener); return () => listeners.delete(listener); }, () => jobs);

async function post(url, csrf, body) {
  const response = await fetch(url, { method: 'POST', headers: { 'X-CSRFToken': csrf }, body });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data.success === false) throw new Error(data.error || 'Something went wrong.');
  return data;
}

function playsBody(job, dryRun) {
  const data = new URLSearchParams({ ...job.form, dry_run: dryRun ? '1' : '0' });
  job.itemIds.forEach(id => data.append('item_ids', id));
  return data;
}

async function startPlays(config, job, dryRun) {
  try {
    const data = await post(config.playsUrl, config.csrfToken, playsBody(job, dryRun));
    patchJob(job.id, { operation: data.operation_id, phase: dryRun ? 'previewing' : 'running', error: '', progress: null });
  } catch (error) {
    patchJob(job.id, { phase: 'error', error: error.message });
  }
}

async function runStatus(config, job) {
  try {
    const body = new URLSearchParams({ status: job.status });
    job.itemIds.forEach(id => body.append('item_ids', id));
    const data = await post(config.statusUrl, config.csrfToken, body);
    patchJob(job.id, { phase: 'done', message: data.message || 'Status updated.' });
    notify(data.message || 'Status updated.');
    finished();
  } catch (error) {
    patchJob(job.id, { phase: 'error', error: error.message });
  }
}

// ---- docked job card -------------------------------------------------------
function Progress({ done, total, label }) {
  const known = total > 0 && done !== undefined;
  return <div role="status">
    <p>{label}{known ? ` ${done.toLocaleString()} of ${plural(total, 'show')}` : ''}</p>
    <div className={`ui-progress${known ? '' : ' ui-progress-indeterminate'}`}>
      <div style={known ? { width: `${Math.round((done / total) * 100)}%` } : undefined} /></div>
  </div>;
}

function Summary({ totals, samples }) {
  const notes = [
    totals.existing && `${plural(totals.existing, 'episode')} skipped (already have a play)`,
    totals.unaired && `${plural(totals.unaired, 'episode')} skipped (not aired yet)`,
    totals.no_date && `${plural(totals.no_date, 'episode')} skipped (no air date)`,
  ].filter(Boolean);
  return <>
    <p><strong>{plural(totals.plays, 'play')}</strong> across {plural(totals.shows, 'show')}.</p>
    {samples.length > 0 && <ul className="ui-bulk-list">{samples.map(s => <li key={s.title}>{s.title}: {plural(s.add, 'play')}</li>)}</ul>}
    {notes.length > 0 && <ul className="ui-bulk-list">{notes.map(note => <li key={note}>{note}</li>)}</ul>}
  </>;
}

function Problems({ state }) {
  if (!state?.problem_count) return null;
  return <details className="ui-bulk-problems" open>
    <summary>{plural(state.problem_count, 'show')} could not be used</summary>
    <ul className="ui-bulk-list">{state.problems.map((p, i) => <li key={i}>{p.title}: {p.reason}</li>)}</ul>
    {state.problem_count > state.problems.length && <p>And {(state.problem_count - state.problems.length).toLocaleString()} more.</p>}
  </details>;
}

function JobCard({ config, job }) {
  const polling = job.kind === 'plays' && ['previewing', 'running'].includes(job.phase) && job.operation;
  useEffect(() => {
    if (!polling) return undefined;
    let stopped = false;
    let timer;
    const url = config.playsStatusUrl.replace('OPERATION', job.operation);
    const tick = async () => {
      try {
        const response = await fetch(url);
        const data = await response.json();
        if (stopped) return;
        if (!response.ok) throw new Error(data.error || 'Progress is unavailable.');
        if (data.state === 'running') { patchJob(job.id, { progress: data }); timer = setTimeout(tick, 1500); return; }
        if (data.state === 'error') { patchJob(job.id, { phase: 'error', error: 'The job stopped unexpectedly.' }); return; }
        if (job.phase === 'previewing') { patchJob(job.id, { phase: 'review', result: data, progress: null }); return; }
        patchJob(job.id, { phase: 'done', result: data, progress: null });
        notify(`${plural(data.totals.plays, 'play')} added.`);
        finished();
      } catch (error) {
        if (!stopped) patchJob(job.id, { phase: 'error', error: error.message });
      }
    };
    timer = setTimeout(tick, 400);
    return () => { stopped = true; clearTimeout(timer); };
  }, [polling, job.operation, job.phase]);

  const title = job.kind === 'status' ? 'Update Status' : 'Add Plays to History';
  const result = job.result;
  const progress = job.progress || { done: 0, total: job.itemIds.length };
  return <div className="ui-dock-card" role="group" aria-label={title}>
    <div className="ui-dock-head"><h4>{title}</h4>
      <Button type="button" secondary aria-label="Hide" title="Hide. A running job keeps going." onClick={() => dropJob(job.id)}>×</Button></div>
    {job.phase === 'working' && <Progress label={`Setting ${plural(job.itemIds.length, 'item')} to ${job.statusLabel}`} />}
    {job.phase === 'starting' && <Progress label="Starting" />}
    {job.phase === 'previewing' && <Progress done={progress.done} total={progress.total} label="Checking" />}
    {job.phase === 'running' && <Progress done={progress.done} total={progress.total} label="Adding plays" />}
    {job.phase === 'review' && result && <>
      <Summary totals={result.totals} samples={result.samples} />
      <Problems state={result} />
      {result.totals.plays === 0 && <p>Nothing to add with these choices.</p>}
      <div className="ui-bulk-actions">
        {result.totals.plays > 0 && <Button type="button" onClick={() => { patchJob(job.id, { phase: 'starting' }); startPlays(config, job, false); }}>Add {plural(result.totals.plays, 'play')}</Button>}
        <Button type="button" secondary onClick={() => dropJob(job.id)}>Discard</Button></div></>}
    {job.phase === 'done' && job.kind === 'status' && <p>{job.message}</p>}
    {job.phase === 'done' && job.kind === 'plays' && result && <>
      <p><strong>{plural(result.totals.plays, 'play')}</strong> added across {plural(result.totals.shows, 'show')}.</p>
      <Problems state={result} /></>}
    {job.phase === 'error' && <p role="alert" className="ui-bulk-error">{job.error}</p>}
  </div>;
}

// ---- dialogs that start a job ---------------------------------------------
function StatusDialog({ request, close, start }) {
  const count = request.itemIds.length;
  return <Dialog open title="Update Status" closeLabel="Close" onClose={close}>
    <p>Set {plural(count, 'item')} to <strong>{request.statusLabel}</strong>?</p>
    <p className="ui-bulk-note">{request.status === 'Completed'
      ? 'Completed also adds a play for every episode not yet played, dated today. To choose the dates, use Add Plays to History first.'
      : 'This changes status only. Nothing is added to History, Statistics or streaks. To record viewing activity, use Add Plays to History.'}</p>
    <div className="ui-bulk-actions"><Button type="button" onClick={start}>Update status</Button>
      <Button type="button" secondary onClick={close}>Cancel</Button></div>
  </Dialog>;
}

function PlaysDialog({ request, close, start }) {
  const [form, setForm] = useState({ scope: 'aired', season_from: '1', season_to: '1', existing: 'skip',
    date_mode: 'air_date', date: '', start_date: '', end_date: '' });
  const today = new Date().toISOString().slice(0, 10);
  const set = event => setForm(prev => ({ ...prev, [event.target.name]: event.target.value }));
  return <Dialog open title="Add Plays to History" closeLabel="Close" onClose={close}>
    <p className="ui-bulk-note">Adds viewing records for {plural(request.itemIds.length, 'selected item')}. They show in History and count in activity, Statistics and streaks.</p>
    <SelectField id="bulk-plays-scope" name="scope" label="Which episodes" value={form.scope} options={SCOPES} onChange={set} />
    <p className="ui-bulk-note">{SCOPE_HELP[form.scope]}</p>
    {form.scope === 'seasons' && <div className="ui-bulk-row">
      <Field id="bulk-plays-from" name="season_from" type="number" min="0" label="First season" value={form.season_from} onChange={set} />
      <Field id="bulk-plays-to" name="season_to" type="number" min="0" label="Last season" value={form.season_to} onChange={set} /></div>}
    <SelectField id="bulk-plays-existing" name="existing" label="Episodes already played" value={form.existing} options={EXISTING} onChange={set} />
    <SelectField id="bulk-plays-dates" name="date_mode" label="Play dates" value={form.date_mode} options={DATES} onChange={set} />
    <p className="ui-bulk-note">{DATE_HELP[form.date_mode]}</p>
    {form.date_mode === 'one_date' && <Field id="bulk-plays-date" name="date" type="date" max={today} label="Date" value={form.date} onChange={set} />}
    {form.date_mode === 'range' && <div className="ui-bulk-row">
      <Field id="bulk-plays-start" name="start_date" type="date" max={today} label="From" value={form.start_date} onChange={set} />
      <Field id="bulk-plays-end" name="end_date" type="date" max={today} label="To" value={form.end_date} onChange={set} /></div>}
    <p className="ui-bulk-note">Review checks every show in the background and shows the counts. Nothing is added until you confirm, and you can keep browsing meanwhile.</p>
    <div className="ui-bulk-actions"><Button type="button" onClick={() => start(form)}>Review</Button>
      <Button type="button" secondary onClick={close}>Cancel</Button></div>
  </Dialog>;
}

function Adapter({ config }) {
  const [request, setRequest] = useState(null);
  const all = useJobs();
  const seq = useRef(0);
  useEffect(() => {
    const open = event => setRequest(event.detail);
    window.addEventListener('bulk-actions-open', open);
    return () => window.removeEventListener('bulk-actions-open', open);
  }, []);
  useEffect(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(STORE) || '[]');
      if (Array.isArray(saved) && saved.length && !jobs.length) setJobs(saved);
    } catch { /* ignore unreadable storage */ }
  }, []);

  const newJob = fields => {
    seq.current += 1;
    const job = { id: `${Date.now()}-${seq.current}`, itemIds: request.itemIds, ...fields };
    setJobs([...jobs, job]);
    setRequest(null);
    window.dispatchEvent(new CustomEvent('bulk-actions-done'));
    return job;
  };
  return <>
    {request?.kind === 'status' && <StatusDialog request={request} close={() => setRequest(null)}
      start={() => runStatus(config, newJob({ kind: 'status', phase: 'working', status: request.status, statusLabel: request.statusLabel }))} />}
    {request?.kind === 'plays' && <PlaysDialog request={request} close={() => setRequest(null)}
      start={form => startPlays(config, newJob({ kind: 'plays', phase: 'starting', form }), true)} />}
    {all.length > 0 && <div className="ui-dock" aria-live="polite">{all.map(job => <JobCard key={job.id} config={config} job={job} />)}</div>}
  </>;
}

export function mountBulkActions(host, props) {
  return mountRoot(host, <Adapter config={props} />);
}
