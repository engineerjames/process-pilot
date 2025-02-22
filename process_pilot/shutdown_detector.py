import signal
import sys
import threading


class ShutdownDetector:
    def __init__(self) -> None:
        self._stop_event = threading.Event()
        self._detector_thread: threading.Thread | None = None

    def _detect_shutdown_linux(self) -> None:
        def signal_handler(signum, frame) -> None:
            self._stop_event.set()

        # Set up process signal handlers
        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)

        try:
            import dbus
            from dbus.mainloop.glib import DBusGMainLoop
            from gi.repository import GLib
        except ImportError:
            # Fallback to process signals only if D-Bus is not available
            self._stop_event.wait()
            return

        DBusGMainLoop(set_as_default=True)
        bus = dbus.SystemBus()

        def shutdown_handler(*args, **kwargs) -> None:
            self._stop_event.set()

        # Listen for shutdown/reboot signals
        bus.add_signal_receiver(
            shutdown_handler, "PrepareForShutdown", "org.freedesktop.login1.Manager", "org.freedesktop.login1"
        )

        # Listen for suspend/hibernate signals
        bus.add_signal_receiver(
            shutdown_handler, "PrepareForSleep", "org.freedesktop.login1.Manager", "org.freedesktop.login1"
        )

        # Start GLib main loop
        loop = GLib.MainLoop()

        def run_loop() -> None:
            loop.run()

        loop_thread = threading.Thread(target=run_loop, daemon=True)
        loop_thread.start()

        # Wait for either signal
        self._stop_event.wait()
        loop.quit()

    def _detect_shutdown_windows(self) -> None:
        if sys.platform != "win32":
            msg = "This method is only supported on Windows."
            raise RuntimeError(msg)

        import win32api  # type: ignore[import-untyped]
        import win32con  # type: ignore[import-untyped]

        def handler(ctrl_type: int) -> bool:
            if ctrl_type in (
                win32con.CTRL_SHUTDOWN_EVENT,
                win32con.CTRL_LOGOFF_EVENT,
            ):
                self._stop_event.set()
                return True
            return False

        win32api.SetConsoleCtrlHandler(handler, True)
        self._stop_event.wait()

    def _detect_shutdown_darwin(self) -> None:
        def signal_handler(signum, frame) -> None:
            self._stop_event.set()

        # Set up process signal handlers
        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)

        try:
            from Foundation import NSDate, NSRunLoop  # type: ignore[import-untyped]
            from SystemConfiguration import (  # type: ignore[import-untyped]
                SCDynamicStoreCreate,
                SCDynamicStoreCreateRunLoopSource,
                SCDynamicStoreSetNotificationKeys,
            )
        except ImportError as e:
            # Fallback to process signals only if PyObjC is not available
            print(f"Warning: PyObjC not available, falling back to signal handling: {e}")
            self._stop_event.wait()
            return

        def callback(store, keys, info):
            # This callback is called when system power state changes
            self._stop_event.set()

        # Create dynamic store and run loop source
        store = SCDynamicStoreCreate(None, "ShutdownDetector", callback, None)
        SCDynamicStoreSetNotificationKeys(
            store,
            None,  # interested in all keys
            ["State:/System/Power"],  # power management notifications
        )

        run_loop_source = SCDynamicStoreCreateRunLoopSource(None, store, 0)
        current_loop = NSRunLoop.currentRunLoop()
        current_loop.addTimer_forMode_(NSDate.distantFuture(), "kCFRunLoopDefaultMode")
        current_loop.addSource_forMode_(run_loop_source, "kCFRunLoopDefaultMode")

        # Run the event loop until stop event is set
        while not self._stop_event.is_set():
            current_loop.runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.1))

    def start(self) -> None:
        if self._detector_thread is not None:
            return

        platform = sys.platform
        if sys.platform == "linux":
            detect_method = self._detect_shutdown_linux
        elif sys.platform == "win32":
            detect_method = self._detect_shutdown_windows
        elif sys.platform == "darwin":
            detect_method = self._detect_shutdown_darwin
        else:
            raise RuntimeError(f"Unsupported platform: {platform}")

        self._detector_thread = threading.Thread(target=detect_method, daemon=True)
        self._detector_thread.start()

    def stop(self) -> None:
        if self._detector_thread is not None:
            self._stop_event.set()
            self._detector_thread.join()
            self._detector_thread = None
