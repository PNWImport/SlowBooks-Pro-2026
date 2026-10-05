// Controller-level clipboard checks; no native-browser acceptance claimed.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function load({ secure = true, clipboard, selectionFails = false } = {}) {
    const messages = [];
    const selected = [];
    const context = vm.createContext({
        window: { isSecureContext: secure, getSelection: () => ({
            removeAllRanges() {}, addRange() {},
        }) },
        document: { addEventListener() {}, createRange: () => ({ selectNodeContents(el) {
            if (selectionFails) throw Error('selection unavailable');
            selected.push(el);
        } }) },
        navigator: { clipboard },
    });
    vm.runInContext(fs.readFileSync(path.join(__dirname, '../../app/static/js/utils.js'), 'utf8'), context);
    context.toast = (...args) => messages.push(args);
    return { context, messages, selected };
}

test('secure clipboard receives exact text, without putting the secret in a toast', async () => {
    const writes = [];
    const { context, messages } = load({ clipboard: { writeText: async text => writes.push(text) } });
    assert.equal(await context.copyToClipboard('synthetic-secret', 'Token'), true);
    assert.deepEqual(writes, ['synthetic-secret']);
    assert.deepEqual(messages, [['Token copied to clipboard']]);
});

test('insecure network context selects visible token and never attempts clipboard write', async () => {
    let writes = 0;
    const { context, messages, selected } = load({ secure: false, clipboard: { writeText: async () => writes++ } });
    const element = {};
    assert.equal(await context.copyToClipboard('synthetic-secret', 'Token', element), false);
    assert.equal(writes, 0);
    assert.deepEqual(selected, [element]);
    assert.match(messages[0][0], /secure connection/);
    assert.match(messages[0][0], /Ctrl\+C/);
    assert.ok(!messages[0][0].includes('synthetic-secret'));
});

for (const [name, clipboard] of [
    ['missing API', undefined],
    ['permission refusal', { writeText: async () => { throw Error('private refusal detail'); } }],
]) {
    test(`${name} offers manual copying without leaking the exception`, async () => {
        const { context, messages } = load({ clipboard, selectionFails: true });
        assert.equal(await context.copyToClipboard('synthetic-secret', 'Token', {}), false);
        assert.match(messages[0][0], /manually/);
        assert.equal(messages[0][1], 'error');
        assert.ok(!messages[0][0].includes('private refusal'));
    });
}

test('empty token does not access the clipboard', async () => {
    const { context, messages } = load({ clipboard: { writeText: async () => assert.fail('must not write') } });
    assert.equal(await context.copyToClipboard('', 'Token'), false);
    assert.deepEqual(messages, [['No token to copy.', 'error']]);
});
