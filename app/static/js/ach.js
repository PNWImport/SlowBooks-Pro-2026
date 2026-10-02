/**
 * ACH file dialog — shared by payroll and contractor runs.
 * The company's bank details are saved encrypted and shown masked; seeing
 * them in full takes the bank-details permission plus your password.
 */
const AchFile = {
    FIELDS: [
        ['immediate_destination', "Immediate Destination (your bank's routing)", 9],
        ['immediate_origin', 'Immediate Origin (company ID from your bank, often EIN)', 10],
        ['originating_dfi_id', "Originating DFI ID (first 8 digits of your bank's routing)", 8],
        ['company_account', 'Company account number (funds the deposits)', 17],
    ],
    _url: null,
    _fallbackName: null,
    _saved: null,

    async open(url, fallbackName) {
        AchFile._url = url;
        AchFile._fallbackName = fallbackName;
        let s;
        try { s = await API.get('/payroll/ach-settings'); }
        catch (e) { return toast(e.message, 'error'); }
        if (!s.can_access) {
            return openModal('Direct Deposit — ACH File', `
                <p style="font-size:11px; color:var(--text-muted); margin-bottom:12px;">
                    Your account doesn't have access to bank details. An admin
                    can grant it under Settings &rarr; Users.
                </p>
                <div class="form-actions">
                    <button class="btn btn-secondary" onclick="closeModal()">Close</button>
                </div>`);
        }
        AchFile._saved = s.values;
        AchFile._render(s.configured ? 'view' : 'setup');
    },

    // view: saved details, masked, read-only. setup: first save.
    // edit: change saved details; a blank field keeps its saved value.
    _render(mode) {
        const editable = mode !== 'view';
        const fields = AchFile.FIELDS.map(([key, label, max]) => {
            const saved = AchFile._saved[key] || '';
            const value = mode === 'view' ? saved : '';
            const placeholder = mode === 'edit' && saved ? `Leave blank to keep ${saved}` : '';
            return `<div class="form-group">
                <label for="ach-${key}">${escapeHtml(label)}</label>
                <input type="text" id="ach-${key}" maxlength="${max}" autocomplete="off"
                    value="${escapeHtml(value)}" placeholder="${escapeHtml(placeholder)}"
                    ${editable ? '' : 'readonly'}>
            </div>`;
        }).join('');
        const intro = mode === 'view'
            ? 'Your bank\'s ACH details are saved. The file credits each payee\'s active bank account(s) on file; upload it to your bank\'s ACH portal to send the deposits.'
            : 'Origination details come from your bank\'s ACH agreement. They are saved encrypted for future runs and shown masked.';
        const actions = mode === 'view'
            ? `<button class="btn btn-secondary" id="ach-show-btn" onclick="AchFile._askPassword()">Show numbers</button>
               <button class="btn btn-secondary" onclick="AchFile._render('edit')">Change details</button>
               <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
               <button class="btn btn-primary" onclick="AchFile.download()">Download</button>`
            : `<button class="btn btn-secondary" onclick="${mode === 'edit' ? "AchFile._render('view')" : 'closeModal()'}">Cancel</button>
               <button class="btn btn-primary" onclick="AchFile.save(${mode === 'setup'})">${mode === 'setup' ? 'Save &amp; Download' : 'Save'}</button>`;
        openModal('Direct Deposit — ACH File', `
            <p style="font-size:11px; color:var(--text-muted); margin-bottom:12px;">${intro}</p>
            ${fields}
            <div id="ach-reveal"></div>
            <div class="form-actions">${actions}</div>`);
    },

    _askPassword() {
        $('#ach-reveal').innerHTML = `
            <div class="form-group">
                <label for="ach-password">Enter your password to show the full numbers</label>
                <input type="password" id="ach-password" autocomplete="current-password"
                    onkeydown="if (event.key === 'Enter') AchFile.reveal()">
            </div>
            <div style="margin-bottom:12px;">
                <button class="btn btn-sm btn-primary" onclick="AchFile.reveal()">Show</button>
            </div>`;
        $('#ach-show-btn').disabled = true;
        $('#ach-password').focus();
    },

    async reveal() {
        const password = $('#ach-password')?.value || '';
        if (!password) return toast('Enter your password', 'error');
        try {
            const res = await API.post('/payroll/ach-settings/reveal', { password });
            for (const [key] of AchFile.FIELDS) $(`#ach-${key}`).value = res.values[key] || '';
            $('#ach-reveal').innerHTML = '';
        } catch (e) { toast(e.message, 'error'); }
    },

    async save(thenDownload) {
        const body = {};
        for (const [key] of AchFile.FIELDS) {
            const v = ($(`#ach-${key}`)?.value || '').trim();
            if (v) body[key] = v;
        }
        if (thenDownload && Object.keys(body).length < AchFile.FIELDS.length) {
            return toast('All four fields are required', 'error');
        }
        try {
            const s = await API.put('/payroll/ach-settings', body);
            AchFile._saved = s.values;
            toast('Bank details saved');
        } catch (e) { return toast(e.message, 'error'); }
        if (thenDownload) return AchFile.download();
        AchFile._render('view');
    },

    async download() {
        try {
            const name = await postAndSaveFile(AchFile._url, {}, AchFile._fallbackName);
            closeModal();
            toast(`Saved ${name}`);
        } catch (e) { toast(e.message, 'error'); }
    },
};
