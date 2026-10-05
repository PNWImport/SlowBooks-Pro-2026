const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function load({ failView = false } = {}) {
    const calls = [];
    const content = { innerHTML: '' };
    const page = name => ({
        render: async () => { calls.push(['render', name]); return `<main>${name}</main>`; },
        view: async id => {
            calls.push(['view', name, id]);
            if (failView) throw Error('Document not found');
        },
    });
    const context = vm.createContext({
        window: {}, document: { addEventListener() {} },
        $: () => content, $$: () => [], console: { error() {} },
        escapeHtml: String,
        InvoicesPage: page('invoices'), BillsPage: page('bills'),
        PaymentsPage: page('payments'), JournalPage: page('journal'),
        BankingPage: page('banking'),
    });
    vm.runInContext(fs.readFileSync(path.join(__dirname, '../../app/static/js/app.js'), 'utf8'), context);
    return { app: context.window.App, calls, content };
}

for (const name of ['invoices', 'bills', 'payments', 'journal']) {
    test(`${name} source link loads its page and exact document`, async () => {
        const { app, calls, content } = load();
        await app.navigate(`#/${name}/42`);
        assert.deepEqual(calls, [['render', name], ['view', name, '42']]);
        assert.equal(content.innerHTML, `<main>${name}</main>`);
    });
}

test('invalid document IDs never reach a document controller', async () => {
    const { app, calls, content } = load();
    for (const id of ['0', '-1', 'abc', '1%2F2']) {
        await app.navigate(`#/journal/${id}`);
        assert.match(content.innerHTML, /Invalid document ID/);
    }
    assert.deepEqual(calls, []);
});

test('missing source document displays the route error', async () => {
    const { app, content } = load({ failView: true });
    await app.navigate('#/journal/42');
    assert.match(content.innerHTML, /Document not found/);
    assert.doesNotMatch(content.innerHTML, /<main>/);
});

test('old check-register bookmark retains the banking page after rendering', async () => {
    const { app, content, calls } = load();
    await app.navigate('#/check-register');
    assert.equal(content.innerHTML, '<main>banking</main>');
    assert.deepEqual(calls, [['render', 'banking']]);
});
