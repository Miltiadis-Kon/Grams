-- ============================================================
-- Grams — Full PostgreSQL Schema
-- Run once on a fresh database (handled automatically by Docker)
-- ============================================================

-- Enable pgcrypto for UUID generation (optional, recipe_id is text)
-- CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ──────────────────────────────────────────────────────────────
-- Foods table (OpenNutrition dataset + barcode lookups)
-- ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.foods (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    protein_g   REAL DEFAULT 0,
    carbs_g     REAL DEFAULT 0,
    fat_g       REAL DEFAULT 0,
    energy_kcal REAL DEFAULT 0,
    serving     TEXT
);

-- Full-text search index on food name (English dictionary)
CREATE INDEX IF NOT EXISTS foods_name_fts_idx
    ON public.foods USING gin (to_tsvector('english', name));

-- Case-insensitive LIKE index (trigram — requires pg_trgm extension)
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX IF NOT EXISTS foods_name_trgm_idx
    ON public.foods USING gin (name gin_trgm_ops);

-- ──────────────────────────────────────────────────────────────
-- Recipes table
-- ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.recipes (
    recipe_id    TEXT PRIMARY KEY,
    name         TEXT,
    url          TEXT,
    description  TEXT,
    macros       JSONB DEFAULT '{}',
    ingredients  JSONB DEFAULT '[]',
    instructions JSONB DEFAULT '[]',
    tags         JSONB DEFAULT '[]',
    added_on     TEXT,
    updated_at   TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS recipes_name_idx ON public.recipes (name);
CREATE INDEX IF NOT EXISTS recipes_tags_idx ON public.recipes USING gin (tags);

-- ──────────────────────────────────────────────────────────────
-- Not-added (failed) recipes table — same schema as recipes
-- ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.not_added_recipes (
    recipe_id    TEXT PRIMARY KEY,
    name         TEXT,
    url          TEXT,
    description  TEXT,
    macros       JSONB DEFAULT '{}',
    ingredients  JSONB DEFAULT '[]',
    instructions JSONB DEFAULT '[]',
    tags         JSONB DEFAULT '[]',
    added_on     TEXT,
    updated_at   TIMESTAMPTZ
);
