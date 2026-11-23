/* Mockup-only behaviour: approve / edit / reject / retry feedback. Real app uses React state + BFF calls. */
document.querySelectorAll('[data-draft],[role=alert]').forEach(function (root) {
  var status = root.querySelector('.act-status');
  var body = root.querySelector('.draft-body'), subj = root.querySelector('.draft-subj');
  root.querySelectorAll('[data-act]').forEach(function (b) {
    b.addEventListener('click', function () {
      var a = b.dataset.act;
      if (a === 'edit' && body) {
        var editing = body.readOnly;
        body.readOnly = subj.readOnly = !editing;
        b.lastChild.textContent = editing ? 'Save edit' : 'Edit';
        if (editing) body.focus();
        status.textContent = editing ? 'Editing. Your changes are saved as the version that will be sent.' : 'Edit saved. The original draft is kept for audit.';
      } else if (a === 'approve') { status.textContent = 'Approved. The email is queued and will appear in Mailpit in a few seconds.'; }
      else if (a === 'reject') { status.textContent = 'Rejected. No email will be sent to this lead.'; }
      else if (a === 'retry') { status.textContent = 'Retry started. Run #2 is qualifying this lead.'; }
    });
  });
});
