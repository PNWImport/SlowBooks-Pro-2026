/**
 * Garnishment Remittance Register — tracking withheld garnishment money
 * from processed pay runs until it is forwarded to the agency.
 *
 * The classic small-employer garnishment failure is withholding the money
 * and then never sending it. This page makes the pending balance visible
 * and lets the operator mark rows remitted with a payment reference once
 * the check or ACH actually goes out.
 */
const GarnishmentRemittancesPage = {
    _status: 'pending',

    async render() {
        const data = await API.get(`/deductions/garnishments/remittances?status=${GarnishmentRemittancesPage._status}`);
        GarnishmentRemittancesPage._data = data;

        return `
            <div class="page-header">
                <h2>Garnishment Remittances</h2>
                <div style="font-size:10px; color:var(--text-muted);">
                    Withheld garnishment money owed to agencies &mdash; mark remitted once sent
                </div>
            </div>

            <div class="toolbar">
                <select id="rem-status" onchange="GarnishmentRemittancesPage.reload()">
                    <option value="pending" ${GarnishmentRemittancesPage._status === 'pending' ? 'selected' : ''}>Pending</option>
                    <option value="remitted" ${GarnishmentRemittancesPage._status === 'remitted' ? 'selected' : ''}>Remitted</option>
                    <option value="all" ${GarnishmentRemittancesPage._status === 'all' ? 'selected' : ''}>All</option>
                </select>
                ${data.total_pending > 0
                    ? `<span style="font-weight:700;color:var(--accent,#c00);">
                        Pending total: ${formatCurrency(data.total_pending)}</span>`
                    : ''}
            </div>

            <div id="remittance-results">
                ${GarnishmentRemittancesPage.remittanceTable(data.rows)}
            </div>`;
    },

    async reload() {
        GarnishmentRemittancesPage._status = $('#rem-status')?.value || 'pending';
        App.navigate('#/payroll/remittances');
    },

    remittanceTable(rows) {
        if (!rows.length) {
            const label = GarnishmentRemittancesPage._status;
            return `<div class="empty-state"><p>No ${label === 'all' ? '' : label + ' '}remittances.</p></div>`;
        }
        let html = `<div class="table-container"><table>
            <thead><tr>
                <th scope="col">Employee</th><th scope="col">Type</th><th scope="col">Agency</th><th scope="col">Case #</th>
                <th scope="col" class="amount">Amount</th><th scope="col">Withheld</th>
                <th scope="col">Status</th><th scope="col">Reference</th><th scope="col">Actions</th>
            </tr></thead><tbody>`;
        for (const r of rows) {
            const isPending = !r.remitted_at;
            const agencyCell = r.agency_missing
                ? `<span style="color:var(--accent,#c00);font-weight:700;">missing</span>`
                : escapeHtml(r.agency_name || '');

            html += `<tr>
                <td>${escapeHtml(r.employee_name || '')}</td>
                <td>${escapeHtml(r.garnishment_type || '')}</td>
                <td>${agencyCell}</td>
                <td>${escapeHtml(r.case_number || '')}</td>
                <td class="amount">${formatCurrency(r.amount)}</td>
                <td>${formatDate(r.withheld_date)}</td>
                <td>${isPending
                    ? '<span class="badge badge-sent">pending</span>'
                    : '<span class="badge badge-paid">remitted</span>'}</td>
                <td>${escapeHtml(r.remit_payment_reference || '')}</td>
                <td>${isPending
                    ? `<button class="btn" onclick="GarnishmentRemittancesPage.markModal(${r.id})">Mark Remitted</button>`
                    : `<span style="font-size:10px;color:var(--text-muted);">${formatDate(r.remitted_at)}</span>`}</td>
            </tr>`;
        }
        return html + '</tbody></table></div>';
    },

    markModal(remittanceId) {
        openModal('Mark Remitted', `
            <p style="font-size:10px;color:var(--text-muted);">
                Record the payment reference (check number, ACH trace, wire
                confirmation) so the remittance register shows what was sent.
            </p>
            <div class="form-group">
                <label>Payment reference</label>
                <input type="text" id="mr-ref" placeholder="Check #12345 / ACH trace 20260818...">
            </div>
            <div class="form-actions">
                <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
                <button class="btn btn-primary" onclick="GarnishmentRemittancesPage.markRemitted(${remittanceId})">Confirm</button>
            </div>`);
    },

    async markRemitted(remittanceId) {
        const ref = ($('#mr-ref')?.value || '').trim();
        if (!ref) return toast('Payment reference is required', 'error');
        try {
            await API.post(`/deductions/garnishments/remittances/${remittanceId}/mark-remitted`, {
                payment_reference: ref,
            });
            closeModal();
            toast('Marked remitted');
            App.navigate('#/payroll/remittances');
        } catch (e) {
            toast(e.message, 'error');
        }
    },
};
