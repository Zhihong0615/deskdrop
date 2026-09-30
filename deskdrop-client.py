#!/usr/bin/env python3
"""Native GTK chat client for a trusted two-computer DeskDrop room."""
import argparse
import http.client
import json
import os
import platform
import subprocess
import threading
import urllib.parse
import uuid
from pathlib import Path

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk

DEFAULT_URL = os.environ.get("DESKDROP_RECEIVER_URL", "http://10.192.185.160:8787")
PROJECT_DIR = Path(__file__).resolve().parent
STATE_DIR = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "deskdrop"
CSS = """
window { background: #eef1f4; color: #18212b; }
headerbar { background: #f8fafb; border-bottom: 1px solid #dfe5e9; }
.chat-title { font-size: 16px; font-weight: 700; }
.chat-subtitle { color: #73808d; font-size: 12px; }
.sidebar { background: #f8fafb; border-right: 1px solid #dfe5e9; }
.room-selected { background: #e8f1f7; border-radius: 10px; padding: 12px; }
.room-name { font-weight: 700; }
.room-hint { color: #73808d; font-size: 12px; }
.conversation { background: #eef1f4; }
.message-bubble { background: #ffffff; border: 0; border-radius: 14px; padding: 10px 13px; }
.message-bubble.me { background: #d8f5c8; }
.message-sender { color: #71808b; font-size: 11px; }
.message-text { font-size: 14px; }
.message-time { color: #87939c; font-size: 10px; }
.composer { background: #f8fafb; border-top: 1px solid #dfe5e9; padding: 12px; }
.composer entry { min-height: 40px; border-radius: 18px; padding: 0 14px; }
.status { color: #657482; font-size: 12px; padding: 4px 14px; }
button.send { background: #168c69; color: white; border-radius: 18px; font-weight: 700; }
button.send:hover { background: #0e7658; }
"""

def api_request(base_url, method, route, body=None, extra_headers=None):
    parsed = urllib.parse.urlsplit(base_url)
    if parsed.scheme != "http" or not parsed.hostname:
        raise RuntimeError("房间地址必须是 http:// 开头的局域网地址")
    conn = http.client.HTTPConnection(parsed.hostname, parsed.port or 80, timeout=8)
    headers = dict(extra_headers or {})
    payload = None
    if body is not None:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    conn.request(method, route, body=payload, headers=headers)
    response = conn.getresponse()
    data = response.read()
    result = json.loads(data.decode("utf-8")) if data else {}
    status = response.status
    conn.close()
    return status, result

def device_id():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    identity = STATE_DIR / "client-id"
    try:
        value = identity.read_text(encoding="utf-8").strip()
        if value:
            return value
    except OSError:
        pass
    value = uuid.uuid4().hex
    identity.write_text(value, encoding="utf-8")
    try:
        identity.chmod(0o600)
    except OSError:
        pass
    return value

def human_size(value):
    amount = float(value or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if amount < 1024 or unit == "GB":
            return f"{amount:.0f} {unit}" if unit == "B" else f"{amount:.1f} {unit}"
        amount /= 1024

class DeskDropWindow(Gtk.ApplicationWindow):
    def __init__(self, app, host_mode, base_url):
        super().__init__(application=app, title="DeskDrop")
        self.host_mode = host_mode
        self.base_url = "http://127.0.0.1:8787" if host_mode else base_url.rstrip("/")
        self.sender_id = device_id()
        self.sender_name = "工位电脑" if host_mode else (platform.node() or "笔记本")
        self.messages_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.seen_ids = set()
        self.polling = False
        self.child_server = None
        self.ready = False
        self.set_default_size(980, 680)
        self.set_size_request(720, 480)
        self.build_ui()
        self.apply_css()
        self.connect("close-request", self.on_close)
        if host_mode:
            threading.Thread(target=self.start_receiver, daemon=True).start()
        GLib.timeout_add_seconds(2, self.poll)

    def build_ui(self):
        root = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.set_child(root)

        side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        side.add_css_class("sidebar")
        side.set_size_request(235, -1)
        side.set_margin_top(18)
        side.set_margin_bottom(18)
        side.set_margin_start(16)
        side.set_margin_end(14)
        root.append(side)

        brand = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        icon = Gtk.Label(label="D")
        icon.add_css_class("chat-title")
        icon.set_size_request(38, 38)
        icon.set_halign(Gtk.Align.CENTER)
        icon.set_valign(Gtk.Align.CENTER)
        icon.add_css_class("room-selected")
        brand.append(icon)
        brand.append(Gtk.Label(label="DeskDrop", xalign=0))
        side.append(brand)

        room = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        room.add_css_class("room-selected")
        room.append(Gtk.Label(label="两台电脑的聊天", xalign=0))
        room.get_last_child().add_css_class("room-name")
        room.append(Gtk.Label(label="消息和文件实时同步", xalign=0))
        room.get_last_child().add_css_class("room-hint")
        side.append(room)
        side.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        room_label = "本机房间" if self.host_mode else "工位电脑"
        peer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        avatar = Gtk.Label(label="聊")
        avatar.add_css_class("room-selected")
        peer.append(avatar)
        names = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        names.append(Gtk.Label(label=room_label, xalign=0))
        names.get_last_child().add_css_class("room-name")
        names.append(Gtk.Label(label="固定设备 · 无需 PIN", xalign=0))
        names.get_last_child().add_css_class("room-hint")
        peer.append(names)
        side.append(peer)

        side_spacer = Gtk.Box()
        side_spacer.set_vexpand(True)
        side.append(side_spacer)
        if self.host_mode:
            folder_btn = Gtk.Button(label="打开接收文件夹")
            folder_btn.connect("clicked", self.open_received_folder)
            side.append(folder_btn)
        side.append(Gtk.Label(label="仅限已配置的两台电脑", xalign=0))
        side.get_last_child().add_css_class("room-hint")

        chat = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        chat.set_hexpand(True)
        root.append(chat)
        top = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        top.set_margin_top(15)
        top.set_margin_bottom(13)
        top.set_margin_start(18)
        top.set_margin_end(18)
        top.append(Gtk.Label(label="文件传输助手", xalign=0))
        top.get_last_child().add_css_class("chat-title")
        endpoint = "本机接收端" if self.host_mode else self.base_url
        top.append(Gtk.Label(label=f"{endpoint}  ·  PIN 自动免输", xalign=0))
        top.get_last_child().add_css_class("chat-subtitle")
        chat.append(top)
        chat.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        self.scroller = Gtk.ScrolledWindow()
        self.scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scroller.add_css_class("conversation")
        self.scroller.set_hexpand(True)
        self.scroller.set_vexpand(True)
        self.messages_box.set_margin_top(22)
        self.messages_box.set_margin_bottom(22)
        self.messages_box.set_margin_start(24)
        self.messages_box.set_margin_end(24)
        self.scroller.set_child(self.messages_box)
        chat.append(self.scroller)

        self.status_label = Gtk.Label(label="正在连接房间…", xalign=0)
        self.status_label.add_css_class("status")
        chat.append(self.status_label)

        composer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        composer.add_css_class("composer")
        attach = Gtk.Button(label="＋ 文件")
        attach.connect("clicked", self.choose_file)
        composer.append(attach)
        self.entry = Gtk.Entry()
        self.entry.set_placeholder_text("输入消息，按 Enter 发送")
        self.entry.set_hexpand(True)
        self.entry.connect("activate", self.send_text)
        composer.append(self.entry)
        send = Gtk.Button(label="发送")
        send.add_css_class("send")
        send.connect("clicked", self.send_text)
        composer.append(send)
        chat.append(composer)

    def apply_css(self):
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS.encode("utf-8"))
        display = Gdk.Display.get_default()
        if display:
            Gtk.StyleContext.add_provider_for_display(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def start_receiver(self):
        try:
            status, _ = api_request(self.base_url, "GET", "/api/status")
            if status == 200:
                GLib.idle_add(self.set_status, "接收端已运行，房间在线", True)
                return
        except Exception:
            pass
        try:
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            log_path = STATE_DIR / "receiver.log"
            log = open(log_path, "ab", buffering=0)
            self.child_server = subprocess.Popen(
                ["/bin/bash", str(PROJECT_DIR / "start-deskdrop.sh"), "--no-browser"],
                cwd=PROJECT_DIR, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            GLib.idle_add(self.set_status, "正在启动本机接收端…", False)
        except Exception as error:
            GLib.idle_add(self.set_status, f"启动失败：{error}", False)

    def set_status(self, text, online):
        self.status_label.set_text(("●  " if online else "○  ") + text)
        self.ready = online
        return GLib.SOURCE_REMOVE

    def poll(self):
        if self.polling:
            return GLib.SOURCE_CONTINUE
        self.polling = True
        threading.Thread(target=self.poll_worker, daemon=True).start()
        return GLib.SOURCE_CONTINUE

    def poll_worker(self):
        try:
            status, room = api_request(self.base_url, "GET", "/api/status")
            if status != 200 or not room.get("authenticated"):
                raise RuntimeError("接收端暂未允许这台电脑，请检查固定 IP 信任配置")
            status, response = api_request(self.base_url, "GET", "/api/messages")
            if status != 200:
                raise RuntimeError(response.get("error", "读取聊天记录失败"))
            GLib.idle_add(self.show_messages, response.get("messages", []))
            GLib.idle_add(self.set_status, f"已连接 · {room.get('room', 'DeskDrop 房间')}", True)
        except Exception as error:
            GLib.idle_add(self.set_status, f"等待连接：{error}", False)
        finally:
            self.polling = False

    def show_messages(self, messages):
        for message in messages:
            message_id = message.get("id")
            if not message_id or message_id in self.seen_ids:
                continue
            self.seen_ids.add(message_id)
            self.add_message(message)
        GLib.idle_add(self.scroll_to_bottom)
        return GLib.SOURCE_REMOVE

    def scroll_to_bottom(self):
        adjustment = self.scroller.get_vadjustment()
        adjustment.set_value(adjustment.get_upper())
        return GLib.SOURCE_REMOVE

    def add_message(self, message):
        mine = message.get("senderId") == self.sender_id
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        row.set_halign(Gtk.Align.END if mine else Gtk.Align.START)
        bubble = Gtk.Frame()
        bubble.add_css_class("message-bubble")
        if mine:
            bubble.add_css_class("me")
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        content.set_margin_top(9)
        content.set_margin_bottom(9)
        content.set_margin_start(12)
        content.set_margin_end(12)
        if not mine:
            who = Gtk.Label(label=message.get("sender", "另一台电脑"), xalign=0)
            who.add_css_class("message-sender")
            content.append(who)
        if message.get("type") == "file":
            file_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            file_box.append(Gtk.Label(label="📄"))
            details = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
            details.append(Gtk.Label(label=message.get("name", "文件"), xalign=0))
            details.append(Gtk.Label(label=human_size(message.get("size")), xalign=0))
            details.get_last_child().add_css_class("message-sender")
            file_box.append(details)
            action = Gtk.Button(label="打开" if self.host_mode else "下载")
            action.connect("clicked", self.open_file, message)
            file_box.append(action)
            content.append(file_box)
        else:
            text = Gtk.Label(label=message.get("text", ""), xalign=0, yalign=0)
            text.set_wrap(True)
            text.set_selectable(True)
            text.set_max_width_chars(48)
            text.add_css_class("message-text")
            content.append(text)
        from datetime import datetime
        try:
            time_text = datetime.fromtimestamp(float(message.get("createdAt", 0)) / 1000).strftime("%H:%M")
        except (ValueError, TypeError, OSError):
            time_text = ""
        timestamp = Gtk.Label(label=time_text, xalign=1)
        timestamp.add_css_class("message-time")
        content.append(timestamp)
        bubble.set_child(content)
        row.append(bubble)
        self.messages_box.append(row)

    def send_text(self, *_args):
        value = self.entry.get_text().strip()
        if not value:
            return
        self.entry.set_text("")
        self.run_async(self.post_text, value)

    def post_text(self, value):
        status, response = api_request(self.base_url, "POST", "/api/messages", {
            "text": value, "sender": self.sender_name, "senderId": self.sender_id,
        })
        if status >= 300:
            raise RuntimeError(response.get("error", "消息发送失败"))
        GLib.idle_add(self.show_messages, [response.get("message", {})])

    def choose_file(self, *_args):
        chooser = Gtk.FileChooserNative.new("选择要发送的文件", self, Gtk.FileChooserAction.OPEN, "发送", "取消")
        chooser.connect("response", self.on_file_chosen)
        chooser.show()

    def on_file_chosen(self, chooser, response):
        if response == Gtk.ResponseType.ACCEPT:
            selected = chooser.get_file()
            if selected and selected.get_path():
                self.run_async(self.upload_file, selected.get_path())
        chooser.destroy()

    def upload_file(self, file_path):
        parsed = urllib.parse.urlsplit(self.base_url)
        name = Path(file_path).name
        query = urllib.parse.urlencode({"name": name, "sender": self.sender_name, "senderId": self.sender_id})
        route = f"/api/upload?{query}"
        conn = http.client.HTTPConnection(parsed.hostname, parsed.port or 80, timeout=30)
        size = os.path.getsize(file_path)
        conn.putrequest("POST", route)
        conn.putheader("Content-Length", str(size))
        conn.putheader("Content-Type", "application/octet-stream")
        conn.endheaders()
        with open(file_path, "rb") as source:
            while True:
                block = source.read(1024 * 1024)
                if not block:
                    break
                conn.send(block)
        response = conn.getresponse()
        data = response.read()
        result = json.loads(data.decode("utf-8")) if data else {}
        code = response.status
        conn.close()
        if code >= 300:
            raise RuntimeError(result.get("error", "文件发送失败"))
        GLib.idle_add(self.set_status, f"文件已发送：{name}", True)

    def open_file(self, _button, message):
        if self.host_mode:
            path = PROJECT_DIR / "received" / message.get("fileId", "")
            if path.is_file():
                subprocess.Popen(["xdg-open", str(path)])
            else:
                self.set_status("这个旧文件已不在接收目录", False)
            return
        self.run_async(self.download_file, message)

    def download_file(self, message):
        parsed = urllib.parse.urlsplit(self.base_url)
        file_id = urllib.parse.quote(message.get("fileId", ""), safe="")
        conn = http.client.HTTPConnection(parsed.hostname, parsed.port or 80, timeout=60)
        conn.request("GET", f"/api/files/{file_id}")
        response = conn.getresponse()
        if response.status >= 300:
            detail = response.read().decode("utf-8", "replace")
            conn.close()
            raise RuntimeError(detail or "文件下载失败")
        downloads = Path.home() / "Downloads"
        downloads.mkdir(parents=True, exist_ok=True)
        target = downloads / Path(message.get("name", "file")).name
        stem, suffix = target.stem, target.suffix
        index = 1
        while target.exists():
            target = downloads / f"{stem} ({index}){suffix}"
            index += 1
        with target.open("wb") as output:
            while True:
                block = response.read(1024 * 1024)
                if not block:
                    break
                output.write(block)
        conn.close()
        GLib.idle_add(self.set_status, f"已下载到：{target}", True)

    def run_async(self, function, *args):
        def work():
            try:
                function(*args)
            except Exception as error:
                GLib.idle_add(self.set_status, f"操作失败：{error}", False)
        threading.Thread(target=work, daemon=True).start()

    def open_received_folder(self, *_args):
        inbox = PROJECT_DIR / "received"
        inbox.mkdir(parents=True, exist_ok=True)
        Gio.AppInfo.launch_default_for_uri(inbox.as_uri(), None)

    def on_close(self, *_args):
        if self.child_server and self.child_server.poll() is None:
            try:
                os.killpg(self.child_server.pid, 15)
            except ProcessLookupError:
                pass
        return False

class DeskDropApp(Gtk.Application):
    def __init__(self, host_mode, base_url):
        super().__init__(application_id="com.deskdrop.Chat", flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.host_mode = host_mode
        self.base_url = base_url

    def do_activate(self):
        window = DeskDropWindow(self, self.host_mode, self.base_url)
        window.present()

def main():
    parser = argparse.ArgumentParser(description="Native DeskDrop chat and file transfer")
    parser.add_argument("--host", action="store_true", help="start the receiver on this computer")
    parser.add_argument("--url", default=DEFAULT_URL, help="fixed address of the DeskDrop receiver")
    parser.add_argument("--configure", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--no-prompt", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    app = DeskDropApp(args.host, args.url)
    return app.run([])

if __name__ == "__main__":
    raise SystemExit(main())
