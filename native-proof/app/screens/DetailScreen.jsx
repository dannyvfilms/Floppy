import React, { useEffect, useMemo, useState } from 'react';
import { Linking } from 'react-native';
import { DetailView } from '../../../frontend/pages/DetailView';
import { Screen } from '../components/Screen';
import { createDetailModelForItem, loadDetailModel } from '../surfaces/DetailSlot';
import { getActiveAuthSession } from '../data/authSession';
import { palette } from '../theme';

export default function DetailScreen({ params, onBack, navigate }) {
  const item = useMemo(
    () => params?.item || (params?.href ? { href: params.href } : null),
    [params?.item, params?.href],
  );
  const [model, setModel] = useState(() => createDetailModelForItem(item));
  const [loading, setLoading] = useState(Boolean(item));
  const [error, setError] = useState('');
  const [loadFailed, setLoadFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [actionBusy, setActionBusy] = useState(false);

  useEffect(() => {
    if (!item) {
      setLoading(false);
      setModel(createDetailModelForItem(null));
      return undefined;
    }
    let cancelled = false;
    setLoading(true);
    setLoadFailed(false);
    setError('');
    loadDetailModel(item, { publicView: params?.publicView }).then(next => {
      if (cancelled) return;
      setModel(next);
      setLoading(false);
    }).catch(cause => {
      if (cancelled) return;
      setModel(createDetailModelForItem(item));
      setError(cause?.message || 'The detail could not be loaded from the server.');
      setLoadFailed(true);
      setLoading(false);
    });
    return () => { cancelled = true; };
  }, [item, attempt, params?.publicView]);

  const wrapAction = action => ({
    ...action,
    onPress: async () => {
      if (actionBusy) return;
      setActionBusy(true);
      setError('');
      try {
        await action.onPress?.();
        const next = await loadDetailModel(item, { publicView: params?.publicView });
        setModel(next);
      } catch (cause) {
        setError(cause?.message || 'The action could not be completed.');
      } finally {
        setActionBusy(false);
      }
    },
  });
  const actionableModel = model?.actions ? {
    ...model,
    actions: {
      ...model.actions,
      primary: model.actions.primary ? wrapAction(model.actions.primary) : null,
      items: (model.actions.items || []).map(wrapAction),
    },
  } : model;

  async function loadMoreEpisodes() {
    const page = model?.children?.nextPage;
    if (!page) return;
    setActionBusy(true);
    setError('');
    try {
      const next = await loadDetailModel(item, { publicView: params?.publicView, episodePage: page });
      setModel(current => ({
        ...next,
        children: {
          ...next.children,
          episodes: [...(current?.children?.episodes || []), ...(next.children?.episodes || [])],
        },
      }));
    } catch (cause) {
      setError(cause?.message || 'The next episodes could not be loaded.');
    } finally {
      setActionBusy(false);
    }
  }

  function openDetail(identity) {
    const target = identity?.identity || identity;
    if (target?.href) navigate?.('Detail', { href: target.href });
    else if (target) navigate?.('Detail', { item: { identity: target } });
  }

  function openExternal(url) {
    if (!url) return;
    const serverUrl = getActiveAuthSession()?.serverUrl;
    const target = String(url).startsWith('/') && serverUrl
      ? new URL(url, serverUrl).toString()
      : url;
    Linking.openURL(target).catch(() => {});
  }

  function openVideo(video) {
    const key = video?.key || video?.id;
    if (key) openExternal(`https://www.youtube.com/watch?v=${encodeURIComponent(key)}`);
  }

  async function rateRelatedItem(card, score) {
    const identity = card?.identity;
    const request = getActiveAuthSession()?.request;
    if (!identity?.mediaType || !identity?.source || !identity?.mediaId || !request) return;
    await request(`/api/v1/media/${encodeURIComponent(identity.mediaType)}/${encodeURIComponent(identity.source)}/${encodeURIComponent(identity.mediaId)}/`, {
      method: 'PATCH',
      json: { score },
    });
    const next = await loadDetailModel(item, { publicView: params?.publicView });
    setModel(next);
  }

  async function runChildAction(key, child) {
    const identity = child?.identity;
    const request = getActiveAuthSession()?.request;
    if (!identity?.mediaId || !identity?.source || identity.seasonNumber == null
      || identity.episodeNumber == null || !request) return;
    const path = `/api/v1/media/tv/${encodeURIComponent(identity.source)}/${encodeURIComponent(identity.mediaId)}/${encodeURIComponent(identity.seasonNumber)}/episodes/${encodeURIComponent(identity.episodeNumber)}/watch/`;
    setActionBusy(true);
    setError('');
    try {
      await request(path, { method: key === 'unwatch' ? 'DELETE' : 'POST' });
      setModel(await loadDetailModel(item, { publicView: params?.publicView }));
    } catch (cause) {
      setError(cause?.message || 'The episode action could not be completed.');
    } finally {
      setActionBusy(false);
    }
  }

  async function rateChild(child, score) {
    const identity = child?.identity;
    const request = getActiveAuthSession()?.request;
    if (!identity?.mediaId || !identity?.source || identity.seasonNumber == null
      || identity.episodeNumber == null || !request) return;
    setActionBusy(true);
    setError('');
    try {
      await request(`/api/v1/media/tv/${encodeURIComponent(identity.source)}/${encodeURIComponent(identity.mediaId)}/${encodeURIComponent(identity.seasonNumber)}/episodes/${encodeURIComponent(identity.episodeNumber)}/score/`, {
        method: 'PATCH', json: { score },
      });
      setModel(await loadDetailModel(item, { publicView: params?.publicView }));
    } catch (cause) {
      setError(cause?.message || 'The episode rating could not be saved.');
    } finally {
      setActionBusy(false);
    }
  }

  async function rateMain(score) {
    const request = getActiveAuthSession()?.request;
    const identity = model?.identity;
    if (!identity?.media_type || !identity?.source || !identity?.media_id || !request) return;
    const parentType = identity.parent_media_type || identity.media_type;
    const base = `/api/v1/media/${encodeURIComponent(parentType)}/${encodeURIComponent(identity.source)}/${encodeURIComponent(identity.media_id)}/`;
    const path = identity.media_type === 'episode'
      ? `${base}${encodeURIComponent(identity.season_number)}/episodes/${encodeURIComponent(identity.episode_number)}/score/`
      : identity.media_type === 'season' ? `${base}${encodeURIComponent(identity.season_number)}/` : base;
    setActionBusy(true);
    setError('');
    try {
      await request(path, {
        method: 'PATCH', json: { score },
      });
      setModel(await loadDetailModel(item, { publicView: params?.publicView }));
    } catch (cause) {
      setError(cause?.message || 'The rating could not be saved.');
    } finally {
      setActionBusy(false);
    }
  }

  return <Screen onBack={onBack} chrome={false}>
    <DetailView
      model={actionableModel}
      labels={model.labels}
      palette={palette}
      loading={loading}
      error={error}
      hideContent={loadFailed}
      onRetry={item ? () => setAttempt(value => value + 1) : undefined}
      onOpenItem={openDetail}
      onOpenExternal={openExternal}
      onOpenVideo={openVideo}
      onLoadMore={loadMoreEpisodes}
      onChildAction={runChildAction}
      onRate={rateRelatedItem}
      onRateChild={rateChild}
      onRateMain={rateMain}
    />
  </Screen>;
}
