"""Quản trị: tạo tài khoản (không cho tự đăng ký) và cấp API key cho thiết bị.

Trong container:
    docker compose exec api python -m app.cli create-user --email gv@truong.edu.vn --role viewer
    docker compose exec api python -m app.cli create-device --dev har01 --alias "Ông A"
    docker compose exec api python -m app.cli rotate-key --dev har01
    docker compose exec api python -m app.cli list
"""
import argparse
import getpass
import sys

from sqlmodel import Session, select

from .db import get_engine
from .models import Device, User
from .security import hash_device_key, hash_password, new_device_key


def _password(arg: str | None) -> str:
    if arg:
        return arg
    p1 = getpass.getpass("Mật khẩu: ")
    p2 = getpass.getpass("Nhập lại: ")
    if p1 != p2 or len(p1) < 8:
        sys.exit("Mật khẩu không khớp hoặc ngắn hơn 8 ký tự")
    return p1


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m app.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)

    u = sub.add_parser("create-user", help="tạo hoặc đổi mật khẩu tài khoản web app")
    u.add_argument("--email", required=True)
    u.add_argument("--password", help="bỏ trống để nhập ẩn")
    u.add_argument("--role", default="viewer", choices=["admin", "viewer"])

    d = sub.add_parser("create-device", help="thêm thiết bị và in API key (chỉ hiện 1 lần)")
    d.add_argument("--dev", required=True)
    d.add_argument("--alias")
    d.add_argument("--position", default="hông phải")

    r = sub.add_parser("rotate-key", help="cấp API key mới cho thiết bị")
    r.add_argument("--dev", required=True)

    sub.add_parser("list", help="liệt kê tài khoản và thiết bị")

    a = ap.parse_args(argv)
    with Session(get_engine()) as s:
        if a.cmd == "create-user":
            email = a.email.strip().lower()
            user = s.exec(select(User).where(User.email == email)).first() or User(email=email, password_hash="")
            user.password_hash = hash_password(_password(a.password))
            user.role = a.role
            s.add(user)
            s.commit()
            print(f"OK: {email} ({a.role})")
        elif a.cmd in ("create-device", "rotate-key"):
            dev = s.get(Device, a.dev)
            if a.cmd == "create-device" and dev is not None:
                sys.exit(f"{a.dev} đã tồn tại; dùng rotate-key để đổi key")
            if a.cmd == "rotate-key" and dev is None:
                sys.exit(f"Không có thiết bị {a.dev}")
            key = new_device_key()
            if dev is None:
                dev = Device(dev=a.dev, alias=a.alias, position=a.position, key_hash="")
            dev.key_hash = hash_device_key(key)
            s.add(dev)
            s.commit()
            print(f"Thiết bị: {a.dev}\nAPI key (ghi vào VPS_DEVICE_KEY trong edge/.env, chỉ hiện 1 lần):\n{key}")
        elif a.cmd == "list":
            for user in s.exec(select(User)).all():
                print(f"user   {user.email:32} {user.role}")
            for dev in s.exec(select(Device)).all():
                print(f"device {dev.dev:12} {dev.alias or '':20} fw={dev.fw} model={dev.model}")


if __name__ == "__main__":
    main()
