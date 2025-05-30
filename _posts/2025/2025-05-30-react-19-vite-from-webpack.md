---
layout: post
title: "React 19 + Vite — what changed from the webpack days"
categories: tech
tags: [react, vite, typescript, devtools]
comments: True
---

I've been building React apps since the `create-react-app` days. Webpack configs, Babel plugins, 45-second cold starts. It was fine — it was all we had. Then Vite happened, and then React 19, and now frontend development feels like a different job. A better one.

<!-- readmore -->

## Leaving CRA behind

`create-react-app` was great when it shipped. Zero config, sensible defaults, you could just build stuff. The problem was it never really grew up. The underlying webpack config was locked away, upgrades were painful, and eventually it just stopped keeping up. The React team officially deprecated it.

The recommended path now is `Vite` (for SPAs) or a meta-framework like Next.js (for SSR). I went with Vite for most projects and haven't looked back.

```bash
npm create vite@latest my-app -- --template react-ts
cd my-app && npm install && npm run dev
```

That's it. Dev server up in under 2 seconds. Hot module replacement that actually works. TypeScript out of the box. No ejecting, no config archaeology.

## Why Vite is actually fast

This is the part that surprised me most once I understood it. `webpack` bundles everything before serving. Even in dev mode, it processes your entire dependency graph upfront. For a medium-sized app that could mean 30-60 seconds on first start.

Vite does something different: it uses native ES modules in the browser during development. Your source files are served as-is (after a quick transform via `esbuild`). The browser handles the module resolution. There's no bundle step.

`esbuild` is written in Go and is 10-100x faster than the JavaScript-based alternatives. Dependency pre-bundling (the thing that handles `node_modules`) runs once and caches. After that, cold start is almost instant.

For production builds, Vite uses `rollup` under the hood — still fast, great tree-shaking, solid output.

## HMR that actually works

Hot module replacement in webpack always felt a bit fragile. Sometimes it worked. Sometimes the page refreshed anyway. Sometimes you had to restart the dev server because state got weird.

Vite's HMR is built around ES modules. When you change a file, only that module and its dependents update. React's fast refresh integrates cleanly — component state is preserved across edits. Change the styling of a component, the state stays. Change the logic, it reloads the component.

In practice, this means you edit code and see the result almost immediately without losing your place in the app. It sounds small. After a week it feels essential.

## The Vite config you actually need

```typescript
// vite.config.ts
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:8080',
        changeOrigin: true,
      },
    },
  },
  build: {
    sourcemap: true,
    rollupOptions: {
      output: {
        manualChunks: {
          vendor: ['react', 'react-dom'],
        },
      },
    },
  },
});
```

That's a full config for a typical app. Alias for `@/` imports, API proxy for dev, source maps in prod, manual chunk splitting. Equivalent webpack config would be several times longer.

## React 19 — what actually changed

React 19 shipped with several things I was excited about and a few I haven't used yet. Let's be honest about which is which.

**Actions** are the headline feature. The concept: async functions that manage state transitions, including pending state, errors, and optimistic updates. The `useActionState` hook wraps this:

```typescript
import { useActionState } from 'react';

async function submitForm(prevState: State, formData: FormData): Promise<State> {
  const result = await api.submit(formData.get('name') as string);
  if (!result.ok) return { error: result.error };
  return { success: true };
}

function MyForm() {
  const [state, action, isPending] = useActionState(submitForm, { error: null });

  return (
    <form action={action}>
      <input name="name" />
      <button disabled={isPending}>
        {isPending ? 'Submitting...' : 'Submit'}
      </button>
      {state.error && <p>{state.error}</p>}
    </form>
  );
}
```

Less boilerplate than the `useState` + `useEffect` + manual loading state pattern. I've adopted this for forms.

**`use()`** is a hook that can unwrap Promises and Context. The Promise version is what gets people excited:

```typescript
import { use, Suspense } from 'react';

function UserProfile({ userPromise }: { userPromise: Promise<User> }) {
  const user = use(userPromise); // suspends until resolved
  return <div>{user.name}</div>;
}

function App() {
  const userPromise = fetchUser(userId); // called outside component

  return (
    <Suspense fallback={<Spinner />}>
      <UserProfile userPromise={userPromise} />
    </Suspense>
  );
}
```

Note: the Promise needs to be created outside the component (or memoized), otherwise you re-create it on every render and it never resolves. This trips people up.

**`useOptimistic`** handles optimistic UI properly:

```typescript
const [optimisticItems, addOptimisticItem] = useOptimistic(
  items,
  (state, newItem) => [...state, { ...newItem, sending: true }],
);
```

Update the UI immediately, roll back if the server request fails. Way cleaner than managing this manually.

**Server Components** — I haven't used these in a Vite SPA context. They're Next.js territory. For a plain Vite app, this doesn't apply. Don't let the hype confuse the picture: React 19 is a great upgrade for SPAs without touching RSC at all.

## The React Compiler

React 19 ships with the experimental React Compiler (formerly React Forget). The idea: the compiler automatically adds the equivalent of `useMemo`, `useCallback`, and `memo` where needed. You write plain React, the compiler figures out the memoization.

```typescript
// vite.config.ts — enabling the compiler
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [
    react({
      babel: {
        plugins: [['babel-plugin-react-compiler', {}]],
      },
    }),
  ],
});
```

I've tried it on a couple of projects. For most code it works as advertised. It's still opt-in and marked experimental. If you're writing idiomatic React (no mutation of props, no side effects outside effects), it handles things well. Worth trying — you can always disable it per component with `'use no memo'`.

## Plugin ecosystem

Webpack plugins → Vite plugins. Most of the things you relied on have equivalents:

- `@vitejs/plugin-react` — React + Fast Refresh
- `vite-plugin-svgr` — SVG as React components
- `vite-tsconfig-paths` — TypeScript path aliases from `tsconfig`
- `vite-plugin-checker` — TypeScript type checking in dev (Vite doesn't type-check by default — it just strips types with esbuild)
- `rollup-plugin-visualizer` — bundle analysis

That last one is worth calling out: Vite doesn't run `tsc` during dev. This makes it faster but means type errors don't break the dev server. You need either `vite-plugin-checker` or `tsc --noEmit` in your CI pipeline. Don't skip this — silent type errors will bite you.

```json
// package.json
{
  "scripts": {
    "dev": "vite",
    "build": "tsc --noEmit && vite build",
    "typecheck": "tsc --noEmit"
  }
}
```

Run `tsc --noEmit` as part of `build`. Type errors block the production build but don't slow down dev.

## Environment variables

Webpack had `process.env.REACT_APP_*`. Vite uses `import.meta.env.VITE_*`. The prefix requirement is intentional — anything without `VITE_` stays on the server side and isn't exposed to the browser bundle.

```typescript
// In your code
const apiUrl = import.meta.env.VITE_API_URL;

// TypeScript support — create src/vite-env.d.ts
/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_URL: string;
  readonly VITE_CHAIN_ID: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
```

With this, `import.meta.env.VITE_API_URL` is typed and autocompleted. Much nicer than `process.env.REACT_APP_FOO` (which TypeScript types as `string | undefined` everywhere).

## Build times, real numbers

On a mid-sized React app (about 80 components, `react-router`, a UI library, some charting):

- webpack/CRA cold start: ~45 seconds
- Vite cold start: ~2 seconds
- webpack HMR: 1-3 seconds (sometimes full refresh)
- Vite HMR: under 100ms

Production builds are closer — webpack and Vite both take 20-40 seconds depending on optimizations. The dev experience difference is where Vite wins decisively.

## Should you migrate existing projects?

If the project is actively developed: yes, eventually. The migration is mostly mechanical — update config files, rename env vars, swap a few imports. The React 18 → 19 upgrade is separate and needs its own attention (`ReactDOM.createRoot` was already 18, so if you're on 18 you're most of the way there).

If it's stable and rarely touched: probably not worth the disruption. `webpack` still works. CRA apps still build. Don't migrate for the sake of it.

For any new project, there's no reason to start with webpack. Vite is the default now. The ecosystem has fully moved on.

3h4x