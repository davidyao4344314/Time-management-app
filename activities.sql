CREATE TABLE IF NOT EXISTS activities(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    subject TEXT,

    activity_type TEXT NOT NULL,

    date TEXT,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS exams(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    SUJECT TEXT,
    date TEXT NOT NULL,
    start_time TEXT not null,
    end_time TEXT NOT NULL
)