--
-- PostgreSQL database dump
--

\restrict mgisYKGtm52Jg8SpIesLQFFXid93OgkpQ3XPwg65hDqEkIo0d1XSbiTLuVGyp20

-- Dumped from database version 16.13
-- Dumped by pg_dump version 16.13

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: public; Type: SCHEMA; Schema: -; Owner: -
--

-- *not* creating schema, since initdb creates it


--
-- Name: agentrunstatus; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.agentrunstatus AS ENUM (
    'STARTED',
    'COMPLETED',
    'FAILED'
);


--
-- Name: blogsessionstatus; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.blogsessionstatus AS ENUM (
    'QUEUED',
    'PROCESSING',
    'AWAITING_OUTLINE_REVIEW',
    'AWAITING_FINAL_REVIEW',
    'COMPLETED',
    'FAILED',
    'CANCELLED'
);


--
-- Name: budgetentrytype; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.budgetentrytype AS ENUM (
    'GRANT',
    'RESERVE',
    'COMMIT',
    'RELEASE',
    'ADJUSTMENT'
);


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: agent_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_runs (
    id integer NOT NULL,
    blog_session_id integer NOT NULL,
    stage_name character varying(100) NOT NULL,
    agent_name character varying(100) NOT NULL,
    model_name character varying(100) NOT NULL,
    status character varying(50) DEFAULT 'STARTED'::character varying NOT NULL,
    prompt_tokens integer DEFAULT 0 NOT NULL,
    completion_tokens integer DEFAULT 0 NOT NULL,
    total_tokens integer DEFAULT 0 NOT NULL,
    cost_usd numeric(12,8) DEFAULT '0'::numeric NOT NULL,
    latency_ms integer,
    output_snapshot jsonb,
    error_message text,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    completed_at timestamp with time zone
);


--
-- Name: agent_runs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.agent_runs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: agent_runs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.agent_runs_id_seq OWNED BY public.agent_runs.id;


--
-- Name: alembic_version; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alembic_version (
    version_num character varying(32) NOT NULL
);


--
-- Name: auth_users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.auth_users (
    id integer NOT NULL,
    email character varying(255) NOT NULL,
    password_hash character varying(255) NOT NULL,
    display_name character varying(255),
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    last_login_at timestamp with time zone
);


--
-- Name: auth_users_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.auth_users_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: auth_users_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.auth_users_id_seq OWNED BY public.auth_users.id;


--
-- Name: blog_sessions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.blog_sessions (
    id integer NOT NULL,
    user_id integer NOT NULL,
    topic character varying(500) NOT NULL,
    audience character varying(255) DEFAULT 'general readers'::character varying NOT NULL,
    tone character varying(100) DEFAULT 'professional'::character varying NOT NULL,
    status character varying(50) DEFAULT 'QUEUED'::character varying NOT NULL,
    current_stage character varying(50),
    adk_session_id character varying(255),
    invocation_id character varying(255),
    confirmation_request_id character varying(255),
    outline_data jsonb,
    final_content text,
    budget_reserved_tokens integer DEFAULT 0 NOT NULL,
    budget_spent_tokens integer DEFAULT 0 NOT NULL,
    budget_reserved_usd numeric(12,8) DEFAULT '0'::numeric NOT NULL,
    budget_spent_usd numeric(12,8) DEFAULT '0'::numeric NOT NULL,
    reap_count integer DEFAULT 0 NOT NULL,
    idempotency_key character varying(255),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    completed_at timestamp with time zone,
    failed_at timestamp with time zone,
    failure_reason text
);


--
-- Name: blog_sessions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.blog_sessions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: blog_sessions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.blog_sessions_id_seq OWNED BY public.blog_sessions.id;


--
-- Name: budget_accounts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.budget_accounts (
    id integer NOT NULL,
    user_id integer NOT NULL,
    balance_usd numeric(12,8) DEFAULT '0'::numeric NOT NULL,
    reserved_usd numeric(12,8) DEFAULT '0'::numeric NOT NULL,
    total_granted_usd numeric(12,8) DEFAULT '0'::numeric NOT NULL,
    total_spent_usd numeric(12,8) DEFAULT '0'::numeric NOT NULL,
    last_updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: budget_accounts_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.budget_accounts_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: budget_accounts_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.budget_accounts_id_seq OWNED BY public.budget_accounts.id;


--
-- Name: budget_ledger; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.budget_ledger (
    id integer NOT NULL,
    user_id integer NOT NULL,
    blog_session_id integer,
    agent_run_id integer,
    entry_type character varying(50) NOT NULL,
    tokens integer DEFAULT 0 NOT NULL,
    amount_usd numeric(12,8) DEFAULT '0'::numeric NOT NULL,
    note character varying(255),
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: budget_ledger_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.budget_ledger_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: budget_ledger_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.budget_ledger_id_seq OWNED BY public.budget_ledger.id;


--
-- Name: research_sources; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.research_sources (
    id integer NOT NULL,
    user_id integer NOT NULL,
    blog_session_id integer NOT NULL,
    title character varying(500) NOT NULL,
    url character varying(2048) NOT NULL,
    content text,
    score numeric(5,4) DEFAULT '0'::numeric NOT NULL,
    topic character varying(500),
    collected_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: session_leases; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.session_leases (
    id integer NOT NULL,
    blog_session_id integer NOT NULL,
    lease_owner character varying(255) NOT NULL,
    lease_expires_at timestamp with time zone,
    lease_version integer DEFAULT 1 NOT NULL,
    last_heartbeat_at timestamp with time zone,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    ended_at timestamp with time zone,
    release_reason character varying(50)
);


--
-- Name: session_leases_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.session_leases_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: session_leases_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.session_leases_id_seq OWNED BY public.session_leases.id;


--
-- Name: session_reservations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.session_reservations (
    id integer NOT NULL,
    user_id integer NOT NULL,
    blog_session_id integer NOT NULL,
    reserved_usd numeric(12,8) NOT NULL,
    reserved_tokens integer NOT NULL,
    actual_usd numeric(12,8) DEFAULT '0'::numeric NOT NULL,
    actual_tokens integer DEFAULT 0 NOT NULL,
    status character varying(20) DEFAULT 'ACTIVE'::character varying NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: session_reservations_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.session_reservations_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: session_reservations_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.session_reservations_id_seq OWNED BY public.session_reservations.id;


--
-- Name: agent_runs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_runs ALTER COLUMN id SET DEFAULT nextval('public.agent_runs_id_seq'::regclass);


--
-- Name: auth_users id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_users ALTER COLUMN id SET DEFAULT nextval('public.auth_users_id_seq'::regclass);


--
-- Name: blog_sessions id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.blog_sessions ALTER COLUMN id SET DEFAULT nextval('public.blog_sessions_id_seq'::regclass);


--
-- Name: budget_accounts id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.budget_accounts ALTER COLUMN id SET DEFAULT nextval('public.budget_accounts_id_seq'::regclass);


--
-- Name: budget_ledger id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.budget_ledger ALTER COLUMN id SET DEFAULT nextval('public.budget_ledger_id_seq'::regclass);


--
-- Name: session_leases id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.session_leases ALTER COLUMN id SET DEFAULT nextval('public.session_leases_id_seq'::regclass);


--
-- Name: session_reservations id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.session_reservations ALTER COLUMN id SET DEFAULT nextval('public.session_reservations_id_seq'::regclass);


--
-- Name: agent_runs agent_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_runs
    ADD CONSTRAINT agent_runs_pkey PRIMARY KEY (id);


--
-- Name: alembic_version alembic_version_pkc; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alembic_version
    ADD CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num);


--
-- Name: auth_users auth_users_email_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_users
    ADD CONSTRAINT auth_users_email_key UNIQUE (email);


--
-- Name: auth_users auth_users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_users
    ADD CONSTRAINT auth_users_pkey PRIMARY KEY (id);


--
-- Name: blog_sessions blog_sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.blog_sessions
    ADD CONSTRAINT blog_sessions_pkey PRIMARY KEY (id);


--
-- Name: budget_accounts budget_accounts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.budget_accounts
    ADD CONSTRAINT budget_accounts_pkey PRIMARY KEY (id);


--
-- Name: budget_ledger budget_ledger_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.budget_ledger
    ADD CONSTRAINT budget_ledger_pkey PRIMARY KEY (id);


--
-- Name: session_reservations session_reservations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.session_reservations
    ADD CONSTRAINT session_reservations_pkey PRIMARY KEY (id);


--
-- Name: agent_runs uq_agent_runs_session_stage; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_runs
    ADD CONSTRAINT uq_agent_runs_session_stage UNIQUE (blog_session_id, stage_name);


--
-- Name: blog_sessions uq_blog_sessions_idempotency; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.blog_sessions
    ADD CONSTRAINT uq_blog_sessions_idempotency UNIQUE (user_id, idempotency_key);


--
-- Name: budget_accounts uq_budget_accounts_user_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.budget_accounts
    ADD CONSTRAINT uq_budget_accounts_user_id UNIQUE (user_id);


--
-- Name: session_reservations uq_session_reservations_session; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.session_reservations
    ADD CONSTRAINT uq_session_reservations_session UNIQUE (blog_session_id);


--
-- Name: ix_agent_runs_session; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_agent_runs_session ON public.agent_runs USING btree (blog_session_id);


--
-- Name: ix_auth_users_email; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_auth_users_email ON public.auth_users USING btree (email);


--
-- Name: ix_blog_sessions_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_blog_sessions_status ON public.blog_sessions USING btree (status);


--
-- Name: ix_blog_sessions_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_blog_sessions_user_id ON public.blog_sessions USING btree (user_id);


--
-- Name: ix_budget_accounts_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_budget_accounts_user_id ON public.budget_accounts USING btree (user_id);


--
-- Name: ix_budget_ledger_session; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_budget_ledger_session ON public.budget_ledger USING btree (blog_session_id);


--
-- Name: ix_budget_ledger_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_budget_ledger_user_id ON public.budget_ledger USING btree (user_id);


--
-- Name: ix_research_sources_session; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_research_sources_session ON public.research_sources USING btree (blog_session_id);


--
-- Name: ix_research_sources_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_research_sources_user ON public.research_sources USING btree (user_id);


--
-- Name: ix_session_leases_ended; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_session_leases_ended ON public.session_leases USING btree (ended_at);


--
-- Name: ix_session_leases_owner; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_session_leases_owner ON public.session_leases USING btree (lease_owner);


--
-- Name: ix_session_leases_session; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_session_leases_session ON public.session_leases USING btree (blog_session_id);


--
-- Name: ix_session_leases_started; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_session_leases_started ON public.session_leases USING btree (started_at);


--
-- Name: ix_session_reservations_session; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_session_reservations_session ON public.session_reservations USING btree (blog_session_id);


--
-- Name: ix_session_reservations_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_session_reservations_user ON public.session_reservations USING btree (user_id);


--
-- Name: agent_runs agent_runs_blog_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_runs
    ADD CONSTRAINT agent_runs_blog_session_id_fkey FOREIGN KEY (blog_session_id) REFERENCES public.blog_sessions(id) ON DELETE CASCADE;


--
-- Name: blog_sessions blog_sessions_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.blog_sessions
    ADD CONSTRAINT blog_sessions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.auth_users(id) ON DELETE CASCADE;


--
-- Name: budget_accounts budget_accounts_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.budget_accounts
    ADD CONSTRAINT budget_accounts_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.auth_users(id) ON DELETE CASCADE;


--
-- Name: budget_ledger budget_ledger_agent_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.budget_ledger
    ADD CONSTRAINT budget_ledger_agent_run_id_fkey FOREIGN KEY (agent_run_id) REFERENCES public.agent_runs(id) ON DELETE SET NULL;


--
-- Name: budget_ledger budget_ledger_blog_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.budget_ledger
    ADD CONSTRAINT budget_ledger_blog_session_id_fkey FOREIGN KEY (blog_session_id) REFERENCES public.blog_sessions(id) ON DELETE SET NULL;


--
-- Name: budget_ledger budget_ledger_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.budget_ledger
    ADD CONSTRAINT budget_ledger_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.auth_users(id) ON DELETE CASCADE;


--
-- Name: research_sources fk_research_sources_session; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.research_sources
    ADD CONSTRAINT fk_research_sources_session FOREIGN KEY (blog_session_id) REFERENCES public.blog_sessions(id) ON DELETE CASCADE;


--
-- Name: research_sources fk_research_sources_user; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.research_sources
    ADD CONSTRAINT fk_research_sources_user FOREIGN KEY (user_id) REFERENCES public.auth_users(id) ON DELETE CASCADE;


--
-- Name: session_leases fk_session_leases_session; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.session_leases
    ADD CONSTRAINT fk_session_leases_session FOREIGN KEY (blog_session_id) REFERENCES public.blog_sessions(id) ON DELETE CASCADE;


--
-- Name: session_reservations session_reservations_blog_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.session_reservations
    ADD CONSTRAINT session_reservations_blog_session_id_fkey FOREIGN KEY (blog_session_id) REFERENCES public.blog_sessions(id) ON DELETE CASCADE;


--
-- Name: session_reservations session_reservations_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.session_reservations
    ADD CONSTRAINT session_reservations_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.auth_users(id) ON DELETE CASCADE;


--
-- Name: SCHEMA public; Type: ACL; Schema: -; Owner: -
--

REVOKE USAGE ON SCHEMA public FROM PUBLIC;
GRANT ALL ON SCHEMA public TO PUBLIC;


--
-- PostgreSQL database dump complete
--

\unrestrict mgisYKGtm52Jg8SpIesLQFFXid93OgkpQ3XPwg65hDqEkIo0d1XSbiTLuVGyp20

