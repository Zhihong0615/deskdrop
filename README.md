# DeskDrop

DeskDrop 是一个自托管的局域网文件传输小工具。让工位电脑运行接收端，笔记本在浏览器里打开它的地址，就能发送文档、图片和其他文件。文件只保存在接收电脑，不经过云端。

## 一键启动

把整个项目文件夹放到两台 Linux 电脑上。在每台电脑上首次运行一次：

```bash
bash install-desktop-launcher.sh
```

这会为当前用户安装 GNOME 应用菜单启动项。工位电脑在“显示应用程序”中搜索 **DeskDrop** 启动接收端；也可以运行 `bash install-desktop-launcher.sh --pin-dock` 将图标固定到 Dock。笔记本搜索 **Send to DeskDrop** 启动发送端。桌面文件夹中的快捷方式也会转到这些已安装的应用项。

启动接收端后会弹出终端窗口并打开接收页面，终端会显示局域网地址和 PIN。传输期间请保持该窗口打开。若移动了项目文件夹，请重新运行安装脚本更新启动项。

首次在接收端启动时，如果电脑还没有 Node.js 18 或更新版本，启动器会从 Node.js 官网下载便携版运行环境到当前用户目录，不需要管理员权限。首次准备需要联网；之后可以离线启动。Linux 首次准备需要 `curl` 和 `tar`，它们通常已预装。

## 从笔记本发送文件

1. 确认两台电脑连接到同一个局域网或 Wi-Fi。
2. 在工位电脑启动接收端。在笔记本第一次点击 `Send to DeskDrop.desktop` 时，填入终端显示的 **Local network** 地址，例如 `http://192.168.1.20:8787`。若局域网启用了 mDNS，也可以试终端显示的 `http://主机名.local:8787`。
3. 在笔记本浏览器中输入工位电脑显示的 PIN。登录状态会在本机保存 7 天；之后点发送图标即可直接进入。
4. 拖放文件或点击“浏览电脑选择文件”。发送完成后，文件会出现在工位电脑的“已接收”列表中。

接收电脑上的文件保存在项目目录的 `received/` 文件夹。默认单个文件最大 1 GB。Linux 防火墙如果拦截连接，请允许本地网络访问 DeskDrop 的 8787 端口。

## 登录后自动启动

在工位电脑双击 `Install Receiver Autostart.desktop`，按提示设置固定 PIN。DeskDrop 会安装为当前用户的 systemd 服务，在登录后自动启动；不需要打开终端或浏览器。查看状态和接收端地址：

```bash
systemctl --user status deskdrop.service
journalctl --user -u deskdrop.service -n 30 --no-pager
```

在笔记本双击 `Install Sender Autostart.desktop`，输入一次工位电脑地址。之后每次登录 Linux 桌面时，会自动打开发送页面。双击 `Remove DeskDrop Autostart.desktop` 可取消两端的自动启动。接收 PIN、发送端地址和已登录会话分别保存在当前用户的 `~/.config/deskdrop/` 与 `~/.local/state/deskdrop/` 中，权限只对当前用户开放。

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
| `DESKDROP_STATE_DIR` | `~/.local/state/deskdrop` | 登录会话状态目录 |

DeskDrop 使用 Node.js 内置模块，不需要安装 npm 依赖。

## 安全说明

PIN 用于限制同一局域网内的访问。DeskDrop 默认使用 HTTP，因此适合可信任的家庭或办公局域网；请勿将端口直接暴露到互联网或不可信网络。浏览器的已登录会话会在接收电脑重启后保留，最长 7 天；服务会话文件只允许当前 Linux 用户读取。

## License

MIT
