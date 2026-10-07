import sqlite3

from agent.nodes.seed_data_postprocess import postprocess_seed_sql


def _column(
    column_id: str,
    name: str,
    *,
    primary_key: bool = False,
    ref_table_id: str | None = None,
    ref_column_id: str | None = None,
) -> dict:
    roles: dict = {"primaryKey": primary_key}
    if ref_table_id and ref_column_id:
        roles["foreignKey"] = {
            "refTableId": ref_table_id,
            "refColumnId": ref_column_id,
        }
    return {
        "id": column_id,
        "name": name,
        "dataType": "integer",
        "nullable": False,
        "unique": False,
        "roles": roles,
    }


def _composite_fk_schema() -> dict:
    return {
        "model": {"id": "school", "name": "school", "version": 1},
        "tables": [
            {
                "id": "course",
                "name": "Course",
                "columns": [_column("course_id", "course_id", primary_key=True)],
            },
            {
                "id": "student",
                "name": "Student",
                "columns": [_column("student_id", "student_id", primary_key=True)],
            },
            {
                "id": "section",
                "name": "Section",
                "columns": [
                    _column(
                        "section_course_id",
                        "course_id",
                        primary_key=True,
                        ref_table_id="course",
                        ref_column_id="course_id",
                    ),
                    _column(
                        "section_number", "section_number", primary_key=True
                    ),
                ],
            },
            {
                "id": "enrollment",
                "name": "enrollment",
                "columns": [
                    _column(
                        "enrollment_student_id",
                        "student_id",
                        primary_key=True,
                        ref_table_id="student",
                        ref_column_id="student_id",
                    ),
                    _column(
                        "enrollment_course_id",
                        "course_id",
                        primary_key=True,
                        ref_table_id="section",
                        ref_column_id="section_course_id",
                    ),
                    _column(
                        "enrollment_section_number",
                        "section_number",
                        primary_key=True,
                        ref_table_id="section",
                        ref_column_id="section_number",
                    ),
                ],
            },
        ],
    }


def test_postprocess_remaps_composite_foreign_keys_as_tuples(monkeypatch) -> None:
    monkeypatch.setattr(
        "agent.nodes.seed_data_postprocess.random.randint", lambda _a, _b: 1000
    )
    sql = """
    INSERT INTO enrollment (student_id, course_id, section_number) VALUES (10, 1, 1);
    INSERT INTO enrollment (student_id, course_id, section_number) VALUES (11, 1, 2);
    INSERT INTO enrollment (student_id, course_id, section_number) VALUES (12, 2, 1);
    INSERT INTO Section (course_id, section_number) VALUES (1, 1);
    INSERT INTO Section (course_id, section_number) VALUES (1, 2);
    INSERT INTO Section (course_id, section_number) VALUES (2, 1);
    INSERT INTO Student (student_id) VALUES (10);
    INSERT INTO Student (student_id) VALUES (11);
    INSERT INTO Student (student_id) VALUES (12);
    INSERT INTO Course (course_id) VALUES (1);
    INSERT INTO Course (course_id) VALUES (2);
    """

    processed, cyclic_tables = postprocess_seed_sql(
        sql, _composite_fk_schema(), "postgres"
    )

    assert cyclic_tables == set()

    db = sqlite3.connect(":memory:")
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript(
        """
        CREATE TABLE Course (course_id INTEGER PRIMARY KEY);
        CREATE TABLE Student (student_id INTEGER PRIMARY KEY);
        CREATE TABLE Section (
            course_id INTEGER NOT NULL,
            section_number INTEGER NOT NULL,
            PRIMARY KEY (course_id, section_number),
            FOREIGN KEY (course_id) REFERENCES Course(course_id)
        );
        CREATE TABLE enrollment (
            student_id INTEGER NOT NULL,
            course_id INTEGER NOT NULL,
            section_number INTEGER NOT NULL,
            PRIMARY KEY (student_id, course_id, section_number),
            FOREIGN KEY (student_id) REFERENCES Student(student_id),
            FOREIGN KEY (course_id, section_number)
                REFERENCES Section(course_id, section_number)
        );
        """
    )
    db.executescript(processed)

    assert db.execute("SELECT COUNT(*) FROM enrollment").fetchone() == (3,)
    assert db.execute(
        """
        SELECT COUNT(*)
        FROM enrollment AS e
        JOIN Section AS s
          ON s.course_id = e.course_id
         AND s.section_number = e.section_number
        """
    ).fetchone() == (3,)
    assert db.execute(
        "SELECT COUNT(*) FROM Section WHERE course_id = 1000"
    ).fetchone() == (2,)
    db.close()
