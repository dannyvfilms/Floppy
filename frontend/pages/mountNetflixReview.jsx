import React from 'react';
import { mountRoot } from '../settings/root';
import { linkRequest, readThemePalette, submitNativeForm } from '../providers/transport.web';
import { NetflixReviewView } from './NetflixReviewView';

// Web transport for the Netflix review island. The server keeps the routes,
// permissions and the no-JavaScript fallback; this adapter owns the fetch for
// search results and the form POSTs for record/dismiss.

function searchUrl(baseUrl, query, mediaType) {
  const params = new URLSearchParams({ format: 'json', q: query, type: mediaType });
  return `${baseUrl}?${params.toString()}`;
}

export function mountNetflixReview(host, props) {
  const { model = {}, labels } = props || {};
  const palette = readThemePalette();
  const search = async ({ query, mediaType }) => {
    // GET: the search branch of the view is read-only and CSRF-exempt.
    const body = await linkRequest({
      url: searchUrl(model.actions?.searchUrl || '', query, mediaType),
      method: 'GET',
    });
    return body.results || [];
  };
  const resolve = ({ row, values }) => {
    submitNativeForm({ action: row.resolveUrl, csrf: props.csrf, values });
  };
  const dismiss = ({ row }) => {
    submitNativeForm({ action: row.dismissUrl, csrf: props.csrf });
  };
  return mountRoot(host, React.createElement(NetflixReviewView, {
    model,
    labels,
    palette,
    onSearch: search,
    onResolve: resolve,
    onDismiss: dismiss,
  }));
}
