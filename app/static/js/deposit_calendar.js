/**
 * Tax Deposit Calendar — depositor classification + the year's liability
 * calendar (941 deposits, FUTA, quarterly/annual returns, state amounts).
 */
const DepositCalendarPage = {
    async render() {
        const year = new Date().getFullYear();
        return `
            <div class="page-header">
                <h2>Tax Deposit Calendar</h2>
                <div style="font-size:10px; color:var(--text-muted);">
                    IRS depositor classification and every payroll tax due date for the year
                </div>
            </div>
            <div class="toolbar">
                <label style="font-size:11px;">Year
                    <input type="number" id="dc-year" value="${year}" min="2000" max="2100"
                        style="width:80px; margin-left:6px;">
                </label>
                <button class="btn btn-primary" onclick="DepositCalendarPage.load()">Load</button>
            </div>
            <div id="dc-schedule"></div>
            <div id="dc-calendar"></div>`;
    },

    async load() {
        const year = parseInt($('#dc-year')?.value, 10);
        if (!year) return toast('Enter a year', 'error');
        try {
            const [sched, cal] = await Promise.all([
                API.get(`/tax-forms/deposit-schedule?year=${year}`),
                API.get(`/tax-forms/liability-calendar?year=${year}`),
            ]);
            DepositCalendarPage.renderSchedule(sched);
            DepositCalendarPage.renderCalendar(cal);
        } catch (e) {
            toast(e.message, 'error');
        }
    },

    renderSchedule(s) {
        const box = $('#dc-schedule');
        if (!box) return;
        let quarters = s.lookback_quarters.map(q =>
            `<tr><td>${q.year} Q${q.quarter}</td>
                 <td class="amount">${formatCurrency(q.form_941_tax)}</td></tr>`
        ).join('');
        box.innerHTML = `
            <h3 style="margin-top:14px;">Depositor Classification — ${s.year}</h3>
            <div class="card-grid" style="margin:8px 0;">
                <div class="card">
                    <div class="card-header">Schedule</div>
                    <div class="card-value">${escapeHtml(s.schedule)}</div>
                </div>
                <div class="card">
                    <div class="card-header">Lookback Total</div>
                    <div class="card-value">${formatCurrency(s.lookback_total)}</div>
                </div>
                <div class="card">
                    <div class="card-header">Threshold</div>
                    <div class="card-value">${formatCurrency(s.threshold)}</div>
                </div>
            </div>
            <div class="table-container"><table>
                <thead><tr><th scope="col">Lookback Quarter</th><th scope="col" class="amount">941 Tax</th></tr></thead>
                <tbody>${quarters}</tbody>
            </table></div>
            <p style="font-size:10px; color:var(--text-muted); margin-top:6px;">
                Lookback window ${formatDate(s.lookback_start)} &ndash; ${formatDate(s.lookback_end)}.
                ${escapeHtml(s.note || '')}</p>`;
    },

    renderCalendar(c) {
        const box = $('#dc-calendar');
        if (!box) return;
        let warnings = '';
        if (c.warnings && c.warnings.length) {
            warnings = `<div style="color:var(--danger); font-size:11px; margin:6px 0;">
                ${c.warnings.map(w => escapeHtml(w)).join('<br>')}</div>`;
        }
        if (!c.entries.length) {
            box.innerHTML = warnings + '<div class="empty-state"><p>No liabilities for this year.</p></div>';
            return;
        }
        let rows = c.entries.map(e => `<tr>
            <td>${formatDate(e.due_date)}</td>
            <td>${escapeHtml(e.period)}</td>
            <td>${escapeHtml(e.description)}</td>
            <td class="amount">${e.amount != null ? formatCurrency(e.amount) : ''}</td>
            <td><span class="badge badge-sent">${escapeHtml(e.rule)}</span></td>
        </tr>`).join('');
        box.innerHTML = `
            <h3 style="margin-top:18px;">Liability Calendar — ${c.year}</h3>
            ${warnings}
            <div class="table-container"><table>
                <thead><tr><th scope="col">Due Date</th><th scope="col">Period</th><th scope="col">Description</th>
                <th scope="col" class="amount">Amount</th><th scope="col">Rule</th></tr></thead>
                <tbody>${rows}</tbody>
            </table></div>`;
    },
};
