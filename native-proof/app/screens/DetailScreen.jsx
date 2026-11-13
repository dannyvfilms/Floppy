import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Linking } from 'react-native';
import { DetailView } from '../../../frontend/pages/DetailView';
import { Screen } from '../components/Screen';
import { createDetailModelForItem, loadDetailModel } from '../surfaces/DetailSlot';
import { useDetailFeatures } from '../surfaces/DetailFeatures';
import { setShellPageType } from '../surfaces/shellContext';
import { getActiveAuthSession } from '../data/authSession';
import { formatUserDate } from '../data/userDate';
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
  const [version, setVersion] = useState(0);

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

  // A write from one of the page's own controls reloads the page payload in place.
  const refresh = useCallback(() => {
    if (!item) return;
    loadDetailModel(item, { publicView: params?.publicView })
      .then(next => { setModel(next); setVersion(value => value + 1); })
      .catch(cause => setError(cause?.message || 'The detail could not be loaded from the server.'));
  }, [item, params?.publicView]);

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

  // A season page's title is the show's name and opens the show, like the web title link.
  const seasonIdentity = model?.identity?.media_type === 'season' ? model.identity : null;
  const showIdentity = seasonIdentity?.source && seasonIdentity?.media_id ? {
    mediaType: seasonIdentity.parent_media_type || 'tv',
    source: seasonIdentity.source,
    mediaId: seasonIdentity.media_id,
  } : null;

  const features = useDetailFeatures({
    model,
    ready: !loading && !loadFailed,
    version,
    refresh,
    navigate,
    onOpenItem: openDetail,
    onOpenExternal: openExternal,
  });

  // The header search follows the page like the web header: a film page searches Movies.
  const pageType = features.enabled ? features.pageType : null;
  useEffect(() => {
    setShellPageType(pageType);
    return () => setShellPageType(null);
  }, [pageType]);

  const children = actionableModel?.children;
  const hasChildren = Boolean(children?.seasons?.length || children?.episodes?.length || children?.issues?.length);
  const viewModel = {
    ...actionableModel,
    // A film has no seasons, episodes or issues: the web page shows no such section.
    children: hasChildren && !features.replacesChildren ? {
      ...children,
      // A season page switches season from its title, like the web; it does not list them again.
      seasons: model?.identity?.media_type === 'season' ? [] : children.seasons,
      episodes: (children.episodes || []).map(episode => ({
        ...episode, dateLabel: formatUserDate(episode.dateLabel) || episode.dateLabel,
      })),
    } : null,
    // The score row already shows each stored source: keep the viewer's score and the tag chips.
    scoreChips: features.scoreSlot
      ? (actionableModel.scoreChips || []).filter(chip => chip.kind === 'viewer' || chip.text)
      : actionableModel.scoreChips,
    sections: features.enabled
      ? (actionableModel.sections || []).filter(section => !features.replacedSections.includes(section.id))
      : actionableModel.sections,
  };

  function openPerson(person) {
    navigate?.('People', {
      identity: { kind: 'person', source: model?.identity?.source, personId: person.person_id },
    });
  }

  return <Screen onBack={onBack} chrome={false}>
    <DetailView
      model={viewModel}
      labels={model.labels}
      palette={palette}
      loading={loading}
      error={error}
      hideContent={loadFailed}
      onRetry={item ? () => setAttempt(value => value + 1) : undefined}
      onOpenItem={openDetail}
      onOpenTitle={showIdentity ? () => openDetail(showIdentity) : undefined}
      onOpenExternal={openExternal}
      onOpenVideo={openVideo}
      onLoadMore={loadMoreEpisodes}
      onChildAction={runChildAction}
      onRate={rateRelatedItem}
      onRateChild={rateChild}
      onRateMain={rateMain}
      onOpenPerson={model?.identity?.source ? openPerson : undefined}
      actionsSlot={features.actionsSlot}
      scoreSlot={features.headerSlot || features.scoreSlot
        ? <>{features.headerSlot}{features.scoreSlot}</> : null}
      sectionsSlot={features.sectionsSlot}
      childrenSlot={features.childrenSlot}
    >{features.overlays}</DetailView>
  </Screen>;
}
