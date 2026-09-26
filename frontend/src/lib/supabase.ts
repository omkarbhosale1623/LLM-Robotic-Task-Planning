// Supabase browser client. Created from NEXT_PUBLIC_SUPABASE_URL +
// NEXT_PUBLIC_SUPABASE_ANON_KEY (the anon key is safe to expose to the browser).
//
// The client is created lazily and is null when Supabase is not configured, so
// the app still builds/runs (the login gate then shows a "not configured" note).

import { createClient, type SupabaseClient } from "@supabase/supabase-js";

export const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL ?? "";
export const SUPABASE_ANON_KEY = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "";

export const isSupabaseConfigured = Boolean(SUPABASE_URL && SUPABASE_ANON_KEY);

let _client: SupabaseClient | null = null;

/** Return the singleton Supabase client, or null when not configured. */
export function getSupabase(): SupabaseClient | null {
  if (!isSupabaseConfigured) return null;
  if (_client) return _client;
  _client = createClient(SUPABASE_URL, SUPABASE_ANON_KEY, {
    auth: {
      persistSession: true,
      autoRefreshToken: true,
      detectSessionInUrl: true,
    },
  });
  return _client;
}
