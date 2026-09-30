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
from gi.repository import Gdk, Gio, GLib, Gtk, Pango

DEFAULT_URL = os.environ.get("DESKDROP_RECEIVER_URL", "http://10.192.185.160:8787")
PROJECT_DIR = Path(__file__).resolve().parent
STATE_DIR = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "deskdrop"
CSS = """
window { background: #f5f5f7; color: #1d1d1f; }
.app-shell { background: #f5f5f7; }
.topbar { background: rgba(255,255,255,.96); border-bottom: 1px solid #e7e7eb; padding: 13px 22px; }
.brand-mark { background: #147efb; color: #fff; border-radius: 11px; font-size: 15px; font-weight: 750; }
.brand-name { font-size: 14px; font-weight: 720; letter-spacing: -.25px; }
.room-title { font-size: 14px; font-weight: 650; }
.room-subtitle { color: #85858d; font-size: 11px; }
.connection-pill { background: #eff8f1; border-radius: 999px; padding: 7px 11px; }
.connection-pill.offline { background: #fff2f0; }
.status-dot { color: #34a853; font-size: 9px; }
.status-dot.offline { color: #d15b52; }
.status { color: #4f8060; font-size: 11px; }
.status.offline { color: #a15b54; }
.conversation { background: #f5f5f7; }
.message-bubble { background: #fff; border: 1px solid #e9e9ed; border-radius: 17px; }
.message-bubble.me { background: #e8f2ff; border-color: #dceaff; }
.message-sender { color: #85858d; font-size: 10px; }
.message-text { font-size: 13px; }
.message-time { color: #96969d; font-size: 9px; }
.empty-state { color: #85858d; }
.empty-symbol { color: #147efb; font-size: 27px; }
.empty-title { color: #303036; font-size: 14px; font-weight: 650; }
.empty-copy { color: #85858d; font-size: 11px; }
.composer { background: #fff; border-top: 1px solid #e7e7eb; padding: 12px 18px 16px; }
.composer entry { min-height: 42px; border-radius: 13px; padding: 0 13px; background: #f4f4f6; border: 1px solid #ededf0; }
button.attach { min-width: 42px; min-height: 42px; border-radius: 13px; background: #f4f4f6; color: #505058; font-size: 19px; }
button.attach:hover { background: #ebebef; }
button.send { min-height: 42px; padding: 0 17px; background: #147efb; color: white; border-radius: 13px; font-weight: 650; }
button.send:hover { background: #086de4; }
button.send:disabled, button.attach:disabled { opacity: .5; }
.transfer-feedback { background: #fff; padding: 0 20px 10px; }
.transfer-label { color: #64646b; font-size: 10px; }
.transfer-label.offline { color: #a15b54; }
.transfer-feedback progressbar trough { min-height: 4px; border-radius: 99px; background: #ececf0; }
.transfer-feedback progressbar progress { min-height: 4px; border-radius: 99px; background: #147efb; }
.file-name { color: #303036; font-size: 12px; font-weight: 620; }
.file-type { min-width: 34px; min-height: 38px; border: 1px solid #e6eaf0; border-radius: 9px; color: #687180; background: #f7f8fa; font-size: 8px; font-weight: 750; }
.file-action { min-height: 30px; padding: 0 11px; border-radius: 9px; color: #0969da; background: #f0f6ff; font-size: 11px; }
.file-action:hover { background: #e4efff; }
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
        self.message_rows = {}
        self.polling = False
        self.child_server = None
        self.ready = False
        self.sending_text = False
        self.transfer_active = False
        self.transfer_hide_timeout = None
        self.set_default_size(920, 700)
        self.set_size_request(620, 460)
        self.build_ui()
        self.apply_css()
        self.connect("close-request", self.on_close)
        if host_mode:
            threading.Thread(target=self.start_receiver, daemon=True).start()
        GLib.timeout_add_seconds(2, self.poll)

    def build_ui(self):
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        root.add_css_class("app-shell")
        self.set_child(root)

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        top.add_css_class("topbar")
        brand = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        icon = Gtk.Label(label="D")
        icon.add_css_class("brand-mark")
        icon.set_size_request(38, 38)
        icon.set_halign(Gtk.Align.CENTER)
        icon.set_valign(Gtk.Align.CENTER)
        brand.append(icon)
        name_stack = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        name_stack.append(Gtk.Label(label="DeskDrop", xalign=0))
        name_stack.get_last_child().add_css_class("brand-name")
        name_stack.append(Gtk.Label(label="文件传输助手", xalign=0))
        name_stack.get_last_child().add_css_class("room-subtitle")
        brand.append(name_stack)
        top.append(brand)

        divider = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        divider.set_margin_top(3)
        divider.set_margin_bottom(3)
        top.append(divider)

        conversation_title = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        conversation_title.set_hexpand(True)
        conversation_title.append(Gtk.Label(label="工位电脑" if not self.host_mode else "笔记本", xalign=0))
        conversation_title.get_last_child().add_css_class("room-title")
        conversation_title.append(Gtk.Label(label="固定设备 · 点对点房间", xalign=0))
        conversation_title.get_last_child().add_css_class("room-subtitle")
        top.append(conversation_title)

        connection = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=7)
        self.connection = connection
        connection.add_css_class("connection-pill")
        self.status_dot = Gtk.Label(label="●")
        self.status_dot.add_css_class("status-dot")
        connection.append(self.status_dot)
        self.status_label = Gtk.Label(label="正在连接…", xalign=0)
        self.status_label.add_css_class("status")
        self.status_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.status_label.set_max_width_chars(34)
        connection.append(self.status_label)
        top.append(connection)
        if self.host_mode:
            folder_button = Gtk.Button(label="接收目录")
            folder_button.add_css_class("file-action")
            folder_button.connect("clicked", self.open_received_folder)
            top.append(folder_button)
        root.append(top)

        self.scroller = Gtk.ScrolledWindow()
        self.scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scroller.add_css_class("conversation")
        self.scroller.set_hexpand(True)
        self.scroller.set_vexpand(True)
        self.messages_box.set_margin_top(25)
        self.messages_box.set_margin_bottom(25)
        self.messages_box.set_margin_start(44)
        self.messages_box.set_margin_end(44)
        self.scroller.set_child(self.messages_box)
        root.append(self.scroller)

        self.empty_state = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.empty_state.add_css_class("empty-state")
        self.empty_state.set_halign(Gtk.Align.CENTER)
        self.empty_state.set_valign(Gtk.Align.CENTER)
        self.empty_state.set_margin_top(80)
        self.empty_state.set_margin_bottom(80)
        self.empty_state.append(Gtk.Label(label="↗"))
        self.empty_state.get_last_child().add_css_class("empty-symbol")
        self.empty_state.append(Gtk.Label(label="从这里开始传文件", xalign=0))
        self.empty_state.get_last_child().add_css_class("empty-title")
        self.empty_state.append(Gtk.Label(label="消息和文件只在这两台设备间同步", xalign=0))
        self.empty_state.get_last_child().add_css_class("empty-copy")
        self.messages_box.append(self.empty_state)

        self.transfer_feedback = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        self.transfer_feedback.add_css_class("transfer-feedback")
        self.transfer_label = Gtk.Label(label="", xalign=0)
        self.transfer_label.add_css_class("transfer-label")
        self.transfer_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.transfer_label.set_max_width_chars(72)
        self.transfer_feedback.append(self.transfer_label)
        self.transfer_progress = Gtk.ProgressBar()
        self.transfer_progress.set_show_text(True)
        self.transfer_feedback.append(self.transfer_progress)
        self.transfer_feedback.set_visible(False)

        composer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        composer.add_css_class("composer")
        self.attach_button = Gtk.Button(label="＋")
        self.attach_button.add_css_class("attach")
        self.attach_button.set_tooltip_text("选择要发送的文件")
        self.attach_button.connect("clicked", self.choose_file)
        composer.append(self.attach_button)
        self.entry = Gtk.Entry()
        self.entry.set_placeholder_text("输入消息…")
        self.entry.set_hexpand(True)
        self.entry.connect("activate", self.send_text)
        composer.append(self.entry)
        self.send_button = Gtk.Button(label="发送")
        self.send_button.add_css_class("send")
        self.send_button.connect("clicked", self.send_text)
        composer.append(self.send_button)

        root.append(self.transfer_feedback)
        root.append(composer)

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
        self.status_label.set_text(text)
        if online:
            self.status_label.remove_css_class("offline")
            self.status_dot.remove_css_class("offline")
            self.connection.remove_css_class("offline")
        else:
            self.status_label.add_css_class("offline")
            self.status_dot.add_css_class("offline")
            self.connection.add_css_class("offline")
        self.ready = online
        self.attach_button.set_sensitive(online and not self.transfer_active)
        self.send_button.set_sensitive(online and not self.sending_text)
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

    def show_messages(self, messages, force_scroll=False, reconcile=True):
        should_scroll = force_scroll or self.is_near_bottom()
        added = False
        current_ids = {message.get("id") for message in messages if message.get("id")}
        for message in messages:
            message_id = message.get("id")
            if not message_id or message_id in self.seen_ids:
                continue
            self.seen_ids.add(message_id)
            if self.empty_state.get_parent() is self.messages_box:
                self.messages_box.remove(self.empty_state)
            self.message_rows[message_id] = self.add_message(message)
            added = True
        removed = False
        if reconcile:
            for message_id in self.seen_ids - current_ids:
                row = self.message_rows.pop(message_id, None)
                if row and row.get_parent() is self.messages_box:
                    self.messages_box.remove(row)
                    removed = True
                self.seen_ids.discard(message_id)
        if not current_ids and self.empty_state.get_parent() is None:
            self.messages_box.append(self.empty_state)
        if (added or removed) and should_scroll:
            GLib.idle_add(self.scroll_to_bottom)
        return GLib.SOURCE_REMOVE

    def is_near_bottom(self):
        adjustment = self.scroller.get_vadjustment()
        distance = adjustment.get_upper() - adjustment.get_page_size() - adjustment.get_value()
        return distance <= 96

    def scroll_to_bottom(self):
        adjustment = self.scroller.get_vadjustment()
        adjustment.set_value(adjustment.get_upper())
        return GLib.SOURCE_REMOVE

    def add_message(self, message):
        mine = message.get("senderId") == self.sender_id
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        row.set_halign(Gtk.Align.END if mine else Gtk.Align.START)
        bubble = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
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
            extension = Path(message.get("name", "")).suffix.lower().lstrip(".")[:4].upper() or "FILE"
            badge = Gtk.Label(label=extension)
            badge.add_css_class("file-type")
            file_box.append(badge)
            details = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
            details.set_hexpand(True)
            filename = Gtk.Label(label=message.get("name", "文件"), xalign=0)
            filename.set_ellipsize(Pango.EllipsizeMode.END)
            filename.set_max_width_chars(32)
            filename.add_css_class("file-name")
            details.append(filename)
            details.append(Gtk.Label(label=human_size(message.get("size")), xalign=0))
            details.get_last_child().add_css_class("message-sender")
            file_box.append(details)
            action = Gtk.Button(label="打开" if self.host_mode else "下载")
            action.add_css_class("file-action")
            action.connect("clicked", self.open_file, message)
            file_box.append(action)
            content.append(file_box)
        else:
            text = Gtk.Label(label=message.get("text", ""), xalign=0, yalign=0)
            text.set_wrap(True)
            text.set_selectable(True)
            text.set_max_width_chars(58)
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
        bubble.append(content)
        row.append(bubble)
        self.messages_box.append(row)
        return row

    def send_text(self, *_args):
        if self.sending_text or not self.ready:
            return
        value = self.entry.get_text().strip()
        if not value:
            return
        self.sending_text = True
        self.entry.set_text("")
        self.entry.set_sensitive(False)
        self.send_button.set_sensitive(False)
        self.run_async(self.post_text, value)

    def post_text(self, value):
        status, response = api_request(self.base_url, "POST", "/api/messages", {
            "text": value, "sender": self.sender_name, "senderId": self.sender_id,
        })
        if status >= 300:
            raise RuntimeError(response.get("error", "消息发送失败"))
        GLib.idle_add(self.finish_text_send, response.get("message", {}))

    def finish_text_send(self, message):
        self.sending_text = False
        self.entry.set_sensitive(True)
        self.send_button.set_sensitive(self.ready)
        if message:
            self.show_messages([message], force_scroll=True, reconcile=False)
        self.entry.grab_focus()
        return GLib.SOURCE_REMOVE

    def fail_text_send(self, value, error):
        self.sending_text = False
        self.entry.set_text(value)
        self.entry.set_sensitive(True)
        self.send_button.set_sensitive(self.ready)
        self.entry.grab_focus()
        self.set_status(f"消息未发送：{error}", self.ready)
        self.status_label.add_css_class("offline")
        self.status_dot.add_css_class("offline")
        self.connection.add_css_class("offline")
        return GLib.SOURCE_REMOVE

    def choose_file(self, *_args):
        chooser = Gtk.FileChooserNative.new("选择要发送的文件", self, Gtk.FileChooserAction.OPEN, "发送", "取消")
        chooser.connect("response", self.on_file_chosen)
        chooser.show()

    def on_file_chosen(self, chooser, response):
        if response == Gtk.ResponseType.ACCEPT:
            selected = chooser.get_file()
            if selected and selected.get_path() and self.ready and not self.transfer_active:
                file_path = selected.get_path()
                self.begin_transfer(Path(file_path).name, "正在发送")
                self.run_async(self.upload_file, file_path)
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
                if size:
                    GLib.idle_add(self.update_transfer, min(1.0, source.tell() / size))
        response = conn.getresponse()
        data = response.read()
        result = json.loads(data.decode("utf-8")) if data else {}
        code = response.status
        conn.close()
        if code >= 300:
            raise RuntimeError(result.get("error", "文件发送失败"))
        GLib.idle_add(self.finish_transfer, True, f"已发送 · {name}")

    def begin_transfer(self, name, action):
        if self.transfer_hide_timeout:
            GLib.source_remove(self.transfer_hide_timeout)
            self.transfer_hide_timeout = None
        self.transfer_active = True
        self.transfer_label.remove_css_class("offline")
        self.transfer_label.set_text(f"{action} · {name}")
        self.transfer_progress.set_fraction(0)
        self.transfer_progress.set_text("准备中")
        self.transfer_feedback.set_visible(True)
        self.attach_button.set_sensitive(False)
        return GLib.SOURCE_REMOVE

    def update_transfer(self, fraction):
        fraction = max(0.0, min(1.0, fraction))
        self.transfer_progress.set_fraction(fraction)
        self.transfer_progress.set_text(f"{round(fraction * 100)}%")
        return GLib.SOURCE_REMOVE

    def finish_transfer(self, success, message):
        self.transfer_active = False
        self.transfer_label.set_text(message)
        if success:
            self.transfer_progress.set_fraction(1)
            self.transfer_progress.set_text("完成")
        else:
            self.transfer_label.add_css_class("offline")
            self.transfer_progress.set_text("未完成")
        self.attach_button.set_sensitive(self.ready)
        if self.transfer_hide_timeout:
            GLib.source_remove(self.transfer_hide_timeout)
        self.transfer_hide_timeout = GLib.timeout_add_seconds(5, self.hide_transfer_feedback)
        return GLib.SOURCE_REMOVE

    def hide_transfer_feedback(self):
        self.transfer_feedback.set_visible(False)
        self.transfer_label.remove_css_class("offline")
        self.transfer_hide_timeout = None
        return GLib.SOURCE_REMOVE

    def open_file(self, _button, message):
        if self.host_mode:
            path = PROJECT_DIR / "received" / message.get("fileId", "")
            if path.is_file():
                subprocess.Popen(["xdg-open", str(path)])
            else:
                self.set_status("这个旧文件已不在接收目录", False)
            return
        if self.transfer_active or not self.ready:
            return
        _button.set_sensitive(False)
        self.begin_transfer(Path(message.get("name", "file")).name, "正在下载")
        self.run_async(self.download_file, message, _button)

    def download_file(self, message, button):
        parsed = urllib.parse.urlsplit(self.base_url)
        file_id = urllib.parse.quote(message.get("fileId", ""), safe="")
        conn = http.client.HTTPConnection(parsed.hostname, parsed.port or 80, timeout=60)
        name = Path(message.get("name", "file")).name
        temporary = None
        temporary_created = False
        try:
            conn.request("GET", f"/api/files/{file_id}")
            response = conn.getresponse()
            if response.status >= 300:
                detail = response.read().decode("utf-8", "replace")
                raise RuntimeError(detail or "文件下载失败")
            total = int(response.getheader("Content-Length") or 0)
            downloads = Path.home() / "Downloads"
            downloads.mkdir(parents=True, exist_ok=True)
            target = downloads / name
            stem, suffix = target.stem, target.suffix
            index = 1
            while target.exists():
                target = downloads / f"{stem} ({index}){suffix}"
                index += 1
            temporary = downloads / f".{target.name}.{uuid.uuid4().hex}.part"
            with temporary.open("xb") as output:
                temporary_created = True
                received = 0
                while True:
                    block = response.read(1024 * 1024)
                    if not block:
                        break
                    output.write(block)
                    received += len(block)
                    if total:
                        GLib.idle_add(self.update_transfer, min(1.0, received / total))
            if total and received != total:
                raise RuntimeError(f"下载不完整：收到 {received} / {total} 字节")
            os.replace(temporary, target)
        except Exception:
            if temporary_created and temporary is not None:
                temporary.unlink(missing_ok=True)
            raise
        finally:
            conn.close()
        GLib.idle_add(self.finish_transfer, True, f"已下载到 Downloads · {name}")
        GLib.idle_add(button.set_sensitive, True)

    def run_async(self, function, *args):
        def work():
            try:
                function(*args)
            except Exception as error:
                if function.__name__ == "post_text":
                    GLib.idle_add(self.fail_text_send, args[0], str(error))
                elif function.__name__ in {"upload_file", "download_file"}:
                    GLib.idle_add(self.finish_transfer, False, f"传输失败：{error}")
                    if function.__name__ == "download_file":
                        GLib.idle_add(args[1].set_sensitive, True)
                else:
                    GLib.idle_add(self.set_status, f"操作失败：{error}", self.ready)
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
