/** Service workers and static HTTP caches are browser features. The native app
 * reports the honest not-applicable state instead of inventing a cache control. */
export async function getCacheStatus() {
  return { supported: false, reason: 'web-only', cacheNames: [] };
}
