--
-- PostgreSQL database dump
--

\restrict dZZ8MnVQ3St3NBwaek1o161dPJIy4NJNypFswVSgQgh4SCafuADUZVxrLVKHIvV

-- Dumped from database version 15.14 (Debian 15.14-1.pgdg12+1)
-- Dumped by pg_dump version 15.16 (Debian 15.16-0+deb12u1)

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

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: entries; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.entries (
    id text NOT NULL,
    title text NOT NULL,
    link text NOT NULL,
    published timestamp with time zone,
    source text,
    category text,
    content text,
    summarized_at timestamp with time zone,
    uploaded_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.entries OWNER TO postgres;

--
-- Name: news_summaries; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.news_summaries (
    id integer NOT NULL,
    category text NOT NULL,
    headline text NOT NULL,
    facts text NOT NULL,
    article_count integer DEFAULT 1,
    impact_score double precision DEFAULT 0.5,
    generated_at timestamp without time zone DEFAULT now(),
    expires_at timestamp without time zone
);


ALTER TABLE public.news_summaries OWNER TO postgres;

--
-- Name: news_summaries_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.news_summaries_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.news_summaries_id_seq OWNER TO postgres;

--
-- Name: news_summaries_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.news_summaries_id_seq OWNED BY public.news_summaries.id;


--
-- Name: news_summaries id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.news_summaries ALTER COLUMN id SET DEFAULT nextval('public.news_summaries_id_seq'::regclass);


--
-- Name: entries entries_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.entries
    ADD CONSTRAINT entries_pkey PRIMARY KEY (id);


--
-- Name: news_summaries news_summaries_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.news_summaries
    ADD CONSTRAINT news_summaries_pkey PRIMARY KEY (id);


--
-- Name: idx_summaries_category; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_summaries_category ON public.news_summaries USING btree (category);


--
-- Name: idx_summaries_expires; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_summaries_expires ON public.news_summaries USING btree (expires_at);


--
-- Name: idx_summaries_generated; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_summaries_generated ON public.news_summaries USING btree (generated_at DESC);


--
-- Name: TABLE entries; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.entries TO n8n;


--
-- PostgreSQL database dump complete
--

\unrestrict dZZ8MnVQ3St3NBwaek1o161dPJIy4NJNypFswVSgQgh4SCafuADUZVxrLVKHIvV

