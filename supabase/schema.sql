create extension if not exists pgcrypto;
create extension if not exists vector;

create table if not exists profiles (
  id uuid primary key default gen_random_uuid(),
  user_id uuid unique not null,
  name text not null,
  age integer,
  gender text,
  height numeric(5,2),
  weight numeric(5,2),
  goal text,
  activity_level text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists conversations (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  title text not null default 'Cuộc trò chuyện mới',
  created_at timestamptz not null default now()
);

create table if not exists messages (
  id uuid primary key default gen_random_uuid(),
  conversation_id uuid not null references conversations(id) on delete cascade,
  user_id uuid not null,
  role text not null check (role in ('user','assistant','system')),
  content text not null,
  created_at timestamptz not null default now()
);

create table if not exists knowledge_documents (
  id uuid primary key default gen_random_uuid(),
  title text not null,
  source text,
  content text not null,
  created_at timestamptz not null default now()
);

create table if not exists knowledge_chunks (
  id uuid primary key default gen_random_uuid(),
  document_id uuid references knowledge_documents(id) on delete cascade,
  chunk_text text not null,
  embedding vector(384),
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists idx_messages_conversation on messages(conversation_id);
create index if not exists idx_messages_user on messages(user_id);
create index if not exists idx_conversations_user on conversations(user_id);

-- Production RAG migration path:
-- 1) parse the TXT knowledge base into knowledge_documents / knowledge_chunks;
-- 2) generate embeddings matching vector(384);
-- 3) replace local lexical retrieval with pgvector cosine similarity;
-- 4) optionally add an HNSW index when the dataset becomes large.
