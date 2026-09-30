# DeskDrop

DeskDrop 是一个自托管的局域网原生聊天与文件传输工具。Linux 客户端使用 GTK 桌面窗口，不需要浏览器；两台电脑打开同一个房间后，可以实时聊天、双向发送文件。文件和聊天记录保存在接收电脑，不经过云端。

## 一键启动

把整个项目文件夹放到两台 Linux 电脑上。在每台电脑上首次运行一次：

```bash
bash install-desktop-launcher.sh
```

Ubuntu 需要 GTK 4 和 Python GObject。缺少依赖时运行 `sudo apt install python3-gi gir1.2-gtk-4.0`。然后运行上面的命令安装 GNOME 应用菜单启动项。工位电脑搜索 **DeskDrop** 打开接收端和聊天窗口；笔记本搜索 **DeskDrop on this computer** 打开同一个原生聊天窗口。也可以运行 `bash install-desktop-launcher.sh --pin-dock` 将工位端图标固定到 Dock。

接收电脑双击 `Start DeskDrop.desktop` 会启动原生聊天窗口和接收端；关闭窗口会停止由该窗口启动的接收端。笔记本双击 `Send to DeskDrop.desktop` 会打开客户端。若移动了项目文件夹，请重新运行安装脚本更新启动项。

首次在接收端启动时，如果电脑还没有 Node.js 18 或更新版本，启动器会从 Node.js 官网下载便携版运行环境到当前用户目录，不需要管理员权限。首次准备需要联网；之后可以离线启动。Linux 首次准备需要 `curl` 和 `tar`，它们通常已预装。

## 两台电脑聊天和传文件

1. 确认两台电脑能通过局域网互相访问接收端的 `8787` 端口。
2. 在工位电脑打开 **DeskDrop**；在笔记本打开 **DeskDrop on this computer**。笔记本客户端默认连接 `http://10.192.185.160:8787`，可以通过 `DESKDROP_RECEIVER_URL` 覆盖。
3. 两边可互发文字和文件。工位电脑收到的文件保存在项目目录 `received/`；笔记本下载的文件保存在 `~/Downloads`。

两台固定设备可以配置免 PIN 直连。在接收端 `~/.config/deskdrop/receiver.env` 设置 `DESKDROP_TRUSTED_CLIENTS` 为笔记本的固定 IP（仅写在本地配置，不要提交到仓库）。启用此项后 PIN 登录关闭，只有本机和信任 IP 可进入聊天 API。其他 IP 不会获得访问权限。

聊天记录保存在接收电脑的 `~/.local/state/deskdrop/messages.json`。默认单个文件最大 1 GB。Linux 防火墙如果拦截连接，请允许本地网络访问 DeskDrop 的 8787 端口。

## 登录后自动启动

在工位电脑双击 `Install Receiver Autostart.desktop`，DeskDrop 会安装为当前用户的 systemd 服务，在登录后自动启动。之后打开 **DeskDrop** 桌面应用即可聊天；服务状态可用以下命令查看：

```bash
systemctl --user status deskdrop.service
journalctl --user -u deskdrop.service -n 30 --no-pager
```

在笔记本双击 `Install Sender Autostart.desktop`，之后每次登录 Linux 桌面时会自动打开原生聊天客户端。双击 `Remove DeskDrop Autostart.desktop` 可取消两端的自动启动。本机信任配置保存在当前用户的 `~/.config/deskdrop/receiver.env` 中。

登录自启适用于常见的 systemd Linux 桌面。如果你的发行版没有 systemd 用户服务，可继续用 `Start DeskDrop.desktop` 手动启动接收端。

## 开发与配置

需要 Node.js 18 或更高版本。启动开发服务器：

```bash
npm start
```

可通过环境变量调整配置：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `PORT` | `8787` | 监听端口 |
| `HOST` | `0.0.0.0` | 监听地址 |
| `DESKDROP_DIR` | 项目内 `received/` | 接收文件保存目录 |
| `TRANSFER_PIN` | 每次启动随机生成 | 固定 PIN，需为 4–12 位数字 |
| `MAX_FILE_SIZE` | `1073741824` | 单个文件大小上限，单位字节 |
| `DESKDROP_STATE_DIR` | `~/.local/state/deskdrop` | 登录会话、聊天记录状态目录 |
| `DESKDROP_TRUSTED_CLIENTS` | 空 | 允许免 PIN 访问的固定 IPv4 地址或 CIDR，逗号分隔 |

DeskDrop 使用 Node.js 内置模块，不需要安装 npm 依赖。

## 安全说明

配置 `DESKDROP_TRUSTED_CLIENTS` 后，PIN 登录关闭，接收端只允许本机和信任列表中的固定 IP 使用聊天 API。DeskDrop 使用 HTTP，适合可信任的局域网；请勿将端口直接暴露到互联网或不可信网络。

## License

MIT
