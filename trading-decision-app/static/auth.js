/* =========================================================================
   Auth module — Supabase Auth + a minimal login/signup modal.

   - Supabase client is loaded from the CDN script tag in index.html
     (window.supabase). We wrap it in a small `Auth` API so the rest of
     app.js doesn't have to know about Supabase internals.
   - When `window.APP_CONFIG` is missing or has no Supabase keys, the
     module silently falls back to "anonymous" — the rest of the app keeps
     working with localStorage history.
   - Exposes a global `Auth` and `Decisions` (CRUD on the decisions table).
   ========================================================================= */

(function () {
  "use strict";

  const cfg = window.APP_CONFIG || {};
  const SUPABASE_URL = cfg.SUPABASE_URL || "";
  const SUPABASE_ANON = cfg.SUPABASE_ANON_KEY || "";

  let client = null;
  let session = null;
  const listeners = new Set();

  function isConfigured() {
    return Boolean(SUPABASE_URL && SUPABASE_ANON && window.supabase);
  }

  function notify() { listeners.forEach(fn => { try { fn(session); } catch (e) { console.error(e); } }); }

  // ------------------------------------------------------------------ Auth
  const Auth = {
    isConfigured,

    async init() {
      if (!isConfigured()) {
        console.info("[auth] Supabase not configured — running anonymous-only");
        return null;
      }
      try {
        client = window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON, {
          auth: { persistSession: true, autoRefreshToken: true },
        });
        const { data } = await client.auth.getSession();
        session = data?.session || null;
        client.auth.onAuthStateChange((_evt, sess) => {
          session = sess || null;
          notify();
        });
        return session;
      } catch (e) {
        console.error("[auth] init failed:", e);
        return null;
      }
    },

    onChange(cb) { listeners.add(cb); return () => listeners.delete(cb); },

    user() { return session?.user || null; },
    accessToken() { return session?.access_token || null; },
    isSignedIn() { return Boolean(session?.user); },

    async signUp(email, password, displayName) {
      if (!isConfigured()) throw new Error("Supabase 未配置");
      const { data, error } = await client.auth.signUp({
        email, password,
        options: { data: { display_name: displayName || email.split("@")[0] } },
      });
      if (error) throw error;
      session = data.session;
      notify();
      return data;
    },

    async signIn(email, password) {
      if (!isConfigured()) throw new Error("Supabase 未配置");
      const { data, error } = await client.auth.signInWithPassword({ email, password });
      if (error) throw error;
      session = data.session;
      notify();
      return data;
    },

    async signInWithMagicLink(email) {
      if (!isConfigured()) throw new Error("Supabase 未配置");
      const { error } = await client.auth.signInWithOtp({ email });
      if (error) throw error;
    },

    async signOut() {
      if (!client) return;
      await client.auth.signOut();
      session = null;
      notify();
    },

    /**
     * Change the password for the current signed-in user.
     * Verifies the current password first by re-signing-in (Supabase doesn't
     * require it, but checking blocks drive-by changes on an unlocked machine).
     */
    async updatePassword(currentPassword, newPassword) {
      if (!isConfigured()) throw new Error("Supabase 未配置");
      if (!session?.user?.email) throw new Error("未登录");
      if (!newPassword || newPassword.length < 6) throw new Error("新密码至少 6 位");
      // Step 1: verify the current password by attempting a re-auth.
      const { error: verifyErr } = await client.auth.signInWithPassword({
        email: session.user.email, password: currentPassword,
      });
      if (verifyErr) throw new Error("当前密码不正确");
      // Step 2: update.
      const { error } = await client.auth.updateUser({ password: newPassword });
      if (error) throw error;
    },

    rawClient() { return client; },
  };

  // ------------------------------------------------------------- Decisions
  // Thin CRUD wrapper around the `decisions` table. RLS in Supabase
  // ensures every query is automatically scoped to auth.uid().
  const Decisions = {
    isConfigured,

    async list() {
      if (!client || !session) return { rows: [], error: null };
      // Try the summary view first (cheaper — no run_state JSONB).
      let { data, error } = await client
        .from("decisions_summary")
        .select("*")
        .order("created_at", { ascending: false })
        .limit(500);
      if (error) {
        console.warn("[decisions] view failed, falling back to decisions:", error.message);
        // View missing / column drift — fall back to the base table so the
        // user can at least see records. Pull params JSONB so the UI can
        // still extract llm_provider / depth / mode for filtering.
        const fb = await client
          .from("decisions")
          .select("id,ticker,trade_date,rating,status,started_at,completed_at,created_at,pinned,user_rating,user_note,params")
          .order("created_at", { ascending: false })
          .limit(500);
        if (fb.data) {
          // Normalise to the shape decisions_summary would have produced.
          data = fb.data.map(r => ({
            ...r,
            llm_provider:    r.params?.llm_provider ?? null,
            deep_think_llm:  r.params?.deep_think_llm ?? null,
            quick_think_llm: r.params?.quick_think_llm ?? null,
            instrument_hint: r.params?.instrument_hint ?? null,
            mode:            r.params?.mode ?? null,
            output_language: r.params?.output_language ?? null,
            research_depth:  r.params?.research_depth ?? null,
          }));
        } else {
          data = null;
        }
        error = fb.error;
        if (error) console.error("[decisions] list (fallback)", error);
      }
      return { rows: data || [], error: error ? (error.message || String(error)) : null };
    },

    async get(id) {
      if (!client || !session) return null;
      const { data, error } = await client
        .from("decisions")
        .select("*")
        .eq("id", id)
        .single();
      if (error) { console.error("[decisions] get", error); return null; }
      return data;
    },

    async upsert(entry) {
      if (!client || !session) return null;
      const row = {
        id: entry.id,
        user_id: session.user.id,
        ticker: entry.ticker,
        trade_date: entry.trade_date,
        rating: entry.rating,
        status: entry.status || "done",
        started_at: entry.startedAt,
        completed_at: entry.completedAt,
        pinned: !!entry.pinned,
        user_rating: entry.user_rating || 0,
        user_note: entry.user_note || null,
        params: entry.params,
        run_state: entry.runState,
      };
      const { data, error } = await client
        .from("decisions")
        .upsert(row, { onConflict: "id" })
        .select()
        .single();
      if (error) { console.error("[decisions] upsert", error); return null; }
      return data;
    },

    async delete(id) {
      if (!client || !session) return false;
      const { error } = await client.from("decisions").delete().eq("id", id);
      if (error) { console.error("[decisions] delete", error); return false; }
      return true;
    },

    async deleteAll() {
      if (!client || !session) return false;
      const { error } = await client.from("decisions").delete().eq("user_id", session.user.id);
      if (error) { console.error("[decisions] deleteAll", error); return false; }
      return true;
    },
  };

  window.Auth = Auth;
  window.Decisions = Decisions;
})();
