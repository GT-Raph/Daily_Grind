/* Server forms remain fully usable without JavaScript. */
(() => {
  const feedback = document.querySelector('[data-order-feedback]');
  let clearFeedback;
  // Serialize basket mutations so rapid taps cannot overwrite a session update.
  let basketRequest = Promise.resolve();
  document.querySelectorAll('[data-add-to-order]').forEach((form) => {
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      const button = form.querySelector('button');
      if (button.disabled) return;
      const original = button.innerHTML;
      button.disabled = true;
      button.textContent = 'Adding…';
      basketRequest = basketRequest.then(async () => {
        try {
          const response = await fetch(form.action, { method: 'POST', body: new FormData(form),
            headers: { Accept: 'application/json' }, credentials: 'same-origin', signal: AbortSignal.timeout(12000) });
          if (!response.headers.get('content-type')?.includes('application/json')) {
            throw new Error('Your session may have expired. Refresh the page and try again.');
          }
          const data = await response.json();
          if (!response.ok || data.error) throw new Error(data.error || 'Could not update your order. Please try again.');
          document.querySelectorAll('[data-basket-count]').forEach((el) => { el.textContent = data.count; });
          document.querySelectorAll('[data-basket-total]').forEach((el) => { el.textContent = Number(data.total).toFixed(2); });
          const dock = document.querySelector('[data-basket-dock]');
          if (dock) dock.hidden = data.count === 0;
          feedback.textContent = `${form.closest('.card').querySelector('h3').textContent} added to your order.`;
        } catch (error) {
          feedback.textContent = error instanceof TypeError || error.name === 'TimeoutError'
            ? 'Connection interrupted. Check your basket before trying again.' : error.message;
        } finally {
          button.disabled = false;
          button.innerHTML = original;
          clearTimeout(clearFeedback);
          clearFeedback = setTimeout(() => { feedback.textContent = ''; }, 7000);
        }
      });
    });
  });

  const checkout = document.querySelector('[data-checkout-form]');
  checkout?.addEventListener('submit', () => {
    const button = checkout.querySelector('button[type="submit"]');
    button.disabled = true;
    button.textContent = 'Placing your order…';
  });
  // A restored page must remain usable after navigating back from the receipt.
  window.addEventListener('pageshow', (event) => { if (event.persisted && checkout) location.reload(); });
  document.querySelector('[data-form-errors]')?.focus();

  const receipt = document.querySelector('[data-receipt-status]');
  const target = receipt;
  if (!target) return;
  const pollStatus = document.querySelector('[data-poll-status]');
  const receiptClosed = () => receipt && ['completed', 'cancelled'].includes(receipt.querySelector('[data-receipt-state]')?.dataset.receiptState);
  async function refresh() {
    if (document.hidden) return;
    if (receiptClosed()) {
      pollStatus.textContent = 'This order is closed.';
      return;
    }
    try {
      const response = await fetch(target.dataset.pollUrl, { credentials: 'same-origin', cache: 'no-store', signal: AbortSignal.timeout(8000) });
      if (!response.ok || response.redirected) throw new Error('Refresh the page to reconnect or sign in.');
      const html = await response.text();
      if (target.innerHTML.trim() !== html.trim()) {
        target.innerHTML = html;
      }
      pollStatus.textContent = receiptClosed() ? 'This order is closed.' : 'Live · checking for an update every 10 seconds';
    } catch (_) {
      pollStatus.textContent = 'Updates paused. Check your connection and refresh this page. Your saved order is safe.';
    }
  }
  pollStatus.textContent = receiptClosed() ? 'This order is closed.' : 'Live · checking every 10 seconds';
  setInterval(refresh, 10000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
})();
