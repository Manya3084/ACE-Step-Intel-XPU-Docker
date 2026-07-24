#!/usr/bin/env python3
"""Make ace-step-ui auth optional for local / LAN Docker installs.

Rewrites authMiddleware so missing/invalid Bearer tokens still proceed as a
stable local user (id=local-docker-user). Keeps real JWT users when present.

Set OPEN_LOCAL_AUTH=false to restore strict JWT checks.
"""
from pathlib import Path
import re

LOCAL_ID = "local-docker-user"
LOCAL_NAME = "local"

auth_mw = Path("server/src/middleware/auth.ts")
if not auth_mw.is_file():
    raise SystemExit("auth.ts not found")

auth_mw.write_text(
    '''import { Request, Response, NextFunction } from \'express\';
import jwt from \'jsonwebtoken\';
import { config } from \'../config/index.js\';
import { pool } from \'../db/pool.js\';

export interface AuthenticatedUser {
  id: string;
  username: string;
  isAdmin?: boolean;
}

export interface AuthenticatedRequest extends Request {
  user?: AuthenticatedUser;
}

/** Local Docker default: skip JWT. Set OPEN_LOCAL_AUTH=false to enforce tokens. */
function openLocalAuth(): boolean {
  const v = (process.env.OPEN_LOCAL_AUTH || \'true\').toLowerCase();
  return v !== \'false\' && v !== \'0\' && v !== \'no\' && v !== \'off\';
}

const LOCAL_USER: AuthenticatedUser = {
  id: \'local-docker-user\',
  username: \'local\',
  isAdmin: true,
};

function tryDecode(authHeader: string | undefined): AuthenticatedUser | null {
  if (!authHeader || !authHeader.startsWith(\'Bearer \')) return null;
  const token = authHeader.substring(7);
  try {
    return jwt.verify(token, config.jwt.secret) as AuthenticatedUser;
  } catch {
    return null;
  }
}

export function authMiddleware(
  req: AuthenticatedRequest,
  res: Response,
  next: NextFunction
): void {
  const decoded = tryDecode(req.headers.authorization);
  if (decoded) {
    req.user = decoded;
    next();
    return;
  }

  if (openLocalAuth()) {
    req.user = { ...LOCAL_USER };
    next();
    return;
  }

  res.status(401).json({ error: \'No token provided\' });
}

export function optionalAuthMiddleware(
  req: AuthenticatedRequest,
  _res: Response,
  next: NextFunction
): void {
  const decoded = tryDecode(req.headers.authorization);
  req.user = decoded || (openLocalAuth() ? { ...LOCAL_USER } : undefined);
  next();
}

export async function adminMiddleware(
  req: AuthenticatedRequest,
  res: Response,
  next: NextFunction
): Promise<void> {
  const decoded = tryDecode(req.headers.authorization);

  if (decoded) {
    try {
      const result = await pool.query(\'SELECT is_admin FROM users WHERE id = ?\', [decoded.id]);
      if (result.rows.length === 0 || !result.rows[0].is_admin) {
        if (openLocalAuth()) {
          req.user = { ...LOCAL_USER };
          next();
          return;
        }
        res.status(403).json({ error: \'Admin access required\' });
        return;
      }
      req.user = { ...decoded, isAdmin: true };
      next();
      return;
    } catch {
      if (openLocalAuth()) {
        req.user = { ...LOCAL_USER };
        next();
        return;
      }
      res.status(401).json({ error: \'Invalid or expired token\' });
      return;
    }
  }

  if (openLocalAuth()) {
    req.user = { ...LOCAL_USER };
    next();
    return;
  }

  res.status(401).json({ error: \'No token provided\' });
}
'''.replace("\\'", "'")
)
print("Rewrote authMiddleware for OPEN_LOCAL_AUTH")

# Ensure local user row exists (FK for songs / settings)
mig = Path("server/src/db/migrate.ts")
if mig.is_file():
    mt = mig.read_text()
    if "local-docker-user" not in mt:
        seed = '''
// ACE-Step-Intel-XPU-Docker: ensure local open-auth user exists
try {
  await pool.query(
    `INSERT OR IGNORE INTO users (id, username, password_hash, is_admin, created_at)
     VALUES ('local-docker-user', 'local', '!', 1, datetime('now'))`
  );
  console.log('[auth] local-docker-user ready');
} catch (e) {
  console.warn('[auth] local user seed skipped', e);
}
'''
        # Append near end of migrate run
        if "console.log" in mt and "Migration" in mt:
            mt = mt + "\n" + seed
        else:
            mt = mt + "\n" + seed
        mig.write_text(mt)
        print("Seeded local-docker-user in migrate.ts")
    else:
        print("local-docker-user already in migrate")

# Soften /api/auth/auto if present — always ok in open mode
auth_routes = Path("server/src/routes/auth.ts")
if auth_routes.is_file():
    at = auth_routes.read_text()
    if "OPEN_LOCAL_AUTH" not in at and "router.get('/auto'" in at or 'router.get("/auto"' in at:
        # optional: leave as-is; middleware covers API
        print("auth routes present (middleware handles open mode)")
    print("auth.ts left intact")

print("open-auth OK")
