/**
 * Benefits — plans, enrollments, dependents, COBRA notices, and the ACA
 * 1095/1094 derivation that reads all of it.
 *
 * The records half of benefits administration. Carrier enrollment feeds
 * (EDI 834) are external integrations and deliberately out of scope, so
 * nothing here talks to a carrier — this is the book of record the ACA
 * forms and COBRA notices generate from.
 *
 * ePHI NOTE. Carrier name, every dependent identifier, the plan kind and the
 * coverage window are Fernet-encrypted at rest; the server decrypts them for
 * these responses. That means this page renders ePHI, and its network
 * responses carry it — which is why the app refuses to serve over plain HTTP
 * in production. See docs/hipaa-compliance.md.
 */
const BenefitsPage = {
    _enrollEmpId: '',
    _acaYear: new Date().getFullYear(),

    async render() {
        const [plans, employees] = await Promise.all([
            API.get('/benefits/plans'),
            API.get('/employees?active_only=false'),
        ]);
        BenefitsPage._plans = plans;
        BenefitsPage._employees = employees;

        setTimeout(() => {
            BenefitsPage.loadEnrollments();
            BenefitsPage.loadAca();
        }, 0);

        return `
            <div class="page-header">
                <h2>Benefits</h2>
                <div style="font-size:10px; color:var(--text-muted);">
                    Plans, enrollment, dependents, COBRA, and ACA coverage reporting
                </div>
            </div>

            <h3>Plans</h3>
            <div class="toolbar">
                <button class="btn btn-primary" onclick="BenefitsPage.newPlanModal()">New Plan</button>
            </div>
            ${BenefitsPage.plansTable(plans)}

            <h3 style="margin-top:18px;">Enrollments</h3>
            <div class="toolbar">
                <select id="enroll-emp" onchange="BenefitsPage.loadEnrollments()">
                    <option value="">All employees</option>
                    ${BenefitsPage.employeeOptions()}
                </select>
                <button class="btn btn-primary" onclick="BenefitsPage.enrollModal()"
                        ${plans.length ? '' : 'disabled title="Create a plan first"'}>
                    Enroll Employee
                </button>
            </div>
            <div id="enrollment-results"></div>

            <h3 style="margin-top:18px;">ACA Coverage (1095 / 1094)</h3>
            <div class="toolbar">
                <label style="font-size:10px;font-weight:700;color:var(--text-secondary);">Year:</label>
                <input type="number" id="aca-year" value="${BenefitsPage._acaYear}"
                       style="width:90px;" onchange="BenefitsPage.loadAca()">
            </div>
            <div id="aca-results"></div>`;
    },

    employeeOptions(selected) {
        return (BenefitsPage._employees || []).map(e =>
            `<option value="${e.id}" ${String(e.id) === String(selected) ? 'selected' : ''}>${
                escapeHtml(e.first_name)} ${escapeHtml(e.last_name)}</option>`
        ).join('');
    },

    // --- plans ------------------------------------------------------------

    plansTable(plans) {
        if (!plans.length) {
            return `<div class="empty-state"><p>No plans yet. A plan is what
                    enrollments and ACA coverage months hang off.</p></div>`;
        }
        let html = `<div class="table-container"><table>
            <thead><tr>
                <th>Plan</th><th>Kind</th><th>Carrier</th><th>MEC</th><th>Funding</th>
                <th class="amount">EE / mo</th><th class="amount">ER / mo</th><th>Status</th>
            </tr></thead><tbody>`;
        for (const p of plans) {
            html += `<tr>
                <td>${escapeHtml(p.name)}</td>
                <td>${escapeHtml(p.kind || '')}</td>
                <td>${escapeHtml(p.carrier_name || '')}</td>
                <td>${p.provides_mec
                    ? '<span class="badge badge-paid">MEC</span>'
                    : '<span class="badge badge-void">no MEC</span>'}</td>
                <td>${p.self_insured ? 'Self-insured' : 'Fully insured'}</td>
                <td class="amount">${formatCurrency(p.monthly_premium_employee)}</td>
                <td class="amount">${formatCurrency(p.monthly_premium_employer)}</td>
                <td>${p.is_active
                    ? '<span class="badge badge-paid">active</span>'
                    : '<span class="badge badge-void">inactive</span>'}</td>
            </tr>`;
        }
        return html + '</tbody></table></div>';
    },

    newPlanModal() {
        openModal('New Benefit Plan', `
            <div class="form-group">
                <label>Plan name</label>
                <input type="text" id="p-name" placeholder="Gold PPO">
            </div>
            <div class="form-group">
                <label>Kind</label>
                <select id="p-kind">
                    ${['medical','dental','vision','life','disability','other']
                        .map(k => `<option value="${k}">${k}</option>`).join('')}
                </select>
            </div>
            <div class="form-group">
                <label>Carrier</label>
                <input type="text" id="p-carrier" placeholder="Blue Shield">
            </div>
            <div class="form-group">
                <label><input type="checkbox" id="p-mec" checked>
                    Provides minimum essential coverage (drives ACA months)</label>
            </div>
            <div class="form-group">
                <label><input type="checkbox" id="p-self">
                    Self-insured (employer files covered individuals on 1095 Part III)</label>
            </div>
            <div class="form-group">
                <label>Employee premium / month</label>
                <input type="number" step="0.01" id="p-ee" value="0">
            </div>
            <div class="form-group">
                <label>Employer premium / month</label>
                <input type="number" step="0.01" id="p-er" value="0">
            </div>
            <div class="form-actions">
                <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
                <button class="btn btn-primary" onclick="BenefitsPage.createPlan()">Create</button>
            </div>`);
    },

    async createPlan() {
        const name = $('#p-name').value.trim();
        if (!name) return toast('Plan name is required', 'error');
        try {
            await API.post('/benefits/plans', {
                name,
                kind: $('#p-kind').value,
                carrier_name: $('#p-carrier').value.trim() || null,
                provides_mec: $('#p-mec').checked,
                self_insured: $('#p-self').checked,
                monthly_premium_employee: parseFloat($('#p-ee').value) || 0,
                monthly_premium_employer: parseFloat($('#p-er').value) || 0,
            });
            closeModal();
            toast(`Plan "${name}" created`);
            App.navigate('#/hr/benefits');
        } catch (e) {
            toast(e.message, 'error');
        }
    },

    /** active / terminated / cobra — COBRA is its own state, not a failure. */
    statusBadge(status) {
        const cls = { active: 'badge-paid', cobra: 'badge-sent' }[status] || 'badge-void';
        return `<span class="badge ${cls}">${escapeHtml(status || '')}</span>`;
    },

    // --- enrollments ------------------------------------------------------

    async loadEnrollments() {
        const box = $('#enrollment-results');
        if (!box) return;
        const empId = $('#enroll-emp')?.value || '';
        BenefitsPage._enrollEmpId = empId;
        // Built in two steps rather than a nested template literal:
        // tests/test_wiring.py parses these paths with a single-pass regex and
        // documents that the codebase does not nest `${ `${}` }`.
        let url = '/benefits/enrollments';
        if (empId) url += `?employee_id=${empId}`;
        const rows = await API.get(url);

        if (!rows.length) {
            box.innerHTML = '<div class="empty-state"><p>No enrollments.</p></div>';
            return;
        }
        let html = `<div class="table-container"><table>
            <thead><tr>
                <th>Employee</th><th>Plan</th><th>Kind</th><th>Coverage</th>
                <th>Status</th><th>Dependents</th><th>Actions</th>
            </tr></thead><tbody>`;
        for (const e of rows) {
            const open = !e.coverage_end;
            const deps = e.dependents.length
                ? e.dependents.map(d =>
                    `${escapeHtml(d.name)}${d.relationship_kind
                        ? ` <span style="color:var(--text-muted);">(${escapeHtml(d.relationship_kind)})</span>`
                        : ''}`).join('<br>')
                : '<span style="color:var(--text-muted);">—</span>';

            // COBRA is a medical-plan rule and needs a qualifying event, which
            // here is the coverage end date. Offering the button before then
            // would just produce a 400 the operator has to read to understand.
            const cobra = (!open && e.plan_kind === 'medical')
                ? `<button class="btn" onclick="BenefitsPage.cobraNotice(${e.id})">COBRA Notice</button>`
                : '';

            html += `<tr>
                <td>${escapeHtml(e.employee_name || '')}</td>
                <td>${escapeHtml(e.plan_name || '')}</td>
                <td>${escapeHtml(e.plan_kind || '')}</td>
                <td>${formatDate(e.coverage_start)} &rarr; ${
                    e.coverage_end ? formatDate(e.coverage_end)
                                   : '<span style="color:var(--text-muted);">ongoing</span>'}</td>
                <td>${BenefitsPage.statusBadge(e.status)}</td>
                <td style="font-size:11px;">${deps}</td>
                <td>
                    <button class="btn" onclick="BenefitsPage.dependentModal(${e.id})">Add Dependent</button>
                    ${open ? `<button class="btn" onclick="BenefitsPage.endModal(${e.id}, '${e.coverage_start}')">End</button>` : ''}
                    ${cobra}
                </td>
            </tr>`;
        }
        box.innerHTML = html + '</tbody></table></div>';
    },

    enrollModal() {
        const planOpts = (BenefitsPage._plans || [])
            .filter(p => p.is_active)
            .map(p => `<option value="${p.id}">${escapeHtml(p.name)} (${escapeHtml(p.kind || '')})</option>`)
            .join('');
        openModal('Enroll Employee', `
            <div class="form-group">
                <label>Employee</label>
                <select id="e-emp">${BenefitsPage.employeeOptions(BenefitsPage._enrollEmpId)}</select>
            </div>
            <div class="form-group">
                <label>Plan</label>
                <select id="e-plan">${planOpts}</select>
            </div>
            <div class="form-group">
                <label>Coverage start</label>
                <input type="date" id="e-start" value="${todayISO()}">
            </div>
            <div class="form-actions">
                <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
                <button class="btn btn-primary" onclick="BenefitsPage.enroll()">Enroll</button>
            </div>`);
    },

    async enroll() {
        try {
            await API.post('/benefits/enrollments', {
                employee_id: parseInt($('#e-emp').value, 10),
                plan_id: parseInt($('#e-plan').value, 10),
                coverage_start: $('#e-start').value,
            });
            closeModal();
            toast('Enrolled');
            BenefitsPage.loadEnrollments();
            BenefitsPage.loadAca();
        } catch (e) {
            // 400 covers "already has an open enrollment" — the duplicate
            // guard the encrypted coverage_end column still supports.
            toast(e.message, 'error');
        }
    },

    dependentModal(enrollmentId) {
        openModal('Add Dependent', `
            <p style="font-size:10px;color:var(--text-muted);">
                Name, SSN last-4 and date of birth are encrypted at rest — a
                dependent is a family member who never consented to this system
                directly. Relationship stays plaintext; it is a category, not an
                identifier, and the 1095 covered-individuals listing groups on it.
            </p>
            <div class="form-group"><label>Name</label>
                <input type="text" id="d-name"></div>
            <div class="form-group"><label>Relationship</label>
                <select id="d-rel">
                    <option value="">—</option>
                    <option value="spouse">spouse</option>
                    <option value="child">child</option>
                    <option value="other">other</option>
                </select></div>
            <div class="form-group"><label>SSN last 4</label>
                <input type="text" id="d-ssn" maxlength="4" style="width:80px;"></div>
            <div class="form-group"><label>Date of birth</label>
                <input type="date" id="d-dob"></div>
            <div class="form-actions">
                <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
                <button class="btn btn-primary" onclick="BenefitsPage.addDependent(${enrollmentId})">Add</button>
            </div>`);
    },

    async addDependent(enrollmentId) {
        const name = $('#d-name').value.trim();
        if (!name) return toast('Dependent name is required', 'error');
        try {
            await API.post(`/benefits/enrollments/${enrollmentId}/dependents`, {
                name,
                relationship_kind: $('#d-rel').value || null,
                ssn_last_four: $('#d-ssn').value.trim() || null,
                dob: $('#d-dob').value || null,
            });
            closeModal();
            toast('Dependent added');
            BenefitsPage.loadEnrollments();
            BenefitsPage.loadAca();
        } catch (e) {
            toast(e.message, 'error');
        }
    },

    endModal(enrollmentId, coverageStart) {
        openModal('End Coverage', `
            <p style="font-size:10px;color:var(--text-muted);">
                The end date is the COBRA qualifying event. Coverage counts for
                ACA purposes through any day of the month it falls in.
            </p>
            <div class="form-group">
                <label>Coverage end</label>
                <input type="date" id="x-end" value="${todayISO()}" min="${coverageStart}">
            </div>
            <div class="form-actions">
                <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
                <button class="btn btn-primary" onclick="BenefitsPage.endCoverage(${enrollmentId})">End Coverage</button>
            </div>`);
    },

    async endCoverage(enrollmentId) {
        try {
            await API.post(`/benefits/enrollments/${enrollmentId}/end`, {
                coverage_end: $('#x-end').value,
            });
            closeModal();
            toast('Coverage ended');
            BenefitsPage.loadEnrollments();
            BenefitsPage.loadAca();
        } catch (e) {
            toast(e.message, 'error');
        }
    },

    async cobraNotice(enrollmentId) {
        // Page-scoped rather than the shared _openPDF() global, which
        // tax_forms.js already owns — two definitions of the same name across
        // script tags is a collision waiting to happen.
        const res = await fetch(`/api/benefits/enrollments/${enrollmentId}/cobra-notice`,
                                { method: 'POST', credentials: 'same-origin' });
        if (!res.ok) {
            let msg = 'COBRA notice generation failed';
            try { msg = (await res.json()).detail || msg; } catch (_) {}
            return toast(msg, 'error');
        }
        const url = URL.createObjectURL(await res.blob());
        window.open(url, '_blank');
        setTimeout(() => URL.revokeObjectURL(url), 15000);
    },

    // --- ACA --------------------------------------------------------------

    async loadAca() {
        const box = $('#aca-results');
        if (!box) return;
        const year = parseInt($('#aca-year')?.value, 10) || BenefitsPage._acaYear;
        BenefitsPage._acaYear = year;
        const data = await API.get(`/tax-forms/1095?year=${year}`);

        const MONTHS = ['Jan','Feb','Mar','Apr','May','Jun',
                        'Jul','Aug','Sep','Oct','Nov','Dec'];

        if (!data.form_count) {
            box.innerHTML = `<div class="empty-state"><p>No MEC-providing medical
                coverage in ${year}. Only medical plans flagged as providing minimum
                essential coverage produce 1095 forms.</p></div>`;
            return;
        }

        let html = `<div class="table-container"><table>
            <thead><tr>
                <th>Employee</th><th>SSN</th>
                ${MONTHS.map(m => `<th style="text-align:center;">${m}</th>`).join('')}
                <th>All 12</th><th>Plans</th><th>Part III</th>
            </tr></thead><tbody>`;
        for (const f of data.forms) {
            const covered = new Set(f.months_covered);
            html += `<tr>
                <td>${escapeHtml(f.name || '')}</td>
                <td>${f.ssn_last_four ? '***-**-' + escapeHtml(f.ssn_last_four) : ''}</td>
                ${MONTHS.map((_, i) => `<td style="text-align:center;">${
                    covered.has(i + 1) ? '&#10003;' : '&middot;'}</td>`).join('')}
                <td>${f.all_12_months ? '<span class="badge badge-paid">yes</span>' : ''}</td>
                <td style="font-size:11px;">${f.plans.map(escapeHtml).join(', ')}</td>
                <td style="font-size:11px;">${f.self_insured
                    ? f.covered_individuals.map(c =>
                        `${escapeHtml(c.name)} <span style="color:var(--text-muted);">(${
                            escapeHtml(c.relationship || '')})</span>`).join('<br>')
                    : '<span style="color:var(--text-muted);">carrier files 1095-B</span>'}</td>
            </tr>`;
        }
        // 1094 transmittal row — the per-month covered-employee counts.
        html += `<tr style="font-weight:700;border-top:2px solid var(--border,#999);">
            <td colspan="2">1094 monthly counts</td>
            ${MONTHS.map((_, i) => `<td style="text-align:center;">${
                data.monthly_covered_employee_counts[i + 1] ?? 0}</td>`).join('')}
            <td colspan="3">${data.form_count} form(s)</td>
        </tr>`;

        box.innerHTML = html + `</tbody></table></div>
            <div style="font-size:10px;color:var(--text-muted);margin-top:6px;">
                ${escapeHtml(data.note || '')}
            </div>`;
    },
};
