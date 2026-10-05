const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function load() {
    const calls = [];
    let finish;
    const reply = new Promise(resolve => { finish = resolve; });
    const context = vm.createContext({
        $: () => ({ files: [{ name: 'bank.csv', type: 'text/csv' }] }),
        FormData: class { append() {} },
        fetch: async url => { calls.push(['fetch', url]); return reply; },
        toast: (...args) => calls.push(['toast', ...args]),
        closeModal: () => calls.push(['close']),
        App: { navigate: route => calls.push(['navigate', route]) },
    });
    const page = vm.runInContext(fs.readFileSync(path.join(__dirname, '../../app/static/js/banking.js'), 'utf8') + '\nBankingPage;', context);
    return { page, calls, finish };
}

for (const success of [true, false]) {
    test(`explicit import button is restored after ${success ? 'success' : 'failure'}`, async () => {
        const { page, calls, finish } = load();
        const button = { disabled: false, textContent: 'Import 2 Transactions' };
        const pending = page.confirmOFXImport(7, 12, button);
        assert.equal(button.disabled, true);
        assert.equal(button.textContent, 'Importing…');
        await page.confirmOFXImport(7, 12, button);
        assert.deepEqual(calls, [['fetch', '/api/bank-import/import-csv/7']]);
        finish({ ok: success, json: async () => success
            ? { imported: 2, skipped: 0, matched: 0 } : { detail: 'Import refused' } });
        await pending;
        assert.equal(button.disabled, false);
        assert.equal(button.textContent, 'Import 2 Transactions');
        assert.equal(calls.some(c => c[0] === 'close'), success);
        assert.equal(calls.some(c => c[0] === 'navigate'), success);
        if (success) assert.deepEqual(calls.at(-1), ['navigate', '#/banking/12']);
        else assert.deepEqual(calls.at(-1), ['toast', 'Import refused', 'error']);
    });
}
