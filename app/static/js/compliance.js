/**
 * Compliance — the document-audit hash chain, its checkpoints, and the
 * off-box artifacts that back them up.
 *
 * The endpoints behind this page were API-first for a while (docs/todo.md
 * called it "the admin Compliance tab"), which meant the integrity story
 * SlowBooks documents under HIPAA § 164.312(c)(1) was only reachable with
 * curl. This surfaces all four questions an auditor actually asks:
 *
 *   1. Does this printed document match its data?      -> hash lookup
 *   2. Has anything been removed from the trail?       -> chain verify
 *   3. Was the tail truncated?                         -> checkpoints
 *   4. Were the checkpoints themselves deleted?        -> artifact verify
 *
 * The last one is the reason the artifact box exists on this page rather
 * than only in the CLI: the answer lives in a file the operator kept
 * somewhere else, so there has to be somewhere to paste it back in.
 */
const CompliancePage = {
    async render() {
        setTimeout(() => {
            CompliancePage.verifyChain();
            CompliancePage.loadCheckpoints();
            CompliancePage.loadAudits();
        }, 0);

        return `
            <div class="page-header">
                <h2>Compliance</h2>
                <div style="font-size:10px; color:var(--text-muted);">
                    Document hash chain, tamper checkpoints, and off-box attestation
                </div>
            </div>

            <div id="chain-status"></div>

            <h3 style="margin-top:18px;">Checkpoints</h3>
            <div style="font-size:10px;color:var(--text-muted);margin-bottom:6px;">
                A checkpoint pins the chain tip so later truncation is detectable.
                Export it and keep the file somewhere this server cannot write.
            </div>
            <div class="toolbar">
                <input type="text" id="cp-note" placeholder="Label (e.g. Q3 close)" style="width:220px;">
                <button class="btn btn-primary" onclick="CompliancePage.createCheckpoint()">
                    Take Checkpoint
                </button>
                <button class="btn" onclick="CompliancePage.artifactBox()">
                    Verify an Exported Artifact
                </button>
            </div>
            <div id="checkpoint-results"></div>

            <h3 style="margin-top:18px;">Document Ledger</h3>
            <div class="toolbar">
                <input type="text" id="doc-type" placeholder="Doc type (w2, 941, cobra...)"
                       style="width:180px;" onchange="CompliancePage.loadAudits()">
                <input type="text" id="doc-hash" placeholder="Paste a 64-char content hash to look up"
                       style="width:420px;font-family:monospace;">
                <button class="btn" onclick="CompliancePage.lookupHash()">Look Up Hash</button>
            </div>
            <div id="audit-results"></div>`;
    },

    // --- chain ------------------------------------------------------------

    async verifyChain() {
        const box = $('#chain-status');
        if (!box) return;
        box.innerHTML = '<div class="empty-state"><p>Verifying chain...</p></div>';
        let report;
        try {
            report = await API.get('/document-audits/chain/verify');
        } catch (e) {
            box.innerHTML = `<div class="empty-state"><p>Could not verify: ${escapeHtml(e.message)}</p></div>`;
            return;
        }

        const ok = report.ok;
        const colour = ok ? 'var(--qb-green, #2b7a2b)' : 'var(--qb-red, #b00020)';
        const heading = ok
            ? 'Chain intact'
            : `Chain BROKEN — ${report.breaks.length} break(s)`;

        // rows_unchained is not a failure: rows written before the chain
        // existed carry no linkage. Saying so beats an unexplained number.
        let detail = `
            <div style="font-size:11px;">
                ${report.rows_verified} of ${report.rows_total} rows verified.
                ${report.rows_unchained > 0
                    ? `${report.rows_unchained} pre-date the chain and carry no linkage.`
                    : ''}
            </div>`;
        if (report.tip_audit_id) {
            detail += `<div style="font-size:10px;color:var(--text-muted);font-family:monospace;">
                tip #${report.tip_audit_id} &middot; ${escapeHtml(String(report.tip_chain_hash || '').slice(0, 32))}...
            </div>`;
        }
        if (!ok) {
            detail += '<ul style="font-size:11px;margin:6px 0 0 16px;">' +
                report.breaks.map(b =>
                    `<li>audit #${b.audit_id}: ${escapeHtml(b.reason)}</li>`
                ).join('') + '</ul>';
        }

        box.innerHTML = `
            <div class="table-container" style="padding:10px;border-left:4px solid ${colour};">
                <strong style="color:${colour};">${heading}</strong>
                ${detail}
                <div style="margin-top:8px;">
                    <button class="btn" onclick="CompliancePage.verifyChain()">Re-verify</button>
                </div>
            </div>`;
    },

    // --- checkpoints ------------------------------------------------------

    async loadCheckpoints() {
        const box = $('#checkpoint-results');
        if (!box) return;
        const rows = await API.get('/document-audits/chain/checkpoints?limit=25');
        if (!rows.length) {
            box.innerHTML = `<div class="empty-state">
                <p>No checkpoints yet. Take one now, then export it —
                a checkpoint that only exists in this database is evidence, not proof.</p>
            </div>`;
            return;
        }

        let html = `<div class="table-container"><table>
            <thead><tr>
                <th>#</th><th>Taken</th><th>Label</th><th>Tip</th><th>Rows</th>
                <th>Signature</th><th>Actions</th>
            </tr></thead><tbody>`;
        for (const c of rows) {
            html += `<tr>
                <td>${c.id}</td>
                <td>${c.created_at ? new Date(c.created_at).toLocaleString() : ''}</td>
                <td>${escapeHtml(c.note || '')}</td>
                <td style="font-family:monospace;font-size:10px;">#${c.tip_audit_id}</td>
                <td>${c.row_count}</td>
                <td>${CompliancePage.signatureBadge(c.signature_status, c.signature_key_id)}</td>
                <td>
                    <button class="btn" onclick="CompliancePage.verifyCheckpoint(${c.id})">Verify</button>
                    <a class="btn" href="/api/document-audits/chain/checkpoints/${c.id}/export"
                       download="slowbooks-checkpoint-${c.id}.json">Export</a>
                </td>
            </tr>`;
        }
        box.innerHTML = html + '</tbody></table></div>';
    },

    /** Five states, because they mean very different things to an auditor. */
    signatureBadge(status, keyId) {
        const map = {
            valid:              ['badge-paid', 'signed'],
            valid_previous_key: ['badge-sent', 'signed (old key)'],
            unsigned:           ['badge-void', 'unsigned'],
            unverifiable:       ['badge-void', 'no key here'],
            invalid:            ['badge-void', 'INVALID'],
        };
        const [cls, label] = map[status] || ['badge-void', status || '?'];
        const title = keyId ? ` title="key: ${escapeHtml(keyId)}"` : '';
        return `<span class="badge ${cls}"${title}>${label}</span>`;
    },

    async createCheckpoint() {
        const note = $('#cp-note')?.value?.trim() || null;
        try {
            const cp = await API.post('/document-audits/chain/checkpoints', { note });
            $('#cp-note').value = '';
            if (cp.signature_status === 'unsigned') {
                // Not an error — but silence here would let an operator
                // believe they have something they do not.
                toast('Checkpoint taken, but UNSIGNED — set AUDIT_CHECKPOINT_SIGNING_SECRET', 'error');
            } else {
                toast(`Checkpoint #${cp.id} taken and signed`);
            }
            CompliancePage.loadCheckpoints();
        } catch (e) {
            // 409 = the chain is already broken, so checkpointing it would
            // launder the break into the baseline.
            toast(e.message, 'error');
        }
    },

    async verifyCheckpoint(id) {
        const r = await API.get(`/document-audits/chain/checkpoints/${id}/verify`);
        openModal(`Checkpoint #${id}`, CompliancePage.verdictHtml(r));
    },

    // --- off-box artifacts ------------------------------------------------

    artifactBox() {
        openModal('Verify an Exported Artifact', `
            <p style="font-size:11px;color:var(--text-muted);">
                Paste the contents of a checkpoint artifact you kept off this
                machine. It verifies against the live chain even if every
                checkpoint row in the database has been deleted — which is the
                one case the in-database checkpoints cannot cover.
            </p>
            <textarea id="artifact-json" rows="10"
                      style="width:100%;font-family:monospace;font-size:10px;"
                      placeholder='{"artifact": "slowbooks-audit-checkpoint", ...}'></textarea>
            <div style="margin-top:8px;">
                <button class="btn btn-primary" onclick="CompliancePage.verifyArtifact()">Verify</button>
                <button class="btn" onclick="closeModal()">Cancel</button>
            </div>
            <div id="artifact-result" style="margin-top:10px;"></div>`);
    },

    async verifyArtifact() {
        const box = $('#artifact-result');
        let parsed;
        try {
            parsed = JSON.parse($('#artifact-json').value);
        } catch (e) {
            box.innerHTML = '<div style="color:var(--qb-red,#b00020);font-size:11px;">Not valid JSON.</div>';
            return;
        }
        try {
            const r = await API.post('/document-audits/chain/checkpoints/verify-artifact', parsed);
            box.innerHTML = CompliancePage.verdictHtml(r);
        } catch (e) {
            box.innerHTML = `<div style="color:var(--qb-red,#b00020);font-size:11px;">${escapeHtml(e.message)}</div>`;
        }
    },

    /**
     * Shared verdict rendering for both checkpoint and artifact verification.
     * Deliberately shows containment and signature SEPARATELY: an unsigned
     * checkpoint over an untouched chain is a setup gap, not a tampering
     * finding, and collapsing them into one red light would train an operator
     * to ignore the light.
     */
    verdictHtml(r) {
        const good = 'var(--qb-green, #2b7a2b)';
        const bad = 'var(--qb-red, #b00020)';
        const line = (label, ok, text) => `
            <div style="font-size:11px;margin:3px 0;">
                <strong style="color:${ok ? good : bad};">${ok ? 'OK' : 'FAIL'}</strong>
                &nbsp;${label}: ${escapeHtml(text)}
            </div>`;

        let html = `<div style="border-left:4px solid ${r.ok ? good : bad};padding-left:10px;">
            <strong style="color:${r.ok ? good : bad};">
                ${r.ok ? 'Verified' : 'Not verified'}
            </strong>`;

        html += line(
            'Contains the checkpointed state',
            r.contains_checkpointed_state,
            r.contains_checkpointed_state
                ? `${r.current_row_count} rows now, ${r.checkpoint_row_count} at checkpoint time`
                : 'rows are missing since this checkpoint was taken');

        html += line(
            'Signature',
            r.signature?.ok,
            r.signature?.detail || r.signature?.status || 'unknown');

        if (r.checkpoint_row_present === false) {
            html += line(
                'Database copy',
                false,
                'the checkpoint row is gone — only this artifact still attests to that state');
        }

        if (r.problems?.length) {
            html += '<ul style="font-size:11px;margin:6px 0 0 16px;">' +
                r.problems.map(p => `<li>${escapeHtml(p)}</li>`).join('') + '</ul>';
        }
        return html + '</div>';
    },

    // --- document ledger --------------------------------------------------

    async loadAudits() {
        const box = $('#audit-results');
        if (!box) return;
        const docType = $('#doc-type')?.value?.trim() || '';
        let url = '/document-audits?limit=50';
        if (docType) url += `&doc_type=${encodeURIComponent(docType)}`;
        CompliancePage.renderAudits(await API.get(url));
    },

    async lookupHash() {
        const hash = $('#doc-hash')?.value?.trim().toLowerCase() || '';
        if (!hash) return CompliancePage.loadAudits();
        try {
            const rows = await API.get(`/document-audits/verify/${encodeURIComponent(hash)}`);
            CompliancePage.renderAudits(rows, hash);
        } catch (e) {
            toast(e.message, 'error');
        }
    },

    renderAudits(rows, lookedUpHash) {
        const box = $('#audit-results');
        if (!rows.length) {
            box.innerHTML = `<div class="empty-state"><p>${
                lookedUpHash
                    ? 'No document in the ledger has that hash — it was not produced by this system, or its data has changed since.'
                    : 'No documents recorded yet.'
            }</p></div>`;
            return;
        }
        let html = `<div class="table-container"><table>
            <thead><tr>
                <th>#</th><th>Issued</th><th>Type</th><th>Key</th>
                <th>Content Hash</th><th>Chained</th>
            </tr></thead><tbody>`;
        for (const a of rows) {
            html += `<tr>
                <td>${a.id}</td>
                <td>${a.created_at ? new Date(a.created_at).toLocaleString() : ''}</td>
                <td>${escapeHtml(a.doc_type)}</td>
                <td>${escapeHtml(a.doc_key)}</td>
                <td style="font-family:monospace;font-size:10px;" title="${escapeHtml(a.content_hash)}">
                    ${escapeHtml(a.content_hash.slice(0, 24))}...
                </td>
                <td>${a.chain_hash
                    ? '<span class="badge badge-paid">linked</span>'
                    : '<span class="badge badge-void">pre-chain</span>'}</td>
            </tr>`;
        }
        box.innerHTML = html + '</tbody></table></div>';
    },
};
