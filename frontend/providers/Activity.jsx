import React, { useEffect, useRef, useState } from 'react';
import { ActivityList, Button, Card } from '../ui/controls';
import { Form, usePage } from './web';

export function Activity() {
  const { model, t } = usePage();
  const [data, setData] = useState(null);
  const [page, setPage] = useState(1);
  const [error, setError] = useState(false);
  const [retry, setRetry] = useState(0);
  const [openDetails, setOpenDetails] = useState(new Set());
  const [copied, setCopied] = useState('');
  const copyTimer = useRef(null);
  useEffect(() => () => clearTimeout(copyTimer.current), []);
  useEffect(() => {
    if (openDetails.size) return;
    const controller = new AbortController();
    let timer;
    async function load() {
      try {
        const response = await fetch(`${model.activityUrl}&page=${page}`, {
          signal: controller.signal, credentials: 'same-origin', headers: { Accept: 'application/json' },
        });
        if (!response.ok || !response.headers.get('content-type')?.includes('application/json')) throw new Error('Activity unavailable');
        const next = await response.json();
        if (controller.signal.aborted) return;
        setData(next); setError(false);
        if (next.active) timer = setTimeout(load, 5000);
      } catch {
        if (!controller.signal.aborted) setError(true);
      }
    }
    load();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [model.activityUrl, page, retry, openDetails.size]);

  function detailsChanged(id, open) {
    setOpenDetails(previous => {
      const next = new Set(previous);
      if (open) next.add(id); else next.delete(id);
      return next;
    });
  }
  function changePage(next) {
    setData(null); setError(false); setPage(next);
  }
  async function copy(id, text) {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(id); clearTimeout(copyTimer.current);
      copyTimer.current = setTimeout(() => setCopied(''), 2000);
    } catch { setCopied('error'); }
  }
  return <div className="provider-activity">
    {error && <div role="alert"><p>{t('Could not load import activity.')}</p>
      <Button type="button" secondary onClick={() => setRetry(value => value + 1)}>{t('Retry')}</Button></div>}
    {!data && !error && <p role="status">{t('Loading import activity…')}</p>}
    {data && <>
      <Card title={t('Active Periodic Imports')}>
        {data.schedules.length ? <ActivityList>{data.schedules.map(schedule => <div className="provider-activity-row" key={schedule.id}>
          <div className="ui-heading"><strong>{schedule.schedule}</strong>
            <Form action={schedule.action}><input type="hidden" name="task_name" value={schedule.name} />
              <Button type="submit" danger>{t('Remove schedule')}</Button></Form></div>
          {schedule.username && <p>{t('Username')}: {schedule.username}</p>}
          <p>{t('Mode')}: {schedule.mode}</p>
          <p>{t('Last Import')}: {schedule.lastRun || '—'}</p><p>{t('Next Import')}: {schedule.nextRun || '—'}</p>
        </div>)}</ActivityList> : <p>{t('No periodic imports configured')}</p>}
      </Card>
      <Card title={t('Import History')}>
        <p>{t('Showing import activity from the last 7 days.')}</p>
        {data.results.length ? <ActivityList>{data.results.map(result => <div className="provider-activity-row" key={result.id}>
          <div className="ui-heading"><strong>{result.statusLabel}</strong><span>{result.date}</span></div>
          {result.summary && <p>{result.summary}</p>}
          {result.status === 'STARTED' && result.current !== null && <div>
            <p>{result.progressLabel || t('Import')}: {result.current}{result.total ? ` / ${result.total}` : ''}</p>
            {!!result.total && <progress value={result.current} max={result.total} aria-label={result.progressLabel || t('Import')} />}
          </div>}
          {result.cancelAction && <Form action={result.cancelAction} confirm={t('Cancel this import?')}>
            <Button type="submit" danger>{t('Cancel import')}</Button></Form>}
          {result.errors && <details onToggle={event => detailsChanged(result.id, event.currentTarget.open)}>
            <summary>{t(result.status === 'FAILURE' ? 'Show traceback' : 'Show details')}</summary>
            <div className="provider-error-details" data-keep-open={openDetails.has(result.id) ? 'true' : 'false'}>
              <Button type="button" secondary onClick={() => copy(result.id, result.errors)}>{t(copied === result.id ? 'Copied!' : 'Copy')}</Button>
              <pre>{result.errors}</pre>
            </div>
          </details>}
        </div>)}</ActivityList> : <p>{t('No imports in the last 7 days')}</p>}
        {copied === 'error' && <p role="status">{t('Could not copy details.')}</p>}
        {(page > 1 || data.hasMore) && <nav className="ui-heading" aria-label={t('Import History')}>
          <Button type="button" secondary disabled={page === 1 || openDetails.size > 0} onClick={() => changePage(page - 1)}>{t('Previous')}</Button>
          <span>{page}</span>
          <Button type="button" secondary disabled={!data.hasMore || openDetails.size > 0} onClick={() => changePage(page + 1)}>{t('Next')}</Button>
        </nav>}
      </Card>
      {!!data.runs.length && <Card title={t('Recent Import Runs')}><p>{t('Counts and undo options for supported imports.')}</p><ActivityList>{data.runs.map(run => <div className="provider-activity-row" key={run.id}>
        <div className="ui-heading"><strong>{run.statusLabel}</strong><span>{run.date}</span></div>
        <p>{t('Created')}: {run.created} · {t('Updated')}: {run.updated} · {t('Skipped')}: {run.skipped} · {t('Failed')}: {run.failed}
          {run.remaining !== null && <> · {t('Remaining')}: {run.remaining}</>}</p>
        <Form action={run.action} confirm={t(run.status === 'running' ? 'Cancel this import?' : 'Remove the items this import created? This cannot be undone.')}>
          <Button type="submit" danger>{t(run.status === 'running' ? 'Cancel import' : 'Undo this import')}</Button>
        </Form>
      </div>)}</ActivityList></Card>}
      {!!data.cleanup.length && <Card title={t('Imported Media by Source')}>
        <p>{t('Permanently delete everything of a media type imported from this source.')}</p>
        {data.cleanup.map(row => <div className="ui-heading provider-activity-row" key={row.mediaType}>
          <span>{row.mediaLabel} · {row.count}</span>
          <Form action={row.action} confirm={t('Permanently delete all items of this media type imported from AniList? This cannot be undone.')}>
            <Button type="submit" danger>{t('Delete all')}</Button></Form>
        </div>)}
      </Card>}
    </>}
  </div>;
}
