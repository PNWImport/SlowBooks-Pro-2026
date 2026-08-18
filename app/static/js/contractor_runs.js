/**
 * Contractor Pay Runs — batch-paying 1099 contractors, payroll-style.
 *
 * One dated run, many payees, one JE, one NACHA file. No withholding —
 * 1099 payees get gross. Payments here join bill payments in the
 * 1099-NEC totals (services/form_1099.py).
 */
const ContractorRunsPage = {
    _vendors: [],

    async render() {
        const [runs, vendors] = await Promise.all([
            API.get('/contractor-runs'),
            API.get('/vendors'),
        ]);
        ContractorRunsPage._vendors = vendors;

        return `
            <div class="page-header">
                <h2>Contractor Pay Runs</h2>
                <div style="font-size:10px; color:var(--text-muted);">
                    Batch contractor payments &mdash; each run posts one JE and exports one NACHA file
                </div>
            </div>

            <div class="toolbar">
                <button class="btn btn-primary" onclick="ContractorRunsPage.newRunModal()">New Run</button>
            </div>

            ${ContractorRunsPage.runsTable(runs)}`;
    },

    statusBadge(status) {
        const cls = { processed: 'badge-paid', void: 'badge-void' }[status] || 'badge-sent';
        return `<span class="badge ${cls}">${escapeHtml(status || 'draft')}</span>`;
    },

    runsTable(runs) {
        if (!runs.length) {
            return `<div class="empty-state"><p>No contractor pay runs yet.
                A run groups payments to one or more 1099 vendors under a
                single pay date, journal entry, and NACHA file.</p></div>`;
        }
        let html = `<div class="table-container"><table>
            <thead><tr>
                <th>ID</th><th>Pay Date</th><th>Memo</th><th>Payees</th>
                <th class="amount">Total</th><th>Status</th><th>JE</th><th>Actions</th>
            </tr></thead><tbody>`;
        for (const r of runs) {
            const actions = [];
            if (r.status === 'draft') {
                actions.push(`<button class="btn" onclick="ContractorRunsPage.processRun(${r.id})">Process</button>`);
            }
            if (r.status === 'processed') {
                actions.push(`<button class="btn" onclick="ContractorRunsPage.nachaModal(${r.id})">NACHA</button>`);
            }
            actions.push(`<button class="btn" onclick="ContractorRunsPage.detailModal(${r.id})">Details</button>`);
            html += `<tr>
                <td>${r.id}</td>
                <td>${formatDate(r.pay_date)}</td>
                <td>${escapeHtml(r.memo || '')}</td>
                <td>${r.payments.length}</td>
                <td class="amount">${formatCurrency(r.total_amount)}</td>
                <td>${ContractorRunsPage.statusBadge(r.status)}</td>
                <td>${r.transaction_id || ''}</td>
                <td>${actions.join(' ')}</td>
            </tr>`;
        }
        return html + '</tbody></table></div>';
    },

    newRunModal() {
        const vendors = ContractorRunsPage._vendors;
        if (!vendors.length) {
            return toast('Create at least one vendor first', 'error');
        }
        const vendorOpts = vendors.map(v =>
            `<option value="${v.id}">${escapeHtml(v.name)}</option>`
        ).join('');

        openModal('New Contractor Pay Run', `
            <div class="form-group">
                <label>Pay date</label>
                <input type="date" id="cr-date" value="${todayISO()}">
            </div>
            <div class="form-group">
                <label>Memo</label>
                <input type="text" id="cr-memo" placeholder="August contractor payments">
            </div>
            <div id="cr-lines">
                <div class="form-group" style="display:flex;gap:8px;align-items:end;" data-line="0">
                    <div style="flex:2;">
                        <label>Vendor</label>
                        <select id="cr-vendor-0">${vendorOpts}</select>
                    </div>
                    <div style="flex:1;">
                        <label>Amount</label>
                        <input type="number" step="0.01" id="cr-amt-0" value="0">
                    </div>
                    <div style="flex:2;">
                        <label>Description</label>
                        <input type="text" id="cr-desc-0" placeholder="Services rendered">
                    </div>
                </div>
            </div>
            <button class="btn" onclick="ContractorRunsPage.addLine()" style="margin:8px 0;">+ Add Payee</button>
            <div class="form-actions">
                <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
                <button class="btn btn-primary" onclick="ContractorRunsPage.createRun()">Create</button>
            </div>`);
        ContractorRunsPage._lineCount = 1;
    },

    _lineCount: 1,

    addLine() {
        const i = ContractorRunsPage._lineCount++;
        const vendors = ContractorRunsPage._vendors;
        const vendorOpts = vendors.map(v =>
            `<option value="${v.id}">${escapeHtml(v.name)}</option>`
        ).join('');
        const box = $('#cr-lines');
        if (!box) return;
        const div = document.createElement('div');
        div.className = 'form-group';
        div.style.cssText = 'display:flex;gap:8px;align-items:end;';
        div.dataset.line = String(i);
        div.innerHTML = `
            <div style="flex:2;">
                <label>Vendor</label>
                <select id="cr-vendor-${i}">${vendorOpts}</select>
            </div>
            <div style="flex:1;">
                <label>Amount</label>
                <input type="number" step="0.01" id="cr-amt-${i}" value="0">
            </div>
            <div style="flex:2;">
                <label>Description</label>
                <input type="text" id="cr-desc-${i}" placeholder="Services rendered">
            </div>`;
        box.appendChild(div);
    },

    async createRun() {
        const payments = [];
        for (let i = 0; i < ContractorRunsPage._lineCount; i++) {
            const vendorEl = $(`#cr-vendor-${i}`);
            const amtEl = $(`#cr-amt-${i}`);
            if (!vendorEl || !amtEl) continue;
            const amount = parseFloat(amtEl.value);
            if (!amount || amount <= 0) continue;
            const descEl = $(`#cr-desc-${i}`);
            payments.push({
                vendor_id: parseInt(vendorEl.value, 10),
                amount,
                description: descEl ? descEl.value.trim() || null : null,
            });
        }
        if (!payments.length) return toast('Add at least one payment', 'error');
        try {
            await API.post('/contractor-runs', {
                pay_date: $('#cr-date').value,
                memo: $('#cr-memo').value.trim() || null,
                payments,
            });
            closeModal();
            toast('Contractor run created');
            App.navigate('#/payroll/contractors');
        } catch (e) {
            toast(e.message, 'error');
        }
    },

    async processRun(runId) {
        try {
            const result = await API.post(`/contractor-runs/${runId}/process`);
            toast(`Processed — JE #${result.transaction_id}`);
            App.navigate('#/payroll/contractors');
        } catch (e) {
            toast(e.message, 'error');
        }
    },

    async detailModal(runId) {
        try {
            const run = await API.get(`/contractor-runs/${runId}`);
            let rows = '';
            for (const p of run.payments) {
                rows += `<tr>
                    <td>${escapeHtml(p.vendor_name || `Vendor #${p.vendor_id}`)}</td>
                    <td class="amount">${formatCurrency(p.amount)}</td>
                    <td>${escapeHtml(p.description || '')}</td>
                </tr>`;
            }
            openModal(`Run #${run.id} — ${formatDate(run.pay_date)}`, `
                <p>Status: ${ContractorRunsPage.statusBadge(run.status)}
                   &nbsp; Total: <strong>${formatCurrency(run.total_amount)}</strong>
                   ${run.memo ? ` &nbsp; Memo: ${escapeHtml(run.memo)}` : ''}
                   ${run.transaction_id ? ` &nbsp; JE #${run.transaction_id}` : ''}</p>
                <div class="table-container"><table>
                    <thead><tr><th>Vendor</th><th class="amount">Amount</th><th>Description</th></tr></thead>
                    <tbody>${rows}</tbody>
                </table></div>
                <div class="form-actions">
                    <button class="btn btn-secondary" onclick="closeModal()">Close</button>
                </div>`);
        } catch (e) {
            toast(e.message, 'error');
        }
    },

    nachaModal(runId) {
        openModal('NACHA Export', `
            <p style="font-size:10px;color:var(--text-muted);">
                ACH origination details — these come from your bank. The file
                credits each contractor's bank account on file.
            </p>
            <div class="form-group">
                <label>Immediate Destination (routing)</label>
                <input type="text" id="nc-dest" maxlength="9" placeholder="021000021">
            </div>
            <div class="form-group">
                <label>Immediate Origin (your routing or EIN)</label>
                <input type="text" id="nc-origin" placeholder="123456789">
            </div>
            <div class="form-group">
                <label>Originating DFI ID (8 digits)</label>
                <input type="text" id="nc-dfi" maxlength="8" placeholder="02100002">
            </div>
            <div class="form-actions">
                <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
                <button class="btn btn-primary" onclick="ContractorRunsPage.exportNacha(${runId})">Export</button>
            </div>`);
    },

    async exportNacha(runId) {
        const dest = ($('#nc-dest')?.value || '').trim();
        const origin = ($('#nc-origin')?.value || '').trim();
        const dfi = ($('#nc-dfi')?.value || '').trim();
        if (!dest || !origin || !dfi) {
            return toast('All three origination fields are required', 'error');
        }
        try {
            const res = await fetch(`/api/contractor-runs/${runId}/nacha`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify({
                    immediate_destination: dest,
                    immediate_origin: origin,
                    originating_dfi_id: dfi,
                }),
            });
            if (!res.ok) {
                let msg = 'NACHA export failed';
                try { msg = (await res.json()).detail || msg; } catch (_) {}
                return toast(msg, 'error');
            }
            const url = URL.createObjectURL(await res.blob());
            window.open(url, '_blank');
            setTimeout(() => URL.revokeObjectURL(url), 15000);
            closeModal();
            toast('NACHA file exported');
        } catch (e) {
            toast(e.message, 'error');
        }
    },
};
