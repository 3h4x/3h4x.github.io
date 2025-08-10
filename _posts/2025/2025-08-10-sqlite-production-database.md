---
layout: post
title: "SQLite as the production database — when it's actually fine"
categories: tech
tags: [sqlite, database, tools]
comments: True
---

Every time someone mentions using SQLite in production, the response is predictable: "it doesn't scale," "no concurrent writes," "use Postgres." And they're right — if you're building the next Twitter. But most of us aren't. Most of us are running apps that serve hundreds of requests per minute, not thousands per second. And for that, SQLite is not just fine — it's better.

<!-- readmore -->

## Why I switched

I was running PostgreSQL on my VPS for three apps. Combined, they had maybe 50,000 rows of data total. Postgres was using 150MB of RAM just idling. It needed vacuuming, connection pooling, backup scripts, and occasional "why is this query plan terrible" investigations.

Then I rewrote one app to use SQLite and realized: the data lives in a single file. Backup is `cp`. There's no server process. The database starts when your app starts. No connection strings, no auth, no port conflicts.

That was enough for me to try it properly. A few months later, I'm not going back.

## The performance question

Let's get this out of the way:

```
SQLite can handle:
- ~50,000 INSERTs/second (with WAL mode)
- ~500,000 SELECTs/second for simple queries
- Databases up to 281 terabytes (theoretical limit)
```

If your Express app handles 100 requests/second and each request does 2-3 queries, you're at maybe 300 queries/second. SQLite won't even notice.

The real limitation is **concurrent writes**. SQLite uses a single-writer model — only one write transaction at a time. For read-heavy workloads (which most web apps are), this doesn't matter. For write-heavy workloads, you'll hit contention.

## WAL mode is mandatory

```javascript
const db = new Database('./data/app.db');
db.pragma('journal_mode = WAL');
db.pragma('busy_timeout = 5000');
db.pragma('synchronous = NORMAL');
db.pragma('foreign_keys = ON');
db.pragma('cache_size = -32000'); // 32MB page cache
db.pragma('temp_store = MEMORY');
```

WAL (Write-Ahead Logging) mode changes everything. Without it, a write takes an exclusive lock on the entire file — all reads block. With WAL, writers append to a separate log file. Readers continue reading the last consistent snapshot. They never block each other.

The mechanics: WAL mode maintains a `.db-wal` file alongside the main database. Writes go there first. Reads check the WAL for recent pages, fall back to the main file for the rest. Periodically (or on demand), SQLite checkpoints the WAL back into the main file. This is automatic — you don't manage it.

`busy_timeout = 5000` is equally important. Without it, a second writer gets `SQLITE_BUSY` immediately and your app throws. With 5000ms timeout, SQLite retries for up to 5 seconds before giving up. This resolves almost all write contention in practice for typical web workloads. Set it. Always.

`synchronous = NORMAL` is a safe middle ground. `FULL` fsync on every write — safe but slow. `OFF` — fast but data loss on power failure. `NORMAL` syncs at safe points (WAL checkpoints), which is fast and durable enough for most applications.

`cache_size = -32000` sets the page cache to 32MB (negative values mean kilobytes). SQLite's default is 2MB, which is tiny. More cache means fewer disk reads. For any database over a few MB, bump this up.

## better-sqlite3 vs sql.js — which one

For Node.js there are two main options. They're very different.

**better-sqlite3** is a native addon. It wraps the C SQLite library directly. All operations are synchronous (which sounds wrong but is actually great for SQLite — no async overhead, no callbacks, simpler code).

```javascript
import Database from 'better-sqlite3';

const db = new Database('./app.db');
db.pragma('journal_mode = WAL');
db.pragma('busy_timeout = 5000');

// Synchronous — no await, no callbacks
const user = db.prepare('SELECT * FROM users WHERE id = ?').get(userId);
const users = db.prepare('SELECT * FROM users WHERE active = 1').all();

// Transactions are first-class
const transfer = db.transaction((from, to, amount) => {
  db.prepare('UPDATE accounts SET balance = balance - ? WHERE id = ?').run(amount, from);
  db.prepare('UPDATE accounts SET balance = balance + ? WHERE id = ?').run(amount, to);
});

transfer(accountA, accountB, 100);
```

**sql.js** is SQLite compiled to WebAssembly. It runs entirely in JavaScript — no native compilation, works in browsers, works anywhere. The trade-off: it loads the whole database into memory. Every write requires serializing back to a `Uint8Array` if you want to persist it. It's not for server-side production databases.

Use `better-sqlite3` for server-side apps. Use `sql.js` if you need SQLite in a browser, Electron renderer, or Cloudflare Workers (with some adapter magic).

One gotcha with `better-sqlite3`: it's a native module, so it needs to be compiled for your platform. In practice this means `npm install` might take a few seconds longer. In Docker, make sure you're building for the right architecture. If you hit issues, `npm rebuild better-sqlite3` usually fixes it.

## Migration patterns

SQLite doesn't have `ALTER COLUMN`. This trips people up. You can add columns, rename columns (SQLite 3.25+), and drop columns (SQLite 3.35+). But changing a column type or adding constraints to existing columns requires the copy-table approach.

For simple additive migrations, it's fine:

```javascript
// Check if column exists before adding
const columns = db.pragma('table_info(users)');
const hasColumn = columns.some(c => c.name === 'created_at');

if (!hasColumn) {
  db.exec('ALTER TABLE users ADD COLUMN created_at INTEGER DEFAULT 0');
}
```

For anything more complex, the pattern is: create new table, copy data, drop old, rename new.

```sql
-- The SQLite way to change a column type or add constraints
BEGIN;
CREATE TABLE users_new (
  id INTEGER PRIMARY KEY,
  email TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  created_at INTEGER NOT NULL DEFAULT (unixepoch())
);
INSERT INTO users_new SELECT id, email, name, created_at FROM users;
DROP TABLE users;
ALTER TABLE users_new RENAME TO users;
COMMIT;
```

I use a simple version table and migration runner rather than a full ORM. Something like:

```javascript
const migrations = [
  {
    version: 1,
    up: `CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT UNIQUE, name TEXT)`,
  },
  {
    version: 2,
    up: `ALTER TABLE users ADD COLUMN created_at INTEGER DEFAULT 0`,
  },
  {
    version: 3,
    up: `CREATE INDEX idx_users_email ON users (email)`,
  },
];

function runMigrations(db) {
  db.exec(`CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY)`);

  const current = db.prepare('SELECT MAX(version) as v FROM schema_version').get().v ?? 0;

  for (const migration of migrations) {
    if (migration.version <= current) continue;

    db.transaction(() => {
      db.exec(migration.up);
      db.prepare('INSERT INTO schema_version (version) VALUES (?)').run(migration.version);
    })();

    console.log(`Applied migration ${migration.version}`);
  }
}
```

Runs at startup, idempotent, no external tool required. For a side project, this is plenty.

## Backup is a file copy

```bash
# Hot backup while the app is running
sqlite3 /data/app.db ".backup /backups/app_$(date +%Y%m%d_%H%M%S).db"
```

That's a consistent, point-in-time backup. No `pg_dump`, no credentials, no "is the backup valid" anxiety. The backup is a regular SQLite file — open it and query it to verify.

The `.backup` command uses SQLite's online backup API. It's safe while the app is running with WAL mode. It locks briefly at the start and end, but reads and writes continue normally in between. For a 50MB database, the whole thing takes under a second.

I run this on a cron every hour and keep the 100 most recent backups. That's 4 days of hourly snapshots at basically zero cost.

## What I miss from Postgres

**Full-text search.** SQLite has FTS5, but Postgres's `tsvector` + `tsquery` is more mature and flexible. For basic search, FTS5 works. For anything involving ranking, stemming across languages, or complex queries — Postgres wins.

**JSON queries.** SQLite has `json_extract()` and it works, but Postgres's `jsonb` operators are more ergonomic. If your app stores a lot of semi-structured data, Postgres is a better fit.

**Migrations tooling.** The ecosystem around Postgres migrations (Prisma, Knex, TypeORM) is deeper. SQLite support exists but it's always the second-class citizen. You'll end up writing more by hand.

**Window functions.** SQLite added these in 3.25.0 (2018), so it's mostly caught up. But complex analytic queries can still hit edge cases where Postgres handles them better.

## When to NOT use SQLite

- Multiple servers need to access the same database (SQLite is file-based, no network protocol)
- Write-heavy workloads (>1000 writes/second sustained)
- You need replication, read replicas, or point-in-time recovery
- Your team expects Postgres and changing that isn't worth the friction
- You're deploying to a platform without persistent storage (Heroku, most serverless)

## When it's the right call

- Single-server apps (most side projects, internal tools)
- Read-heavy workloads with occasional writes
- Apps where operational simplicity matters more than theoretical scalability
- Prototypes that might become production (they always do)
- Anything where "the database is a file I can inspect with DB Browser" is a feature, not a limitation

I'm running three apps on SQLite now. The largest database is 45MB. Backups are a cron job. There's no database server to monitor, patch, or restart. And the apps start in 200ms instead of waiting for a Postgres connection.

The boring choice is often the right one.

3h4x
