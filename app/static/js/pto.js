/**
 * PTO — manage PTO policies and requests
 * Feature 24: Paid time off tracking
 */
const PTOPage = {
    async render() {
        const [policies, requests] = await Promise.all([
            API.get('/pto/policies'),
            API.get('/pto/requests'),
        ]);

        // --- Policies section ---
        let policiesBody = '';
        if (policies.length === 0) {
            policiesBody = '<tr><td colspan="6"><em>No policies defined yet</em></td></tr>';
        } else {
            for (const p of policies) {
                policiesBody += `<tr>
                    <td><strong>${escapeHtml(p.name)}</strong></td>
                    <td>${escapeHtml(p.pto_type)}</td>
                    <td>${escapeHtml(p.accrual_method)}</td>
                    <td class="amount">${p.accrual_rate}</td>
                    <td class="amount">${p.max_balance}</td>
                    <td class="actions">
                        <button class="btn btn-sm btn-secondary" onclick="PTOPage.showPolicyForm(${p.id})">Edit</button>
                    </td>
                </tr>`;
            }
        }

        // --- Requests section ---
        let requestsBody = '';
        if (requests.length === 0) {
            requestsBody = '<tr><td colspan="7"><em>No PTO requests on file</em></td></tr>';
        } else {
            for (const r of requests) {
                const isPending = r.status === 'pending';
                const approveBtn = isPending
                    ? `<button class="btn btn-sm btn-primary" onclick="PTOPage.approveRequest(${r.id})">Approve</button>`
                    : '';
                const rejectBtn = isPending
                    ? `<button class="btn btn-sm btn-secondary" onclick="PTOPage.rejectRequest(${r.id})">Reject</button>`
                    : '';
                requestsBody += `<tr>
                    <td>${escapeHtml(r.employee_name || String(r.employee_id))}</td>
                    <td>${formatDate(r.start_date)}</td>
                    <td>${formatDate(r.end_date)}</td>
                    <td class="amount">${r.hours}</td>
                    <td>${escapeHtml(r.pto_type)}</td>
                    <td>${statusBadge(r.status)}</td>
                    <td class="actions">${approveBtn}${rejectBtn}</td>
                </tr>`;
            }
        }

        return `
            <div class="page-header">
                <h2>PTO Policies</h2>
                <button class="btn btn-primary" onclick="PTOPage.showPolicyForm()">+ Add Policy</button>
            </div>
            <div class="table-container">
                <table>
                    <thead><tr>
                        <th>Name</th>
                        <th>Type</th>
                        <th>Accrual Method</th>
                        <th class="amount">Accrual Rate</th>
                        <th class="amount">Max Balance</th>
                        <th>Actions</th>
                    </tr></thead>
                    <tbody>${policiesBody}</tbody>
                </table>
            </div>

            <div class="page-header" style="margin-top:2rem">
                <h2>PTO Requests</h2>
                <button class="btn btn-primary" onclick="PTOPage.showRequestForm()">+ New Request</button>
            </div>
            <div class="table-container">
                <table>
                    <thead><tr>
                        <th>Employee</th>
                        <th>Start</th>
                        <th>End</th>
                        <th class="amount">Hours</th>
                        <th>Type</th>
                        <th>Status</th>
                        <th>Actions</th>
                    </tr></thead>
                    <tbody>${requestsBody}</tbody>
                </table>
            </div>`;
    },

    async showPolicyForm(id = null) {
        let p = { name: '', pto_type: 'vacation', accrual_method: 'per_pay_period', accrual_rate: 0, max_balance: 0 };
        if (id) p = await API.get(`/pto/policies/${id}`);

        openModal(id ? 'Edit PTO Policy' : 'Add PTO Policy', `
            <form onsubmit="PTOPage.savePolicy(event, ${id})">
                <div class="form-grid">
                    <div class="form-group"><label>Policy Name *</label>
                        <input name="name" required value="${escapeHtml(p.name)}"></div>
                    <div class="form-group"><label>PTO Type</label>
                        <select name="pto_type">
                            <option value="vacation"  ${p.pto_type === 'vacation'  ? 'selected' : ''}>Vacation</option>
                            <option value="sick"      ${p.pto_type === 'sick'      ? 'selected' : ''}>Sick</option>
                            <option value="personal"  ${p.pto_type === 'personal'  ? 'selected' : ''}>Personal</option>
                        </select></div>
                    <div class="form-group"><label>Accrual Method</label>
                        <select name="accrual_method">
                            <option value="per_pay_period"    ${p.accrual_method === 'per_pay_period'    ? 'selected' : ''}>Per Pay Period</option>
                            <option value="per_hour_worked"   ${p.accrual_method === 'per_hour_worked'   ? 'selected' : ''}>Per Hour Worked</option>
                            <option value="annual_lump_sum"   ${p.accrual_method === 'annual_lump_sum'   ? 'selected' : ''}>Annual Lump Sum</option>
                        </select></div>
                    <div class="form-group"><label>Accrual Rate</label>
                        <input name="accrual_rate" type="number" step="0.01" value="${p.accrual_rate}"></div>
                    <div class="form-group"><label>Max Balance</label>
                        <input name="max_balance" type="number" step="0.01" value="${p.max_balance}"></div>
                </div>
                <div class="form-actions">
                    <button type="button" class="btn btn-secondary" onclick="closeModal()">Cancel</button>
                    <button type="submit" class="btn btn-primary">${id ? 'Update' : 'Add'} Policy</button>
                </div>
            </form>`);
    },

    async savePolicy(e, id) {
        e.preventDefault();
        const data = Object.fromEntries(new FormData(e.target).entries());
        data.accrual_rate = parseFloat(data.accrual_rate) || 0;
        data.max_balance  = parseFloat(data.max_balance)  || 0;
        try {
            if (id) { await API.put(`/pto/policies/${id}`, data); toast('Policy updated'); }
            else    { await API.post('/pto/policies', data);      toast('Policy added'); }
            closeModal();
            App.navigate('#/hr/pto');
        } catch (err) { toast(err.message, 'error'); }
    },

    async showRequestForm() {
        let emps = [];
        try {
            emps = await API.get('/employees?active_only=true');
        } catch {
            toast('Failed to load employees', 'error');
            return;
        }

        const empOptions = emps.map(emp =>
            `<option value="${emp.id}">${escapeHtml(emp.first_name)} ${escapeHtml(emp.last_name)}</option>`
        ).join('');

        openModal('New PTO Request', `
            <form onsubmit="PTOPage.saveRequest(event)">
                <div class="form-grid">
                    <div class="form-group"><label>Employee *</label>
                        <select name="employee_id" required>
                            <option value="">— Select Employee —</option>
                            ${empOptions}
                        </select></div>
                    <div class="form-group"><label>PTO Type</label>
                        <select name="pto_type">
                            <option value="vacation">Vacation</option>
                            <option value="sick">Sick</option>
                            <option value="personal">Personal</option>
                        </select></div>
                    <div class="form-group"><label>Start Date *</label>
                        <input name="start_date" type="date" required value="${todayISO()}"></div>
                    <div class="form-group"><label>End Date *</label>
                        <input name="end_date" type="date" required value="${todayISO()}"></div>
                    <div class="form-group"><label>Hours</label>
                        <input name="hours" type="number" step="0.5" min="0" value="8"></div>
                    <div class="form-group"><label>Notes</label>
                        <input name="notes" value=""></div>
                </div>
                <div class="form-actions">
                    <button type="button" class="btn btn-secondary" onclick="closeModal()">Cancel</button>
                    <button type="submit" class="btn btn-primary">Submit Request</button>
                </div>
            </form>`);
    },

    async saveRequest(e) {
        e.preventDefault();
        const data = Object.fromEntries(new FormData(e.target).entries());
        data.employee_id = parseInt(data.employee_id) || 0;
        data.hours       = parseFloat(data.hours) || 0;
        if (!data.notes) delete data.notes;
        try {
            await API.post('/pto/requests', data);
            toast('PTO request submitted');
            closeModal();
            App.navigate('#/hr/pto');
        } catch (err) { toast(err.message, 'error'); }
    },

    async approveRequest(id) {
        try {
            await API.post(`/pto/requests/${id}/approve`, {});
            toast('Request approved');
            App.navigate('#/hr/pto');
        } catch (err) { toast(err.message, 'error'); }
    },

    async rejectRequest(id) {
        try {
            await API.post(`/pto/requests/${id}/reject`, {});
            toast('Request rejected');
            App.navigate('#/hr/pto');
        } catch (err) { toast(err.message, 'error'); }
    },
};
