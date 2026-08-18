/**
 * HR Team — org chart, team PTO calendar, performance reviews.
 *
 * Three tabs over the /api/hr views. The org chart renders the manager
 * tree as nested lists (cycles flagged by the backend surface with a
 * warning). The PTO calendar is a windowed list, and reviews follow a
 * draft -> submitted -> acknowledged lifecycle.
 */
const HRViewsPage = {
    _tab: 'org',

    async render() {
        const employees = await API.get('/employees?active_only=false');
        HRViewsPage._employees = employees;
        return `
            <div class="page-header">
                <h2>HR Team</h2>
                <div style="font-size:10px; color:var(--text-muted);">
                    Org chart, team time-off calendar, and performance reviews
                </div>
            </div>
            <div class="toolbar">
                <button class="btn" id="hr-tab-org" onclick="HRViewsPage.showTab('org')">Org Chart</button>
                <button class="btn" id="hr-tab-pto" onclick="HRViewsPage.showTab('pto')">PTO Calendar</button>
                <button class="btn" id="hr-tab-reviews" onclick="HRViewsPage.showTab('reviews')">Reviews</button>
            </div>
            <div id="hr-tab-content"></div>`;
    },

    async showTab(tab) {
        HRViewsPage._tab = tab;
        ['org', 'pto', 'reviews'].forEach(t => {
            const btn = $(`#hr-tab-${t}`);
            if (btn) btn.classList.toggle('btn-primary', t === tab);
        });
        const box = $('#hr-tab-content');
        if (!box) return;
        try {
            if (tab === 'org') box.innerHTML = await HRViewsPage.renderOrgChart();
            else if (tab === 'pto') box.innerHTML = HRViewsPage.renderPtoControls();
            else box.innerHTML = await HRViewsPage.renderReviews();
            if (tab === 'pto') await HRViewsPage.loadPtoCalendar();
        } catch (e) {
            toast(e.message, 'error');
        }
    },

    // --- Org chart ----------------------------------------------------------

    async renderOrgChart() {
        const data = await API.get('/hr/org-chart');
        let warning = '';
        if (data.cycle_employee_ids.length) {
            warning = `<div style="color:var(--danger); font-size:11px; margin-bottom:8px;">
                Reporting cycle detected involving employee IDs:
                ${data.cycle_employee_ids.join(', ')}</div>`;
        }
        if (!data.tree.length) {
            return warning + '<div class="empty-state"><p>No employees.</p></div>';
        }
        return warning + `<div style="margin-top:8px;">${data.tree.map(n => HRViewsPage.orgNode(n)).join('')}</div>`;
    },

    orgNode(node) {
        const badge = node.cycle
            ? ' <span class="badge badge-void">cycle</span>'
            : (node.is_active === false ? ' <span class="badge badge-void">inactive</span>' : '');
        const role = node.role ? ` <span style="color:var(--text-muted); font-size:10px;">${escapeHtml(node.role)}</span>` : '';
        const kids = (node.reports || []).map(c => HRViewsPage.orgNode(c)).join('');
        return `<div style="padding:3px 0 3px 0;">
            <strong>${escapeHtml(node.name)}</strong>${role}${badge}
            ${kids ? `<div style="margin-left:22px; border-left:1px solid var(--gray-200); padding-left:10px;">${kids}</div>` : ''}
        </div>`;
    },

    // --- PTO calendar -------------------------------------------------------

    renderPtoControls() {
        const today = new Date();
        const start = new Date(today.getFullYear(), today.getMonth(), 1);
        const end = new Date(today.getFullYear(), today.getMonth() + 1, 0);
        const iso = d => d.toISOString().slice(0, 10);
        return `
            <div class="form-grid" style="max-width:480px; margin-top:8px;">
                <div class="form-group"><label>From</label>
                    <input type="date" id="hr-pto-start" value="${iso(start)}"></div>
                <div class="form-group"><label>To</label>
                    <input type="date" id="hr-pto-end" value="${iso(end)}"></div>
            </div>
            <button class="btn btn-primary" onclick="HRViewsPage.loadPtoCalendar()">Refresh</button>
            <div id="hr-pto-results" style="margin-top:12px;"></div>`;
    },

    async loadPtoCalendar() {
        const box = $('#hr-pto-results');
        if (!box) return;
        const start = $('#hr-pto-start')?.value;
        const end = $('#hr-pto-end')?.value;
        if (!start || !end) return toast('Pick a date range', 'error');
        try {
            const data = await API.get(`/hr/pto-calendar?start=${start}&end=${end}`);
            if (!data.entries.length) {
                box.innerHTML = '<p style="color:var(--text-muted); font-size:11px;">No time off in this window.</p>';
                return;
            }
            let html = `<div class="table-container"><table>
                <thead><tr><th>Employee</th><th>Type</th><th>From</th><th>To</th>
                <th class="amount">Hours</th><th>Status</th></tr></thead><tbody>`;
            for (const e of data.entries) {
                html += `<tr>
                    <td>${escapeHtml(e.employee_name || '')}</td>
                    <td>${escapeHtml(e.pto_type || '')}</td>
                    <td>${formatDate(e.start_date)}</td>
                    <td>${formatDate(e.end_date)}</td>
                    <td class="amount">${e.hours}</td>
                    <td>${e.status === 'approved'
                        ? '<span class="badge badge-paid">approved</span>'
                        : '<span class="badge badge-sent">pending</span>'}</td>
                </tr>`;
            }
            box.innerHTML = html + '</tbody></table></div>';
        } catch (e) {
            toast(e.message, 'error');
        }
    },

    // --- Performance reviews ------------------------------------------------

    async renderReviews() {
        const reviews = await API.get('/hr/reviews');
        let html = `<div style="margin:8px 0;">
            <button class="btn btn-primary" onclick="HRViewsPage.newReviewModal()">New Review</button>
        </div>`;
        if (!reviews.length) {
            return html + '<div class="empty-state"><p>No performance reviews yet.</p></div>';
        }
        html += `<div class="table-container"><table>
            <thead><tr><th>Employee</th><th>Reviewer</th><th>Period</th>
            <th>Rating</th><th>Status</th><th>Actions</th></tr></thead><tbody>`;
        for (const r of reviews) {
            const status = r.status === 'acknowledged'
                ? '<span class="badge badge-paid">acknowledged</span>'
                : (r.status === 'submitted'
                    ? '<span class="badge badge-sent">submitted</span>'
                    : '<span class="badge badge-void">draft</span>');
            let actions = '';
            if (r.status === 'draft') {
                actions = `<button class="btn" onclick="HRViewsPage.editReviewModal(${r.id})">Edit</button>
                    <button class="btn" onclick="HRViewsPage.submitReview(${r.id})">Submit</button>`;
            } else if (r.status === 'submitted') {
                actions = `<button class="btn" onclick="HRViewsPage.acknowledgeModal(${r.id})">Acknowledge</button>`;
            }
            html += `<tr>
                <td>${escapeHtml(r.employee_name || '')}</td>
                <td>${escapeHtml(r.reviewer_name || '')}</td>
                <td>${formatDate(r.period_start)} &ndash; ${formatDate(r.period_end)}</td>
                <td>${r.rating != null ? `${r.rating}/5` : ''}</td>
                <td>${status}</td>
                <td>${actions}</td>
            </tr>`;
        }
        return html + '</tbody></table></div>';
    },

    _employeeOptions(selected) {
        return (HRViewsPage._employees || []).map(e =>
            `<option value="${e.id}" ${e.id === selected ? 'selected' : ''}>${escapeHtml(e.first_name)} ${escapeHtml(e.last_name)}</option>`
        ).join('');
    },

    newReviewModal() {
        openModal('New Performance Review', `
            <div class="form-group">
                <label>Employee</label>
                <select id="rev-emp">${HRViewsPage._employeeOptions()}</select>
            </div>
            <div class="form-group">
                <label>Reviewer</label>
                <select id="rev-reviewer"><option value="">(none)</option>${HRViewsPage._employeeOptions()}</select>
            </div>
            <div class="form-group">
                <label>Period start</label>
                <input type="date" id="rev-start">
            </div>
            <div class="form-group">
                <label>Period end</label>
                <input type="date" id="rev-end">
            </div>
            <div class="form-group">
                <label>Rating (1-5, optional)</label>
                <input type="number" id="rev-rating" min="1" max="5">
            </div>
            <div class="form-group">
                <label>Goals</label>
                <textarea id="rev-goals"></textarea>
            </div>
            <div class="form-group">
                <label>Feedback</label>
                <textarea id="rev-feedback"></textarea>
            </div>
            <div class="form-actions">
                <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
                <button class="btn btn-primary" onclick="HRViewsPage.createReview()">Create</button>
            </div>`);
    },

    async createReview() {
        const start = $('#rev-start')?.value;
        const end = $('#rev-end')?.value;
        if (!start || !end) return toast('Period dates are required', 'error');
        const rating = $('#rev-rating').value;
        try {
            await API.post('/hr/reviews', {
                employee_id: parseInt($('#rev-emp').value, 10),
                reviewer_id: $('#rev-reviewer').value ? parseInt($('#rev-reviewer').value, 10) : null,
                period_start: start,
                period_end: end,
                rating: rating ? parseInt(rating, 10) : null,
                goals: $('#rev-goals').value || null,
                feedback: $('#rev-feedback').value || null,
            });
            closeModal();
            toast('Review created');
            HRViewsPage.showTab('reviews');
        } catch (e) {
            toast(e.message, 'error');
        }
    },

    async editReviewModal(reviewId) {
        try {
            const reviews = await API.get('/hr/reviews');
            const r = reviews.find(x => x.id === reviewId);
            if (!r) return toast('Review not found', 'error');
            openModal('Edit Review (draft)', `
                <div class="form-group">
                    <label>Rating (1-5)</label>
                    <input type="number" id="rev-rating" min="1" max="5" value="${r.rating != null ? r.rating : ''}">
                </div>
                <div class="form-group">
                    <label>Goals</label>
                    <textarea id="rev-goals">${escapeHtml(r.goals || '')}</textarea>
                </div>
                <div class="form-group">
                    <label>Feedback</label>
                    <textarea id="rev-feedback">${escapeHtml(r.feedback || '')}</textarea>
                </div>
                <div class="form-actions">
                    <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
                    <button class="btn btn-primary" onclick="HRViewsPage.updateReview(${reviewId})">Save</button>
                </div>`);
        } catch (e) {
            toast(e.message, 'error');
        }
    },

    async updateReview(reviewId) {
        const rating = $('#rev-rating').value;
        try {
            await API.put(`/hr/reviews/${reviewId}`, {
                rating: rating ? parseInt(rating, 10) : null,
                goals: $('#rev-goals').value || null,
                feedback: $('#rev-feedback').value || null,
            });
            closeModal();
            toast('Review updated');
            HRViewsPage.showTab('reviews');
        } catch (e) {
            toast(e.message, 'error');
        }
    },

    async submitReview(reviewId) {
        try {
            await API.post(`/hr/reviews/${reviewId}/submit`);
            toast('Review submitted');
            HRViewsPage.showTab('reviews');
        } catch (e) {
            toast(e.message, 'error');
        }
    },

    acknowledgeModal(reviewId) {
        openModal('Acknowledge Review', `
            <div class="form-group">
                <label>Employee comment (optional)</label>
                <textarea id="rev-comment"></textarea>
            </div>
            <div class="form-actions">
                <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
                <button class="btn btn-primary" onclick="HRViewsPage.acknowledge(${reviewId})">Acknowledge</button>
            </div>`);
    },

    async acknowledge(reviewId) {
        try {
            await API.post(`/hr/reviews/${reviewId}/acknowledge`, {
                employee_comment: $('#rev-comment').value || null,
            });
            closeModal();
            toast('Review acknowledged');
            HRViewsPage.showTab('reviews');
        } catch (e) {
            toast(e.message, 'error');
        }
    },
};
