PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT NOT NULL UNIQUE COLLATE NOCASE,
    display_name  TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    timezone      TEXT NOT NULL DEFAULT 'UTC',
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id           INTEGER NOT NULL,
    title             TEXT NOT NULL,
    description       TEXT NOT NULL DEFAULT '',
    category          TEXT NOT NULL DEFAULT 'other',
    due_date          TEXT,
    status            TEXT NOT NULL DEFAULT 'pending'
                      CHECK (status IN ('pending', 'completed')),
    priority          TEXT NOT NULL DEFAULT 'MEDIUM'
                      CHECK (priority IN ('HIGH', 'MEDIUM', 'LOW')),
    priority_source   TEXT NOT NULL DEFAULT 'auto'
                      CHECK (priority_source IN ('auto', 'manual')),
    predicted_priority TEXT,
    risk_score        REAL,
    risk_band         TEXT,
    effort_minutes    INTEGER NOT NULL DEFAULT 60
                      CHECK (effort_minutes > 0 AND effort_minutes <= 10080),
    completed_at      TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_tasks_user_status ON tasks (user_id, status);
CREATE INDEX IF NOT EXISTS idx_tasks_user_due ON tasks (user_id, due_date);
CREATE INDEX IF NOT EXISTS idx_tasks_user_risk ON tasks (user_id, risk_score DESC);

CREATE TABLE IF NOT EXISTS risk_predictions (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id          INTEGER NOT NULL,
    task_id          INTEGER,
    model_version    TEXT NOT NULL,
    risk_score       REAL NOT NULL,
    risk_band        TEXT NOT NULL,
    confidence       REAL,
    signals_json     TEXT NOT NULL,
    rescue_plan_json TEXT NOT NULL,
    accepted         INTEGER NOT NULL DEFAULT 1,
    created_at       TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
    FOREIGN KEY (task_id) REFERENCES tasks (id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_predictions_user ON risk_predictions (user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS settings (
    user_id          INTEGER PRIMARY KEY,
    high_keywords    TEXT NOT NULL,
    medium_keywords  TEXT NOT NULL,
    category_weights TEXT NOT NULL,
    auto_priority    INTEGER NOT NULL DEFAULT 1,
    theme            TEXT NOT NULL DEFAULT 'dark',
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);

PRAGMA user_version = 1;
