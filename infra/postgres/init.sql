CREATE TABLE IF NOT EXISTS users (
    id                   SERIAL PRIMARY KEY,
    ldap_uid             VARCHAR(255) UNIQUE NOT NULL,
    display_name         VARCHAR(255),
    email                VARCHAR(255),
    is_global_admin      BOOLEAN NOT NULL DEFAULT FALSE,
    local_password_hash  VARCHAR(255),
    created_at           TIMESTAMP NOT NULL DEFAULT NOW(),
    last_login           TIMESTAMP
);

CREATE TABLE IF NOT EXISTS instances (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(255) NOT NULL,
    slug        VARCHAR(64)  UNIQUE NOT NULL,
    description TEXT,
    created_at  TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS instance_members (
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    instance_id INTEGER NOT NULL REFERENCES instances(id) ON DELETE CASCADE,
    role        VARCHAR(32) NOT NULL DEFAULT 'viewer',
    added_at    TIMESTAMP NOT NULL DEFAULT NOW(),
    added_by    INTEGER REFERENCES users(id),
    PRIMARY KEY (user_id, instance_id)
);

CREATE TABLE IF NOT EXISTS groups (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(255) NOT NULL,
    ldap_group_dn   TEXT,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS group_instance_roles (
    group_id    INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    instance_id INTEGER NOT NULL REFERENCES instances(id) ON DELETE CASCADE,
    role        VARCHAR(32) NOT NULL DEFAULT 'viewer',
    PRIMARY KEY (group_id, instance_id)
);

CREATE TABLE IF NOT EXISTS group_members (
    user_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    group_id INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, group_id)
);

CREATE TABLE IF NOT EXISTS chat_history (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    instance_id INTEGER NOT NULL REFERENCES instances(id) ON DELETE CASCADE,
    question    TEXT NOT NULL,
    answer      TEXT NOT NULL,
    context_docs JSONB,
    created_at  TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS sessions (
    token      VARCHAR(128) PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sessions_user_id   ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_expires   ON sessions(expires_at);
CREATE INDEX IF NOT EXISTS idx_chat_history_user  ON chat_history(user_id);
CREATE INDEX IF NOT EXISTS idx_chat_history_inst  ON chat_history(instance_id);
CREATE INDEX IF NOT EXISTS idx_chat_history_time  ON chat_history(created_at DESC);
