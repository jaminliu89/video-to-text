"""packaging/launcher.py — .app 入口

打包成 macOS .app 后，程序被放在只读目录（/Applications 或挂载的 DMG）里，
不能往自身目录写 cache/output，也读不到项目根的 .env。
这里做四件事，然后交给 gui.py：

1. 把 stdout/stderr 落到 ~/Library/.../app.log（窗口模式没有终端，不落盘就等于没有日志）
2. 把 CACHE_DIR / OUTPUT_DIR 指到 ~/Library/Application Support/VideoToText
3. 把随包的 ffmpeg/ffprobe 指给 v2t.ffmpeg（通过 FFMPEG_BIN / FFPROBE_BIN）
4. 静态 import gui 并调用 gui.run_app()（静态 import 才能让 PyInstaller 分析依赖）

另外两件"分发才需要"的事：

- 读随包的 NATIVE_DEFAULT 决定默认用浏览器还是原生窗口（同一个 launcher 服务两个包）
- V2T_SELFTEST=1 时只做依赖自检就退出：冻结后的 App 里依赖图对不对，
  是这类打包最容易翻车的地方，得有个不依赖图形界面就能跑的判据
"""

import multiprocessing
import os
import sys
import time
from pathlib import Path

APP_NAME = "VideoToText"


def resource_dir() -> Path:
    """PyInstaller 解包目录；源码运行时是项目根"""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def user_dir() -> Path:
    return Path.home() / "Library" / "Application Support" / APP_NAME


def flag_path(base: Path) -> Path | None:
    """找随包的 NATIVE_DEFAULT

    .app 里 _MEIPASS 指向 Contents/Frameworks，而数据文件被 PyInstaller 放在
    Contents/Resources（VERSION 也在那儿）。两个位置都探一下，省得下次升级
    PyInstaller 换了布局又静默降级成浏览器模式。
    """
    cands = [base / "NATIVE_DEFAULT"]
    if getattr(sys, "frozen", False):
        contents = Path(sys.executable).parent.parent
        cands += [
            contents / "Resources" / "NATIVE_DEFAULT",
            contents / "Frameworks" / "NATIVE_DEFAULT",
        ]
    for cand in cands:
        if cand.is_file():
            return cand
    return None


def native_default(base: Path) -> bool:
    """这个包默认开不开原生窗口（源码运行时没有标记文件 → False）"""
    path = flag_path(base)
    if path is None:
        return False
    try:
        return path.read_text(encoding="utf-8").strip() == "1"
    except OSError:
        return False


def selftest(base: Path) -> int:
    """只验证"冻结后的依赖图是否完整"，不启动服务、不需要图形界面

    PyInstaller 最常见的失败不是代码写错，而是依赖没被打进去：进程起来了、
    窗口没出现、日志里一行 ModuleNotFoundError。这个模式让 CI 能在没有
    WindowServer 的机器上也给出确定结论。
    """
    native = native_default(base)
    print(f"[selftest] frozen={bool(getattr(sys, 'frozen', False))} "
          f"variant={'native' if native else 'browser'}")

    # NATIVE_DEFAULT 和 VERSION 都由 PyInstaller 放进同一个 Resources 目录
    flag = flag_path(base)
    version_file = flag.parent / "VERSION" if flag else None
    if version_file and version_file.is_file():
        print(f"[selftest] version={version_file.read_text(encoding='utf-8').strip()}")

    has_webview = False
    try:
        import webview  # noqa: F401
        has_webview = True
        print("[selftest] webview=ok")
    except Exception as exc:  # noqa: BLE001 — 缺依赖就是缺依赖，什么异常都要报出来
        print(f"[selftest] webview=missing（{type(exc).__name__}: {exc}）")

    if has_webview:
        try:
            import AppKit  # noqa: F401
            import Foundation  # noqa: F401
            import WebKit  # noqa: F401
            import objc
            from PyObjCTools import AppHelper  # noqa: F401
            print(f"[selftest] pyobjc={getattr(objc, '__version__', '?')}")
        except Exception as exc:  # noqa: BLE001
            print(f"[selftest] pyobjc 导入失败：{type(exc).__name__}: {exc}")
            return 1

    bindir = base / "bin"
    for tool in ("ffmpeg", "ffprobe"):
        cand = bindir / tool
        print(f"[selftest] {tool}={'ok' if cand.exists() else 'missing'}")

    if native != has_webview:
        print(f"[selftest] ✗ 变体与依赖不一致："
              f"variant={'native' if native else 'browser'} 但 webview "
              f"{'在' if has_webview else '不在'}包里")
        return 1

    print("[selftest] OK")
    return 0


def setup_logging(home: Path) -> Path:
    """把 stdout/stderr 重定向到 ~/Library/.../app.log

    .app 是窗口模式（console=False），双击启动时没有终端。启动失败、端口被占、
    模型下载报错这些信息会全部消失，用户只看到一个打不开的图标。落盘才有得查。
    """
    log_path = home / "app.log"
    try:
        # 只留一份上一版，避免日志无限长
        if log_path.exists() and log_path.stat().st_size > 4 * 1024 * 1024:
            log_path.replace(home / "app.log.1")
    except OSError:
        pass
    fh = open(log_path, "a", buffering=1, encoding="utf-8", errors="replace")
    # dup2 到 1/2：连 uvicorn / PyInstaller 这种直接写 fd 的输出也一并抓住
    os.dup2(fh.fileno(), 1)
    os.dup2(fh.fileno(), 2)
    sys.stdout = sys.stderr = fh
    print(f"\n=== {APP_NAME} 启动 {time.strftime('%Y-%m-%d %H:%M:%S')} pid={os.getpid()} ===")
    return log_path


def main() -> None:
    base = resource_dir()

    # 自检要在 setup_logging 之前：这时候 stdout 还是终端，CI 才抓得到
    if os.environ.get("V2T_SELFTEST") == "1":
        sys.exit(selftest(base))

    home = user_dir()

    for sub in ("cache", "output"):
        (home / sub).mkdir(parents=True, exist_ok=True)

    setup_logging(home)

    # 配置/输出一律放可写目录；环境变量优先级低于 .env，但 .app 里通常没有 .env
    os.environ.setdefault("VIDEOTOTEXT_HOME", str(home))
    os.environ.setdefault("CACHE_DIR", str(home / "cache"))
    os.environ.setdefault("OUTPUT_DIR", str(home / "output"))

    # NiceGUI 的 storage 目录（.nicegui）是相对 cwd 建的；
    # 从 Finder 启动时 cwd 是 "/"，不可写，必须先切到用户目录
    os.chdir(home)

    # 这个包默认用哪种界面，由打包时写进 Resources 的 NATIVE_DEFAULT 决定。
    # 用 setdefault：显式设了 V2T_NATIVE=1/0 的人（比如 verify_dmg.sh 的冒烟）优先。
    native = native_default(base)
    os.environ.setdefault("V2T_NATIVE", "1" if native else "0")
    if not native:
        # 浏览器版双击 .app 要自己打开浏览器：gui.py 读这个开关
        os.environ.setdefault("V2T_SHOW", "1")
    print(f"[launcher] 界面模式：{'原生窗口' if native else '浏览器'}")

    # 随包 ffmpeg（静态二进制），找不到就退回系统 PATH
    bindir = base / "bin"
    for tool in ("ffmpeg", "ffprobe"):
        cand = bindir / tool
        if cand.exists():
            os.environ.setdefault(f"{tool.upper()}_BIN", str(cand))

    sys.path.insert(0, str(base))

    # 必须是静态 import：PyInstaller 靠分析 import 图来决定打哪些依赖。
    # 之前用 runpy 按路径执行 gui.py，依赖图是空的，打包后必然 ModuleNotFoundError。
    # 放在 main() 里（而不是文件顶部）是为了保证上面的环境变量先生效。
    import gui

    print(f"[launcher] 调用 gui.run_app()，ffmpeg={os.environ.get('FFMPEG_BIN')}")
    gui.run_app()
    print("[launcher] run_app() 已返回（正常不该看到这行）")


if __name__ == "__main__":
    # 必须是第一条语句，而且必须存在。
    #
    # 冻结后的 App 里，multiprocessing 的辅助进程是拿 sys.executable 重新执行本程序的：
    #   VideoToText -B -S -I -c "from multiprocessing.resource_tracker import main;main(20)"
    #   VideoToText --multiprocessing-fork fd=3 ...
    # PyInstaller 的运行时钩子把 freeze_support() 替换成能识别这两种命令行的版本：认出来就
    # exec 那一小段代码然后退出。不调用它，bootloader 只会把它当成"又一次正常启动"——
    # 于是子进程里又创建一个 tracker、又启动一个 App、又创建 tracker……无限自我复制，
    # 几十个进程同时抢 8766 端口，日志里刷满 address already in use。
    multiprocessing.freeze_support()
    main()
