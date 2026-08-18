/**
 * Pay Schedules — CRUD, upcoming-dates preview, employee assignment.
 *
 * A pay schedule defines the frequency and anchor date for a group of
 * employees. Assigning an employee syncs their pay_frequency to the
 * schedule's, so the payroll run picks them up on the right cadence.
 */
const PaySchedulesPage = {
    async render() {
        const [schedules, employees] = await Promise.all([
            API.get('/pay-schedules'),
            API.get('/employees?active_only=false'),
        ]);
        PaySchedulesPage._employees = employees;

        return `
            <div class="page-header">
                <h2>Pay Schedules</h2>
                <div style="font-size:10px; color:var(--text-muted);">
                    Define pay cadences, preview upcoming dates, and assign employees
                </div>
            </div>

            <div class="toolbar">
                <button class="btn btn-primary" onclick="PaySchedulesPage.newModal()">New Schedule</button>
            </div>

            ${PaySchedulesPage.schedulesTable(schedules)}
            <div id="ps-upcoming"></div>`;
    },

    schedulesTable(schedules) {
        if (!schedules.length) {
            return `<div class="empty-state"><p>No pay schedules yet.</p></div>`;
        }
        let html = `<div class="table-container"><table>
            <thead><tr>
                <th>Name</th><th>Frequency</th><th>Anchor Date</th>
                <th>Lead Days</th><th>Weekend Shift</th><th>Status</th><th>Actions</th>
            </tr></thead><tbody>`;
        for (const s of schedules) {
            html += `<tr>
                <td>${escapeHtml(s.name)}</td>
                <td>${escapeHtml(s.frequency || '')}</td>
                <td>${formatDate(s.anchor_pay_date)}</td>
                <td>${s.submission_lead_days}</td>
                <td>${escapeHtml((s.weekend_shift || '').replace(/_/g, ' '))}</td>
                <td>${s.is_active
                    ? '<span class="badge badge-paid">active</span>'
                    : '<span class="badge badge-void">inactive</span>'}</td>
                <td>
                    <button class="btn" onclick="PaySchedulesPage.editModal(${s.id})">Edit</button>
                    <button class="btn" onclick="PaySchedulesPage.previewUpcoming(${s.id})">Preview</button>
                    <button class="btn" onclick="PaySchedulesPage.assignModal(${s.id})">Assign</button>
                </td>
            </tr>`;
        }
        return html + '</tbody></table></div>';
    },

    newModal() {
        const freqs = ['weekly', 'biweekly', 'semimonthly', 'monthly'];
        const shifts = ['previous_business_day', 'next_business_day'];
        openModal('New Pay Schedule', `
            <div class="form-group">
                <label>Name</label>
                <input type="text" id="ps-name" placeholder="Biweekly Friday">
            </div>
            <div class="form-group">
                <label>Frequency</label>
                <select id="ps-freq">
                    ${freqs.map(f => `<option value="${f}">${f}</option>`).join('')}
                </select>
            </div>
            <div class="form-group">
                <label>Anchor pay date</label>
                <input type="date" id="ps-anchor" value="${todayISO()}">
            </div>
            <div class="form-group">
                <label>Submission lead days</label>
                <input type="number" id="ps-lead" value="2" min="0">
            </div>
            <div class="form-group">
                <label>Weekend shift</label>
                <select id="ps-shift">
                    ${shifts.map(s => `<option value="${s}">${s.replace(/_/g, ' ')}</option>`).join('')}
                </select>
            </div>
            <div class="form-actions">
                <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
                <button class="btn btn-primary" onclick="PaySchedulesPage.create()">Create</button>
            </div>`);
    },

    async editModal(scheduleId) {
        const freqs = ['weekly', 'biweekly', 'semimonthly', 'monthly'];
        const shifts = ['previous_business_day', 'next_business_day'];
        try {
            const schedules = await API.get('/pay-schedules');
            const s = schedules.find(x => x.id === scheduleId);
            if (!s) return toast('Schedule not found', 'error');

            openModal('Edit Pay Schedule', `
                <div class="form-group">
                    <label>Name</label>
                    <input type="text" id="ps-name" value="${escapeHtml(s.name)}">
                </div>
                <div class="form-group">
                    <label>Frequency</label>
                    <select id="ps-freq">
                        ${freqs.map(f => `<option value="${f}" ${s.frequency === f ? 'selected' : ''}>${f}</option>`).join('')}
                    </select>
                </div>
                <div class="form-group">
                    <label>Anchor pay date</label>
                    <input type="date" id="ps-anchor" value="${s.anchor_pay_date}">
                </div>
                <div class="form-group">
                    <label>Submission lead days</label>
                    <input type="number" id="ps-lead" value="${s.submission_lead_days}" min="0">
                </div>
                <div class="form-group">
                    <label>Weekend shift</label>
                    <select id="ps-shift">
                        ${shifts.map(sh => `<option value="${sh}" ${s.weekend_shift === sh ? 'selected' : ''}>${sh.replace(/_/g, ' ')}</option>`).join('')}
                    </select>
                </div>
                <div class="form-group">
                    <label>Active</label>
                    <select id="ps-active">
                        <option value="true" ${s.is_active ? 'selected' : ''}>Yes</option>
                        <option value="false" ${!s.is_active ? 'selected' : ''}>No</option>
                    </select>
                </div>
                <div class="form-actions">
                    <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
                    <button class="btn btn-primary" onclick="PaySchedulesPage.update(${scheduleId})">Save</button>
                </div>`);
        } catch (e) {
            toast(e.message, 'error');
        }
    },

    async update(scheduleId) {
        try {
            await API.put(`/pay-schedules/${scheduleId}`, {
                name: $('#ps-name').value.trim() || undefined,
                frequency: $('#ps-freq').value,
                anchor_pay_date: $('#ps-anchor').value,
                submission_lead_days: parseInt($('#ps-lead').value, 10),
                weekend_shift: $('#ps-shift').value,
                is_active: $('#ps-active').value === 'true',
            });
            closeModal();
            toast('Schedule updated');
            App.navigate('#/payroll/schedules');
        } catch (e) {
            toast(e.message, 'error');
        }
    },

    async create() {
        const name = ($('#ps-name')?.value || '').trim();
        if (!name) return toast('Name is required', 'error');
        try {
            await API.post('/pay-schedules', {
                name,
                frequency: $('#ps-freq').value,
                anchor_pay_date: $('#ps-anchor').value,
                submission_lead_days: parseInt($('#ps-lead').value, 10) || 0,
                weekend_shift: $('#ps-shift').value,
            });
            closeModal();
            toast(`Schedule "${name}" created`);
            App.navigate('#/payroll/schedules');
        } catch (e) {
            toast(e.message, 'error');
        }
    },

    async previewUpcoming(scheduleId) {
        const box = $('#ps-upcoming');
        if (!box) return;
        try {
            const data = await API.get(`/pay-schedules/${scheduleId}/upcoming?count=12`);
            let html = `<h3 style="margin-top:18px;">Upcoming: ${escapeHtml(data.schedule.name)}</h3>
                <div class="table-container"><table>
                <thead><tr><th>Pay Date</th><th>Submission Cutoff</th></tr></thead><tbody>`;
            for (const d of data.dates) {
                html += `<tr>
                    <td>${formatDate(d.pay_date)}</td>
                    <td>${formatDate(d.submission_cutoff)}</td>
                </tr>`;
            }
            box.innerHTML = html + '</tbody></table></div>';
        } catch (e) {
            toast(e.message, 'error');
        }
    },

    assignModal(scheduleId) {
        const emps = PaySchedulesPage._employees || [];
        const opts = emps.map(e =>
            `<option value="${e.id}">${escapeHtml(e.first_name)} ${escapeHtml(e.last_name)}</option>`
        ).join('');
        openModal('Assign Employee', `
            <div class="form-group">
                <label>Employee</label>
                <select id="ps-emp">${opts}</select>
            </div>
            <div class="form-actions">
                <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
                <button class="btn btn-primary" onclick="PaySchedulesPage.assign(${scheduleId})">Assign</button>
            </div>`);
    },

    async assign(scheduleId) {
        const empId = $('#ps-emp')?.value;
        if (!empId) return toast('Select an employee', 'error');
        try {
            await API.post(`/pay-schedules/${scheduleId}/assign/${empId}`);
            closeModal();
            toast('Employee assigned');
        } catch (e) {
            toast(e.message, 'error');
        }
    },
};
