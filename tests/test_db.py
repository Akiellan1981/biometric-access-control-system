from acs.storage.db import DB


def make_db(tmp_path):
    db = DB(tmp_path / "t.db")
    db.init_schema()
    return db


def test_people_crud(tmp_path):
    db = make_db(tmp_path)
    pid = db.add_person("Asha")
    assert db.get_person(pid)["name"] == "Asha"
    db.rename_person(pid, "Asha K")
    assert db.get_person(pid)["name"] == "Asha K"
    db.delete_person(pid)
    assert db.get_person(pid) is None


def test_events_and_stats(tmp_path):
    db = make_db(tmp_path)
    pid = db.add_person("Ravi")
    db.log_event(pid, "Ravi", "face", "granted", 0.8)
    db.log_event(None, "unknown", "face", "denied-spoof", 0.1, image_path="x.jpg")
    assert len(db.recent_events()) == 2
    assert len(db.query_events(result="granted")) == 1
    assert len(db.intruders()) == 1
    s = db.stats_today()
    assert s["entries"] == 1 and s["spoof"] == 1 and s["enrolled"] == 1


def test_finger_map(tmp_path):
    db = make_db(tmp_path)
    pid = db.add_person("Sara")
    db.add_finger_template(pid, 5)
    assert db.finger_map()[5]["person_id"] == pid
