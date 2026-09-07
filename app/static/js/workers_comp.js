/**
 * Workers' Comp — carrier class rates + the annual premium-audit report.
 *
 * A new rate for the same (state, class) supersedes the old one; the
 * premium report surfaces classes with no rate on file so nothing gets
 * silently priced at zero.
 */
const WorkersCompPage = {
    async render() {
        const rates = await API.get('/workers-comp/rates');
        const year = new Date().getFullYear();
        return `
            <div class="page-header">
                <h2>Workers' Comp</h2>
                <div style="font-size:10px; color:var(--text-muted);">
                    Carrier class rates and the annual premium-audit report
                </div>
            </div>
            <div class="toolbar">
                <button class="btn btn-primary" onclick="WorkersCompPage.newRateModal()">New Rate</button>
                <label style="font-size:11px; margin-left:12px;">Report year
                    <input type="number" id="wc-year" value="${year}" min="2000" max="2100"
                        style="width:80px; margin-left:6px;">
                </label>
                <button class="btn" onclick="WorkersCompPage.loadReport()">Premium Report</button>
            </div>
            ${WorkersCompPage.ratesTable(rates)}
            <div id="wc-report"></div>`;
    },

    ratesTable(rates) {
        if (!rates.length) {
            return '<div class="empty-state"><p>No WC class rates on file.</p></div>';
        }
        let rows = rates.map(r => `<tr>
            <td>${escapeHtml(r.state)}</td>
            <td>${escapeHtml(r.class_code)}</td>
            <td>${escapeHtml(r.description || '')}</td>
            <td class="amount">${r.rate_per_100.toFixed(2)}</td>
            <td>${r.is_active
                ? '<span class="badge badge-paid">active</span>'
                : '<span class="badge badge-void">superseded</span>'}</td>
        </tr>`).join('');
        return `<div class="table-container"><table>
            <thead><tr><th scope="col">State</th><th scope="col">Class</th><th scope="col">Description</th>
            <th scope="col" class="amount">Rate / $100</th><th scope="col">Status</th></tr></thead>
            <tbody>${rows}</tbody>
        </table></div>`;
    },

    newRateModal() {
        openModal('New WC Class Rate', `
            <div class="form-group">
                <label>State (2-letter code)</label>
                <input type="text" id="wc-state" maxlength="2" placeholder="WA">
            </div>
            <div class="form-group">
                <label>Class code</label>
                <input type="text" id="wc-class" placeholder="8810">
            </div>
            <div class="form-group">
                <label>Description</label>
                <input type="text" id="wc-desc" placeholder="Clerical office">
            </div>
            <div class="form-group">
                <label>Rate per $100 of payroll</label>
                <input type="number" id="wc-rate" step="0.01" min="0">
            </div>
            <div class="form-actions">
                <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
                <button class="btn btn-primary" onclick="WorkersCompPage.createRate()">Create</button>
            </div>`);
    },

    async createRate() {
        const state = ($('#wc-state')?.value || '').trim().toUpperCase();
        const classCode = ($('#wc-class')?.value || '').trim();
        const rate = parseFloat($('#wc-rate')?.value);
        if (!state || !classCode) return toast('State and class code are required', 'error');
        if (isNaN(rate)) return toast('Rate is required', 'error');
        try {
            await API.post('/workers-comp/rates', {
                state,
                class_code: classCode,
                description: $('#wc-desc').value || null,
                rate_per_100: rate,
            });
            closeModal();
            toast('Rate created');
            App.navigate('#/payroll/workers-comp');
        } catch (e) {
            toast(e.message, 'error');
        }
    },

    async loadReport() {
        const box = $('#wc-report');
        if (!box) return;
        const year = parseInt($('#wc-year')?.value, 10);
        if (!year) return toast('Enter a year', 'error');
        try {
            const report = await API.get(`/workers-comp/premium-report?year=${year}`);
            let missing = '';
            if (report.classes_missing_rates.length) {
                missing = `<div style="color:var(--danger); font-size:11px; margin:6px 0;">
                    No rate on file for: ${report.classes_missing_rates.map(escapeHtml).join(', ')}</div>`;
            }
            if (!report.rows.length) {
                box.innerHTML = `<h3 style="margin-top:18px;">Premium Report — ${year}</h3>
                    ${missing}<p style="color:var(--text-muted); font-size:11px;">No processed payroll for ${year}.</p>`;
                return;
            }
            let rows = report.rows.map(r => `<tr>
                <td>${escapeHtml(r.state)}</td>
                <td>${escapeHtml(r.class_code)}</td>
                <td class="amount">${r.employees}</td>
                <td class="amount">${formatCurrency(r.wages)}</td>
                <td class="amount">${r.rate_per_100 != null ? r.rate_per_100.toFixed(2) : '<span style="color:var(--danger);">none</span>'}</td>
                <td class="amount">${r.premium != null ? formatCurrency(r.premium) : ''}</td>
            </tr>`).join('');
            box.innerHTML = `
                <h3 style="margin-top:18px;">Premium Report — ${year}</h3>
                ${missing}
                <div class="table-container"><table>
                    <thead><tr><th scope="col">State</th><th scope="col">Class</th><th scope="col" class="amount">Employees</th>
                    <th scope="col" class="amount">Wages</th><th scope="col" class="amount">Rate / $100</th>
                    <th scope="col" class="amount">Premium</th></tr></thead>
                    <tbody>${rows}</tbody>
                </table></div>
                <div style="font-size:12px; font-weight:700; margin-top:8px;">
                    Total premium: ${formatCurrency(report.total_premium)}</div>`;
        } catch (e) {
            toast(e.message, 'error');
        }
    },
};
