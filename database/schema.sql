-- DDL Schema for Grams foods Table in Supabase
-- Run this script in the Supabase SQL Editor to initialize the table.

CREATE TABLE IF NOT EXISTS public.foods (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    protein_g REAL DEFAULT 0,
    carbs_g REAL DEFAULT 0,
    fat_g REAL DEFAULT 0,
    energy_kcal REAL DEFAULT 0,
    serving TEXT
);

-- Disable Row Level Security (RLS) for simple read/write access
ALTER TABLE public.foods DISABLE ROW LEVEL SECURITY;

-- Create GIN index for english language full-text search matching on the name column
CREATE INDEX IF NOT EXISTS foods_name_idx ON public.foods USING gin (to_tsvector('english', name));
