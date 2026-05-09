# Vercel Deploy Runbook — BlogifyAI Frontend

## 1. Create Vercel Project

1. Go to [vercel.com/new](https://vercel.com/new) and import the GitHub repo `iarpitchauhan/blogify-ai`
2. **Root Directory**: set to `frontend`
3. **Framework Preset**: Vite (auto-detected)
4. **Build Command**: `pnpm build`
5. **Output Directory**: `dist`
6. **Install Command**: `pnpm install --frozen-lockfile`

---

## 2. Set Environment Variables

In Vercel → Project → Settings → Environment Variables:

| Variable | Value | Environments |
|---|---|---|
| `VITE_API_BASE_URL` | `https://api.blogifyai.arpitdev.site` | Production |
| `VITE_API_BASE_URL` | `http://localhost:8000` | Preview, Development |

> [!IMPORTANT]
> Vite only embeds env vars prefixed with `VITE_` into the bundle at build time.
> The `VITE_API_BASE_URL` variable must be set **before** Vercel triggers a build.

---

## 3. Configure Custom Domain (Optional)

In Vercel → Project → Settings → Domains, add:
- `blogifyai.arpitdev.site`

Point a CNAME in your DNS provider:
```
blogifyai.arpitdev.site  →  cname.vercel-dns.com
```

---

## 4. Enable Auto-Deploy

Vercel auto-deploys on every push to `main` by default. No extra configuration needed.

The GitHub Actions `CI` workflow runs `pnpm build` (with `VITE_API_BASE_URL` set to the
production URL) to validate the build before Vercel deploys.

---

## 5. CORS Configuration

The backend's `CORS_ORIGINS` secret must include the Vercel domain:

```json
"CORS_ORIGINS": "[\"https://blogifyai.arpitdev.site\"]"
```

If you use Vercel preview deployments (feature branches), add `*.vercel.app` to CORS
or use a regex pattern in the FastAPI CORS middleware.

---

## 6. Verify

After deploy:
1. Visit `https://blogifyai.arpitdev.site`
2. Log in — requests should go to `https://api.blogifyai.arpitdev.site`
3. Check browser DevTools → Network tab: all API calls should use the absolute URL
4. Confirm no CORS errors in the console
