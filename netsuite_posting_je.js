/**
 * @NApiVersion 2.1
 * @NScriptType Restlet
 */
define(['N/record', 'N/error', 'N/log', 'N/search'], (record, error, log, search) => {
  // ---- Constants -----------------------------------------------------------
  // fixed sublist ID for JE lines
  const SUBLIST = 'line'; 

  // ---- Helpers -------------------------------------------------------------

  function safeStringify(obj, max = 800) {
    // Prevent huge/PII payloads from flooding logs
    const s = JSON.stringify(obj);
    return s.length > max ? s.slice(0, max) + '…(truncated)' : s;
  }

  function requireBody(body) {
    if (!body || typeof body !== 'object') {
      throw error.create({
        name: 'BAD_REQUEST_NO_BODY',
        message: 'Request body must be a JSON object.'
      });
    }
  }

  function requireLines(lines) {
    if (!Array.isArray(lines) || lines.length < 2) {
      throw error.create({
        name: 'BAD_REQUEST_LINES',
        message: 'Provide at least 2 lines in "lines".'
      });
    }
  }

  function validateLineShape(line, index) {
    if (!line || typeof line !== 'object') {
      throw error.create({
        name: 'BAD_LINE',
        message: `Line ${index + 1} must be an object.`
      });
    }
    if (line.account == null) {
      throw error.create({
        name: 'MISSING_ACCOUNT',
        message: `Line ${index + 1} is missing "account" (internal ID).`
      });
    }
    const hasDebit = line.debit != null;
    const hasCredit = line.credit != null;
    if (hasDebit === hasCredit) {
      // both set or neither set
      throw error.create({
        name: 'BAD_AMOUNT',
        message: `Line ${index + 1} must have exactly one of "debit" or "credit".`
      });
    }
  }

  function validateBalanced(lines) {
    let debit = 0, credit = 0;
    for (const l of lines) {
      if (l.debit != null)  debit  += Number(l.debit);
      if (l.credit != null) credit += Number(l.credit);
    }
    // compare to cents
    const cents = (n) => Math.round(Number(n) * 100);
    if (cents(debit) !== cents(credit)) {
      throw error.create({
        name: 'JE_NOT_BALANCED',
        message: `Debits (${debit.toFixed(2)}) must equal credits (${credit.toFixed(2)}).`
      });
    }
  }
  
  function findExistingJournal(externalid) {
    const results = search.create({
        type: record.Type.JOURNAL_ENTRY,
        filters: [
            ['externalidstring', 'is', externalid]
        ],
        columns: ['internalid']
    }).run().getRange({ start: 0, end: 1 });
    return results.length ? results[0].getValue('internalid') : null;
    }


  function setBodyFields(je, body) {
    const [y, m, d] = body.trandate.split('-');
    const dateObj = new Date(y, m - 1, d);  // Local date;
    if (body.trandate)   je.setValue({ fieldId: 'trandate',   value: dateObj });
    if (body.memo)       je.setValue({ fieldId: 'memo',       value: String(body.memo) });
    if (body.subsidiary) je.setValue({ fieldId: 'subsidiary', value: Number(body.subsidiary) }); // OneWorld only
    if (body.externalid) je.setValue({ fieldId: 'externalid', value: String(body.externalid).trim()})
    //if (body.currency)   je.setValue({ fieldId: 'currency',   value: Number(body.currency) });   // Non-base currency
  }

  function addLine(je, line) {
    je.selectNewLine({ sublistId: SUBLIST });
    je.setCurrentSublistValue({ sublistId: SUBLIST, fieldId: 'account', value: Number(line.account) });
    if (line.debit != null)  je.setCurrentSublistValue({ sublistId: SUBLIST, fieldId: 'debit',  value: Number(line.debit) });
    if (line.credit != null) je.setCurrentSublistValue({ sublistId: SUBLIST, fieldId: 'credit', value: Number(line.credit) });
    if (line.memo)           je.setCurrentSublistValue({ sublistId: SUBLIST, fieldId: 'memo',   value: String(line.memo) });
    je.commitLine({ sublistId: SUBLIST });
  }

  // ---- Entry point ---------------------------------------------------------

  function post(body) {
    // 1) Log the raw request (trimmed) at DEBUG
    log.debug({ title: 'JE RESTlet: Request received', details: safeStringify(body) });

    try {
      // 2) Fail fast on shape errors (400-like)
      requireBody(body);
      requireLines(body.lines);
      body.lines.forEach((line, i) => validateLineShape(line, i));
      validateBalanced(body.lines);
      var existing = findExistingJournal(String(body.externalid).trim())
      // If duplicated,
      if(existing){
        log.audit("JE already exists", existing);
        return { report: 'duplicate', internalID: existing, subsidiary: body.subsidiary };
       }

      // 3) Build the record in dynamic mode
      const je = record.create({ type: record.Type.JOURNAL_ENTRY, isDynamic: true });
      setBodyFields(je, body);

      // 4) Add lines (DEBUG one lightweight summary; avoid dumping PII)
      log.debug({
        title: 'JE lines summary',
        details: `count=${body.lines.length}`
      });

      for (const line of body.lines) {
        log.debug("line.account raw", JSON.stringify(line.account));
        addLine(je, line);
      }

      // 5) Save + AUDIT success (good for operational reporting)
      const id = je.save({ enableSourcing: true, ignoreMandatoryFields: false });
      log.audit({ title: 'JE saved', details: `id=${id}` });

      return { report: 'success', internalID: id, subsidiary: body.subsidiary }; 
      
    } catch (e) {
      // 6) Log the error, then rethrow a concise SuiteScriptError (non-2xx to client)
      log.error({
        title: e.name || 'JE_CREATE_FAILED',
        details: e.message || String(e)
      });

      // Wrap non-SuiteScript errors in a SuiteScript error for consistency
      if (e && typeof e === 'object' && e.name && e.message) {
        throw e; // already a SuiteScriptError (or similar)
      } else {
        throw error.create({
          name: 'JE_CREATE_FAILED',
          message: String(e)
        });
      }
    }
  }

  return { post };
});
