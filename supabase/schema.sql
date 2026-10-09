-- Run in Supabase SQL Editor. Supabase Auth owns auth.users; do not store passwords yourself.
create extension if not exists pgcrypto;
create extension if not exists vector;

create table if not exists public.profiles (
 id uuid primary key default gen_random_uuid(),
 user_id uuid not null unique references auth.users(id) on delete cascade,
 name text not null,
 age integer check (age between 1 and 120),
 gender text,
 height numeric(5,2) check (height > 0 and height <= 260),
 weight numeric(5,2) check (weight > 0 and weight <= 500),
 goal text,
 activity_level text,
 created_at timestamptz not null default now(),
 updated_at timestamptz not null default now()
);

create table if not exists public.conversations (
 id uuid primary key default gen_random_uuid(),
 user_id uuid not null references auth.users(id) on delete cascade,
 title text not null default 'Cuộc trò chuyện mới',
 created_at timestamptz not null default now()
);

create table if not exists public.messages (
 id uuid primary key default gen_random_uuid(),
 conversation_id uuid not null references public.conversations(id) on delete cascade,
 user_id uuid not null references auth.users(id) on delete cascade,
 role text not null check (role in ('user','assistant','system')),
 content text not null check (length(content) <= 20000),
 created_at timestamptz not null default now()
);

create table if not exists public.knowledge_documents (
 id uuid primary key default gen_random_uuid(),
 title text not null,
 source text,
 content text not null,
 created_at timestamptz not null default now()
);

create table if not exists public.knowledge_chunks (
 id uuid primary key default gen_random_uuid(),
 document_id uuid references public.knowledge_documents(id) on delete cascade,
 title text not null default 'Tài liệu kiến thức',
 source text,
 chunk_text text not null,
 embedding vector(1536),
 metadata jsonb not null default '{}'::jsonb,
 created_at timestamptz not null default now()
);

create index if not exists idx_messages_conversation on public.messages(conversation_id, created_at);
create index if not exists idx_messages_user on public.messages(user_id);
create index if not exists idx_conversations_user on public.conversations(user_id, created_at desc);
create index if not exists idx_knowledge_chunks_embedding
 on public.knowledge_chunks using hnsw (embedding vector_cosine_ops);

alter table public.profiles enable row level security;
alter table public.conversations enable row level security;
alter table public.messages enable row level security;
alter table public.knowledge_documents enable row level security;
alter table public.knowledge_chunks enable row level security;

drop policy if exists "Users manage own profile" on public.profiles;
create policy "Users manage own profile" on public.profiles for all to authenticated
 using (auth.uid() = user_id) with check (auth.uid() = user_id);

drop policy if exists "Users manage own conversations" on public.conversations;
create policy "Users manage own conversations" on public.conversations for all to authenticated
 using (auth.uid() = user_id) with check (auth.uid() = user_id);

drop policy if exists "Users read own messages" on public.messages;
create policy "Users read own messages" on public.messages for select to authenticated
 using (auth.uid() = user_id);
drop policy if exists "Users add own messages" on public.messages;
create policy "Users add own messages" on public.messages for insert to authenticated
 with check (auth.uid() = user_id);

drop policy if exists "Authenticated read knowledge documents" on public.knowledge_documents;
create policy "Authenticated read knowledge documents" on public.knowledge_documents for select to authenticated using (true);
drop policy if exists "Authenticated read knowledge chunks" on public.knowledge_chunks;
create policy "Authenticated read knowledge chunks" on public.knowledge_chunks for select to authenticated using (true);

create or replace function public.match_knowledge_chunks(
 query_embedding vector(1536), match_count int default 5
)
returns table(id uuid, title text, source text, chunk_text text, metadata jsonb, similarity float)
language sql stable
as $$
 select kc.id, kc.title, kc.source, kc.chunk_text, kc.metadata,
        1 - (kc.embedding <=> query_embedding) as similarity
 from public.knowledge_chunks kc
 where kc.embedding is not null
 order by kc.embedding <=> query_embedding
 limit greatest(1, least(match_count, 10));
$$;
