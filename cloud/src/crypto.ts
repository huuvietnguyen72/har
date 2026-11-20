// Mã hóa bằng Web Crypto có sẵn trong Workers (không thư viện ngoài):
// - JWT HS256 cho web app (giống backend FastAPI: sub = email, role, exp)
// - Mật khẩu: PBKDF2-SHA256, chuỗi lưu "pbkdf2_sha256$<vòng lặp>$<salt b64>$<hash b64>"
// - API key thiết bị: sha256 hex (key ngẫu nhiên dài, không cần chậm)

const enc = new TextEncoder();

export function b64url(bytes: ArrayBuffer | Uint8Array): string {
  const b = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  let s = "";
  for (const x of b) s += String.fromCharCode(x);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function fromB64url(s: string): Uint8Array {
  const pad = s.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((s.length + 3) % 4);
  return Uint8Array.from(atob(pad), (c) => c.charCodeAt(0));
}

function fromB64(s: string): Uint8Array {
  return Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
}

function timingSafeEqual(a: Uint8Array, b: Uint8Array): boolean {
  if (a.length !== b.length) return false;
  let d = 0;
  for (let i = 0; i < a.length; i++) d |= a[i] ^ b[i];
  return d === 0;
}

export async function sha256Hex(text: string): Promise<string> {
  const h = await crypto.subtle.digest("SHA-256", enc.encode(text));
  return [...new Uint8Array(h)].map((x) => x.toString(16).padStart(2, "0")).join("");
}

// ---------- mật khẩu ----------
async function pbkdf2(password: string, salt: Uint8Array, iterations: number): Promise<Uint8Array> {
  const key = await crypto.subtle.importKey("raw", enc.encode(password), "PBKDF2", false, ["deriveBits"]);
  const bits = await crypto.subtle.deriveBits({ name: "PBKDF2", hash: "SHA-256", salt, iterations }, key, 256);
  return new Uint8Array(bits);
}

export async function verifyPassword(password: string, stored: string): Promise<boolean> {
  const parts = stored.split("$");
  if (parts.length !== 4 || parts[0] !== "pbkdf2_sha256") return false;
  const iterations = Number(parts[1]);
  if (!Number.isInteger(iterations) || iterations < 1000) return false;
  const got = await pbkdf2(password, fromB64(parts[2]), iterations);
  return timingSafeEqual(got, fromB64(parts[3]));
}

// ---------- JWT HS256 ----------
async function hmacKey(secret: string): Promise<CryptoKey> {
  return crypto.subtle.importKey("raw", enc.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign", "verify"]);
}

export async function signJwt(claims: Record<string, unknown>, secret: string): Promise<string> {
  const head = b64url(enc.encode(JSON.stringify({ alg: "HS256", typ: "JWT" })));
  const body = b64url(enc.encode(JSON.stringify(claims)));
  const sig = await crypto.subtle.sign("HMAC", await hmacKey(secret), enc.encode(`${head}.${body}`));
  return `${head}.${body}.${b64url(sig)}`;
}

/** Trả claims nếu chữ ký đúng và chưa hết hạn, không thì null. */
export async function verifyJwt(token: string, secret: string): Promise<Record<string, any> | null> {
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  try {
    const head = JSON.parse(new TextDecoder().decode(fromB64url(parts[0])));
    if (head.alg !== "HS256") return null;
    const ok = await crypto.subtle.verify("HMAC", await hmacKey(secret), fromB64url(parts[2]), enc.encode(`${parts[0]}.${parts[1]}`));
    if (!ok) return null;
    const claims = JSON.parse(new TextDecoder().decode(fromB64url(parts[1])));
    if (typeof claims.exp !== "number" || claims.exp * 1000 < Date.now()) return null;
    return claims;
  } catch {
    return null;
  }
}
