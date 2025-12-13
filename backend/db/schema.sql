-- ============================================================
-- SerenAI — Database Schema
-- ============================================================

-- ======================
-- 1) users
-- ======================
CREATE TABLE users (
  id              SERIAL PRIMARY KEY,
  email           TEXT NOT NULL UNIQUE,
  hashed_password TEXT NOT NULL,
  name            TEXT,
  is_active       BOOLEAN NOT NULL DEFAULT TRUE,
  created_at      timestamptz NOT NULL DEFAULT now(),
  last_login_at   timestamptz
);

-- ======================
-- 2) user_profiles (1:1 with users)
-- ======================
CREATE TABLE user_profiles (
  id          SERIAL PRIMARY KEY,
  user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  full_name   TEXT,
  dob         DATE,
  preferences JSONB,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX ux_user_profiles_user_id ON user_profiles(user_id);

-- ======================
-- 3) mom_profiles (personality + training metadata)
-- ======================
CREATE TABLE mom_profiles (
  id                  SERIAL PRIMARY KEY,
  user_id             INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  personality         JSONB,      -- personality structure
  voice_model_id      TEXT,       -- fine-tuned model id
  voice_model_type    TEXT,       -- e.g., elevenlabs / local
  voice_ready         BOOLEAN NOT NULL DEFAULT FALSE,
  persona_model_id    TEXT,
  persona_ready       BOOLEAN NOT NULL DEFAULT FALSE,
  consent_given       BOOLEAN NOT NULL DEFAULT FALSE,
  consent_granted_at  timestamptz,
  voice_count         INTEGER NOT NULL DEFAULT 0,
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX ux_mom_profiles_user_id ON mom_profiles(user_id);
CREATE INDEX ix_mom_profiles_personality_gin ON mom_profiles USING GIN (personality);

-- ======================
-- 4) mom_voices (one row per audio file)
-- ======================
CREATE TABLE mom_voices (
  id             SERIAL PRIMARY KEY,
  mom_profile_id INTEGER NOT NULL REFERENCES mom_profiles(id) ON DELETE CASCADE,
  user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  filename       TEXT NOT NULL,         -- original name
  stored_name    TEXT NOT NULL,         -- safe uuid filename
  path           TEXT NOT NULL,         -- storage path or S3
  mime_type      TEXT,
  size_bytes     BIGINT,
  duration_secs  NUMERIC,
  checksum       TEXT,
  status         TEXT NOT NULL DEFAULT 'pending', -- pending/validated/trained/rejected
  uploaded_at    timestamptz NOT NULL DEFAULT now(),
  is_active      BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE INDEX ix_mom_voices_mom_profile_id ON mom_voices(mom_profile_id);
CREATE INDEX ix_mom_voices_user_id ON mom_voices(user_id);
CREATE UNIQUE INDEX ux_mom_voices_stored_name ON mom_voices(stored_name);

-- Status validation
ALTER TABLE mom_voices
  ADD CONSTRAINT chk_mom_voices_status
  CHECK (status IN ('pending','validated','trained','rejected'));

-- ======================
-- 5) jobs (background processing)
-- ======================
CREATE TABLE jobs (
  id         SERIAL PRIMARY KEY,
  user_id    INTEGER REFERENCES users(id) ON DELETE SET NULL,
  type       TEXT NOT NULL,              -- voice_train, persona_train, etc.
  status     TEXT NOT NULL,              -- queued, running, success, failed
  meta       JSONB,
  error_msg  TEXT,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX ix_jobs_user_id ON jobs(user_id);
CREATE INDEX ix_jobs_status ON jobs(status);

ALTER TABLE jobs
  ADD CONSTRAINT chk_jobs_status
  CHECK (status IN ('queued','running','success','failed'));

-- ======================
-- 6) audit_events (optional logging)
-- ======================
CREATE TABLE audit_events (
  id         BIGSERIAL PRIMARY KEY,
  user_id    INTEGER REFERENCES users(id) ON DELETE SET NULL,
  event_type TEXT NOT NULL,
  payload    JSONB,
  ip_address INET,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX ix_audit_events_user_id ON audit_events(user_id);
CREATE INDEX ix_audit_events_event_type ON audit_events(event_type);

-- ======================
-- 7) error catalog
-- ======================
CREATE TABLE error_catalog (
  id            SERIAL PRIMARY KEY,
  error_code    TEXT NOT NULL UNIQUE,
  http_status   INTEGER NOT NULL,
  short_message TEXT NOT NULL,
  long_message  TEXT,
  severity      TEXT NOT NULL DEFAULT 'error',
  i18n_key      TEXT,
  tags          TEXT[],
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX ix_error_catalog_error_code ON error_catalog(error_code);

-- ======================
-- 8) error occurrences
-- ======================
CREATE TABLE error_occurrence (
  id            BIGSERIAL PRIMARY KEY,
  error_code    TEXT REFERENCES error_catalog(error_code) ON DELETE SET NULL,
  user_id       INTEGER,
  request_path  TEXT,
  http_method   TEXT,
  http_status   INTEGER,
  details       JSONB,
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX ix_error_occurrence_error_code ON error_occurrence(error_code);
CREATE INDEX ix_error_occurrence_user_id ON error_occurrence(user_id);
CREATE INDEX ix_error_occurrence_created_at ON error_occurrence(created_at);

-- ======================
-- 9) user_events
-- ======================
CREATE TABLE user_events (
  id              BIGSERIAL PRIMARY KEY,
  user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,

  event_type      TEXT NOT NULL,  
  -- example: mistake, improvement, habit, emotion, milestone

  event_key       TEXT NOT NULL,  
  -- example: skipped_meal, missed_deadline, procrastination

  severity        TEXT NOT NULL DEFAULT 'medium',
  -- low / medium / high

  source          TEXT NOT NULL DEFAULT 'user',
  -- user / ai / system

  context         JSONB,
  -- free-form details (what happened, why, extra info)

  occurred_at     timestamptz NOT NULL DEFAULT now(),
  created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX ix_user_events_user_id ON user_events(user_id);
CREATE INDEX ix_user_events_event_key ON user_events(event_key);
CREATE INDEX ix_user_events_event_type ON user_events(event_type);

ALTER TABLE user_events
  ADD CONSTRAINT chk_user_events_severity
  CHECK (severity IN ('low','medium','high'));

ALTER TABLE user_events
  ADD CONSTRAINT chk_user_events_source
  CHECK (source IN ('user','ai','system'));

-- ======================
-- 10) behavior_patterns
-- ======================
CREATE TABLE behavior_patterns (
  id                BIGSERIAL PRIMARY KEY,
  user_id           INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,

  pattern_key       TEXT NOT NULL,
  -- example: repeated:skipped_meal

  related_event_key TEXT NOT NULL,
  -- example: skipped_meal

  occurrence_count  INTEGER NOT NULL DEFAULT 1,

  first_seen_at     timestamptz NOT NULL DEFAULT now(),
  last_seen_at      timestamptz NOT NULL DEFAULT now(),

  status            TEXT NOT NULL DEFAULT 'active',
  -- active / resolved / ignored

  meta              JSONB,

  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX ux_behavior_patterns_user_event
  ON behavior_patterns(user_id, pattern_key);

CREATE INDEX ix_behavior_patterns_user_id ON behavior_patterns(user_id);

ALTER TABLE behavior_patterns
  ADD CONSTRAINT chk_behavior_patterns_status
  CHECK (status IN ('active','resolved','ignored'));

-- ======================
-- 11) seren_memory
-- ======================
CREATE TABLE seren_memory (
  id                BIGSERIAL PRIMARY KEY,
  user_id           INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,

  memory_type       TEXT NOT NULL,
  -- emotional / behavioral / preference / trust

  memory_key        TEXT NOT NULL,
  -- example: reacts_well_to_gentle_tone

  memory_value      JSONB NOT NULL,
  -- structured learned data

  confidence_score  NUMERIC DEFAULT 0.5,
  -- 0.0 to 1.0

  source            TEXT NOT NULL DEFAULT 'ai',
  -- ai / system / manual

  last_reinforced_at timestamptz,
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX ux_seren_memory_user_key
  ON seren_memory(user_id, memory_key);

CREATE INDEX ix_seren_memory_user_id ON seren_memory(user_id);

ALTER TABLE seren_memory
  ADD CONSTRAINT chk_seren_memory_type
  CHECK (memory_type IN ('emotional','behavioral','preference','trust'));

ALTER TABLE seren_memory
  ADD CONSTRAINT chk_seren_memory_source
  CHECK (source IN ('ai','system','manual'));


