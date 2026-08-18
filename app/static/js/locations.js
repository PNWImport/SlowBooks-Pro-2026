/**
 * Work Locations — CRUD, employee assignment, roster view.
 *
 * A work location pins an address + tax jurisdiction (state, locality,
 * default WC class code). Employees assigned to a location inherit the
 * jurisdiction as a fallback — explicit per-employee values still win.
 */
const LocationsPage = {
    async render() {
        const [locations, employees] = await Promise.all([
            API.get('/locations'),
            API.get('/employees?active_only=false'),
        ]);
        LocationsPage._employees = employees;

        return `
            <div class="page-header">
                <h2>Work Locations</h2>
                <div style="font-size:10px; color:var(--text-muted);">
                    Manage office sites, tax jurisdictions, and employee assignments
                </div>
            </div>

            <div class="toolbar">
                <button class="btn btn-primary" onclick="LocationsPage.newModal()">New Location</button>
            </div>

            ${LocationsPage.locationsTable(locations)}
            <div id="loc-roster"></div>`;
    },

    locationsTable(locations) {
        if (!locations.length) {
            return '<div class="empty-state"><p>No work locations yet.</p></div>';
        }
        let html = `<div class="table-container"><table>
            <thead><tr>
                <th>Name</th><th>State</th><th>City</th>
                <th>Locality</th><th>WC Class</th><th>Status</th><th>Actions</th>
            </tr></thead><tbody>`;
        for (const loc of locations) {
            html += `<tr>
                <td>${escapeHtml(loc.name)}</td>
                <td>${escapeHtml(loc.state || '')}</td>
                <td>${escapeHtml(loc.city || '')}</td>
                <td>${escapeHtml(loc.locality || '')}</td>
                <td>${escapeHtml(loc.default_wc_class_code || '')}</td>
                <td>${loc.is_active
                    ? '<span class="badge badge-paid">active</span>'
                    : '<span class="badge badge-void">inactive</span>'}</td>
                <td>
                    <button class="btn" onclick="LocationsPage.editModal(${loc.id})">Edit</button>
                    <button class="btn" onclick="LocationsPage.rosterView(${loc.id})">Roster</button>
                    <button class="btn" onclick="LocationsPage.assignModal(${loc.id})">Assign</button>
                </td>
            </tr>`;
        }
        return html + '</tbody></table></div>';
    },

    newModal() {
        openModal('New Work Location', `
            <div class="form-group">
                <label>Name</label>
                <input type="text" id="loc-name" placeholder="Main Office">
            </div>
            <div class="form-group">
                <label>State (2-letter code)</label>
                <input type="text" id="loc-state" maxlength="2" placeholder="WA">
            </div>
            <div class="form-group">
                <label>City</label>
                <input type="text" id="loc-city">
            </div>
            <div class="form-group">
                <label>Address Line 1</label>
                <input type="text" id="loc-addr1">
            </div>
            <div class="form-group">
                <label>Address Line 2</label>
                <input type="text" id="loc-addr2">
            </div>
            <div class="form-group">
                <label>ZIP</label>
                <input type="text" id="loc-zip">
            </div>
            <div class="form-group">
                <label>Locality code</label>
                <input type="text" id="loc-locality" placeholder="PA-PHILADELPHIA">
            </div>
            <div class="form-group">
                <label>Default WC class code</label>
                <input type="text" id="loc-wc">
            </div>
            <div class="form-actions">
                <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
                <button class="btn btn-primary" onclick="LocationsPage.create()">Create</button>
            </div>`);
    },

    async create() {
        const name = ($('#loc-name')?.value || '').trim();
        const state = ($('#loc-state')?.value || '').trim().toUpperCase();
        if (!name) return toast('Name is required', 'error');
        if (!state) return toast('State is required', 'error');
        try {
            await API.post('/locations', {
                name,
                state,
                city: $('#loc-city').value || null,
                address1: $('#loc-addr1').value || null,
                address2: $('#loc-addr2').value || null,
                zip: $('#loc-zip').value || null,
                locality: $('#loc-locality').value || null,
                default_wc_class_code: $('#loc-wc').value || null,
            });
            closeModal();
            toast(`Location "${name}" created`);
            App.navigate('#/payroll/locations');
        } catch (e) {
            toast(e.message, 'error');
        }
    },

    async editModal(locationId) {
        try {
            const locations = await API.get('/locations');
            const loc = locations.find(l => l.id === locationId);
            if (!loc) return toast('Location not found', 'error');

            openModal('Edit Location', `
                <div class="form-group">
                    <label>Name</label>
                    <input type="text" id="loc-name" value="${escapeHtml(loc.name)}">
                </div>
                <div class="form-group">
                    <label>State (2-letter code)</label>
                    <input type="text" id="loc-state" maxlength="2" value="${escapeHtml(loc.state || '')}">
                </div>
                <div class="form-group">
                    <label>City</label>
                    <input type="text" id="loc-city" value="${escapeHtml(loc.city || '')}">
                </div>
                <div class="form-group">
                    <label>Address Line 1</label>
                    <input type="text" id="loc-addr1" value="${escapeHtml(loc.address1 || '')}">
                </div>
                <div class="form-group">
                    <label>Address Line 2</label>
                    <input type="text" id="loc-addr2" value="${escapeHtml(loc.address2 || '')}">
                </div>
                <div class="form-group">
                    <label>ZIP</label>
                    <input type="text" id="loc-zip" value="${escapeHtml(loc.zip || '')}">
                </div>
                <div class="form-group">
                    <label>Locality code</label>
                    <input type="text" id="loc-locality" value="${escapeHtml(loc.locality || '')}">
                </div>
                <div class="form-group">
                    <label>Default WC class code</label>
                    <input type="text" id="loc-wc" value="${escapeHtml(loc.default_wc_class_code || '')}">
                </div>
                <div class="form-group">
                    <label>Active</label>
                    <select id="loc-active">
                        <option value="true" ${loc.is_active ? 'selected' : ''}>Yes</option>
                        <option value="false" ${!loc.is_active ? 'selected' : ''}>No</option>
                    </select>
                </div>
                <div class="form-actions">
                    <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
                    <button class="btn btn-primary" onclick="LocationsPage.update(${locationId})">Save</button>
                </div>`);
        } catch (e) {
            toast(e.message, 'error');
        }
    },

    async update(locationId) {
        try {
            await API.put(`/locations/${locationId}`, {
                name: $('#loc-name').value.trim() || undefined,
                state: ($('#loc-state').value || '').trim().toUpperCase() || undefined,
                city: $('#loc-city').value || null,
                address1: $('#loc-addr1').value || null,
                address2: $('#loc-addr2').value || null,
                zip: $('#loc-zip').value || null,
                locality: $('#loc-locality').value || null,
                default_wc_class_code: $('#loc-wc').value || null,
                is_active: $('#loc-active').value === 'true',
            });
            closeModal();
            toast('Location updated');
            App.navigate('#/payroll/locations');
        } catch (e) {
            toast(e.message, 'error');
        }
    },

    async rosterView(locationId) {
        const box = $('#loc-roster');
        if (!box) return;
        try {
            const employees = await API.get(`/locations/${locationId}/employees`);
            const locations = await API.get('/locations');
            const loc = locations.find(l => l.id === locationId);
            const locName = loc ? loc.name : `#${locationId}`;
            let html = `<h3 style="margin-top:18px;">Roster: ${escapeHtml(locName)}</h3>`;
            if (!employees.length) {
                html += '<p style="color:var(--text-muted); font-size:11px;">No employees assigned.</p>';
            } else {
                html += `<div class="table-container"><table>
                    <thead><tr><th>Name</th><th>Status</th></tr></thead><tbody>`;
                for (const e of employees) {
                    html += `<tr>
                        <td>${escapeHtml(e.name)}</td>
                        <td>${e.is_active
                            ? '<span class="badge badge-paid">active</span>'
                            : '<span class="badge badge-void">inactive</span>'}</td>
                    </tr>`;
                }
                html += '</tbody></table></div>';
            }
            box.innerHTML = html;
        } catch (e) {
            toast(e.message, 'error');
        }
    },

    assignModal(locationId) {
        const emps = LocationsPage._employees || [];
        const opts = emps.map(e =>
            `<option value="${e.id}">${escapeHtml(e.first_name)} ${escapeHtml(e.last_name)}</option>`
        ).join('');
        openModal('Assign Employee', `
            <div class="form-group">
                <label>Employee</label>
                <select id="loc-emp">${opts}</select>
            </div>
            <div class="form-actions">
                <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
                <button class="btn btn-primary" onclick="LocationsPage.assign(${locationId})">Assign</button>
            </div>`);
    },

    async assign(locationId) {
        const empId = $('#loc-emp')?.value;
        if (!empId) return toast('Select an employee', 'error');
        try {
            await API.post(`/locations/${locationId}/assign/${empId}`);
            closeModal();
            toast('Employee assigned');
        } catch (e) {
            toast(e.message, 'error');
        }
    },
};
