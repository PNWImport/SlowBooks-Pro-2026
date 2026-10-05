const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function load({ failView = false } = {}) {
    const calls = [];
    const toasts = [];
    const content = { innerHTML: '' };
    const page = name => ({
        render: async () => { calls.push(['render', name]); return `<main>${name}</main>`; },
        view: async id => {
            calls.push(['view', name, id]);
            if (failView) throw Error('Document not found');
        },
    });
    const location = { hash: '', pathname: '/', search: '' };
    const history = {
        pushed: [], replaced: [],
        pushState(_s, _t, url) { this.pushed.push(url); if (String(url).startsWith('#')) location.hash = url; },
        replaceState(_s, _t, url) { this.replaced.push(url); },
    };
    const context = vm.createContext({
        location, history, setTimeout,
        toast: (msg, kind) => toasts.push([msg, kind]),
        window: {}, document: { addEventListener() {} },
        $: () => content, $$: () => [], console: { error() {} },
        escapeHtml: String,
        InvoicesPage: page('invoices'), BillsPage: page('bills'),
        PaymentsPage: page('payments'), JournalPage: page('journal'),
        BankingPage: page('banking'),
    });
    vm.runInContext(fs.readFileSync(path.join(__dirname, '../../app/static/js/app.js'), 'utf8'), context);
    return { app: context.window.App, calls, content, history, toasts };
}

// withDocument opens the document from a setTimeout(0) after the list renders.
const settle = () => new Promise(resolve => setTimeout(resolve, 5));

for (const name of ['invoices', 'bills', 'payments', 'journal']) {
    test(`${name} source link loads its page and exact document`, async () => {
        const { app, calls, content } = load();
        await app.navigate(`#/${name}/42`);
        await settle();
        assert.deepEqual(calls, [['render', name], ['view', name, '42']]);
        assert.equal(content.innerHTML, `<main>${name}</main>`);
    });
}

test('document IDs are passed decoded to the controller, which validates them', async () => {
    const { app, calls } = load();
    for (const id of ['0', 'abc', '1%2F2']) await app.navigate(`#/journal/${id}`);
    await settle();
    assert.deepEqual(calls.filter(c => c[0] === 'view').map(c => c[2]), ['0', 'abc', '1/2']);
});

test('missing source document toasts the error over the rendered list', async () => {
    const { app, content, toasts } = load({ failView: true });
    await app.navigate('#/journal/42');
    await settle();
    assert.equal(content.innerHTML, '<main>journal</main>');
    assert.deepEqual(toasts, [['Document not found', 'error']]);
});

test('navigate pushes the hash URL when the address differs', async () => {
    const { app, history } = load();
    await app.navigate('#/journal/42');
    assert.deepEqual(history.pushed, ['#/journal/42']);
});

test('old check-register bookmark retains the banking page after rendering', async () => {
    const { app, content, calls, history } = load();
    await app.navigate('#/check-register');
    assert.equal(content.innerHTML, '<main>banking</main>');
    assert.deepEqual(calls, [['render', 'banking']]);
    assert.equal(history.replaced[0], '#/banking');
});
