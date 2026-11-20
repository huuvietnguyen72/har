#!/usr/bin/env node
// Quản trị HAR cloud (thay cho `python -m app.cli` của bản VPS). Ghi thẳng vào D1 qua wrangler.
//
//   npm run admin -- create-user --email gv@truong.edu.vn --role viewer --remote     # in mật khẩu sinh ngẫu nhiên
//   npm run admin -- create-user --email me@x.com --role admin --password '...' --remote
//   npm run admin -- create-device --dev har01 --alias "Ông A" --remote               # in API key (chỉ 1 lần)
//   npm run admin -- rotate-key --dev har01 --remote
//   npm run admin -- list --remote
// Dùng --local thay --remote để làm với D1 chạy trên máy (wrangler dev).
import { execFileSync } from "node:child_process";
import { createHash, pbkdf2Sync, randomBytes } from "node:crypto";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const DB = "har-db";
// Gói miễn phí của Workers giới hạn ~10 ms CPU mỗi request: 20 000 vòng PBKDF2-SHA256 nằm trong mức đó.
// Số vòng lưu kèm từng mật khẩu (pbkdf2_sha256$<vòng>$...), tăng được sau này mà không đổi code.
const ITERATIONS = 20_000;

function args(argv) {
  const out = { _: [] };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a.startsWith("--")) {
      const k = a.slice(2);
      const v = argv[i + 1] && !argv[i + 1].startsWith("--") ? argv[++i] : true;
      out[k] = v;
    } else out._.push(a);
  }
  return out;
}

const sq = (s) => (s == null ? "NULL" : `'${String(s).replace(/'/g, "''")}'`);

function d1(sql, where, json = false) {
  // ghi SQL ra file tạm để không phải lo dấu nháy khi truyền qua dòng lệnh
  const dir = mkdtempSync(join(tmpdir(), "har-admin-"));
  const file = join(dir, "q.sql");
  writeFileSync(file, sql, "utf8");
  try {
    const cmd = ["wrangler", "d1", "execute", DB, `--${where}`, "--file", file, ...(json ? ["--json"] : [])];
    const out = execFileSync("npx", cmd, { encoding: "utf8", shell: process.platform === "win32", stdio: ["ignore", "pipe", "inherit"] });
    return json ? JSON.parse(out) : out;
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

function hashPassword(pw) {
  const salt = randomBytes(16);
  const h = pbkdf2Sync(pw, salt, ITERATIONS, 32, "sha256");
  return `pbkdf2_sha256$${ITERATIONS}$${salt.toString("base64")}$${h.toString("base64")}`;
}

const a = args(process.argv.slice(2));
const cmd = a._[0];
const where = a.remote ? "remote" : a.local ? "local" : null;
if (!cmd || !where) {
  console.error("Cách dùng: npm run admin -- <create-user|create-device|rotate-key|list> [...] --remote|--local");
  process.exit(2);
}

if (cmd === "create-user") {
  const email = String(a.email || "").trim().toLowerCase();
  const role = a.role || "viewer";
  if (!email.includes("@") || !["admin", "viewer"].includes(role)) {
    console.error("Cần --email hợp lệ và --role admin|viewer");
    process.exit(2);
  }
  const generated = !a.password || a.password === true;
  const pw = generated ? randomBytes(12).toString("base64url") : String(a.password);
  if (pw.length < 8) {
    console.error("Mật khẩu tối thiểu 8 ký tự");
    process.exit(2);
  }
  d1(`INSERT INTO users (email, password_hash, role) VALUES (${sq(email)}, ${sq(hashPassword(pw))}, ${sq(role)})
      ON CONFLICT(email) DO UPDATE SET password_hash = excluded.password_hash, role = excluded.role;`, where);
  console.log(`OK: ${email} (${role})` + (generated ? `\nMật khẩu (chỉ hiện 1 lần, đổi bằng cách chạy lại lệnh): ${pw}` : ""));
} else if (cmd === "create-device" || cmd === "rotate-key") {
  const dev = String(a.dev || "");
  if (!/^[A-Za-z0-9_-]{1,32}$/.test(dev)) {
    console.error("Cần --dev (chữ, số, - hoặc _)");
    process.exit(2);
  }
  const rows = d1(`SELECT dev FROM devices WHERE dev = ${sq(dev)};`, where, true)[0].results;
  if (cmd === "create-device" && rows.length) {
    console.error(`${dev} đã tồn tại; dùng rotate-key để đổi key`);
    process.exit(1);
  }
  if (cmd === "rotate-key" && !rows.length) {
    console.error(`Không có thiết bị ${dev}`);
    process.exit(1);
  }
  const key = randomBytes(32).toString("base64url");
  const hash = createHash("sha256").update(key).digest("hex");
  d1(cmd === "create-device"
    ? `INSERT INTO devices (dev, alias, position, key_hash) VALUES (${sq(dev)}, ${sq(a.alias === true ? null : a.alias)}, ${sq(a.position || "hông phải")}, ${sq(hash)});`
    : `UPDATE devices SET key_hash = ${sq(hash)} WHERE dev = ${sq(dev)};`, where);
  console.log(`Thiết bị: ${dev}\nAPI key (ghi vào VPS_DEVICE_KEY trong edge/.env trên Pi, chỉ hiện 1 lần):\n${key}`);
} else if (cmd === "list") {
  const [u] = d1("SELECT email, role FROM users ORDER BY email;", where, true);
  const [d] = d1("SELECT dev, alias, fw, model FROM devices ORDER BY dev;", where, true);
  for (const x of u.results) console.log(`user   ${x.email.padEnd(32)} ${x.role}`);
  for (const x of d.results) console.log(`device ${x.dev.padEnd(12)} ${(x.alias || "").padEnd(20)} fw=${x.fw} model=${x.model}`);
} else {
  console.error(`Không có lệnh ${cmd}`);
  process.exit(2);
}
