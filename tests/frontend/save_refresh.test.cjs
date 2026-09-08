// Focused UI-controller tests with mocked API/DOM, not browser acceptance.
// Run: node --test tests/frontend/save_refresh.test.cjs
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function load(file, name, overrides = {}) {
    const events = [];
    const context = vm.createContext({
        API: { post: async () => ({}), put: async () => ({}) },
        App: { navigate: async route => events.push(route) },
        $: () => ({ value: 'demo', checked: false, innerHTML: '' }),
        toast: (...args) => events.push(args),
        closeModal: () => events.push('close'),
        openModal: () => events.push('open'),
        escapeHtml: String, statusBadge: String,
        formatDate: String, formatCurrency: String,
        ...overrides,
    });
    vm.runInContext(fs.readFileSync(path.join(__dirname, '../../app/static/js', file), 'utf8') + `\nthis.page = ${name};`, context);
    return { page: context.page, events };
}

for (const action of ['complete', 'sign']) {
    test(`onboarding ${action} refreshes the underlying row before dismissal`, async () => {
        const cells = Object.fromEntries(['complete', 'total', 'percent'].map(k => [k, { textContent: 'stale' }]));
        const summary = { complete: 1, total: 8, percent_complete: 12.5,
            tasks: [{ id: 11, task_type: 'w4', status: 'complete', signed: true }] };
        const { page, events } = load('onboarding.js', 'OnboardingPage', {
            document: { querySelector: selector => {
                assert.equal(selector, '[data-onboarding-employee="7"]');
                return { querySelector: key => cells[key.match(/"(.*?)"/)[1]] };
            } },
            API: { post: async () => ({}), put: async () => ({}), get: async () => summary },
        });
        if (action === 'complete') await page.completeTask(11, 7);
        else await page.signTask(11, true, 7);
        assert.equal(cells.complete.textContent, 1);
        assert.equal(cells.total.textContent, 8);
        assert.equal(cells.percent.textContent, '12.5%');
        assert.ok(events.includes('open'));
    });
}

test('failed onboarding save does not close or refresh the dialog', async () => {
    const { page, events } = load('onboarding.js', 'OnboardingPage', {
        API: { post: async () => { throw Error('save failed'); } },
    });
    await page.completeTask(11, 7);
    assert.deepEqual(events, [['save failed', 'error']]);
});

test('onboarding can refresh its dialog after navigating away from the list', async () => {
    const { page, events } = load('onboarding.js', 'OnboardingPage', {
        document: { querySelector: () => null },
        API: { get: async () => ({ tasks: [{ id: 1, task_type: 'w4' }], complete: 0, total: 1, percent_complete: 0 }) },
    });
    await page.viewChecklist(7);
    assert.ok(events.includes('open'));
});

test('coverage plan save returns to Coverage, not payroll benefit codes', async () => {
    const { page, events } = load('benefit_coverage.js', 'BenefitCoveragePage');
    await page.createPlan();
    assert.ok(events.includes('#/hr/benefit-coverage'));
    assert.ok(!events.includes('#/hr/benefits'));
});

test('pay schedule assignment refreshes the page and employee cache', async () => {
    const { page, events } = load('pay_schedules.js', 'PaySchedulesPage');
    await page.assign(1);
    assert.ok(events.includes('#/payroll/schedules'));
});

test('termination refreshes the list without requiring the Done button', async () => {
    const elements = {
        '#term-date': { value: '2026-09-07' },
        '#term-reason': { value: 'voluntary' },
        '#term-payout': { value: 'yes' },
        '#term-sick': { value: 'no' },
        '#term-benefit-end': { value: '2026-09-30' },
        '#term-submit': { disabled: false, textContent: 'Terminate' },
        '#term-result': { innerHTML: '' },
        '#term-form-fields': { hidden: false },
        '#term-actions': { innerHTML: '<button>Terminate</button>' },
    };
    let posts = 0;
    const { page, events } = load('employees.js', 'EmployeesPage', {
        $: selector => elements[selector],
        API: { post: async () => {
            posts += 1;
            return { final_paycheck: {}, pto_payout: { total_payout: 0 }, deductions_deactivated: 0, benefit_enrollments_ended: 2 };
        } },
    });
    await page.terminate(7);
    await page.terminate(7);
    assert.ok(events.includes('#/employees'));
    assert.ok(!events.includes('close'), 'Keep the termination result available');
    assert.equal(posts, 1, 'Disabled action blocks duplicate termination requests');
    assert.equal(elements['#term-form-fields'].hidden, true);
    assert.ok(!elements['#term-actions'].innerHTML.includes('Terminate'));
    assert.ok(elements['#term-actions'].innerHTML.includes('Done'));
});

test('failed termination re-enables its action for retry', async () => {
    const submit = { disabled: false, textContent: 'Terminate' };
    const values = {
        '#term-date': { value: '2026-09-07' }, '#term-reason': { value: 'voluntary' },
        '#term-payout': { value: 'no' }, '#term-sick': { value: 'no' }, '#term-submit': submit,
        '#term-benefit-end': { value: '2026-09-07' },
    };
    const { page, events } = load('employees.js', 'EmployeesPage', {
        $: selector => values[selector],
        API: { post: async () => { throw Error('save failed'); } },
    });
    await page.terminate(7);
    assert.equal(submit.disabled, false);
    assert.equal(submit.textContent, 'Terminate');
    assert.deepEqual(events, [['save failed', 'error']]);
});

test('AI Custom provider starts with its required model field visible', () => {
    const { page } = load('settings.js', 'SettingsPage');
    const custom = {
        key: 'custom', label: 'Custom (OpenAI-compatible)', default_model: '',
        model_choices: [], needs_endpoint_url: true,
    };
    const html = page._renderAiConfig({
        provider: 'custom', model: '', providers: [custom], has_api_key: false,
    });
    const modelInput = html.match(/id="ai-settings-model-custom"[\s\S]*?>/)[0];
    assert.ok(modelInput.includes('maxlength="255"'));
    assert.ok(!modelInput.includes('display:none'));
    assert.ok(page._modelOptionsHtml(custom, '').includes('value="__custom__" selected'));
});

test('AI provider preserves a manual model ID across rendering', () => {
    const { page } = load('settings.js', 'SettingsPage');
    const provider = {
        key: 'openai', label: 'OpenAI', default_model: 'gpt-5.6-terra',
        model_choices: ['gpt-5.6-terra'],
    };
    const manual = 'account/pinned-model-2026-09-07';
    const html = page._renderAiConfig({
        provider: 'openai', model: manual, providers: [provider], has_api_key: false,
    });
    assert.ok(page._modelOptionsHtml(provider, manual).includes('value="__custom__" selected'));
    assert.ok(html.includes(`value="${manual}"`));
});
