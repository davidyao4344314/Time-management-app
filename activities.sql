CREATE TABLE IF NOT EXISTS activities(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    subject TEXT,
    activity_type TEXT NOT NULL CHECK (activity_type IN ('one_time', 'daily', 'weekly')),
    date TEXT,
    weekday TEXT,
    start_time TEXT,
    end_time TEXT,
    active_start_date TEXT,
    active_end_date TEXT,
    source TEXT NOT NULL DEFAULT 'Manual',
    external_id TEXT
);
CREATE TABLE IF NOT EXISTS exams(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    subject TEXT,
    date TEXT NOT NULL,
    start_time TEXT,
    end_time TEXT,
    source TEXT NOT NULL DEFAULT 'Manual',
    external_id TEXT
);
CREATE TABLE IF NOT EXISTS uoa_activity_external_ids(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    activity_id INTEGER NOT NULL,
    external_id TEXT NOT NULL,
    FOREIGN KEY(activity_id) REFERENCES activities(id) ON DELETE CASCADE,
    UNIQUE(activity_id, external_id)
);
