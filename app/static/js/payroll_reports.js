/**
 * Payroll Reports — the report library the payroll routes feed:
 * payroll journal (GL reconciliation), deduction register (benefit /
 * 401k remittance reconciliation), contractor payments (1099 split by
 * payment path).
 */
const PayrollReportsPage = {
    async render() {
        const year = new Date().getFullYear();
        const jan1 = `${year}-01-01`;
        const dec31 = `${year}-12-31`;
        return `
            <div class="page-header">
                <h2>Payroll Reports</h2>
                <div style="font-size:10px; color:var(--text-muted);">
                    Payroll journal, deduction register, and contractor payments
                </div>
            </div>
            <div class="toolbar">
                <button class="btn" id="pr-tab-journal" onclick="PayrollReportsPage.showTab('journal')">Payroll Journal</button>
                <button class="btn" id="pr-tab-deductions" onclick="PayrollReportsPage.showTab('deductions')">Deduction Register</button>
                <button class="btn" id="pr-tab-contractors" onclick="PayrollReportsPage.showTab('contractors')">Contractor Payments</button>
            </div>
            <div id="pr-controls">
                <div class="form-grid" style="max-width:520px;">
                    <div class="form-group"><label>From</label>
                        <input type="date" id="pr-start" value="${jan1}"></div>
                    <div class="form-group"><label>To</label>
                        <input type="date" id="pr-end" value="${dec31}"></div>
                    <div class="form-group"><label>Year</label>
                        <input type="number" id="pr-year" value="${year}" min="2000" max="2100"></div>
                </div>
                <button class="btn btn-primary" onclick="PayrollReportsPage.run()">Run Report</button>
            </div>
            <div id="pr-results" style="margin-top:14px;"></div>`;
    },

    _tab: 'journal',

    showTab(tab) {
        PayrollReportsPage._tab = tab;
        ['journal', 'deductions', 'contractors'].forEach(t => {
            const btn = $(`#pr-tab-${t}`);
            if (btn) btn.classList.toggle('btn-primary', t === tab);
        });
        const results = $('#pr-results');
        if (results) results.innerHTML = '';
    },

    async run() {
        const box = $('#pr-results');
        if (!box) return;
        try {
            if (PayrollReportsPage._tab === 'journal') {
                const start = $('#pr-start')?.value;
                const end = $('#pr-end')?.value;
                if (!start || !end) return toast('Pick a date range', 'error');
                const data = await API.get(`/reports/payroll-journal?start=${start}&end=${end}`);
                box.innerHTML = PayrollReportsPage.renderJournal(data);
            } else if (PayrollReportsPage._tab === 'deductions') {
                const year = parseInt($('#pr-year')?.value, 10);
                if (!year) return toast('Enter a year', 'error');
                const data = await API.get(`/reports/deduction-register?year=${year}`);
                box.innerHTML = PayrollReportsPage.renderDeductions(data);
            } else {
                const year = parseInt($('#pr-year')?.value, 10);
                if (!year) return toast('Enter a year', 'error');
                const data = await API.get(`/reports/contractor-payments?year=${year}`);
                box.innerHTML = PayrollReportsPage.renderContractors(data);
            }
        } catch (e) {
            toast(e.message, 'error');
        }
    },

    renderJournal(data) {
        if (!data.runs.length) {
            return '<div class="empty-state"><p>No processed pay runs in this window.</p></div>';
        }
        let html = `<h3>Payroll Journal ${formatDate(data.start)} &ndash; ${formatDate(data.end)}</h3>`;
        for (const run of data.runs) {
            let rows = run.stubs.map(s => `<tr>
                <td>${escapeHtml(s.employee_name || '')}</td>
                <td class="amount">${formatCurrency(s.gross)}</td>
                <td class="amount">${formatCurrency(s.federal)}</td>
                <td class="amount">${formatCurrency(s.state)}</td>
                <td class="amount">${formatCurrency(s.ss)}</td>
                <td class="amount">${formatCurrency(s.medicare)}</td>
                <td class="amount">${formatCurrency(s.pretax_deductions)}</td>
                <td class="amount">${formatCurrency(s.garnishments)}</td>
                <td class="amount">${formatCurrency(s.net)}</td>
                <td class="amount">${formatCurrency(s.employer_taxes)}</td>
            </tr>`).join('');
            html += `<h4 style="margin-top:12px; font-size:12px;">
                    Run #${run.pay_run_id} — paid ${formatDate(run.pay_date)}
                    ${run.transaction_id ? `(JE ${run.transaction_id})` : ''}</h4>
                <div class="table-container"><table>
                <thead><tr><th scope="col">Employee</th><th scope="col" class="amount">Gross</th>
                <th scope="col" class="amount">Fed</th><th scope="col" class="amount">State</th>
                <th scope="col" class="amount">SS</th><th scope="col" class="amount">Medicare</th>
                <th scope="col" class="amount">Pre-tax</th><th scope="col" class="amount">Garnish</th>
                <th scope="col" class="amount">Net</th><th scope="col" class="amount">Employer</th></tr></thead>
                <tbody>${rows}</tbody></table></div>`;
        }
        const t = data.totals;
        html += `<div style="font-size:12px; font-weight:700; margin-top:10px;">
            Window totals — gross ${formatCurrency(t.gross)},
            net ${formatCurrency(t.net)},
            employer taxes ${formatCurrency(t.employer_taxes)}</div>`;
        return html;
    },

    renderDeductions(data) {
        if (!data.rows.length) {
            return `<div class="empty-state"><p>No deductions withheld in ${data.year}.</p></div>`;
        }
        let rows = data.rows.map(r => `<tr>
            <td>${escapeHtml(r.employee_name || '')}</td>
            <td class="amount">${formatCurrency(r.pretax_deductions)}</td>
            <td class="amount">${formatCurrency(r.posttax_deductions)}</td>
            <td class="amount">${formatCurrency(r.garnishments)}</td>
            <td class="amount">${r.stub_count}</td>
        </tr>`).join('');
        const t = data.totals;
        return `<h3>Deduction Register — ${data.year}</h3>
            <div class="table-container"><table>
            <thead><tr><th scope="col">Employee</th><th scope="col" class="amount">Pre-tax</th>
            <th scope="col" class="amount">Post-tax</th><th scope="col" class="amount">Garnishments</th>
            <th scope="col" class="amount">Stubs</th></tr></thead>
            <tbody>${rows}</tbody></table></div>
            <div style="font-size:12px; font-weight:700; margin-top:8px;">
                Totals — pre-tax ${formatCurrency(t.pretax_deductions)},
                post-tax ${formatCurrency(t.posttax_deductions)},
                garnishments ${formatCurrency(t.garnishments)}</div>`;
    },

    renderContractors(data) {
        if (!data.rows.length) {
            return `<div class="empty-state"><p>No contractor payments in ${data.year}.</p></div>`;
        }
        let rows = data.rows.map(r => `<tr>
            <td>${escapeHtml(r.vendor_name || '')}</td>
            <td>${r.is_1099_vendor ? '<span class="badge badge-paid">1099</span>' : ''}</td>
            <td class="amount">${formatCurrency(r.ap_bill_payments)}</td>
            <td class="amount">${formatCurrency(r.contractor_run_payments)}</td>
            <td class="amount">${formatCurrency(r.total)}</td>
        </tr>`).join('');
        return `<h3>Contractor Payments — ${data.year}</h3>
            <div class="table-container"><table>
            <thead><tr><th scope="col">Vendor</th><th scope="col">1099</th>
            <th scope="col" class="amount">AP Bill Payments</th>
            <th scope="col" class="amount">Contractor Runs</th>
            <th scope="col" class="amount">Total</th></tr></thead>
            <tbody>${rows}</tbody></table></div>
            <div style="font-size:12px; font-weight:700; margin-top:8px;">
                Total: ${formatCurrency(data.total)}</div>`;
    },
};
