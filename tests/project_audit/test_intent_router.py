from core.ai.intent import Intent, classify_intent


def test_analyze():
    assert classify_intent("Analyze this case") == Intent.ANALYZE


def test_status():
    assert classify_intent("What is the case status?") == Intent.STATUS


def test_blockers():
    assert classify_intent("What documents are missing?") == Intent.CHECK_BLOCKERS


def test_create_task():
    assert classify_intent("Create a task") == Intent.CREATE_TASK


def test_assign():
    assert classify_intent("Assign this case to John") == Intent.ASSIGN_TASK


def test_approve():
    assert classify_intent("Approve this case") == Intent.APPROVE_CASE


def test_reject():
    assert classify_intent("Reject this case") == Intent.REJECT_CASE


def test_delete():
    assert classify_intent("Delete this case") == Intent.DELETE_CASE


def test_archive():
    assert classify_intent("Archive this case") == Intent.ARCHIVE_CASE


def test_close():
    assert classify_intent("Close this case") == Intent.CLOSE_CASE


def test_document():
    assert classify_intent("Upload document") == Intent.DOCUMENT_ACTION