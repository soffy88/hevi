from oskill.expand_tasks_from_note import expand_tasks_from_note


def test_expand_tasks_from_note_empty():
    assert expand_tasks_from_note("") == []
    assert expand_tasks_from_note("   ") == []


def test_expand_tasks_from_note_basic():
    note = "- [ ] Task 1"
    tasks = expand_tasks_from_note(note)
    assert len(tasks) == 1
    assert tasks[0].text == "Task 1"
    assert tasks[0].completed is False
    assert len(tasks[0].fingerprint) == 16


def test_expand_tasks_from_note_normalization():
    # NFKC normalization and spacing
    note = "- [ ] Ｔａｓｋ   １"
    tasks = expand_tasks_from_note(note)
    assert len(tasks) == 1
    assert tasks[0].text == "Task 1"


def test_expand_tasks_from_note_deduplication():
    note = "- [ ] Task 1\nSome text\n- [ ] task 1"
    tasks = expand_tasks_from_note(note)
    assert len(tasks) == 1
    assert tasks[0].source_line == 1


def test_expand_tasks_from_note_dates_distinguish():
    note = "- [ ] Task 1 📅 2024-05-20\n- [ ] Task 1 📅 2024-05-21"
    tasks = expand_tasks_from_note(note)
    assert len(tasks) == 2


def test_expand_tasks_from_note_completed_distinguish():
    note = "- [ ] Task 1\n- [x] Task 1"
    tasks = expand_tasks_from_note(note)
    assert len(tasks) == 2


def test_expand_tasks_from_note_tags_order_insensitive():
    note = "- [ ] Task 1 #a #b\n- [ ] Task 1 #b #a"
    tasks = expand_tasks_from_note(note)
    assert len(tasks) == 1


def test_expand_tasks_from_note_source_line_ordering():
    note = "\n\n- [ ] Task 2\n- [ ] Task 1"
    tasks = expand_tasks_from_note(note)
    assert len(tasks) == 2
    assert tasks[0].text == "Task 2"
    assert tasks[0].source_line == 3
    assert tasks[1].text == "Task 1"
    assert tasks[1].source_line == 4


def test_expand_tasks_from_note_keeps_smaller_source_line():
    note = "- [ ] Task\n\n- [ ] task"
    tasks = expand_tasks_from_note(note)
    assert len(tasks) == 1
    assert tasks[0].source_line == 1
