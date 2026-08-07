/**
 * Minimal, modern-aesthetic HTML for the two Phase 1 screens (PRD Section
 * 7: Login, Watchlist Management). No framework — the surface area is
 * small enough that vanilla fetch() calls against /api are simpler than
 * shipping a client bundle. Pause toggle, send-time setting, and cost
 * history are Phase 2 and intentionally not rendered here yet.
 */

const BASE_STYLES = `
  :root { color-scheme: light dark; }
  * { box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    max-width: 480px;
    margin: 4rem auto;
    padding: 0 1.5rem;
    color: light-dark(#1a1a1a, #e8e8e8);
    background: light-dark(#fafafa, #121212);
  }
  h1 { font-size: 1.25rem; font-weight: 600; margin-bottom: 1.5rem; }
  input, select, button {
    font: inherit;
    padding: 0.6rem 0.8rem;
    border-radius: 8px;
    border: 1px solid light-dark(#d0d0d0, #3a3a3a);
    background: light-dark(#fff, #1e1e1e);
    color: inherit;
  }
  button {
    background: light-dark(#1a1a1a, #e8e8e8);
    color: light-dark(#fff, #1a1a1a);
    border: none;
    cursor: pointer;
    font-weight: 500;
  }
  button:hover { opacity: 0.85; }
  form { display: flex; gap: 0.5rem; margin-bottom: 1.5rem; flex-wrap: wrap; }
  form input[type="text"] { flex: 1; min-width: 0; }
  ul { list-style: none; padding: 0; margin: 0; }
  li {
    display: flex; justify-content: space-between; align-items: center;
    padding: 0.75rem 0;
    border-bottom: 1px solid light-dark(#eaeaea, #2a2a2a);
  }
  .symbol { font-weight: 600; }
  .name { color: light-dark(#666, #999); font-size: 0.85rem; margin-left: 0.5rem; }
  .remove { background: none; color: light-dark(#b00, #f66); font-size: 0.85rem; }
  .error { color: light-dark(#b00, #f66); font-size: 0.85rem; margin-top: 0.5rem; min-height: 1.2em; }
  .empty { color: light-dark(#888, #777); font-size: 0.9rem; padding: 1rem 0; }
`;

function loginPage(): string {
  return `<!doctype html><html><head><meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Watchlist — Login</title><style>${BASE_STYLES}</style></head><body>
  <h1>Insider &amp; Market Watchlist</h1>
  <form id="login-form">
    <input type="password" id="password" placeholder="Password" required autofocus>
    <button type="submit">Log in</button>
  </form>
  <div class="error" id="error"></div>
  <script>
    document.getElementById('login-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const password = document.getElementById('password').value;
      const res = await fetch('/api/login', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password }),
      });
      if (res.ok) { window.location.href = '/'; }
      else { document.getElementById('error').textContent = 'Incorrect password.'; }
    });
  </script>
  </body></html>`;
}

function watchlistPage(): string {
  return `<!doctype html><html><head><meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Watchlist</title><style>${BASE_STYLES}</style></head><body>
  <h1>Your Watchlist</h1>
  <form id="add-form">
    <input type="text" id="symbol" placeholder="Symbol (e.g. AAPL)" required>
    <select id="type">
      <option value="stock">Stock</option>
      <option value="etf">ETF</option>
      <option value="mutual_fund">Mutual Fund</option>
    </select>
    <input type="text" id="full_name" placeholder="Full name" required>
    <button type="submit">Add</button>
  </form>
  <div class="error" id="error"></div>
  <ul id="list"></ul>
  <script>
    async function loadHoldings() {
      const res = await fetch('/api/watchlist');
      const { holdings } = await res.json();
      const list = document.getElementById('list');
      list.innerHTML = holdings.length
        ? holdings.map(h => \`
          <li>
            <span><span class="symbol">\${h[1]}</span><span class="name">\${h[3]}</span></span>
            <button class="remove" data-id="\${h[0]}">Remove</button>
          </li>\`).join('')
        : '<li class="empty">No holdings yet — add one above.</li>';

      list.querySelectorAll('.remove').forEach(btn => {
        btn.addEventListener('click', async () => {
          await fetch('/api/watchlist/' + btn.dataset.id, { method: 'DELETE' });
          loadHoldings();
        });
      });
    }

    document.getElementById('add-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const errorEl = document.getElementById('error');
      errorEl.textContent = '';
      const res = await fetch('/api/watchlist', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          symbol: document.getElementById('symbol').value,
          type: document.getElementById('type').value,
          full_name: document.getElementById('full_name').value,
        }),
      });
      if (res.ok) {
        e.target.reset();
        loadHoldings();
      } else {
        const { error } = await res.json();
        errorEl.textContent = error;
      }
    });

    loadHoldings();
  </script>
  </body></html>`;
}

export function renderPage(page: "login" | "watchlist"): string {
  return page === "login" ? loginPage() : watchlistPage();
}
