/* All staff forms and navigation also work without JavaScript. */
(() => {
  document.querySelector('[data-form-errors]')?.focus();
  const login = document.querySelector('[data-staff-login]');
  login?.addEventListener('submit', () => {
    const button = login.querySelector('button[type="submit"]');
    button.disabled = true;
    button.textContent = 'Signing in…';
  });
  window.addEventListener('pageshow', (event) => { if (event.persisted) location.reload(); });

  const queue = document.querySelector('[data-order-queue]');
  if (!queue) return;
  const status = document.querySelector('[data-poll-status]');
  const loginLink = document.querySelector('[data-session-login]');
  const orderIds = () => new Set([...queue.querySelectorAll('[data-queue-id]')].map((el) => el.dataset.queueId));
  let knownIds = orderIds();
  let submitting = false;
  let refreshing = false;
  let sessionExpired = false;
  document.addEventListener('submit', (event) => {
    if (event.target.matches('[data-status-form]')) submitting = true;
  });
  async function refresh() {
    if (document.hidden || submitting || refreshing || sessionExpired || queue.contains(document.activeElement)) return;
    refreshing = true;
    try {
      const response = await fetch(queue.dataset.pollUrl, {
        credentials: 'same-origin', cache: 'no-store', signal: AbortSignal.timeout(8000),
      });
      if (response.redirected || response.status === 401 || response.status === 403) {
        sessionExpired = true;
        status.textContent = 'Staff session ended or access changed. Sign in again to continue.';
        loginLink.hidden = false;
        queue.replaceChildren();
        return;
      }
      if (!response.ok) throw new Error('Refresh failed');
      const html = await response.text();
      // Do not replace a control that received focus while the request was in flight.
      if (submitting || queue.contains(document.activeElement)) return;
      queue.innerHTML = html;
      const nextIds = orderIds();
      const added = [...nextIds].filter((id) => !knownIds.has(id)).length;
      if (added) document.querySelector('[data-queue-announcement]').textContent = `${added} new order${added === 1 ? '' : 's'} in this view.`;
      knownIds = nextIds;
      status.textContent = 'Live · checking every 10 seconds';
    } catch (_) {
      status.textContent = 'Updates paused. Check your connection or refresh to try again.';
    } finally {
      refreshing = false;
    }
  }
  status.textContent = 'Live · checking every 10 seconds';
  document.querySelector('[data-refresh-orders]').addEventListener('click', (event) => {
    if (sessionExpired) return;
    event.preventDefault();
    refresh();
  });
  setInterval(refresh, 10000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
})();
