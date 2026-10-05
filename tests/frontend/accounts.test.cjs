// Run the actual controller methods with mocked transport and browser prompts.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function load(accounts, { accept = true, failDelete = false } = {}) {
    const calls = [];
    const context = vm.createContext({
        window: {}, document: { addEventListener() {} }, T: String,
        escapeHtml: text => String(text).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('"', '&quot;'),
        formatCurrency: String,
        toast: (...args) => calls.push(['toast', ...args]),
        confirm: text => { calls.push(['confirm', text]); return accept; },
        API: {
            get: async url => url === '/accounts' ? accounts : accounts.find(a => url === `/accounts/${a.id}`),
            put: async (url, data) => calls.push(['put', url, data.is_active]),
            del: async url => {
                calls.push(['delete', url]);
                if (failDelete) throw Error('Account is still in use');
            },
        },
    });
    vm.runInContext(fs.readFileSync(path.join(__dirname, '../../app/static/js/app.js'), 'utf8'), context);
    const app = context.window.App;
    app.navigate = async route => calls.push(['navigate', route]);
    return { app, calls };
}

const accounts = [
    { id: 1, name: 'Control', account_number: '1100', account_type: 'asset', is_control: true, is_active: true },
    { id: 2, name: 'Savings "A" <demo>', account_number: '1010', account_type: 'asset', is_control: false, is_active: true },
    { id: 3, name: 'Hidden', account_number: '9990', account_type: 'expense', is_control: false, is_active: false },
];

test('rendered delete handlers carry only IDs; controls have Edit but no Delete', async () => {
    const { app } = load(accounts);
    const html = await app.renderAccounts();
    const handlers = [...html.matchAll(/onclick="([^"]*)"/g)].map(m => m[1]);
    assert.ok(handlers.includes('App.showAccountForm(1)'));
    assert.ok(!handlers.includes('App.deleteAccount(1)'));
    assert.ok(handlers.includes('App.deleteAccount(2)'));
    assert.ok(html.includes('Savings &quot;A&quot; &lt;demo>'));
    assert.ok(!html.includes('<strong>Hidden</strong>'));
    app._showInactiveAccounts = true;
    const shown = await app.renderAccounts();
    assert.ok(shown.includes('App.setAccountActive(3, true)'));
    assert.ok(shown.includes('<strong>Hidden</strong>'));
});

test('confirmed deletion fetches the name, deletes the exact ID, then refreshes', async () => {
    const { app, calls } = load(accounts);
    await app.deleteAccount(2);
    assert.ok(calls[0][1].includes(accounts[1].name));
    assert.deepEqual(calls.slice(1), [
        ['delete', '/accounts/2'], ['toast', 'Account deleted'], ['navigate', '#/accounts'],
    ]);
});

test('cancelled deletion does not send a delete request', async () => {
    const { app, calls } = load(accounts, { accept: false });
    await app.deleteAccount(2);
    assert.equal(calls.length, 1);
    assert.equal(calls[0][0], 'confirm');
});

test('refused deletion shows its reason without a false success or refresh', async () => {
    const { app, calls } = load(accounts, { failDelete: true });
    await app.deleteAccount(2);
    assert.deepEqual(calls.slice(1), [
        ['delete', '/accounts/2'], ['toast', 'Account is still in use', 'error'],
    ]);
});

test('reactivation updates only the selected account then refreshes', async () => {
    const { app, calls } = load(accounts);
    await app.setAccountActive(3, true);
    assert.deepEqual(calls, [
        ['put', '/accounts/3', true], ['toast', 'Account reactivated'], ['navigate', '#/accounts'],
    ]);
});
