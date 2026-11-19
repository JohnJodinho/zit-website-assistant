"""Create the private Phase 1 application schema."""

from alembic import op

revision = "0001_foundation"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA extensions")
    op.execute("CREATE SCHEMA assistant AUTHORIZATION CURRENT_USER")
    op.execute("SET LOCAL search_path TO assistant, public, extensions")
    op.execute("REVOKE ALL ON SCHEMA assistant FROM PUBLIC")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
                EXECUTE 'REVOKE ALL ON SCHEMA assistant FROM anon';
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
                EXECUTE 'REVOKE ALL ON SCHEMA assistant FROM authenticated';
            END IF;
        END
        $$
        """
    )
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA assistant REVOKE ALL ON TABLES FROM PUBLIC")
    op.execute(
        """
        CREATE TABLE assistant.sources (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            kind text NOT NULL,
            name text NOT NULL,
            last_payload_hash text,
            last_run_at timestamptz
        )
        """
    )
    op.execute(
        """
        CREATE TABLE assistant.documents (
            doc_key text PRIMARY KEY,
            doc_type text NOT NULL,
            title text NOT NULL,
            url_path text,
            origin text NOT NULL,
            source_id uuid REFERENCES assistant.sources(id),
            status text NOT NULL DEFAULT 'active',
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE assistant.chunks (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            chunk_key text NOT NULL,
            doc_key text NOT NULL REFERENCES assistant.documents(doc_key),
            version integer NOT NULL,
            kind text NOT NULL,
            origin text NOT NULL,
            overrides_id uuid REFERENCES assistant.chunks(id),
            text text NOT NULL,
            embed_text text,
            token_count integer NOT NULL,
            metadata jsonb NOT NULL DEFAULT '{}',
            content_hash text NOT NULL,
            embedding vector(768),
            embedding_model text,
            created_by text NOT NULL,
            created_via text NOT NULL,
            change_note text,
            trace_id uuid,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (chunk_key, version)
        )
        """
    )
    op.execute("CREATE INDEX chunks_chunk_key_idx ON assistant.chunks (chunk_key)")
    op.execute("CREATE INDEX chunks_content_hash_idx ON assistant.chunks (content_hash)")
    op.execute(
        """
        CREATE TABLE assistant.links (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            link_key text NOT NULL,
            version integer NOT NULL,
            kind text NOT NULL,
            label text NOT NULL,
            url text NOT NULL,
            description text NOT NULL DEFAULT '',
            aliases text[] NOT NULL DEFAULT '{}',
            doc_key text,
            priority integer NOT NULL DEFAULT 50,
            active boolean NOT NULL DEFAULT true,
            origin text NOT NULL,
            created_by text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (link_key, version)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE assistant.suppressions (
            chunk_key text PRIMARY KEY,
            reason text,
            created_by text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE assistant.releases (
            id bigserial PRIMARY KEY,
            status text NOT NULL,
            parent_id bigint REFERENCES assistant.releases(id),
            note text,
            created_by text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            published_at timestamptz,
            stats jsonb NOT NULL DEFAULT '{}',
            eval_report jsonb
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX one_open_draft ON assistant.releases (status) WHERE status = 'draft'"
    )
    op.execute(
        """
        CREATE TABLE assistant.release_chunks (
            release_id bigint NOT NULL REFERENCES assistant.releases(id) ON DELETE CASCADE,
            chunk_id uuid NOT NULL REFERENCES assistant.chunks(id),
            PRIMARY KEY (release_id, chunk_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE assistant.release_links (
            release_id bigint NOT NULL REFERENCES assistant.releases(id) ON DELETE CASCADE,
            link_id uuid NOT NULL REFERENCES assistant.links(id),
            PRIMARY KEY (release_id, link_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE assistant.settings (
            key text PRIMARY KEY,
            value jsonb NOT NULL,
            updated_by text,
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE assistant.ingestion_runs (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            source_kind text NOT NULL,
            mode text NOT NULL,
            status text NOT NULL,
            payload_hash text,
            release_id bigint,
            requested_by text NOT NULL,
            started_at timestamptz NOT NULL DEFAULT now(),
            finished_at timestamptz,
            stats jsonb,
            warnings jsonb,
            error text,
            trace_id uuid
        )
        """
    )
    op.execute(
        """
        CREATE TABLE assistant.ingestion_events (
            id bigserial PRIMARY KEY,
            run_id uuid REFERENCES assistant.ingestion_runs(id) ON DELETE CASCADE,
            stage text NOT NULL,
            doc_key text,
            chunk_key text,
            action text NOT NULL,
            detail jsonb,
            at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE assistant.api_keys (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            name text UNIQUE NOT NULL,
            key_hash text NOT NULL,
            scopes text[] NOT NULL,
            created_at timestamptz DEFAULT now(),
            last_used_at timestamptz,
            revoked_at timestamptz
        )
        """
    )
    op.execute(
        """
        CREATE TABLE assistant.audit_log (
            id bigserial PRIMARY KEY,
            at timestamptz DEFAULT now(),
            actor text NOT NULL,
            action text NOT NULL,
            target text,
            before jsonb,
            after jsonb,
            trace_id uuid
        )
        """
    )
    op.execute(
        """
        CREATE TABLE assistant.eval_cases (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            question text NOT NULL,
            history jsonb,
            expect jsonb NOT NULL,
            tags text[],
            embedding vector(768),
            created_from_trace uuid,
            active boolean DEFAULT true
        )
        """
    )
    op.execute(
        """
        CREATE TABLE assistant.eval_runs (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            release_id bigint,
            kind text NOT NULL,
            started_at timestamptz DEFAULT now(),
            summary jsonb,
            results jsonb
        )
        """
    )
    op.execute(
        """
        CREATE TABLE assistant.sessions (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            token_hash text UNIQUE NOT NULL,
            ip_hash text,
            ua_hash text,
            created_at timestamptz DEFAULT now(),
            last_seen_at timestamptz,
            expires_at timestamptz NOT NULL,
            turn_count integer DEFAULT 0,
            state jsonb DEFAULT '{}'
        )
        """
    )
    op.execute(
        """
        CREATE TABLE assistant.traces (
            trace_id uuid PRIMARY KEY,
            kind text NOT NULL,
            started_at timestamptz NOT NULL,
            duration_ms integer,
            status text NOT NULL,
            error_code text,
            session_id uuid,
            ip_hash text,
            release_id bigint,
            route text,
            intent text,
            path text,
            provider text,
            model text,
            tier integer,
            attempts integer,
            ttfw_ms integer,
            tokens_in integer,
            tokens_out integer,
            confidence jsonb,
            retrieved jsonb,
            link_map jsonb,
            user_text text,
            answer_text text,
            stages jsonb,
            prompt_sections jsonb,
            flags text[],
            feedback text,
            review jsonb
        )
        """
    )
    op.execute("CREATE INDEX traces_started_at_idx ON assistant.traces (started_at DESC)")
    op.execute(
        "CREATE INDEX traces_session_started_idx ON assistant.traces (session_id, started_at)"
    )
    op.execute("CREATE INDEX traces_flags_idx ON assistant.traces USING gin (flags)")
    op.execute(
        """
        CREATE TABLE assistant.spans (
            id bigserial PRIMARY KEY,
            trace_id uuid NOT NULL,
            span_id text NOT NULL,
            parent_id text,
            name text NOT NULL,
            started_at timestamptz NOT NULL,
            duration_ms integer,
            status text,
            attrs jsonb,
            error text
        )
        """
    )
    op.execute("CREATE INDEX spans_trace_id_idx ON assistant.spans (trace_id)")
    op.execute(
        """
        CREATE TABLE assistant.llm_calls (
            id bigserial PRIMARY KEY,
            trace_id uuid,
            provider text NOT NULL,
            model text NOT NULL,
            tier integer,
            started_at timestamptz NOT NULL,
            ttfw_ms integer,
            duration_ms integer,
            status text NOT NULL,
            http_status integer,
            error_class text,
            tokens_in integer,
            tokens_out integer,
            reasoning_tokens integer,
            est_tokens_in integer,
            reserved_out integer,
            remaining jsonb,
            retry_after_s integer
        )
        """
    )
    op.execute("CREATE INDEX llm_calls_started_at_idx ON assistant.llm_calls (started_at DESC)")
    op.execute(
        "CREATE INDEX llm_calls_model_started_idx ON assistant.llm_calls (model, started_at DESC)"
    )
    op.execute(
        """
        CREATE TABLE assistant.error_events (
            id bigserial PRIMARY KEY,
            at timestamptz DEFAULT now(),
            trace_id uuid,
            level text,
            component text,
            code text,
            message text,
            exc text,
            ctx jsonb
        )
        """
    )
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA assistant FROM PUBLIC")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
                EXECUTE 'REVOKE ALL ON ALL TABLES IN SCHEMA assistant FROM anon';
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
                EXECUTE 'REVOKE ALL ON ALL TABLES IN SCHEMA assistant FROM authenticated';
            END IF;
        END
        $$
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE assistant.error_events")
    op.execute("DROP TABLE assistant.llm_calls")
    op.execute("DROP TABLE assistant.spans")
    op.execute("DROP TABLE assistant.traces")
    op.execute("DROP TABLE assistant.sessions")
    op.execute("DROP TABLE assistant.eval_runs")
    op.execute("DROP TABLE assistant.eval_cases")
    op.execute("DROP TABLE assistant.audit_log")
    op.execute("DROP TABLE assistant.api_keys")
    op.execute("DROP TABLE assistant.ingestion_events")
    op.execute("DROP TABLE assistant.ingestion_runs")
    op.execute("DROP TABLE assistant.settings")
    op.execute("DROP TABLE assistant.release_links")
    op.execute("DROP TABLE assistant.release_chunks")
    op.execute("DROP TABLE assistant.releases")
    op.execute("DROP TABLE assistant.suppressions")
    op.execute("DROP TABLE assistant.links")
    op.execute("DROP TABLE assistant.chunks")
    op.execute("DROP TABLE assistant.documents")
    op.execute("DROP TABLE assistant.sources")
    op.execute("DROP SCHEMA assistant")
