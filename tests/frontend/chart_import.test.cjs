const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function load() {
    const calls = [];
    const apply = { hidden: true, textContent: '' };
    const preview = { innerHTML: '' };
    const context = vm.createContext({
        window: {}, document: { addEventListener() {} },
        $: selector => selector === '#chart-import-apply' ? apply : preview,
        escapeHtml: String,
        encodeURIComponent,
        FormData: class {
            append(_key, file) { this.filename = file.name; }
        },
        fetch: async (url, options) => {
            calls.push(['fetch', url, options.body.filename]);
            return {
                ok: true,
                json: async () => ({
                    rows: [], errors: [], created: 1, updated: 0, skipped: 0,
                    deactivated: 0, kept: 0, replace: false,
                    plan_hash: 'reviewed-plan-hash',
                }),
            };
        },
        toast: (...args) => calls.push(['toast', ...args]),
        closeModal: () => calls.push(['close']),
    });
    vm.runInContext(
        fs.readFileSync(path.join(__dirname, '../../app/static/js/app.js'), 'utf8'),
        context,
    );
    context.window.App.navigate = route => calls.push(['navigate', route]);
    return { app: context.window.App, calls, apply };
}

function loadWithResult(result) {
    const state = load();
    state.app._postChartImport = async () => result;
    return state;
}

function form(filename = 'reviewed.csv') {
    return {
        file: { files: [{ name: filename }] },
        replace: { checked: false },
    };
}

test('apply sends the reviewed plan hash with the same file and options', async () => {
    const { app, calls } = load();
    const f = form();
    await app.previewChartImport({ preventDefault() {}, target: f });
    await app.applyChartImport();
    assert.deepEqual(calls.filter(c => c[0] === 'fetch'), [
        ['fetch', '/api/csv/import/accounts?dry_run=1&replace=0', 'reviewed.csv'],
        ['fetch', '/api/csv/import/accounts?dry_run=0&replace=0&plan_hash=reviewed-plan-hash', 'reviewed.csv'],
    ]);
});

test('changing the file after preview blocks apply and requires another preview', async () => {
    const { app, calls, apply } = load();
    const f = form();
    await app.previewChartImport({ preventDefault() {}, target: f });
    f.file.files = [{ name: 'unreviewed.csv' }];
    f.replace.checked = true;
    await app.applyChartImport();
    assert.equal(calls.filter(c => c[0] === 'fetch').length, 1);
    assert.deepEqual(calls.at(-1), [
        'toast', 'The file or options changed — preview the import again', 'error',
    ]);
    assert.equal(apply.hidden, true);
});

test('a preview containing errors never enables apply', async () => {
    const { app, apply } = loadWithResult({
        rows: [{ action: 'deactivate', name: 'Unused', number: '7000', type: 'expense' }],
        errors: ['Row 2 has an unknown type'], row_errors: 0,
        created: 0, updated: 0, skipped: 0, deactivated: 1, kept: 0,
        plan_hash: 'invalid-plan',
    });
    await app.previewChartImport({ preventDefault() {}, target: form() });
    assert.equal(apply.hidden, true);
});
